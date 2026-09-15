from __future__ import annotations

import structlog
from users.profiles import interface as profiles
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import (
    CandidateError,
    _S,
    _EDU_LEVELS,
    _EDU_QUALIFICATIONS,
    _require,
    _set_status,
    logger,
)
from users.roles.candidate.serializers import me_dict

def set_pix(*, user_external_id, key: str, key_type: str) -> dict:
    """Valida a chave Pix no Asaas/DICT (confere que é do candidato, CPF do Profile) e grava. MEXE R$0,01."""
    from integrations.bank.asaas import pixkey

    # apelidos PT do front (celular/aleatoria/…) → tipo canônico do DICT (PHONE/EVP/…); o Profile
    # guarda SEMPRE o canônico.
    key_type = pixkey.normalize_key_type(key_type)
    cand = _require(user_external_id, _S.DOCUMENTS, _S.PIX)
    profile = profiles.find_by_external_id(user_external_id)
    if profile is None or not profile.cpf:
        raise CandidateError(
            "CPF do perfil ausente — refaça o cadastro.", code="PROFILE_CPF_MISSING"
        )
    try:
        pixkey.validate_pix_key(
            key=key, key_type=key_type, expected_document=profile.cpf
        )
    except pixkey.PixKeyError as exc:
        raise CandidateError(
            "Chave Pix inválida ou não é do titular.",
            code="PIX_INVALID",
            extra={"reason": str(exc)},
        ) from exc

    # chave Pix canônica → SÓ no Profile (Victor 2026-06-16); no candidate fica só o flag de processo.
    profiles.set_pix(user_external_id, key.strip(), key_type)
    cand.pix_validated = True
    cand.save(update_fields=["pix_validated", "updated_at"])
    if cand.status == _S.DOCUMENTS:
        _set_status(cand, _S.PIX)
    logger.info("candidate.pix_validated", external_id=str(cand.external_id))
    return me_dict(cand)


# escolaridade — ÚLTIMA pergunta antes da selfie (Victor 2026-07-08). Grava no Profile (nível-pessoa),
# reusada quando/se virar aluno. Sem médio completo → o promotor nasce `pre_matriculado` (F4). Fica
# ANTES da selfie de propósito: a selfie aprovada auto-promove (F2), então a escolaridade tem que
# ser coletada antes disso. Só nível+concluiu (série/escola são riqueza do enrollment, não do funil promotor).
_EDU_LEVELS = ("fundamental", "medio", "superior")
_EDU_QUALIFICATIONS = ("graduacao", "pos_graduacao", "mestrado", "doutorado")


