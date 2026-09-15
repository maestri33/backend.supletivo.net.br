"""Charge service — cobranças recebidas via Asaas (Pix, Cartão, Boleto e Fatura).

Fluxo de criação (CONVENTION §8 — caminho do dinheiro idempotente):
  1. find_or_create customer (payer)
  2. POST /v3/payments com billingType (PIX, BOLETO, CREDIT_CARD ou UNDEFINED)
  3. Se PIX: busca pixQrCode ({payload, encodedImage})
  4. Se BOLETO: busca ou extrai linha digitável ({identificationField, nossoNumero, barCode, bankSlipUrl})
  5. Se CREDIT_CARD: processa tokenização ou autorização com parcelamento
  6. Persiste Payment(kind=charge, billing_type=..., status=...)
"""

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import structlog
from django.conf import settings

from . import customers
from .client import AsaasError, get_client
from .models import Payment
from .qr import qr_url_for, save_pix_qr_png

logger = structlog.get_logger()

_TERMINAL = {"PAID", "EXPIRED", "CANCELLED", "REFUNDED"}


class ChargeError(Exception):
    pass


def _new_or_check_payment_id(payment_id: str | None) -> str:
    pid = payment_id or f"pay_{uuid.uuid4().hex[:16]}"
    if Payment.objects.filter(payment_id=pid).exists():
        raise ChargeError("payment_id_already_exists")
    return pid


def _resolve_due_date(due_date: str | None) -> date:
    if not due_date:
        return date.today() + timedelta(days=settings.ASAAS_CHARGE_DUE_DAYS)
    try:
        parsed = date.fromisoformat(due_date)
    except ValueError as e:
        raise ChargeError(f"invalid_due_date: {e}") from e
    if parsed < date.today():
        raise ChargeError(f"invalid_due_date: {due_date} está no passado")
    return parsed


async def _create_payment_with_gateway(
    customer_asaas_id: str,
    value: float,
    due: date,
    description: str | None,
    pid: str,
    billing_type: str = "PIX",
    success_url: str | None = None,
    credit_card: dict | None = None,
    credit_card_holder: dict | None = None,
    credit_card_token: str | None = None,
    installment_count: int | None = None,
    installment_value: float | None = None,
    fine: dict | None = None,
    interest: dict | None = None,
    postal_service: bool = False,
):
    async with get_client() as c:
        payload = {
            "customer": customer_asaas_id,
            "billingType": billing_type.upper(),
            "value": value,
            "dueDate": due.isoformat(),
            "description": description or f"charge {pid}",
            "externalReference": pid,
            "postalService": postal_service,
        }
        if success_url:
            payload["callback"] = {"successUrl": success_url, "autoRedirect": True}

        if fine:
            payload["fine"] = fine
        if interest:
            payload["interest"] = interest

        if billing_type.upper() == "CREDIT_CARD":
            if credit_card_token:
                payload["creditCardToken"] = credit_card_token
            elif credit_card:
                payload["creditCard"] = credit_card
            if credit_card_holder:
                payload["creditCardHolderInfo"] = credit_card_holder
            if installment_count and installment_count > 1:
                payload["installmentCount"] = installment_count
                if installment_value:
                    payload["installmentValue"] = float(installment_value)

        created = await c.create_payment(payload)
        qr = None
        ident_field = None

        if billing_type.upper() in ("PIX", "UNDEFINED"):
            try:
                qr = await c.get_payment_pix_qr_code(created["id"])
            except AsaasError as e:
                logger.warning(
                    "charge_qr_fetch_failed",
                    asaas_id=created.get("id"),
                    body=str(e.body),
                )

        if billing_type.upper() in ("BOLETO", "UNDEFINED"):
            try:
                ident_field = await c.get_payment_identification_field(created["id"])
            except AsaasError as e:
                logger.warning(
                    "charge_identification_field_fetch_failed",
                    asaas_id=created.get("id"),
                    body=str(e.body),
                )

        return created, qr, ident_field


