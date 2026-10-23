from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from django.core.management import call_command
from django.utils import timezone

from core import hooks
from integrations.bank import recovery
from integrations.bank.infinitepay import checkout as ip_checkout
from integrations.bank.infinitepay import webhooks as ip_webhooks
from integrations.bank.infinitepay.models import Checkout, WebhookEvent

pytestmark = pytest.mark.django_db
REAL_ENQUEUE = recovery._enqueue


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    monkeypatch.setattr(recovery, "_enqueue", lambda *args: None)


@pytest.fixture
def intent():
    return Checkout.objects.create(amount_cents=1000, request_payload={"handle": "original-handle"})


def payload(intent, **changes):
    return {"order_nsu": str(intent.external_id), "transaction_nsu": "transaction", "invoice_slug": "invoice", "receipt_url": "https://receipt.infinitepay.io/original", **changes}


def confirmed(monkeypatch, **changes):
    async def check(*args):
        return {"success": True, "paid": True, "amount": 1000, "paid_amount": 1010, "installments": 1, "capture_method": "credit_card", **changes}
    monkeypatch.setattr(ip_webhooks, "_payment_check", check)


@pytest.mark.parametrize("proof,code", [
    ({"paid_amount": None}, "amount_missing"),
    ({"amount": None}, "amount_missing"),
    ({"amount": 900, "paid_amount": 1100}, "amount_mismatch"),
    ({"paid_amount": 999}, "amount_mismatch"),
    ({"amount": True}, "invalid_amount"),
    ({"paid_amount": "1010"}, "invalid_amount"),
    ({"paid": "true"}, "not_paid"),
    ({"success": "true"}, "payment_check_unsuccessful"),
])
def test_infinitepay_requires_documented_financial_proof(intent, monkeypatch, proof, code):
    confirmed(monkeypatch, **proof)
    row, result, reason = ip_webhooks._apply(str(intent.external_id), payload(intent))
    assert row is None and reason == code
    intent.refresh_from_db()
    assert intent.status == "PENDING" and intent.paid_amount_cents is None


def test_infinitepay_confirms_with_original_account(intent, settings, monkeypatch):
    settings.INFINITEPAY_HANDLE = "different-current-account"
    seen = []
    async def check(handle, *args):
        seen.append(handle)
        return {"success": True, "paid": True, "amount": 1000, "paid_amount": 1000}
    monkeypatch.setattr(ip_webhooks, "_payment_check", check)
    ip_webhooks._apply(str(intent.external_id), payload(intent))
    assert seen == ["original-handle"]


def test_duplicate_reference_cannot_replace_verified_receipt(intent, monkeypatch):
    confirmed(monkeypatch)
    monkeypatch.setattr(hooks, "dispatch", lambda *args, **kwargs: True)
    ip_webhooks.handle_event(str(intent.external_id), payload(intent))
    async def forbidden(*args):
        pytest.fail("duplicate consulted provider")
    monkeypatch.setattr(ip_webhooks, "_payment_check", forbidden)
    event, result = ip_webhooks.handle_event(str(intent.external_id), payload(intent, transaction_nsu="forged", receipt_url="https://attacker.example/receipt"))
    assert event.last_error_code == "reference_mismatch" and not event.forwarded_ok
    calls = []
    monkeypatch.setattr(hooks, "dispatch", lambda *args, **kwargs: calls.append(kwargs) or True)
    ip_webhooks.handle_event(str(intent.external_id), payload(intent, receipt_url="https://receipt.infinitepay.io/changed"))
    assert calls[0]["receipt_url"] == "https://receipt.infinitepay.io/original"


def test_legacy_paid_event_upgrades_missing_proof(intent, monkeypatch):
    intent.status, intent.transaction_nsu, intent.slug = "PAID", "transaction", "invoice"
    intent.save()
    confirmed(monkeypatch)
    row, result, reason = ip_webhooks._apply(str(intent.external_id), payload(intent))
    assert row.payment_check_payload["amount"] == 1000


