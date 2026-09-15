"""Schemas Pydantic v2 do grupo Staff: Configuração e Setup da Plataforma."""

from __future__ import annotations

from typing import Any

from ninja import Field, Schema
from pydantic import field_validator
from users.auth import validation as auth_val


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
    anchor_full: str | None = None
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
    anchor_full: str | None = None
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
