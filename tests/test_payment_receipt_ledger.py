"""Receipt accounting against controlled provider evidence, never production proof."""
import json
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from finance.interface import ledger
from finance.models import FinancialTransaction, LedgerEntry
from integrations.bank.asaas.models import Payment

pytestmark = pytest.mark.django_db


def attempt(provider="asaas", **changes):
    fields = dict(external_id=uuid4(), provider=provider, provider_payment_id=str(uuid4()),
        provider_confirmed=True, amount=Decimal("100.00"), paid_amount=Decimal("100.00"), last_error="")
    fields.update(changes)
    return SimpleNamespace(**fields)


def balances(tx):
    return {(e.account.code, e.entry_type): e.amount for e in LedgerEntry.objects.filter(transaction=tx).select_related("account")}


def provider_row(item, net, proof_net):
    return Payment.objects.create(payment_id=item.provider_payment_id, kind="static_pix_qr",
        status="PAID", amount=item.amount, net_value=net,
        confirmation_payload={"value": "100.00", "netValue": proof_net})


def test_asaas_verified_net_books_fee_and_receipt_once():
    item = attempt()
    provider_row(item, Decimal("98.01"), "98.01")
    tx = ledger.record_lead_receipt(attempt=item)
    assert ledger.record_lead_receipt(attempt=item).pk == tx.pk
    assert FinancialTransaction.objects.count() == 1
    assert tx.source_external_id == item.external_id
    assert tx.status == "completed"
    assert balances(tx) == {
        (ledger.ACCOUNT_REVENUE_ENROLLMENT, "credit"): Decimal("100.00"),
        (ledger.ACCOUNT_ASSET_ASAAS, "debit"): Decimal("98.01"),
        (ledger.ACCOUNT_EXPENSE_GATEWAY, "debit"): Decimal("1.99"),
    }


@pytest.mark.parametrize("net,proof_net", [(None, None), (Decimal("99.00"), "98.01"),
    (Decimal("101.00"), "101.00"), (Decimal("98.01"), True)])
def test_asaas_unproven_net_stays_pending_receivable(net, proof_net):
    item = attempt()
    provider_row(item, net, proof_net)
    tx = ledger.record_lead_receipt(attempt=item)
    assert tx.status == "pending"
    assert (ledger.ACCOUNT_ASSET_ASAAS, "debit") not in balances(tx)
    assert balances(tx)[(ledger.ACCOUNT_ASSET_ASAAS_RECEIVABLE, "debit")] == item.amount
    assert json.loads(tx.description)["gateway_fee"] is None


def test_infinitepay_buyer_financing_is_not_assumed_merchant_cash():
    tx = ledger.record_lead_receipt(attempt=attempt("infinitepay", paid_amount=Decimal("107.00")))
    assert tx.amount == Decimal("100.00") and tx.status == "pending"
    assert balances(tx) == {
        (ledger.ACCOUNT_REVENUE_ENROLLMENT, "credit"): Decimal("100.00"),
        (ledger.ACCOUNT_ASSET_INFINITEPAY, "debit"): Decimal("100.00"),
    }
    evidence = json.loads(tx.description)
    assert evidence["buyer_additional_amount"] == "7.00"
    assert evidence["net_amount"] is None and evidence["gateway_fee"] is None


def test_second_charge_is_liability_not_second_sale():
    tx = ledger.record_lead_receipt(attempt=attempt("infinitepay", last_error="additional_payment_review"))
    assert (ledger.ACCOUNT_REVENUE_ENROLLMENT, "credit") not in balances(tx)
    assert balances(tx)[(ledger.ACCOUNT_LIABILITY_ADDITIONAL_PAYMENT, "credit")] == tx.amount


def test_zero_net_is_full_proven_gateway_expense():
    item = attempt()
    provider_row(item, Decimal("0.00"), "0.00")
    tx = ledger.record_lead_receipt(attempt=item)
    assert balances(tx)[(ledger.ACCOUNT_EXPENSE_GATEWAY, "debit")] == tx.amount
    assert len(balances(tx)) == 2


@pytest.mark.parametrize("changes", [{"provider_confirmed": False}, {"paid_amount": None},
    {"paid_amount": Decimal("99.00")}, {"amount": Decimal("NaN")},
    {"paid_amount": Decimal("100.001")}, {"provider": "unknown"}])
def test_invalid_evidence_creates_no_entries(changes):
    with pytest.raises(ValueError):
        ledger.record_lead_receipt(attempt=attempt(**changes))
    assert not FinancialTransaction.objects.exists()


def test_failure_rolls_back_receipt_with_business_transaction():
    from django.db import transaction
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            ledger.record_lead_receipt(attempt=attempt("infinitepay"))
            raise RuntimeError("enrollment failed")
    assert not FinancialTransaction.objects.exists()


def test_unique_race_leaves_outer_business_transaction_usable(monkeypatch):
    from django.db import transaction

    item = attempt("infinitepay")
    original = ledger.record_lead_receipt(attempt=item)
    real_filter = FinancialTransaction.objects.filter
    missed = False

    def filter_once(**kwargs):
        nonlocal missed
        if not missed and kwargs == {"idempotency_key": original.idempotency_key}:
            missed = True
            return SimpleNamespace(first=lambda: None)
        return real_filter(**kwargs)

    monkeypatch.setattr(FinancialTransaction.objects, "filter", filter_once)
    with transaction.atomic():
        result = ledger.record_transaction(kind=original.kind, amount=original.amount,
            source_type=original.source_type, idempotency_key=original.idempotency_key,
            entries=[{"account_code": ledger.ACCOUNT_ASSET_INFINITEPAY, "entry_type": "debit", "amount": item.amount},
                     {"account_code": ledger.ACCOUNT_REVENUE_ENROLLMENT, "entry_type": "credit", "amount": item.amount}])
        assert result.pk == original.pk
        assert FinancialTransaction.objects.count() == 1
