"""Schemas Pydantic v2 do grupo Staff: Autenticação."""

from __future__ import annotations

from ninja import Field, Schema


class StaffCheckIn(Schema):
    cpf: str | None = None
    phone: str | None = None
    external_id: str | None = None
    preferred_channel: str | None = None


class StaffCheckOut(Schema):
    found: bool
    external_id: str | None = None
    otp_sent: bool
    otp_wait: int | None = None
    masked_email: str | None = None
    channels_sent: list[str] = Field(default_factory=list)


class StaffLoginIn(Schema):
    external_id: str
    otp: str


class StaffLoginPasswordIn(Schema):
    identifier: str
    password: str
