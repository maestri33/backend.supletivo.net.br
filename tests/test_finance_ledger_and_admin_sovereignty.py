"""Testes do Motor de Ledger Contábil, Soberania do Admin e Previsibilidade Financeira."""

from decimal import Decimal
import uuid
import pytest

from django.test import Client
from finance import interface as finance_iface
from finance.interface import ledger as finance_ledger
from finance.models import (
    Commission,
    DisputeRecord,
    FinancialAccount,
    FinancialAuditLog,
    FinancialTransaction,
    LedgerEntry,
    PaymentRequest,
    UnexpectedExpense,
)
from users.auth.models import User
from users.profiles import interface as profiles

pytestmark = pytest.mark.django_db


def test_ensure_default_accounts_and_double_entry_balance():
    """Garante a criação do plano de contas e a invariante de partidas dobradas."""
    accounts = finance_ledger.ensure_default_accounts()
    assert finance_ledger.ACCOUNT_ASSET_ASAAS in accounts
    assert finance_ledger.ACCOUNT_REVENUE_ENROLLMENT in accounts

    # 1. Transação balanceada (R$ 100,00)
    tx = finance_ledger.record_transaction(
        kind=FinancialTransaction.Kind.PAYMENT_RECEIVED,
        amount=Decimal("100.00"),
        source_type=FinancialTransaction.SourceType.LEAD_PAYMENT,
        idempotency_key="tx_test_balance_100",
        description="Matrícula Aluno Teste",
        entries=[
            {
                "account_code": finance_ledger.ACCOUNT_ASSET_ASAAS,
                "entry_type": LedgerEntry.EntryType.DEBIT,
                "amount": Decimal("100.00"),
            },
            {
                "account_code": finance_ledger.ACCOUNT_REVENUE_ENROLLMENT,
                "entry_type": LedgerEntry.EntryType.CREDIT,
                "amount": Decimal("100.00"),
            },
        ],
    )
    assert tx.status == FinancialTransaction.Status.COMPLETED
    assert tx.ledger_entries.count() == 2

    # 2. Transação desbalanceada (deve falhar)
    with pytest.raises(ValueError, match="unbalanced_ledger"):
        finance_ledger.record_transaction(
            kind=FinancialTransaction.Kind.PAYMENT_RECEIVED,
            amount=Decimal("100.00"),
            source_type=FinancialTransaction.SourceType.LEAD_PAYMENT,
            idempotency_key="tx_test_unbalanced",
            entries=[
                {
                    "account_code": finance_ledger.ACCOUNT_ASSET_ASAAS,
                    "entry_type": LedgerEntry.EntryType.DEBIT,
                    "amount": Decimal("100.00"),
                },
                {
                    "account_code": finance_ledger.ACCOUNT_REVENUE_ENROLLMENT,
                    "entry_type": LedgerEntry.EntryType.CREDIT,
                    "amount": Decimal("80.00"),  # Desbalanceado
                },
            ],
        )


def test_idempotency_in_financial_transactions():
    """Garante que a mesma idempotency_key não duplica lançamentos contábeis."""
    entries = [
        {
            "account_code": finance_ledger.ACCOUNT_ASSET_ASAAS,
            "entry_type": LedgerEntry.EntryType.DEBIT,
            "amount": Decimal("50.00"),
        },
        {
            "account_code": finance_ledger.ACCOUNT_REVENUE_ENROLLMENT,
            "entry_type": LedgerEntry.EntryType.CREDIT,
            "amount": Decimal("50.00"),
        },
    ]

    tx1 = finance_ledger.record_transaction(
        kind=FinancialTransaction.Kind.PAYMENT_RECEIVED,
        amount=Decimal("50.00"),
        source_type=FinancialTransaction.SourceType.LEAD_PAYMENT,
        idempotency_key="idem_key_unique_123",
        entries=entries,
    )

    tx2 = finance_ledger.record_transaction(
        kind=FinancialTransaction.Kind.PAYMENT_RECEIVED,
        amount=Decimal("50.00"),
        source_type=FinancialTransaction.SourceType.LEAD_PAYMENT,
        idempotency_key="idem_key_unique_123",
        entries=entries,
    )

    assert tx1.id == tx2.id
    assert FinancialTransaction.objects.filter(idempotency_key="idem_key_unique_123").count() == 1
    assert LedgerEntry.objects.filter(transaction=tx1).count() == 2


