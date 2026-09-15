from __future__ import annotations

import datetime
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from hub.models import Hub
from users.documents import service as documents_iface
from users.exceptions import Conflict, Forbidden
from users.profiles import interface as profiles
from users.roles import _document_ai, _selfie
from users.roles.enrollment.models import Enrollment
from users.roles.enrollment.common import (
    EnrollmentError,
    _S,
    _advance_to,
    get_by_external_id,
    logger,
)
from users.roles.enrollment.serializers import me_dict
from users.roles.enrollment import service
from users.roles.enrollment.fees_events import batch_fee_facts

def _enrollment_for_coordinator(
    enrollment_external_id: str, coordinator, *allowed_status
) -> Enrollment:
    """Carrega a matrícula e exige que o `coordinator` coordene o hub dela (gate de TODA ação plan/14)."""
    enr = get_by_external_id(enrollment_external_id)
    if enr is None:
        raise NotFound("Matrícula não encontrada.", code="ENROLLMENT_NOT_FOUND")
    if enr.hub.coordinator_id != coordinator.id:
        raise EnrollmentError(
            "Você não coordena o polo desta matrícula.", code="NOT_HUB_COORDINATOR"
        )
    if allowed_status and enr.status not in allowed_status:
        # visão do coordenador → status REAL (sem máscara).
        raise Conflict(
            "A matrícula está em outra etapa.",
            code="WRONG_STATUS",
            extra={"expected_status": enr.status},
        )
    return enr





def _hub_item_dict(enr: Enrollment, profile=None, fees_info=None) -> dict:
    p = profile if profile is not None else profiles.get(enr.user)
    return {
        "external_id": str(enr.external_id),
        "name": p.name if p else None,
        "phone": p.phone if p else None,
        "status": enr.status,  # status REAL (visão do coordenador, sem máscara)
        "fees": fees_info if fees_info is not None else fee_facts(enr),
        "created_at": enr.created_at.isoformat(),
    }


def list_for_staff(*, hub_external_id=None, status=None, limit=200) -> list[dict]:
    """Matrículas de TODOS os polos (ou de um, se `hub_external_id`) pro painel do staff. Read-only."""
    from users.profiles import interface as profiles

    qs = Enrollment.objects.select_related("user", "hub").order_by("-id")
    if hub_external_id:
        qs = qs.filter(hub__external_id=hub_external_id)
    if status:
        qs = qs.filter(status=status)
    rows = list(qs[:limit])
    pmap = profiles.get_map([r.user for r in rows])
    out = []
    for enr in rows:
        p = pmap.get(enr.user_id)
        out.append(
            {
                "external_id": str(enr.external_id),
                "status": enr.status,
                "self_study": enr.self_study,
                "hub_external_id": str(enr.hub.external_id),
                "name": p.name if p else None,
            }
        )
    return out


def list_for_hub(*, hub, status: str | None = None) -> list[dict]:
    """Matrículas do polo (visão do coordenador): status REAL + resumo das 2 parcelas da taxa.
    `?status=awaiting_release` = quem terminou o wizard e espera ação do coordenador."""
    qs = (
        Enrollment.objects.filter(hub=hub)
        .select_related("user")
        .order_by("-created_at")
    )
    if status:
        qs = qs.filter(status=status)
    rows = list(qs)
    pmap = profiles.get_map([enr.user for enr in rows])
    fees_map = batch_fee_facts(rows)
    return [
        _hub_item_dict(
            enr,
            profile=pmap.get(enr.user_id),
            fees_info=fees_map.get(str(enr.external_id)),
        )
        for enr in rows
    ]


def coordinated_user_ext(*, enrollment_external_id: str, coordinator) -> str:
    """Gate (coordenar o hub da matrícula) → external_id do USER, pra o coordenador AGIR NO LUGAR de
    um cliente sem prática digital (WP5). Reusa o gate do `_enrollment_for_coordinator`."""
    enr = service._enrollment_for_coordinator(enrollment_external_id, coordinator)
    return str(enr.user.external_id)


def detail_for_hub(*, enrollment_external_id: str, coordinator) -> dict:
    """Detalhe COMPLETO de uma matrícula pro coordenador: a visão rica do /me (todas as seções)
    + status REAL (sem máscara) + fatos da taxa."""
    enr = service._enrollment_for_coordinator(enrollment_external_id, coordinator)
    return {**me_dict(enr), "status": enr.status, "fees": fee_facts(enr)}


# campos de identidade DERIVADOS DO DOCUMENTO (OCR) que o coordenador pode corrigir. NÃO inclui
# `name`/`birth_date` (CPFHub é a fonte autoritativa) nem `pix` (validação própria) — Victor 2026-06-17.
_COORD_CORRECTABLE = (
    "mother_name",
    "father_name",
    "marital_status",
    "nationality",
    "birthplace",
)


