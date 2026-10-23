"""Receiver de eventos da InfinitePay (webhook de pagamento aprovado).

Fluxo (CONVENTION §7): persiste o evento bruto → acha o Checkout por order_nsu → RECONFIRMA via
payment_check (a trava real: nunca confia só no corpo do webhook) → marca PAID. A doc oficial da InfinitePay não
tem HMAC/secret; o `order_nsu` (UUID opaco) liga o webhook ao checkout e o `payment_check` confirma
o pagamento direto na API antes de mudar qualquer estado.
"""

import asyncio
from uuid import UUID

import structlog
from django.db import transaction
from django.utils import timezone

from core import hooks as core_hooks

from .client import InfinitePayError, get_client
from .models import Checkout, WebhookEvent

logger = structlog.get_logger()


def handle_event(order_nsu, payload, *, source_ip=None, user_agent=None, event_row=None):
    """Persiste o evento bruto e roteia. Retorna (WebhookEvent, result_dict).

    A persistência do evento NÃO é protegida (se o banco falhar, a view 500a e a InfinitePay re-tenta).
    A aplicação que falha propaga a exceção: o evento fica salvo e o remetente pode repetir.
    """
    row = event_row or WebhookEvent.objects.create(
        order_nsu=str(order_nsu or ""),
        payload=payload if isinstance(payload, dict) else {"_raw": payload},
        source_ip=source_ip,
        user_agent=user_agent,
    )

    checkout, result, reason = None, {"ok": True}, "unknown"
    try:
        checkout, result, reason = _apply(order_nsu, payload)
    except Exception as exc:  # roteamento falhou -> não perde o evento, cai no fallback
        logger.error("webhook_apply_failed", order_nsu=str(order_nsu), code="processing_failed")
        raise

    if checkout is not None:
        # CHECKOUT PAGO -> dispara o hook do app destino (lead) §7.3.
        # G4: reraise=True — efeito de negócio que falha propaga (view não-2xx → InfinitePay
        # re-tenta), em vez de mascarar como sucesso. `_apply` já retorna o row em `duplicate`
        # (checkout PAID), então o retry re-dispatcha. forwarded_ok só após o dispatch não levantar.
        consumed = False
        if checkout.status == Checkout.Status.PAID:
            consumed = core_hooks.dispatch(
                "payment.paid",
                reraise=True,
                provider="infinitepay",
                provider_payment_id=str(checkout.external_id),
                amount_cents=checkout.paid_amount_cents,
                # comprovante (InfinitePay) → o lead manda pro aluno na notify de pago.
                receipt_url=checkout.receipt_url,
            )
        row.forwarded_ok = consumed
        row.forwarded_at = timezone.now() if consumed else None
        row.last_error_code = "" if consumed else "consumer_missing"
        row.save(update_fields=["forwarded_ok", "forwarded_at", "last_error_code"])
        if not consumed:
            logger.warning(
                "webhook_unconsumed",
                provider="infinitepay",
                provider_event="checkout_paid",
                reason=f"applied_no_consumer: {reason}",
            )
    else:
        row.last_error_code = reason
        row.save(update_fields=["last_error_code"])
        logger.warning(
            "webhook_unconsumed",
            provider="infinitepay",
            provider_event="webhook",
            reason=reason,
        )
    return row, result


