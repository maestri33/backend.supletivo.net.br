from __future__ import annotations
from django.core.exceptions import ObjectDoesNotExist

from users.address import interface as address_iface
from users.blocks import service as blocks
from users.documents import service as documents_iface
from users.exceptions import NotFound
from users.profiles import interface as profiles
from users.roles import _address_proof
from users.roles.enrollment.models import EducationalData, Enrollment

def _selfie_dict(enr: Enrollment) -> dict:
    from users.roles.enrollment.selfie import _selfie_dict as sd
    return sd(enr)

def _rg_section_dict(enr: Enrollment) -> dict:
    from users.roles.enrollment.rg import _rg_section_dict as rsd
    return rsd(enr)

from users.roles.enrollment.common import (
    _S,
    _ADDRESS_FIELDS,
    _PROFILE_FIELDS,
    _EDUCATION_FIELDS,
    public_status,
    _RG_DOC_FIELDS,
    _RG_PROFILE_FIELDS,
)


def _address_dict(user_external_id: str) -> dict:
    data = address_iface.as_public_dict(
        address_iface.get_by_external_id(user_external_id)
    )
    data["missing_fields"] = [f for f in _ADDRESS_FIELDS if not data.get(f)]
    return data



def to_dict(enr: Enrollment) -> dict:
    return {
        "external_id": str(enr.external_id),
        "status": public_status(enr),
        "hub_external_id": str(enr.hub.external_id),
        "selfie_verified": enr.selfie_verified,
        "selfie_status": enr.selfie_status,
        # canônico unificado (proposta #4): a análise da SELFIE/assinatura sob o nome `analysis_status`.
        # `selfie_status` segue como alias (compat) até o front migrar.
        "analysis_status": enr.selfie_status,
    }



def me_dict(enr: Enrollment) -> dict:
    from users.roles.enrollment.rg import _reconcile_stale_analyses
    """GET /me RICO (auditoria do front 2026-06-10): o resume do wizard pré-preenche TODAS as seções
    numa chamada só. Bloco `None` = seção ainda não preenchida; `address_complete` = endereço pronto."""
    from users.roles import _address_proof

    _reconcile_stale_analyses(
        enr
    )  # TTL guard (proposta #2): pending estourado → review, aqui também
    user_ext = str(enr.user.external_id)
    p = profiles.get(enr.user)

    profile = None
    if p and any(
        (
            p.mother_name,
            p.father_name,
            p.marital_status,
            p.birthplace,
            p.nationality,
        )
    ):
        profile = {
            "mother_name": p.mother_name,
            "father_name": p.father_name,
            "marital_status": p.marital_status,
            "birthplace": p.birthplace,
            "nationality": p.nationality,
        }

    rg_data = (documents_iface.get_by_external_id(user_ext) or {}).get("rg") or {}
    rg = None
    if any(
        rg_data.get(k) for k in ("number", "front_photo", "back_photo", "full_photo")
    ):
        rg = {
            "number": rg_data.get("number"),
            "issuing_agency": rg_data.get("issuing_agency"),
            "issue_date": rg_data.get("issue_date"),
            "front_photo": rg_data.get("front_photo"),
            "back_photo": rg_data.get("back_photo"),
            "full_photo": rg_data.get("full_photo"),
            # validação IA (plan/12): o front mostra "analisando…"/motivo e o que falta digitar.
            # `analysis_status`/`analysis_reason` = nome CANÔNICO (proposta #4); os `validation_*`
            # seguem como alias (compat) até o front migrar.
            "analysis_status": rg_data.get("validation_status"),
            "analysis_reason": rg_data.get("validation_reason"),
            "validation_status": rg_data.get("validation_status"),
            "validation_reason": rg_data.get("validation_reason"),
            # MESMA régua da seção (doc + perfil) — é a lista que trava a selfie (proposta #10)
            "missing_fields": [
                *(f for f in _RG_DOC_FIELDS if not rg_data.get(f)),
                *(f for f in _RG_PROFILE_FIELDS if not getattr(p, f, None)),
            ],
        }

    try:
        edu = enr.educational_data
    except (EducationalData.DoesNotExist, ObjectDoesNotExist):
        edu = None
    education = None
    if edu is not None:
        education = {
            "level": edu.level,
            "grade": edu.grade,
            "completed": edu.completed,
            "last_school": edu.last_school,
            "city": edu.city,
            "state": edu.state,
            "last_year_when": edu.last_year_when,
        }

    address = address_iface.get_by_external_id(user_ext)
    return {
        **to_dict(enr),
        "profile": profile,
        "address_complete": address_iface.is_complete(address),
        "address": _address_dict(user_ext),
        "address_proof": _address_proof.section_dict(user_ext),
        "selfie": _selfie_dict(enr),
        "rg": rg,
        "education": education,
        # ponytail: lista de flags ativas — o front mostra modais p/ cada uma.
        "blocks": [blocks.to_dict(b) for b in blocks.get_active_blocks(enr.user)],
    }

