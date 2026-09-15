"""Worker do payout (rodado pelo Django-Q): processa as `PaymentRequest` e reconcilia com o asaas.

Reusa `integrations.bank.asaas.payout` (PIX-out síncrono + idempotente, provado real no 1a-vi). O
finance é só a **camada de domínio do lote semanal**: claim atômico + backoff; `awaiting_pix` (sem
chave no profile) e `awaiting_balance` (asaas sem saldo) são NÃO-terminais — esperam na fila, não
falham, não perdem dinheiro. O join asaas↔finance é `PaymentRequest.external_reference` ==
`asaas Payment.payment_id` (passado como `payment_id=external_reference` no `create_payout`).
"""

from __future__ import annotations

from datetime import timedelta

import structlog
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from finance.models import Commission, PaymentRequest
from integrations.bank.asaas import billpay as asaas_billpay
from integrations.bank.asaas import payout as asaas_payout
from integrations.bank.asaas import qrpay as asaas_qrpay
from integrations.bank.asaas.webhooks import is_insufficient_balance_reason
from users.profiles.interface import get as get_profile

logger = structlog.get_logger()

_ACTIVE = (
    PaymentRequest.Status.QUEUED,
    PaymentRequest.Status.AWAITING_PIX,
    PaymentRequest.Status.SUBMITTED,
    PaymentRequest.Status.AWAITING_BALANCE,
)
_BACKOFF_BASE_S = 60  # backoff = base * (attempts+1), com teto
_BACKOFF_MAX_S = 3600
_CLAIM_LOCK_S = 120  # janela do claim (evita re-pick na mesma volta do cluster)


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(_BACKOFF_BASE_S * (attempts + 1), _BACKOFF_MAX_S))


def _cascade(pr: PaymentRequest, status: str) -> None:
    """Propaga o desfecho terminal da PaymentRequest pras comissões que a compõem."""
    Commission.objects.filter(payment_request=pr).update(status=status)


def _dispatch_fee_hook(
    pr: PaymentRequest, event: str, *, detail: str | None = None
) -> None:
    """Dispara o hook do app de origem quando uma FEE muda de vida (plan/14, CONVENTION §7.3).

    `fee.paid` = pagamento confirmado; `fee.problem` = qualquer B.O. (recusa, sem saldo, falha).
    Só pra fee COM origem (source_type) — comissão segue pelo `_cascade`. O dispatch isola exceção
    de handler (não derruba o worker)."""
    if pr.kind != PaymentRequest.Kind.FEE or not pr.source_type:
        return
    from core import hooks as core_hooks

    core_hooks.dispatch(
        event,
        external_reference=pr.external_reference,
        source_type=pr.source_type,
        source_external_id=str(pr.source_external_id),
        amount=str(pr.amount),
        detail=detail,
        asaas_status=pr.asaas_status or None,
    )


def _notify_commission_paid(pr: PaymentRequest) -> None:
    """Avisa o beneficiário que a comissão da semana CAIU (PIX confirmado pelo Asaas).

    Só pra `Kind.COMMISSION` (fee/manual não têm User payee). UMA notificação por PaymentRequest
    (idempotente por external_reference — re-reconciliação não renotifica). Confirmação de transação
    JÁ concluída (não promete nada: o PIX do valor exato já saiu). Isola exceção: notificar nunca
    pode derrubar o worker de pagamento (§12)."""
    if pr.kind != PaymentRequest.Kind.COMMISSION:
        return
    try:
        profile = get_profile(pr.payee)
        phone = (profile.phone if profile else None) or None
        if not phone:
            return  # sem telefone não há canal — nada a fazer (não falha)
        first = ((profile.name or "").strip().split() or [""])[0] if profile else ""
        valor = f"{pr.amount:.2f}".replace(".", ",")
        from notify.interface.events import send_event

        send_event(
            "finance.commission_paid",
            profile=profile,
            phone=phone,
            ctx={
                "nome": first or "Promotor",
                "valor": valor,
                "external_reference": pr.external_reference,
            },
            idempotency_key=f"commission_paid:{pr.external_reference}",
        )
    except Exception as exc:  # noqa: BLE001 — notificar nunca derruba o pagamento (§12)
        logger.warning(
            "finance.commission_paid_notify_failed",
            ref=pr.external_reference,
            error=str(exc)[:160],
        )


