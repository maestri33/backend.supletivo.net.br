from __future__ import annotations

import datetime
from django.conf import settings
from django.utils import timezone

from users.documents import service as documents_iface
from users.exceptions import Conflict, Forbidden
from users.profiles import interface as profiles
from users.roles import _document_ai
from users.roles.enrollment.models import Enrollment
from users.roles.enrollment.common import (
    EnrollmentError,
    _S,
    _require,
    logger,
)
from users.roles.enrollment.serializers import me_dict
from users.roles.enrollment import service


def decide_rg(
    *,
    enrollment_external_id: str,
    coordinator,
    approve: bool,
    reason: str | None = None,
) -> dict:
    """Coordenador do hub decide o RG em REVISÃO (sim/não). A decisão humana é FINAL sobre a
    validade: aprovou → avisa o aluno + biometria + extração best-effort preenche os campos
    (sem veto); reprovou → volta pro aluno refazer (com o motivo)."""
    from users.roles import _document_ai as doc_ai

    enr = _enrollment_for_coordinator(enrollment_external_id, coordinator)
    rg = documents_iface.get_rg(str(enr.user.external_id))
    if rg is None or rg.validation_status != doc_ai.REVIEW:
        raise EnrollmentError(
            "O RG não está em revisão.",
            code="RG_NOT_IN_REVIEW",
            extra={"rg_validation_status": rg.validation_status if rg else "missing"},
        )
    note = (reason or "").strip() or (
        "aprovado pelo coordenador" if approve else "reprovado pelo coordenador"
    )
    result = rg.validation_result or {}
    result["human"] = {
        "approve": approve,
        "reason": note,
        "by": str(coordinator.external_id),
    }
    if not approve:
        _finish_rg(enr, rg, doc_ai.REJECTED, note, result)
        return {
            "external_id": str(enr.external_id),
            "status": enr.status,
            "rg_validation_status": rg.validation_status,
        }
    # aprovação humana: as fotos presentes valem como aprovadas (fica registrado por foto)
    photos = dict(result.get("photos") or {})
    for slot, field in _RG_SLOT_FIELD.items():
        if getattr(rg, field, None):
            photos[slot] = {"status": doc_ai.APPROVED, "reason": note}
    result["photos"] = photos
    _finish_rg(enr, rg, doc_ai.APPROVED, note, result)
    _notify_rg_approved(enr)
    if result.get("extracted"):
        # a revisão veio da dúvida de NOME — extração já existe, povoa agora
        _apply_rg_extracted(enr, rg, result["extracted"])
    else:
        # a revisão veio da visão/IA fora do ar — extração roda best-effort em 2º plano
        from django_q.tasks import async_task

        async_task("users.roles.enrollment.tasks.fill_rg_data", enr.id)
    _rg_post_approval(enr, rg)
    return {
        "external_id": str(enr.external_id),
        "status": enr.status,
        "rg_validation_status": rg.validation_status,
    }


def _resume_link() -> str:
    """Deep-link de re-entrada no wizard (proposta #11): FRONTEND_URL + ENROLLMENT_RESUME_PATH.
    Sem front configurado → vazio (a mensagem sai sem o link)."""
    from users.roles.lead.config import frontend_url

    base = frontend_url().rstrip("/")
    if not base:
        return ""
    return base + getattr(settings, "ENROLLMENT_RESUME_PATH", "/matricula")


def _notify_resolution(enr: Enrollment, event_key: str, **placeholders) -> None:
    """Entrega ao notify-server o evento e os dados necessários para renderização."""
    from notify.interface.events import send_event

    p = profiles.get(enr.user)
    ctx = dict(placeholders)
    if event_key != "enrollment.selfie_approved" and (link := _resume_link()):
        ctx["link"] = link
    try:
        send_event(
            event_key,
            profile=p,
            ctx=ctx,
            subject="Sua matrícula — atualização",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "enrollment.notify_resolution_failed", event=event_key, error=str(exc)
        )


def _notify_rg_rejected(enr: Enrollment, reason: str | None) -> None:
    _notify_resolution(enr, "enrollment.rg_rejected", detail=(reason or "").strip())


def _notify_rg_review(enr: Enrollment, reason: str | None) -> None:
    # wave-2: send_event lê teor/canais/is_tts do Template no DB. WhatsApp-only (coordenador).
    from notify.interface.events import send_event

    coord = enr.hub.coordinator
    if coord is None:
        return
    cp = profiles.get(coord)
    try:
        send_event(
            "enrollment.rg_in_review",
            profile=cp,
            ctx={"detail": (reason or "").strip()},
            channels_override=("whatsapp",),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_rg_review_failed", error=str(exc))


def _notify_rg_approved(enr: Enrollment) -> None:
    _notify_resolution(enr, "enrollment.rg_approved")

