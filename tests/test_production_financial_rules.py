"""Financial rules agreed for the production recovery. No provider I/O."""
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from finance.interface import commissions, payout
from finance.models import Commission, PaymentRequest
from hub.models import Hub
from users.address import interface as addresses
from users.auth.models import User
from users.profiles import interface as profiles
from users.roles.candidate.models import Candidate
from users.roles.promoter.models import Promoter

pytestmark = pytest.mark.django_db
SP = ZoneInfo("America/Sao_Paulo")
CLOSE = datetime(2026, 10, 9, 18, tzinfo=SP)


@pytest.fixture(autouse=True)
def financial_settings(settings):
    settings.COMMISSION_DIRECT = "100"
    settings.COMMISSION_BONUS_FLAT = "500"
    settings.COMMISSION_BONUS_THRESHOLD = 5


def person(*, active=True, activated=CLOSE-timedelta(days=14)):
    user = User.objects.create_user()
    profiles.create(user=user, cpf=None, phone="5543996648750", name="Offline test")
    profiles.fill_identity(user, pix_key="offline@example.test")
    hub = Hub.objects.create(coordinator=user, address=addresses.create_empty())
    if active:
        promoter = Promoter.objects.create(user=user, hub=hub)
        fields = {"created_at": activated}
        if hasattr(promoter, "activated_at"):
            fields["activated_at"] = activated
        Promoter.objects.filter(pk=promoter.pk).update(**fields)
    else:
        Candidate.objects.create(user=user, hub=hub)
    return user


def credit(user, at, *, source=None, status=Commission.Status.PENDING):
    item = commissions.credit_manual_commission(payee=user, amount="100") if source == Commission.Source.MANUAL else commissions.credit_commission(
        payee=user, payee_role=Commission.Role.PROMOTER,
        source_type=source or Commission.Source.LEAD,
        source_external_id=uuid.uuid4(),
    )
    Commission.objects.filter(pk=item.pk).update(created_at=at, status=status)
    item.refresh_from_db()
    return item


def test_week_changes_exactly_at_friday_18():
    assert commissions.week_window(CLOSE-timedelta(seconds=1)) == (CLOSE-timedelta(days=7), CLOSE)
    assert commissions.week_window(CLOSE) == (CLOSE, CLOSE+timedelta(days=7))


def test_friday_closing_excludes_the_new_week_and_is_idempotent():
    user = person()
    before = credit(user, CLOSE-timedelta(seconds=1))
    after = credit(user, CLOSE)
    commissions.run_weekly_closing(reference_date=CLOSE)
    before.refresh_from_db()
    after.refresh_from_db()
    assert before.status == Commission.Status.PROCESSED
    assert after.status == Commission.Status.PENDING
    assert PaymentRequest.objects.get().amount == Decimal("100")
    commissions.run_weekly_closing(reference_date=CLOSE)
    assert PaymentRequest.objects.count() == 1


def test_candidate_accrues_bonus_but_does_not_get_a_payment_request():
    user = person(active=False)
    for _ in range(5):
        credit(user, CLOSE-timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE)
    assert not PaymentRequest.objects.exists()
    assert Commission.objects.filter(payee=user, source_type=Commission.Source.BONUS).get().amount == Decimal("500")
    assert Commission.objects.filter(payee=user, status=Commission.Status.PENDING).count() == 6


def test_activation_after_cutoff_waits_for_the_next_closing():
    user = person(activated=CLOSE+timedelta(seconds=1))
    credit(user, CLOSE-timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE+timedelta(minutes=5))
    assert not PaymentRequest.objects.exists()
    commissions.run_weekly_closing(reference_date=CLOSE+timedelta(days=7))
    assert PaymentRequest.objects.get().amount == Decimal("100")


def test_held_weeks_do_not_merge_toward_the_bonus():
    user = person()
    for _ in range(3):
        credit(user, CLOSE-timedelta(days=9))
        credit(user, CLOSE-timedelta(days=2))
    commissions.run_weekly_closing(reference_date=CLOSE)
    assert not Commission.objects.filter(source_type=Commission.Source.BONUS).exists()
    assert PaymentRequest.objects.get().amount == Decimal("600")


def test_two_held_qualifying_weeks_keep_two_bonuses():
    user = person()
    for _ in range(5):
        credit(user, CLOSE-timedelta(days=9))
        credit(user, CLOSE-timedelta(days=2))
    commissions.run_weekly_closing(reference_date=CLOSE)
    assert Commission.objects.filter(source_type=Commission.Source.BONUS).count() == 2
    assert PaymentRequest.objects.get().amount == Decimal("2000")


