from __future__ import annotations
from django.core.exceptions import ObjectDoesNotExist

import structlog
from users.exceptions import Conflict, DomainError, NotFound
from users.roles.enrollment.models import EducationalData, Enrollment

logger = structlog.get_logger()
_S = Enrollment.Status

_ADDRESS_FIELDS = ("zipcode", "street", "number", "neighborhood", "city", "state")
_PROFILE_FIELDS = (
    "name",
    "birth_date",
    "mother_name",
    "father_name",
    "birthplace",
    "marital_status",
    "nationality",
)
_EDUCATION_FIELDS = (
    "education_level",
    "education_completed",
    "education_grade",
    "education_last_completed_grade",
    "education_qualification",
    "education_last_completed_qualification",
    "education_status",
    "education_year",
    "education_city",
    "education_school",
)
_SELFIE_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}



class EnrollmentError(DomainError):
    """Erro de domínio da matrícula."""
    status = 422


def get_by_external_id(external_id: str) -> Enrollment | None:
    return (
        Enrollment.objects.filter(external_id=external_id)
        .select_related("hub", "promoter", "user")
        .first()
    )


def get_for_user_external_id(user_external_id: str) -> Enrollment | None:
    return (
        Enrollment.objects.filter(user__external_id=user_external_id)
        .select_related("hub", "promoter", "user")
        .first()
    )


def _require(user_external_id: str, *allowed_status) -> Enrollment:
    enr = get_for_user_external_id(user_external_id)
    if enr is None:
        raise NotFound("Matrícula não encontrada.", code="ENROLLMENT_NOT_FOUND")
    if allowed_status and enr.status not in allowed_status:
        raise Conflict(
            "Sua matrícula está em outra etapa.",
            code="WRONG_STATUS",
            extra={"expected_status": enr.status},
        )
    return enr


def _set_status(enr: Enrollment, to_status: str) -> None:
    enr.status = to_status
    enr.save(update_fields=["status", "updated_at"])


def _has_education(enr: Enrollment) -> bool:
    try:
        return getattr(enr, "educational_data", None) is not None
    except (EducationalData.DoesNotExist, ObjectDoesNotExist, AttributeError):
        return False


def _advance_to(enr: Enrollment, target: str) -> None:
    from users.address import interface as address_iface
    user_ext = str(enr.user.external_id)
    status = target
    while True:
        from users.roles.enrollment import service as es_module
        addr_checker = getattr(es_module, 'address_iface', address_iface)
        if status == _S.ADDRESS and addr_checker.is_complete(
            address_iface.get_by_external_id(user_ext)
        ):
            status = _S.EDUCATION
            continue
        if status == _S.EDUCATION and _has_education(enr):
            status = _S.SELFIE
            continue
        break
    from_status = enr.status
    from users.roles.enrollment import service as es_module
    status_setter = getattr(es_module, '_set_status', _set_status)
    status_setter(enr, status)
    if from_status != status:
        logger.info(
            "enrollment.advanced",
            enrollment=str(getattr(enr, "external_id", None)),
            from_status=from_status,
            to_status=status,
        )


def public_status(enr: Enrollment) -> str:
    if enr.status in (_S.FEE_PAID, _S.FEE_SCHEDULED):
        return _S.AWAITING_RELEASE
    return enr.status

_RG_DOC_FIELDS = ("number", "issuing_agency", "issue_date")
_RG_PROFILE_FIELDS = (
    "mother_name",
    "father_name",
    "birthplace",
    "marital_status",
    "nationality",
)
_RG_SLOT_FIELD = {
    "rg_front": "front_photo",
    "rg_back": "back_photo",
    "rg_full": "full_photo",
}
_RG_SLOT_SIDE = {"rg_front": "front", "rg_back": "back", "rg_full": "full"}