def set_education(
    *,
    user_external_id,
    level: str,
    completed: bool,
    grade: int | None = None,
    last_completed_grade: int | None = None,
    qualification: str | None = None,
    last_completed_qualification: str | None = None,
    education_status: str | None = None,
    year: int | None = None,
    city: str | None = None,
    school: str | None = None,
) -> dict:
    cand = _require(user_external_id, _S.PIX, _S.EDUCATION)
    if level not in _EDU_LEVELS:
        raise CandidateError(
            "Nível de ensino inválido.",
            code="EDUCATION_LEVEL_INVALID",
            extra={"level": level, "allowed": list(_EDU_LEVELS)},
        )
    allowed_grades = range(1, 10) if level == "fundamental" else range(1, 4)
    if level != "superior" and grade is not None and grade not in allowed_grades:
        raise CandidateError(
            "Série/ano incompatível com o nível de ensino.",
            code="EDUCATION_GRADE_INVALID",
            extra={"grade": grade, "level": level},
        )
    if level == "superior":
        if qualification not in _EDU_QUALIFICATIONS:
            raise CandidateError(
                "Formação superior inválida.",
                code="EDUCATION_QUALIFICATION_INVALID",
                extra={
                    "qualification": qualification,
                    "allowed": list(_EDU_QUALIFICATIONS),
                },
            )
        if grade is not None or last_completed_grade is not None:
            raise CandidateError(
                "Ensino Superior deve informar formação, não série.",
                code="EDUCATION_GRADE_INVALID",
                extra={"grade": grade, "level": level},
            )
    elif qualification is not None or last_completed_qualification is not None:
        raise CandidateError(
            "Formação superior só pode ser usada no Ensino Superior.",
            code="EDUCATION_QUALIFICATION_INVALID",
        )
    education_status = education_status or ("completed" if completed else "stopped")
    if education_status not in ("completed", "attending", "stopped"):
        raise CandidateError(
            "Situação escolar inválida.",
            code="EDUCATION_STATUS_INVALID",
            extra={"education_status": education_status},
        )
    if level == "superior" and education_status == "completed":
        if (
            last_completed_qualification is not None
            and last_completed_qualification != qualification
        ):
            raise CandidateError(
                "A última formação concluída deve coincidir com a formação informada.",
                code="EDUCATION_LAST_COMPLETED_QUALIFICATION_INVALID",
            )
        last_completed_qualification = qualification
    elif level == "superior":
        if (
            last_completed_qualification is not None
            and last_completed_qualification not in _EDU_QUALIFICATIONS
        ):
            raise CandidateError(
                "Última formação concluída inválida.",
                code="EDUCATION_LAST_COMPLETED_QUALIFICATION_INVALID",
            )
        if last_completed_qualification is not None and qualification is not None:
            if _EDU_QUALIFICATIONS.index(
                last_completed_qualification
            ) >= _EDU_QUALIFICATIONS.index(qualification):
                raise CandidateError(
                    "A última formação concluída deve ser anterior à formação frequentada.",
                    code="EDUCATION_LAST_COMPLETED_QUALIFICATION_INVALID",
                )
    elif education_status == "completed":
        if last_completed_grade is not None and last_completed_grade != grade:
            raise CandidateError(
                "A última série concluída deve coincidir com a série informada.",
                code="EDUCATION_LAST_COMPLETED_GRADE_INVALID",
                extra={"grade": grade, "last_completed_grade": last_completed_grade},
            )
        last_completed_grade = grade
    elif last_completed_grade is not None:
        max_completed = (grade - 1) if grade is not None else max(allowed_grades)
        if last_completed_grade < 0 or last_completed_grade > max_completed:
            raise CandidateError(
                "A última série concluída deve ser anterior à série frequentada.",
                code="EDUCATION_LAST_COMPLETED_GRADE_INVALID",
                extra={
                    "grade": grade,
                    "last_completed_grade": last_completed_grade,
                    "min": 0,
                    "max": max_completed,
                },
            )
    if level == "superior":
        level_completed = education_status == "completed"
    elif grade is None:
        level_completed = bool(completed)
    else:
        final_grade = 9 if level == "fundamental" else 3
        level_completed = education_status == "completed" and grade == final_grade
    if year is not None:
        from django.utils import timezone

        if year < 1950 or year > timezone.now().year + 1:
            raise CandidateError(
                "Ano da última frequência inválido.",
                code="EDUCATION_YEAR_INVALID",
                extra={"year": year},
            )
    profiles.set_education(
        cand.user,
        level=level,
        completed=level_completed,
        grade=grade,
        last_completed_grade=last_completed_grade,
        qualification=qualification,
        last_completed_qualification=last_completed_qualification,
        education_status=education_status,
        year=year,
        city=(city or "").strip() or None,
        school=(school or "").strip() or None,
    )
    if cand.status == _S.PIX:
        _set_status(cand, _S.EDUCATION)
    logger.info(
        "candidate.education_set",
        external_id=str(cand.external_id),
        level=level,
        grade=grade,
        last_completed_grade=last_completed_grade,
        qualification=qualification,
        last_completed_qualification=last_completed_qualification,
        education_status=education_status,
        completed=level_completed,
    )
    return me_dict(cand)

