"""Cross-charge business recovery; controlled gateway boundaries, never production evidence."""
from decimal import Decimal

import pytest

from finance.models import Commission
from hub.models import Hub
from users.address.models import Address
from users.auth.models import User
from users.profiles import interface as profiles
from users.roles.models import UserRole
from users.roles.promoter.models import Promoter
from users.roles.enrollment.models import Enrollment
from users.roles.lead.models import Checkout, Lead, PaymentAttempt
from users.roles.lead import payments, service

pytestmark = pytest.mark.django_db


@pytest.fixture
def lead(monkeypatch):
    import core.tasks
    monkeypatch.setattr(core.tasks, "async_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_notify_paid", lambda *args: None)
    coordinator = User.objects.create_user()
    profiles.create(user=coordinator, cpf=None, phone="5543990000101", name="Test coordinator")
    hub = Hub.objects.create(coordinator=coordinator, address=Address.objects.create(), brand="Payment test")
    Promoter.objects.create(user=coordinator, hub=hub)
    UserRole.objects.create(user=coordinator, role="promoter")
    user = User.objects.create_user()
    profiles.create(user=user, cpf="12345678909", email="payment@example.test", phone="5542990000102", name="Test student")
    UserRole.objects.create(user=user, role="lead")
    return Lead.objects.create(user=user, promoter=coordinator, pix_price=Decimal("1.01"),
        card_price=Decimal("1.02"), pricing_snapshot={"pix": "1.01", "card": {
            "total": "1.02", "installments": 1, "installment": "1.02"}})


def test_same_method_keeps_exact_charge_and_short_link(lead):
    old = service._create_checkout_row(lead, "card")
    result = service.set_checkout(user_external_id=str(lead.user.external_id), payment_method="credit_card")
    assert Checkout.objects.get(lead=lead).pk == old.pk
    assert result["short_url"].endswith(old.short_token)
    assert PaymentAttempt.objects.filter(lead=lead).count() == 1


def test_old_card_paid_after_switch_is_applied_once_and_projected(lead):
    card = service._create_checkout_row(lead, "card")
    old_id = card.provider_payment_id
    service.set_checkout(user_external_id=str(lead.user.external_id), payment_method="pix")
    assert not Checkout.objects.filter(pk=card.pk).exists()
    assert service.mark_paid(provider="infinitepay", provider_payment_id=old_id, amount_cents=107)
    assert service.mark_paid(provider="infinitepay", provider_payment_id=old_id, amount_cents=107)
    lead.refresh_from_db()
    current = Checkout.objects.get(lead=lead)
    assert current.provider_payment_id == old_id and current.is_paid
    assert lead.status == "paid" and Enrollment.objects.filter(user=lead.user).count() == 1
    assert Commission.objects.filter(source_external_id=lead.external_id).count() == 1
    assert PaymentAttempt.objects.filter(lead=lead).count() == 2
    assert PaymentAttempt.objects.get(provider_payment_id=old_id).paid_amount == Decimal("1.07")
    from finance.models import FinancialTransaction
    receipt = FinancialTransaction.objects.get(kind="payment_received")
    assert receipt.amount == Decimal("1.02") and receipt.status == "pending"
    assert set(receipt.ledger_entries.values_list("account__code", flat=True)) == {"ASSET_INFINITEPAY", "REVENUE_ENROLLMENT"}


def test_additional_paid_charge_is_review_without_second_commission(lead):
    card = service._create_checkout_row(lead, "card")
    old_id = card.provider_payment_id
    service.set_checkout(user_external_id=str(lead.user.external_id), payment_method="pix")
    pix = Checkout.objects.get(lead=lead)
    assert service.mark_paid(provider="asaas", provider_payment_id=pix.provider_payment_id, amount_cents=101)
    assert not service.mark_paid(provider="infinitepay", provider_payment_id=old_id, amount_cents=102)
    old = PaymentAttempt.objects.get(provider_payment_id=old_id)
    assert old.provider_confirmed and not old.app_applied and old.last_error == "additional_payment_review"
    assert Commission.objects.filter(source_external_id=lead.external_id).count() == 1


def test_effect_failure_rolls_back_business_and_retry_succeeds(lead, monkeypatch):
    card = service._create_checkout_row(lead, "card")
    real_effects = service._apply_effects
    def fail(_):
        raise RuntimeError("hub temporary failure")
    monkeypatch.setattr(service, "_apply_effects", fail)
    with pytest.raises(RuntimeError):
        service.mark_paid(provider="infinitepay", provider_payment_id=card.provider_payment_id, amount_cents=102)
    lead.refresh_from_db()
    assert lead.status == "pending" and not Enrollment.objects.filter(user=lead.user).exists()
    assert not Commission.objects.filter(source_external_id=lead.external_id).exists()
    monkeypatch.setattr(service, "_apply_effects", real_effects)
    assert service.mark_paid(provider="infinitepay", provider_payment_id=card.provider_payment_id, amount_cents=102)


