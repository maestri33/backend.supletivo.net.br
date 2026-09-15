"""Schemas Pydantic v2 do grupo Staff: Gestão de Usuários, Leads, Matrículas e Conciliação."""

from __future__ import annotations

from typing import Any

from ninja import Field, FilterSchema, Schema
from pydantic import ConfigDict


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
