"""Schemas Pydantic v2 do grupo Staff: Árvore da Rede de Polos e Promotores."""

from __future__ import annotations

from ninja import Field, FilterSchema, Schema


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
