"""Payment history and operational recovery. Never creates a charge during reconciliation."""

from decimal import Decimal
from uuid import UUID

from django.db import transaction

from users.roles.lead.models import Checkout, Lead, PaymentAttempt

SNAPSHOT_FIELDS = ("provider", "payment_method", "provider_payment_id", "amount", "short_token",
                   "checkout_url", "receipt_url", "qrcode_payload", "qrcode_image", "due_date", "paid_at")


def snapshot(checkout):
    attempt, _ = PaymentAttempt.objects.get_or_create(checkout=checkout, defaults={
        "lead": checkout.lead, "lead_external_id": checkout.lead.external_id,
        "user_external_id": checkout.lead.user.external_id,
        **{field: getattr(checkout, field) for field in SNAPSHOT_FIELDS},
        "provider_confirmed": checkout.is_paid,
        "app_applied": checkout.is_paid and has_business_access(checkout.lead),
    })
    return attempt


def sync(checkout, *, attempt=None):
    attempt = attempt or snapshot(checkout)
    PaymentAttempt.objects.filter(pk=attempt.pk).update(**{
        field: getattr(checkout, field) for field in SNAPSHOT_FIELDS
    })
    attempt.refresh_from_db()
    return attempt


def has_business_access(lead):
    from users.roles.models import UserRole
    from users.roles.enrollment.models import Enrollment
    from users.roles.student.models import Student
    if lead is None:
        return False
    roles = set(UserRole.objects.filter(user=lead.user, revoked_at__isnull=True).values_list("role", flat=True))
    return ("enrollment" in roles and Enrollment.objects.filter(user=lead.user).exists()) or (
        bool(roles & {"student", "veteran"}) and Student.objects.filter(user=lead.user).exists())


def evidence(attempt):
    """Read only the matching provider's persisted proof, never a public callback's claims."""
    if attempt.provider == "infinitepay":
        from integrations.bank.infinitepay.models import Checkout as CardCheckout
        try:
            provider_id = UUID(str(attempt.provider_payment_id))
        except (ValueError, TypeError, AttributeError):
            provider_id = None
        row = CardCheckout.objects.filter(external_id=provider_id).first() if provider_id else None
        proof = row.payment_check_payload if row else {}
        verified = bool(row and isinstance(proof, dict) and proof.get("success") is True and proof.get("paid") is True
            and type(proof.get("amount")) is int and type(proof.get("paid_amount")) is int
            and proof["amount"] == row.amount_cents and proof["paid_amount"] >= row.amount_cents)
        return {"confirmed": bool(row and row.status == "PAID"), "amount": row.amount_cents if row else None,
                "verified": verified,
                "paid": row.paid_amount_cents if row else None, "receipt": row.receipt_url if row else None,
                "method": row.capture_method if row else None,
                "creation_state": getattr(row, "creation_state", "pending") if row else "pending"}
    from integrations.bank.asaas.models import Payment
    row = Payment.objects.filter(payment_id=attempt.provider_payment_id,
        kind__in=[Payment.Kind.CHARGE, Payment.Kind.STATIC_PIX_QR]).first()
    try:
        proof = row.confirmation_payload if row else {}
        verified = isinstance(proof, dict) and Decimal(str(proof.get("value"))) == row.amount
    except (ArithmeticError, ValueError, TypeError, AttributeError):
        verified = False
    return {"confirmed": bool(row and row.status == "PAID"), "amount": int(row.amount * 100) if row else None,
            "verified": bool(verified),
            "paid": int(row.amount * 100) if row and row.status == "PAID" else None,
            "receipt": row.receipt_url if row else None,
            "method": "pix", "creation_state": "ready" if row else "pending"}


def diagnostic(attempt):
    proof = evidence(attempt)
    confirmed = proof["confirmed"] or attempt.provider_confirmed
    applied = attempt.app_applied and has_business_access(attempt.lead)
    uncertain = attempt.creation_uncertain or proof["creation_state"] == "uncertain"
    error = attempt.last_error
    event = latest_event(attempt)
    retry_at = attempt.next_retry_at
    if event and not applied:
        error = error or event.last_error_code
        retry_at = event.next_attempt_at if event.processing_state == "retry" else retry_at
    if confirmed and not proof["verified"] and not applied:
        error = error or "financial_proof_missing"
    if confirmed and not has_business_access(attempt.lead) and attempt.app_applied:
        error = "business_state_mismatch"
    if uncertain:
        error = "checkout_creation_uncertain"
    stage = ("review" if error else "applied" if applied else "provider_confirmed" if confirmed
             else "uncertain" if uncertain else "superseded" if attempt.superseded
             else "creating" if proof["creation_state"] == "creating" else "pending")
    return {"external_id": str(attempt.external_id), "lead_external_id": str(attempt.lead_external_id),
            "provider": attempt.provider, "amount": str(attempt.amount), "status": stage,
            "provider_payment_id": attempt.provider_payment_id, "provider_confirmed": confirmed,
            "app_applied": applied, "superseded": attempt.superseded, "creation_uncertain": uncertain,
            "last_error": error or None, "next_retry_at": retry_at.isoformat() if retry_at else None,
            "created_at": attempt.created_at.isoformat()}


