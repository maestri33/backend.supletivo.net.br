"""Receiver de eventos do Asaas (webhook de status).

Porte da lógica do micro legado (charge.apply_webhook + payment.apply_webhook) pro mono Django,
ORM síncrono. Fluxo (CONVENTION §7): persiste o evento bruto → mapeia PAYMENT_*/TRANSFER_* pra
Payment.status (só altera estado DENTRO do app Asaas). O payload bruto permanece em WebhookEvent.
"""

import structlog
from django.utils import timezone

from core import hooks as core_hooks

from .models import Payment, WebhookEvent

logger = structlog.get_logger()

# Evento de cobrança (inbound, kind=charge) -> status. None = no-op (só refresh de metadata).
ASAAS_TO_CHARGE_STATUS = {
    "PAYMENT_CREATED": "PENDING",
    "PAYMENT_AWAITING_RISK_ANALYSIS": "PENDING",
    "PAYMENT_APPROVED_BY_RISK_ANALYSIS": "PAID",
    "PAYMENT_REPROVED_BY_RISK_ANALYSIS": "FAILED",
    "PAYMENT_UPDATED": None,
    "PAYMENT_CONFIRMED": "PAID",
    "PAYMENT_RECEIVED": "PAID",
    "PAYMENT_OVERDUE": "EXPIRED",
    "PAYMENT_DELETED": "CANCELLED",
    "PAYMENT_RESTORED": "PENDING",
    "PAYMENT_REFUNDED": "REFUNDED",
    "PAYMENT_RECEIVED_IN_CASH_UNDONE": "PENDING",
    "PAYMENT_CHARGEBACK_REQUESTED": "DISPUTED",
    "PAYMENT_CHARGEBACK_DISPUTE": "DISPUTED",
    "PAYMENT_AWAITING_CHARGEBACK_REVERSAL": "DISPUTED",
    "PAYMENT_DUNNING_RECEIVED": "PAID",
    "PAYMENT_DUNNING_REQUESTED": None,
    "PAYMENT_BANK_SLIP_VIEWED": None,
    "PAYMENT_CHECKOUT_VIEWED": None,
}

# Evento de transferência (outbound, kind=pixkey|qrcode) -> status.
ASAAS_TO_PAYOUT_STATUS = {
    "TRANSFER_CREATED": "SUBMITTED",
    "TRANSFER_PENDING": "SUBMITTED",
    "TRANSFER_IN_BANK_PROCESSING": "SUBMITTED",
    "TRANSFER_DONE": "PAID",
    "TRANSFER_FAILED": "FAILED",
    "TRANSFER_BLOCKED": "FAILED",
    "TRANSFER_CANCELLED": "CANCELLED",
}

_PAYOUT_KINDS = (Payment.Kind.PIXKEY, Payment.Kind.QRCODE)

# kinds de cobrança inbound — inclui QR Code estático direto
_CHARGE_KINDS = (Payment.Kind.CHARGE, Payment.Kind.STATIC_PIX_QR)

# Trechos do `failReason` do Asaas que indicam SALDO insuficiente na conta — não é recusa
# definitiva: o Payment (e a PaymentRequest que reconcilia por cima) fica AWAITING_BALANCE e a
# fila re-tenta sozinha (CONVENTION §8: não perde dinheiro), em vez de FAILED terminal.
_INSUFFICIENT_BALANCE_HINTS = (
    "saldo insuficiente",
    "insufficient balance",
    "insufficient_balance",
    "insufficient funds",
)


def is_insufficient_balance_reason(reason: str | None) -> bool:
    """True se o motivo de falha do Asaas indica falta de saldo (retryable, não terminal)."""
    reason = (reason or "").lower()
    return any(hint in reason for hint in _INSUFFICIENT_BALANCE_HINTS)


def handle_event(payload, source_ip=None, user_agent=None):
    """Persiste o evento bruto e roteia. Retorna o WebhookEvent.

    A persistência do evento NÃO é protegida (se o banco falhar, a view 500a e o Asaas re-tenta).
    O roteamento é protegido: erro ao aplicar não pode perder o evento já salvo — cai no fallback.
    """
    event = payload.get("event") if isinstance(payload, dict) else None

    row = WebhookEvent.objects.create(
        event=event or "",
        payload=payload if isinstance(payload, dict) else {"_raw": payload},
        source_ip=source_ip,
        user_agent=user_agent,
    )

    payment, reason = None, "unknown_event"
    try:
        if isinstance(event, str) and event.startswith("PAYMENT_"):
            payment, reason = _apply_charge(payload, event)
        elif isinstance(event, str) and event.startswith("TRANSFER_"):
            payment, reason = _apply_payout(payload, event)
    except Exception as exc:  # roteamento falhou -> não perde o evento, cai no fallback
        logger.error("webhook_apply_failed", asaas_event=event, error=str(exc))
        payment, reason = None, f"apply_failed: {exc}"

    if payment is not None:
        consumed = False
        if payment.status == "PAID" and payment.kind in (Payment.Kind.CHARGE, Payment.Kind.STATIC_PIX_QR):
            consumed = core_hooks.dispatch(
                "payment.paid",
                reraise=True,
                provider="asaas",
                provider_payment_id=payment.payment_id,
                amount_cents=int(payment.amount * 100),
                # comprovante PIX / fatura (Asaas)
                receipt_url=(payload.get("payment") or {}).get("transactionReceiptUrl")
                or (payload.get("payment") or {}).get("invoiceUrl"),
            )
        elif payment.status == "REFUNDED" and payment.kind == Payment.Kind.CHARGE:
            consumed = core_hooks.dispatch(
                "payment.refunded",
                reraise=False,
                provider="asaas",
                provider_payment_id=payment.payment_id,
                amount_cents=int(payment.amount * 100),
            )
        elif payment.status == "DISPUTED" and payment.kind == Payment.Kind.CHARGE:
            consumed = core_hooks.dispatch(
                "payment.disputed",
                reraise=False,
                provider="asaas",
                provider_payment_id=payment.payment_id,
                amount_cents=int(payment.amount * 100),
                asaas_event=event,
            )
        row.forwarded_ok = True
        row.forwarded_at = timezone.now()
        row.save(update_fields=["forwarded_ok", "forwarded_at"])
        if not consumed:
            logger.warning(
                "webhook_unconsumed",
                provider="asaas",
                provider_event=event or "",
                reason=f"applied_no_consumer: {reason}",
            )
    else:
        logger.warning(
            "webhook_unconsumed",
            provider="asaas",
            provider_event=event or "",
            reason=reason,
        )

    return row


