"""Tokens JWT da plataforma — via `django-ninja-jwt` (swap do JWT escrito à mão, Victor 2026-06-02).

Mantém o "seam" histórico (`issue`/`refresh`/`decode`) pra NÃO mexer nos chamadores (login em
`users/auth/service.py` e o `HttpBearer` em `api/auth.py`). Só as tripas trocaram: a config (RS256,
chaves de `keys/`, expirações, issuer/audience) vive em `settings.NINJA_JWT` (CONVENTION §10). Sem
consumidor externo → o JWKS foi removido (não há mais `get_jwks` nem `/.well-known/jwks.json`).

Claims no token: `external_id` (str), `roles` (list[str]) e `token_version` (int). O gate lê
`external_id`/`roles` dos claims, mas **confere o `token_version` no banco**: trocar de role incrementa
a versão (`roles.promote`/`assign`) e invalida todo token antigo (Victor 2026-06-05). O ninja-jwt copia
os claims custom do refresh pro access automaticamente.
"""

from __future__ import annotations

import structlog
from ninja_jwt.exceptions import (
    TokenError,
)  # re-exportado p/ o api/auth capturar sem conhecer o ninja
from ninja_jwt.tokens import AccessToken, RefreshToken

logger = structlog.get_logger()

__all__ = ["issue", "refresh", "decode", "TokenError", "version_matches"]


def current_version(external_id: str) -> int:
    """Versão de token atual do User (DB). G2: usuário inexistente OU inativo → -1, que nunca bate
    com uma versão de claims real (>=0). Assim desativar (`is_active=False`, o único ban) derruba
    access E refresh de uma vez, sem precisar bumpar `token_version` no callsite — a divergência é
    automática. Reativar restaura (revogar sessão comprometida é bump de versão, não ban)."""
    from users.auth.models import User

    row = (
        User.objects.filter(external_id=external_id)
        .values_list("is_active", "token_version")
        .first()
    )
    if row is None or not row[0]:  # inexistente ou desativado
        return -1
    return row[1] or 0


def version_matches(external_id: str, claims_version) -> bool:
    """True se a versão dos claims bate com a do User (token não foi invalidado por troca de role)."""
    return int(claims_version or 0) == current_version(external_id)


def issue(external_id: str, roles: list[str]) -> dict:
    """Emite o par access + refresh para `external_id` com as `roles` ativas (passwordless)."""
    rt = RefreshToken()
    rt["external_id"] = str(external_id)
    rt["roles"] = roles
    rt["token_version"] = current_version(external_id)  # carimba a versão atual
    logger.info("jwt.issued", external_id=str(external_id), roles=roles)
    return {
        "access_token": str(
            rt.access_token
        ),  # ninja-jwt copia external_id/roles/token_version do refresh
        "refresh_token": str(rt),
        "token_type": "bearer",
    }


def _live_roles(external_id: str) -> list[str] | None:
    from users.auth.models import User
    from users.roles import interface as role_service

    user = User.objects.filter(external_id=external_id, is_active=True).first()
    if user is None:
        return None
    return sorted(role_service.active_roles(user))


def _promoter_transition_roles(token, external_id: str) -> list[str] | None:
    """Aceita somente a promoção monotônica `candidate` → `promoter` do próprio refresh assinado.

    A selfie é validada de forma assíncrona e a promoção invalida a sessão antiga. Sem esta ponte,
    o próximo poll recebe 401 e prende o usuário no último passo. Qualquer outra troca de papel,
    banimento ou salto de mais de uma versão continua exigindo novo OTP.
    """
    claims_version = int(token.get("token_version") or 0)
    live_version = current_version(external_id)
    if live_version < 0 or live_version != claims_version + 1:
        return None
    live_roles = _live_roles(external_id)
    if live_roles is None:
        return None
    previous = set(token.get("roles") or [])
    current = set(live_roles)
    removed = previous - current
    added = current - previous
    if removed != {"candidate"}:
        return None
    if "promoter" not in added or not added.issubset({"promoter", "training"}):
        return None
    return sorted(current)


def refresh(refresh_token: str) -> dict:
    """Rotaciona o par; só a promoção segura candidato→promotor atravessa troca de role."""
    token = RefreshToken(refresh_token)
    external_id = token.get("external_id", "")
    if not version_matches(external_id, token.get("token_version")):
        transitioned = _promoter_transition_roles(token, external_id)
        if transitioned is None:
            raise TokenError("token_version_stale")
        logger.info("jwt.promoter_transition_refreshed", external_id=external_id)
        return issue(external_id, transitioned)
    roles = _live_roles(external_id)
    if roles is None:
        raise TokenError("token_user_inactive")
    logger.info("jwt.refreshed", external_id=external_id)
    return issue(external_id, roles)


def decode(token: str) -> dict:
    """Valida (assinatura + exp + tipo `access`) e devolve os claims. Levanta `TokenError` se inválido."""
    return dict(AccessToken(token).payload)