def payment_status(lead, checkout):
    attempt = snapshot(checkout) if checkout else None
    if attempt is None:
        return {"stage": "pending", "continuation_url": None}
    item = diagnostic(attempt)
    proof = evidence(attempt)
    complete = lead.status == Lead.Status.PAID and has_business_access(lead)
    stage = ("completed" if complete else "review" if item["last_error"] else
             "provider_confirmed" if item["provider_confirmed"] else "pending")
    if lead.status == Lead.Status.PAID and not complete:
        stage = "review"
    return {"stage": stage, "continuation_url": "/student/enrollment" if complete else None,
            "actual_capture_method": proof["method"],
            "paid_amount": str(Decimal(proof["paid"]) / 100) if proof["paid"] is not None else None}


def reconcile(attempt):
    from users.roles.lead import service
    proof = evidence(attempt)
    if not proof["verified"] or not proof["confirmed"] or proof["amount"] != int(attempt.amount * 100) or proof["paid"] is None:
        # A received callback can be re-verified by the same durable processor.
        from integrations.bank import recovery
        event = latest_event(attempt)
        if event:
            from django.utils import timezone
            from django.db.models import Q
            # A live worker keeps its lease; an operator may retry a completed review.
            type(event).objects.filter(pk=event.pk).filter(
                ~Q(processing_state="processing") | Q(lease_until__lte=timezone.now())).update(
                    processing_state="retry", next_attempt_at=timezone.now())
            recovery.process(attempt.provider, event.pk)
        recovery.reconcile_attempt(attempt.provider, attempt.provider_payment_id)
        proof = evidence(attempt)
    if proof["verified"] and proof["confirmed"] and proof["amount"] == int(attempt.amount * 100) and proof["paid"] is not None:
        service.mark_paid(provider=attempt.provider, provider_payment_id=attempt.provider_payment_id,
                          amount_cents=proof["paid"], receipt_url=proof["receipt"])
    attempt.refresh_from_db()
    return diagnostic(attempt)


def latest_event(attempt):
    from django.db.models import Q
    if not attempt.provider_payment_id:
        return None
    if attempt.provider == "infinitepay":
        from integrations.bank.infinitepay.models import WebhookEvent
        return WebhookEvent.objects.filter(order_nsu=attempt.provider_payment_id).order_by("-received_at").first()
    from integrations.bank.asaas.models import Payment, WebhookEvent
    payment = Payment.objects.filter(payment_id=attempt.provider_payment_id).first()
    query = Q(payload__payment__externalReference=attempt.provider_payment_id)
    if payment and payment.asaas_id:
        query |= Q(payload__payment__id=payment.asaas_id) | Q(payload__payment__pixQrCodeId=payment.asaas_id)
    return WebhookEvent.objects.filter(query).filter(event__in=("PAYMENT_CONFIRMED", "PAYMENT_RECEIVED",
        "PAYMENT_REFUNDED", "PAYMENT_CHARGEBACK_REQUESTED", "PAYMENT_CHARGEBACK_DISPUTE")).order_by("-received_at").first()


@transaction.atomic
def restore_projection(attempt, lead):
    """When a superseded charge pays, project the successful charge; preserve the newer one."""
    current = Checkout.objects.filter(lead=lead).first()
    if current and current.pk == attempt.checkout_id:
        return current
    if current:
        newer = sync(current)
        newer.superseded = True
        newer.checkout = None
        newer.save(update_fields=["superseded", "checkout", "updated_at"])
        current.delete()
    checkout = Checkout.objects.create(lead=lead, **{field: getattr(attempt, field) for field in SNAPSHOT_FIELDS})
    attempt.checkout = checkout
    attempt.save(update_fields=["checkout", "updated_at"])
    return checkout
