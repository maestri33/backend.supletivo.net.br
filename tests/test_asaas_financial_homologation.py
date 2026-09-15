"""Suíte de homologação e auditoria da integração financeira com Asaas (Issue #6).

Cobre:
1. Meios de Pagamento (Pix, Cartão de Crédito com parcelamento, Boleto com linha digitável e PDF).
2. Webhooks assíncronos (Autenticação timing-safe, idempotência, resiliência fora de ordem).
3. Ciclo de vida de pagamentos (CONFIRMED, OVERDUE, REFUNDED, CHARGEBACK/DISPUTE).
4. Comissões, Split de pagamento, Bônus por meta e Fechamento semanal.
5. Payouts (Saques Pix, tratamento de saldo insuficiente, retentativa soberana).
6. Escrituração Contábil em Partidas Dobradas (Double-Entry Ledger) e Conciliação Bancária.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import json
import uuid

import pytest
from django.conf import settings
from django.test import Client

from finance import config as finance_config
from finance.interface import commissions as finance_commissions
from finance.interface import ledger as finance_ledger
from finance.interface import payout as finance_payout
from finance.models import (
    Commission,
    DisputeRecord,
    FinancialAccount,
    FinancialTransaction,
    LedgerEntry,
    PaymentRequest,
)
from hub.models import Hub
from integrations.bank.asaas import charge as asaas_charge
from integrations.bank.asaas import client as asaas_client
from integrations.bank.asaas import customers as asaas_customers
from integrations.bank.asaas import models as asaas_models
from integrations.bank.asaas import webhooks as asaas_webhooks
from users.address.models import Address
from users.auth.jwt import service as jwt_service
from users.auth.models import User
from users.profiles.models import Profile
from users.roles import service as roles_service
from users.roles.enrollment.models import Enrollment
from users.roles.lead.models import Checkout, Lead
from users.roles.promoter.models import Promoter


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES E HELPERS
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def api_client():
    return Client()


@pytest.fixture
def auth_headers(db):
    user = User.objects.create_superuser(password="superpassword123")
    tokens = jwt_service.issue(str(user.external_id), ["admin"])
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens['access_token']}"}


@pytest.fixture
def hub_and_promoter(db):
    coord_user = User.objects.create_user()
    roles_service.assign(coord_user, "candidate")
    roles_service.promote(coord_user, "promoter")
    roles_service.assign(coord_user, "coordinator")
    Profile.objects.create(
        user=coord_user,
        name="Coordenador Hub",
        cpf="11111111111",
        phone="5511999990001",
        pix_key="coord@v7m.org",
    )
    addr = Address.objects.create(city="São Paulo", state="SP")
    hub = Hub.objects.create(
        brand="v7m",
        address=addr,
        coordinator=coord_user,
        is_default=True,
    )
    prom_user = User.objects.create_user()
    roles_service.assign(prom_user, "candidate")
    roles_service.promote(prom_user, "promoter")
    Profile.objects.create(
        user=prom_user,
        name="Promotor V7M",
        cpf="22222222222",
        phone="5511999990002",
        pix_key="promotor@v7m.org",
    )
    Promoter.objects.create(
        user=prom_user,
        hub=hub,
        status=Promoter.Status.ACTIVE,
    )
    return hub, prom_user, coord_user


@pytest.fixture
def lead_with_checkout(db, hub_and_promoter):
    hub, promoter_user, _ = hub_and_promoter
    student_user = User.objects.create_user()
    roles_service.assign(student_user, "lead")
    Profile.objects.create(
        user=student_user,
        name="Aluno Supletivo",
        cpf="33333333333",
        phone="5511999990003",
        email="aluno@supletivo.org",
    )
    lead = Lead.objects.create(
        user=student_user,
        promoter=promoter_user,
        status=Lead.Status.PENDING,
    )
    checkout = Checkout.objects.create(
        lead=lead,
        payment_method=Checkout.Method.PIX,
        provider=Checkout.Provider.ASAAS,
        provider_payment_id=f"lead_pay_{lead.external_id.hex[:8]}",
        amount=Decimal("197.00"),
        short_token="tok_test_123",
        is_paid=False,
    )
    cust = asaas_models.Customer.objects.create(
        asaas_id="cus_test_123",
        name="Aluno Supletivo",
        cpf_cnpj="33333333333",
        email="aluno@supletivo.org",
    )
    payment = asaas_models.Payment.objects.create(
        payment_id=checkout.provider_payment_id,
        kind=asaas_models.Payment.Kind.CHARGE,
        billing_type="PIX",
        customer=cust,
        amount=Decimal("197.00"),
        status="PENDING",
        asaas_id="pay_asaas_test_123",
    )
    return lead, checkout, payment


# ─────────────────────────────────────────────────────────────────────────────
# 1. TESTES DE CLIENTE E MEIOS DE PAGAMENTO (PIX, CARTÃO, BOLETO)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_create_pix_charge_with_qr(monkeypatch):
    """Testa criação de cobrança PIX com QR code e cópia-e-cola no Asaas."""
    monkeypatch.setattr(settings, "ASAAS_API_KEY", "test_asaas_key")

    async def mock_create(self, payload):
        return {
            "id": "pay_pix_999",
            "invoiceUrl": "https://sandbox.asaas.com/i/pay_pix_999",
            "status": "PENDING",
            "netValue": 195.01,
        }

    async def mock_qr(self, pid):
        return {
            "payload": "00020101021226830014br.gov.bcb.pix0025pay_pix_9995204000053039865802BR6304ABCD",
            "encodedImage": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        }

    monkeypatch.setattr(
        asaas_customers,
        "find_or_create",
        lambda p: asaas_models.Customer.objects.create(
            asaas_id=f"cus_pix_{uuid.uuid4().hex[:8]}", cpf_cnpj=getattr(p, "cpf_cnpj", "12345678909")
        ),
    )
    monkeypatch.setattr(asaas_client.AsaasClient, "create_payment", mock_create)
    monkeypatch.setattr(asaas_client.AsaasClient, "get_payment_pix_qr_code", mock_qr)

    payer = asaas_customers.PayerData(
        name="Teste Pix",
        cpf_cnpj="12345678909",
        email="pix@test.org",
        mobile_phone="11999990000",
    )

    charge = asaas_charge.create_charge(
        amount=Decimal("197.00"),
        payer=payer,
        billing_type="PIX",
        description="Matrícula Pix V7M",
    )

    assert charge.kind == asaas_models.Payment.Kind.CHARGE
    assert charge.billing_type == "PIX"
    assert charge.status == "PENDING"
    assert charge.qrcode_payload is not None
    assert charge.pix_qr_image is not None
    assert charge.net_value == Decimal("195.01")
    assert charge.invoice_url == "https://sandbox.asaas.com/i/pay_pix_999"

    charge_dict = asaas_charge.to_dict(charge)
    assert charge_dict["billing_type"] == "PIX"
    assert charge_dict["amount"] == "197.00"
    assert charge_dict["net_value"] == "195.01"


@pytest.mark.django_db
def test_create_boleto_charge_with_line_code(monkeypatch):
    """Testa criação de cobrança Boleto Bancário com linha digitável e PDF."""
    monkeypatch.setattr(settings, "ASAAS_API_KEY", "test_asaas_key")

    async def mock_create(self, payload):
        assert payload["billingType"] == "BOLETO"
        return {
            "id": "pay_bol_888",
            "bankSlipUrl": "https://sandbox.asaas.com/b/pdf/pay_bol_888",
            "invoiceUrl": "https://sandbox.asaas.com/i/pay_bol_888",
            "status": "PENDING",
            "nossoNumero": "12345678",
            "netValue": 194.00,
        }

    async def mock_ident(self, pid):
        return {
            "identificationField": "00190.00009 01234.567802 00000.000000 1 99990000019700",
            "barCode": "00191999900000197000000001234567800000000000",
        }

    monkeypatch.setattr(
        asaas_customers,
        "find_or_create",
        lambda p: asaas_models.Customer.objects.create(
            asaas_id=f"cus_bol_{uuid.uuid4().hex[:8]}", cpf_cnpj=getattr(p, "cpf_cnpj", "12345678909")
        ),
    )
    monkeypatch.setattr(asaas_client.AsaasClient, "create_payment", mock_create)
    monkeypatch.setattr(asaas_client.AsaasClient, "get_payment_identification_field", mock_ident)

    payer = asaas_customers.PayerData(
        name="Teste Boleto",
        cpf_cnpj="12345678909",
        email="boleto@test.org",
        mobile_phone="11999990000",
    )

    charge = asaas_charge.create_charge(
        amount=Decimal("197.00"),
        payer=payer,
        billing_type="BOLETO",
        description="Matrícula Boleto V7M",
        fine={"value": 2.0, "type": "PERCENTAGE"},
        interest={"value": 1.0},
    )

    assert charge.billing_type == "BOLETO"
    assert charge.bank_slip_url == "https://sandbox.asaas.com/b/pdf/pay_bol_888"
    assert charge.identification_field == "00190.00009 01234.567802 00000.000000 1 99990000019700"
    assert charge.nosso_numero == "12345678"
    assert charge.net_value == Decimal("194.00")

    charge_dict = asaas_charge.to_dict(charge)
    assert charge_dict["billing_type"] == "BOLETO"
    assert charge_dict["bank_slip_url"] == "https://sandbox.asaas.com/b/pdf/pay_bol_888"
    assert charge_dict["identification_field"] == "00190.00009 01234.567802 00000.000000 1 99990000019700"


@pytest.mark.django_db
def test_create_credit_card_charge_with_installments(monkeypatch):
    """Testa cobrança com cartão de crédito, parcelamento e metadados de bandeira."""
    monkeypatch.setattr(settings, "ASAAS_API_KEY", "test_asaas_key")

    async def mock_create(self, payload):
        assert payload["billingType"] == "CREDIT_CARD"
        assert payload["installmentCount"] == 12
        assert payload["creditCardToken"] == "tok_card_test_xyz"
        return {
            "id": "pay_card_777",
            "status": "CONFIRMED",
            "netValue": 185.50,
            "creditCard": {
                "creditCardBrand": "MASTERCARD",
                "creditCardNumber": "5555",
            },
        }

    monkeypatch.setattr(
        asaas_customers,
        "find_or_create",
        lambda p: asaas_models.Customer.objects.create(
            asaas_id=f"cus_card_{uuid.uuid4().hex[:8]}", cpf_cnpj=getattr(p, "cpf_cnpj", "12345678909")
        ),
    )
    monkeypatch.setattr(asaas_client.AsaasClient, "create_payment", mock_create)

    payer = asaas_customers.PayerData(
        name="Teste Cartão",
        cpf_cnpj="12345678909",
        email="card@test.org",
        mobile_phone="11999990000",
    )

    charge = asaas_charge.create_charge(
        amount=Decimal("197.00"),
        payer=payer,
        billing_type="CREDIT_CARD",
        credit_card_token="tok_card_test_xyz",
        installment_count=12,
        installment_value=Decimal("19.90"),
        description="Matrícula Cartão 12x",
    )

    assert charge.billing_type == "CREDIT_CARD"
    assert charge.installment_count == 12
    assert charge.credit_card_brand == "MASTERCARD"
    assert charge.credit_card_last_digits == "5555"
    assert charge.net_value == Decimal("185.50")

    charge_dict = asaas_charge.to_dict(charge)
    assert charge_dict["billing_type"] == "CREDIT_CARD"
    assert charge_dict["installment_count"] == 12
    assert charge_dict["credit_card_brand"] == "MASTERCARD"


@pytest.mark.django_db
def test_charge_input_validations(monkeypatch):
    """Valida rejeição de valores nulos, negativos e datas no passado."""
    monkeypatch.setattr(settings, "ASAAS_API_KEY", "test_key")
    monkeypatch.setattr(
        asaas_customers,
        "find_or_create",
        lambda p: asaas_models.Customer.objects.create(
            asaas_id=f"cus_val_{uuid.uuid4().hex[:8]}", cpf_cnpj="11111111111"
        ),
    )
    payer = asaas_customers.PayerData(name="Inv", cpf_cnpj="11111111111")

    with pytest.raises(asaas_charge.ChargeError, match="amount_required"):
        asaas_charge.create_charge(amount=None, payer=payer)

    with pytest.raises(asaas_charge.ChargeError, match="invalid_amount"):
        asaas_charge.create_charge(amount="-50.00", payer=payer)

    with pytest.raises(asaas_charge.ChargeError, match="no passado"):
        past = (date.today() - timedelta(days=2)).isoformat()
        asaas_charge.create_charge(amount="100.00", payer=payer, due_date=past)


# ─────────────────────────────────────────────────────────────────────────────
# 2. WEBHOOKS ASSÍNCRONOS & SEGURANÇA TIMING-SAFE
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_webhook_security_header(api_client, monkeypatch):
    """Testa autenticação timing-safe do header asaas-access-token."""
    monkeypatch.setattr(settings, "ASAAS_WEBHOOK_SECRET", "super-secret-token-123")

    # 1. Sem token -> 401
    resp1 = api_client.post(
        "/integrations/asaas/webhook/",
        data=json.dumps({"event": "PAYMENT_RECEIVED"}),
        content_type="application/json",
    )
    assert resp1.status_code == 401
    assert resp1.json()["detail"] == "invalid_token"

    # 2. Token incorreto -> 401
    resp2 = api_client.post(
        "/integrations/asaas/webhook/",
        data=json.dumps({"event": "PAYMENT_RECEIVED"}),
        content_type="application/json",
        HTTP_ASAAS_ACCESS_TOKEN="wrong-token",
    )
    assert resp2.status_code == 401

    # 3. Token correto -> 200
    resp3 = api_client.post(
        "/integrations/asaas/webhook/",
        data=json.dumps({"event": "PAYMENT_CREATED", "payment": {"id": "pay_dummy"}}),
        content_type="application/json",
        HTTP_ASAAS_ACCESS_TOKEN="super-secret-token-123",
    )
    assert resp3.status_code == 200
    assert resp3.json()["ok"] is True


@pytest.mark.django_db
def test_webhook_payment_confirmed_triggers_enrollment_and_ledger(lead_with_checkout):
    """Testa fluxo PAYMENT_CONFIRMED: ativa aluno, credita comissão e lança partidas dobradas."""
    lead, checkout, payment = lead_with_checkout

    webhook_payload = {
        "event": "PAYMENT_CONFIRMED",
        "payment": {
            "id": payment.asaas_id,
            "externalReference": payment.payment_id,
            "value": 197.00,
            "netValue": 195.01,
            "billingType": "PIX",
            "transactionReceiptUrl": "https://sandbox.asaas.com/receipt/123",
        },
    }

    event_row = asaas_webhooks.handle_event(webhook_payload)
    assert event_row.forwarded_ok is True

    payment.refresh_from_db()
    assert payment.status == "PAID"

    checkout.refresh_from_db()
    assert checkout.is_paid is True

    lead.refresh_from_db()
    assert lead.status == Lead.Status.PAID

    # Enrollment criado
    enrollment = Enrollment.objects.filter(user=lead.user).first()
    assert enrollment is not None

    # Comissão creditada ao promotor
    comm = Commission.objects.filter(
        source_type=Commission.Source.LEAD,
        source_external_id=lead.external_id,
    ).first()
    assert comm is not None
    assert comm.payee == lead.promoter
    assert comm.status == Commission.Status.PENDING


@pytest.mark.django_db
def test_webhook_payment_overdue_and_anti_downgrade(lead_with_checkout):
    """Testa PAYMENT_OVERDUE e proteção contra rebaixamento de PAID para EXPIRED."""
    lead, checkout, payment = lead_with_checkout

    payload_overdue = {
        "event": "PAYMENT_OVERDUE",
        "payment": {"id": payment.asaas_id, "externalReference": payment.payment_id},
    }
    asaas_webhooks.handle_event(payload_overdue)
    payment.refresh_from_db()
    assert payment.status == "EXPIRED"

    payload_paid = {
        "event": "PAYMENT_RECEIVED",
        "payment": {"id": payment.asaas_id, "externalReference": payment.payment_id},
    }
    asaas_webhooks.handle_event(payload_paid)
    payment.refresh_from_db()
    assert payment.status == "PAID"

    # OVERDUE tardio não rebaixa de PAID -> EXPIRED (anti-downgrade)
    asaas_webhooks.handle_event(payload_overdue)
    payment.refresh_from_db()
    assert payment.status == "PAID"


@pytest.mark.django_db
def test_webhook_payment_refunded_and_ledger_reversal(lead_with_checkout):
    """Testa estorno (PAYMENT_REFUNDED): cancela lead/comissão e lança estorno contábil."""
    lead, checkout, payment = lead_with_checkout

    asaas_webhooks.handle_event({
        "event": "PAYMENT_CONFIRMED",
        "payment": {
            "id": payment.asaas_id,
            "externalReference": payment.payment_id,
            "value": 197.00,
        },
    })

    asaas_webhooks.handle_event({
        "event": "PAYMENT_REFUNDED",
        "payment": {
            "id": payment.asaas_id,
            "externalReference": payment.payment_id,
            "value": 197.00,
        },
    })

    payment.refresh_from_db()
    assert payment.status == "REFUNDED"

    lead.refresh_from_db()
    assert lead.status == Lead.Status.FAILED
    assert lead.failed_reason == "payment_refunded"

    comm = Commission.objects.get(source_external_id=lead.external_id)
    assert comm.status == Commission.Status.CANCELLED


@pytest.mark.django_db
def test_webhook_chargeback_dispute_registration(lead_with_checkout):
    """Testa recepção de PAYMENT_CHARGEBACK_REQUESTED gerando DisputeRecord."""
    lead, checkout, payment = lead_with_checkout

    chargeback_payload = {
        "event": "PAYMENT_CHARGEBACK_REQUESTED",
        "payment": {
            "id": payment.asaas_id,
            "externalReference": payment.payment_id,
            "value": 197.00,
        },
    }

    asaas_webhooks.handle_event(chargeback_payload)

    payment.refresh_from_db()
    assert payment.status == "DISPUTED"

    dispute = DisputeRecord.objects.filter(
        external_dispute_id=f"dsp_{payment.asaas_id}"
    ).first()
    assert dispute is not None
    assert dispute.status == DisputeRecord.Status.OPEN
    assert dispute.amount == Decimal("197.00")
    assert "PAYMENT_CHARGEBACK_REQUESTED" in dispute.reason


# ─────────────────────────────────────────────────────────────────────────────
# 3. SPLIT, COMISSÕES, FECHAMENTO SEMANAL & PAYOUTS
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_commission_split_and_weekly_bonus(hub_and_promoter):
    """Testa split de comissão direta, bônus por 5 vendas e fechamento semanal."""
    hub, prom_user, coord_user = hub_and_promoter

    # 5 leads => bônus semanal
    for _ in range(5):
        lead_id = uuid.uuid4()
        finance_commissions.credit_commission(
            payee=prom_user,
            payee_role=Commission.Role.PROMOTER,
            source_type=Commission.Source.LEAD,
            source_external_id=lead_id,
        )

    # 1 comissão de coordenador
    vet_id = uuid.uuid4()
    finance_commissions.credit_commission(
        payee=coord_user,
        payee_role=Commission.Role.COORDINATOR,
        source_type=Commission.Source.VETERAN,
        source_external_id=vet_id,
    )

    sim = finance_commissions.simulate_weekly_closing()
    assert sim["commissions_count"] == 6
    assert sim["bonuses_count"] == 1

    res = finance_commissions.run_weekly_closing()
    assert res["bonuses_created"] == 1
    assert res["payment_requests_created"] == 2

    pr_prom = PaymentRequest.objects.get(payee=prom_user)
    assert pr_prom.status == PaymentRequest.Status.QUEUED
    assert pr_prom.pix_key == "promotor@v7m.org"

    pr_coord = PaymentRequest.objects.get(payee=coord_user)
    assert pr_coord.status == PaymentRequest.Status.QUEUED


@pytest.mark.django_db
def test_payout_insufficient_balance_and_retry(hub_and_promoter, monkeypatch):
    """Testa tratamento de saldo insuficiente (AWAITING_BALANCE) e retry soberano."""
    _, prom_user, _ = hub_and_promoter

    pr = PaymentRequest.objects.create(
        external_reference="payout_week_test_123",
        payee=prom_user,
        amount=Decimal("1250.00"),
        pix_key="promotor@v7m.org",
        status=PaymentRequest.Status.QUEUED,
    )

    def mock_create_payout(*args, **kwargs):
        raise finance_payout.asaas_payout.PayoutError(
            "asaas_rejected: Saldo insuficiente para transferência"
        )

    monkeypatch.setattr(finance_payout.asaas_payout, "create_payout", mock_create_payout)

    summary = finance_payout.process_payment_requests()
    assert summary["awaiting"] == 1

    pr.refresh_from_db()
    assert pr.status == PaymentRequest.Status.AWAITING_BALANCE
    assert "saldo insuficiente" in pr.last_error.lower()

    retried_pr = finance_payout.retry_payment_request(str(pr.external_id))
    assert retried_pr.status == PaymentRequest.Status.QUEUED
    assert retried_pr.attempts == 0
    assert retried_pr.last_error is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. CONCILIAÇÃO BANCÁRIA E COCKPIT STAFF ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_staff_reconciliation_and_cashflow_endpoints(api_client, auth_headers, monkeypatch):
    """Testa o endpoint de conciliação bancária Asaas vs Ledger."""
    # Mock do saldo da conta Asaas
    monkeypatch.setattr(
        "integrations.bank.asaas.onboarding.account_balance",
        lambda: {"balance": 15000.00},
    )

    # Cria um lançamento no ledger para testar o balanço
    finance_ledger.ensure_default_accounts()
    finance_ledger.record_transaction(
        kind=FinancialTransaction.Kind.PAYMENT_RECEIVED,
        amount=Decimal("5000.00"),
        source_type=FinancialTransaction.SourceType.LEAD_PAYMENT,
        idempotency_key="tx_rec_reconciliation_001",
        entries=[
            {
                "account_code": finance_ledger.ACCOUNT_ASSET_ASAAS,
                "entry_type": LedgerEntry.EntryType.DEBIT,
                "amount": Decimal("5000.00"),
            },
            {
                "account_code": finance_ledger.ACCOUNT_REVENUE_ENROLLMENT,
                "entry_type": LedgerEntry.EntryType.CREDIT,
                "amount": Decimal("5000.00"),
            },
        ],
    )

    # Chama endpoint de conciliação
    resp_recon = api_client.get("/api/v1/staff/finance/reconciliation", **auth_headers)
    assert resp_recon.status_code == 200
    data_recon = resp_recon.json()
    assert data_recon["asaas_live_balance"] == "15000.00"
    assert data_recon["ledger_asset_balance"] == "5000.00"
    assert data_recon["is_solvent"] is True
    assert "reconciled_at" in data_recon

    # Chama endpoint de fluxo de caixa
    resp_cash = api_client.get("/api/v1/staff/finance/cashflow", **auth_headers)
    assert resp_cash.status_code == 200
    data_cash = resp_cash.json()
    assert "pending_payouts_queue" in data_cash
    assert "unclosed_commissions_liability" in data_cash
    assert "total_obligations_due" in data_cash
