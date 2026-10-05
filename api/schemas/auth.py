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
    email: str | None = None
    hub: str | None = None
    external_id: str | None = None  # re-dispara OTP de usuário já conhecido (do USER)
    ref: str | None = None  # external_id do promotor (landing ?ref=)
    send_otp: bool = True  # send_otp=False permite checar/gerar token em teste/bot autenticado
    preferred_channel: str | None = Field(default=None, description="Canal preferido para envio de OTP: 'whatsapp', 'email' ou 'all'")
    attribution: AttributionIn | None = None
    turnstile_token: str | None = None  # Token emitido pelo Cloudflare Turnstile
    name: str | None = None
    gender: str | None = None
    auto_capture: bool = Field(default=True, description="Se False, apenas valida existência e WhatsApp sem capturar lead nem criar usuário")



class CheckOut(Schema):
    """Resposta do `POST /auth/check` — compartilhada pelos grupos do funil (dedup)."""

    found: bool
    registered: bool = True
    external_id: str | None = Field(
        None, description="external_id do USER (é o que o /auth/login espera)"
    )
    name: str | None = None
    masked_phone: str | None = None
    masked_email: str | None = Field(default=None, description="E-mail mascarado para onde o OTP foi enviado")
    channels_sent: list[str] | None = Field(default=None, description="Canais para onde o código foi despachado")
    otp_sent: bool = False
    otp_wait: int | None = None
    whatsapp: bool | None = None
    roles: list[str] | None = None
    token: str | None = None
    created: bool = False
    is_valid: bool = True
    birth_date: str | None = None
    sex: str | None = None
    next_route: str = Field(default="/autenticacao/otp", description="Próxima rota no frontend")



class LoginIn(Schema):
    """Body do `POST /auth/login` — compartilhado pelos grupos do funil (dedup)."""

    external_id: str = Field(
        default="", description="external_id do USER (veio do /auth/check)"
    )
    otp: str

    phone: str | None = Field(
        default=None, description="Fallback opcional de telefone caso external_id esteja ausente"
    )
    cpf: str | None = Field(
        default=None, description="Fallback opcional de CPF caso external_id esteja ausente"
    )


class RefreshIn(Schema):
    """Body do `POST /auth/refresh` — compartilhado pelos grupos (dedup #4)."""

    refresh_token: str


class TokenOut(Schema):
    """Par de tokens devolvido por `login`/`refresh` — compartilhado pelos grupos (dedup #4)."""

    access_token: str
    refresh_token: str
    token_type: str


class PhoneRecoveryIn(Schema):
    """Payload de solicitação e execução de troca de telefone / recuperação de conta por CPF."""

    cpf: str = Field(description="CPF do titular (11 dígitos)")
    new_phone: str = Field(description="Novo número de WhatsApp (com DDD)")
    birth_date: str | None = Field(
        default=None,
        description="Data de nascimento do titular (YYYY-MM-DD ou DD/MM/YYYY) para validação de segurança",
    )
    email: str | None = Field(
        default=None,
        description="E-mail cadastrado para validação ou recebimento do código de desafio",
    )
    otp: str | None = Field(
        default=None,
        description="Código OTP de validação (enviado ao e-mail cadastrado)",
    )
    method: str = Field(
        default="email",
        description="Método de verificação solicitado ('email', 'birth_date', 'secretaria')",
    )
    turnstile_token: str | None = Field(
        default=None,
        description="Token de segurança Cloudflare Turnstile antifraude",
    )


class PhoneRecoveryOut(Schema):
    """Resposta do processo de recuperação de conta / troca de telefone."""

    success: bool
    protocol: str = Field(description="Número de protocolo auditável da solicitação")
    status: str = Field(
        description="Status do processamento: 'COMPLETED', 'CHALLENGE_REQUIRED', 'PENDING_SECRETARIA'"
    )
    message: str = Field(description="Mensagem explicativa orientando o usuário")
    masked_email: str | None = Field(
        default=None,
        description="E-mail mascarado para onde o desafio foi enviado, se aplicável",
    )
    masked_new_phone: str | None = Field(
        default=None,
        description="Novo número mascarado com regras de privacidade",
    )
    requires_challenge: bool = Field(
        default=False,
        description="Indica se é necessário submeter OTP enviado por e-mail",
    )