def coordinator_correct_identity(
    *, enrollment_external_id: str, coordinator, **fields
) -> dict:
    """Coordenador corrige campos de identidade do Profile que o OCR extraiu errado (filiação, estado
    civil, naturalidade, nacionalidade) — sem isso uma extração torta fica gravada pra sempre e só um
    db-edit conserta (Victor 2026-06-17: user→coord, sem dev). SOBRESCREVE via `profiles.update_identity`.

    NÃO mexe em `name`/`birth_date` (CPFHub manda) nem em `pix`. Gate: coordenar o hub da matrícula."""
    enr = service._enrollment_for_coordinator(enrollment_external_id, coordinator)
    clean = {
        k: v for k, v in fields.items() if k in _COORD_CORRECTABLE and v is not None
    }
    if not clean:
        raise DomainError(
            "Nenhum campo de identidade corrigível foi informado.", code="NO_FIELDS"
        )
    profiles.update_identity(enr.user, **clean)
    # G8/#17: os campos corrigidos podem ser exatamente o que faltava no gate #10 (selfie já
    # aprovada pelo coordenador, mas faltava nacionalidade/estado civil). Re-dispara o avanço —
    # idempotente (só sai de SELFIE, e só se não faltar mais nada). Sem isso, ficava preso em SELFIE.
    service._advance_to_release(enr)
    logger.info(
        "leadership.acted_for",
        action="correct_identity",
        enrollment=enrollment_external_id,
        fields=list(clean.keys()),
        by=str(coordinator.external_id),
    )
    return {**service.me_dict(enr), "status": enr.status}


def _sweep_stale_reviews(hub) -> None:
    from users.documents.models import RG
    from users.roles import _analysis

    _analysis.sweep_stale_selfies(Enrollment, hub)
    user_ids = list(
        Enrollment.objects.filter(hub=hub).values_list("user_id", flat=True)
    )
    _analysis.sweep_stale_documents(
        RG.objects.filter(document__user_id__in=user_ids), _rg_started_at
    )


def list_reviews_for_hub(*, hub) -> dict:
    """Análises da MATRÍCULA paradas esperando decisão do coordenador (RG e selfie em revisão).
    Cada item aponta pro POST de decisão que já existe (`/rg/decide`, `/selfie/decide`).
    Antes de listar, varre PENDING órfão (worker morto) → review (`_sweep_stale_reviews`)."""
    from users.roles import _analysis, _selfie

    _sweep_stale_reviews(hub)

    rg_qs = list(
        Enrollment.objects.filter(
            hub=hub, user__document__rg__validation_status=_analysis.REVIEW
        )
        .select_related("user")
        .order_by("updated_at")
    )
    selfie_qs = list(
        Enrollment.objects.filter(hub=hub, selfie_status=_selfie.SelfieStatus.REVIEW)
        .select_related("user")
        .order_by("updated_at")
    )
    all_users = [e.user for e in rg_qs] + [e.user for e in selfie_qs]
    pmap = profiles.get_map(all_users)

    def _item(enr: Enrollment) -> dict:
        p = pmap.get(enr.user_id)
        return {
            "external_id": str(enr.external_id),
            "name": p.name if p else None,
            "since": enr.updated_at.isoformat(),
        }

    return {"rg": [_item(e) for e in rg_qs], "selfie": [_item(e) for e in selfie_qs]}


def _notify_released(enr: Enrollment) -> None:
    # wave-2: send_event lê teor/canais/is_tts do Template no DB.
    from notify.interface.events import send_event

    p = profiles.get(enr.user)
    try:
        send_event(
            "enrollment.released",
            profile=p,
            idempotency_key=f"enr_released_{enr.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_released_failed", error=str(exc))


def _notify_credentials(enr: Enrollment, *, login: str, password: str) -> None:
    """Manda login/senha/link da plataforma ao novo ALUNO (WhatsApp + e-mail; SEM TTS — não se lê
    senha em voz). Link = INSTITUTION_LOGIN_URL. Best-effort (§12); idempotente por chave.

    wave-2: send_event com ctx={login,password,link} — o body_md do Template contém {login}/{password}/{link}."""
    from notify.interface.events import send_event

    p = profiles.get(enr.user)
    link = getattr(settings, "INSTITUTION_LOGIN_URL", "") or ""
    try:
        send_event(
            "enrollment.credentials",
            profile=p,
            ctx={"login": login, "password": password, "link": link},
            idempotency_key=f"enr_credentials_{enr.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_credentials_failed", error=str(exc))
