"""Lógica do `student`/`veteran` (§4 item 9) — o funil final do aluno (`specs/student.md`).

Fluxo (status em `Student.Status`):
  AWAITING_DOCUMENTS → (envia docs; IA valida async) → DOCUMENTS_UNDER_REVIEW
    → (todos aprovados + tipo sanguíneo) → EXAM_RELEASED
    → (aluno agenda) → EXAM_SCHEDULED → (coordenador corrige) → passou: AWAITING_DOCUMENTATION_DISPATCH
                                                                  reprovou: EXAM_FAILED → (reagenda)
    → (coordenador confere; pendência doc/taxa) ⇄ PENDING → (sem pendência) AWAITING_DIPLOMA_ISSUANCE
    → (coordenador emite) → AWAITING_PICKUP → (aluno posta foto da retirada) → VETERAN + comissão do coordenador

Cada passo é idempotente por gate de status (`_require`). A validação de documento é assíncrona
(Django-Q `tasks.validate_document` → `ai.describe_image`); best-effort: IA fora do ar / em dúvida
→ fica REVIEW (o coordenador decide; nunca auto-aprova).
A comissão da formatura usa o motor `finance` (`Source.VETERAN`, valor do `.env`), idempotente.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from users.exceptions import Conflict, DomainError, NotFound
from users.roles.student.config import (
    MALE_ONLY_DOC_TYPES,
    REQUIRED_DOC_TYPES,
)
from users.roles.student.models import (
    Student,
    StudentDiploma,
    StudentDocument,
    StudentExam,
    StudentPendency,
)

logger = structlog.get_logger()

_EXT = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}

_DOC_TYPE_ALIASES = {
    "military": StudentDocument.Type.MILITARY,
    "military_certificate": StudentDocument.Type.MILITARY,
    "reservista": StudentDocument.Type.MILITARY,
    "voter_card": StudentDocument.Type.CERTIFICATE,
    "school_history": StudentDocument.Type.TRANSCRIPT,
    "address": StudentDocument.Type.ADDRESS_PROOF,
    "identity": StudentDocument.Type.ID_CARD,
    "rg": StudentDocument.Type.ID_CARD,
    "cnh": StudentDocument.Type.ID_CARD,
    "civil_certificate": StudentDocument.Type.BIRTH_CERTIFICATE,
    "certidao": StudentDocument.Type.BIRTH_CERTIFICATE,
}


def normalize_doc_type(doc_type: str) -> str:
    return _DOC_TYPE_ALIASES.get(doc_type, doc_type)


class StudentError(DomainError):
    """Erro de borda do student (aluno não encontrado, etapa fora de ordem, gate de coordenador).

    É `DomainError` (422): o handler central da API converte em JSON `{detail, code, …extra}`."""

    status = 422


# ── criação (chamada por enrollment.release) ─────────────────────────────────


def create_from_enrollment(
    *,
    user,
    hub,
    platform_url=None,
    platform_login=None,
    platform_password=None,
    platform_notes=None,
    self_study=False,
    bolsista=False,
) -> Student:
    """Cria o `Student(AWAITING_DOCUMENTS)` na liberação da matrícula. Idempotente (1-1 com o User)."""
    existing = Student.objects.filter(user=user).first()
    if existing is not None:
        return existing
    student = Student.objects.create(
        user=user,
        hub=hub,
        self_study=self_study,
        bolsista=bolsista,
        platform_url=platform_url,
        platform_login=platform_login,
        platform_password=platform_password,
        platform_notes=platform_notes,
        status=Student.Status.AWAITING_DOCUMENTS,
    )
    logger.info("student.created", external_id=str(student.external_id))
    return student


def ensure_platform_login_available(
    *, platform_login: str | None, exclude_user_external_id: str | None = None
) -> None:
    """Login da plataforma é ÚNICO por matrícula (Victor 2026-06-23): nenhum OUTRO student usa o
    mesmo `platform_login`. Vazio/None não trava (login é opcional no model). Usado no `conclude`
    (criação) e no `set_platform_credentials` (edição do staff)."""
    if not platform_login:
        return
    qs = Student.objects.filter(platform_login=platform_login)
    if exclude_user_external_id:
        qs = qs.exclude(user__external_id=exclude_user_external_id)
    if qs.exists():
        raise Conflict(
            "Este login de plataforma já está em uso por outra matrícula.",
            code="PLATFORM_LOGIN_TAKEN",
        )


def set_platform_credentials(
    *,
    student_external_id: str,
    platform_login: str,
    platform_password: str,
    platform_url: str | None = None,
    platform_notes: str | None = None,
) -> Student:
    """Staff corrige as credenciais da plataforma de um aluno JÁ concluído (Victor 2026-06-23: SÓ
    staff altera; coordenadores não mexem depois de concluído). Login único por matrícula."""
    student = _by_external_id(student_external_id)
    ensure_platform_login_available(
        platform_login=platform_login,
        exclude_user_external_id=str(student.user.external_id),
    )
    student.platform_login = platform_login
    student.platform_password = platform_password
    if platform_url is not None:
        student.platform_url = platform_url
    if platform_notes is not None:
        student.platform_notes = platform_notes
    student.save(
        update_fields=[
            "platform_login",
            "platform_password",
            "platform_url",
            "platform_notes",
            "updated_at",
        ]
    )
    logger.info(
        "student.platform_credentials_updated", external_id=str(student.external_id)
    )
    return student


# ── consulta / helpers ───────────────────────────────────────────────────────


def _by_user(user_external_id: str) -> Student:
    student = (
        Student.objects.filter(user__external_id=user_external_id)
        .select_related("hub", "hub__coordinator", "user")
        .first()
    )
    if student is None:
        raise NotFound("Aluno não encontrado.", code="STUDENT_NOT_FOUND")
    return student


def _require(user_external_id: str, *allowed_status) -> Student:
    student = _by_user(user_external_id)
    if allowed_status and student.status not in allowed_status:
        raise Conflict(
            "Seu processo está em outra fase.",
            code="WRONG_STATUS",
            extra={"expected_status": student.status},
        )
    return student


def _by_external_id(external_id: str) -> Student:
    student = (
        Student.objects.filter(external_id=external_id)
        .select_related("hub", "hub__coordinator", "user")
        .first()
    )
    if student is None:
        raise NotFound("Aluno não encontrado.", code="STUDENT_NOT_FOUND")
    return student


def _set_status(student: Student, to_status: str) -> None:
    student.status = to_status
    student.save(update_fields=["status", "updated_at"])


def get_for_user_external_id(external_id: str) -> Student | None:
    return (
        Student.objects.filter(user__external_id=external_id)
        .select_related("hub", "user")
        .first()
    )


def reevaluate_exam_release(user) -> None:
    """G8/#5: re-avalia a liberação da prova de um student BOLSISTA quando uma indicação paga entra.

    O gate do bolsista exige >=10 indicações pagas ALÉM de docs+sangue. Se ele completa os docs com
    <10 indicações, `_maybe_release_exam` retorna cedo; e quando a 8ª/9ª/10ª indicação paga, nada
    re-avaliava → ficava preso em DOCUMENTS_UNDER_REVIEW. Chamado por `lead._apply_effects` a cada
    lead pago do promotor. No-op se o user não é student ou não é bolsista."""
    student = Student.objects.filter(user=user).select_related("user").first()
    if student is None or not student.bolsista:
        return
    _maybe_release_exam(student)


def to_dict(student: Student) -> dict:
    diploma = getattr(student, "diploma", None)
    return {
        "external_id": str(student.external_id),
        "status": student.status,
        "hub_external_id": str(student.hub.external_id),
        "blood_type": student.blood_type,
        "platform": {
            "url": student.platform_url,
            "login": student.platform_login,
            "password": student.platform_password,
            "notes": student.platform_notes,
        },
        "documents": _student_documents_dict(student),
        "pendencies": [
            {
                "external_id": str(p.external_id),
                "kind": p.kind,
                "description": p.description,
                "amount_cents": p.amount_cents,
                "resolved": p.resolved_at is not None,
            }
            for p in student.pendencies.all()
        ],
        "diploma": {
            "issued_at": diploma.issued_at.isoformat()
            if diploma and diploma.issued_at
            else None,
            "picked_up": bool(diploma and diploma.picked_up_at),
        }
        if diploma
        else None,
    }


def _student_documents_dict(student) -> list[dict]:
    """Documentos do aluno pro coordenador decidir VENDO: foto + external_id (pra endereçar o
    decide `.../documents/{doc_id}/decide`) + veredito da IA. Sem a foto/id o coordenador aprovava
    às cegas e a fila `student_documents` não tinha como decidir."""
    return [
        {
            "external_id": str(d.external_id),
            "doc_type": d.doc_type,
            "photo": d.photo,
            "validation_status": d.validation_status,
            "has_photo": bool(d.photo),
            "analysis_status": d.validation_status,
            "analysis_reason": _document_analysis_reason(d),
            "expires_at": _document_expires_at(d),
        }
        for d in student.documents.all()
    ]


def _document_analysis_reason(doc: StudentDocument) -> str | None:
    """Motivo da análise guardado no validation_result (pipeline 2 estágios)."""
    if not isinstance(doc.validation_result, dict):
        return None
    return doc.validation_result.get("reason")


def _document_expires_at(doc: StudentDocument) -> str | None:
    """TTL do pending: até quando o status `pending` vale."""
    from datetime import datetime

    from django.utils import timezone
    from users.roles import _analysis

    if doc.validation_status != StudentDocument.Validation.PENDING:
        return None
    started_raw = (doc.validation_result or {}).get("analysis_started_at")
    if not started_raw:
        return None
    if isinstance(started_raw, datetime):
        started = (
            started_raw
            if started_raw.tzinfo
            else started_raw.replace(tzinfo=timezone.utc)
        )
    else:
        try:
            started = datetime.fromisoformat(started_raw)
        except (TypeError, ValueError):
            return None
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
    exp = _analysis.expires_at(started)
    return exp.isoformat() if exp else None


# ── envio de documentos (aluno) + validação por IA (async) ───────────────────


def _gender_of(student: Student) -> str | None:
    from users.profiles import interface as profiles

    p = profiles.get(student.user)
    return p.gender if p else None


def set_blood_type(*, user_external_id: str, blood_type: str) -> Student:
    student = _require(
        user_external_id,
        Student.Status.AWAITING_DOCUMENTS,
        Student.Status.DOCUMENTS_UNDER_REVIEW,
    )
    valid = {c for c, _ in Student.BloodType.choices}
    if blood_type not in valid:
        raise StudentError("Tipo sanguíneo inválido.", code="INVALID_BLOOD_TYPE")
    student.blood_type = blood_type
    student.save(update_fields=["blood_type", "updated_at"])
    return student


def _save_photo(
    student: Student, doc_type: str, image_bytes: bytes, content_type: str
) -> str:
    from core.media import save_media

    ext = _EXT.get(content_type, "jpg")
    return save_media(prefix="student", data=image_bytes, ext=ext)


# diploma/histórico aceitam PDF além de imagem (o coordenador sobe o documento emitido).
_DOC_EXT = {**_EXT, "application/pdf": "pdf"}


def _save_doc_file(student: Student, kind: str, data: bytes, content_type: str) -> str:
    """Salva um arquivo do diploma (PDF ou imagem) em media/diploma/ com token não-enumerável."""
    from core.media import save_media

    ext = _DOC_EXT.get(content_type, "pdf")
    return save_media(prefix="diploma", data=data, ext=ext)


def upload_document(
    *, user_external_id: str, doc_type: str, image_bytes: bytes, content_type: str
) -> tuple[StudentDocument, dict]:
    """Aluno envia a foto de um documento → fica PENDING e dispara a validação por IA (async).

    Retorna (documento, ack) para a API devolver `analysis_status`, `poll_after_ms` e `expires_at`."""
    from django.utils import timezone

    from users.roles import _analysis

    student = _require(
        user_external_id,
        Student.Status.AWAITING_DOCUMENTS,
        Student.Status.DOCUMENTS_UNDER_REVIEW,
    )
    doc_type = normalize_doc_type(doc_type)
    valid_types = {c for c, _ in StudentDocument.Type.choices}
    if doc_type not in valid_types:
        raise StudentError("Tipo de documento inválido.", code="INVALID_DOC_TYPE")
    # militar só de homens (gate de gênero — igual o `documents` do enrollment).
    if doc_type in MALE_ONLY_DOC_TYPES and _gender_of(student) != "M":
        raise StudentError(
            "Documento de serviço militar só para homens.", code="MILITARY_MALE_ONLY"
        )
    # não deixa um re-post derrubar um doc JÁ APROVADO de volta pra PENDING (reentrância: o aluno
    # clica 2× / retry de rede). Re-upload só é aceito enquanto PENDING (em análise) ou REJECTED.
    existing = StudentDocument.objects.filter(
        student=student, doc_type=doc_type
    ).first()
    if existing and existing.validation_status == StudentDocument.Validation.APPROVED:
        raise StudentError(
            "Documento já aprovado — não precisa reenviar.", code="ALREADY_APPROVED"
        )

    rel = _save_photo(student, doc_type, image_bytes, content_type)
    started_at = timezone.now()
    doc, _ = StudentDocument.objects.update_or_create(
        student=student,
        doc_type=doc_type,
        defaults={
            "photo": rel,
            "validation_status": StudentDocument.Validation.PENDING,
            "validation_result": {"analysis_started_at": started_at.isoformat()},
            "validated_at": None,
        },
    )
    if student.status == Student.Status.AWAITING_DOCUMENTS:
        _set_status(student, Student.Status.DOCUMENTS_UNDER_REVIEW)

    def _queue():
        from django_q.tasks import async_task

        async_task("users.roles.student.tasks.validate_document", doc.id)

    transaction.on_commit(_queue)
    logger.info(
        "student.document_uploaded",
        external_id=str(doc.external_id),
        doc_type=doc_type,
    )
    return doc, _analysis.ack(_analysis.PENDING, started_at)


def _ai_validate(
    doc: StudentDocument,
) -> tuple[str, dict | None]:
    """Pipeline 2 estágios de IA para 1 foto de documento do aluno.

    (a) Visão: a foto é o documento esperado e está legível?
    (b) Se aprovado, OCR + extração JSON: lê campos relevantes e confere identidade.

    Retorna (validation_status, payload). O payload grava `vision` (status+motivo),
    `ocr` (texto bruto), `extracted` (JSON) e `reason` (motivo final). Best-effort sem foto
    → ('pending', None). IA fora do ar/ambígua → REVIEW (coordenador decide; nunca auto-aprova).

    Confere a IDENTIDADE: passa o nome do CPFHub (Profile); se o documento for de outra pessoa,
    a IA reprova de imediato (Victor 2026-06-05)."""
    from users.profiles import interface as profiles
    from users.roles.student import _document_ai as doc_ai

    fp = Path(settings.MEDIA_ROOT) / (doc.photo or "")
    if not doc.photo or not fp.exists():
        return StudentDocument.Validation.PENDING, None

    ext = fp.suffix.lstrip(".").lower()
    mime = "image/png" if ext == "png" else "image/jpeg"
    caller = "student.document"

    p = profiles.get(doc.student.user)
    holder_name = p.name if p else None

    image_bytes = fp.read_bytes()

    # (a) Visão: foto é o documento esperado e está legível?
    vision_status, vision_reason = doc_ai.check_student_document_photo(
        image_bytes,
        doc_type=doc.doc_type,
        mime_type=mime,
        caller=caller,
    )

    result: dict = {
        "vision": {"status": vision_status, "reason": vision_reason},
    }

    # Visão reprovou → rejeita imediatamente (sem gastar OCR).
    if vision_status == doc_ai.REJECTED:
        result["reason"] = vision_reason
        return StudentDocument.Validation.REJECTED, result

    # Visão em dúvida/fora do ar → review.
    if vision_status != doc_ai.APPROVED:
        result["reason"] = vision_reason
        return StudentDocument.Validation.REVIEW, result

    # (b) OCR + extração JSON.
    try:
        ocr_text = doc_ai.ocr_image(image_bytes, caller=caller)
        extracted = doc_ai.extract_student_document(
            ocr_text,
            doc_type=doc.doc_type,
            holder_name=holder_name,
            caller=caller,
        )
    except Exception as exc:  # noqa: BLE001 — IA do ar na extração → review
        logger.warning(
            "student.doc_extract_failed",
            external_id=str(doc.external_id),
            error=str(exc),
        )
        result["reason"] = (
            "IA indisponível na extração dos dados — enviado para revisão manual do coordenador."
        )
        return StudentDocument.Validation.REVIEW, result

    result["ocr"] = ocr_text
    result["extracted"] = extracted

    match = str(extracted.get("name_match") or "").strip().lower()
    name_reason = (extracted.get("name_reason") or "").strip()

    if match in ("nao", "não", "no"):
        result["reason"] = (
            f"O nome no documento não confere com o do cadastro. {name_reason}".strip()
        )
        return StudentDocument.Validation.REJECTED, result

    if match not in ("sim", "yes"):
        result["reason"] = (
            f"Não deu pra confirmar o nome do titular. {name_reason}".strip()
        )
        return StudentDocument.Validation.REVIEW, result

    result["reason"] = name_reason or "Documento validado."
    return StudentDocument.Validation.APPROVED, result


def apply_validation(
    student_document_id: int, *, status: str, payload: dict | None
) -> None:
    """Grava o veredito da IA no documento (chamado pela task). Idempotente (só age em PENDING).

    `payload` contém `vision`, `ocr`, `extracted` e `reason` (motivo final). Mantém compat
    com o formato legado em que a chave `raw` pode vir do `validation_result` legado."""
    doc = (
        StudentDocument.objects.select_related("student")
        .filter(id=student_document_id)
        .first()
    )
    if doc is None or doc.validation_status != StudentDocument.Validation.PENDING:
        return
    if status == StudentDocument.Validation.PENDING:
        return  # sem foto — nada a aplicar
    doc.validation_status = status
    doc.validation_result = payload
    doc.validated_at = timezone.now()
    doc.save(
        update_fields=[
            "validation_status",
            "validation_result",
            "validated_at",
            "updated_at",
        ]
    )
    reason = (payload or {}).get("reason")
    logger.info(
        "student.document_validated",
        external_id=str(doc.external_id),
        status=status,
        reason=reason,
    )
    if status == StudentDocument.Validation.APPROVED:
        _maybe_release_exam(doc.student)
    elif status == StudentDocument.Validation.REJECTED:
        # documento reprovado: avisa o aluno pra reenviar (antes reprovava em silêncio).
        _notify(
            doc.student,
            event="student.document_rejected",
            key=f"student_doc_rejected_{doc.external_id}",
            doc_type=doc.get_doc_type_display(),
            reason=reason,
        )
    elif status == StudentDocument.Validation.REVIEW:
        # IA em dúvida / fora do ar → aciona o coordenador pra decidir (sim/não).
        _notify_coordinator(
            doc.student,
            event="student.document_in_review",
            key=f"student_doc_review_{doc.external_id}",
            doc_type=doc.get_doc_type_display(),
            reason=reason,
        )


def _required_doc_types_for(student: Student) -> set[str]:
    needed = set(REQUIRED_DOC_TYPES)
    if _gender_of(student) == "M":
        needed |= set(MALE_ONLY_DOC_TYPES)
    return needed


def _maybe_release_exam(student: Student) -> None:
    """Todos os docs exigidos aprovados + tipo sanguíneo informado → libera pra agendar a prova."""
    # relê do banco: a validação roda async (Django-Q) e o `blood_type`/status podem ter mudado por
    # outro request (set_blood_type) depois desta instância ser carregada — evita decisão com dado stale.
    student.refresh_from_db(fields=["status", "blood_type"])
    if student.status != Student.Status.DOCUMENTS_UNDER_REVIEW:
        return
    if not student.blood_type:
        return
    needed = _required_doc_types_for(student)
    approved = set(
        StudentDocument.objects.filter(
            student=student, validation_status=StudentDocument.Validation.APPROVED
        ).values_list("doc_type", flat=True)
    )
    if not needed.issubset(approved):
        return
    # F2: selfie reprovada 5× no cadastro → flag nível-pessoa exige encontro presencial com o
    # coordenador (que posta a foto manual) ANTES de liberar a prova. "Fim do curso" = este gate.
    from users.profiles import interface as profiles

    p = profiles.get(student.user)
    if p and p.selfie_needs_meeting:
        return
    # F4: bolsista (herdado do promotor pré-matriculado) precisa de ≥10 leads pagos, ALÉM de
    # docs+sangue (soma, não substitui). `student.user` era o promotor.
    if student.bolsista:
        # `rules` é folha (só lê lead.models): importar `promoter.service` aqui fecharia o ciclo
        # promoter -> enrollment -> student -> promoter.
        from users.roles.promoter import rules as promoter_rules

        if (
            promoter_rules.paid_referrals(student.user)
            < promoter_rules.get_bolsa_exam_threshold()
        ):
            return
    _set_status(student, Student.Status.EXAM_RELEASED)
    _notify(
        student,
        event="student.exam_released",
        key=f"student_exam_released_{student.external_id}",
    )


def decide_document(
    *,
    student_external_id: str,
    document_external_id: str,
    coordinator,
    approve: bool,
    reason: str | None = None,
) -> StudentDocument:
    """Coordenador do hub decide um documento que a IA mandou pra REVISÃO (o sim/não dele).

    aprova → APPROVED (+ pode liberar a prova); reprova → REJECTED (+ avisa o aluno pra refazer). Só age
    em documento `review` (a decisão da IA aprovado/reprovado é final; o coordenador resolve a dúvida)."""
    student = _coordinated(student_external_id, coordinator)
    doc = StudentDocument.objects.filter(
        student=student, external_id=document_external_id
    ).first()
    if doc is None:
        raise StudentError("Documento não encontrado.", code="DOCUMENT_NOT_FOUND")
    if doc.validation_status != StudentDocument.Validation.REVIEW:
        raise StudentError(
            "O documento não está em revisão.",
            code="DOC_NOT_IN_REVIEW",
            extra={"validation_status": doc.validation_status},
        )
    note = (reason or "").strip() or (
        "aprovado pelo coordenador" if approve else "reprovado pelo coordenador"
    )
    doc.validation_status = (
        StudentDocument.Validation.APPROVED
        if approve
        else StudentDocument.Validation.REJECTED
    )
    # preserva a justificativa da IA e soma a decisão humana (auditoria).
    doc.validation_result = {
        **(doc.validation_result or {}),
        "coordinator": note,
    }
    doc.validated_at = timezone.now()
    doc.save(
        update_fields=[
            "validation_status",
            "validation_result",
            "validated_at",
            "updated_at",
        ]
    )
    logger.info(
        "student.document_decided",
        external_id=str(doc.external_id),
        status=doc.validation_status,
        approve=approve,
    )
    if approve:
        _maybe_release_exam(student)
    else:
        _notify(
            student,
            event="student.document_rejected",
            key=f"student_doc_rejected_{doc.external_id}",
            doc_type=doc.get_doc_type_display(),
        )
    return doc


# ── prova (aluno agenda; coordenador corrige) ────────────────────────────────


def schedule_exam(*, user_external_id: str, subject: str, scheduled_at) -> StudentExam:
    student = _require(
        user_external_id, Student.Status.EXAM_RELEASED, Student.Status.EXAM_FAILED
    )
    if not (subject or "").strip():
        raise StudentError("Informe a matéria da prova.", code="SUBJECT_REQUIRED")
    if isinstance(scheduled_at, str):
        from django.utils.dateparse import parse_datetime

        parsed = parse_datetime(scheduled_at)
        if parsed is None:
            raise StudentError(
                "Data/hora da prova inválida.", code="INVALID_SCHEDULED_AT"
            )
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed)
        scheduled_at = parsed
    last = student.exams.order_by("-attempt_number").first()
    attempt = (last.attempt_number + 1) if last else 1
    exam = StudentExam.objects.create(
        student=student,
        subject=subject.strip()[:120],
        scheduled_at=scheduled_at,
        attempt_number=attempt,
    )
    _set_status(student, Student.Status.EXAM_SCHEDULED)
    _notify_coordinator(
        student,
        event="student.exam_scheduled",
        key=f"student_exam_scheduled_{exam.external_id}",
    )
    logger.info(
        "student.exam_scheduled", external_id=str(exam.external_id), attempt=attempt
    )
    return exam


def grade_exam(
    *, student_external_id: str, coordinator, passed: bool, notes: str | None = None
) -> StudentExam:
    """Coordenador do hub corrige a prova agendada. Passou → conferência; reprovou → refazer."""
    student = _coordinated(student_external_id, coordinator)
    if student.status != Student.Status.EXAM_SCHEDULED:
        raise Conflict(
            "Seu processo está em outra fase.",
            code="WRONG_STATUS",
            extra={"expected_status": student.status},
        )
    exam = student.exams.filter(result__isnull=True).order_by("-attempt_number").first()
    if exam is None:
        raise StudentError("Não há prova pendente de correção.", code="NO_PENDING_EXAM")
    exam.result = StudentExam.Result.PASSED if passed else StudentExam.Result.FAILED
    exam.corrected_by = coordinator
    exam.corrected_at = timezone.now()
    exam.notes = (notes or "")[:500] or None
    exam.save(
        update_fields=["result", "corrected_by", "corrected_at", "notes", "updated_at"]
    )
    if passed:
        _set_status(student, Student.Status.AWAITING_DOCUMENTATION_DISPATCH)
        _notify(
            student,
            event="student.exam_passed",
            key=f"student_exam_passed_{exam.external_id}",
        )
    else:
        _set_status(student, Student.Status.EXAM_FAILED)
        _notify(
            student,
            event="student.exam_failed",
            key=f"student_exam_failed_{exam.external_id}",
        )
    logger.info("student.exam_graded", external_id=str(exam.external_id), passed=passed)
    return exam


# ── pendências (coordenador; «conferir» = documento OU taxa) ─────────────────


def open_pendency(
    *,
    student_external_id: str,
    coordinator,
    kind: str,
    description: str,
    amount_cents: int | None = None,
) -> StudentPendency:
    """Coordenador lança pendência (documento/taxa) → aluno vai pra PENDING. Taxa NÃO move dinheiro aqui."""
    student = _coordinated(student_external_id, coordinator)
    if student.status not in (
        Student.Status.AWAITING_DOCUMENTATION_DISPATCH,
        Student.Status.PENDING,
    ):
        raise Conflict(
            "Seu processo está em outra fase.",
            code="WRONG_STATUS",
            extra={"expected_status": student.status},
        )
    valid_kinds = {c for c, _ in StudentPendency.Kind.choices}
    if kind not in valid_kinds:
        raise StudentError("Tipo de pendência inválido.", code="INVALID_KIND")
    if not (description or "").strip():
        raise StudentError(
            "Informe a descrição da pendência.", code="DESCRIPTION_REQUIRED"
        )
    pend = StudentPendency.objects.create(
        student=student,
        kind=kind,
        description=description.strip()[:500],
        amount_cents=amount_cents if kind == StudentPendency.Kind.FEE else None,
        opened_by=coordinator,
    )
    if student.status != Student.Status.PENDING:
        _set_status(student, Student.Status.PENDING)
    _notify(
        student,
        event="student.pendency_opened",
        key=f"student_pendency_{pend.external_id}",
        detail=pend.description,
    )
    logger.info("student.pendency_opened", external_id=str(pend.external_id), kind=kind)
    return pend


def resolve_pendency(*, pendency_external_id: str, coordinator) -> StudentPendency:
    """Coordenador resolve a pendência. Sem pendência aberta → volta a AWAITING_DOCUMENTATION_DISPATCH."""
    pend = (
        StudentPendency.objects.select_related("student", "student__hub")
        .filter(external_id=pendency_external_id)
        .first()
    )
    if pend is None:
        raise StudentError("Pendência não encontrada.", code="PENDENCY_NOT_FOUND")
    if pend.student.hub.coordinator_id != coordinator.id:
        raise StudentError(
            "Você não coordena o polo deste aluno.", code="NOT_HUB_COORDINATOR"
        )
    # lock no aluno: a checagem "sem pendência aberta → avança" não pode correr com um open_pendency
    # concorrente (senão o aluno avançaria com pendência aberta). select_for_update trava no Postgres.
    with transaction.atomic():
        student = Student.objects.select_for_update().get(id=pend.student_id)
        if pend.resolved_at is None:
            pend.resolved_at = timezone.now()
            pend.save(update_fields=["resolved_at", "updated_at"])
        still_open = student.pendencies.filter(resolved_at__isnull=True).exists()
        if not still_open and student.status == Student.Status.PENDING:
            _set_status(student, Student.Status.AWAITING_DOCUMENTATION_DISPATCH)
    logger.info("student.pendency_resolved", external_id=str(pend.external_id))
    return pend


def list_pendencies(
    user_external_id: str, *, open_only: bool = False
) -> list[StudentPendency]:
    student = _by_user(user_external_id)
    qs = student.pendencies.all()
    if open_only:
        qs = qs.filter(resolved_at__isnull=True)
    return list(qs.order_by("created_at"))


# ── diploma (coordenador emite) → retirada (aluno) → veteran + comissão ──────


def clear_documentation(*, student_external_id: str, coordinator) -> Student:
    """Coordenador confirma que não há pendência → libera a emissão do diploma."""
    student = _coordinated(student_external_id, coordinator)
    if student.status not in (
        Student.Status.AWAITING_DOCUMENTATION_DISPATCH,
        Student.Status.PENDING,
    ):
        raise Conflict(
            "Seu processo está em outra fase.",
            code="WRONG_STATUS",
            extra={"expected_status": student.status},
        )
    if student.pendencies.filter(resolved_at__isnull=True).exists():
        raise StudentError("Há pendências em aberto.", code="OPEN_PENDENCIES")
    _set_status(student, Student.Status.AWAITING_DIPLOMA_ISSUANCE)
    logger.info("student.documentation_cleared", external_id=str(student.external_id))
    return student


def issue_diploma(
    *,
    student_external_id: str,
    coordinator,
    diploma_bytes: bytes,
    diploma_content_type: str,
    transcript_bytes: bytes | None = None,
    transcript_content_type: str | None = None,
) -> StudentDiploma:
    """Coordenador emite o diploma: sobe o PDF/imagem do diploma (+ histórico, opcional) → aluno fica
    AGUARDANDO RETIRADA e é notificado a comparecer ao polo. TODO o fluxo é do coordenador (Victor
    2026-06-29): o aluno não posta nada."""
    student = _coordinated(student_external_id, coordinator)
    if student.status != Student.Status.AWAITING_DIPLOMA_ISSUANCE:
        raise Conflict(
            "Seu processo está em outra fase.",
            code="WRONG_STATUS",
            extra={"expected_status": student.status},
        )
    if not diploma_bytes:
        raise StudentError("Envie o arquivo do diploma.", code="DIPLOMA_FILE_REQUIRED")
    diploma_rel = _save_doc_file(
        student, "diploma", diploma_bytes, diploma_content_type
    )
    transcript_rel = None
    if transcript_bytes:
        transcript_rel = _save_doc_file(
            student, "transcript", transcript_bytes, transcript_content_type or ""
        )
    diploma, _ = StudentDiploma.objects.get_or_create(student=student)
    diploma.issued_by = coordinator
    diploma.issued_at = timezone.now()
    diploma.diploma_file = diploma_rel
    if transcript_rel:
        diploma.transcript_file = transcript_rel
    diploma.save(
        update_fields=[
            "issued_by",
            "issued_at",
            "diploma_file",
            "transcript_file",
            "updated_at",
        ]
    )
    _set_status(student, Student.Status.AWAITING_PICKUP)
    _notify(
        student,
        event="student.diploma_issued",
        key=f"student_diploma_issued_{diploma.external_id}",
    )
    _notify(
        student,
        event="student.diploma_pickup",
        key=f"student_diploma_pickup_{diploma.external_id}",
    )
    logger.info("student.diploma_issued", external_id=str(diploma.external_id))
    return diploma


def register_pickup(
    *, student_external_id: str, coordinator, image_bytes: bytes, content_type: str
) -> Student:
    """Coordenador posta a FOTO do aluno recebendo o diploma → aluno vira VETERAN + comissão do
    coordenador do polo (Victor 2026-06-29: TODO o fluxo do diploma é do coordenador; o aluno não
    posta nada).

    TUDO (retirada + role + status + comissão) numa ÚNICA transação: se a comissão não puder ser
    creditada (coordenador None/sem profile), o ROLLBACK desfaz a retirada inteira e o aluno continua
    em AWAITING_PICKUP — basta repostar quando o hub tiver coordenador válido. NUNCA vira veteran sem a
    comissão (sem perda silenciosa, sem estado inconsistente). A foto vai pro disco antes (idempotente:
    token novo a cada post; re-post grava outro arquivo e atualiza o ponteiro)."""
    student = _coordinated(student_external_id, coordinator)
    if student.status != Student.Status.AWAITING_PICKUP:
        raise Conflict(
            "Seu processo está em outra fase.",
            code="WRONG_STATUS",
            extra={"expected_status": student.status},
        )
    diploma = getattr(student, "diploma", None)
    if diploma is None:
        raise StudentError(
            "O diploma ainda não foi emitido.", code="DIPLOMA_NOT_ISSUED"
        )
    rel = _save_photo(student, "diploma_pickup", image_bytes, content_type)
    with transaction.atomic():
        diploma.pickup_photo = rel
        diploma.picked_up_at = timezone.now()
        diploma.save(update_fields=["pickup_photo", "picked_up_at", "updated_at"])
        _become_veteran(student, diploma)
    # troca de role student→veteran: notifica os DOIS envolvidos (o aluno + o coordenador da comissão).
    _notify(
        student,
        event="student.veteran",
        key=f"student_veteran_{student.external_id}",
    )
    _notify_coordinator(
        student,
        event="student.veteran.coordinator",
        key=f"student_veteran_coord_{student.external_id}",
    )
    logger.info("student.veteran", external_id=str(student.external_id))
    return student


def clear_manual_selfie(
    *, student_external_id: str, coordinator, image_bytes: bytes, content_type: str
) -> Student:
    """F2 — encontro presencial: o aluno cuja selfie reprovou 5× no cadastro chega ao fim do curso
    com `Profile.selfie_needs_meeting`. O coordenador tira a foto DELE pelo app e posta aqui como
    assinatura → a flag cai e a prova destrava (`_maybe_release_exam`). Espelha `register_pickup`."""
    from users.profiles import interface as profiles

    student = _coordinated(student_external_id, coordinator)
    _save_photo(student, "manual_selfie", image_bytes, content_type)
    profiles.set_selfie_needs_meeting(student.user, False)
    logger.info(
        "student.manual_selfie_cleared",
        external_id=str(student.external_id),
        by=str(coordinator.external_id),
    )
    _maybe_release_exam(
        student
    )  # a flag era o que segurava a liberação — reavalia agora
    return student


def _become_veteran(student: Student, diploma: StudentDiploma) -> None:
    """Adiciona a role `veteran` (mantém `student`), marca VETERAN e credita a comissão. Roda DENTRO
    da transação do `register_pickup` — se a comissão falhar, tudo é desfeito (nada de veteran sem ela)."""
    from users.roles import interface as roles

    if "veteran" not in roles.active_roles(student.user):
        roles.assign(student.user, "veteran")
    _set_status(student, Student.Status.VETERAN)
    _credit_coordinator(student, diploma)


def _credit_coordinator(student: Student, diploma: StudentDiploma) -> None:
    """Comissão flat pro coordenador do hub do aluno (Source.VETERAN). Idempotente.

    Coordenador ausente (None) ou sem profile → levanta `StudentError` (rollback do caller; retryável
    quando o hub tiver coordenador válido). NUNCA descarta a comissão em silêncio."""
    if student.self_study:
        # auto-matrícula de promotor: NÃO gera comissão pra ninguém (Victor 2026-06-16). Sai limpo
        # (sem raise) pra não desfazer a virada a veteran.
        logger.info(
            "student.veteran_self_study_no_commission",
            external_id=str(student.external_id),
        )
        return
    if diploma.commission_triggered_at is not None:
        return
    from finance.interface import commissions
    from finance.models import Commission

    coordinator = student.hub.coordinator
    if coordinator is None:
        raise StudentError(
            "O polo não tem coordenador para receber a comissão.",
            code="NO_HUB_COORDINATOR",
        )
    try:
        commissions.credit_commission(
            payee=coordinator,
            payee_role=Commission.Role.COORDINATOR,
            source_type=Commission.Source.VETERAN,
            source_external_id=student.external_id,
        )
    except (
        ValueError
    ) as exc:  # payee None/inválido (defensivo; coordinator já checado acima)
        raise StudentError(
            "Beneficiário da comissão inválido.", code="COMMISSION_PAYEE_INVALID"
        ) from exc
    diploma.commission_triggered_at = timezone.now()
    diploma.save(update_fields=["commission_triggered_at", "updated_at"])


# ── gate de coordenador + notificações ───────────────────────────────────────


def _coordinated(student_external_id: str, coordinator) -> Student:
    """Carrega o aluno e exige que `coordinator` seja o coordenador do hub dele."""
    student = _by_external_id(student_external_id)
    if student.hub.coordinator_id != coordinator.id:
        raise StudentError(
            "Você não coordena o polo deste aluno.", code="NOT_HUB_COORDINATOR"
        )
    return student


def detail_for_coordinator(*, student_external_id: str, coordinator) -> dict:
    """Detalhe RICO do student pro coordenador (gate: coordenar o hub do aluno). É o que faltava: o
    coordenador agia (grade/decide/pendency) mas não tinha um GET completo do aluno."""
    from users.profiles import interface as profiles

    student = _coordinated(student_external_id, coordinator)
    p = profiles.get(student.user)
    data = to_dict(student)
    data["self_study"] = student.self_study
    data["user"] = {
        "external_id": str(student.user.external_id),
        "name": p.name if p else None,
        "cpf": p.cpf if p else None,
        "phone": p.phone if p else None,
        "email": p.email if p else None,
    }
    return data


def veteran_detail(*, user_external_id: str) -> dict:
    """Parte STUDENT da visão do veterano (read-only): identidade, os documentos que ELE postou e o
    que o COORDENADOR postou (diploma + histórico + foto da retirada). O veterano mantém a role
    student; aqui é só leitura do estado final (não move nada).

    O bloco `enrollment` (perfil/endereço/escolaridade/RG/selfie) NÃO vem daqui: buscá-lo faria
    `student.service` importar `enrollment.service`, que já importa `student.service` no `conclude`
    (ciclo). Quem cruza os dois domínios é a rota `veteran_me` em `api/clients.py`."""
    from users.profiles import interface as profiles

    student = _by_user(user_external_id)
    data = to_dict(student)

    # dados pessoais (nome/cpf/phone/email).
    p = profiles.get(student.user)
    data["user"] = {
        "external_id": str(student.user.external_id),
        "name": p.name if p else None,
        "cpf": p.cpf if p else None,
        "phone": p.phone if p else None,
        "email": p.email if p else None,
    }

    # documentos que o ALUNO postou — com o path da foto (o to_dict só traz has_photo; o veterano
    # precisa acessar os arquivos). O front prefixa /media/.
    data["documents"] = [
        {
            "doc_type": d.doc_type,
            "validation_status": d.validation_status,
            "photo": d.photo,
            "validated_at": d.validated_at.isoformat() if d.validated_at else None,
        }
        for d in student.documents.all()
    ]

    # diploma RICO: os arquivos que o COORDENADOR postou (diploma + histórico + foto da retirada).
    # Paths relativos; o front prefixa /media/.
    diploma = getattr(student, "diploma", None)
    data["diploma"] = (
        {
            "issued_at": diploma.issued_at.isoformat() if diploma.issued_at else None,
            "picked_up_at": (
                diploma.picked_up_at.isoformat() if diploma.picked_up_at else None
            ),
            "diploma_file": diploma.diploma_file,
            "transcript_file": diploma.transcript_file,
            "pickup_photo": diploma.pickup_photo,
        }
        if diploma is not None
        else None
    )
    return data


def _notify(student: Student, *, event: str, key: str, **ctx) -> None:
    """Notifica o ALUNO. Teor/canais/is_tts/storytelling vêm do Template no DB (`send_event`):
    `student.diploma_issued` é TTS+story (voz + discurso motivacional da IA); `{nome}` do profile."""
    from notify.interface.events import send_event
    from users.profiles import interface as profiles

    p = profiles.get(student.user)
    try:
        send_event(event, profile=p, ctx=ctx or None, idempotency_key=key)
    except Exception as exc:  # noqa: BLE001 — notificação é best-effort (§12, canais isolados)
        logger.warning("student.notify_failed", caller=event, error=str(exc))


def _notify_coordinator(student: Student, *, event: str, key: str, **ctx) -> None:
    """Notifica o COORDENADOR do polo do aluno. Teor/canais do DB; `{nome}` do profile do coordenador.
    Sem coordenador ou sem profile → send_event devolve None (no-op, sem row morto)."""
    from notify.interface.events import send_event
    from users.profiles import interface as profiles

    coord = student.hub.coordinator
    if coord is None:
        return
    cp = profiles.get(coord)
    try:
        send_event(event, profile=cp, ctx=ctx or None, idempotency_key=key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("student.notify_coord_failed", caller=event, error=str(exc))


def list_for_hub(
    *, hub, status: str | None = None, limit: int = 200, offset: int = 0
) -> tuple[list[dict], int]:
    """Alunos do POLO (visão do coordenador, A2 — Victor 2026-06-21: antes o coordenador só tinha o
    detalhe /students/{id}; agora lista/busca por status). Devolve (rows, total) pra paginação."""
    from users.profiles import interface as profiles

    qs = Student.objects.filter(hub=hub).select_related("user").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    total = qs.count()
    rows = list(qs[offset : offset + limit])
    pmap = profiles.get_map([r.user for r in rows])
    out = []
    for s in rows:
        p = pmap.get(s.user_id)
        out.append(
            {
                "external_id": str(s.external_id),
                "name": p.name if p else None,
                "phone": p.phone if p else None,
                "status": s.status,
                "created_at": s.created_at.isoformat(),
            }
        )
    return out, total


def list_for_staff(*, hub_external_id=None, status=None, limit=200) -> list[dict]:
    """Alunos de TODOS os polos (ou de um, se `hub_external_id`) pro painel do staff. Read-only."""
    from users.profiles import interface as profiles

    qs = Student.objects.select_related("user", "hub").order_by("-id")
    if hub_external_id:
        qs = qs.filter(hub__external_id=hub_external_id)
    if status:
        qs = qs.filter(status=status)
    rows = list(qs[:limit])
    pmap = profiles.get_map([r.user for r in rows])
    out = []
    for s in rows:
        p = pmap.get(s.user_id)
        out.append(
            {
                "external_id": str(s.external_id),
                "status": s.status,
                "self_study": s.self_study,
                "hub_external_id": str(s.hub.external_id),
                "name": p.name if p else None,
            }
        )
    return out


def _sweep_stale_reviews(hub) -> None:
    """Resiliência (Victor 2026-06-17): worker da IA morto → documento do student fica PENDING
    calado e some da fila de todos (só db-edit destrava, o que o Victor não quer em prod). Ao
    montar a fila, PENDING que estourou o TTL VIRA `review` → aparece pro coordenador decidir."""
    from datetime import timedelta

    from users.roles import _analysis

    cutoff = timezone.now() - timedelta(seconds=_analysis.ttl_seconds())
    StudentDocument.objects.filter(
        student__hub=hub,
        validation_status=StudentDocument.Validation.PENDING,
        updated_at__lt=cutoff,
    ).update(validation_status=StudentDocument.Validation.REVIEW)


def list_document_reviews_for_hub(*, hub) -> list[dict]:
    """Documentos de students do polo parados em REVISÃO (decisão do coordenador — plan/14).

    Cada item traz o PAR (student, documento) que o POST de decisão já existente espera
    (`/students/{ext}/documents/{doc_ext}/decide`). Antes, varre PENDING órfão → review."""
    from users.profiles import interface as profiles

    _sweep_stale_reviews(hub)
    out = []
    qs = (
        StudentDocument.objects.filter(
            student__hub=hub, validation_status=StudentDocument.Validation.REVIEW
        )
        .select_related("student", "student__user")
        .order_by("updated_at")
    )
    rows = list(qs)
    pmap = profiles.get_map([doc.student.user for doc in rows])
    for doc in rows:
        p = pmap.get(doc.student.user_id)
        out.append(
            {
                "student_external_id": str(doc.student.external_id),
                "document_external_id": str(doc.external_id),
                "doc_type": doc.doc_type,
                "name": p.name if p else None,
                "since": doc.updated_at.isoformat(),
            }
        )
    return out
