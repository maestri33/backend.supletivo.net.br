from __future__ import annotations

from ninja import Schema


class StudentPlatformFields(Schema):
    url: str | None = None
    login: str | None = None
    password: str | None = None
    notes: str | None = None
