"""Fábrica dos grupos da API Ninja (CONVENTION §1).

Cada grupo é um `NinjaAPI` **versionado** (`/api/v1/<grupo>/`, montado no `core/urls.py`), com
auth JWT default e duas rotas de esqueleto: `health` (pública) e `whoami` (autenticada, prova o
JWT fim-a-fim). As rotas de negócio entram com cada role/módulo (§4), chamando o `interface/`.

Versão: o caminho carrega `v1` e o `NinjaAPI(version=...)` versiona a doc OpenAPI por grupo
(CONVENTION §1 — toda API é versionada). Quebra de contrato = nova versão.
"""

from __future__ import annotations

import structlog
from django.http import JsonResponse
from ninja import Field, NinjaAPI, Schema
from ninja.errors import AuthenticationError, HttpError
from ninja.errors import ValidationError as NinjaValidationError

from api.auth import JWTAuth
from api.schemas import LoginIn, RefreshIn, TokenOut
from users.exceptions import DomainError

logger = structlog.get_logger()

API_VERSION = "1.0"
_DEFAULT_AUTH = object()


class WhoamiOut(Schema):
    external_id: str = Field(
        description="external_id do USER autenticado (≠ enrollment, ≠ lead — proposta #8)"
    )
    roles: list[str]
    name: str | None = None  # do Profile — o front saúda pelo nome
    phone: str | None = None  # telefone do Profile para exibição e suporte
    photo_url: str | None = None  # foto do WhatsApp ou avatar registrado
    avatar_url: str | None = None  # alias de conveniência pro front


class HealthOut(Schema):
    """Resposta padrão do liveness de cada grupo da API."""

    group: str
    version: str
    status: str


def build_group(name: str, description: str, auth_override=_DEFAULT_AUTH) -> NinjaAPI:
    """Cria o `NinjaAPI` de um público: versionado, auth JWT default, com health + whoami.

    `auth_override` = força auth=None (grupo público como health) ou outro auth customizado."""
    api = NinjaAPI(
        version=API_VERSION,
        urls_namespace=f"api-{name}",
        title=f"API {name}",
        description=description,
        auth=JWTAuth() if auth_override is _DEFAULT_AUTH else auth_override,
    )

    @api.exception_handler(DomainError)
    def domain_error(request, exc: DomainError):
        """Erro de DOMÍNIO → JSON padronizado `{detail, code, …extra}` no status do erro. Ex.: etapa
        errada do funil → **409** + `expected_status` (o front roteia o wizard sozinho com isso)."""
        resp = JsonResponse(
            {"detail": exc.detail, "code": exc.code, **exc.extra}, status=exc.status
        )
        retry_after = getattr(exc, "retry_after_s", None)
        if retry_after is not None:
            resp["Retry-After"] = str(retry_after)
        return resp


    # Envelope de erro padronizado (proposta API #5): TODO 4xx sai `{detail, code, …extra}` —
    # o front faz `switch(code)`, nunca parseia o texto de `detail`.
    @api.exception_handler(AuthenticationError)
    def auth_error(request, exc: AuthenticationError):
        """Sem token / token inválido/expirado/versão velha → 401 com code."""
        return JsonResponse(
            {"detail": "Não autenticado — faça login.", "code": "UNAUTHORIZED"},
            status=401,
        )

    @api.exception_handler(NinjaValidationError)
    def schema_error(request, exc: NinjaValidationError):
        """Body/query fora do schema → 422. `detail` mantém a lista do pydantic (aditivo)."""
        return JsonResponse(
            {"detail": exc.errors, "code": "VALIDATION_ERROR"}, status=422
        )

    @api.exception_handler(HttpError)
    def http_error(request, exc: HttpError):
        """HttpError cru (sem code próprio) → ganha o fallback `ERROR` pra manter o envelope."""
        return JsonResponse(
            {"detail": str(exc), "code": "ERROR"}, status=exc.status_code
        )

    @api.exception_handler(Exception)
    def unhandled_error(request, exc: Exception):
        """Erro NÃO tratado → SEMPRE JSON `{detail}` 500 — nunca traceback/URLconf em HTML, nem com
        DEBUG ligado (auditoria do front 2026-06-10). O traceback completo vai pro log do server."""
        logger.exception("api.unhandled_error", group=name, path=request.path)
        return JsonResponse(
            {"detail": "Erro interno do servidor.", "code": "INTERNAL"}, status=500
        )

    @api.get("/health", response=HealthOut, auth=None, tags=["health"])
    def health(request):
        """Liveness público do grupo (sem auth)."""
        return {"group": name, "version": API_VERSION, "status": "ok"}

    @api.get("/whoami", response=WhoamiOut, tags=["auth"])
    def whoami(request):
        """Eco do principal autenticado + `name`, `phone` e `photo_url` do Profile (exige Bearer)."""
        from users.models import Profile

        principal = request.auth
        profile = (
            Profile.objects.filter(user__external_id=principal.external_id)
            .only("name", "phone", "whatsapp_photo_url")
            .first()
        )
        photo = profile.whatsapp_photo_url if profile and profile.whatsapp_photo_url else None
        return {
            "external_id": principal.external_id,
            "roles": principal.roles,
            "name": profile.name if profile else None,
            "phone": profile.phone if profile else None,
            "photo_url": photo,
            "avatar_url": photo,
        }

    return api


