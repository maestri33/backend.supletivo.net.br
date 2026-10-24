"""Superfície in-process do finance (CONVENTION §3): creditar comissão + fechamento semanal.

`credit_commission` é o ponto que `lead`/`student` chamam: recebe o **objeto `users.User`** (o caller
já tem a FK), lê o valor do `.env` (corrige o bug do legado: o valor vinha do caller) e é idempotente
por `(source_type, source_external_id)`.

`run_weekly_closing` é a "sexta 18h": janela = **semana encerrada** (sexta 18h→sexta 18h de `reference_date`,
America/Sao_Paulo — corrige o bug do legado "tudo que está pending"), dispara o bônus FLAT (>= threshold
indicações de lead na semana), agrupa por beneficiário e cria **1 `PaymentRequest` por pessoa**
(idempotente por `external_reference`), resolvendo a chave PIX do `profile` (snapshot).
"""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import structlog
from django.db import IntegrityError, transaction
from django.utils import timezone

from finance import config
from finance.models import Commission, PaymentRequest
from users.profiles.interface import get as get_profile

logger = structlog.get_logger()

SP_TZ = ZoneInfo("America/Sao_Paulo")
# namespace estável p/ o uuid5 determinístico do bônus (mesma semana+promotor => mesmo id => não duplica).
_BONUS_NAMESPACE = uuid.UUID("00000000-0000-0000-0000-0000000000f1")

# valor (reais) por tipo de comissão — lido do .env (config). lead→direta, veteran→coordenador.
_AMOUNT_BY_SOURCE = {
    Commission.Source.LEAD: config.direct_amount,
    Commission.Source.VETERAN: config.coordinator_amount,
    Commission.Source.BONUS: config.bonus_amount,
}


@transaction.atomic
def credit_commission(
    *, payee, payee_role, source_type, source_external_id
) -> Commission:
    """Credita uma comissão (valor do .env) ao beneficiário. Idempotente pela fonte.

    `payee` é o objeto `users.User` (o caller já tem a FK em mãos — sem ida-e-volta por external_id,
    §1/§4). `payee` None levanta ValueError (não cria comissão órfã). `source_external_id` repetido
    devolve a comissão já existente (get_or_create no `unique(source_type, source_external_id)`).
    """
    if payee is None:
        raise ValueError("payee_required")

    from finance.interface import canary
    terms = canary.source_terms(source_type=source_type, source_external_id=source_external_id, payee=payee)
    amount = Decimal(terms["direct"] if source_type == Commission.Source.LEAD else terms["coordinator"]) if terms else _AMOUNT_BY_SOURCE[source_type]()
    commission, created = Commission.objects.get_or_create(
        source_type=source_type,
        source_external_id=source_external_id,
        defaults={
            "payee": payee,
            "payee_role": payee_role,
            "amount": amount,
            "canary_run_id": terms["run_id"] if terms else None,
            "canary_snapshot": terms or {},
        },
    )
    if created and terms:
        canary.record_accrual(commission)
    logger.info(
        "finance.commission_credited",
        external_id=str(commission.external_id),
        payee_role=payee_role,
        source_type=str(source_type),
        amount=str(amount),
        created=created,
    )
    return commission


def _week_bounds(reference):
    local = reference.astimezone(SP_TZ)
    closing_date = local.date() - timedelta(days=(local.weekday()-4) % 7)
    start = datetime.combine(closing_date, time(hour=18), tzinfo=SP_TZ)
    if local < start:
        start -= timedelta(days=7)
    end = start + timedelta(days=7)
    return start, end, start.date(), end.date()


def week_window(reference=None) -> tuple[datetime, datetime]:
    """Janela corrente: sexta 18:00 SP até a próxima sexta 18:00 SP.

    Mesma janela que `run_weekly_closing` usa — consumida pelo painel do promotor
    (`/promoter/me/summary`) pra contagem/soma "desta semana" bater com o fechamento.
    """
    now = reference or timezone.now()
    if timezone.is_naive(now):
        now = timezone.make_aware(now, SP_TZ)
    week_start, week_end, _monday, _friday = _week_bounds(now)
    return week_start, week_end