def test_ten_sales_in_one_week_get_only_one_bonus():
    user = person()
    for _ in range(10):
        credit(user, CLOSE-timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE)
    assert PaymentRequest.objects.get().amount == Decimal("1500")


def test_retry_cannot_pay_a_future_fee(monkeypatch):
    pr = PaymentRequest.objects.create(
        external_reference="future-fee", kind=PaymentRequest.Kind.FEE,
        method=PaymentRequest.Method.PIX_QRCODE, qrcode_payload="offline",
        amount=Decimal("100"), status=PaymentRequest.Status.FAILED,
        scheduled_for=timezone.now()+timedelta(days=7),
    )
    calls = []
    def forbidden(**kw):
        calls.append(kw)
        raise AssertionError("Future fee submitted before its scheduled date")
    monkeypatch.setattr(payout.asaas_qrpay, "pay_qr_code", forbidden)
    payout.retry_payment_request(str(pr.external_id))
    payout.process_payment_requests()
    assert calls == []


def test_reconciliation_never_resurrects_cancelled_commissions():
    user = person()
    item = credit(user, CLOSE-timedelta(days=1), status=Commission.Status.CANCELLED)
    pr = PaymentRequest.objects.create(external_reference="cancelled-item", amount=100, payee=user)
    item.payment_request = pr
    item.save(update_fields=["payment_request"])
    payout._cascade(pr, Commission.Status.PAID)
    item.refresh_from_db()
    assert item.status == Commission.Status.CANCELLED


def refunded_sale(user, at):
    from users.roles.lead.models import Checkout, Lead
    lead = Lead.objects.create(user=User.objects.create_user(), promoter=user, status=Lead.Status.PAID)
    checkout = Checkout.objects.create(lead=lead, provider="asaas", provider_payment_id=f"offline-{lead.external_id}", amount=999, is_paid=True)
    item = credit(user, at)
    item.source_external_id = lead.external_id
    item.save(update_fields=["source_external_id"])
    return checkout, item


def refund(checkout):
    from users.roles.lead.service import mark_refunded
    assert mark_refunded(provider="asaas", provider_payment_id=checkout.provider_payment_id)


@pytest.mark.parametrize("sales,debt", [(5, Decimal("600")), (10, Decimal("100"))])
def test_paid_refund_recovers_only_commission_and_affected_bonus(sales, debt):
    user = person()
    checkout, sale = refunded_sale(user, CLOSE-timedelta(days=1))
    for _ in range(sales-1):
        credit(user, CLOSE-timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE)
    pr = PaymentRequest.objects.get()
    pr.status = PaymentRequest.Status.PAID
    pr.save(update_fields=["status"])
    payout._cascade(pr, Commission.Status.PAID)
    refund(checkout)
    refund(checkout)
    sale.refresh_from_db()
    assert sale.status == Commission.Status.CANCELLED
    assert sum(Commission.objects.filter(source_type="reversal").values_list("amount", flat=True)) == -debt


def test_refund_reduces_an_unsent_batch_without_paying_cancelled_values():
    user = person()
    checkout, sale = refunded_sale(user, CLOSE-timedelta(days=1))
    for _ in range(4):
        credit(user, CLOSE-timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE)
    refund(checkout)
    assert PaymentRequest.objects.get().amount == Decimal("400")
    assert not Commission.objects.filter(source_type="reversal").exists()


def test_refund_inflight_creates_debt_only_when_payment_is_confirmed():
    user = person()
    checkout, sale = refunded_sale(user, CLOSE-timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE)
    pr = PaymentRequest.objects.get()
    pr.status = PaymentRequest.Status.SUBMITTED
    pr.attempts = 1
    pr.save(update_fields=["status", "attempts"])
    refund(checkout)
    assert not Commission.objects.filter(source_type="reversal", status=Commission.Status.PENDING).exists()
    payout._cascade(pr, Commission.Status.PAID)
    reversal = Commission.objects.get(source_type="reversal")
    assert reversal.status == Commission.Status.PENDING
    assert reversal.payment_request_id is None
    assert reversal.amount == Decimal("-100")
    sale.refresh_from_db()
    assert sale.status == Commission.Status.CANCELLED


