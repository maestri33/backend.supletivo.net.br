from __future__ import annotations

from ninja import Schema


class ToolLeadOut(Schema):
    """Linha do radar de leads (mesmo shape da listagem staff/hub)."""

    external_id: str
    status: str
    name: str | None = None
    phone: str | None = None
    promoter_external_id: str
    payment_link: str | None = None
    receipt_url: str | None = None
    created_at: str


class ToolsNotifyIn(Schema):
    """Aceita usuário cadastrado ou destino livre para envio pelo notify-server."""

    user_external_id: str | None = None
    phone: str | None = None
    email: str | None = None
    subject: str | None = None
    message: str
    channels: list[str] | None = None  # subconjunto de {"whatsapp","email"}


class ToolsNotifySentOut(Schema):
    external_id: str


class TurnstileVerifyIn(Schema):
    token: str
    remote_ip: str | None = None


class TurnstileVerifyOut(Schema):
    success: bool
    challenge_ts: str | None = None
    hostname: str | None = None
    error_codes: list[str] = []
    action: str | None = None
    cdata: str | None = None
