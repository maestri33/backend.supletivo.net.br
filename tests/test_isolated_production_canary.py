"""Financial isolation regressions; local DB events are not production payment evidence."""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
import uuid

import pytest
from django.utils import timezone

from core.models import PlatformSetting
from finance import canary
from finance.interface.commissions import credit_commission
from finance.interface.weekly import _groups, _items
from finance.interface.reversals import reverse_commission
from finance.models import Commission, FinancialTransaction, PaymentRequest
from hub.models import Hub
from users.address.models import Address
from users.auth.models import User
from users.profiles.models import Profile
from users.roles.lead.models import Lead, Checkout
from users.roles.promoter.models import Promoter

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup_run():
    actor = User.objects.create_user(is_staff=True)
    owner = User.objects.create_user()
    student = User.objects.create_user()
    Profile.objects.create(user=owner, cpf="11144477735", phone="554396111111", pix_key="11144477735")
    Profile.objects.create(user=student, cpf="52998224725", phone="554298222222")
    hub = Hub.objects.create(address=Address.objects.create(city="Curitiba", state="PR"), brand="standard")
    Promoter.objects.create(user=owner, hub=hub, activated_at=timezone.now()-timedelta(days=21))
    run = canary.configure(actor=actor, owner=owner,
        allowlist=[{"cpf": "11144477735", "phone": "43996111111"}, {"cpf": "52998224725", "phone": "42998222222"}],
        justification="Local isolation regression")
    return actor, owner, student, run


def paid_source(setup_run):
    _, owner, student, _ = setup_run
    lead = Lead.objects.create(user=student, promoter=owner, status=Lead.Status.PAID)
    Checkout.objects.create(lead=lead, payment_method="pix", provider="asaas", provider_payment_id="local-event-fixture", amount=lead.pix_price, is_paid=True)
    return lead


def test_staff_required_and_no_global_commercial_setting_changes(setup_run):
    actor, owner, student, run = setup_run
    assert run["proposal_count"] == 0
    assert not PlatformSetting.objects.filter(key__in=["ENROLLMENT_PRICE_PIX", "COMMISSION_DIRECT"]).exists()
    with pytest.raises(canary.CanaryError, match="staff_required"):
        canary.disable(actor=owner, justification="unauthorized")
    assert canary.pricing_snapshot(User.objects.create_user()) is None
    assert canary.pricing_snapshot(student)["pix"] == "1.01"


def test_frozen_pricing_survives_disabled_run_and_cannot_be_tampered(setup_run):
    actor, owner, student, _ = setup_run
    lead = Lead.objects.create(user=student, promoter=owner)
    assert lead.card_price == Decimal("1.02") and lead.card_installments == 1
    assert lead.pix_price == Decimal("1.01")
    snapshot = lead.pricing_snapshot.copy()
    canary.disable(actor=actor, justification="test finished")
    lead.lock_pricing()
    assert lead.pricing_snapshot == snapshot
    with pytest.raises(canary.CanaryError, match="snapshot_invalid"):
        canary.validate_snapshot(snapshot["canary"] | {"direct": "100.00"})
    assert canary.pricing_snapshot(student) is None


def test_source_payment_and_recipient_are_checked_before_credit(setup_run):
    _, owner, student, _ = setup_run
    lead = Lead.objects.create(user=student, promoter=owner)
    with pytest.raises(canary.CanaryError, match="payment_unconfirmed"):
        credit_commission(payee=owner, payee_role="promoter", source_type="lead", source_external_id=lead.external_id)
    assert not Commission.objects.exists()
    Checkout.objects.create(lead=lead, payment_method="pix", provider="asaas", provider_payment_id="local-event-fixture", amount=Decimal("1.02"), is_paid=True)
    lead.status = Lead.Status.PAID; lead.save()
    with pytest.raises(canary.CanaryError, match="checkout_amount_mismatch"):
        credit_commission(payee=owner, payee_role="promoter", source_type="lead", source_external_id=lead.external_id)


def test_canary_credit_is_idempotent_and_other_sales_keep_commercial_rate(setup_run):
    _, owner, _, run = setup_run
    lead = paid_source(setup_run)
    item = credit_commission(payee=owner, payee_role="promoter", source_type="lead", source_external_id=lead.external_id)
    again = credit_commission(payee=owner, payee_role="promoter", source_type="lead", source_external_id=lead.external_id)
    ordinary = credit_commission(payee=owner, payee_role="promoter", source_type="lead", source_external_id=uuid.uuid4())
    assert item.pk == again.pk and item.amount == Decimal("0.01")
    assert str(item.canary_run_id) == run["run_id"]
    assert ordinary.amount == Decimal("100.00") and ordinary.canary_run_id is None
    assert FinancialTransaction.objects.filter(canary_run_id=run["run_id"]).count() == 1


def test_proposal_quota_is_bounded(setup_run):
    _, _, student, _ = setup_run
    for _ in range(5):
        assert canary.pricing_snapshot(student)
    with pytest.raises(canary.CanaryError, match="proposal_limit"):
        canary.pricing_snapshot(student)


