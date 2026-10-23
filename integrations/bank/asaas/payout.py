"""Payout PIX (saída) — 1a-vi. Porte enxuto da lógica de saída do legado (payment.py) pro mono.

Cria a transferência PIX pra uma chave, persiste como Payment(kind=pixkey) e deixa o status ser
guiado pelo webhook (`TRANSFER_DONE` -> PAID), reusando o que já existe: `transfer_validation`
(aprova o saque casando por asaas_id) e `webhooks._apply_payout`.

Money-safe (CONVENTION §8):
 - **idempotência:** `idempotency_key=payment_id` (re-submit do mesmo recurso -> 409, nunca duplica);
   se já existe Payment com aquele payment_id, devolve sem reenviar.
 - **persiste a intenção ANTES de chamar o Asaas** (Payment SUBMITTING) — id determinístico.
 - **falha incerta de rede** (não se sabe se a transfer foi criada) deixa SUBMITTING p/ reconciliação,
   **não marca FAILED às cegas** (o idempotency_key resolve no retry).

O envio é síncrono e idempotente; a fila de negócio fica em `finance.PaymentRequest`.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from decimal import Decimal, InvalidOperation
from datetime import timedelta
from zoneinfo import ZoneInfo

import structlog
from django.conf import settings
from django.db import transaction

from .client import AsaasError, get_client
from .models import Payment

logger = structlog.get_logger()


class PayoutError(Exception):
    """Erro de borda do payout (entrada inválida ou recusa do Asaas)."""


def create_payout(*, amount, pix_key, description=None, payment_id=None) -> Payment:
    """Cria e submete um payout PIX. Retorna o Payment (status SUBMITTED em sucesso).

    `amount` em reais (Decimal/str/num), `pix_key` = chave PIX de destino (CPF/CNPJ/email/phone/EVP).
    """
    amt = _parse_amount(amount)
    if not pix_key:
        raise PayoutError("pix_key_required")

    pid = payment_id or f"payout_{uuid.uuid4().hex[:16]}"

    # idempotência: payout já registrado com esse id -> devolve, não reenvia (CONVENTION §8)
    existing = Payment.objects.filter(payment_id=pid).first()
    if existing is not None:
        return existing

    # persiste a intenção ANTES de chamar o Asaas
    row = Payment.objects.create(
        payment_id=pid,
        kind=Payment.Kind.PIXKEY,
        amount=amt,
        status="SUBMITTING",
        description=description or f"payout {pid}",
    )

    allow_sandbox = (
        getattr(settings, "ASAAS_ENABLE_SANDBOX_TRANSFERS", False)
        or os.environ.get("ASAAS_ENABLE_SANDBOX_TRANSFERS", "").lower() in ("1", "true", "yes")
    )
    if settings.TEST_EXTERNAL_ADAPTERS or (settings.APP_ENV != "prod" and not allow_sandbox):
        from core.test_adapters import payout_response

        response = payout_response(payment_id=pid)
        row.asaas_id = response["id"]
        row.status = "SUBMITTED"
        row.save(update_fields=["asaas_id", "status", "updated_at"])
        logger.info("payout_stubbed", payment_id=pid, amount=str(amt))
        return row

    try:
        res = asyncio.run(_send(amt, pix_key, pid, row.description))
    except AsaasError as e:
        row.status = "FAILED"
        row.last_error = f"asaas {e.status_code}: {e.body}"
        row.save(update_fields=["status", "last_error", "updated_at"])
        logger.error("payout_rejected", payment_id=pid, status_code=e.status_code)
        raise PayoutError(f"asaas_rejected: {e.body}") from e
    except Exception as e:
        # falha incerta (timeout/transporte): NÃO sabemos se a transfer foi criada -> deixa
        # SUBMITTING (sem marcar FAILED); o idempotency_key resolve num re-submit. (CONVENTION §8)
        row.last_error = f"submit_uncertain: {type(e).__name__}"
        row.save(update_fields=["last_error", "updated_at"])
        logger.error("payout_submit_uncertain", payment_id=pid, error=type(e).__name__)
        raise PayoutError("submit_uncertain") from e

    row.asaas_id = res.get("id")
    row.status = "SUBMITTED"
    row.save(update_fields=["asaas_id", "status", "updated_at"])
    logger.info(
        "payout_submitted", payment_id=pid, asaas_id=row.asaas_id, amount=str(amt)
    )
    return row


def get_payout(payment_id: str) -> Payment:
    """Lê um payout pelo payment_id (só kind=pixkey)."""
    row = Payment.objects.filter(
        payment_id=payment_id, kind=Payment.Kind.PIXKEY
    ).first()
    if row is None:
        raise PayoutError("not_found")
    return row


def refresh_payout(payment_id: str) -> Payment:
    """Recover a missed callback through GET only; never resend uncertain money."""
    row = get_payout(payment_id)
    if row.status in ("PAID", "FAILED", "CANCELLED") or settings.TEST_EXTERNAL_ADAPTERS or settings.APP_ENV == "test":
        return row
    try:
        data = asyncio.run(_lookup_transfer(row))
    except AsaasError as exc:
        raise PayoutError(f"reconcile_http_{exc.status_code}") from exc
    except PayoutError:
        raise
    except Exception as exc:
        raise PayoutError("reconcile_unavailable") from exc
    if Decimal(str(data.get("value", "0"))).quantize(Decimal("0.01")) != row.amount:
        raise PayoutError("transfer_amount_mismatch")
    mapping = {"DONE": "PAID", "FAILED": "FAILED", "CANCELLED": "CANCELLED", "PENDING": "SUBMITTED", "IN_BANK_PROCESSING": "SUBMITTED", "BLOCKED": "SUBMITTED"}
    status = mapping.get(data.get("status"))
    if status is None:
        raise PayoutError("transfer_unknown_status")
    with transaction.atomic():
        row = Payment.objects.select_for_update().get(pk=row.pk)
        if row.status not in ("PAID", "FAILED", "CANCELLED"):
            row.asaas_id = data["id"]
            row.status = status
            row.last_error = data.get("failReason") or None
            row.save(update_fields=["asaas_id", "status", "last_error", "updated_at"])
    return row


async def _lookup_transfer(row: Payment) -> dict:
    async with get_client() as client:
        if row.asaas_id:
            data = await client.get_transfer(row.asaas_id)
            if data.get("id") != row.asaas_id or data.get("externalReference") not in (None, "", row.payment_id):
                raise PayoutError("transfer_reference_mismatch")
            return data
        # The documented listing supports date filters, not reference filters.
        # Filter the bounded pages locally by our exact immutable reference.
        day = row.created_at.astimezone(ZoneInfo("America/Sao_Paulo")).date()
        matches = []
        for offset in range(0, 1000, 100):
            response = await client.list_transfers({"dateCreated[ge]": (day-timedelta(days=1)).isoformat(), "dateCreated[le]": (day+timedelta(days=1)).isoformat(), "limit": 100, "offset": offset})
            matches.extend(item for item in response.get("data", []) if item.get("externalReference") == row.payment_id)
            if not response.get("hasMore"):
                break
        else:
            raise PayoutError("transfer_search_incomplete")
        if len(matches) != 1:
            raise PayoutError("transfer_not_found" if not matches else "transfer_ambiguous")
        return matches[0]


def to_dict(row: Payment) -> dict:
    return {
        "payment_id": row.payment_id,
        "kind": row.kind,
        "status": row.status,
        "asaas_id": row.asaas_id,
        "amount": str(row.amount),
        "description": row.description,
        "last_error": row.last_error,
    }


def _parse_amount(amount) -> Decimal:
    try:
        amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise PayoutError("invalid_amount") from e
    if amt <= 0:
        raise PayoutError("amount_must_be_positive")
    return amt


async def _send(
    amount: Decimal, pix_key: str, payment_id: str, description: str
) -> dict:
    async with get_client() as c:
        return await c.create_transfer(
            {
                "value": float(amount),
                "pixAddressKey": pix_key,
                "externalReference": payment_id,
                "description": description,
            },
            idempotency_key=payment_id,
        )