def _apply_charge(payload, event):
    """PAYMENT_* -> Payment(kind=charge). Retorna (payment_atualizado|None, reason)."""
    if event not in ASAAS_TO_CHARGE_STATUS:
        return None, f"unmapped_charge_event: {event}"
    new_status = ASAAS_TO_CHARGE_STATUS[event]
    data = payload.get("payment") or {}
    asaas_id = data.get("id")
    ext_ref = data.get("externalReference")

    row = _find_payment(ext_ref, asaas_id, kinds=_CHARGE_KINDS)
    if row is None:
        return None, f"no_matching_charge: ext_ref={ext_ref} asaas_id={asaas_id}"

    # Atualiza metadados se vierem no webhook
    if asaas_id and row.asaas_id != asaas_id:
        row.asaas_id = asaas_id
    if data.get("billingType") and not row.billing_type:
        row.billing_type = data.get("billingType")
    if data.get("bankSlipUrl") and not row.bank_slip_url:
        row.bank_slip_url = data.get("bankSlipUrl")
    if data.get("identificationField") and not row.identification_field:
        row.identification_field = data.get("identificationField")
    if data.get("nossoNumero") and not row.nosso_numero:
        row.nosso_numero = data.get("nossoNumero")
    if data.get("netValue") is not None:
        try:
            from decimal import Decimal

            row.net_value = Decimal(str(data.get("netValue"))).quantize(Decimal("0.01"))
        except Exception:
            pass

    # Registra / atualiza DisputeRecord em caso de contestação/chargeback
    if new_status == "DISPUTED":
        from finance.models import DisputeRecord

        dsp_id = f"dsp_{row.asaas_id or row.payment_id}"
        DisputeRecord.objects.get_or_create(
            external_dispute_id=dsp_id,
            defaults={
                "amount": row.amount,
                "status": DisputeRecord.Status.OPEN,
                "reason": f"Asaas Webhook: {event}",
            },
        )

    if new_status is None:  # PAYMENT_UPDATED / VIEWS -> só refresh, sem mudar status
        row.save()
        return None, "payment_updated_noop"

    # G5: não rebaixa estado terminal por evento tardio/fora de ordem. REFUNDED é final; PAID só
    # aceita ir pra PAID/REFUNDED/DISPUTED.
    if row.status == "REFUNDED" or (
        row.status == "PAID" and new_status not in ("PAID", "REFUNDED", "DISPUTED")
    ):
        row.save()
        return None, f"terminal_{row.status}_ignora_{new_status}"

    if row.status == new_status:
        if new_status in ("PAID", "DISPUTED"):
            row.save()
            return row, "already_paid_redispatch"
        row.save()
        return None, "status_unchanged"

    row.status = new_status
    row.save()
    logger.info(
        "charge_status_changed",
        payment_id=row.payment_id,
        status=new_status,
        asaas_event=event,
    )
    return row, "ok"



def _apply_payout(payload, event):
    """TRANSFER_* -> Payment(kind in pixkey,qrcode). Retorna (payment|None, reason)."""
    new_status = ASAAS_TO_PAYOUT_STATUS.get(event)
    if not new_status:
        return None, f"unmapped_transfer_event: {event}"
    data = payload.get("transfer") or {}
    asaas_id = data.get("id")
    ext_ref = data.get("externalReference")
    fail_reason = data.get("failReason") or ""

    # saldo insuficiente NÃO é recusa definitiva: vira AWAITING_BALANCE (não-terminal, a fila
    # do finance re-tenta sozinha) em vez de FAILED.
    if new_status == "FAILED" and is_insufficient_balance_reason(fail_reason):
        new_status = "AWAITING_BALANCE"

    row = _find_payment(ext_ref, asaas_id, kinds=_PAYOUT_KINDS)
    if row is None:
        return None, f"no_matching_transfer: ext_ref={ext_ref} asaas_id={asaas_id}"

    if asaas_id and row.asaas_id != asaas_id:
        row.asaas_id = asaas_id
    if row.status == new_status:
        return None, "status_unchanged"
    row.status = new_status
    if new_status == "FAILED":
        row.last_error = fail_reason or f"event={event}"
    row.save()
    logger.info(
        "payout_status_changed",
        payment_id=row.payment_id,
        status=new_status,
        asaas_event=event,
    )
    return row, "ok"


def _find_payment(ext_ref, asaas_id, kinds):
    """Match por externalReference (= nosso payment_id) e, em seguida, por asaas_id."""
    qs = Payment.objects.filter(kind__in=kinds)
    if ext_ref:
        row = qs.filter(payment_id=ext_ref).first()
        if row is not None:
            return row
    if asaas_id:
        return qs.filter(asaas_id=asaas_id).first()
    return None
