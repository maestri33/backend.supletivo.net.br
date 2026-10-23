from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


def test_asaas_apply_failure_is_persisted_and_propagated_for_retry(monkeypatch):
    from integrations.bank.asaas import webhooks
    from integrations.bank.asaas.models import WebhookEvent

    def database_failure(*args):
        raise RuntimeError("transient apply failure")

    monkeypatch.setattr(webhooks, "_apply_charge", database_failure)
    with pytest.raises(RuntimeError, match="transient apply failure"):
        webhooks.handle_event({"event": "PAYMENT_RECEIVED", "payment": {"id": "pay-provider"}})
    assert WebhookEvent.objects.count() == 1
    assert not WebhookEvent.objects.get().forwarded_ok


def test_infinitepay_check_outage_does_not_acknowledge_payment(monkeypatch):
    from integrations.bank.infinitepay import webhooks
    from integrations.bank.infinitepay.client import InfinitePayError
    from integrations.bank.infinitepay.models import Checkout, WebhookEvent

    row = Checkout.objects.create(amount_cents=99900, description="test", status="PENDING", request_payload={"handle": "original-handle"})

    async def unavailable(*args):
        raise InfinitePayError("provider unavailable", status_code=503)

    monkeypatch.setattr(webhooks, "_payment_check", unavailable)
    with pytest.raises(InfinitePayError):
        webhooks.handle_event(str(row.external_id), {"transaction_nsu": "tx", "slug": "slug"})
    row.refresh_from_db()
    assert row.status == Checkout.Status.PENDING
    assert not WebhookEvent.objects.get().forwarded_ok


@pytest.mark.parametrize("handler", ["mark_payment_failed", "mark_payment_expired"])
def test_paid_checkout_cannot_be_downgraded_by_failure_event(monkeypatch, handler):
    from users.auth.models import User
    from users.roles.lead import service
    from users.roles.lead.models import Checkout, Lead

    student = User.objects.create_user()
    lead = Lead.objects.create(user=student, promoter=student, self_study=True)
    Checkout.objects.create(
        lead=lead, amount=Decimal("999.00"), provider="asaas", provider_payment_id="paid-checkout",
        payment_method="pix", is_paid=True,
    )
    monkeypatch.setattr(service, "_notify_payment_recovery", lambda *args, **kwargs: pytest.fail("paid recovery notification"))
    assert getattr(service, handler)(provider="asaas", provider_payment_id="paid-checkout")
    lead.refresh_from_db()
    assert lead.status == Lead.Status.PENDING