def _apply(order_nsu, payload):
    """Aplica o evento. Retorna (checkout|None, result_dict, reason)."""
    if not isinstance(payload, dict):
        return None, {"ok": True}, "payload_not_dict"

    body_order = str(payload.get("order_nsu") or "")
    if order_nsu and body_order and body_order != str(order_nsu):
        return None, {"ok": True}, "order_nsu_mismatch"
    nsu = str(order_nsu or body_order)
    if not nsu:
        return None, {"ok": True}, "no_order_nsu"
    try:
        UUID(nsu)
    except (ValueError, TypeError, AttributeError):
        return None, {"ok": False, "paid": False}, "invalid_order_nsu"

    transaction_nsu = payload.get("transaction_nsu")
    slug = payload.get("invoice_slug") or payload.get("slug")
    if not transaction_nsu or not slug:
        return None, {"ok": True, "paid": False}, "incomplete_payload"
    if any(not isinstance(value, str) or len(value) > 128 for value in (transaction_nsu, slug)):
        return None, {"ok": False, "paid": False}, "invalid_reference"

    row = Checkout.objects.filter(external_id=nsu).first()
    if row is None:
        return None, {"ok": False}, "no_matching_checkout"
    if row.status == Checkout.Status.PAID:
        if row.transaction_nsu != transaction_nsu or row.slug != slug:
            return None, {"ok": False, "paid": False}, "reference_mismatch"
        if row.payment_check_payload:
            return row, {"ok": True, "paid": True, "duplicate": True}, "duplicate"
    elif row.slug and row.slug != slug:
        return None, {"ok": False, "paid": False}, "reference_mismatch"

    # A TRAVA real: reconfirma o pagamento direto na API antes de marcar pago.
    handle = row.request_payload.get("handle")
    if not isinstance(handle, str) or not handle.strip():
        return None, {"ok": False, "paid": False}, "original_handle_missing"
    try:
        check = asyncio.run(
            _payment_check(handle, nsu, transaction_nsu, slug)
        )
    except InfinitePayError as e:
        logger.warning("payment_check_failed", order_nsu=nsu, code="payment_check_failed")
        if e.status_code is None or e.status_code in {401, 403, 408, 429} or e.status_code >= 500:
            raise
        return None, {"ok": False, "paid": False}, "payment_check_failed"

    if not isinstance(check, dict):
        return None, {"ok": False, "paid": False}, "invalid_confirmation"
    if check.get("success") is not True:
        return None, {"ok": True, "paid": False}, "payment_check_unsuccessful"
    if check.get("paid") is not True:
        return None, {"ok": True, "paid": False}, "not_paid"

    # VALOR: confia SÓ no payment_check (out-of-band verificado), NUNCA no payload forjável. E confirma
    # que o pago cobre o esperado (amount_cents é fixo, gravado na criação do checkout). Parcelamento
    # pode pagar a MAIS (juros do cliente) → exigimos >= esperado; pagar a MENOS é rejeitado.
    paid_raw = check.get("paid_amount")
    amount_raw = check.get("amount")
    if paid_raw is None or amount_raw is None:
        return None, {"ok": False, "paid": False}, "amount_missing"
    if type(paid_raw) is not int or type(amount_raw) is not int or amount_raw <= 0 or paid_raw <= 0:
        return None, {"ok": False, "paid": False}, "invalid_amount"
    if amount_raw != row.amount_cents or paid_raw < amount_raw:
        logger.warning(
            "infinitepay_underpaid",
            order_nsu=nsu,
            expected_cents=row.amount_cents,
            paid_cents=paid_raw,
        )
        return None, {"ok": False, "paid": False}, "amount_mismatch"

    installments = check.get("installments")
    capture = check.get("capture_method")
    if (installments is not None and (type(installments) is not int or not 1 <= installments <= 12)) or (capture is not None and capture not in ("credit_card", "pix")):
        return None, {"ok": False, "paid": False}, "invalid_confirmation"

    from integrations.bank.recovery import safe_receipt_url

    with transaction.atomic():
        row = Checkout.objects.select_for_update().get(pk=row.pk)
        if row.status == Checkout.Status.PAID and (row.transaction_nsu != transaction_nsu or row.slug != slug):
            return None, {"ok": False, "paid": False}, "reference_mismatch"
        row.status = Checkout.Status.PAID
        row.transaction_nsu = transaction_nsu
        row.slug = slug
        row.paid_amount_cents = paid_raw
        row.payment_check_payload = check
        row.installments = check.get("installments")
        row.capture_method = check.get("capture_method")
        if not row.receipt_url:
            row.receipt_url = safe_receipt_url(payload.get("receipt_url"))
        row.save(update_fields=["status", "transaction_nsu", "slug", "paid_amount_cents", "payment_check_payload", "installments", "capture_method", "receipt_url", "updated_at"])
    logger.info(
        "checkout_paid",
        external_id=nsu,
        transaction_nsu=transaction_nsu,
        capture_method=row.capture_method,
    )
    return row, {"ok": True, "paid": True}, "paid"


async def _payment_check(handle, order_nsu, transaction_nsu, slug):
    async with get_client() as c:
        return await c.payment_check(
            handle=handle,
            order_nsu=order_nsu,
            transaction_nsu=transaction_nsu,
            slug=slug,
        )
