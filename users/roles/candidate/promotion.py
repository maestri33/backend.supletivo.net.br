from __future__ import annotations

import structlog
from django.db import transaction

from users.documents import service as documents_iface
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import _S, _set_status, logger


def _notify_became_promoter(cand: Candidate, *, locked: bool) -> None:
    """Avisa o candidato que virou promotor (plan/15 C). Sem TTS; Template no DB."""
    from notify.interface.events import send_event

    p = profiles.get(cand.user)
    try:
        send_event(
            "candidate.approved",
            profile=p,
            idempotency_key=f"candidate_approved_{cand.external_id}",
            locked=locked,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_approved_failed", error=str(exc))


def _promote_to_promoter(cand: Candidate) -> bool:
    """Promove candidate→PROMOTOR: cria Promoter + atribui matérias FIXAS do treino."""
    from users.roles.promoter import service as promoter_iface
    from users.roles.training import service as training_iface

    with transaction.atomic():
        if "promoter" not in roles.active_roles(cand.user):
            roles.promote(cand.user, "promoter")
        promoter_iface.create_promoter(user=cand.user, hub=cand.hub)
        _set_status(cand, _S.APPROVED)
        locked = training_iface.on_became_promoter(cand.user)
    _notify_became_promoter(cand, locked=locked)
    logger.info("candidate.approved", external_id=str(cand.external_id), locked=locked)
    return locked


def _complete_candidate(cand: Candidate) -> None:
    """Promove depois da selfie, sem prender as telas durante as análises assíncronas."""
    from users.roles import _address_proof, _document_ai, _selfie
    from users.roles.candidate import service

    if cand.status not in (_S.SELFIE, _S.COMPLETED):
        return
    selfie_allowed = cand.selfie_verified or (
        cand.selfie_reject_count >= _selfie.MAX_REJECTS_BEFORE_MEETING
    )
    if not selfie_allowed:
        return
    user_ext = str(cand.user.external_id)
    document = (
        documents_iface.get_doc_sub(user_ext, cand.doc_type) if cand.doc_type else None
    )
    proof = documents_iface.get_address_proof(user_ext)
    checks_ready = bool(
        document
        and document.validation_status == _document_ai.APPROVED
        and proof
        and proof.validation_status == _address_proof.APPROVED
    )
    if not checks_ready:
        if cand.status == _S.SELFIE:
            _set_status(cand, _S.COMPLETED)
        return
    service._promote_to_promoter(cand)
