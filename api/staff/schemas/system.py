"""Schemas Pydantic v2 do grupo Staff: Status do Sistema, Integrações e Logs."""

from __future__ import annotations

from typing import Any

from ninja import Field, FilterSchema, Schema
from pydantic import ConfigDict


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
