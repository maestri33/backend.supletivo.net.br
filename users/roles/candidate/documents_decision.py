from __future__ import annotations

import datetime
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from hub.models import Hub
from users.documents import service as documents_iface
from users.exceptions import Conflict, Forbidden, NotFound
from users.profiles import interface as profiles
from users.roles import _document_ai
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import (
    CandidateError,
    _S,
    _require,
    _DOC_SLOT_FIELD,
    logger,
)
from users.roles.candidate import service

def decide_document(
    *,
    candidate_external_id: str,
    coordinator,
    approve: bool,
    reason: str | None = None,
) -> dict:
    """Coordenador do hub decide o documento do candidato em REVISÃO. Espelha `decide_rg`."""
    from users.roles import _document_ai as doc_ai

    cand = (
        Candidate.objects.filter(external_id=candidate_external_id)
        .select_related("hub", "user")
        .first()
    )
    if cand is None:
        raise CandidateError("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if cand.hub.coordinator_id != coordinator.id:
        raise CandidateError(
            "Você não coordena o polo deste candidato.", code="NOT_HUB_COORDINATOR"
        )
    if not cand.doc_type:
        raise CandidateError("Documento ainda não enviado.", code="DOC_TYPE_NOT_SET")
    sub = documents_iface.get_doc_sub(str(cand.user.external_id), cand.doc_type)
    if sub is None or sub.validation_status != doc_ai.REVIEW:
        raise CandidateError(
            "O documento não está em revisão.",
            code="DOC_NOT_IN_REVIEW",
            extra={"validation_status": sub.validation_status if sub else None},
        )
    note = (reason or "").strip() or (
        "aprovado pelo coordenador" if approve else "reprovado pelo coordenador"
    )
    result = sub.validation_result or {}
    result["human"] = {
        "approve": approve,
        "reason": note,
        "by": str(coordinator.external_id),
    }
    if not approve:
        service._finish_doc(cand, sub, doc_ai.REJECTED, note, result)
        return me_dict(cand)
    # aprovação humana: as fotos presentes valem como aprovadas
    photos = dict(result.get("photos") or {})
    for slot, field in _DOC_SLOT_FIELD.items():
        if getattr(sub, field, None):
            photos[slot] = {"status": doc_ai.APPROVED, "reason": note}
    result["photos"] = photos
    service._finish_doc(cand, sub, doc_ai.APPROVED, note, result)
    service._notify_doc_event(
        cand=cand,
        event="candidate.document_approved",
        subject="Seu cadastro — documento aprovado",
    )
    if result.get("extracted"):
        _apply_doc_extracted(cand, sub, result["extracted"])
    else:
        from django_q.tasks import async_task

        async_task("users.roles.candidate.tasks.fill_document_data", cand.id)
    service._doc_post_approval(cand, sub)
    return me_dict(cand)


def _notify_doc_event(
    *,
    cand: Candidate,
    event: str,
    detail: str | None = None,
    subject: str | None = None,
) -> None:
    """Despachante único dos notifies do documento do candidato (plan/15 B3, refator do /python-review).

    Direciona o destinatário pelo `event` configurado no notify-server:
      • `candidate.document_in_review` → coordenador do hub
      • `candidate.document_rejected` / `candidate.document_approved` → candidato

    Falha do `send` vira WARNING (a análise IA segue válida — o destinatário pode descobrir pelo
    app; o notify tem retry/canal alternativo internamente, então engolir aqui é proposital).

    wave-2: send_event lê teor/canais/is_tts do Template no DB."""
    from notify.interface.events import send_event

    if event == "candidate.document_in_review":
        coord = cand.hub.coordinator
        if coord is None:
            return
        cp = profiles.get(coord)
        target_profile = cp
        channels = ("whatsapp",)  # coordenador: WhatsApp-only (legado)
    else:
        target_profile = profiles.get(cand.user)
        channels = None  # Template decide os canais

    try:
        send_event(
            event,
            profile=target_profile,
            ctx={"detail": detail or ""},
            subject=subject,
            channels_override=channels,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "candidate.notify_doc_event_failed", doc_event=event, error=str(exc)
        )


def _sweep_stale_reviews(hub) -> None:
    from users.documents.models import CNH, RG
    from users.roles import _analysis

    _analysis.sweep_stale_selfies(Candidate, hub)
    user_ids = list(Candidate.objects.filter(hub=hub).values_list("user_id", flat=True))
    for model in (RG, CNH):
        _analysis.sweep_stale_documents(
            model.objects.filter(document__user_id__in=user_ids), _doc_started_at
        )


def list_document_reviews_for_hub(*, hub) -> list[dict]:
    """Candidatos do polo com o documento parado em REVISÃO (decisão do coordenador — plan/15 B3).
    Cada item aponta pro POST de decisão que existe. Antes, varre PENDING órfão → review."""
    from users.roles import _document_ai as doc_ai

    _sweep_stale_reviews(hub)
    out = []
    qs = (
        Candidate.objects.filter(hub=hub, doc_type__isnull=False)
        .exclude(doc_type="")
        .select_related("user")
        .order_by("updated_at")
    )
    for cand in qs:
        sub = documents_iface.get_doc_sub(str(cand.user.external_id), cand.doc_type)
        if sub is None or sub.validation_status != doc_ai.REVIEW:
            continue
        p = profiles.get(cand.user)
        out.append(
            {
                "external_id": str(cand.external_id),
                "name": p.name if p else None,
                "doc_type": cand.doc_type,
                "since": cand.updated_at.isoformat(),
            }
        )
    return out