def test_bonus_counts_and_batches_do_not_mix_canary_with_commercial_sales(setup_run):
    _, owner, _, run = setup_run
    lead = paid_source(setup_run)
    terms = lead.pricing_snapshot["canary"]
    for _ in range(5):
        Commission.objects.create(payee=owner, payee_role="promoter", source_type="lead", source_external_id=uuid.uuid4(), amount="0.01", canary_run_id=run["run_id"], canary_snapshot=terms)
    for _ in range(4):
        Commission.objects.create(payee=owner, payee_role="promoter", source_type="lead", source_external_id=uuid.uuid4(), amount="100")
    end = datetime(2026, 10, 16, 21, tzinfo=dt_timezone.utc)
    items, bonuses, _ = _items(end, persist=True)
    assert bonuses == 1
    bonus = Commission.objects.get(source_type="bonus")
    assert bonus.amount == Decimal("0.10") and str(bonus.canary_run_id) == run["run_id"]
    assert _items(end, persist=True)[1] == 0
    groups, _ = _groups(items, end)
    assert groups[owner.pk]["amount"] == Decimal("400")
    assert groups[(owner.pk, run["run_id"])]["amount"] == Decimal("0.15")
    sale = Commission.objects.filter(canary_run_id=run["run_id"], source_type="lead").first()
    reverse_commission(sale)
    bonus.refresh_from_db()
    assert bonus.status == Commission.Status.CANCELLED


def test_payout_rejects_mixed_amounts_and_another_recipient(setup_run):
    _, owner, _, run = setup_run
    lead = paid_source(setup_run)
    item = credit_commission(payee=owner, payee_role="promoter", source_type="lead", source_external_id=lead.external_id)
    pr = PaymentRequest.objects.create(payee=owner, payee_role="promoter", external_reference="local-test", amount="0.01", pix_key=owner.profile.cpf, canary_run_id=run["run_id"])
    item.payment_request=pr;item.save()
    canary.validate_payout(pr)
    pr.amount=Decimal("0.02")
    with pytest.raises(canary.CanaryError, match="amount_invalid"):canary.validate_payout(pr)
    pr.amount=Decimal("0.01");pr.pix_key="52998224725"
    with pytest.raises(canary.CanaryError, match="pix_recipient_invalid"):canary.validate_payout(pr)
    pr.pix_key=owner.profile.cpf
    Commission.objects.create(payee=owner,payee_role="promoter",source_type="manual",source_external_id=uuid.uuid4(),amount="100",payment_request=pr)
    with pytest.raises(canary.CanaryError, match="batch_mixed"):canary.validate_payout(pr)


def test_paid_reversal_preserves_isolation_and_original_amount(setup_run):
    _, owner, _, run = setup_run
    lead = paid_source(setup_run)
    item = credit_commission(payee=owner,payee_role="promoter",source_type="lead",source_external_id=lead.external_id)
    item.status=Commission.Status.PAID;item.save()
    reverse_commission(item)
    debt = Commission.objects.get(source_type=Commission.Source.REVERSAL)
    assert debt.amount == Decimal("-0.01") and str(debt.canary_run_id)==run["run_id"]
    assert debt.canary_snapshot == item.canary_snapshot


def test_invalid_source_is_rejected_before_any_bank_submission(setup_run, monkeypatch):
    from finance.interface import payout
    _, owner, _, run = setup_run
    lead = paid_source(setup_run)
    item = credit_commission(payee=owner, payee_role="promoter", source_type="lead", source_external_id=lead.external_id)
    pr = PaymentRequest.objects.create(payee=owner, payee_role="promoter", external_reference="local-invalid-source",
        amount="0.01", pix_key=owner.profile.cpf, canary_run_id=run["run_id"])
    item.source_external_id = uuid.uuid4()
    item.payment_request = pr
    item.save()
    def unexpected_bank_call(*args, **kwargs):
        pytest.fail("An invalid canary must never call the bank")
    monkeypatch.setattr(payout.asaas_payout, "create_payout", unexpected_bank_call)
    result = payout.process_payment_requests(external_id=pr.external_id)
    pr.refresh_from_db()
    assert result["failed"] == 1 and pr.status == PaymentRequest.Status.FAILED
    assert pr.attempts == 0 and pr.last_error == "canary_commission_source_invalid"


def test_expired_run_stops_new_quotes_but_preserves_issued_proposal(setup_run):
    import json
    _, owner, student, _ = setup_run
    lead = Lead.objects.create(user=student, promoter=owner)
    row = PlatformSetting.objects.get(key=canary.CONFIG_KEY)
    value = json.loads(row.value)
    value["expires_at"] = (timezone.now()-timedelta(seconds=1)).isoformat()
    row.value = json.dumps(value)
    row.save()
    assert canary.pricing_snapshot(student) is None
    lead.lock_pricing()
    assert lead.pix_price == Decimal("1.01")
    canary.validate_snapshot(lead.pricing_snapshot["canary"])