def create_charge(
    *,
    amount,
    payer,
    billing_type: str = "PIX",
    description=None,
    due_date=None,
    payment_id=None,
    success_url=None,
    credit_card: dict | None = None,
    credit_card_holder: dict | None = None,
    credit_card_token: str | None = None,
    installment_count: int | None = None,
    installment_value=None,
    fine: dict | None = None,
    interest: dict | None = None,
    postal_service: bool = False,
) -> Payment:
    """Cria uma cobrança (Pix, Cartão de Crédito ou Boleto). Retorna o Payment persistido.

    - PIX: gera e armazena QR code e copia-e-cola.
    - BOLETO: extrai linha digitável e PDF (bankSlipUrl).
    - CREDIT_CARD: processa tokenização/autorização e dados do cartão.
    """
    if amount is None:
        raise ChargeError("amount_required")
    try:
        amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as e:
        raise ChargeError(f"invalid_amount: {amount}") from e
    if amt <= 0:
        raise ChargeError("invalid_amount")

    cust = customers.find_or_create(payer)
    pid = _new_or_check_payment_id(payment_id)
    due = _resolve_due_date(due_date)
    norm_billing_type = (billing_type or "PIX").strip().upper()

    try:
        created, qr, ident_field = asyncio.run(
            _create_payment_with_gateway(
                customer_asaas_id=cust.asaas_id,
                value=float(amt),
                due=due,
                description=description,
                pid=pid,
                billing_type=norm_billing_type,
                success_url=success_url,
                credit_card=credit_card,
                credit_card_holder=credit_card_holder,
                credit_card_token=credit_card_token,
                installment_count=installment_count,
                installment_value=float(installment_value)
                if installment_value
                else None,
                fine=fine,
                interest=interest,
                postal_service=postal_service,
            )
        )
    except AsaasError as e:
        raise ChargeError(f"asaas_charge_create_failed: {e.body}") from e

    encoded = (qr or {}).get("encodedImage")
    if encoded:
        try:
            save_pix_qr_png(pid, encoded)
        except Exception as exc:
            logger.error("qrcode_save_failed", payment_id=pid, error=str(exc))

    # Extrai metadados bancários
    bank_slip = created.get("bankSlipUrl")
    ident_line = (ident_field or {}).get("identificationField") or created.get(
        "identificationField"
    )
    nosso_num = created.get("nossoNumero")
    card_info = created.get("creditCard") or {}
    card_brand = card_info.get("creditCardBrand")
    card_last4 = card_info.get("creditCardNumber")
    net_val = created.get("netValue")
    net_val_dec = (
        Decimal(str(net_val)).quantize(Decimal("0.01")) if net_val is not None else None
    )
    initial_status = (created.get("status") or "PENDING").upper()

    row = Payment.objects.create(
        payment_id=pid,
        kind=Payment.Kind.CHARGE,
        billing_type=norm_billing_type,
        customer=cust,
        qrcode_payload=(qr or {}).get("payload"),
        pix_qr_image=encoded,
        bank_slip_url=bank_slip,
        identification_field=ident_line,
        nosso_numero=nosso_num,
        installment_count=installment_count,
        credit_card_brand=card_brand,
        credit_card_last_digits=card_last4[-4:] if card_last4 else None,
        net_value=net_val_dec,
        amount=amt,
        description=description,
        due_date=due,
        status=initial_status if initial_status in ("PAID", "CONFIRMED") else "PENDING",
        asaas_id=created["id"],
    )
    # invoiceUrl = fatura hospedada do Asaas
    row.invoice_url = created.get("invoiceUrl")
    logger.info(
        "charge_created",
        payment_id=pid,
        asaas_id=created["id"],
        billing_type=norm_billing_type,
        amount=str(amt),
    )
    return row


def get_charge(payment_id: str) -> Payment:
    row = Payment.objects.filter(
        payment_id=payment_id, kind=Payment.Kind.CHARGE
    ).first()
    if row is None:
        raise ChargeError("not_found")
    return row


async def _delete(asaas_id):
    async with get_client() as c:
        return await c.delete_payment(asaas_id)


def cancel_charge(payment_id: str) -> Payment:
    row = get_charge(payment_id)
    if row.status in _TERMINAL:
        if row.status == "CANCELLED":
            return row
        raise ChargeError(f"cannot_cancel_status: {row.status}")
    if row.asaas_id:
        try:
            asyncio.run(_delete(row.asaas_id))
        except AsaasError as e:
            row.last_error = str(e.body)[:500]
            row.save(update_fields=["last_error"])
            raise ChargeError(f"asaas_charge_delete_failed: {e.body}") from e
    row.status = "CANCELLED"
    row.save()
    logger.info("charge_cancelled", payment_id=payment_id, asaas_id=row.asaas_id)
    return row


def to_dict(row: Payment) -> dict:
    return {
        "payment_id": row.payment_id,
        "status": row.status,
        "billing_type": row.billing_type,
        "asaas_id": row.asaas_id,
        "amount": str(row.amount),
        "net_value": str(row.net_value) if row.net_value is not None else None,
        "description": row.description,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "customer": str(row.customer.external_id) if row.customer_id else None,
        "qr": {"payload": row.qrcode_payload, "image_url": qr_url_for(row.payment_id)},
        "bank_slip_url": row.bank_slip_url,
        "identification_field": row.identification_field,
        "nosso_numero": row.nosso_numero,
        "installment_count": row.installment_count,
        "credit_card_brand": row.credit_card_brand,
        "credit_card_last_digits": row.credit_card_last_digits,
        "invoice_url": getattr(row, "invoice_url", None),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }

