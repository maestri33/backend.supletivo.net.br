"""Checkout service — link de pagamento InfinitePay (porte do checkout_service legado, ORM síncrono).

Fluxo de criação (CONVENTION §8 — caminho do dinheiro idempotente):
  1. persiste a INTENÇÃO primeiro: Checkout(status=PENDING) → gera external_id (= order_nsu) ANTES da
     chamada externa. external_id único impede duplicar; é o token opaco que liga o webhook ao checkout.
  2. POST /links {handle, items, order_nsu, redirect_url, webhook_url, customer?} → checkout_url + slug
  3. grava checkout_url/slug/payloads no Checkout
O client httpx é async; chamamos via asyncio.run() com o ORM síncrono em volta (padrão do asaas). O
status depois é guiado pelo webhook (webhooks.handle_event), que reconfirma via payment_check.
"""

import asyncio
from decimal import Decimal, InvalidOperation

import structlog
from django.conf import settings

from .client import InfinitePayError, get_client
from .models import Checkout

logger = structlog.get_logger()


class CheckoutError(Exception):
    pass


def _normalize_amount_cents(amount_cents, amount) -> int:
    """Aceita amount_cents (int, nativo da API) OU amount em reais (converte). Centavos > 0."""
    if amount_cents is not None:
        try:
            cents = int(amount_cents)
        except (TypeError, ValueError) as e:
            raise CheckoutError(f"invalid_amount_cents: {amount_cents}") from e
    elif amount is not None:
        try:
            cents = int((Decimal(str(amount)) * 100).quantize(Decimal("1")))
        except (InvalidOperation, ValueError) as e:
            raise CheckoutError(f"invalid_amount: {amount}") from e
    else:
        raise CheckoutError("amount_required")
    if cents <= 0:
        raise CheckoutError("invalid_amount")
    return cents


async def _create_link(payload: dict) -> dict:
    async with get_client() as c:
        return await c.create_checkout_link(payload)


def create_checkout(
    *,
    amount_cents=None,
    amount=None,
    description=None,
    customer=None,
    redirect_url=None,
) -> Checkout:
    """Cria um link de checkout InfinitePay. Retorna o Checkout persistido (status PENDING)."""
    cents = _normalize_amount_cents(amount_cents, amount)
    if not description:
        raise CheckoutError("description_required")
    from core.system_config import get_setting

    handle = get_setting("INFINITEPAY_HANDLE", getattr(settings, "INFINITEPAY_HANDLE", "")).lstrip("$")
    if not handle:
        raise CheckoutError(
            "handle_not_configured"
        )  # o check infinitepay.E001 já avisa no boot
    ext_url = get_setting("EXTERNAL_URL", getattr(settings, "EXTERNAL_URL", ""))
    if not ext_url:
        raise CheckoutError("external_url_not_configured")

    # 1. intenção persiste primeiro (§8): external_id = order_nsu (UUID opaco)
    row = Checkout.objects.create(
        amount_cents=cents, description=description, status=Checkout.Status.PENDING
    )
    order_nsu = str(row.external_id)

    redirect = (
        redirect_url or getattr(settings, "INFINITEPAY_REDIRECT_URL", "") or get_setting("FRONTEND_URL", getattr(settings, "FRONTEND_URL", "")) or ext_url
    )
    webhook_url = f"{ext_url}/integrations/infinitepay/webhook/?order_nsu={order_nsu}"
    payload = {
        "handle": handle,
        "items": [{"quantity": 1, "price": cents, "description": description}],
        "order_nsu": order_nsu,
        "redirect_url": redirect,
        "webhook_url": webhook_url,
    }
    if customer:
        payload["customer"] = customer

    try:
        resp = asyncio.run(_create_link(payload))
    except InfinitePayError as e:
        # mantém a intenção (PENDING) como registro auditável da tentativa que falhou
        row.request_payload = payload
        row.response_payload = {"error": str(e), "payload": e.payload}
        row.save(update_fields=["request_payload", "response_payload", "updated_at"])
        logger.warning(
            "checkout_create_failed", external_id=order_nsu, body=str(e.payload)
        )
        raise CheckoutError(f"infinitepay_create_link_failed: {e.payload or e}") from e

    row.checkout_url = resp.get("url") or resp.get("checkout_url") or resp.get("link")
    row.slug = resp.get("slug")
    row.request_payload = payload
    row.response_payload = resp
    row.save()
    logger.info(
        "checkout_created", external_id=order_nsu, slug=row.slug, amount_cents=cents
    )
    return row


def to_dict(row: Checkout) -> dict:
    return {
        "external_id": str(row.external_id),
        "status": row.status,
        "checkout_url": row.checkout_url,
        "slug": row.slug,
        "amount_cents": row.amount_cents,
        "paid_amount_cents": row.paid_amount_cents,
        "description": row.description,
        "capture_method": row.capture_method,
        "installments": row.installments,
        "transaction_nsu": row.transaction_nsu,
        "receipt_url": row.receipt_url,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