def test_debt_larger_than_credit_is_carried_without_a_negative_payout():
    user = person()
    checkout, _ = refunded_sale(user, CLOSE-timedelta(days=1))
    for _ in range(4):
        credit(user, CLOSE-timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE)
    pr = PaymentRequest.objects.get()
    pr.status = PaymentRequest.Status.PAID
    pr.save(update_fields=["status"])
    payout._cascade(pr, Commission.Status.PAID)
    refund(checkout)
    for _ in range(2):
        credit(user, CLOSE+timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE+timedelta(days=7))
    assert PaymentRequest.objects.count() == 1
    assert sum(Commission.objects.filter(status=Commission.Status.PENDING).values_list("amount", flat=True)) == Decimal("-400")
    for _ in range(5):
        credit(user, CLOSE+timedelta(days=8), source=Commission.Source.MANUAL)
    commissions.run_weekly_closing(reference_date=CLOSE+timedelta(days=14))
    assert PaymentRequest.objects.latest("pk").amount == Decimal("100")


def test_candidate_cannot_receive_by_admin_advance():
    user = person(active=False)
    credit(user, CLOSE-timedelta(days=1))
    with pytest.raises(ValueError, match="payout_not_eligible"):
        commissions.advance_user_payout(user=user, immediate_submit=False)
    assert not PaymentRequest.objects.exists()


def test_existing_queue_does_not_bypass_candidate_eligibility(monkeypatch):
    user = person(active=False)
    pr = PaymentRequest.objects.create(external_reference="legacy-candidate-batch", payee=user, payee_role="promoter", amount=100, pix_key="offline@example.test")
    calls = []
    def forbidden(**kw):
        calls.append(kw)
        raise AssertionError("Candidate cannot receive a payout")
    monkeypatch.setattr(payout.asaas_payout, "create_payout", forbidden)
    payout.process_payment_requests()
    assert calls == []


def test_cancelled_unsent_batch_returns_remaining_debt_to_future_closings():
    user = person()
    checkout, _ = refunded_sale(user, CLOSE-timedelta(days=1))
    debt = Commission.objects.create(
        payee=user, payee_role=Commission.Role.PROMOTER, source_type=Commission.Source.REVERSAL,
        source_external_id=uuid.uuid4(), amount=Decimal("-50"),
    )
    Commission.objects.filter(pk=debt.pk).update(created_at=CLOSE-timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE)
    assert PaymentRequest.objects.get().amount == Decimal("50")

    refund(checkout)
    debt.refresh_from_db()
    assert PaymentRequest.objects.get().status == PaymentRequest.Status.CANCELLED
    assert debt.status == Commission.Status.PENDING
    assert debt.payment_request_id is None

    credit(user, CLOSE+timedelta(days=1), source=Commission.Source.MANUAL)
    commissions.run_weekly_closing(reference_date=CLOSE+timedelta(days=7))
    assert PaymentRequest.objects.latest("pk").amount == Decimal("50")


def test_promoter_debt_offsets_eligible_coordinator_income_even_when_promoter_inactive():
    user = person(active=False)
    debt = Commission.objects.create(
        payee=user, payee_role=Commission.Role.PROMOTER, source_type=Commission.Source.REVERSAL,
        source_external_id=uuid.uuid4(), amount=Decimal("-50"),
    )
    delivery = Commission.objects.create(
        payee=user, payee_role=Commission.Role.COORDINATOR, source_type=Commission.Source.VETERAN,
        source_external_id=uuid.uuid4(), amount=Decimal("100"),
    )
    Commission.objects.filter(pk__in=[debt.pk, delivery.pk]).update(created_at=CLOSE-timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE)
    assert PaymentRequest.objects.get().amount == Decimal("50")


def test_reconciliation_of_uncertain_transfer_continues_after_promoter_suspension(monkeypatch):
    from integrations.bank.asaas.models import Payment
    user = person()
    Promoter.objects.filter(user=user).update(status=Promoter.Status.SUSPENDED)
    pr = PaymentRequest.objects.create(
        external_reference="uncertain-existing-transfer", payee=user, amount=100,
        pix_key="offline@example.test", status=PaymentRequest.Status.QUEUED, attempts=1,
    )
    Payment.objects.create(payment_id=pr.external_reference, kind=Payment.Kind.PIXKEY, amount=100, status="SUBMITTING")
    calls = []
    def reconcile(pr, summary):
        calls.append(pr.pk)
    def forbidden(pr, summary):
        raise AssertionError("An uncertain transfer must not be submitted again")
    monkeypatch.setattr(payout, "_reconcile", reconcile)
    monkeypatch.setattr(payout, "_submit", forbidden)
    payout._process_one(pr, {"submitted": 0, "awaiting": 0})
    assert calls == [pr.pk]