def test_async_receipt_never_calls_provider_before_ack(intent, client, monkeypatch):
    monkeypatch.setattr(ip_webhooks, "_payment_check", lambda *args: pytest.fail("provider called in receiver"))
    response = client.post("/integrations/infinitepay/webhook/", data=payload(intent), content_type="application/json")
    assert response.status_code == 200
    event = WebhookEvent.objects.get()
    assert event.processing_state == "pending" and not event.forwarded_ok


def test_missing_consumer_is_retried_and_eventually_applied(intent, monkeypatch):
    confirmed(monkeypatch)
    monkeypatch.setattr(hooks, "dispatch", lambda *args, **kwargs: False)
    event = recovery.receive("infinitepay", payload(intent))
    result = recovery.process("infinitepay", event.pk)
    event.refresh_from_db()
    assert result["state"] == "retry" and result["code"] == "consumer_missing"
    assert not event.forwarded_ok
    intent.refresh_from_db()
    assert intent.status == "PAID" and intent.payment_check_payload["paid"] is True
    monkeypatch.setattr(hooks, "dispatch", lambda *args, **kwargs: True)
    WebhookEvent.objects.filter(pk=event.pk).update(next_attempt_at=timezone.now())
    assert recovery.recover()["applied"] == 1
    event.refresh_from_db()
    assert event.forwarded_ok and event.processing_state == "applied" and event.attempts == 2


def test_queue_failure_keeps_receipt_for_recovery(intent, monkeypatch, django_capture_on_commit_callbacks):
    from core import tasks
    calls = []
    def failed_publish(*args, **kwargs):
        calls.append(args)
        raise RuntimeError("broker failure with private content")
    monkeypatch.setattr(tasks, "async_task", failed_publish)
    monkeypatch.setattr(recovery, "_enqueue", REAL_ENQUEUE)
    with django_capture_on_commit_callbacks(execute=True):
        event = recovery.receive("infinitepay", payload(intent))
    assert len(calls) == 1 and WebhookEvent.objects.filter(pk=event.pk).exists()
    confirmed(monkeypatch)
    monkeypatch.setattr(hooks, "dispatch", lambda *args, **kwargs: True)
    assert recovery.recover()["applied"] == 1


