"""Schemas Pydantic v2 do grupo Staff: Polos, Promotores e Coordenadores."""

from __future__ import annotations

from ninja import Field, Schema
from pydantic import ConfigDict


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