def test_static_pix_refund_cancels_earned_commission():
    from integrations.bank.asaas.models import Payment
    from integrations.bank.asaas.webhooks import handle_event
    user = person()
    checkout, sale = refunded_sale(user, CLOSE-timedelta(days=1))
    payment = Payment.objects.create(payment_id=checkout.provider_payment_id, kind=Payment.Kind.STATIC_PIX_QR, asaas_id="offline-qr", amount=999, status="PAID")
    handle_event({"event": "PAYMENT_REFUNDED", "payment": {"id": "offline-bank-charge", "pixQrCodeId": payment.asaas_id}})
    sale.refresh_from_db()
    assert sale.status == Commission.Status.CANCELLED
    assert not Commission.objects.filter(source_type=Commission.Source.REVERSAL).exists()


def test_refund_callback_retries_business_effect_after_a_transient_failure(monkeypatch):
    from core import hooks
    from integrations.bank.asaas.models import Payment, WebhookEvent
    from integrations.bank.asaas.webhooks import handle_event
    user = person()
    checkout, sale = refunded_sale(user, CLOSE-timedelta(days=1))
    Payment.objects.create(payment_id=checkout.provider_payment_id, kind=Payment.Kind.CHARGE, asaas_id="offline-refund", amount=999, status="PAID")
    payload = {"event": "PAYMENT_REFUNDED", "payment": {"id": "offline-refund"}}
    dispatch = hooks.dispatch
    calls = []
    def transient(event, **kwargs):
        if event == "payment.refunded":
            calls.append(event)
            if len(calls) == 1:
                raise RuntimeError("temporary domain failure")
        return dispatch(event, **kwargs)
    monkeypatch.setattr(hooks, "dispatch", transient)
    with pytest.raises(RuntimeError, match="temporary domain failure"):
        handle_event(payload)
    assert not WebhookEvent.objects.get().forwarded_ok
    handle_event(payload)
    sale.refresh_from_db()
    assert calls == ["payment.refunded", "payment.refunded"]
    assert sale.status == Commission.Status.CANCELLED
    assert WebhookEvent.objects.latest("pk").forwarded_ok


def test_chargeback_cancels_commission_while_partner_enrollment_waits_for_admin():
    from integrations.bank.asaas.models import Payment
    from integrations.bank.asaas.webhooks import handle_event
    from users.roles.enrollment.models import Enrollment
    user = person()
    checkout, sale = refunded_sale(user, CLOSE-timedelta(days=1))
    enrollment = Enrollment.objects.create(user=checkout.lead.user, promoter=user, hub=user.promoter.hub)
    original_status = enrollment.status
    Payment.objects.create(payment_id=checkout.provider_payment_id, kind=Payment.Kind.CHARGE, asaas_id="offline-dispute", amount=999, status="PAID")
    handle_event({"event": "PAYMENT_CHARGEBACK_REQUESTED", "payment": {"id": "offline-dispute"}})
    sale.refresh_from_db()
    enrollment.refresh_from_db()
    assert sale.status == Commission.Status.CANCELLED
    assert enrollment.status == original_status


@pytest.mark.parametrize("paid", [False, True])
def test_admin_dispute_reverses_commission_value_instead_of_student_price(paid):
    from finance.interface.ledger import resolve_dispute
    from finance.models import DisputeRecord, FinancialTransaction
    user = person()
    _, sale = refunded_sale(user, CLOSE-timedelta(days=1))
    if paid:
        Commission.objects.filter(pk=sale.pk).update(status=Commission.Status.PAID)
    dispute = DisputeRecord.objects.create(external_dispute_id=f"offline-dispute-{paid}", amount=999, reason="Offline chargeback")
    kwargs = dict(actor=User.objects.create_user(is_staff=True), external_dispute_id=dispute.external_dispute_id, resolution=DisputeRecord.Resolution.DEBIT_PROMOTER, justification="Reverse only earned commission", correlated_commission_id=sale.external_id)
    resolve_dispute(**kwargs)
    resolve_dispute(**kwargs)
    tx = FinancialTransaction.objects.get(idempotency_key=f"dispute_debit_{dispute.external_dispute_id}")
    assert tx.amount == Decimal("100")
    assert sum(Commission.objects.filter(source_type=Commission.Source.REVERSAL).values_list("amount", flat=True)) == (Decimal("-100") if paid else 0)


