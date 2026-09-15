"""Lógica do training (LMS) — agora a TRAVA pós-promotor (Victor 2026-06-16).

Não há mais entrevista/Trainee. O candidato vira **promotor** quando o coordenador o aprova
(`candidate.approve_candidate`). Aí entra o treino:

- `on_became_promoter(user)`: atribui as matérias FIXAS ativas (`MaterialAssignment` pending) e, se
  houver alguma obrigatória pendente, dá a role overlay `training` (trava). Devolve `locked`.
- `publish_transitory(material)`: o staff publica uma matéria transitória → atribui só aos promotores
  JÁ existentes + re-trava + notifica.
- `submit`/`apply_grade`: a IA corrige; aprovou → marca a `MaterialAssignment` approved → re-checa a
  trava (zerou as obrigatórias → tira a role `training` + notifica "painel liberado").
- `coordinator_approve_material`: o coordenador aprova uma matéria EM ABERTO (sem submissão).

A trava é lida do banco (assignments pending obrigatórias) e exposta no `/promoter/me` — NÃO depende
do JWT (a role overlay não dá bump de token; o promotor não leva OTP ao travar/destravar).
"""

from __future__ import annotations

from decimal import Decimal

import structlog
from django.db import transaction
from django.utils import timezone

from users.blocks import service as blocks
from users.exceptions import Conflict, DomainError, Forbidden, NotFound
from users.roles import interface as roles
from users.roles.training.config import pass_score
from users.roles.training.models import Material, MaterialAssignment, Submission

logger = structlog.get_logger()

_TRAINING_ROLE = "training"


class TrainingError(DomainError):
    """Erro de borda do training (matéria/atribuição não encontrada, etapa fora de ordem, gate).

    É `DomainError` (422): o handler central da API converte em JSON `{detail, code, …extra}`."""

    status = 422


# ── autoria de matéria (staff + coordenador) ────────────────────────────────


def create_material(
    *,
    title,
    question,
    expected_answer,
    text_content="",
    content_blocks=None,
    order=0,
    kind=Material.Kind.FIXED,
    blocking=True,
    ephemeral=False,
    video=None,
    photo=None,
) -> Material:
    """Cria uma matéria. `kind` fixa (todo promotor novo recebe) ou transitória (publicar p/ existentes).
    `blocking` = obrigatória (trava o painel). `content_blocks` = conteúdo rico (texto/imagem/etc)."""
    if kind not in Material.Kind.values:
        raise TrainingError("Tipo de matéria inválido.", code="INVALID_MATERIAL_KIND")
    return Material.objects.create(
        title=title,
        text_content=text_content or "",
        content_blocks=content_blocks or [],
        question=question,
        expected_answer=expected_answer,
        video=video,
        photo=photo,
        kind=kind,
        blocking=bool(blocking),
        ephemeral=bool(ephemeral),
        order=order,
        active=True,
    )


def _material(external_id: str) -> Material:
    m = Material.objects.filter(external_id=external_id).first()
    if m is None:
        raise NotFound("Matéria não encontrada.", code="MATERIAL_NOT_FOUND")
    return m


def update_material(external_id: str, **fields) -> Material:
    m = _material(external_id)
    allowed = {
        "title",
        "text_content",
        "content_blocks",
        "question",
        "expected_answer",
        "order",
        "active",
        "video",
        "photo",
        "kind",
        "blocking",
        "ephemeral",
    }
    for key, value in fields.items():
        if key in allowed and value is not None:
            setattr(m, key, value)
    m.save()
    return m


_VIDEO_EXT = {
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/quicktime": "mov",
    "video/x-msvideo": "avi",
}


def set_material_video(external_id: str, *, data: bytes, content_type: str) -> Material:
    """Staff sobe o VÍDEO da matéria (1 por matéria) → salva em media/training/ e grava o path.

    Substitui o vídeo anterior (campo único `Material.video`). Path NÃO-enumerável (token aleatório),
    igual aos demais writers de mídia (core.media). Formato não suportado → 422 `INVALID_VIDEO_TYPE`."""
    from core.media import save_media

    m = _material(external_id)
    ext = _VIDEO_EXT.get(content_type)
    if ext is None:
        raise TrainingError(
            "Formato de vídeo não suportado (use mp4/webm/mov).",
            code="INVALID_VIDEO_TYPE",
        )
    m.video = save_media(prefix="training", data=data, ext=ext)
    m.save(update_fields=["video", "updated_at"])
    logger.info("training.material_video_set", external_id=external_id)
    return m


