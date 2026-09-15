"""Emissão de QR Code PIX **estático direto** (INBOUND) via Asaas.

Substitui o fluxo de fatura/payment (POST /v3/payments) na cobrança de matrícula PIX,
usando o endpoint de menor custo:  POST /v3/pix/qrCodes/static

Vantagem comercial
------------------
- Cobrança padrão (/v3/payments): gera uma fatura gerenciada pelo Asaas com custo por emissão
  e por recebimento.
- QR Code estático (/v3/pix/qrCodes/static): gera apenas o payload copia-e-cola e PNG —
  custo transacional drasticamente reduzido (ou isento conforme plano da conta).

Compatibilidade com o resto do sistema
--------------------------------------
O Payment retornado preserva os mesmos campos consumidos pelo lead/service.py e pelo frontend
(qrcode_payload, qrcode_image/pix_qr_image), garantindo que o wizard do aluno continue
sem alterações.

Reconciliação por Webhook
--------------------------
O Asaas dispara PAYMENT_RECEIVED com `externalReference` igual ao nosso `pid` e com
`pixTransaction.endToEndId`. O receiver (webhooks.py) encontra o Payment por `payment_id=ext_ref`
(CHARGE lookup) ou pelo novo kind=static_qr.  Adicionamos KIND=STATIC_PIX_QR para diferenciar.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal, InvalidOperation

import structlog
from django.db import IntegrityError

from .client import AsaasError, get_client
from .models import Payment
from .qr import save_pix_qr_png, qr_url_for

logger = structlog.get_logger()


class StaticQrError(Exception):
    pass


def _parse_amount(amount) -> Decimal:
    if amount is None:
        raise StaticQrError("amount_required")
    try:
        amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise StaticQrError(f"invalid_amount: {amount}") from e
    if amt <= 0:
        raise StaticQrError("amount_must_be_positive")
    return amt


def _reusable_or_new_payment_id(payment_id: str | None, amount: Decimal):
    """Resolve o `payment_id` do QR: `(pid, linha_reaproveitável|None)`.

    IDEMPOTÊNCIA (issue #158): o mesmo `payment_id` pedido DE NOVO devolve o QR que já existe em
    vez de estourar. O `pid` do lead é determinístico (`lead_<hex>_<checkout.pk>`), então o
    segundo clique no link curto — ou um retry da task — caía em `payment_id_already_exists`, a
    view engolia e o lead via 503 pra sempre. QR estático é recurso ESTÁVEL: mesmo valor, mesma
    chave, mesmo payload — reemitir não faz sentido, reaproveitar faz.

    Só reaproveita o que é seguro:
      - `kind` tem que ser `static_pix_qr` (colisão com fatura/transferência é erro de verdade);
      - `status` tem que ser `PENDING` (pago/cancelado/expirado NÃO se reabre);
      - o valor tem que ser o MESMO (senão devolveríamos um QR que cobra outro preço).
    """
    pid = payment_id or f"sqr_{uuid.uuid4().hex[:16]}"
    row = Payment.objects.filter(payment_id=pid).first()
    if row is None:
        return pid, None
    if row.kind != Payment.Kind.STATIC_PIX_QR:
        raise StaticQrError(f"payment_id_already_exists: kind={row.kind}")
    if row.status != "PENDING":
        raise StaticQrError(f"payment_id_already_exists: status={row.status}")
    if row.amount != amount:
        raise StaticQrError(
            f"payment_id_amount_mismatch: existente={row.amount} pedido={amount}"
        )
    return pid, row


async def _fetch_pix_address_key() -> str:
    """Retorna a primeira chave PIX ativa cadastrada na conta Asaas."""
    from core.system_config import get_setting

    # Chave configurada manualmente tem prioridade
    configured_key = get_setting("ASAAS_PIX_ADDRESS_KEY")
    if configured_key:
        return configured_key

    async with get_client() as c:
        resp = await c.list_pix_address_keys({"status": "ACTIVE", "limit": 1})
        data = resp.get("data") or []
        if not data:
            raise StaticQrError("no_active_pix_address_key_found")
        return data[0]["key"]


async def _create_qr_with_gateway(pix_key: str, value: float, pid: str, description: str | None) -> dict:
    async with get_client() as c:
        payload = {
            "addressKey": pix_key,
            "value": value,
            "description": description or f"Matricula {pid}",
            "format": "ALL",                # retorna payload + encodedImage
            "allowsMultiplePayments": False,  # uso único por checkout
            "externalReference": pid,
        }
        return await c.create_static_qr_code(payload)


def create_pix_qr(
    *,
    amount,
    description: str | None = None,
    payment_id: str | None = None,
    pix_address_key: str | None = None,
) -> Payment:
    """Emite um QR Code PIX estático com valor definido. Retorna o Payment persistido.

    - Não cria fatura/customer no Asaas (custo menor).
    - Retorna Payment(kind=STATIC_PIX_QR) com qrcode_payload e pix_qr_image já populados.
    - Compatível com o receiver de webhook existente via externalReference == payment_id.
    - IDEMPOTENTE por `payment_id`: pedido repetido devolve o QR já emitido, SEM tocar no Asaas.
    """
    amt = _parse_amount(amount)
    pid, existing = _reusable_or_new_payment_id(payment_id, amt)
    if existing is not None:
        logger.info(
            "static_pix_qr_reused",
            payment_id=pid,
            asaas_qr_id=existing.asaas_id,
            amount=str(existing.amount),
        )
        return existing

    try:
        pix_key = pix_address_key or asyncio.run(_fetch_pix_address_key())
    except AsaasError as e:
        raise StaticQrError(f"asaas_pix_key_fetch_failed: {e.body}") from e

    try:
        created = asyncio.run(
            _create_qr_with_gateway(pix_key, float(amt), pid, description)
        )
    except AsaasError as e:
        raise StaticQrError(f"asaas_static_qr_create_failed: {e.body}") from e

    encoded = created.get("encodedImage")
    if encoded:
        try:
            save_pix_qr_png(pid, encoded)
        except Exception as exc:
            logger.error("static_qr_save_failed", payment_id=pid, error=str(exc))

    try:
        row = Payment.objects.create(
            payment_id=pid,
            kind=Payment.Kind.STATIC_PIX_QR,
            billing_type="PIX",
            qrcode_payload=created.get("payload"),
            pix_qr_image=encoded,
            amount=amt,
            description=description,
            status="PENDING",
            asaas_id=created.get("id"),  # ID do QR Code no Asaas (ex: V7MEMPRE000###ASA)
        )
    except IntegrityError:
        # corrida: outro worker gravou o MESMO pid entre a checagem e o insert (`payment_id` é
        # unique). Não perde o clique do lead — devolve a linha que ganhou a corrida.
        row = Payment.objects.filter(payment_id=pid).first()
        if row is None:
            raise
        logger.warning("static_pix_qr_race_reused", payment_id=pid, asaas_id=row.asaas_id)
        return row

    logger.info(
        "static_pix_qr_created",
        payment_id=pid,
        asaas_qr_id=created.get("id"),
        amount=str(amt),
        pix_key=pix_key,
    )
    return row


def cancel_pix_qr(payment_id: str) -> Payment:
    """Cancela (remove) um QR Code estático no Asaas."""
    row = Payment.objects.filter(
        payment_id=payment_id, kind=Payment.Kind.STATIC_PIX_QR
    ).first()
    if row is None:
        raise StaticQrError("not_found")
    if row.status in {"PAID", "CANCELLED", "EXPIRED"}:
        if row.status == "CANCELLED":
            return row
        raise StaticQrError(f"cannot_cancel_status: {row.status}")

    if row.asaas_id:
        try:
            asyncio.run(_delete_qr(row.asaas_id))
        except AsaasError as e:
            logger.warning("static_qr_delete_failed", payment_id=payment_id, error=str(e.body))

    row.status = "CANCELLED"
    row.save()
    logger.info("static_pix_qr_cancelled", payment_id=payment_id, asaas_id=row.asaas_id)
    return row


async def _delete_qr(asaas_id: str) -> None:
    async with get_client() as c:
        await c.delete_static_qr_code(asaas_id)


def to_dict(row: Payment) -> dict:
    return {
        "payment_id": row.payment_id,
        "status": row.status,
        "billing_type": "PIX",
        "asaas_id": row.asaas_id,
        "amount": str(row.amount),
        "qr": {
            "payload": row.qrcode_payload,
            "image_url": qr_url_for(row.payment_id),
        },
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
