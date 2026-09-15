"""Schemas Pydantic v2 do grupo Staff (Administração / Superuser)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from ninja import Field, FilterSchema, Schema
from pydantic import ConfigDict, field_validator
from users.auth import validation as auth_val


# ── 1. Auth ───────────────────────────────────────────────────────────────────


class StaffCheckIn(Schema):
    cpf: str | None = None
    phone: str | None = None
    external_id: str | None = None


class StaffCheckOut(Schema):
    found: bool
    external_id: str | None = None
    otp_sent: bool
    otp_wait: int | None = None


class StaffLoginIn(Schema):
    external_id: str
    otp: str


class StaffLoginPasswordIn(Schema):
    identifier: str
    password: str



# ── 2. Hubs & Promotores ───────────────────────────────────────────────────────


class HubCreateIn(Schema):
    brand: str
    coordinator_external_id: str
    address_id: int | None = None
    cep: str | None = None
    street: str | None = None
    number: str | None = None
    complement: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None
    is_default: bool = False


class SetCoordinatorIn(Schema):
    coordinator_external_id: str


class HubAddressIn(Schema):
    cep: str
    number: str | None = None
    complement: str | None = None
    street: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None


class HubAddressPatchIn(Schema):
    cep: str | None = None
    number: str | None = None
    complement: str | None = None
    street: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None


class HubAddressOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    cep: str | None = None
    zipcode: str | None = None
    street: str | None = None
    number: str | None = None
    complement: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None


class HubOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    brand: str
    coordinator_external_id: str | None
    coordinator_name: str | None = None
    is_default: bool
    address: HubAddressOut | None = None


class PromoterOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    name: str | None
    phone: str | None = None
    cpf: str | None = None


# ── 3. Coordinators ────────────────────────────────────────────────────────────


class CoordinatorHubOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    brand: str
    is_default: bool
    zipcode: str | None = None
    city: str | None = None
    state: str | None = None
    street: str | None = None
    promoters_count: int = 0
    students_count: int = 0


class CoordinatorOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    name: str | None = None
    cpf: str | None = None
    phone: str | None = None
    hubs: list[CoordinatorHubOut] = Field(default_factory=list)
    hubs_count: int = 0
    promoters_count: int = 0
    students_count: int = 0
    total_commission: str = "0.00"
    pending_commission: str = "0.00"


# ── 4. Documents & Dossier ─────────────────────────────────────────────────────


class DocumentDecideIn(Schema):
    kind: str  # rg, selfie, address_proof, student_doc
    approve: bool
    reason: str | None = None
    doc_id: str | None = None


class DocumentReprocessIn(Schema):
    pipeline: str = "all"  # ocr, extract, biometric, all
    model: str | None = None


class DocumentReviewFilterSchema(FilterSchema):
    hub: str | None = None
    doc_type: str | None = None


class DocumentReviewOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    user_external_id: str | None = None
    name: str
    phone: str | None = None
    cpf: str | None = None
    hub_name: str | None = None
    type: str
    kind: str
    reason: str
    created_at: str


class DossierProfileOut(Schema):
    name: str | None = None
    cpf: str | None = None
    phone: str | None = None
    email: str | None = None
    birth_date: str | None = None
    mother_name: str | None = None
    father_name: str | None = None
    pix_key: str | None = None
    selfie_needs_meeting: bool = False


class DossierMediaOut(Schema):
    front_photo: str | None = None
    back_photo: str | None = None
    full_photo: str | None = None
    selfie_photo: str | None = None
    face_crop: str | None = None
    address_photo: str | None = None


class DossierDocumentDataOut(Schema):
    doc_type: str | None = None
    number: str | None = None
    state: str | None = None
    validation_status: str | None = None
    validation_reason: str | None = None
    extracted_data: dict[str, Any] = Field(default_factory=dict)


class DossierBiometricsOut(Schema):
    selfie_status: str | None = None
    selfie_reason: str | None = None
    verifications: list[dict[str, Any]] = Field(default_factory=list)


class DossierAddressOut(Schema):
    street: str | None = None
    number: str | None = None
    complement: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None
    zipcode: str | None = None


class UserDossierOut(Schema):
    user_external_id: str
    profile: DossierProfileOut
    media: DossierMediaOut
    document_data: DossierDocumentDataOut
    biometrics: DossierBiometricsOut
    address: DossierAddressOut


class DocumentDecideOut(Schema):
    detail: str
    status: str


# ── 5. Finance ─────────────────────────────────────────────────────────────────


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



# ── 6. Materials & Training ────────────────────────────────────────────────────


class StaffMaterialOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    title: str
    text_content: str
    content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    question: str
    video: str | None = None
    photo: str | None = None
    kind: str
    blocking: bool
    ephemeral: bool
    order: int
    active: bool
    expected_answer: str | None = None


class PublishMaterialOut(Schema):
    external_id: str
    assigned: int


class DeleteMaterialOut(Schema):
    deleted: str


class TrainingSubmissionFilterSchema(FilterSchema):
    status: str | None = None
    material_id: str | None = None


class TrainingSubmissionOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    user_external_id: str
    user_name: str
    user_phone: str | None = None
    material_title: str
    material_question: str
    material_expected: str
    answer: str
    audio_url: str | None = None
    grade: str | None = None
    justification: str | None = None
    status: str
    created_at: str


class TrainingOverrideOut(Schema):
    detail: str
    status: str


class TrainingUnlockOut(Schema):
    detail: str


# ── 7. Network Tree ────────────────────────────────────────────────────────────


class NetworkTreeFilterSchema(FilterSchema):
    hub: str | None = None


class NetworkTreeCoordinatorOut(Schema):
    user_external_id: str | None = None
    name: str
    phone: str | None = None


class NetworkTreeMetricsOut(Schema):
    total_promoters: int
    total_leads: int
    total_paid: int
    conversion_rate: float


class NetworkTreePromoterOut(Schema):
    external_id: str
    user_external_id: str | None = None
    name: str
    phone: str | None = None
    status: str
    leads_count: int
    paid_count: int
    students_count: int
    conversion_rate: float


class NetworkTreeHubOut(Schema):
    hub_external_id: str
    brand: str
    is_default: bool
    coordinator: NetworkTreeCoordinatorOut
    metrics: NetworkTreeMetricsOut
    promoters: list[NetworkTreePromoterOut] = Field(default_factory=list)


# ── 8. Notify ──────────────────────────────────────────────────────────────────


class TemplatePatchIn(Schema):
    title: str | None = None
    subject: str | None = None
    body_md: str | None = None
    is_tts: bool | None = None
    channels: str | None = None
    media_url: str | None = None
    media_type: str | None = None
    mail_template: str | None = None
    notes: str | None = None


class PreviewIn(Schema):
    ctx: dict[str, Any] | None = None


class TestIn(Schema):
    channels: list[str] | None = None
    ctx: dict[str, Any] | None = None


class AiAssistIn(Schema):
    text: str
    action: str = "improve"  # improve | simplify | shorten | fix | custom
    custom_prompt: str | None = None


class AiAssistOut(Schema):
    text: str
    action: str


class NotifyTriggerOut(Schema):
    fires_on: str = ""
    source: str | None = None
    delay_minutes: int = 0
    active: bool = True


class NotifyTemplateOut(Schema):
    event: str
    external_id: str
    title: str | None = None
    subject: str | None = None
    body_md: str | None = None
    is_tts: bool = False
    channels: str = "whatsapp,email"
    media_url: str | None = None
    media_type: str | None = None
    mail_template: str = "default"
    notes: str | None = None
    updated_at: str = "2026-08-19T00:00:00Z"
    trigger: NotifyTriggerOut | None = None


class NotifyTemplateStatsOut(Schema):
    total: int
    active: int
    inactive: int
    with_tts: int
    with_media: int
    by_channel: dict[str, int] = Field(default_factory=dict)


class NotifyEventOut(Schema):
    event: str
    has_template: bool
    has_in_memory: bool
    active: bool


class NotifyPreviewOut(Schema):
    event: str
    body_md: str
    rendered: str
    is_tts: bool
    channels: list[str] = Field(default_factory=list)


class NotifyTestOut(Schema):
    external_id: str


class NotifyHistoryItemOut(Schema):
    external_id: str | None = None
    caller: str | None = None
    recipient_phone: str | None = None
    recipient_email: str | None = None
    title: str | None = None
    subject: str | None = None
    text: str = ""
    want_whatsapp: bool = False
    want_email: bool = False
    want_tts: bool = False
    whatsapp_status: str | None = None
    email_status: str | None = None
    tts_status: str | None = None
    whatsapp_error: str | None = None
    email_error: str | None = None
    tts_error: str | None = None
    attempts: int = 0
    idempotency_key: str | None = None
    created_at: Any | None = None


class TtsOptionOut(Schema):
    model: str
    voice_female: str
    voice_male: str


class TtsConfigOut(Schema):
    omniroute_url: str
    chain: list[TtsOptionOut] = Field(default_factory=list)
    cross_gender_rule: str = "Destinatário Homem (M) recebe voz feminina; Mulher (F) recebe voz masculina."


class TtsProbeIn(Schema):
    text: str = "Olá, esta é uma mensagem de teste da síntese de voz V7M."
    gender: str | None = None  # "M", "F" ou None
    voice_override: str | None = None


class TtsProbeOut(Schema):
    ok: bool
    audio_url: str | None = None
    gender_target: str
    voice_used: str
    omniroute_url: str
    chain_results: list[dict[str, Any]] = Field(default_factory=list)


# ── 9. System & Logs ───────────────────────────────────────────────────────────


class IntegrationStatusOut(Schema):
    name: str
    configured: bool
    config: dict[str, bool] = Field(default_factory=dict)
    flow: str
    checks: dict[str, Any] = Field(default_factory=dict)


class IntegrationDetailOut(Schema):
    name: str
    configured: bool
    config: dict[str, bool] = Field(default_factory=dict)
    flow: str
    checks: dict[str, Any] = Field(default_factory=dict)
    live: dict[str, Any] | None = None


class SystemStatusOut(Schema):
    db_ok: bool
    migrations_pending: list[str] = Field(default_factory=list)
    qcluster_alive: bool
    qcluster_count: int
    queued_tasks: int | None = None
    success_tasks: int
    failure_tasks: int
    debug: bool
    external_url: str


class AiCallLogFilterSchema(FilterSchema):
    status: str | None = None


class AiCallLogOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    model: str
    operation: str
    caller: str
    status: str
    cost: str | None = None
    latency_ms: int | None = None
    error: str | None = None
    created_at: str


class ValidationCheckLogFilterSchema(FilterSchema):
    scope: str | None = None


class ValidationCheckLogOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    scope: str
    name: str
    passed: bool
    mode: str
    detail: str | None = None
    checked_at: str


# ── 10. Config ─────────────────────────────────────────────────────────────────


class BossIn(Schema):
    name: str | None = None
    cpf: str | None = None
    phone: str | None = None
    email: str | None = None
    pix_key: str | None = None
    default_brand: str | None = None
    password: str | None = None

    @field_validator("cpf")
    @classmethod
    def validate_boss_cpf(cls, v: str | None) -> str | None:
        if v is not None and str(v).strip():
            try:
                return auth_val.validate_cpf_strict(str(v).strip())
            except ValueError as exc:
                raise ValueError(f"CPF inválido: {exc}") from exc
        return v

    @field_validator("phone")
    @classmethod
    def validate_boss_phone(cls, v: str | None) -> str | None:
        if v is not None and str(v).strip():
            try:
                return auth_val.validate_phone_strict(str(v).strip())
            except ValueError as exc:
                raise ValueError(f"Celular/Telefone inválido: {exc}") from exc
        return v


class PricingIn(Schema):
    price_pix: str | None = None
    price_card_cents: int | None = None
    promo_price_pix: str | None = None
    promo_price_card_cents: int | None = None
    promoter_study_unlock_threshold: int | None = None
    promoter_study_complete_threshold: int | None = None
    promoter_price_pix: str | None = None
    promoter_price_card_cents: int | None = None
    card_installments: int | None = None
    description: str | None = None


class CommissionsIn(Schema):
    commission_direct: str | None = None
    commission_bonus_flat: str | None = None
    commission_bonus_threshold: int | None = None
    commission_coordinator: str | None = None
    commission_closing_weekday: int | None = None
    commission_closing_hour: int | None = None


class PlatformSetupIn(Schema):
    boss: BossIn | None = None
    pricing: PricingIn | None = None
    commissions: CommissionsIn | None = None
    integrations: dict[str, str] | None = None


class PlatformSetupBossOut(Schema):
    name: str | None = None
    cpf: str | None = None
    phone: str | None = None
    email: str | None = None
    pix_key: str | None = None
    default_brand: str | None = None


class PlatformSetupPricingOut(Schema):
    price_pix: str | None = None
    price_card_cents: int | None = None
    promo_price_pix: str | None = None
    promo_price_card_cents: int | None = None
    promoter_study_unlock_threshold: int | None = None
    promoter_study_complete_threshold: int | None = None
    promoter_price_pix: str | None = None
    promoter_price_card_cents: int | None = None
    card_installments: int | None = None
    description: str | None = None


class PlatformSetupCommissionsOut(Schema):
    commission_direct: str | None = None
    commission_bonus_flat: str | None = None
    commission_bonus_threshold: int | None = None
    commission_coordinator: str | None = None
    commission_closing_weekday: int | None = None
    commission_closing_hour: int | None = None


class PlatformSetupOut(Schema):
    boss: PlatformSetupBossOut | None = None
    pricing: PlatformSetupPricingOut | None = None
    commissions: PlatformSetupCommissionsOut | None = None
    integrations: dict[str, Any] = Field(default_factory=dict)


class SeedRunOut(Schema):
    success: bool
    output: str
    config: dict[str, Any] = Field(default_factory=dict)


class IntegrationTestLiveOut(Schema):
    name: str
    success: bool
    latency_ms: int
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class BootstrapStatusOut(Schema):
    bootstrapped: bool
    setup_required: bool


class BootstrapInitIn(Schema):
    boss: BossIn
    pricing: PricingIn | None = None
    commissions: CommissionsIn | None = None
    integrations: dict[str, str] | None = None


class BootstrapInitOut(Schema):
    success: bool
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_external_id: str


# ── 11. Users ──────────────────────────────────────────────────────────────────


class PlatformCredentialsIn(Schema):
    platform_login: str
    platform_password: str
    platform_url: str | None = None
    platform_notes: str | None = None


class PhoneIn(Schema):
    phone: str


class StaffLeadFilterSchema(FilterSchema):
    hub: str | None = None
    status: str | None = None


class StaffLeadOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    name: str | None = None
    phone: str | None = None
    cpf: str | None = None
    email: str | None = None
    status: str
    hub: str | None = None
    promoter: str | None = None
    created_at: str | None = None
    step: int | None = None
    payment_method: str | None = None


class StaffLeadMarkPaidOut(Schema):
    detail: str


class StaffPurgeFunnelUserOut(Schema):
    user_external_id: str
    deleted: dict[str, int] = Field(default_factory=dict)


class StaffEnrollmentFilterSchema(FilterSchema):
    hub: str | None = None
    status: str | None = None


class StaffEnrollmentOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    status: str
    self_study: bool
    hub_external_id: str
    name: str | None = None


class StaffStudentFilterSchema(FilterSchema):
    hub: str | None = None
    status: str | None = None


class StaffStudentOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    status: str
    self_study: bool
    hub_external_id: str
    name: str | None = None


class StaffStudentPlatformCredentialsOut(Schema):
    external_id: str
    status: str


class StaffUserFilterSchema(FilterSchema):
    role: str | None = None


class StaffUserOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    name: str | None = None
    cpf: str | None = None
    phone: str | None = None
    is_superuser: bool
    roles: list[str] = Field(default_factory=list)


class StaffUserPhoneOut(Schema):
    external_id: str
    phone: str


class AsaasReconciliationOut(Schema):
    """Relatório de conciliação bancária: saldo Asaas vs ativo contábil vs obrigações pendentes."""

    asaas_live_balance: str | None = None
    ledger_asset_balance: str
    total_debits: str
    total_credits: str
    pending_payouts: str
    pending_commissions: str
    total_obligations: str
    liquid_projected_balance: str
    is_solvent: bool
    reconciled_at: str
