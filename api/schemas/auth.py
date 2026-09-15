from __future__ import annotations

from ninja import Field, Schema


class AttributionIn(Schema):
    """Payload de atribuição de tráfego (UTMs, click IDs, cookies Meta)."""

    ref: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    utm_term: str | None = None
    utm_content: str | None = None
    gclid: str | None = None
    fbclid: str | None = None
    fbp: str | None = None
    fbc: str | None = None
    landing_url: str | None = None


class CheckIn(Schema):
    """Body do `POST /auth/check` — compartilhado pelos grupos do funil (dedup)."""

    cpf: str | None = None
    phone: str | None = None
    external_id: str | None = None  # re-dispara OTP de usuário já conhecido (do USER)
    ref: str | None = None  # external_id do promotor (landing ?ref=)
    send_otp: bool = True  # send_otp=False permite checar/gerar token em teste/bot autenticado
    attribution: AttributionIn | None = None
    turnstile_token: str | None = None  # Token emitido pelo Cloudflare Turnstile



class CheckOut(Schema):
    """Resposta do `POST /auth/check` — compartilhada pelos grupos do funil (dedup)."""

    found: bool
    registered: bool = True
    external_id: str | None = Field(
        None, description="external_id do USER (é o que o /auth/login espera)"
    )
    name: str | None = None
    masked_phone: str | None = None
    otp_sent: bool = False
    otp_wait: int | None = None
    whatsapp: bool | None = None
    roles: list[str] | None = None
    token: str | None = None
    created: bool = False
    is_valid: bool = True
    birth_date: str | None = None
    sex: str | None = None


class LoginIn(Schema):
    """Body do `POST /auth/login` — compartilhado pelos grupos do funil (dedup)."""

    external_id: str = Field(description="external_id do USER (veio do /auth/check)")
    otp: str


class RefreshIn(Schema):
    """Body do `POST /auth/refresh` — compartilhado pelos grupos (dedup #4)."""

    refresh_token: str


class TokenOut(Schema):
    """Par de tokens devolvido por `login`/`refresh` — compartilhado pelos grupos (dedup #4)."""

    access_token: str
    refresh_token: str
    token_type: str
