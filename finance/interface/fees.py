"""Superfície in-process do finance pra DESPESAS (fees): enfileira pagamento de despesa na fila de saída.

**Mesma fila** das comissões (`PaymentRequest`) — é tudo dinheiro saindo da mesma conta Asaas (palavra do
Victor). 1º fornecedor = a instituição que credencia o aluno. Método inicial = **PIX por QR code**
(copia-e-cola), **imediato** ou **agendado**. O valor vem do CALLER (a conta real) — **nunca do `.env`**
(§8: não invento dinheiro). Ver `plan/4-financeiro-fees.md`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import structlog
from django.utils import timezone

from finance.models import PaymentRequest
from integrations.bank.asaas import qrpay

logger = structlog.get_logger()

# Reexporta os enums da fila pra o caller (ex.: enrollment) não furar a fronteira do interface (§3).
SourceType = PaymentRequest.SourceType
PaymentStatus = PaymentRequest.Status


def latest_fee_request(reference_prefix: str) -> PaymentRequest | None:
    """A tentativa MAIS RECENTE de uma fee pela FAMÍLIA de referência (prefixo determinístico).

    É como o caller (ex.: matrícula, plan/14) lê os FATOS da taxa — paga/agendada/falhou — sem furar
    a fronteira do finance (§3). Re-tentativas após falha ganham referência NOVA (`_r2`, `_r3`…),
    porque o Asaas é idempotente por referência: reusar a ref de uma falha devolveria a falha velha
    (gotcha provado no motor de payout)."""
    return (
        PaymentRequest.objects.filter(
            external_reference__startswith=reference_prefix,
            kind=PaymentRequest.Kind.FEE,
        )
        .order_by("-created_at")
        .first()
    )


SP_TZ = ZoneInfo("America/Sao_Paulo")
# Hora do dia em que pagamos uma despesa AGENDADA pelo vencimento do QR (horário comercial SP).
# Decisão técnica (Victor delegou 2026-06-02); CONFIG depois se precisar.
_DUE_PAY_HOUR = 9


def request_fee_payment(
    *,
    amount,
    qr_payload,
    supplier_name=None,
    description=None,
    scheduled_for=None,
    external_reference=None,
    source_type=None,
    source_external_id=None,
) -> PaymentRequest:
    """Enfileira uma despesa pra pagamento via PIX QR code (imediato ou agendado).

    `scheduled_for=None` ⇒ **imediato** (o worker pega na próxima passada). Com data ⇒ **agendado**
    (a fila não pega até lá, via `next_attempt_at`). Idempotente por `external_reference` (default gerado).
    O `description` é guardado no Payment do Asaas no momento do envio (via supplier_name na fila).
    `source_type`/`source_external_id` (opcionais): relacionam a fee à entidade de origem — hoje a taxa do
    credenciador → a matrícula (`SourceType.ENROLLMENT` + `enrollment.external_id`); mesma convenção do Commission.
    """
    ref = external_reference or f"fee_{uuid.uuid4().hex[:16]}"
    existing = PaymentRequest.objects.filter(external_reference=ref).first()
    if existing is not None:
        return existing

    pr = PaymentRequest.objects.create(
        external_reference=ref,
        kind=PaymentRequest.Kind.FEE,
        method=PaymentRequest.Method.PIX_QRCODE,
        amount=Decimal(str(amount)).quantize(Decimal("0.01")),
        qrcode_payload=qr_payload,
        supplier_name=supplier_name or (description or None),
        scheduled_for=scheduled_for,
        status=PaymentRequest.Status.QUEUED,
        next_attempt_at=scheduled_for or timezone.now(),
        source_type=source_type,
        source_external_id=source_external_id,
    )
    logger.info(
        "finance.fee_requested",
        external_reference=ref,
        amount=str(pr.amount),
        supplier=supplier_name,
        scheduled_for=str(scheduled_for) if scheduled_for else None,
        source_type=source_type,
        source_external_id=str(source_external_id) if source_external_id else None,
    )
    return pr


def retry_fee_payment(
    reference_prefix: str, *, qr_payload, amount, scheduled_for=None
) -> PaymentRequest:
    """NOVA tentativa de uma fee que FALHOU: cria OUTRA entrada na fila com referência fresca
    (`<prefixo>_rN`) — a falhada fica na fila como auditoria. Referência nova porque o Asaas é
    idempotente por referência (reusar a da falha devolveria a falha velha). Só permite re-tentar
    se a tentativa mais recente está FAILED (plan/14: o coordenador re-posta após um B.O.)."""
    latest = latest_fee_request(reference_prefix)
    if latest is None:
        raise ValueError(f"fee inexistente: {reference_prefix}")
    if latest.status != PaymentRequest.Status.FAILED:
        raise ValueError(
            f"fee não está em falha (status={latest.status}) — nada a re-tentar"
        )
    attempt = (
        PaymentRequest.objects.filter(
            external_reference__startswith=reference_prefix
        ).count()
        + 1
    )
    return request_fee_payment(
        amount=amount,
        qr_payload=qr_payload,
        supplier_name=latest.supplier_name,
        scheduled_for=scheduled_for,
        external_reference=f"{reference_prefix}_r{attempt}",
        source_type=latest.source_type,
        source_external_id=latest.source_external_id,
    )


def _due_to_scheduled(due_date: str) -> datetime:
    """Converte o `dueDate` do Asaas no instante de pagamento: 09:00 (SP) do dia de vencimento.

    Aceita data `YYYY-MM-DD` ou datetime ISO. Se vier sem fuso (caso comum: só a data), casa às
    `_DUE_PAY_HOUR` no fuso de SP. Levanta `ValueError` em formato inesperado (não chuta data).
    """
    try:
        dt = datetime.fromisoformat(due_date.strip())
    except ValueError as e:
        raise ValueError(f"dueDate em formato inesperado: {due_date!r}") from e
    if dt.tzinfo is None:
        dt = datetime.combine(dt.date(), time(hour=_DUE_PAY_HOUR), tzinfo=SP_TZ)
    return dt


def plan_qr_payment(*, qr_payload, amount=None) -> dict:
    """READ-ONLY: decodifica o QR no Asaas e devolve o PLANO de pagamento — **sem enfileirar nem mover
    dinheiro**. Use antes de uma transação pra validar o QR fora do banco (rede fora do `atomic`).

    Roteia pelo próprio QR (não chuta): COM vencimento → agendado pro dia do vencimento (09:00 SP; se já
    vencido → imediato, não agenda no passado); SEM vencimento (estático/imediato) → imediato. O valor vem do
    caller se informado; senão do `value` da cobrança decodificada (§8: ler o valor cobrado não é inventar
    dinheiro). Levanta `ValueError` com motivo claro se o QR não puder ser pago ou não tiver valor.

    Devolve `{"amount": <reais>, "scheduled_for": datetime|None, "due_date": str|None}`
    (`scheduled_for=None` ⇒ imediato).
    """
    try:
        info = qrpay.decode_qr(qr_payload)
    except qrpay.QrPayError as exc:
        # normaliza na FRONTEIRA (§3): o caller (ex.: enrollment) só conhece ValueError —
        # QR lixo/ilegível vira erro de domínio (422), não 500.
        raise ValueError(f"QR ilegível ou inválido ({exc})") from exc
    if not info.get("canBePaid", False):
        reason = info.get("cannotBePaidReason") or "motivo não informado pelo Asaas"
        raise ValueError(f"QR não pode ser pago: {reason}")
    value = amount if amount is not None else info.get("value")
    if value is None:
        raise ValueError(
            "sem valor: o caller não informou e o QR decodificado não traz `value`."
        )
    due = info.get("dueDate")
    scheduled_for = None
    if due:
        scheduled_for = _due_to_scheduled(str(due))
        if (
            scheduled_for <= timezone.now()
        ):  # vencida → imediato (não agenda no passado)
            scheduled_for = None
    return {"amount": value, "scheduled_for": scheduled_for, "due_date": due}


def schedule_fee_on_due_date(
    *,
    qr_payload,
    amount=None,
    supplier_name=None,
    description=None,
    external_reference=None,
) -> PaymentRequest:
    """Agenda o pagamento de uma despesa pra DATA DE VENCIMENTO lida do próprio QR (cobrança com vencimento).

    Exige `dueDate` no QR (estático/imediato → erro claro). Reusa `plan_qr_payment` (decode + roteamento) pra
    não duplicar a leitura. O valor vem do CALLER se informado; senão do `value` decodificado (§8: ler o valor
    cobrado não é inventar dinheiro). Levanta `ValueError` com motivo claro se não der pra agendar.
    """
    plan = plan_qr_payment(qr_payload=qr_payload, amount=amount)
    if plan["due_date"] is None:
        raise ValueError(
            "QR sem data de vencimento (estático/imediato) — use pagamento imediato ou --at <data>."
        )
    # VENCIDA (dueDate no passado) ⇒ plan["scheduled_for"] vem None ⇒ paga IMEDIATO, explícito e logado.
    logger.info(
        "finance.fee_scheduled_on_due",
        due_date=str(plan["due_date"]),
        scheduled_for=str(plan["scheduled_for"]) if plan["scheduled_for"] else None,
        amount=str(plan["amount"]),
        from_qr_value=amount is None,
        overdue=plan["scheduled_for"] is None,
    )
    return request_fee_payment(
        amount=plan["amount"],
        qr_payload=qr_payload,
        supplier_name=supplier_name,
        description=description,
        scheduled_for=plan["scheduled_for"],
        external_reference=external_reference,
    )