def test_admin_create_manual_adjustment_with_audit_log():
    """Valida o ajuste manual soberano do Admin com auditoria obrigatória."""
    admin_user = User.objects.create_user(is_staff=True, is_superuser=True)

    # 1. Sem justificativa deve falhar
    with pytest.raises(ValueError, match="justification_required"):
        finance_ledger.create_manual_adjustment(
            actor=admin_user,
            account_code=finance_ledger.ACCOUNT_ASSET_ASAAS,
            entry_type=LedgerEntry.EntryType.DEBIT,
            amount=Decimal("250.00"),
            justification="",
            idempotency_key="adj_empty_just",
        )

    # 2. Ajuste válido
    tx = finance_ledger.create_manual_adjustment(
        actor=admin_user,
        account_code=finance_ledger.ACCOUNT_ASSET_ASAAS,
        entry_type=LedgerEntry.EntryType.DEBIT,
        amount=Decimal("250.00"),
        justification="Aporte de capital extraordinário para cobrir taxas",
        idempotency_key="adj_valid_250",
    )

    assert tx.kind == FinancialTransaction.Kind.MANUAL_ADJUSTMENT
    assert tx.amount == Decimal("250.00")

    # Verifica o log de auditoria
    audit = FinancialAuditLog.objects.filter(
        action=FinancialAuditLog.Action.MANUAL_ADJUSTMENT,
        target_external_id=tx.external_id,
    ).first()
    assert audit is not None
    assert audit.actor == admin_user
    assert "Aporte de capital" in audit.justification
    assert audit.snapshot_after["amount"] == "250.00"


def test_admin_create_unexpected_expense_and_payment_request():
    """Valida o registro de custo imprevisto e emissão direta de desembolso pelo Admin."""
    admin_user = User.objects.create_user(is_staff=True, is_superuser=True)

    ue, pr = finance_ledger.create_unexpected_expense(
        actor=admin_user,
        category=UnexpectedExpense.Category.INFRASTRUCTURE,
        amount=Decimal("180.50"),
        description="Upgrade emergencial de CPU no servidor de OCR",
        justification="Pico inesperado de inscrições simultâneas",
        supplier_name="Hetzner Cloud",
        method=PaymentRequest.Method.PIX_KEY,
        pix_key="pix@hetzner.test",
        idempotency_key="unexp_infra_180",
    )

    assert ue.category == UnexpectedExpense.Category.INFRASTRUCTURE
    assert ue.amount == Decimal("180.50")
    assert ue.registered_by == admin_user

    assert pr.kind == PaymentRequest.Kind.UNEXPECTED
    assert pr.status == PaymentRequest.Status.QUEUED
    assert pr.pix_key == "pix@hetzner.test"
    assert pr.amount == Decimal("180.50")

    # Auditoria gerada
    audit = FinancialAuditLog.objects.filter(
        action=FinancialAuditLog.Action.UNEXPECTED_EXPENSE,
        target_external_id=ue.external_id,
    ).first()
    assert audit is not None
    assert audit.actor == admin_user
    assert audit.snapshot_after["supplier_name"] == "Hetzner Cloud"


def test_admin_resolve_dispute_chargeback_scenarios():
    """Valida os fluxos de resolução soberana do Admin em chargebacks/disputas."""
    admin_user = User.objects.create_user(is_staff=True, is_superuser=True)
    promoter = User.objects.create_user()

    # Cria comissão do promotor
    comm = Commission.objects.create(
        payee=promoter,
        payee_role=Commission.Role.PROMOTER,
        source_type=Commission.Source.LEAD,
        source_external_id=uuid.uuid4(),
        amount=Decimal("50.00"),
        status=Commission.Status.PENDING,
    )

    # 1. Disputa resolvida com Débito do Promotor (cancela a comissão)
    dispute1 = DisputeRecord.objects.create(
        external_dispute_id="disp_deb_001",
        amount=Decimal("97.00"),
        reason="Aluno contestou a compra alegando promessa indevida",
        status=DisputeRecord.Status.OPEN,
    )

    resolved1 = finance_ledger.resolve_dispute(
        actor=admin_user,
        external_dispute_id="disp_deb_001",
        resolution=DisputeRecord.Resolution.DEBIT_PROMOTER,
        justification="Promotor agiu contra os termos e gerou o chargeback",
        correlated_commission_id=comm.external_id,
    )

    assert resolved1.status == DisputeRecord.Status.RESOLVED_DEBITED
    comm.refresh_from_db()
    assert comm.status == Commission.Status.CANCELLED

    # 2. Disputa resolvida com Absorção de Prejuízo pela Plataforma
    dispute2 = DisputeRecord.objects.create(
        external_dispute_id="disp_abs_002",
        amount=Decimal("97.00"),
        reason="Fraude de cartão de crédito não detectada a tempo",
        status=DisputeRecord.Status.OPEN,
    )

    resolved2 = finance_ledger.resolve_dispute(
        actor=admin_user,
        external_dispute_id="disp_abs_002",
        resolution=DisputeRecord.Resolution.ABSORB_LOSS,
        justification="Promotor não teve culpa; plataforma assume como despesa operacional",
    )

    assert resolved2.status == DisputeRecord.Status.RESOLVED_ABSORBED
    assert FinancialAuditLog.objects.filter(
        action=FinancialAuditLog.Action.DISPUTE_RESOLUTION,
        target_external_id=resolved2.external_id,
    ).exists()


