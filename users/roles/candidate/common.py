from __future__ import annotations

import structlog
from users.auth.models import User
from users.exceptions import Conflict, DomainError, NotFound
from users.roles.candidate.models import Candidate

logger = structlog.get_logger()

_S = Candidate.Status
_SELFIE_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_COLLABORATOR_ROLES = ("coordinator", "promoter", "training", "candidate")

_ADDRESS_FIELDS = ("zipcode", "street", "number", "neighborhood", "city", "state")
_PROFILE_FIELDS = (
    "mother_name",
    "father_name",
    "birthplace",
    "marital_status",
    "nationality",
)
_EDU_LEVELS = ("fundamental", "medio", "superior")
_EDU_QUALIFICATIONS = ("graduacao", "pos_graduacao", "mestrado", "doutorado")


class CandidateError(DomainError):
    """Erro de borda do candidate (não encontrado, etapa fora de ordem, Pix inválida)."""
    status = 422


def get_for_user_external_id(user_external_id: str) -> Candidate | None:
    return (
        Candidate.objects.filter(user__external_id=user_external_id)
        .select_related("hub", "user")
        .first()
    )


def _require(user_external_id: str, *allowed_status) -> Candidate:
    cand = get_for_user_external_id(user_external_id)
    if cand is None:
        raise NotFound("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if allowed_status and cand.status not in allowed_status:
        raise Conflict(
            "Seu cadastro está em outra etapa.",
            code="WRONG_STATUS",
            extra={"expected_status": cand.status},
        )
    return cand


def _set_status(cand: Candidate, to_status: str) -> None:
    cand.status = to_status
    cand.save(update_fields=["status", "updated_at"])


_DOC_SLOT_FIELD = {
    "rg_front": "front_photo",
    "rg_back": "back_photo",
    "rg_full": "full_photo",
    "cnh_front": "front_photo",
    "cnh_back": "back_photo",
    "cnh_full": "full_photo",
}
_DOC_SLOT_SIDE = {
    "rg_front": "front",
    "rg_back": "back",
    "rg_full": "full",
    "cnh_front": "front",
    "cnh_back": "back",
    "cnh_full": "full",
}
_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
_DOC_DOC_FIELDS = (
    "number",
    "issuing_agency",
    "issue_date",
    "category",
    "national_register",
    "date_of_birth",
)
