"""Read-only recovery of missed transfer callbacks. All provider calls are mocked."""
from decimal import Decimal

import pytest

from integrations.bank.asaas import payout
from integrations.bank.asaas.models import Payment

pytestmark = pytest.mark.django_db


@pytest.fixture
def provider(monkeypatch, settings):
    settings.APP_ENV = "prod"
    settings.TEST_EXTERNAL_ADAPTERS = False
    class Client:
        calls = []
        records = []
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def list_transfers(self, params):
            self.calls.append(("GET", "list", params))
            return {"data": self.records, "hasMore": False}
        async def get_transfer(self, transfer_id):
            self.calls.append(("GET", transfer_id))
            return self.records[0]
        async def create_transfer(self, *args, **kwargs):
            raise AssertionError("Reconciliation cannot send money")
    client = Client()
    monkeypatch.setattr(payout, "get_client", lambda: client)
    return client


def test_uncertain_transfer_is_recovered_by_exact_reference_without_resending(provider):
    row = Payment.objects.create(payment_id="offline-lost-response", kind=Payment.Kind.PIXKEY, amount=Decimal("100"), status="SUBMITTING")
    provider.records = [{"id": "unrelated", "externalReference": "other", "value": 100, "status": "DONE"}, {"id": "known-transfer", "externalReference": row.payment_id, "value": 100, "status": "DONE"}]
    recovered = payout.refresh_payout(row.payment_id)
    assert recovered.asaas_id == "known-transfer"
    assert recovered.status == "PAID"
    assert len(provider.calls) == 1


def test_known_pending_transfer_uses_single_transfer_lookup(provider):
    row = Payment.objects.create(payment_id="offline-pending", kind=Payment.Kind.PIXKEY, asaas_id="known-transfer", amount=100, status="SUBMITTED")
    provider.records = [{"id": row.asaas_id, "externalReference": row.payment_id, "value": 100, "status": "DONE"}]
    assert payout.refresh_payout(row.payment_id).status == "PAID"
    assert provider.calls == [("GET", row.asaas_id)]


def test_recovery_refuses_a_different_amount(provider):
    row = Payment.objects.create(payment_id="offline-wrong-amount", kind=Payment.Kind.PIXKEY, amount=100, status="SUBMITTING")
    provider.records = [{"id": "wrong", "externalReference": row.payment_id, "value": 999, "status": "DONE"}]
    with pytest.raises(payout.PayoutError, match="amount_mismatch"):
        payout.refresh_payout(row.payment_id)
    row.refresh_from_db()
    assert row.status == "SUBMITTING"


def test_recovery_with_no_match_remains_uncertain_without_resending(provider):
    row = Payment.objects.create(payment_id="offline-no-match", kind=Payment.Kind.PIXKEY, amount=100, status="SUBMITTING")
    with pytest.raises(payout.PayoutError, match="transfer_not_found"):
        payout.refresh_payout(row.payment_id)
    row.refresh_from_db()
    assert row.status == "SUBMITTING"


def test_late_transfer_event_cannot_downgrade_confirmed_money():
    from integrations.bank.asaas.webhooks import handle_event
    row = Payment.objects.create(payment_id="offline-confirmed", kind=Payment.Kind.PIXKEY, asaas_id="known", amount=100, status="PAID")
    handle_event({"event": "TRANSFER_PENDING", "transfer": {"id": "known", "externalReference": row.payment_id}})
    row.refresh_from_db()
    assert row.status == "PAID"


def test_blocked_transfer_remains_in_reconciliation_instead_of_becoming_retryable():
    from integrations.bank.asaas.webhooks import handle_event
    row = Payment.objects.create(payment_id="offline-blocked", kind=Payment.Kind.PIXKEY, asaas_id="known", amount=100, status="SUBMITTED")
    handle_event({"event": "TRANSFER_BLOCKED", "transfer": {"id": "known", "externalReference": row.payment_id}})
    row.refresh_from_db()
    assert row.status == "SUBMITTED"
