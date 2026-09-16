from __future__ import annotations

import datetime
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from hub.models import Hub
from users.documents import service as documents_iface
from users.exceptions import Conflict, DomainError, Forbidden, NotFound
from users.profiles import interface as profiles
from users.roles import _analysis, _document_ai
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import (
    CandidateError,
    _S,
    _require,
    _set_status,
    _DOC_SLOT_FIELD,
    _DOC_SLOT_SIDE,
    _MIME_BY_EXT,
    _DOC_DOC_FIELDS,
    logger,
)
from users.roles.candidate import service
from users.roles.candidate.serializers import me_dict
from users.roles.candidate.promotion import _complete_candidate

def run_document_validation(candidate_id: int, slot: str) -> None:
    """Pipeline da task (plan/15 B3). Idempotente: só age com validação `pending`. Mesma
    sequência do `run_rg_validation` do enrollment:
      a) visão na foto do `slot` (é rg/cnh? lado certo? legível?) → reprovou/dúvida = notifica;
      b) seção completa (inteira aprovada OU frente+verso aprovadas) → OCR + extração (1 LLM);
      c) nome de outra pessoa → reprova; dúvida → review; ok → povoa campos VAZIOS →
         biometria → avança o wizard."""
    from pathlib import Path

    from users.roles import _document_ai as doc_ai

    cand = (
        Candidate.objects.select_related("user", "hub", "hub__coordinator")
        .filter(id=candidate_id)
        .first()
    )
    if cand is None or not cand.doc_type:
        return
    user_ext = str(cand.user.external_id)
    sub = documents_iface.get_doc_sub(user_ext, cand.doc_type)
    if sub is None or sub.validation_status != doc_ai.PENDING:
        return

    result = sub.validation_result or {}
    photos = dict(result.get("photos") or {})

    field = _DOC_SLOT_FIELD.get(slot)
    path = getattr(sub, field, None) if field else None
    if path and (photos.get(slot) or {}).get("status") != doc_ai.APPROVED:
        fp = Path(settings.MEDIA_ROOT) / path
        if not fp.exists():
            return
        mime = _MIME_BY_EXT.get(fp.suffix.lstrip(".").lower(), "image/jpeg")
        doc_ai.fix_orientation(str(fp), mime_type=mime, caller="candidate.document")
        status, reason = doc_ai.check_photo(
            fp.read_bytes(),
            side=_DOC_SLOT_SIDE[slot],
            doc_type=cand.doc_type,
            mime_type=mime,
            caller="candidate.document",
        )
        # merge FRESCO (visão 10-60s; frente+verso em 2 workers paralelos — não perder o outro)
        sub.refresh_from_db()
        if sub.validation_status != doc_ai.PENDING:
            return
        # G11: a foto deste slot trocou no meio tempo (re-upload) → o veredito é da foto velha,
        # descarta. `path` foi capturado no início; comparar com o atual identifica a troca (o
        # check de status sozinho não pega um re-upload que re-arma PENDING).
        if getattr(sub, field, None) != path:
            return
        result = sub.validation_result or {}
        photos = dict(result.get("photos") or {})
        photos[slot] = {"status": status, "reason": reason}
        result["photos"] = photos
        if status != doc_ai.APPROVED:
            service._finish_doc(cand, sub, status, reason, result)
            return

    images = _doc_approved_images(sub, photos, cand.doc_type)
    if images is None:
        sub.validation_result = result
        sub.save(update_fields=["validation_result"])
        return
    _doc_extract_and_finish(cand, sub, result, images)


def _doc_approved_images(sub, photos: dict, doc_type: str) -> list | None:
    """Imagens da seção completa e aprovada (inteira OU frente+verso), ou None se falta."""
    from pathlib import Path

    from users.roles import _document_ai as doc_ai

    prefix = f"{doc_type}_"

    def ok(slot: str) -> bool:
        return (photos.get(slot) or {}).get("status") == doc_ai.APPROVED

    full = getattr(sub, "full_photo", None)
    if full and ok(f"{prefix}full"):
        return [Path(settings.MEDIA_ROOT) / full]
    if (
        getattr(sub, "front_photo", None)
        and getattr(sub, "back_photo", None)
        and ok(f"{prefix}front")
        and ok(f"{prefix}back")
    ):
        return [
            Path(settings.MEDIA_ROOT) / sub.front_photo,
            Path(settings.MEDIA_ROOT) / sub.back_photo,
        ]
    return None


