"""Durable receipt and leased processing of inbound payment notifications."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from uuid import uuid4

import structlog
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import F, Q
from django.utils import timezone

logger = structlog.get_logger()
MAX_ATTEMPTS = 10
LEASE_SECONDS = 120


def _model(provider):
    if provider == "infinitepay":
        from integrations.bank.infinitepay.models import WebhookEvent
    elif provider == "asaas":
        from integrations.bank.asaas.models import WebhookEvent
    else:
        raise ValueError("unsupported_provider")
    return WebhookEvent


def safe_receipt_url(value):
    """Receipt links may only navigate to a known gateway over HTTPS."""
    if not isinstance(value, str) or len(value) > 500:
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        trusted = ("infinitepay.io", "infinitepay.com.br", "asaas.com", "asaas.com.br")
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
        if not any(host == domain or host.endswith("." + domain) for domain in trusted):
            return None
    except ValueError:
        return None
    return value


def _enqueue(provider, event_id):
    from core.tasks import async_task

    try:
        async_task("integrations.bank.recovery.process", provider, event_id)
    except Exception:
        # Receipt survives broker failures and is picked up by the minute recovery schedule.
        logger.warning("payment_event_enqueue_failed", provider=provider, event_id=event_id, code="queue_unavailable")


def receive(provider, payload, *, order_nsu=None, source_ip=None, user_agent=None):
    """Commit raw receipt before acknowledging; provider I/O runs in a worker."""
    model = _model(provider)
    body = payload if isinstance(payload, dict) else {"_raw": payload}
    fields = {
        "payload": body,
        "source_ip": str(source_ip).split(",", 1)[0].strip()[:64] if source_ip else None,
        "user_agent": user_agent,
    }
    if provider == "infinitepay":
        fields["order_nsu"] = str(order_nsu or body.get("order_nsu") or "")[:128]
    else:
        fields["event"] = str(body.get("event") or "")[:255]
    with transaction.atomic():
        row = model.objects.create(**fields)
        transaction.on_commit(lambda: _enqueue(provider, row.pk))
    return row


def _outcome(code, attempts):
    if not code:
        return "applied"
    if code in {"payment_updated_noop", "status_unchanged"} or code.startswith("terminal_"):
        return "ignored"
    if code in {
        "consumer_missing", "processing_failed", "payment_check_failed",
        "payment_check_unsuccessful", "not_paid", "no_matching_checkout",
        "no_matching_charge", "no_matching_transfer",
    }:
        return "review" if attempts >= MAX_ATTEMPTS else "retry"
    return "review"


def process(provider, event_id):
    """Claim with an expiring ORM lease. A late worker cannot finish another worker's lease."""
    model = _model(provider)
    now, token = timezone.now(), uuid4()
    available = (
        Q(processing_state__in=("pending", "retry"), next_attempt_at__lte=now)
        | Q(processing_state="processing", lease_until__lte=now)
    )
    claimed = model.objects.filter(pk=event_id).filter(available).update(
        processing_state="processing", lease_token=token,
        lease_until=now + timedelta(seconds=LEASE_SECONDS), attempts=F("attempts") + 1,
    )
    if not claimed:
        row = model.objects.filter(pk=event_id).first()
        return {"provider": provider, "event_id": event_id, "state": row.processing_state if row else "missing", "code": "not_claimed"}
    row = model.objects.get(pk=event_id)
    code = ""
    try:
        if provider == "infinitepay":
            from integrations.bank.infinitepay import webhooks
            webhooks.handle_event(row.order_nsu, row.payload, event_row=row)
        else:
            from integrations.bank.asaas import webhooks
            webhooks.handle_event(row.payload, event_row=row)
        row.refresh_from_db()
        code = row.last_error_code
    except Exception:
        code = "processing_failed"
        logger.warning("payment_event_processing_failed", provider=provider, event_id=event_id, code=code)
    state = _outcome(code, row.attempts)
    retry_at = timezone.now() + timedelta(seconds=min(60 * 2 ** min(row.attempts - 1, 6), 3600))
    model.objects.filter(pk=event_id, lease_token=token).update(
        processing_state=state, last_error_code=code, lease_until=None, lease_token=None,
        next_attempt_at=retry_at, processed_at=timezone.now() if state in ("applied", "review", "ignored") else None,
    )
    return {"provider": provider, "event_id": event_id, "state": state, "code": code}