# ── registro de erros compartilhado (audit 2026-07-13; era duplicado 4×) ───────
# Códigos comuns a TODO grupo — concatenados com os específicos de cada api.
COMMON_ERROR_REGISTRY = """
### Códigos de erro (`{detail, code, …extra}`)

| code | quando | extras |
|---|---|---|
| `VALIDATION_ERROR` | body/query fora do schema (422) | `detail` = lista do pydantic |
| `MISSING_FIELD` | campo obrigatório vazio no body (422) | — |
| `USER_NOT_FOUND` / `ENROLLMENT_NOT_FOUND` / `LEAD_NOT_FOUND` / `STUDENT_NOT_FOUND` / `ADDRESS_NOT_FOUND` | recurso não existe (404) | — |
| `UNAUTHORIZED` / `SESSION_EXPIRED` | sem token ou token vencido (401) | — |
| `FORBIDDEN_ROLE` / `NOT_IN_FUNNEL` | papel sem acesso à rota (403) | — |
| `RATE_LIMITED` | espera do OTP (429) | `retry_after_s` |
| `ERROR` | fallback (erro sem code próprio) | — |
"""

# ── helpers compartilhados entre grupos (dedup da auditoria 2026-06-17) ───────
RG_PHOTO_SLOTS = {"front": "rg_front", "back": "rg_back", "full": "rg_full"}


def resolve_rg_slot(slot: str) -> str:
    """Slot da borda (`front`/`back`/`full`) → slot interno do `documents`. Desconhecido →
    `ValidationError(SLOT_INVALID)`. Dedup #3: clients + leadership tinham o mesmo mapa/validação."""
    from users.exceptions import ValidationError

    real = RG_PHOTO_SLOTS.get(slot)
    if real is None:
        raise ValidationError(
            "Slot inválido. Aceitos: front, back, full.", code="SLOT_INVALID"
        )
    return real


def add_auth_refresh(router) -> None:
    """Registra o `POST /refresh` padrão (rotação de tokens) — idêntico nos 3 grupos (dedup #4).
    Refresh inválido/expirado OU role trocada desde a emissão (`token_version`) → 401."""
    from users.auth.jwt import service as jwt_service
    from users.exceptions import Unauthorized

    @router.post("/refresh", response=TokenOut, auth=None)
    def refresh(request, payload: RefreshIn):
        """Troca o `refresh_token` por um par NOVO (rotação); o front renova silencioso quando o
        access expira, sem voltar pro OTP."""
        try:
            return jwt_service.refresh(payload.refresh_token)
        except jwt_service.TokenError as exc:
            raise Unauthorized(
                "Sessão expirada — faça login novamente.", code="SESSION_EXPIRED"
            ) from exc


def add_funnel_login(
    router, *, funnel_roles: tuple[str, ...], not_in_funnel_msg: str
) -> None:
    """Registra o `POST /login` passwordless (OTP) de um funil — idêntico entre grupos, só mudam a
    cadeia de papéis (`funnel_roles`, do mais avançado ao menos) e a mensagem do 403 (dedup)."""
    from users.auth import service as auth_iface
    from users.auth.models import User
    from users.exceptions import Forbidden, NotFound
    from users.roles import interface as roles

    @router.post("/login", response=TokenOut, auth=None)
    def login(request, payload: LoginIn):
        """Login passwordless (OTP) — resolve o papel mais avançado do funil e emite JWT com TODAS
        as roles ativas."""
        user = User.objects.filter(external_id=payload.external_id).first()
        if user is None:
            raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
        active = roles.active_roles(user)
        funnel_role = next((r for r in funnel_roles if r in active), None)
        if funnel_role is None:
            raise Forbidden(not_in_funnel_msg, code="NOT_IN_FUNNEL")
        return auth_iface.login(
            external_id=payload.external_id, role=funnel_role, otp=payload.otp
        )
