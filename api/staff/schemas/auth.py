"""Schemas Pydantic v2 do grupo Staff: Autenticação."""

from __future__ import annotations

from ninja import Schema


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