def recover(limit=5):
    """Recover receipts after failed publishing, transient processing or an expired lease."""
    now = timezone.now()
    counts = {"processed": 0, "retry": 0, "review": 0, "applied": 0, "ignored": 0}
    for provider in ("infinitepay", "asaas"):
        model = _model(provider)
        due = model.objects.filter(
            Q(processing_state__in=("pending", "retry"), next_attempt_at__lte=now)
            | Q(processing_state="processing", lease_until__lte=now)
        ).order_by("received_at").values_list("pk", flat=True)[:limit]
        for event_id in list(due):
            result = process(provider, event_id)
            if result["state"] in counts:
                counts[result["state"]] += 1
                counts["processed"] += 1
    # A process death during POST /links has an unknown financial outcome, never a safe retry.
    from integrations.bank.infinitepay.models import Checkout
    counts["creation_uncertain"] = Checkout.objects.filter(
        creation_state="creating", creation_started_at__lte=now - timedelta(seconds=LEASE_SECONDS),
        checkout_url__isnull=True,
    ).update(creation_state="uncertain", response_payload={"error_code": "checkout_creation_uncertain"})
    return counts


def reconcile_attempt(provider, provider_payment_id):
    """Reapply only stored provider confirmation, without trusting an operator-supplied payload."""
    from core import hooks

    if provider == "infinitepay":
        from integrations.bank.infinitepay.models import Checkout
        try:
            row = Checkout.objects.filter(external_id=provider_payment_id).first()
        except (ValueError, TypeError, ValidationError):
            row = None
        if row is None:
            return {"consumed": False, "state": "review", "code": "no_matching_checkout"}
        proof = row.payment_check_payload
        if row.status != "PAID" or not isinstance(proof, dict) or proof.get("success") is not True or proof.get("paid") is not True:
            return {"consumed": False, "state": "review", "code": "financial_proof_missing"}
        amount, paid = proof.get("amount"), proof.get("paid_amount")
        if type(amount) is not int or type(paid) is not int or amount != row.amount_cents or paid < amount:
            return {"consumed": False, "state": "review", "code": "amount_mismatch"}
        event, amount_cents, receipt = "payment.paid", paid, row.receipt_url
    elif provider == "asaas":
        from integrations.bank.asaas.models import Payment
        row = Payment.objects.filter(payment_id=provider_payment_id, kind__in=("charge", "static_pix_qr")).first()
        if row is None:
            return {"consumed": False, "state": "review", "code": "no_matching_charge"}
        if row.status not in ("PAID", "REFUNDED", "DISPUTED"):
            return {"consumed": False, "state": "review", "code": "financial_proof_missing"}
        if row.status == "PAID":
            try:
                value = Decimal(str(row.confirmation_payload.get("value")))
                valid = value.is_finite() and value == row.amount
            except (InvalidOperation, ValueError, TypeError, AttributeError):
                valid = False
            if not valid:
                return {"consumed": False, "state": "review", "code": "financial_proof_missing"}
        event = {"PAID": "payment.paid", "REFUNDED": "payment.refunded", "DISPUTED": "payment.disputed"}[row.status]
        amount_cents, receipt = int(row.amount * 100), row.receipt_url
    else:
        raise ValueError("unsupported_provider")
    try:
        consumed = hooks.dispatch(event, reraise=True, provider=provider, provider_payment_id=str(provider_payment_id), amount_cents=amount_cents, **({"receipt_url": receipt} if event == "payment.paid" else {}))
    except Exception:
        return {"consumed": False, "state": "retry", "code": "processing_failed"}
    return {"consumed": consumed, "state": "applied" if consumed else "retry", "code": "" if consumed else "consumer_missing"}
