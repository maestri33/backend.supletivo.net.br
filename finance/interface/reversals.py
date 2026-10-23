"""Reverse the earned commission, never the student's purchase price."""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from finance import config
from finance.models import Commission, PaymentRequest
from finance.interface.commissions import week_window
from finance.interface.weekly import bonus_source
from users.auth.models import User


def _cancel(item):
    if item.status == Commission.Status.CANCELLED:
        return
    pr = PaymentRequest.objects.select_for_update().filter(pk=item.payment_request_id).first() if item.payment_request_id else None
    paid = item.status == Commission.Status.PAID or (pr and pr.status == PaymentRequest.Status.PAID)
    uncertain = pr and not paid and (pr.status == PaymentRequest.Status.SUBMITTED or pr.attempts > 0) and pr.status not in (PaymentRequest.Status.FAILED, PaymentRequest.Status.CANCELLED)
    item.status = Commission.Status.CANCELLED
    item.save(update_fields=["status", "updated_at"])
    if paid or uncertain:
        Commission.objects.get_or_create(source_type=Commission.Source.REVERSAL, source_external_id=item.external_id, defaults={
            "payee": item.payee, "payee_role": item.payee_role, "amount": -item.amount,
            "status": Commission.Status.PENDING if paid else Commission.Status.PROCESSED,
            "payment_request": None if paid else pr,
            "external_reference": f"reversal-await:{item.external_id}" if uncertain else None,
            "canary_run_id": item.canary_run_id, "canary_snapshot": item.canary_snapshot,
        })
    elif pr:
        total = pr.commissions.exclude(status=Commission.Status.CANCELLED).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        pr.amount = max(total, Decimal("0.00"))
        if total <= 0:
            pr.status = PaymentRequest.Status.CANCELLED
            pr.next_attempt_at = None
            # This batch never left the account. Carry its remaining balance,
            # including earlier refund debts, into a later closing.
            pr.commissions.exclude(status=Commission.Status.CANCELLED).update(
                status=Commission.Status.PENDING,
                payment_request=None,
                external_reference=None,
            )
        pr.save(update_fields=["amount", "status", "next_attempt_at", "updated_at"])


@transaction.atomic
def reverse_lead(lead):
    sale = Commission.objects.filter(source_type=Commission.Source.LEAD, source_external_id=lead.external_id).first()
    if not sale:
        return []
    return reverse_commission(sale)


@transaction.atomic
def reverse_commission(item):
    """Cancel the earned amount and any bonus lost in the sale's original week."""
    User.objects.select_for_update().get(pk=item.payee_id)
    sale = Commission.objects.select_for_update().get(pk=item.pk)
    affected = [sale]
    _cancel(sale)
    if sale.source_type != Commission.Source.LEAD:
        return affected
    start, end = week_window(sale.created_at)
    valid_sales = Commission.objects.filter(payee_id=sale.payee_id, source_type=Commission.Source.LEAD, created_at__gte=start, created_at__lt=end, canary_run_id=sale.canary_run_id).exclude(status=Commission.Status.CANCELLED).count()
    threshold = sale.canary_snapshot["bonus_threshold"] if sale.canary_run_id else config.bonus_threshold()
    if valid_sales < threshold:
        bonus = Commission.objects.select_for_update().filter(source_type=Commission.Source.BONUS, source_external_id=bonus_source(start.date(), sale.payee, sale.canary_run_id)).first()
        if bonus:
            _cancel(bonus)
            affected.append(bonus)
    return affected
