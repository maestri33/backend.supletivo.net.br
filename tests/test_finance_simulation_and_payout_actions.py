import uuid
import pytest
from decimal import Decimal

from finance import interface as finance_iface
from finance.interface import commissions as finance_closing
from finance.interface import payout as finance_payout
from finance.models import Commission, PaymentRequest
from users.auth.models import User
from users.profiles import interface as profiles
from users.roles.lead.models import Checkout, Lead
from users.roles.lead import service as lead_service

pytestmark = pytest.mark.django_db


def test_simulation_weekly_closing_without_persisting():
    promoter = User.objects.create_user()
    profiles.create(user=promoter, cpf=None, phone="5511988887777", name="Promotor Milionario")
    profiles.fill_identity(promoter, pix_key="pix@promoter.test")

    # Credita 6 comissões de lead
    for i in range(6):
        finance_closing.credit_commission(
            payee=promoter,
            payee_role=Commission.Role.PROMOTER,
            source_type=Commission.Source.LEAD,
            source_external_id=uuid.uuid4(),
        )

    sim = finance_closing.simulate_weekly_closing()
    assert sim["commissions_count"] == 6
    assert sim["bonuses_count"] == 1  # 6 >= 5 threshold
    assert sim["beneficiaries_count"] == 1
    assert sim["awaiting_pix_count"] == 0
    assert sim["beneficiaries"][0]["bonus_earned"] is True

    # Confirma que nada virou PROCESSED no banco (simulação pura)
    assert Commission.objects.filter(status=Commission.Status.PENDING).count() == 6
    assert PaymentRequest.objects.count() == 0


def test_payout_retry_and_pix_override():
    promoter = User.objects.create_user()
    profiles.create(user=promoter, cpf=None, phone="5511977776666", name="Promotor Sem PIX")

    pr = PaymentRequest.objects.create(
        external_reference="test_ref_123",
        payee=promoter,
        payee_role="promoter",
        amount=Decimal("150.00"),
        status=PaymentRequest.Status.AWAITING_PIX,
        attempts=3,
        last_error="asaas_rejected_no_pix",
    )

    # 1. Override PIX
    updated_pr = finance_payout.override_payment_request_pix(
        external_id=str(pr.external_id),
        new_pix_key="11988887777",
        update_profile=True,
    )
    assert updated_pr.status == PaymentRequest.Status.QUEUED
    assert updated_pr.pix_key == "11988887777"
    assert updated_pr.attempts == 0
    assert updated_pr.last_error is None

    # Confirma que o profile foi atualizado
    p = profiles.get(promoter)
    assert p.pix_key == "11988887777"

    # 2. Retry Payout
    updated_pr.status = PaymentRequest.Status.FAILED
    updated_pr.attempts = 5
    updated_pr.save()

    retried_pr = finance_payout.retry_payment_request(str(pr.external_id))
    assert retried_pr.status == PaymentRequest.Status.QUEUED
    assert retried_pr.attempts == 0


def test_mark_refunded_cancels_pending_commission():
    promoter = User.objects.create_user()
    profiles.create(user=promoter, cpf=None, phone="5511966665555", name="Promotor Vendedor")

    lead_user = User.objects.create_user()
    profiles.create(user=lead_user, cpf=None, phone="5511944443333", name="Lead Comprador")

    lead = Lead.objects.create(user=lead_user, promoter=promoter, status=Lead.Status.PAID)
    checkout = Checkout.objects.create(
        lead=lead,
        provider=Checkout.Provider.ASAAS,
        provider_payment_id="pay_test_refund_999",
        amount=Decimal("97.00"),
        is_paid=True,
    )

    comm = finance_closing.credit_commission(
        payee=promoter,
        payee_role=Commission.Role.PROMOTER,
        source_type=Commission.Source.LEAD,
        source_external_id=lead.external_id,
    )
    assert comm.status == Commission.Status.PENDING

    # Executa estorno
    consumed = lead_service.mark_refunded(
        provider="asaas",
        provider_payment_id="pay_test_refund_999",
    )
    assert consumed is True

    lead.refresh_from_db()
    checkout.refresh_from_db()
    comm.refresh_from_db()

    assert lead.status == Lead.Status.FAILED
    assert lead.failed_reason == "payment_refunded"
    assert checkout.is_paid is False
    assert comm.status == Commission.Status.CANCELLED