def process_payment_requests() -> dict:
    """Uma passada do worker: envia as filas prontas e reconcilia as enviadas com lock pessimista."""
    now = timezone.now()
    summary = {"submitted": 0, "paid": 0, "failed": 0, "awaiting": 0, "skipped": 0}

    ready_ids = list(
        PaymentRequest.objects.filter(status__in=_ACTIVE)
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .values_list("id", flat=True)[:50]
    )

    for pr_id in ready_ids:
        with transaction.atomic():
            pr = (
                PaymentRequest.objects.select_for_update(skip_locked=True)
                .filter(id=pr_id, status__in=_ACTIVE)
                .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
                .first()
            )
            if not pr:
                summary["skipped"] += 1
                continue

            pr.next_attempt_at = now + timedelta(seconds=_CLAIM_LOCK_S)
            pr.save(update_fields=["next_attempt_at", "updated_at"])

        _process_one(pr, summary)

    logger.info("finance.payout_pass", **summary)
    return summary



def _process_one(pr: PaymentRequest, summary: dict) -> None:
    # awaiting_pix: re-resolve a chave do profile; ainda vazia => continua esperando (não falha).
    if pr.status == PaymentRequest.Status.AWAITING_PIX:
        profile = get_profile(pr.payee)
        pix = (profile.pix_key if profile else None) or ""
        if not pix:
            pr.next_attempt_at = timezone.now() + _backoff(pr.attempts)
            pr.save(update_fields=["next_attempt_at", "updated_at"])
            summary["awaiting"] += 1
            return
        pr.pix_key = pix
        pr.status = PaymentRequest.Status.QUEUED
        pr.save(update_fields=["pix_key", "status", "updated_at"])

    if pr.status == PaymentRequest.Status.QUEUED:
        _submit(pr, summary)
    elif pr.status in (
        PaymentRequest.Status.SUBMITTED,
        PaymentRequest.Status.AWAITING_BALANCE,
    ):
        _reconcile(pr, summary)


