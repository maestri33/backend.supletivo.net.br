"""Superfície in-process do finance pra PAGAMENTO AVULSO do staff (kind=manual).

Staff envia um pagamento a um TERCEIRO LIVRE (não precisa ser usuário da plataforma): PIX por chave
OU boleto (linha digitável), pela conta Asaas, e fica registrado na plataforma (Victor 2026-06-29).
**Mesma fila** (`PaymentRequest`) de comissões/fees — é tudo dinheiro saindo da mesma conta Asaas; o
worker (`finance.interface.payout`) paga e reconcilia. O valor vem do CALLER (a conta real), NUNCA do
`.env` (§8). Opcionalmente anexa um comprovante (recibo) — path relativo já salvo pelo endpoint.
"""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal

import structlog
from django.db import IntegrityError, transaction
from django.utils import timezone

from finance.models import PaymentRequest

logger = structlog.get_logger()


class ManualPaymentError(Exception):
    """Erro de borda do pagamento avulso (entrada inválida)."""


def _ref_for(idempotency_key) -> str:
    """External_reference do avulso. Com Idempotency-Key: determinística (`manual_<sha256>`), então um
    retry com a MESMA key colide no `unique(external_reference)` e devolve o pagamento já criado em vez
    de disparar um 2º PIX. Sem key: aleatória (compat — nunca colide)."""
    if idempotency_key:
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]
        return f"manual_{digest}"
    return f"manual_{uuid.uuid4().hex[:16]}"


def _create_or_existing(ref: str, **fields) -> PaymentRequest:
    """Cria o PaymentRequest, ou devolve o já existente com a mesma `external_reference` (dedup do
    retry idempotente). Fecha a corrida via `unique` + IntegrityError."""
    existing = PaymentRequest.objects.filter(external_reference=ref).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            return PaymentRequest.objects.create(external_reference=ref, **fields)
    except IntegrityError:
        # corrida: outra requisição com a mesma key criou primeiro → devolve o existente
        return PaymentRequest.objects.get(external_reference=ref)


def _amount(value) -> Decimal:
    try:
        amt = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception as e:  # noqa: BLE001
        raise ManualPaymentError("invalid_amount") from e
    if amt <= 0:
        raise ManualPaymentError("amount_must_be_positive")
    return amt


def request_pix_payment(
    *,
    amount,
    pix_key,
    supplier_name=None,
    description=None,
    receipt=None,
    idempotency_key=None,
) -> PaymentRequest:
    """Enfileira um pagamento avulso por PIX (chave) a um terceiro livre. Idempotente por referência."""
    if not pix_key:
        raise ManualPaymentError("pix_key_required")
    ref = _ref_for(idempotency_key)
    pr = _create_or_existing(
        ref,
        kind=PaymentRequest.Kind.MANUAL,
        method=PaymentRequest.Method.PIX_KEY,
        amount=_amount(amount),
        pix_key=pix_key,
        supplier_name=supplier_name or (description or None),
        receipt=receipt,
        status=PaymentRequest.Status.QUEUED,
        next_attempt_at=timezone.now(),
    )
    logger.info(
        "finance.manual_pix_requested",
        external_reference=ref,
        amount=str(pr.amount),
        supplier=supplier_name,
        has_receipt=bool(receipt),
    )
    return pr


def request_boleto_payment(
    *,
    line_code,
    amount=None,
    supplier_name=None,
    description=None,
    receipt=None,
    idempotency_key=None,
) -> PaymentRequest:
    """Enfileira o pagamento avulso de um boleto pela linha digitável. `amount` opcional (o Asaas lê
    do próprio boleto). Idempotente por referência."""
    if not line_code:
        raise ManualPaymentError("line_code_required")
    ref = _ref_for(idempotency_key)
    pr = _create_or_existing(
        ref,
        kind=PaymentRequest.Kind.MANUAL,
        method=PaymentRequest.Method.BOLETO,
        amount=_amount(amount) if amount not in (None, "") else Decimal("0"),
        boleto_line=line_code,
        supplier_name=supplier_name or (description or None),
        receipt=receipt,
        status=PaymentRequest.Status.QUEUED,
        next_attempt_at=timezone.now(),
    )
    logger.info(
        "finance.manual_boleto_requested",
        external_reference=ref,
        amount=str(pr.amount),
        supplier=supplier_name,
        has_receipt=bool(receipt),
    )
    return pr