def delete_material(external_id: str) -> None:
    """Descarta uma matéria EFÊMERA (descartável). Não-efêmera → use `active=False` (preserva histórico)."""
    m = _material(external_id)
    if not m.ephemeral:
        raise TrainingError(
            "Só matérias efêmeras podem ser deletadas; desative as demais (active=False).",
            code="MATERIAL_NOT_EPHEMERAL",
        )
    m.delete()
    logger.info("training.material_deleted", external_id=external_id)


def list_materials(*, active_only: bool = True) -> list[Material]:
    qs = Material.objects.all()
    if active_only:
        qs = qs.filter(active=True)
    return list(qs.order_by("order", "id"))


def material_to_dict(m: Material, *, include_answer: bool = False) -> dict:
    data = {
        "external_id": str(m.external_id),
        "title": m.title,
        "text_content": m.text_content,
        "content_blocks": m.content_blocks or [],
        "question": m.question,
        "video": m.video,
        "photo": m.photo,
        "kind": m.kind,
        "blocking": m.blocking,
        "ephemeral": m.ephemeral,
        "order": m.order,
        "active": m.active,
    }
    if include_answer:  # só pra autoria (staff/coordenador), nunca pro promotor
        data["expected_answer"] = m.expected_answer
    return data


# ── atribuição + trava (o coração do modelo novo) ───────────────────────────


def _assignment(user, material) -> MaterialAssignment | None:
    return MaterialAssignment.objects.filter(user=user, material=material).first()


def assign_material(user, material) -> MaterialAssignment:
    """Cria a atribuição (pending) de uma matéria a um colaborador. Idempotente."""
    existing = _assignment(user, material)
    if existing is not None:
        return existing
    return MaterialAssignment.objects.create(user=user, material=material)


def pending_blocking_count(user) -> int:
    """Quantas matérias OBRIGATÓRIAS (blocking, ativas) ainda dependem do promotor = a trava.

    Aula JÁ RESPONDIDA e esperando correção NÃO conta: quem respondeu fez a parte dele e segue
    pro painel — a IA corrige em segundo plano (protótipo: `analise` não trava, só `open`).
    Se a correção reprovar, a submissão vira `rejected` e a aula volta a travar sozinha."""
    return (
        MaterialAssignment.objects.filter(
            user=user,
            status=MaterialAssignment.Status.PENDING,
            material__blocking=True,
            material__active=True,
        )
        .exclude(
            material__submissions__user=user,
            material__submissions__status=Submission.Status.PENDING,
        )
        .count()
    )


def is_locked(user) -> bool:
    """True se o promotor está TRAVADO (tem matéria obrigatória pendente). Lido do banco (não do JWT)."""
    return pending_blocking_count(user) > 0


def pending_materials(user) -> list[dict]:
    """Matérias ainda PENDENTES do user (pro `/promoter/me`: o front sabe o que falta)."""
    qs = (
        MaterialAssignment.objects.filter(
            user=user,
            status=MaterialAssignment.Status.PENDING,
            material__active=True,
        )
        .select_related("material")
        .order_by("material__order", "material__id")
    )
    return [
        {
            "material_external_id": str(a.material.external_id),
            "title": a.material.title,
            "blocking": a.material.blocking,
            "kind": a.material.kind,
        }
        for a in qs
    ]


def assigned_materials(
    user_external_id: str, *, include_content: bool = True
) -> list[dict]:
    """Matérias ATRIBUÍDAS ao colaborador (não todas as ativas) + status + última submissão.

    É o que o promotor em treino vê (`GET /training/materials`): conteúdo da matéria (sem gabarito) +
    se já passou. Só as atribuídas a ELE (fixas do onboarding + transitórias publicadas pra ele)."""
    from users.auth.models import User

    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    qs = (
        MaterialAssignment.objects.filter(user=user, material__active=True)
        .select_related("material")
        .order_by("material__order", "material__id")
    )
    assignments = list(qs)
    if not assignments:
        return []

    submissions = (
        Submission.objects.filter(
            user=user, material__in=[a.material for a in assignments]
        ).order_by("-created_at", "-id")
    )
    latest_submissions = {}
    for sub in submissions:
        if sub.material_id not in latest_submissions:
            latest_submissions[sub.material_id] = sub

    out = []
    for a in assignments:
        last = latest_submissions.get(a.material_id)
        item = {
            "material_external_id": str(a.material.external_id),
            "title": a.material.title,
            "blocking": a.material.blocking,
            "kind": a.material.kind,
            "assignment_status": a.status,
            "submission_status": last.status if last else "not_started",
            "grade": str(last.grade) if last and last.grade is not None else None,
            "justification": last.justification if last else None,
        }
        if include_content:
            item["text_content"] = a.material.text_content
            item["content_blocks"] = a.material.content_blocks or []
            item["question"] = a.material.question
            item["video"] = a.material.video
            item["photo"] = a.material.photo
        out.append(item)
    return out


def progress(user_external_id: str) -> list[dict]:
    """Resumo de status por matéria atribuída (sem o conteúdo). Atalho do `assigned_materials`."""
    return assigned_materials(user_external_id, include_content=False)


def on_became_promoter(user) -> bool:
    """Chamado quando o candidato vira promotor: atribui as matérias FIXAS ativas e, se houver
    obrigatória pendente, dá a role overlay `training` (trava). Devolve `locked` (pro caller notificar)."""
    with transaction.atomic():
        for material in Material.objects.filter(active=True, kind=Material.Kind.FIXED):
            assign_material(user, material)
        locked = is_locked(user)
        if locked and _TRAINING_ROLE not in roles.active_roles(user):
            roles.grant(user, _TRAINING_ROLE)  # overlay, sem bump de token
    return locked


def publish_transitory(material_external_id: str) -> dict:
    """Staff PUBLICA uma matéria transitória → atribui só aos PROMOTORES JÁ existentes + re-trava +
    notifica. Matérias fixas NÃO usam isto (são atribuídas no promote de cada novo promotor)."""
    material = _material(material_external_id)
    if material.kind != Material.Kind.TRANSITORY:
        raise TrainingError(
            "Só matérias transitórias são publicadas; as fixas já entram em cada novo promotor.",
            code="MATERIAL_NOT_TRANSITORY",
        )
    if not material.active:
        raise TrainingError("Matéria inativa.", code="MATERIAL_INACTIVE")
    promoters = roles.users_with_role("promoter")
    assigned = 0
    for user in promoters:
        if _assignment(user, material) is not None:
            continue
        with transaction.atomic():
            assign_material(user, material)
            if material.blocking and _TRAINING_ROLE not in roles.active_roles(user):
                roles.grant(user, _TRAINING_ROLE)
        assigned += 1
        if material.blocking:
            _notify_new_material(user, str(material.external_id))
    logger.info(
        "training.published",
        external_id=str(material.external_id),
        assigned=assigned,
    )
    return {"external_id": str(material.external_id), "assigned": assigned}


def _mark_assignment_approved(user, material, *, decided_by=None) -> None:
    """Marca a atribuição (user, material) como approved + re-checa a trava — ATÔMICO: a role overlay
    `training` e a contagem de pendências ficam em lockstep (nunca role órfã). Idempotente."""
    with transaction.atomic():
        a = _assignment(user, material)
        if a is None:
            # matéria não atribuída a este user (ex.: respondeu uma opcional não atribuída) → nada a fechar
            return
        if a.status != MaterialAssignment.Status.APPROVED:
            a.status = MaterialAssignment.Status.APPROVED
            a.decided_by = decided_by
            a.approved_at = timezone.now()
            a.save(update_fields=["status", "decided_by", "approved_at", "updated_at"])
        _recheck_lock(user, trigger=material)


def _recheck_lock(user, *, trigger=None) -> None:
    """Se NÃO há mais matéria obrigatória pendente → tira a role overlay `training` + notifica liberado.
    `trigger` = a matéria que fechou a trava (entra na chave de idempotência estável do notify)."""
    if is_locked(user):
        return
    if _TRAINING_ROLE in roles.active_roles(user):
        roles.revoke(user, _TRAINING_ROLE)  # overlay, sem bump
        _notify_cleared(user, trigger)


# ── submissão (autenticado, role promoter) ──────────────────────────────────


def _check_can_submit(user_external_id: str, material_external_id: str):
    """Guards comuns às submissões (texto e áudio). Devolve (user, material)."""
    from users.auth.models import User

    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    material = _material(material_external_id)
    if not material.active:
        raise TrainingError("Matéria inativa.", code="MATERIAL_INACTIVE")
    if _assignment(user, material) is None:
        raise TrainingError(
            "Esta matéria não está atribuída a você.", code="MATERIAL_NOT_ASSIGNED"
        )
    # bloqueia 2ª pending na mesma matéria (não gasta IA em dobro)
    if Submission.objects.filter(
        user=user, material=material, status=Submission.Status.PENDING
    ).exists():
        raise Conflict(
            "Já existe uma resposta em correção para esta matéria.",
            code="ALREADY_GRADING",
        )
    return user, material


def _queue_grade(sub: Submission) -> None:
    def _queue():
        from django_q.tasks import async_task

        async_task("users.roles.training.tasks.grade_submission", sub.id)

    transaction.on_commit(_queue)


def submit(
    *, user_external_id: str, material_external_id: str, answer: str
) -> Submission:
    user, material = _check_can_submit(user_external_id, material_external_id)
    sub = Submission.objects.create(
        user=user, material=material, answer=answer, status=Submission.Status.PENDING
    )
    # ponytail: re-submissão resolve o bloco imediatamente
    blocks.resolve_for_source(user=user, source_type=f"training_{material.id}")
    _queue_grade(sub)
    logger.info("training.submitted", external_id=str(sub.external_id))
    return sub


