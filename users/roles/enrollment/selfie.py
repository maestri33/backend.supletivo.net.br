from __future__ import annotations

from users.documents import service as documents_iface
from users.exceptions import Conflict, DomainError
from users.roles import _document_ai, _selfie
from users.roles.enrollment.models import Enrollment
from users.roles.enrollment.common import (
    EnrollmentError,
    _S,
    _require,
    _advance_to,
    logger,
)
from users.roles.enrollment.serializers import me_dict
from users.roles.enrollment import service

_SELFIE_PUBLIC_REASON = {
    "rejected": "Não conseguimos confirmar sua selfie. Envie uma nova foto, nítida e com o rosto bem visível.",
    "review": "Recebemos sua selfie e estamos confirmando. Avisamos você em instantes.",
}


def _selfie_dict(enr: Enrollment) -> dict:
    """Bloco da selfie (GET /selfie e o bloco `selfie` do /me — proposta #3)."""
    from users.roles import _analysis

    status = enr.selfie_status if enr.selfie_image else None
    return {
        "exists": bool(enr.selfie_image),
        "uploaded_at": enr.selfie_taken_at.isoformat() if enr.selfie_taken_at else None,
        "status": status,
        "analysis_status": status,
        "analysis_reason": _SELFIE_PUBLIC_REASON.get(status),
        "expires_at": (
            _analysis.expires_at(enr.selfie_taken_at).isoformat()
            if status == _analysis.PENDING and enr.selfie_taken_at
            else None
        ),
        "verified": enr.selfie_verified,
        "description": _SELFIE_PUBLIC_REASON.get(status),
        "attempts": enr.selfie_reject_count,
    }


def get_selfie(*, user_external_id: str) -> dict:
    """GET da selfie/ASSINATURA (plan/13)."""
    enr = _require(user_external_id)
    return _selfie_dict(enr)


def set_selfie(
    *,
    user_external_id: str,
    image_bytes: bytes,
    content_type: str = "image/jpeg",
    consent_ip: str | None = None,
    consent_user_agent: str | None = None,
) -> Enrollment:
    from django.utils import timezone
    from users.blocks import service as blocks
    from users.consent import STUDENT_CONTRACT
    from users.roles import _selfie
    from users.roles.enrollment.selfie_ai import _save_selfie

    enr = _require(user_external_id, _S.SELFIE)
    _require_rg_ready_for_selfie(enr)
    enr.selfie_image = _save_selfie(enr, image_bytes, content_type)
    blocks.resolve_for_source(user=enr.user, source_type="selfie")
    enr.selfie_taken_at = timezone.now()
    enr.selfie_status = _selfie.SelfieStatus.PENDING
    enr.selfie_verified = False
    enr.selfie_description = None
    enr.consent_accepted = True
    enr.contract_version = STUDENT_CONTRACT.version
    enr.contract_hash = STUDENT_CONTRACT.hash
    enr.consent_ip = consent_ip
    enr.consent_user_agent = consent_user_agent
    enr.consent_accepted_at = enr.selfie_taken_at
    enr.save()
    from django_q.tasks import async_task

    async_task("users.roles.enrollment.tasks.validate_selfie", enr.id)
    return enr


def _require_rg_ready_for_selfie(enr: Enrollment) -> None:
    """Selfie é a assinatura facial da matrícula; só destrava se o RG estiver pronto."""
    user_ext = str(enr.user.external_id)
    rg = documents_iface.get_rg(user_ext)
    if rg is None or not (rg.front_photo or rg.full_photo):
        raise Conflict(
            "Envie a foto do RG antes de tirar a selfie.",
            code="RG_REQUIRED_BEFORE_SELFIE",
        )
    if rg.validation_status == _document_ai.REJECTED:
        raise Conflict(
            "Seu RG foi recusado — regularize o documento antes da selfie.",
            code="RG_REJECTED_BEFORE_SELFIE",
        )
