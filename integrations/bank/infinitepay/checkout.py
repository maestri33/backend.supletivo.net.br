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
from django.db import transaction
from django.utils import timezone

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
    external_id=None,
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

    # Reserve the stable local intent before contacting a provider without a documented
    # remote idempotency guarantee. The caller persists this UUID on its own attempt first.
    with transaction.atomic():
        if external_id is None:
            row = Checkout.objects.create(amount_cents=cents, description=description)
        else:
            row, _ = Checkout.objects.get_or_create(
                external_id=external_id,
                defaults={"amount_cents": cents, "description": description},
            )
            row = Checkout.objects.select_for_update().get(pk=row.pk)
        if row.amount_cents != cents:
            raise CheckoutError("checkout_amount_mismatch")
        if row.checkout_url:
            return row
        if row.creation_state == Checkout.CreationState.UNCERTAIN:
            raise CheckoutError("checkout_creation_uncertain")
        if row.creation_state == Checkout.CreationState.CREATING:
            raise CheckoutError("checkout_creation_in_progress")
    order_nsu = str(row.external_id)

    raw_redirect = (
        redirect_url
        or getattr(settings, "INFINITEPAY_REDIRECT_URL", "")
        or get_setting("FRONTEND_URL", getattr(settings, "FRONTEND_URL", ""))
        or ext_url
    )
    base_redirect = raw_redirect.rstrip("/")
    if ("supletivo.net.br" in base_redirect or "localhost" in base_redirect or "app." in base_redirect) and "/student/lead" not in base_redirect and "/matricula" not in base_redirect:
        base_redirect = f"{base_redirect}/student/lead"

    sep = "&" if "?" in base_redirect else "?"
    if "order_nsu" not in base_redirect:
        redirect = f"{base_redirect}{sep}from=infinitepay&order_nsu={order_nsu}"
    else:
        redirect = base_redirect

    edge_webhook = get_setting(
        "INFINITEPAY_WEBHOOK_URL",
        getattr(settings, "INFINITEPAY_WEBHOOK_URL", "https://webhooks.v7m.live/bank/infinitepay"),
    )
    if edge_webhook:
        sep = "&" if "?" in edge_webhook else "?"
        webhook_url = f"{edge_webhook}{sep}order_nsu={order_nsu}"
    else:
        sep = "&" if "?" in ext_url else "?"
        webhook_url = f"{ext_url}/integrations/infinitepay/webhook/?order_nsu={order_nsu}"

    cleaned_customer = {
        k: str(v).strip()
        for k, v in customer.items()
        if v is not None and str(v).strip()
    } if isinstance(customer, dict) else None

    payload = {
        "handle": handle,
        "items": [{"quantity": 1, "price": cents, "description": row.description}],
        "order_nsu": order_nsu,
        "redirect_url": redirect,
        "webhook_url": webhook_url,
    }
    if cleaned_customer:
        payload["customer"] = cleaned_customer

    with transaction.atomic():
        row = Checkout.objects.select_for_update().get(pk=row.pk)
        if row.checkout_url:
            return row
        if row.creation_state == Checkout.CreationState.UNCERTAIN:
            raise CheckoutError("checkout_creation_uncertain")
        if row.creation_state == Checkout.CreationState.CREATING:
            raise CheckoutError("checkout_creation_in_progress")
        row.creation_state = Checkout.CreationState.CREATING
        row.creation_started_at = timezone.now()
        row.request_payload = payload
        row.save(update_fields=["creation_state", "creation_started_at", "request_payload", "updated_at"])

    try:
        resp = asyncio.run(_create_link(payload))
        if not isinstance(resp, dict) or not (resp.get("url") or resp.get("checkout_url") or resp.get("link")):
            raise CheckoutError("invalid_checkout_response")
    except Exception as exc:
        # An explicit 4xx rejection is retryable locally. Timeout, crash or malformed success
        # may have created a live link: never issue another POST blindly.
        rejected = (
            isinstance(exc, InfinitePayError)
            and exc.status_code is not None
            and 400 <= exc.status_code < 500
            and exc.status_code not in (408, 409)
        )
        code = "infinitepay_create_rejected" if rejected else "checkout_creation_uncertain"
        row.creation_state = Checkout.CreationState.PENDING if rejected else Checkout.CreationState.UNCERTAIN
        row.response_payload = {"error_code": code}
        row.save(update_fields=["creation_state", "response_payload", "updated_at"])
        logger.warning("checkout_create_failed", external_id=order_nsu, code=code)
        raise CheckoutError(code) from exc

    row.checkout_url = resp.get("url") or resp.get("checkout_url") or resp.get("link")
    row.slug = resp.get("slug")
    row.request_payload = payload
    row.response_payload = resp
    row.creation_state = Checkout.CreationState.READY
    row.save(update_fields=["checkout_url", "slug", "request_payload", "response_payload", "creation_state", "updated_at"])
    logger.info(
        "checkout_created", external_id=order_nsu, slug=row.slug, amount_cents=cents
    )
    return row
