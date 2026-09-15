"""Serviço de pagamento de PIX QR code (copia-e-cola, OUTBOUND) — espelha `payout.py` (pixkey).

Usado pelo `finance/fees` (pagar despesas/fornecedores). Idempotente por `payment_id` (= o
`external_reference` da fila). ⚠️ O evento de webhook EXATO do Asaas pro QR-pay ainda **não foi
confirmado num teste real** → a reconciliação aqui é por **LEITURA ATIVA** (`get_pix_transaction`),
não só pelo webhook. Ver `plan/4-financeiro-fees.md` §5.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation

import structlog

from .client import AsaasError, get_client
from .models import Payment

logger = structlog.get_logger()

# status do PIX transaction do Asaas -> status interno do Payment (outbound).
# «PENDÊNCIA»: enum exato a confirmar no teste real (plan/4-financeiro-fees.md §5).
_PIXTX_TO_STATUS = {
    "DONE": "PAID",
    "CONFIRMED": "PAID",
    "CANCELLED": "FAILED",
    "ERROR": "FAILED",
    "REFUSED": "FAILED",
}


class QrPayError(Exception):
    pass


def _parse_amount(amount) -> Decimal:
    try:
        amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise QrPayError("invalid_amount") from e
    if amt <= 0:
        raise QrPayError("amount_must_be_positive")
    return amt


def decode_qr(payload: str) -> dict:
    """Decodifica um PIX QR code no Asaas (resolve o payload dinâmico de cobrança) — LEITURA, não paga.

    Retorna o dict do Asaas. Campos relevantes: `type`, `value`, `totalValue`, `dueDate`
    (None p/ QR estático/imediato), `canBePaid`, `cannotBePaidReason`, `receiver`.
    Levanta `QrPayError` em payload vazio ou falha de leitura no Asaas.
    """
    if not payload:
        raise QrPayError("qr_payload_required")
    try:
        return asyncio.run(_decode(payload))
    except AsaasError as e:
        raise QrPayError(f"decode_failed: {e.status_code}: {e.body}") from e


async def _decode(payload: str) -> dict:
    async with get_client() as c:
        return await c.decode_qr_code(payload)


def pay_qr_code(*, amount, qr_payload, payment_id, description=None) -> Payment:
    """Paga um PIX QR code (copia-e-cola). Retorna o Payment (kind=qrcode). Idempotente por payment_id."""
    amt = _parse_amount(amount)
    if not qr_payload:
        raise QrPayError("qr_payload_required")

    existing = Payment.objects.filter(payment_id=payment_id).first()
    if existing is not None:
        return existing  # idempotência local: não re-paga (CONVENTION §8)

    row = Payment.objects.create(
        payment_id=payment_id,
        kind=Payment.Kind.QRCODE,
        amount=amt,
        status="SUBMITTING",
        qrcode_payload=qr_payload,
        description=description or f"fee {payment_id}",
    )

    try:
        res = asyncio.run(_send(qr_payload, amt, payment_id, row.description))
    except AsaasError as e:
        row.status = "FAILED"
        row.last_error = f"asaas {e.status_code}: {e.body}"
        row.save(update_fields=["status", "last_error", "updated_at"])
        logger.error("qrpay_rejected", payment_id=payment_id, status_code=e.status_code)
        raise QrPayError(f"asaas_rejected: {e.body}") from e
    except Exception as e:
        # falha incerta (timeout/transporte): NÃO sabemos se pagou -> deixa SUBMITTING (idempotency_key resolve).
        row.last_error = f"submit_uncertain: {type(e).__name__}"
        row.save(update_fields=["last_error", "updated_at"])
        logger.error(
            "qrpay_submit_uncertain", payment_id=payment_id, error=type(e).__name__
        )
        raise QrPayError("submit_uncertain") from e

    row.asaas_id = res.get("id")
    asaas_status = res.get("status") or "SUBMITTED"
    row.status = _PIXTX_TO_STATUS.get(str(asaas_status).upper(), "SUBMITTED")
    row.save(update_fields=["asaas_id", "status", "updated_at"])
    logger.info(
        "qrpay_submitted",
        payment_id=payment_id,
        asaas_id=row.asaas_id,
        amount=str(amt),
        asaas_status=asaas_status,
    )
    return row


async def _send(qr_payload, amount, payment_id, description) -> dict:
    async with get_client() as c:
        return await c.pay_qr_code(
            qr_payload, float(amount), description, idempotency_key=payment_id
        )


def get_qr_payment(payment_id: str) -> Payment:
    """Lê o Payment local (kind=qrcode)."""
    row = Payment.objects.filter(
        payment_id=payment_id, kind=Payment.Kind.QRCODE
    ).first()
    if row is None:
        raise QrPayError("not_found")
    return row


def refresh_qr_payment(payment_id: str) -> Payment:
    """Reconciliação ATIVA: lê o PIX transaction no Asaas e atualiza o Payment local. Retorna o Payment."""
    row = get_qr_payment(payment_id)
    if not row.asaas_id:
        return row
    try:
        tx = asyncio.run(_get_tx(row.asaas_id))
    except AsaasError as e:
        raise QrPayError(f"asaas_read_failed: {e.status_code}") from e

    mapped = _PIXTX_TO_STATUS.get((tx.get("status") or "").upper())
    if mapped and row.status != mapped:
        row.status = mapped
        fields = ["status", "updated_at"]
        if mapped == "FAILED":
            row.last_error = tx.get("failReason") or f"pixtx_status={tx.get('status')}"
            fields.append("last_error")
        row.save(update_fields=fields)
    return row


async def _get_tx(transaction_id: str) -> dict:
    async with get_client() as c:
        return await c.get_pix_transaction(transaction_id)