def test_deleted_account_payment_cannot_be_attached_to_recreated_user(lead):
    card = service._create_checkout_row(lead, "card")
    provider_id = card.provider_payment_id
    original_id = lead.user.external_id
    lead.user.delete()
    replacement = User.objects.create_user()
    assert not service.mark_paid(provider="infinitepay", provider_payment_id=provider_id, amount_cents=102)
    old = PaymentAttempt.objects.get(provider_payment_id=provider_id)
    assert old.lead_id is None and old.user_external_id == original_id
    assert old.last_error == "account_removed" and not Enrollment.objects.filter(user=replacement).exists()


def test_underpayment_and_paid_role_mismatch_do_not_unlock(lead):
    card = service._create_checkout_row(lead, "card")
    assert not service.mark_paid(provider="infinitepay", provider_payment_id=card.provider_payment_id, amount_cents=101)
    card.refresh_from_db()
    assert not card.is_paid
    Lead.objects.filter(pk=lead.pk).update(status="paid")
    lead.refresh_from_db()
    assert payments.payment_status(lead, card)["stage"] == "review"
    assert payments.payment_status(lead, card)["continuation_url"] is None


def test_card_return_requires_owner_and_provider_check_then_refreshes_role(lead, client, monkeypatch):
    from users.auth.jwt import service as jwt
    from integrations.bank.infinitepay.models import Checkout as CardCheckout
    from integrations.bank.infinitepay import webhooks
    card = service._create_checkout_row(lead, "card")
    CardCheckout.objects.create(external_id=card.provider_payment_id, amount_cents=102,
        request_payload={"handle": "original-test-account"})
    calls = []
    async def check(*args):
        calls.append(args)
        return {"success": True, "paid": True, "amount": 102, "paid_amount": 107,
                "installments": 1, "capture_method": "credit_card"}
    monkeypatch.setattr(webhooks, "_payment_check", check)
    owner_tokens = jwt.issue(str(lead.user.external_id), ["lead"])
    outsider = User.objects.create_user()
    UserRole.objects.create(user=outsider, role="lead")
    Lead.objects.create(user=outsider, promoter=lead.promoter)
    outsider_tokens = jwt.issue(str(outsider.external_id), ["lead"])
    body = {"order_nsu": card.provider_payment_id, "transaction_nsu": "verified-test-transaction", "slug": "test-invoice"}
    url = "/api/v1/clients/lead/card-confirmation"
    response = client.post(url, body, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {outsider_tokens['access_token']}")
    assert response.status_code == 404 and not calls
    response = client.post(url, body, content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {owner_tokens['access_token']}")
    assert response.status_code == 200, response.content
    assert response.json()["payment_status"] == {"stage": "completed", "continuation_url": "/student/enrollment",
        "actual_capture_method": "credit_card", "paid_amount": "1.07"}
    refreshed = jwt.refresh(owner_tokens["refresh_token"])
    assert "enrollment" in jwt.decode(refreshed["access_token"])["roles"]
    assert len(calls) == 1


def test_pending_local_provider_record_is_not_manual_financial_proof(lead):
    from integrations.bank.infinitepay.models import Checkout as CardCheckout
    card = service._create_checkout_row(lead, "card")
    CardCheckout.objects.create(external_id=card.provider_payment_id, amount_cents=102,
        status="PAID", paid_amount_cents=102, request_payload={"handle": "original-test-account"})
    result = payments.reconcile(payments.snapshot(card))
    assert not result["app_applied"] and result["last_error"] == "financial_proof_missing"
    assert not Enrollment.objects.filter(user=lead.user).exists()


def test_review_event_can_be_reverified_without_new_charge(lead, monkeypatch):
    from integrations.bank.infinitepay.models import Checkout as CardCheckout, WebhookEvent
    from integrations.bank.infinitepay import webhooks
    card = service._create_checkout_row(lead, "card")
    CardCheckout.objects.create(external_id=card.provider_payment_id, amount_cents=102,
        request_payload={"handle": "original-test-account"})
    WebhookEvent.objects.create(order_nsu=card.provider_payment_id, processing_state="review",
        last_error_code="amount_missing", payload={"order_nsu": card.provider_payment_id, "slug": "invoice", "transaction_nsu": "tx"})
    async def check(*args):
        return {"success": True, "paid": True, "amount": 102, "paid_amount": 102}
    monkeypatch.setattr(webhooks, "_payment_check", check)
    result = payments.reconcile(payments.snapshot(card))
    assert result["app_applied"] and not result["last_error"]
    assert CardCheckout.objects.count() == 1 and Checkout.objects.filter(lead=lead).count() == 1
