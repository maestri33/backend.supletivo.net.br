"""Receiver de eventos da InfinitePay (webhook de pagamento aprovado).

Fluxo (CONVENTION §7): persiste o evento bruto → acha o Checkout por order_nsu → RECONFIRMA via
payment_check (a trava real: nunca confia só no corpo do webhook) → marca PAID. A doc oficial da InfinitePay não
tem HMAC/secret; o `order_nsu` (UUID opaco) liga o webhook ao checkout e o `payment_check` confirma
o pagamento direto na API antes de mudar qualquer estado.
"""

import asyncio

import structlog
from django.conf import settings
from django.utils import timezone

from core import hooks as core_hooks

from .client import InfinitePayError, get_client
from .models import Checkout, WebhookEvent

logger = structlog.get_logger()


def handle_event(order_nsu, payload, *, source_ip=None, user_agent=None):
    """Persiste o evento bruto e roteia. Retorna (WebhookEvent, result_dict).

    A persistência do evento NÃO é protegida (se o banco falhar, a view 500a e a InfinitePay re-tenta).
    O roteamento é protegido: erro ao aplicar não pode perder o evento já salvo — cai no fallback.
    """
    row = WebhookEvent.objects.create(
        order_nsu=str(order_nsu or ""),
        payload=payload if isinstance(payload, dict) else {"_raw": payload},
        source_ip=source_ip,
        user_agent=user_agent,
    )

    checkout, result, reason = None, {"ok": True}, "unknown"
    try:
        checkout, result, reason = _apply(order_nsu, payload)
    except Exception as exc:  # roteamento falhou -> não perde o evento, cai no fallback
        logger.error("webhook_apply_failed", order_nsu=str(order_nsu), error=str(exc))
        checkout, result, reason = None, {"ok": True}, f"apply_failed: {exc}"

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
                receipt_url=payload.get("receipt_url")
                if isinstance(payload, dict)
                else None,
            )
        row.forwarded_ok = True
        row.forwarded_at = timezone.now()
        row.save(update_fields=["forwarded_ok", "forwarded_at"])
        if not consumed:
            logger.warning(
                "webhook_unconsumed",
                provider="infinitepay",
                provider_event="checkout_paid",
                reason=f"applied_no_consumer: {reason}",
            )
    else:
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

    transaction_nsu = payload.get("transaction_nsu")
    slug = payload.get("invoice_slug") or payload.get("slug")
    if not transaction_nsu or not slug:
        return None, {"ok": True, "paid": False}, "incomplete_payload"

    row = Checkout.objects.filter(external_id=nsu).first()
    if row is None:
        return None, {"ok": True}, f"no_matching_checkout: {nsu}"
    if row.status == Checkout.Status.PAID:
        return row, {"ok": True, "paid": True, "duplicate": True}, "duplicate"

    # A TRAVA real: reconfirma o pagamento direto na API antes de marcar pago.
    from core.system_config import get_setting

    handle = get_setting("INFINITEPAY_HANDLE", getattr(settings, "INFINITEPAY_HANDLE", "")).lstrip("$")
    try:
        check = asyncio.run(
            _payment_check(handle, nsu, transaction_nsu, slug)
        )
    except InfinitePayError as e:
        logger.warning("payment_check_failed", order_nsu=nsu, body=str(e.payload))
        return None, {"ok": True, "paid": False}, f"payment_check_failed: {e.payload}"

    if not check.get("success"):
        return None, {"ok": True, "paid": False}, "payment_check_unsuccessful"
    if not check.get("paid"):
        return None, {"ok": True, "paid": False}, "not_paid"

    # VALOR: confia SÓ no payment_check (out-of-band verificado), NUNCA no payload forjável. E confirma
    # que o pago cobre o esperado (amount_cents é fixo, gravado na criação do checkout). Parcelamento
    # pode pagar a MAIS (juros do cliente) → exigimos >= esperado; pagar a MENOS é rejeitado.
    paid_raw = check.get("paid_amount")
    if paid_raw is not None and int(paid_raw) < row.amount_cents:
        logger.warning(
            "infinitepay_underpaid",
            order_nsu=nsu,
            expected_cents=row.amount_cents,
            paid_cents=paid_raw,
        )
        return (
            None,
            {"ok": True, "paid": False},
            f"amount_mismatch: expected={row.amount_cents} paid={paid_raw}",
        )

    row.status = Checkout.Status.PAID
    row.transaction_nsu = transaction_nsu
    row.slug = slug
    row.paid_amount_cents = int(paid_raw) if paid_raw is not None else row.amount_cents
    # Informativos (NÃO decidem dinheiro): prefere o payment_check verificado, mas cai pro payload
    # quando o check omite — senão grava NULL à toa (fallback restaurado; wave1 tinha zerado).
    row.installments = check.get("installments") or payload.get("installments")
    row.capture_method = check.get("capture_method") or payload.get("capture_method")
    row.receipt_url = payload.get(
        "receipt_url"
    )  # cosmético (link do recibo), não decide dinheiro
    row.save()
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
