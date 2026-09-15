"""Pagamento de BOLETO / conta de consumo (saída) — espelha `payout.py` (PIX por chave).

Paga pela LINHA DIGITÁVEL (`identificationField`) via Asaas `/v3/bill`. Usado pelo pagamento avulso
do staff (pagar um boleto de despesa/fornecedor). Persiste como Payment(kind=boleto).

Money-safe (CONVENTION §8), idêntico ao payout:
 - **idempotência:** `idempotency_key=payment_id` (re-submit do mesmo recurso -> 409, nunca duplica);
   Payment já existente com aquele payment_id devolve sem reenviar.
 - **persiste a intenção ANTES de chamar o Asaas** (Payment SUBMITTING).
 - **falha incerta de rede** deixa SUBMITTING p/ reconciliação, **não marca FAILED às cegas**.

A reconciliação do status é por LEITURA ATIVA (`refresh_boleto` -> get_bill); o enum exato do /v3/bill
mapeia abaixo (BANK_PROCESSING/PENDING são não-terminais).
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal, InvalidOperation

import structlog

from .client import AsaasError, get_client
from .models import Payment

logger = structlog.get_logger()

# status do /v3/bill do Asaas -> status interno do Payment (outbound).
_BILL_TO_STATUS = {
    "PAID": "PAID",
    "CONFIRMED": "PAID",
    "DONE": "PAID",
    "FAILED": "FAILED",
    "CANCELLED": "FAILED",
    "REFUSED": "FAILED",
}


class BillPayError(Exception):
    """Erro de borda do pagamento de boleto (entrada inválida ou recusa do Asaas)."""


def _parse_amount(amount) -> Decimal | None:
    """Valor é OPCIONAL no boleto (o Asaas lê do próprio documento). Se vier, valida > 0."""
    if amount is None or amount == "":
        return None
    try:
        amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise BillPayError("invalid_amount") from e
    if amt <= 0:
        raise BillPayError("amount_must_be_positive")
    return amt


def pay_bill(*, line_code, amount=None, description=None, payment_id=None) -> Payment:
    """Cria e submete o pagamento de um boleto pela linha digitável. Retorna o Payment.

    `line_code` = linha digitável (47/48 dígitos) ou código de barras. `amount` opcional (o Asaas
    usa o valor do próprio boleto se omitido). Idempotente por `payment_id`.
    """
    if not line_code:
        raise BillPayError("line_code_required")
    amt = _parse_amount(amount)

    pid = payment_id or f"bill_{uuid.uuid4().hex[:16]}"

    existing = Payment.objects.filter(payment_id=pid).first()
    if existing is not None:
        return existing  # idempotência local: não re-paga (CONVENTION §8)

    row = Payment.objects.create(
        payment_id=pid,
        kind=Payment.Kind.BOLETO,
        amount=amt
        or Decimal("0"),  # 0 = "ler do boleto"; reconciliação atualiza pelo Asaas
        status="SUBMITTING",
        description=description or f"boleto {pid}",
    )

    try:
        res = asyncio.run(_send(line_code, amt, pid, row.description))
    except AsaasError as e:
        row.status = "FAILED"
        row.last_error = f"asaas {e.status_code}: {e.body}"
        row.save(update_fields=["status", "last_error", "updated_at"])
        logger.error("billpay_rejected", payment_id=pid, status_code=e.status_code)
        raise BillPayError(f"asaas_rejected: {e.body}") from e
    except Exception as e:
        # falha incerta (timeout/transporte): NÃO sabemos se pagou -> deixa SUBMITTING (idempotency resolve).
        row.last_error = f"submit_uncertain: {type(e).__name__}"
        row.save(update_fields=["last_error", "updated_at"])
        logger.error("billpay_submit_uncertain", payment_id=pid, error=type(e).__name__)
        raise BillPayError("submit_uncertain") from e

    row.asaas_id = res.get("id")
    asaas_status = res.get("status") or "SUBMITTED"
    row.status = _BILL_TO_STATUS.get(str(asaas_status).upper(), "SUBMITTED")
    paid_value = res.get("value")
    if paid_value is not None:
        try:
            row.amount = Decimal(str(paid_value)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            pass
    row.save(update_fields=["asaas_id", "status", "amount", "updated_at"])
    logger.info(
        "billpay_submitted",
        payment_id=pid,
        asaas_id=row.asaas_id,
        amount=str(row.amount),
        asaas_status=asaas_status,
    )
    return row


def get_boleto(payment_id: str) -> Payment:
    """Lê o Payment local (kind=boleto)."""
    row = Payment.objects.filter(
        payment_id=payment_id, kind=Payment.Kind.BOLETO
    ).first()
    if row is None:
        raise BillPayError("not_found")
    return row


def refresh_boleto(payment_id: str) -> Payment:
    """Reconciliação ATIVA: lê o bill no Asaas e atualiza o Payment local. Retorna o Payment."""
    row = get_boleto(payment_id)
    if not row.asaas_id:
        return row
    try:
        bill = asyncio.run(_get_bill(row.asaas_id))
    except AsaasError as e:
        raise BillPayError(f"asaas_read_failed: {e.status_code}") from e

    mapped = _BILL_TO_STATUS.get((bill.get("status") or "").upper())
    if mapped and row.status != mapped:
        row.status = mapped
        fields = ["status", "updated_at"]
        if mapped == "FAILED":
            row.last_error = (
                bill.get("failReason") or f"bill_status={bill.get('status')}"
            )
            fields.append("last_error")
        row.save(update_fields=fields)
    return row


async def _send(line_code, amount, payment_id, description) -> dict:
    body: dict = {"identificationField": line_code, "description": description}
    if amount is not None:
        body["value"] = float(amount)
    async with get_client() as c:
        return await c.pay_bill(body, idempotency_key=payment_id)


async def _get_bill(bill_id: str) -> dict:
    async with get_client() as c:
        return await c.get_bill(bill_id)
