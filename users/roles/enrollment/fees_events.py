from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from finance import models as fin_models
from finance.interface import ledger as ledger_iface
from hub.models import Hub
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.enrollment.models import Enrollment
from users.roles.enrollment.common import (
    EnrollmentError,
    _S,
    _require,
    get_by_external_id,
    logger,
)
from users.roles.enrollment.serializers import me_dict
from users.roles.enrollment import service

def _fee_now_ref(enr: Enrollment) -> str:
    """Referência determinística da 1ª parcela (à vista) — idempotência na fila do finance."""
    return f"fee_enr_{enr.external_id}_now"


def _fee_due_ref(enr: Enrollment) -> str:
    """Referência determinística da 2ª parcela (agendada pro vencimento do QR)."""
    return f"fee_enr_{enr.external_id}_due"


def _fee_dict(pr) -> dict | None:
    if pr is None:
        return None
    return {
        "status": pr.status,
        "amount": str(pr.amount),
        "scheduled_for": pr.scheduled_for.isoformat() if pr.scheduled_for else None,
        "paid": pr.status == "paid",
        "last_error": pr.last_error or None,
    }


def fee_facts(enr: Enrollment) -> dict:
    """Situação das 2 parcelas da taxa, lida da fila do finance (visão do COORDENADOR — interna)."""
    from finance.interface import fees

    first = fees.latest_fee_request(_fee_now_ref(enr))
    second = fees.latest_fee_request(_fee_due_ref(enr))
    return {
        "first": _fee_dict(first),
        "second": _fee_dict(second),
        "first_paid": bool(
            first is not None and first.status == fees.PaymentStatus.PAID
        ),
        "second_scheduled": second is not None,
    }


def batch_fee_facts(enrollments: list[Enrollment]) -> dict[str, dict]:
    """Situação das 2 parcelas da taxa em lote para múltiplas matrículas (evita N+1)."""
    if not enrollments:
        return {}

    from finance.interface import fees
    from finance.models import PaymentRequest
    from django.db.models import Q

    enr_ext_ids = [enr.external_id for enr in enrollments]
    now_refs = [_fee_now_ref(enr) for enr in enrollments]
    due_refs = [_fee_due_ref(enr) for enr in enrollments]

    prs = list(
        PaymentRequest.objects.filter(
            kind=PaymentRequest.Kind.FEE,
        ).filter(
            Q(source_external_id__in=enr_ext_ids)
            | Q(external_reference__in=now_refs + due_refs)
        ).order_by("-created_at")
    )

    latest_now = {}
    latest_due = {}
    for pr in prs:
        ref = pr.external_reference or ""
        for enr in enrollments:
            eid = str(enr.external_id)
            if eid not in latest_now and ref.startswith(_fee_now_ref(enr)):
                latest_now[eid] = pr
            if eid not in latest_due and ref.startswith(_fee_due_ref(enr)):
                latest_due[eid] = pr

    out = {}
    for enr in enrollments:
        eid = str(enr.external_id)
        first = latest_now.get(eid)
        second = latest_due.get(eid)
        out[eid] = {
            "first": _fee_dict(first),
            "second": _fee_dict(second),
            "first_paid": bool(
                first is not None and first.status == fees.PaymentStatus.PAID
            ),
            "second_scheduled": second is not None,
        }
    return out


def apply_fee_paid(enr: Enrollment, *, external_reference: str, amount=None) -> bool:
    """Hook `fee.paid`: 1ª parcela paga → `fee_paid` (se ainda aguardando) + notify ao coordenador
    (é o gatilho do mundo real: a instituição só libera as credenciais com a 1ª paga). 2ª parcela
    paga no vencimento → só notify (o status já andou no agendamento)."""
    valor = f"R$ {amount}" if amount else "—"
    # match por PREFIXO: re-tentativas pós-falha carregam sufixo `_rN` na mesma família de ref.
    if external_reference.startswith(_fee_now_ref(enr)):
        if enr.status == _S.AWAITING_RELEASE:
            _set_status(enr, _S.FEE_PAID)
        _notify_fee_event(enr, "enrollment.fee_paid", valor=valor)
        logger.info("enrollment.fee_paid", external_id=str(enr.external_id))
        return True
    if external_reference.startswith(_fee_due_ref(enr)):
        _notify_fee_event(enr, "enrollment.fee_due_paid", valor=valor)
        logger.info("enrollment.fee_due_paid", external_id=str(enr.external_id))
        return True
    return False


def apply_fee_problem(
    enr: Enrollment, *, external_reference: str, detail=None, asaas_status=None
) -> bool:
    """Hook `fee.problem`: QUALQUER B.O. com a taxa (sem saldo, falha, erro) notifica o coordenador
    (palavra do Victor 2026-06-12). O status da matrícula NÃO regride — o coordenador re-posta a
    parcela (a fila re-arma via `_queue_fee`)."""
    if external_reference.startswith(_fee_now_ref(enr)):
        which = "1ª parcela (à vista)"
    elif external_reference.startswith(_fee_due_ref(enr)):
        which = "2ª parcela (agendada)"
    else:
        return False
    _notify_fee_event(
        enr,
        "enrollment.fee_problem",
        detail=f"{which} — {detail or 'erro desconhecido'}.",
        idem_suffix=f"_{asaas_status or 'err'}",
    )
    logger.warning(
        "enrollment.fee_problem",
        external_id=str(enr.external_id),
        ref=external_reference,
        detail=detail,
    )
    return True


def _notify_fee_event(
    enr: Enrollment, event: str, idem_suffix: str = "", **placeholders
) -> None:
    """Notify do ciclo da taxa → SEMPRE o COORDENADOR, nunca o aluno (política interna). Sem TTS.

    wave-2: send_event lê teor/canais/is_tts do Template no DB. injeção de placeholders via ctx
    (student_name, amount, etc.)."""
    from notify.interface.events import send_event

    coord = enr.hub.coordinator
    if coord is None:
        logger.warning(
            "enrollment.fee_notify_no_coordinator", external_id=str(enr.external_id)
        )
        return
    cp = profiles.get(coord)
    sp = profiles.get(enr.user)
    try:
        send_event(
            event,
            profile=cp,
            ctx={
                "student_name": (sp.name if sp else None) or "um aluno",
                **placeholders,
            },
            idempotency_key=f"{event}_{enr.external_id}{idem_suffix}",
        )
    except Exception as exc:  # noqa: BLE001 — notify nunca quebra o fluxo (§12)
        logger.warning(
            "enrollment.fee_notify_failed", notify_event=event, error=str(exc)
        )


