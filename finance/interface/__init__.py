"""Superfície pública in-process do finance (CONVENTION §3) — LEITURA agregada pro painel do staff.

Os ESCRITORES do motor (commissions/payout/fees) são importados direto pelos seus submódulos
(`finance.interface.commissions` etc.). Aqui só leitura: lista de comissões + solicitações de
pagamento + resumo, que o grupo Ninja `staff` consome (WP6). O saldo da conta Asaas é lido no
endpoint (camada de integração), não aqui — finance não fala HTTP com o gateway.
"""

from __future__ import annotations

from finance.models import Commission, PaymentRequest


def _commission_dict(c: Commission) -> dict:
    return {
        "external_id": str(c.external_id),
        "payee_external_id": str(c.payee.external_id) if c.payee_id else None,
        "payee_role": c.payee_role,
        "source_type": c.source_type,
        "amount": str(c.amount),
        "status": c.status,
        "external_reference": c.external_reference,
        "created_at": c.created_at.isoformat(),
    }


def list_commissions(*, status: str | None = None, limit: int = 200) -> list[dict]:
    """Comissões (mais recentes primeiro), filtráveis por status. Read-only."""
    qs = Commission.objects.select_related("payee").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    return [_commission_dict(c) for c in qs[:limit]]


def _payment_request_dict(pr: PaymentRequest) -> dict:
    from users.profiles.interface import get as get_profile

    profile = get_profile(pr.payee) if pr.payee else None
    return {
        "external_id": str(pr.external_id),
        "kind": pr.kind,
        "method": pr.method,
        "amount": str(pr.amount),
        "status": pr.status,
        "supplier_name": pr.supplier_name,
        "payee_name": profile.name if profile else None,
        "payee_phone": profile.phone if profile else None,
        "payee_external_id": str(pr.payee.external_id) if pr.payee else None,
        "pix_key": pr.pix_key or (profile.pix_key if profile else None),
        "last_error": pr.last_error,
        "attempts": pr.attempts,
        "next_attempt_at": pr.next_attempt_at.isoformat() if pr.next_attempt_at else None,
        "week_of": pr.week_of.isoformat() if pr.week_of else None,
        "scheduled_for": pr.scheduled_for.isoformat() if pr.scheduled_for else None,
        "asaas_status": pr.asaas_status,
        "external_reference": pr.external_reference,
        "boleto_line": pr.boleto_line,
        "receipt": pr.receipt,
        "created_at": pr.created_at.isoformat(),
    }


def list_payment_requests(
    *, status: str | None = None, kind: str | None = None, limit: int = 200
) -> list[dict]:
    """Solicitações de pagamento/payouts (a fila de saída), filtráveis por status/kind. Read-only."""
    qs = PaymentRequest.objects.select_related("payee").order_by("-created_at")
    if status:
        qs = qs.filter(status=status)
    if kind:
        qs = qs.filter(kind=kind)
    return [_payment_request_dict(pr) for pr in qs[:limit]]



def summary() -> dict:
    """Resumo por status (contagem + total em reais) pro cabeçalho do painel financeiro do staff."""
    from django.db.models import Count, Sum

    def _by_status(model) -> dict:
        rows = model.objects.values("status").annotate(
            n=Count("id"), total=Sum("amount")
        )
        return {
            r["status"]: {"count": r["n"], "total": str(r["total"] or 0)} for r in rows
        }

    return {
        "commissions": _by_status(Commission),
        "payment_requests": _by_status(PaymentRequest),
    }


def closing_obligation(*, reference_date=None) -> dict:
    """Estima, SÓ no banco, quanto dinheiro PRECISA sair (sem falar com o gateway — o saldo é lido na
    camada de integração, no endpoint). Soma duas frentes (CONVENTION §3):

      1. comissões PENDENTES da semana corrente — viram PaymentRequest no fechamento (`run_weekly_closing`);
      2. PaymentRequests ATIVAS (não-terminais, ainda não pagas) já na fila — comissões antigas, fees, avulsos.

    Devolve `{week_of, pending_commissions, queued_payouts, obrigacao_estimada}` (tudo em reais, str).
    """
    from decimal import Decimal

    from django.db.models import Sum
    from django.utils import timezone

    from finance.interface.commissions import _week_bounds

    now = reference_date or timezone.now()
    if timezone.is_naive(now):
        now = timezone.make_aware(now)
    week_start, week_end, monday, _friday = _week_bounds(now)

    pending = Commission.objects.filter(
        status=Commission.Status.PENDING,
        created_at__gte=week_start,
        created_at__lt=week_end,
    ).aggregate(total=Sum("amount"))["total"] or Decimal("0")

    active_states = (
        PaymentRequest.Status.QUEUED,
        PaymentRequest.Status.AWAITING_PIX,
        PaymentRequest.Status.SUBMITTED,
        PaymentRequest.Status.AWAITING_BALANCE,
    )
    queued = PaymentRequest.objects.filter(status__in=active_states).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0")

    return {
        "week_of": monday.isoformat(),
        "pending_commissions": str(pending),
        "queued_payouts": str(queued),
        "obrigacao_estimada": str(pending + queued),
    }


# Re-exportações do Ledger Contábil e Soberania do Admin
from finance.interface.audit import (
    list_financial_audit_logs,
    log_financial_audit,
)
from finance.interface.ledger import (
    create_manual_adjustment,
    create_unexpected_expense,
    ensure_default_accounts,
    get_cashflow_overview,
    list_ledger_entries,
    list_transactions,
    record_transaction,
    resolve_dispute,
)