def _submit(pr: PaymentRequest, summary: dict) -> None:
    """Submete o PIX-out via asaas (idempotente por payment_id=external_reference)."""
    pr.attempts += 1
    try:
        if pr.method == PaymentRequest.Method.PIX_QRCODE:
            payment = asaas_qrpay.pay_qr_code(
                amount=pr.amount,  # reais (Decimal) — mesma unidade do asaas
                qr_payload=pr.qrcode_payload,
                payment_id=pr.external_reference,
                description=f"despesa {pr.supplier_name or pr.external_reference}",
            )
        elif pr.method == PaymentRequest.Method.BOLETO:
            payment = asaas_billpay.pay_bill(
                line_code=pr.boleto_line,
                amount=pr.amount or None,  # 0 = deixa o Asaas ler o valor do boleto
                payment_id=pr.external_reference,
                description=f"avulso {pr.supplier_name or pr.external_reference}",
            )
        else:
            payment = asaas_payout.create_payout(
                amount=pr.amount,  # já em reais (Decimal) — mesma unidade do asaas, sem conversão
                pix_key=pr.pix_key,
                payment_id=pr.external_reference,
                description=(
                    f"avulso {pr.supplier_name or pr.external_reference}"
                    if pr.kind == PaymentRequest.Kind.MANUAL
                    else f"comissao {pr.payee_role} semana {pr.week_of}"
                ),
            )
    except (
        asaas_payout.PayoutError,
        asaas_qrpay.QrPayError,
        asaas_billpay.BillPayError,
    ) as exc:
        reason = str(exc)
        if reason.startswith("asaas_rejected"):
            if is_insufficient_balance_reason(reason):
                # saldo insuficiente NÃO é recusa definitiva: espera na fila (AWAITING_BALANCE),
                # a mesma garantia documentada acima — não falha, não perde dinheiro.
                pr.status = PaymentRequest.Status.AWAITING_BALANCE
                pr.last_error = reason
                pr.next_attempt_at = timezone.now() + _backoff(pr.attempts)
                pr.save(
                    update_fields=[
                        "status",
                        "last_error",
                        "attempts",
                        "next_attempt_at",
                        "updated_at",
                    ]
                )
                _dispatch_fee_hook(
                    pr,
                    "fee.problem",
                    detail="sem saldo na conta Asaas — a fila re-tenta sozinha quando houver",
                )
                summary["awaiting"] += 1
                logger.warning(
                    "finance.payout_awaiting_balance",
                    ref=pr.external_reference,
                    error=reason,
                )
                return
            # recusa definitiva do asaas: falha terminal, cascateia.
            pr.status = PaymentRequest.Status.FAILED
            pr.last_error = reason
            pr.save(update_fields=["status", "last_error", "attempts", "updated_at"])
            _cascade(pr, Commission.Status.FAILED)
            _dispatch_fee_hook(
                pr, "fee.problem", detail=f"recusado pelo Asaas: {reason}"
            )
            summary["failed"] += 1
            logger.warning(
                "finance.payout_rejected", ref=pr.external_reference, error=reason
            )
            return
        # incerto (submit_uncertain/pix_key_required transitório): mantém na fila com backoff,
        # a menos que estoure max_attempts.
        if pr.attempts >= pr.max_attempts:
            pr.status = PaymentRequest.Status.FAILED
            pr.last_error = f"max_attempts: {reason}"
            pr.save(update_fields=["status", "last_error", "attempts", "updated_at"])
            _cascade(pr, Commission.Status.FAILED)
            _dispatch_fee_hook(
                pr, "fee.problem", detail=f"esgotou as tentativas: {reason}"
            )
            summary["failed"] += 1
            return
        pr.last_error = reason
        pr.next_attempt_at = timezone.now() + _backoff(pr.attempts)
        pr.save(
            update_fields=["last_error", "next_attempt_at", "attempts", "updated_at"]
        )
        summary["awaiting"] += 1
        return

    pr.asaas_payment_id = payment.payment_id
    pr.asaas_status = payment.status
    pr.status = PaymentRequest.Status.SUBMITTED
    pr.next_attempt_at = timezone.now() + _backoff(pr.attempts)
    pr.save(
        update_fields=[
            "asaas_payment_id",
            "asaas_status",
            "status",
            "attempts",
            "next_attempt_at",
            "updated_at",
        ]
    )
    summary["submitted"] += 1
    logger.info(
        "finance.payout_submitted",
        ref=pr.external_reference,
        asaas_status=payment.status,
        amount=str(pr.amount),
    )