def test_refund_during_submission_keeps_sent_amount_and_waits_for_confirmation(monkeypatch):
    from types import SimpleNamespace
    user = person()
    checkout, sale = refunded_sale(user, CLOSE-timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE)
    pr = PaymentRequest.objects.get()
    def submit(**kwargs):
        refund(checkout)
        return SimpleNamespace(payment_id=kwargs["payment_id"], status="SUBMITTED")
    monkeypatch.setattr(payout.asaas_payout, "create_payout", submit)
    payout._process_one(pr, {"submitted": 0, "awaiting": 0, "failed": 0})
    pr.refresh_from_db()
    assert pr.amount == Decimal("100")
    reversal = Commission.objects.get(source_type=Commission.Source.REVERSAL)
    assert reversal.amount == Decimal("-100")
    assert reversal.status == Commission.Status.PROCESSED
    payout._cascade(pr, Commission.Status.PAID)
    reversal.refresh_from_db()
    assert reversal.status == Commission.Status.PENDING


def test_stale_cancelled_batch_is_never_submitted(monkeypatch):
    user = person()
    checkout, _ = refunded_sale(user, CLOSE-timedelta(days=1))
    commissions.run_weekly_closing(reference_date=CLOSE)
    stale = PaymentRequest.objects.get()
    refund(checkout)
    def forbidden(**kwargs):
        raise AssertionError("A cancelled batch must never leave the account")
    monkeypatch.setattr(payout.asaas_payout, "create_payout", forbidden)
    payout._process_one(stale, {"submitted": 0, "awaiting": 0, "skipped": 0})
    assert PaymentRequest.objects.get().status == PaymentRequest.Status.CANCELLED


@pytest.mark.parametrize("action", ["retry", "override"])
def test_admin_actions_cannot_resend_an_uncertain_transfer(action):
    from integrations.bank.asaas.models import Payment
    user = person()
    pr = PaymentRequest.objects.create(external_reference="offline-uncertain-admin", payee=user, amount=100, pix_key="offline@example.test", status=PaymentRequest.Status.SUBMITTED, attempts=1)
    Payment.objects.create(payment_id=pr.external_reference, kind=Payment.Kind.PIXKEY, amount=100, status="SUBMITTING")
    with pytest.raises(ValueError, match="requires_reconciliation"):
        if action == "retry":
            payout.retry_payment_request(str(pr.external_id))
        else:
            payout.override_payment_request_pix(str(pr.external_id), "other@example.test")
    pr.refresh_from_db()
    assert pr.status == PaymentRequest.Status.SUBMITTED


def test_retry_of_confirmed_failed_bank_intent_keeps_old_attempt_and_uses_new_reference():
    from integrations.bank.asaas.models import Payment
    user = person()
    pr = PaymentRequest.objects.create(external_reference="offline-failed-bank", payee=user, amount=100, pix_key="offline@example.test", status=PaymentRequest.Status.FAILED, attempts=1)
    previous = Payment.objects.create(payment_id=pr.external_reference, kind=Payment.Kind.PIXKEY, asaas_id="failed-transfer", amount=100, status="FAILED")
    retry = payout.retry_payment_request(str(pr.external_id))
    assert retry.external_reference != previous.payment_id
    previous.refresh_from_db()
    assert previous.status == "FAILED"
    assert retry.status == PaymentRequest.Status.QUEUED


def test_admin_advance_does_not_release_activation_after_the_cutoff(monkeypatch):
    user = person(activated=CLOSE+timedelta(seconds=1))
    credit(user, CLOSE-timedelta(days=1))
    monkeypatch.setattr(timezone, "now", lambda: CLOSE+timedelta(days=1))
    with pytest.raises(ValueError, match="payout_not_eligible"):
        commissions.advance_user_payout(user=user, immediate_submit=False)
    assert not PaymentRequest.objects.exists()


def test_advancing_one_recipient_cannot_process_unrelated_bank_requests(monkeypatch):
    from types import SimpleNamespace
    user = person()
    credit(user, CLOSE-timedelta(days=1), source=Commission.Source.MANUAL)
    unrelated = PaymentRequest.objects.create(external_reference="offline-unrelated-fee", kind=PaymentRequest.Kind.FEE, amount=500, method=PaymentRequest.Method.PIX_QRCODE, qrcode_payload="offline")
    calls = []
    def submit(**kwargs):
        calls.append(kwargs["payment_id"])
        return SimpleNamespace(payment_id=kwargs["payment_id"], status="SUBMITTED")
    def forbidden(**kwargs):
        raise AssertionError("A recipient action cannot process unrelated fees")
    monkeypatch.setattr(payout.asaas_payout, "create_payout", submit)
    monkeypatch.setattr(payout.asaas_qrpay, "pay_qr_code", forbidden)
    result = commissions.advance_user_payout(user=user)
    unrelated.refresh_from_db()
    assert calls == [result["external_reference"]]
    assert unrelated.status == PaymentRequest.Status.QUEUED