def test_cashflow_overview_and_projections():
    """Valida o cálculo do cockpit de previsibilidade e fluxo de caixa."""
    promoter = User.objects.create_user()

    # Adiciona comissão pendente
    Commission.objects.create(
        payee=promoter,
        payee_role=Commission.Role.PROMOTER,
        source_type=Commission.Source.LEAD,
        source_external_id=uuid.uuid4(),
        amount=Decimal("70.00"),
        status=Commission.Status.PENDING,
    )

    # Adiciona payout na fila
    PaymentRequest.objects.create(
        external_reference="payout_cf_test_1",
        amount=Decimal("120.00"),
        status=PaymentRequest.Status.QUEUED,
    )

    overview = finance_ledger.get_cashflow_overview()
    assert Decimal(overview["unclosed_commissions_liability"]) == Decimal("70.00")
    assert Decimal(overview["pending_payouts_queue"]) == Decimal("120.00")
    assert Decimal(overview["total_obligations_due"]) == Decimal("190.00")


def test_staff_api_ledger_and_adjustments_integration():
    """Testa os endpoints da API Staff/Admin para Ledger, Ajustes, Transações e Auditoria."""
    from users.auth.jwt import service as jwt_service

    admin_user = User.objects.create_user(is_staff=True, is_superuser=True)
    token = jwt_service.issue(str(admin_user.external_id), [])["access_token"]

    client = Client()
    auth_header = f"Bearer {token}"


    # 1. POST /api/v1/staff/finance/adjustments
    res_adj = client.post(
        "/api/v1/staff/finance/adjustments",
        data={
            "account_code": finance_ledger.ACCOUNT_ASSET_ASAAS,
            "entry_type": "debit",
            "amount": "300.00",
            "justification": "Aporte de liquidez emergencial",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=auth_header,
        HTTP_IDEMPOTENCY_KEY="adj_api_test_001",
    )
    assert res_adj.status_code == 201
    data_adj = res_adj.json()
    assert data_adj["kind"] == "manual_adjustment"
    assert data_adj["amount"] == "300.00"

    # 2. GET /api/v1/staff/finance/ledger
    res_ledger = client.get(
        "/api/v1/staff/finance/ledger",
        HTTP_AUTHORIZATION=auth_header,
    )
    assert res_ledger.status_code == 200
    entries = res_ledger.json()
    assert len(entries) >= 2

    # 3. GET /api/v1/staff/finance/transactions
    res_tx = client.get(
        "/api/v1/staff/finance/transactions",
        HTTP_AUTHORIZATION=auth_header,
    )
    assert res_tx.status_code == 200
    assert len(res_tx.json()) >= 1

    # 4. GET /api/v1/staff/finance/cashflow
    res_cf = client.get(
        "/api/v1/staff/finance/cashflow",
        HTTP_AUTHORIZATION=auth_header,
    )
    assert res_cf.status_code == 200
    assert "total_obligations_due" in res_cf.json()

    # 5. GET /api/v1/staff/finance/audit
    res_audit = client.get(
        "/api/v1/staff/finance/audit",
        HTTP_AUTHORIZATION=auth_header,
    )
    assert res_audit.status_code == 200
    audit_logs = res_audit.json()
    assert any(a["action"] == "manual_adjustment" for a in audit_logs)

