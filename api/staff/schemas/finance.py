"""Schemas Pydantic v2 do grupo Staff: Financeiro, Comissões, Payouts e Ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ninja import Field, FilterSchema, Schema
from pydantic import ConfigDict


class FinanceBalanceOut(Schema):
    balance: float | None = None
    error: str | None = None
    note: str | None = None


class FinanceSummaryStatusItemOut(Schema):
    count: int = 0
    total: str = "0"


class FinanceSummaryOut(Schema):
    commissions: dict[str, FinanceSummaryStatusItemOut] = Field(default_factory=dict)
    payment_requests: dict[str, FinanceSummaryStatusItemOut] = Field(default_factory=dict)


class FinanceCommissionFilterSchema(FilterSchema):
    status: str | None = None


class StaffCommissionOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    payee_external_id: str | None = None
    payee_role: str
    source_type: str
    amount: str
    status: str
    external_reference: str | None = None
    created_at: str


class ManualCommissionIn(Schema):
    user_external_id: str
    amount: str
    description: str | None = None
    role: str = "promoter"


class ManualCommissionOut(Schema):
    external_id: str
    payee_external_id: str
    amount: str
    source_type: str
    status: str
    created_at: str


class AdvancePayoutOut(Schema):
    payment_request_external_id: str
    external_reference: str
    amount: str
    status: str
    commissions_count: int
    pix_key: str | None = None


class FinancePayoutFilterSchema(FilterSchema):
    status: str | None = None
    kind: str | None = None


class StaffPaymentRequestOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    kind: str
    method: str
    amount: str
    status: str
    supplier_name: str | None = None
    payee_name: str | None = None
    payee_phone: str | None = None
    payee_external_id: str | None = None
    pix_key: str | None = None
    last_error: str | None = None
    attempts: int = 0
    next_attempt_at: str | None = None
    week_of: str | None = None
    scheduled_for: str | None = None
    asaas_status: str | None = None
    external_reference: str | None = None
    boleto_line: str | None = None
    receipt: str | None = None
    created_at: str


class ManualPaymentOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    kind: str
    method: str
    amount: str
    status: str
    external_reference: str | None = None
    receipt: str | None = None


class WeeklyClosingResultOut(Schema):
    week_of: str
    friday: str
    commissions_in_window: int
    bonuses_created: int
    payment_requests_created: int
    awaiting_pix: int


class ClosingHealthOut(Schema):
    week_of: str
    pending_commissions: str
    queued_payouts: str
    obrigacao_estimada: str
    saldo: str | None = None
    suficiente: bool | None = None
    deficit: str | None = None
    balance_error: Any | None = None


class ClosingSimulationBeneficiaryOut(Schema):
    user_external_id: str
    name: str
    phone: str | None = None
    cpf: str | None = None
    role: str
    amount: str
    leads_count: int
    bonus_earned: bool
    pix_key: str | None = None
    has_pix: bool


class ClosingSimulationOut(Schema):
    week_of: str
    friday: str
    total_obligation: str
    commissions_count: int
    bonuses_count: int
    beneficiaries_count: int
    awaiting_pix_count: int
    bonus_threshold: int
    bonus_amount: str
    beneficiaries: list[ClosingSimulationBeneficiaryOut] = Field(default_factory=list)


class FinanceScheduleItemOut(Schema):
    id: int
    name: str
    func: str
    schedule_type: str
    minutes: int | None = None
    repeats: int | None = None
    next_run: datetime | None = None
    last_run: datetime | None = None
    last_status: str | None = None
    last_result: Any | None = None
    is_active: bool = True


class FinanceScheduleRunOut(Schema):
    success: bool
    schedule_name: str
    func: str
    result: Any | None = None
    executed_at: datetime


class PayoutRetryOut(Schema):
    external_id: str
    status: str
    attempts: int
    last_error: str | None = None
    next_attempt_at: str | None = None


class PayoutOverridePixOut(Schema):
    external_id: str
    status: str
    pix_key: str | None = None
    attempts: int
    last_error: str | None = None
    next_attempt_at: str | None = None


# ── Ledger, Cashflow, Ajustes Manuais e Soberania do Admin ──────────────────────


class FinanceLedgerFilterSchema(FilterSchema):
    account_code: str | None = None
    entry_type: str | None = None


class LedgerEntryOut(Schema):
    external_id: str
    transaction_external_id: str
    account_code: str
    account_name: str
    entry_type: str
    amount: str
    balance_after: str | None = None
    created_at: str


class FinanceTransactionFilterSchema(FilterSchema):
    kind: str | None = None


class FinancialTransactionOut(Schema):
    external_id: str
    kind: str
    amount: str
    status: str
    description: str | None = None
    source_type: str
    source_external_id: str | None = None
    idempotency_key: str
    created_at: str
    settled_at: str | None = None


class CashflowOverviewOut(Schema):
    pending_payouts_queue: str
    unclosed_commissions_liability: str
    month_unexpected_expenses: str
    open_disputes_at_risk: str
    month_accumulated_revenue: str
    total_obligations_due: str
    timestamp: str


class ManualAdjustmentIn(Schema):
    account_code: str
    entry_type: str
    amount: str
    justification: str
    counterpart_account_code: str | None = None
    description: str | None = None


class UnexpectedExpenseIn(Schema):
    category: str
    amount: str
    description: str
    justification: str
    supplier_name: str | None = None
    method: str = "pix_key"
    pix_key: str | None = None
    boleto_line: str | None = None


class UnexpectedExpenseOut(Schema):
    external_id: str
    transaction_external_id: str | None = None
    payment_request_external_id: str | None = None
    category: str
    amount: str
    description: str
    justification: str
    supplier_name: str | None = None
    receipt: str | None = None
    created_at: str


class DisputeRecordOut(Schema):
    external_id: str
    external_dispute_id: str
    amount: str
    status: str
    reason: str
    resolution: str | None = None
    justification: str | None = None
    resolved_at: str | None = None
    created_at: str


class DisputeResolveIn(Schema):
    resolution: str
    justification: str
    correlated_commission_id: str | None = None


class FinanceAuditFilterSchema(FilterSchema):
    action: str | None = None
    target_model: str | None = None


class FinancialAuditLogOut(Schema):
    external_id: str
    actor_external_id: str | None = None
    action: str
    target_model: str
    target_external_id: str | None = None
    justification: str
    snapshot_before: dict[str, Any] | None = None
    snapshot_after: dict[str, Any] | None = None
    created_at: str
