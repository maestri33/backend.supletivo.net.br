"""Weekly closing: Friday 18:00 in Sao Paulo, with held commissions and original bonus weeks."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
import uuid

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from finance import config
from finance.models import Commission, PaymentRequest
from finance.interface.eligibility import can_receive
from users.auth.models import User
from users.profiles.interface import get as get_profile
from finance.interface.commissions import SP_TZ, _BONUS_NAMESPACE, _external_reference, week_window


def cutoff(reference=None):
    reference = reference or timezone.now()
    if timezone.is_naive(reference):
        reference = timezone.make_aware(reference, SP_TZ)
    return week_window(reference)[0]


def bonus_source(period_start, user, canary_run_id=None):
    key = f"{period_start.isoformat()}:{user.external_id}"
    if canary_run_id:
        key += f":canary:{canary_run_id}"
    return uuid.uuid5(_BONUS_NAMESPACE, key)


def _items(end, *, persist):
    counts = defaultdict(int)
    payees = {}
    snapshots = {}
    for item in Commission.objects.filter(source_type=Commission.Source.LEAD, created_at__lt=end).exclude(status=Commission.Status.CANCELLED).select_related("payee"):
        period_start = week_window(item.created_at)[0].date()
        counts[(item.payee_id, period_start, item.canary_run_id)] += 1
        payees[item.payee_id] = item.payee
        if item.canary_run_id:
            from finance.interface.canary import validate_snapshot
            validate_snapshot(item.canary_snapshot)
            snapshots[item.canary_run_id] = item.canary_snapshot

    extra = []
    bonuses = 0
    for (user_id, period_start, run_id), count in counts.items():
        snapshot = snapshots.get(run_id)
        threshold = snapshot["bonus_threshold"] if snapshot else config.bonus_threshold()
        amount = Decimal(snapshot["bonus"]) if snapshot else config.bonus_amount()
        if count < threshold:
            continue
        user = payees[user_id]
        source = bonus_source(period_start, user, run_id)
        existing = Commission.objects.filter(source_type=Commission.Source.BONUS, source_external_id=source).first()
        if existing:
            continue
        bonuses += 1
        if persist:
            item, created = Commission.objects.get_or_create(source_type=Commission.Source.BONUS, source_external_id=source, defaults={
                "payee": user, "payee_role": Commission.Role.PROMOTER,
                "amount": amount, "bonus_period_start": period_start,
                "canary_run_id": run_id, "canary_snapshot": snapshot or {},
            })
            if created and run_id:
                from finance.interface.canary import record_accrual
                record_accrual(item)
        else:
            extra.append(SimpleNamespace(pk=None, payee_id=user_id, payee=user, payee_role=Commission.Role.PROMOTER, amount=amount, source_type=Commission.Source.BONUS, canary_run_id=run_id))

    pending = list(Commission.objects.filter(status=Commission.Status.PENDING).filter(
        Q(created_at__lt=end) | Q(source_type=Commission.Source.BONUS, bonus_period_start__lt=end.date())
    ).select_related("payee"))
    return pending + extra, bonuses, len(pending)


def _groups(items, end):
    groups = {}
    held = 0
    for item in items:
        if item.amount < 0:
            continue
        if not can_receive(item.payee, role=item.payee_role, at=end):
            held += 1
            continue
        run_id = getattr(item, "canary_run_id", None)
        key = (item.payee_id, str(run_id)) if run_id else item.payee_id
        group = groups.setdefault(key, {"payee": item.payee, "role": item.payee_role, "amount": Decimal("0.00"), "items": [], "canary_run_id": run_id})
        group["amount"] += item.amount
        group["items"].append(item)
        if item.payee_role == Commission.Role.COORDINATOR:
            group["role"] = item.payee_role
    for item in items:
        if item.amount >= 0:
            continue
        run_id = getattr(item, "canary_run_id", None)
        group = groups.get((item.payee_id, str(run_id)) if run_id else item.payee_id)
        if group is None:
            held += 1
            continue
        # Refund debt belongs to the recipient, even if the role which
        # originally earned it is no longer eligible for new payments.
        group["amount"] += item.amount
        group["items"].append(item)
    return groups, held


@transaction.atomic
def close(*, reference_date=None):
    end = cutoff(reference_date)
    # Serialize closing and reversals for a recipient, then reread pending balances.
    ids = Commission.objects.filter(status=Commission.Status.PENDING).values_list("payee_id", flat=True)
    list(User.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
    items, bonuses, _ = _items(end, persist=True)
    groups, held = _groups(items, end)
    created = awaiting = 0
    for group in groups.values():
        if group["amount"] <= 0:
            continue  # Keep negative balances pending for subsequent closings.
        user = group["payee"]
        ref = _external_reference(end.date(), user)
        if group["canary_run_id"]:
            ref += f":canary:{group['canary_run_id']}"
        if PaymentRequest.objects.filter(external_reference=ref).exists():
            continue
        profile = get_profile(user)
        pix = (profile.pix_key if profile else None) or ""
        status = PaymentRequest.Status.QUEUED if pix else PaymentRequest.Status.AWAITING_PIX
        pr = PaymentRequest.objects.create(external_reference=ref, payee=user, payee_role=group["role"], amount=group["amount"], week_of=(end-timedelta(days=7)).date(), pix_key=pix or None, status=status, next_attempt_at=timezone.now(), canary_run_id=group["canary_run_id"])
        Commission.objects.filter(pk__in=[item.pk for item in group["items"]], status=Commission.Status.PENDING).update(status=Commission.Status.PROCESSED, payment_request=pr, external_reference=ref)
        created += 1
        awaiting += not bool(pix)
    return {"week_of": (end-timedelta(days=7)).date().isoformat(), "friday": end.date().isoformat(), "commissions_in_window": len(items), "bonuses_created": bonuses, "payment_requests_created": created, "awaiting_pix": awaiting, "held_commissions": held}


def simulate(*, reference_date=None):
    end = cutoff(reference_date)
    items, bonuses, persisted_count = _items(end, persist=False)
    groups, held = _groups(items, end)
    beneficiaries = []
    for group in groups.values():
        ref = _external_reference(end.date(), group["payee"])
        if group["canary_run_id"]:
            ref += f":canary:{group['canary_run_id']}"
        if group["amount"] <= 0 or PaymentRequest.objects.filter(external_reference=ref).exists():
            continue
        user = group["payee"]
        profile = get_profile(user)
        pix = (profile.pix_key if profile else None) or ""
        leads = sum(item.source_type == Commission.Source.LEAD for item in group["items"])
        beneficiaries.append({"user_external_id": str(user.external_id), "name": profile.name if profile else "Sem Nome", "phone": profile.phone if profile else None, "cpf": profile.cpf if profile else None, "role": group["role"], "amount": str(group["amount"]), "leads_count": leads, "bonus_earned": any(item.source_type == Commission.Source.BONUS for item in group["items"]), "pix_key": pix or None, "has_pix": bool(pix)})
    beneficiaries.sort(key=lambda item: Decimal(item["amount"]), reverse=True)
    return {"week_of": (end-timedelta(days=7)).date().isoformat(), "friday": end.date().isoformat(), "total_obligation": str(sum((Decimal(item["amount"]) for item in beneficiaries), Decimal("0.00"))), "commissions_count": persisted_count, "bonuses_count": bonuses, "beneficiaries_count": len(beneficiaries), "awaiting_pix_count": sum(not item["has_pix"] for item in beneficiaries), "bonus_threshold": config.bonus_threshold(), "bonus_amount": str(config.bonus_amount()), "beneficiaries": beneficiaries, "held_commissions": held}