# MIME de áudio aceito na resposta falada → extensão salva (espelha o _VIDEO_EXT da matéria).
_AUDIO_EXT = {
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


def submit_audio(
    *, user_external_id: str, material_external_id: str, data: bytes, content_type: str
) -> Submission:
    """Resposta em ÁUDIO: salva o arquivo e cria a submissão com `answer=""` — a task de correção
    transcreve (ai.transcribe) e corrige na sequência. Mesmos guards do texto (ALREADY_GRADING etc.)."""
    from django.conf import settings

    from core.media import save_media

    ext = _AUDIO_EXT.get((content_type or "").split(";")[0].strip().lower())
    if ext is None:
        raise TrainingError(
            "Formato de áudio não suportado (use mp3/m4a/aac/ogg/webm/wav).",
            code="INVALID_AUDIO_TYPE",
        )
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise TrainingError(
            f"Áudio maior que {settings.MAX_UPLOAD_MB} MB.", code="AUDIO_TOO_LARGE"
        )
    user, material = _check_can_submit(user_external_id, material_external_id)
    path = save_media(prefix="training/audio", data=data, ext=ext)
    sub = Submission.objects.create(
        user=user,
        material=material,
        answer="",
        audio=path,
        status=Submission.Status.PENDING,
    )
    _queue_grade(sub)
    logger.info(
        "training.submitted_audio", external_id=str(sub.external_id), bytes=len(data)
    )
    return sub


def submission_to_dict(s: Submission) -> dict:
    return {
        "external_id": str(s.external_id),
        "material_external_id": str(s.material.external_id),
        "grade": str(s.grade) if s.grade is not None else None,
        "justification": s.justification,
        "audio": s.audio,
        "status": s.status,
    }


# ── correção (chamada pela task Django-Q após a IA) ─────────────────────────


def apply_grade(submission_id: int, grade_value, justification: str) -> None:
    sub = (
        Submission.objects.select_related("material", "user")
        .filter(id=submission_id)
        .first()
    )
    if sub is None or sub.status != Submission.Status.PENDING:
        return  # idempotente (re-grade não re-aplica)
    sub.grade = Decimal(str(grade_value))
    sub.justification = justification
    sub.status = (
        Submission.Status.APPROVED
        if sub.grade >= pass_score()
        else Submission.Status.REJECTED
    )
    sub.save(update_fields=["grade", "justification", "status", "updated_at"])
    logger.info(
        "training.graded",
        external_id=str(sub.external_id),
        grade=str(sub.grade),
        status=sub.status,
    )
    if sub.status == Submission.Status.APPROVED:
        _mark_assignment_approved(sub.user, sub.material)
    else:
        # ponytail: signal post_save do Submission cria o bloco automaticamente.
        # Notify explícito no WhatsApp — fail-open (signal não cobre notify).
        try:
            from notify.interface.events import send_event

            send_event(
                "training.submission_rejected",
                user=sub.user,
                subject=f"Atividade rejeitada: {sub.material.title}",
                body_md_override=(justification or "")[:400],
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "training.notify_failed",
                submission=str(sub.external_id),
                material=str(sub.material.external_id),
            )


# ── aprovar matéria EM ABERTO (coordenador, grupo leadership) ───────────────


def coordinator_approve_material(
    *, promoter_external_id: str, material_external_id: str, coordinator
) -> dict:
    """Coordenador aprova uma matéria EM ABERTO de um promotor preso (sem submissão) — destrava quem
    não tem prática digital (Victor 2026-06-16). Gate: ser o coordenador do polo do promotor."""
    from users.auth.models import User
    from users.roles.promoter.models import Promoter

    user = User.objects.filter(external_id=promoter_external_id).first()
    if user is None:
        raise NotFound("Promotor não encontrado.", code="PROMOTER_NOT_FOUND")
    promoter = Promoter.objects.filter(user=user).select_related("hub").first()
    if promoter is None:
        raise NotFound("Promotor não encontrado.", code="PROMOTER_NOT_FOUND")
    if promoter.hub.coordinator_id != coordinator.id:
        raise Forbidden(
            "Você não coordena o polo deste promotor.", code="NOT_HUB_COORDINATOR"
        )
    material = _material(material_external_id)
    if _assignment(user, material) is None:
        raise TrainingError(
            "Esta matéria não está atribuída a este promotor.",
            code="MATERIAL_NOT_ASSIGNED",
        )
    _mark_assignment_approved(user, material, decided_by=coordinator)
    logger.info(
        "training.material_approved_by_coordinator",
        promoter=promoter_external_id,
        material=material_external_id,
    )
    return {
        "promoter_external_id": promoter_external_id,
        "material_external_id": material_external_id,
        "locked": is_locked(user),
    }


def list_locked_promoters_for_hub(*, hub) -> list[dict]:
    """Promotores do polo TRAVADOS (com matéria obrigatória pendente) — pro inbox do coordenador
    (`/reviews`): ele pode aprovar a matéria em aberto de quem não tem prática digital."""
    from users.profiles import interface as profiles
    from users.roles.promoter.models import Promoter

    out = []
    promoters = (
        Promoter.objects.filter(hub=hub).select_related("user").order_by("created_at")
    )
    for promoter in promoters:
        pending = pending_materials(promoter.user)
        if not any(p["blocking"] for p in pending):
            continue
        p = profiles.get(promoter.user)
        out.append(
            {
                "promoter_external_id": str(promoter.user.external_id),
                "name": p.name if p else None,
                "pending_materials": pending,
            }
        )
    return out


# ── notify ───────────────────────────────────────────────────────────────────


def _notify(user, event: str, *, key: str, tts: bool = False) -> None:
    # Migração 2026-07-02: send_event lê teor/canais/is_tts do Template no DB. O arg `tts` ficou só
    # pra compat dos callers (_notify_cleared passa tts=True) — a fonte de verdade agora é o DB.
    from notify.interface.events import send_event
    from users.profiles import interface as profiles

    p = profiles.get(user)
    try:
        send_event(event, profile=p, idempotency_key=key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("training.notify_failed", notify_event=event, error=str(exc))


def _notify_cleared(user, trigger=None) -> None:
    # chave estável POR matéria que fechou a trava: cada liberação distinta tem chave própria (o dedup
    # do notify é permanente — uma chave só por user suprimiria liberações de ciclos futuros).
    suffix = str(trigger.external_id) if trigger is not None else "all"
    _notify(
        user,
        "training.cleared",  # painel liberado = momento especial (voz)
        key=f"training_cleared_{user.external_id}_{suffix}",
        tts=True,
    )


def _notify_new_material(user, material_external_id: str) -> None:
    _notify(
        user,
        "training.new_material",
        key=f"training_new_material_{user.external_id}_{material_external_id}",
    )
