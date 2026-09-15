from __future__ import annotations
from django.core.exceptions import ObjectDoesNotExist

from users.profiles import interface as profiles
from users.roles.enrollment.models import EducationalData, Enrollment
from users.roles.enrollment.common import (
    EnrollmentError,
    _S,
    _EDUCATION_FIELDS,
    _require,
    _advance_to,
    _set_status,
)
from users.roles.enrollment.serializers import me_dict
from users.roles.enrollment import service

def get_education(*, user_external_id: str) -> dict:
    """GET dos dados educacionais (plan/13). Tudo None = ainda não preenchido.

    `level`/`completed` fazem PREFILL do Profile (F3, Victor 2026-07-08): se a pessoa já respondeu
    escolaridade como candidato, o front pré-marca e não re-pergunta. `grade`/escola são riqueza da
    matrícula (não moram no Profile) → só do EducationalData."""
    from users.profiles import interface as profiles

    enr = _require(user_external_id)
    try:
        edu = enr.educational_data
    except (EducationalData.DoesNotExist, ObjectDoesNotExist):
        edu = None
    p = profiles.get(enr.user)
    level = (edu.level if edu and edu.level else None) or (
        p.education_level if p else None
    )
    completed = edu.completed if (edu and edu.completed is not None) else None
    if completed is None and p is not None:
        completed = p.education_completed
    return {
        "level": level,
        "grade": edu.grade if edu else None,
        "completed": completed,
        "last_school": edu.last_school if edu else None,
        "city": edu.city if edu else None,
        "state": edu.state if edu else None,
        "last_year_when": edu.last_year_when if edu else None,
    }


def set_education(
    *,
    user_external_id: str,
    level: str,
    grade: int,
    completed: bool,
    city: str,
    state: str,
    last_school: str = "",
    last_year_when=None,
) -> Enrollment:
    enr = _require(user_external_id, _S.EDUCATION)
    # nível válido (Fundamental | Médio)
    if level not in EducationalData.Level.values:
        raise EnrollmentError(
            "Nível de ensino inválido.",
            code="EDUCATION_LEVEL_INVALID",
            extra={"level": level, "allowed": list(EducationalData.Level.values)},
        )
    # série dentro da faixa do nível: Fundamental 1–9, Médio 1–3 (o dado mais valioso da matrícula)
    lo, hi = EducationalData.GRADE_RANGE[level]
    if grade is None or not (lo <= grade <= hi):
        raise EnrollmentError(
            f"Série fora da faixa do nível ({lo}–{hi}).",
            code="EDUCATION_GRADE_OUT_OF_RANGE",
            extra={"level": level, "grade": grade, "min": lo, "max": hi},
        )
    EducationalData.objects.update_or_create(
        enrollment=enr,
        defaults={
            "level": level,
            "grade": grade,
            "completed": completed,
            "last_school": last_school,
            "city": city,
            "state": state,
            "last_year_when": last_year_when,
        },
    )
    _set_status(enr, _S.SELFIE)
    return enr


# Mensagem PÚBLICA da selfie (o que o aluno vê). O comentário cru da IA (`selfie_description`) é
# INTERNO/auditoria e NUNCA é exposto ao front (Victor 2026-06-21) — o `status` diz o resto.