def test_processing_lease_prevents_overlap_and_recovers_crash(intent, monkeypatch):
    confirmed(monkeypatch)
    monkeypatch.setattr(hooks, "dispatch", lambda *args, **kwargs: True)
    event = recovery.receive("infinitepay", payload(intent))
    event.processing_state = "processing"
    event.lease_until = timezone.now() + timedelta(minutes=1)
    event.lease_token = uuid4()
    event.save()
    assert recovery.process("infinitepay", event.pk)["code"] == "not_claimed"
    WebhookEvent.objects.filter(pk=event.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
    assert recovery.process("infinitepay", event.pk)["state"] == "applied"


def test_processing_failure_is_sanitized_and_retries(intent, monkeypatch):
    async def outage(*args):
        raise httpx.ReadTimeout("private customer data must not be exposed")
    monkeypatch.setattr(ip_webhooks, "_payment_check", outage)
    event = recovery.receive("infinitepay", payload(intent))
    result = recovery.process("infinitepay", event.pk)
    assert result["state"] == "retry" and result["code"] == "processing_failed"
    assert "private" not in str(result)
    assert result["event_id"] == event.pk


def test_uncertain_creation_never_submits_second_link(settings, monkeypatch):
    settings.EXTERNAL_URL = "https://api.supletivo.net.br"
    settings.INFINITEPAY_HANDLE = "test-handle"
    external_id = uuid4()
    calls = []
    async def timeout(body):
        calls.append(body)
        raise httpx.ReadTimeout("unknown provider result")
    monkeypatch.setattr(ip_checkout, "_create_link", timeout)
    for _ in range(2):
        with pytest.raises(ip_checkout.CheckoutError, match="checkout_creation_uncertain"):
            ip_checkout.create_checkout(amount_cents=1000, description="test", external_id=external_id)
    assert len(calls) == 1 and Checkout.objects.count() == 1
    assert Checkout.objects.get().request_payload["handle"] == "test-handle"


def test_ready_creation_without_slug_reuses_stable_intent(settings, monkeypatch):
    settings.EXTERNAL_URL = "https://api.supletivo.net.br"
    settings.INFINITEPAY_HANDLE = "test-handle"
    calls = []
    async def link(body):
        calls.append(body)
        return {"url": "https://checkout.infinitepay.com.br/test?lenc=example"}
    monkeypatch.setattr(ip_checkout, "_create_link", link)
    external_id = uuid4()
    first = ip_checkout.create_checkout(amount_cents=1000, description="test", external_id=external_id)
    second = ip_checkout.create_checkout(amount_cents=1000, description="test", external_id=external_id)
    assert first.pk == second.pk and first.creation_state == "ready" and first.slug is None
    assert len(calls) == 1


def test_stale_creation_becomes_uncertain_without_post(monkeypatch):
    row = Checkout.objects.create(amount_cents=1000, creation_state="creating", creation_started_at=timezone.now() - timedelta(minutes=3))
    assert recovery.recover()["creation_uncertain"] == 1
    row.refresh_from_db()
    assert row.creation_state == "uncertain"


@pytest.mark.parametrize("value,code", [(None, "amount_missing"), (9, "amount_mismatch"), ("NaN", "amount_mismatch"), (True, "invalid_amount")])
def test_asaas_requires_fixed_gross_value(monkeypatch, value, code):
    from integrations.bank.asaas import webhooks
    from integrations.bank.asaas.models import Payment
    row = Payment.objects.create(payment_id="fixed", kind="static_pix_qr", asaas_id="qr-id", amount=Decimal("10"), status="PENDING")
    event = webhooks.handle_event({"event": "PAYMENT_RECEIVED", "payment": {"pixQrCodeId": "qr-id", "value": value}})
    row.refresh_from_db()
    assert row.status == "PENDING" and event.last_error_code == code and not event.forwarded_ok


def test_asaas_paid_and_refunded_need_consumer_but_transfer_does_not(monkeypatch):
    from integrations.bank.asaas import webhooks
    from integrations.bank.asaas.models import Payment
    monkeypatch.setattr(hooks, "dispatch", lambda *args, **kwargs: False)
    Payment.objects.create(payment_id="charge", kind="charge", asaas_id="pay", amount=10, status="PENDING")
    for event in ("PAYMENT_RECEIVED", "PAYMENT_REFUNDED"):
        row = webhooks.handle_event({"event": event, "payment": {"id": "pay", "value": 10}})
        assert not row.forwarded_ok and row.last_error_code == "consumer_missing"
    Payment.objects.create(payment_id="transfer", kind="pixkey", asaas_id="transfer", amount=10, status="SUBMITTED")
    row = webhooks.handle_event({"event": "TRANSFER_DONE", "transfer": {"id": "transfer"}})
    assert row.forwarded_ok and not row.last_error_code


def test_reconcile_uses_stored_proof_and_receipt(intent, monkeypatch):
    assert recovery.reconcile_attempt("infinitepay", str(intent.external_id))["code"] == "financial_proof_missing"
    confirmed(monkeypatch)
    ip_webhooks._apply(str(intent.external_id), payload(intent))
    calls = []
    monkeypatch.setattr(hooks, "dispatch", lambda *args, **kwargs: calls.append(kwargs) or True)
    assert recovery.reconcile_attempt("infinitepay", str(intent.external_id))["consumed"]
    assert calls[0]["receipt_url"] == "https://receipt.infinitepay.io/original"


def test_recovery_schedule_is_every_minute_and_idempotent():
    from django_q.models import Schedule
    call_command("payment_schedules")
    call_command("payment_schedules")
    row = Schedule.objects.get(name="payment_event_recovery")
    assert row.minutes == 1 and row.schedule_type == Schedule.MINUTES and row.repeats == -1


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://attacker.example/receipt", "https://receipt.infinitepay.io.attacker.example/path", "https://user:pass@receipt.infinitepay.io/path"])
def test_receipt_rejects_untrusted_navigation(url):
    assert recovery.safe_receipt_url(url) is None
