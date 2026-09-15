"""Superfície in-process do finance (CONVENTION §3): creditar comissão + fechamento semanal.

`credit_commission` é o ponto que `lead`/`student` chamam: recebe o **objeto `users.User`** (o caller
já tem a FK), lê o valor do `.env` (corrige o bug do legado: o valor vinha do caller) e é idempotente
por `(source_type, source_external_id)`.

`run_weekly_closing` é a "sexta 18h": janela = **semana corrente** (seg→dom de `reference_date`,
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

    amount = _AMOUNT_BY_SOURCE[source_type]()
    commission, created = Commission.objects.get_or_create(
        source_type=source_type,
        source_external_id=source_external_id,
        defaults={
            "payee": payee,
            "payee_role": payee_role,
            "amount": amount,
        },
    )
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
    """Devolve (segunda 00:00 SP, segunda seguinte 00:00 SP, sexta date) da semana de `reference`."""
    local = reference.astimezone(SP_TZ)
    monday = (local - timedelta(days=local.weekday())).date()  # weekday(): Mon=0..Sun=6
    week_start = datetime.combine(monday, time.min, tzinfo=SP_TZ)
    week_end = week_start + timedelta(days=7)
    friday = monday + timedelta(days=4)
    return week_start, week_end, monday, friday


def week_window(reference=None) -> tuple[datetime, datetime]:
    """Janela da semana corrente: (segunda 00:00 SP, segunda seguinte 00:00 SP).

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
    """Fecha a semana: dispara bônus, agrupa por beneficiário, cria 1 PaymentRequest por pessoa.

    Idempotente: re-rodar a mesma semana é no-op (external_reference já existe → pula). Devolve um
    resumo (contagens) pro command/log.
    """
    now = reference_date or timezone.now()
    if timezone.is_naive(now):
        now = timezone.make_aware(now, SP_TZ)
    _week_start, week_end, monday, friday = _week_bounds(now)

    # G6: SEM lower-bound. Antes filtrava `created_at >= week_start`, então uma comissão criada
    # depois do fechamento de sexta (ex.: fim de semana) caía numa janela cujo run já passou; na
    # semana seguinte o week_start avançava e o created_at ficava abaixo dele → PENDING eterna, bônus
    # subcontado. Pegando toda PENDING com `created_at < week_end`, qualquer atrasada entra no
    # próximo run. Idempotência preservada: quem já foi pago virou PROCESSED (não é mais PENDING) e o
    # skip por external_reference evita duplicar o PaymentRequest do beneficiário na semana.
    pending = list(
        Commission.objects.filter(
            status=Commission.Status.PENDING,
            created_at__lt=week_end,
        ).select_related("payee")
    )

    # 1) BÔNUS: por promotor, conta comissões de lead na semana; >= threshold => 1 bônus flat.
    threshold = config.bonus_threshold()
    lead_count: dict[int, list] = {}  # payee_id -> [User, count]
    for c in pending:
        if c.source_type == Commission.Source.LEAD:
            entry = lead_count.setdefault(c.payee_id, [c.payee, 0])
            entry[1] += 1
    bonuses = 0
    for user, count in lead_count.values():
        if count < threshold:
            continue
        bonus_source = uuid.uuid5(
            _BONUS_NAMESPACE, f"{monday.isoformat()}:{user.external_id}"
        )
        bonus, created = Commission.objects.get_or_create(
            source_type=Commission.Source.BONUS,
            source_external_id=bonus_source,
            defaults={
                "payee": user,
                "payee_role": Commission.Role.PROMOTER,
                "amount": config.bonus_amount(),
            },
        )
        if created:
            bonuses += 1
        # inclui o bônus no lote desta semana mesmo que o created_at real caia fora da janela
        # simulada (teste de semana passada): agrupa pela lista, não por re-query.
        if bonus.status == Commission.Status.PENDING and bonus.pk not in {
            c.pk for c in pending
        }:
            pending.append(bonus)

    # 2) AGRUPA por beneficiário e cria 1 PaymentRequest por pessoa.
    groups: dict[int, dict] = {}
    for c in pending:
        g = groups.setdefault(
            c.payee_id,
            {
                "payee": c.payee,
                "role": c.payee_role,
                "amount": Decimal("0"),
                "items": [],
            },
        )
        g["amount"] += c.amount
        g["items"].append(c)
        # coordenador tem precedência no rótulo se um mesmo User misturar papéis.
        if c.payee_role == Commission.Role.COORDINATOR:
            g["role"] = Commission.Role.COORDINATOR

    requests_created = 0
    awaiting_pix = 0
    for g in groups.values():
        payee = g["payee"]
        ref = _external_reference(friday, payee)
        if PaymentRequest.objects.filter(external_reference=ref).exists():
            continue  # idempotência: semana já fechada pra este beneficiário

        profile = get_profile(payee)
        pix = (profile.pix_key if profile else None) or ""
        status = (
            PaymentRequest.Status.QUEUED if pix else PaymentRequest.Status.AWAITING_PIX
        )
        try:
            with transaction.atomic():
                pr = PaymentRequest.objects.create(
                    external_reference=ref,
                    payee=payee,
                    payee_role=g["role"],
                    amount=g["amount"],
                    week_of=monday,
                    pix_key=pix or None,
                    status=status,
                    next_attempt_at=timezone.now(),
                )
                Commission.objects.filter(id__in=[c.id for c in g["items"]]).update(
                    status=Commission.Status.PROCESSED,
                    payment_request=pr,
                    external_reference=ref,
                )
        except IntegrityError:
            continue  # corrida no external_reference unique: outra passada criou — pula
        requests_created += 1
        if status == PaymentRequest.Status.AWAITING_PIX:
            awaiting_pix += 1

    summary = {
        "week_of": monday.isoformat(),
        "friday": friday.isoformat(),
        "commissions_in_window": len(pending),
        "bonuses_created": bonuses,
        "payment_requests_created": requests_created,
        "awaiting_pix": awaiting_pix,
    }
    logger.info("finance.weekly_closing", **summary)
    return summary