def next_closing_at(reference=None) -> datetime:
    """Próximo fechamento (closing_weekday/closing_hour em SP). Se o desta semana já passou,
    devolve o da semana seguinte."""
    now = reference or timezone.now()
    if timezone.is_naive(now):
        now = timezone.make_aware(now, SP_TZ)
    local = now.astimezone(SP_TZ)
    monday = (local - timedelta(days=local.weekday())).date()
    closing = datetime.combine(
        monday + timedelta(days=config.closing_weekday()),
        time(hour=config.closing_hour()),
        tzinfo=SP_TZ,
    )
    if local >= closing:
        closing += timedelta(days=7)
    return closing


def _external_reference(friday, payee) -> str:
    """`{ordinal-sexta-no-mês}_{MM}_{AAAA}_{payee.external_id}` (formato do legado)."""
    ordinal = (friday.day - 1) // 7 + 1  # 1ª..5ª sexta do mês
    return f"{ordinal}_{friday.month:02d}_{friday.year}_{payee.external_id}"


def run_weekly_closing(*, reference_date=None) -> dict:
    from finance.interface.weekly import close
    return close(reference_date=reference_date)


def simulate_weekly_closing(*, reference_date=None) -> dict:
    from finance.interface.weekly import simulate
    return simulate(reference_date=reference_date)


def credit_manual_commission(
    *, payee, amount: Decimal | str, description: str | None = None, role: str = "promoter"
) -> Commission:
    """Credita uma comissão manual / avulsa criada pelo Administrador."""
    if payee is None:
        raise ValueError("payee_required")
    dec_amount = Decimal(str(amount))
    if dec_amount <= Decimal("0.00"):
        raise ValueError("amount_must_be_positive")

    source_id = uuid.uuid4()
    commission = Commission.objects.create(
        payee=payee,
        payee_role=role,
        source_type=Commission.Source.MANUAL,
        source_external_id=source_id,
        amount=dec_amount,
        status=Commission.Status.PENDING,
    )
    logger.info(
        "finance.manual_commission_credited",
        commission_id=str(commission.external_id),
        payee_id=str(payee.external_id),
        amount=str(dec_amount),
        description=description,
    )
    return commission


def advance_user_payout(*, user, role: str = "promoter", immediate_submit: bool = True) -> dict:
    """Antecipa a liberação e pagamento das comissões pendentes de um usuário imediatamente."""
    from finance.interface.eligibility import can_receive
    from finance.interface.weekly import _groups, cutoff
    from users.auth.models import User
    end = cutoff()
    if not can_receive(user, role=role, at=end):
        raise ValueError("payout_not_eligible")
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        groups, _ = _groups(list(Commission.objects.filter(payee=user, status=Commission.Status.PENDING)), end)
        group = groups.get(user.pk)
        if not group:
            raise ValueError("no_pending_commissions")
        pending = group["items"]
        total_amount = group["amount"]
        if total_amount <= 0:
            raise ValueError("no_payable_balance")
        profile = get_profile(user)
        pix = (profile.pix_key if profile else None) or ""
        status = PaymentRequest.Status.QUEUED if pix else PaymentRequest.Status.AWAITING_PIX
        ref = f"adv_{uuid.uuid4().hex}_{user.external_id}"
        pr = PaymentRequest.objects.create(
            external_reference=ref,
            payee=user,
            payee_role=group["role"],
            amount=total_amount,
            week_of=timezone.localdate(),
            pix_key=pix or None,
            status=status,
            next_attempt_at=timezone.now(),
        )
        Commission.objects.filter(id__in=[c.id for c in pending]).update(
            status=Commission.Status.PROCESSED,
            payment_request=pr,
            external_reference=ref,
        )

    # Se tiver chave PIX e immediate_submit=True, dispara o payout de forma assíncrona ou em fila
    if immediate_submit and status == PaymentRequest.Status.QUEUED:
        from finance.interface import payout as finance_payout
        try:
            finance_payout.process_payment_requests(external_id=pr.external_id)
        except Exception as exc:
            logger.warning("finance.advance_payout_immediate_submit_failed", error=str(exc))

    pr.refresh_from_db()

    return {
        "payment_request_external_id": str(pr.external_id),
        "external_reference": pr.external_reference,
        "amount": str(pr.amount),
        "status": pr.status,
        "commissions_count": len(pending),
        "pix_key": pr.pix_key,
    }


