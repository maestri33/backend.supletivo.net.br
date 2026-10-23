from __future__ import annotations

import structlog
from django.db import transaction

from users.documents import service as documents_iface
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import _S, _set_status, logger
from users.roles.candidate.common import CandidateError


def _activation_missing(cand: Candidate) -> list[str]:
    from users.address import interface as addresses
    from users.roles import _address_proof, _document_ai, _selfie
    p = profiles.get(cand.user)
    missing = [field for field in ("cpf", "phone", "name", "birth_date") if not p or not getattr(p, field, None)]
    if not p or not addresses.is_complete(p.address):
        missing.append("address")
    if not p or not p.education_level or p.education_completed is None:
        missing.append("education")
    if not cand.pix_validated or not p or not p.pix_key:
        missing.append("pix")
    if not cand.consent_accepted or not cand.consent_accepted_at:
        missing.append("consent")
    if not cand.selfie_verified or cand.selfie_status != _selfie.APPROVED:
        missing.append("selfie")
    user_ext = str(cand.user.external_id)
    document = documents_iface.get_doc_sub(user_ext, cand.doc_type) if cand.doc_type else None
    if not document or document.validation_status != _document_ai.APPROVED:
        missing.append("document")
    proof = documents_iface.get_address_proof(user_ext)
    if not proof or proof.validation_status != _address_proof.APPROVED:
        missing.append("address_proof")
    return missing


def _notify_became_promoter(cand: Candidate, *, locked: bool) -> None:
    """Avisa o candidato que virou promotor (plan/15 C). Sem TTS; Template no DB."""
    from notify.interface.events import send_event

    p = profiles.get(cand.user)
    event = "promoter.activated"
    try:
        send_event(
            event,
            profile=p,
            body_md_override="Seu cadastro foi aprovado e você está ativo como promotor. Seus repasses seguem o fechamento de sexta-feira às 18h. Acompanhe seu saldo no aplicativo.",
            idempotency_key=f"candidate_approved_{cand.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_approved_failed", error=str(exc))


def _promote_to_promoter(cand: Candidate) -> bool:
    """Activate the complete approved registration without a training gate."""
    from users.auth.models import User
    from users.roles.promoter import service as promoter_iface
    from users.roles.training import service as training_iface

    with transaction.atomic():
        User.objects.select_for_update().get(pk=cand.user_id)
        cand = Candidate.objects.select_for_update().get(pk=cand.pk)
        if cand.status == _S.APPROVED:
            return False
        missing = _activation_missing(cand)
        if missing:
            raise CandidateError("Seu cadastro ainda possui requisitos pendentes.", code="CANDIDATE_INCOMPLETE", extra={"missing_requirements": missing})
        if "promoter" not in roles.active_roles(cand.user):
            roles.promote(cand.user, "promoter")
        promoter_iface.create_promoter(user=cand.user, hub=cand.hub)
        _set_status(cand, _S.APPROVED)
        locked = training_iface.on_became_promoter(cand.user)
        transaction.on_commit(lambda: _notify_became_promoter(cand, locked=locked))
    logger.info("candidate.approved", external_id=str(cand.external_id), locked=locked)
    return locked


def _complete_candidate(cand: Candidate) -> None:
    """Promove depois da selfie, sem prender as telas durante as análises assíncronas."""
    from users.roles.candidate import service

    if cand.status not in (_S.SELFIE, _S.COMPLETED):
        return
    if not cand.selfie_verified:
        return
    if _activation_missing(cand):
        if cand.status == _S.SELFIE:
            _set_status(cand, _S.COMPLETED)
        return
    service._promote_to_promoter(cand)