def _doc_extract_and_finish(cand: Candidate, sub, result: dict, images: list) -> None:
    """OCR + extração (1 LLM, plan/15 B3): confere o nome e povoa os campos do sub-doc + perfil."""
    from users.roles import _document_ai as doc_ai

    p = profiles.get(cand.user)
    try:
        ocr_text = doc_ai.ocr_images(
            [fp.read_bytes() for fp in images], caller="candidate.document"
        )
        data = doc_ai.extract_document(
            ocr_text,
            doc_type=cand.doc_type,
            holder_name=(p.name if p else None),
            caller="candidate.document",
        )
    except Exception as exc:  # noqa: BLE001 — IA fora do ar → review
        logger.warning(
            "candidate.doc_extract_failed",
            candidate=str(cand.external_id),
            error=str(exc)[:200],
        )
        service._finish_doc(
            cand,
            sub,
            doc_ai.REVIEW,
            "IA indisponível na extração dos dados — enviado para revisão manual do coordenador.",
            result,
        )
        return
    # guard do worker-zumbi: o OCR + extração acima levam ~15s; se NESSE meio o sweep do TTL
    # (worker lento) ou o coordenador já decidiu, NÃO sobrescrever a decisão. Mesma régua que a
    # visão aplica no re-check acima — aqui fecha a janela do estágio de extração.
    sub.refresh_from_db()
    if sub.validation_status != doc_ai.PENDING:
        return
    result["extracted"] = data
    match = str(data.get("name_match") or "").strip().lower()
    name_reason = (data.get("name_reason") or "").strip()
    if match in ("nao", "não", "no"):
        service._finish_doc(
            cand,
            sub,
            doc_ai.REJECTED,
            f"O nome no documento não confere com o do cadastro. {name_reason}".strip(),
            result,
        )
        return
    if match not in ("sim", "yes"):
        service._finish_doc(
            cand,
            sub,
            doc_ai.REVIEW,
            f"Não deu pra confirmar o nome do titular. {name_reason}".strip(),
            result,
        )
        return
    service._apply_doc_extracted(cand, sub, data)
    service._finish_doc(
        cand, sub, doc_ai.APPROVED, name_reason or "Documento validado.", result
    )
    service._notify_doc_event(
        cand=cand,
        event="candidate.document_approved",
        subject="Seu cadastro — documento aprovado",
    )  # notify também no aprovado automático (espelha plan/13)
    service._doc_post_approval(cand, sub)


def _apply_doc_extracted(cand: Candidate, sub, data: dict) -> None:
    """Povoa SÓ campos vazios (Victor: não sobrescrever). RG/CNH compartilhados por sub-doc;
    aqui o que vale é o tipo."""
    from datetime import date

    def _clean(value, limit: int):
        s = str(value).strip()
        return s[:limit] if s else None

    def _date(value):
        try:
            return date.fromisoformat(str(value)) if value else None
        except ValueError:
            return None

    sub_changed = []
    # RG-specific
    if cand.doc_type == "rg":
        if not sub.number and data.get("number"):
            sub.number = _clean(data["number"], 30)
            sub_changed.append("number")
        if not sub.issuing_agency and data.get("issuing_agency"):
            sub.issuing_agency = _clean(data["issuing_agency"], 50)
            sub_changed.append("issuing_agency")
        if not sub.issue_date:
            d = _date(data.get("issue_date"))
            if d:
                sub.issue_date = d
                sub_changed.append("issue_date")
    # CNH-specific
    elif cand.doc_type == "cnh":
        if not sub.number and data.get("number"):
            sub.number = _clean(data["number"], 30)
            sub_changed.append("number")
        if not sub.category and data.get("category"):
            sub.category = _clean(data["category"], 5)
            sub_changed.append("category")
        if not sub.national_register and data.get("national_register"):
            sub.national_register = _clean(data["national_register"], 30)
            sub_changed.append("national_register")
        if not sub.expires_on:
            d = _date(data.get("expires_on"))
            if d:
                sub.expires_on = d
                sub_changed.append("expires_on")
        if not sub.date_of_birth:
            d = _date(data.get("birth_date"))
            if d:
                sub.date_of_birth = d
                sub_changed.append("date_of_birth")
    # OBS (fix 2026-07-12): o nascimento do RG NÃO fica no sub-doc — o modelo `RG` não tem
    # `date_of_birth` (só a `CNH` tem). A data de nascimento é CENTRALIZADA no Profile logo
    # abaixo via `profiles.fill_identity(birth_date=...)` (Victor 2026-06-16: identidade mora
    # SÓ no Profile). O bloco antigo aqui acessava `sub.date_of_birth` p/ RG e quebrava a
    # extração (AttributeError) assim que um RG passava na validação da foto.
    if sub_changed:
        sub.save(update_fields=sub_changed)

    # filiação/naturalidade + nascimento extraídos do documento → CENTRALIZADO no Profile
    # (Victor 2026-06-16: a identidade mora SÓ no Profile, nunca espalhada no candidate).
    profiles.fill_identity(
        cand.user,
        mother_name=_clean(data["mother_name"], 255)
        if data.get("mother_name")
        else None,
        father_name=_clean(data["father_name"], 255)
        if data.get("father_name")
        else None,
        birthplace=_clean(data["birthplace"], 128) if data.get("birthplace") else None,
        birth_date=_date(data.get("birth_date")),
    )
    # G8/#19: o OCR pode ter acabado de preencher o `number` que faltava — re-avalia o avanço
    # DOCUMENTS→PIX. Guarded (só avança com doc aprovado + number), idempotente nos callsites de
    # validação que já chamam _advance_documents depois. Sem isso, o candidato ficava preso em
    # DOCUMENTS após a aprovação manual quando o número só veio pelo OCR.
    _advance_documents(cand, str(cand.user.external_id))