def simulate_weekly_closing(*, reference_date=None) -> dict:
    """Simula o fechamento semanal em memória: calcula totais, bônus, beneficiários e pendências de PIX.
    
    NÃO altera nenhum dado no banco de dados.
    """
    now = reference_date or timezone.now()
    if timezone.is_naive(now):
        now = timezone.make_aware(now, SP_TZ)
    _week_start, week_end, monday, friday = _week_bounds(now)

    pending = list(
        Commission.objects.filter(
            status=Commission.Status.PENDING,
            created_at__lt=week_end,
        ).select_related("payee")
    )

    threshold = config.bonus_threshold()
    bonus_amount = config.bonus_amount()
    lead_count: dict[int, list] = {}
    for c in pending:
        if c.source_type == Commission.Source.LEAD:
            entry = lead_count.setdefault(c.payee_id, [c.payee, 0])
            entry[1] += 1

    potential_bonuses = 0
    simulated_bonus_items = []
    for user, count in lead_count.values():
        if count >= threshold:
            potential_bonuses += 1
            simulated_bonus_items.append(
                {
                    "payee": user,
                    "payee_role": Commission.Role.PROMOTER,
                    "amount": bonus_amount,
                    "source_type": Commission.Source.BONUS,
                }
            )

    # Agrupa por beneficiário
    groups: dict[int, dict] = {}
    for c in pending:
        g = groups.setdefault(
            c.payee_id,
            {
                "payee": c.payee,
                "role": c.payee_role,
                "amount": Decimal("0"),
                "leads_count": 0,
                "items_count": 0,
            },
        )
        g["amount"] += c.amount
        g["items_count"] += 1
        if c.source_type == Commission.Source.LEAD:
            g["leads_count"] += 1
        if c.payee_role == Commission.Role.COORDINATOR:
            g["role"] = Commission.Role.COORDINATOR

    for b in simulated_bonus_items:
        u = b["payee"]
        g = groups.setdefault(
            u.pk,
            {
                "payee": u,
                "role": b["payee_role"],
                "amount": Decimal("0"),
                "leads_count": 0,
                "items_count": 0,
            },
        )
        g["amount"] += b["amount"]
        g["items_count"] += 1

    beneficiaries = []
    total_obligation = Decimal("0")
    awaiting_pix_count = 0

    for g in groups.values():
        payee = g["payee"]
        profile = get_profile(payee)
        pix = (profile.pix_key if profile else None) or ""
        has_pix = bool(pix)
        if not has_pix:
            awaiting_pix_count += 1
        amount = g["amount"]
        total_obligation += amount

        beneficiaries.append(
            {
                "user_external_id": str(payee.external_id),
                "name": profile.name if profile else "Sem Nome",
                "phone": profile.phone if profile else None,
                "cpf": profile.cpf if profile else None,
                "role": g["role"],
                "amount": str(amount),
                "leads_count": g["leads_count"],
                "bonus_earned": g["leads_count"] >= threshold,
                "pix_key": pix or None,
                "has_pix": has_pix,
            }
        )

    # Ordena por valor decrescente
    beneficiaries.sort(key=lambda x: Decimal(x["amount"]), reverse=True)

    return {
        "week_of": monday.isoformat(),
        "friday": friday.isoformat(),
        "total_obligation": str(total_obligation),
        "commissions_count": len(pending),
        "bonuses_count": potential_bonuses,
        "beneficiaries_count": len(beneficiaries),
        "awaiting_pix_count": awaiting_pix_count,
        "bonus_threshold": threshold,
        "bonus_amount": str(bonus_amount),
        "beneficiaries": beneficiaries,
    }


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
    pending = list(
        Commission.objects.filter(
            payee=user,
            status=Commission.Status.PENDING,
        )
    )
    if not pending:
        raise ValueError("no_pending_commissions")

    total_amount = sum((c.amount for c in pending), Decimal("0.00"))
    profile = get_profile(user)
    pix = (profile.pix_key if profile else None) or ""
    status = PaymentRequest.Status.QUEUED if pix else PaymentRequest.Status.AWAITING_PIX

    ref = f"adv_{timezone.now().strftime('%Y%m%d%H%M%S')}_{user.external_id}"
    with transaction.atomic():
        pr = PaymentRequest.objects.create(
            external_reference=ref,
            payee=user,
            payee_role=role,
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
            finance_payout.process_payment_requests()
        except Exception as exc:
            logger.warning("finance.advance_payout_immediate_submit_failed", error=str(exc))

    return {
        "payment_request_external_id": str(pr.external_id),
        "external_reference": pr.external_reference,
        "amount": str(pr.amount),
        "status": pr.status,
        "commissions_count": len(pending),
        "pix_key": pr.pix_key,
    }