def _reconcile(pr: PaymentRequest, summary: dict) -> None:
    """Lê o Payment no asaas e move a PaymentRequest conforme o status real."""
    try:
        if pr.method == PaymentRequest.Method.PIX_QRCODE:
            payment = asaas_qrpay.refresh_qr_payment(pr.external_reference)
        elif pr.method == PaymentRequest.Method.BOLETO:
            payment = asaas_billpay.refresh_boleto(pr.external_reference)
        else:
            payment = asaas_payout.get_payout(pr.external_reference)
    except (
        asaas_payout.PayoutError,
        asaas_qrpay.QrPayError,
        asaas_billpay.BillPayError,
    ):
        # ainda não achou o Payment (corrida) — tenta de novo com backoff.
        pr.next_attempt_at = timezone.now() + _backoff(pr.attempts)
        pr.save(update_fields=["next_attempt_at", "updated_at"])
        summary["awaiting"] += 1
        return

    was_awaiting_balance = pr.status == PaymentRequest.Status.AWAITING_BALANCE
    pr.asaas_status = payment.status
    status = (payment.status or "").upper()
    if status == "PAID":
        pr.status = PaymentRequest.Status.PAID
        pr.save(update_fields=["status", "asaas_status", "updated_at"])
        _cascade(pr, Commission.Status.PAID)
        _dispatch_fee_hook(pr, "fee.paid")
        _notify_commission_paid(
            pr
        )  # avisa o beneficiário (comissão); idempotente, isolado
        summary["paid"] += 1
        logger.info(
            "finance.payout_paid", ref=pr.external_reference, amount=str(pr.amount)
        )
    elif status in ("FAILED", "CANCELLED"):
        pr.status = PaymentRequest.Status.FAILED
        pr.last_error = f"asaas {status}"
        pr.save(update_fields=["status", "asaas_status", "last_error", "updated_at"])
        _cascade(pr, Commission.Status.FAILED)
        _dispatch_fee_hook(pr, "fee.problem", detail=f"pagamento {status} no Asaas")
        summary["failed"] += 1
    elif status == "AWAITING_BALANCE":
        pr.status = PaymentRequest.Status.AWAITING_BALANCE
        pr.next_attempt_at = timezone.now() + _backoff(pr.attempts)
        pr.save(
            update_fields=["status", "asaas_status", "next_attempt_at", "updated_at"]
        )
        if not was_awaiting_balance:
            # só na TRANSIÇÃO pra sem-saldo (senão spamaria a cada passada do worker).
            _dispatch_fee_hook(
                pr,
                "fee.problem",
                detail="sem saldo na conta Asaas — a fila re-tenta sozinha quando houver",
            )
        summary["awaiting"] += 1
    else:
        # ainda em trânsito (SUBMITTED/SUBMITTING/...): reconcilia de novo depois.
        pr.next_attempt_at = timezone.now() + _backoff(pr.attempts)
        pr.save(update_fields=["asaas_status", "next_attempt_at", "updated_at"])
        summary["awaiting"] += 1


def retry_payment_request(external_id: str) -> PaymentRequest:
    """Força o reprocessamento imediato de uma solicitação de pagamento com erro ou sem saldo."""
    pr = PaymentRequest.objects.filter(external_id=external_id).first()
    if pr is None:
        raise ValueError("payment_request_not_found")
    
    if pr.status in (PaymentRequest.Status.PAID,):
        raise ValueError("payment_request_already_paid")

    profile = get_profile(pr.payee) if pr.payee else None
    pix = (profile.pix_key if profile else None) or pr.pix_key or ""
    
    pr.status = PaymentRequest.Status.QUEUED if pix or pr.method in (PaymentRequest.Method.PIX_QRCODE, PaymentRequest.Method.BOLETO) else PaymentRequest.Status.AWAITING_PIX
    pr.attempts = 0
    pr.last_error = None
    pr.next_attempt_at = timezone.now()
    pr.save(update_fields=["status", "attempts", "last_error", "next_attempt_at", "updated_at"])
    
    # Se tinha comissões em failed, reabre para processed
    Commission.objects.filter(payment_request=pr, status=Commission.Status.FAILED).update(status=Commission.Status.PROCESSED)
    
    logger.info("finance.payout_retry_forced", external_id=external_id, new_status=pr.status)
    return pr


def override_payment_request_pix(external_id: str, new_pix_key: str, update_profile: bool = True) -> PaymentRequest:
    """Permite ao staff atualizar a chave PIX de um payout e re-enfileirar imediatamente."""
    clean_pix = (new_pix_key or "").strip()
    if not clean_pix:
        raise ValueError("pix_key_required")
    
    pr = PaymentRequest.objects.filter(external_id=external_id).first()
    if pr is None:
        raise ValueError("payment_request_not_found")
    
    if pr.status in (PaymentRequest.Status.PAID,):
        raise ValueError("payment_request_already_paid")

    pr.pix_key = clean_pix
    pr.status = PaymentRequest.Status.QUEUED
    pr.attempts = 0
    pr.last_error = None
    pr.next_attempt_at = timezone.now()
    pr.save(update_fields=["pix_key", "status", "attempts", "last_error", "next_attempt_at", "updated_at"])

    if update_profile and pr.payee:
        profile = get_profile(pr.payee)
        if profile:
            profile.pix_key = clean_pix
            profile.save(update_fields=["pix_key", "updated_at"])

    logger.info("finance.payout_pix_overridden", external_id=external_id, pix_key=clean_pix)
    return pr