def _finish_doc(
    cand: Candidate, sub, status: str, reason: str | None, result: dict
) -> None:
    """Grava o veredito (justificativa SEMPRE — plan/9) + dispara o notify do estado."""
    from django.utils import timezone

    from users.roles import _document_ai as doc_ai

    result["reason"] = reason
    sub.validation_status = status
    sub.validation_result = result
    sub.validated_at = timezone.now()
    sub.save(update_fields=["validation_status", "validation_result", "validated_at"])
    logger.info(
        "candidate.doc_validated",
        candidate=str(cand.external_id),
        doc_type=cand.doc_type,
        status=status,
    )
    if status == doc_ai.REJECTED:
        service._notify_doc_event(cand=cand, event="candidate.document_rejected", detail=reason)
    elif status == doc_ai.REVIEW:
        service._notify_doc_event(
            cand=cand, event="candidate.document_in_review", detail=reason
        )


def _doc_post_approval(cand: Candidate, sub) -> None:
    """Aprovado → AVANÇA o wizard PRIMEIRO, biometria best-effort DEPOIS: um crash da biometria
    (InsightFace/onnxruntime pode matar o worker) NÃO pode perder o avanço do wizard (Victor 2026-06-16)."""
    # o doc já está aprovado + com número → avança documents→pix ANTES de tocar na biometria.
    _advance_documents(cand, str(cand.user.external_id))
    service._complete_candidate(cand)

    from pathlib import Path

    from integrations.tools.biometric import service as biometric

    face_path = sub.front_photo or sub.full_photo
    face_slot = f"{cand.doc_type}_front"
    if face_path:
        full = Path(settings.MEDIA_ROOT) / face_path
        biometric.try_enroll_document(
            user=cand.user,
            slot=face_slot,
            image_path=str(full),
            caller="candidate.document",
        )


def run_document_fill(candidate_id: int) -> None:
    """Pós-aprovação do coordenador: OCR+extração best-effort SÓ pra preencher campos vazios.
    A aprovação humana é FINAL — aqui não há veto (o `name_match` fica só registrado)."""
    from users.roles import _document_ai as doc_ai

    cand = (
        Candidate.objects.select_related("user", "hub").filter(id=candidate_id).first()
    )
    if cand is None or not cand.doc_type:
        return
    user_ext = str(cand.user.external_id)
    sub = documents_iface.get_doc_sub(user_ext, cand.doc_type)
    if sub is None or sub.validation_status != doc_ai.APPROVED:
        return
    # já tem extração? só repopula o que ficou faltando
    result = sub.validation_result or {}
    if result.get("extracted"):
        _apply_doc_extracted(cand, sub, result["extracted"])
        return
    # sem extração anterior: roda OCR+extração best-effort
    images = _doc_approved_images(sub, result.get("photos") or {}, cand.doc_type)
    if not images:
        return
    p = profiles.get(cand.user)
    try:
        ocr_text = doc_ai.ocr_images(
            [fp.read_bytes() for fp in images], caller="candidate.document_fill"
        )
        data = doc_ai.extract_document(
            ocr_text,
            doc_type=cand.doc_type,
            holder_name=(p.name if p else None),
            caller="candidate.document_fill",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; falha = aluno digita
        logger.warning(
            "candidate.doc_fill_failed",
            candidate=str(cand.external_id),
            error=str(exc)[:200],
        )
        return
    result["extracted"] = data
    sub.validation_result = result
    sub.save(update_fields=["validation_result"])
    service._apply_doc_extracted(cand, sub, data)


