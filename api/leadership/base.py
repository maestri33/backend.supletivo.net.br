"""Helpers e guards compartilhados do grupo Leadership (Coordenador de Polo)."""

from __future__ import annotations

from api.auth import require_roles
from hub import interface as hub_iface
from users.auth.models import User
from users.exceptions import Forbidden

NOT_COORDINATOR_DETAIL = (
    "Você não pode entrar como coordenador: não coordena nenhum polo. "
    "Faça seu login na área da sua função."
)


def get_coordinator(request) -> User:
    """Valida role coordinator e devolve o User logado."""
    require_roles(request.auth, "coordinator")
    user = User.objects.filter(
        external_id=request.auth.external_id, is_active=True
    ).first()
    if user is None:
        raise Forbidden("Coordenador não encontrado.", code="FORBIDDEN_ROLE")
    return user


def get_coordinator_hub(coordinator: User):
    """Devolve o polo coordenado pelo usuário ou 403 NOT_HUB_COORDINATOR."""
    hub = hub_iface.coordinated_by(coordinator)
    if hub is None:
        raise Forbidden(NOT_COORDINATOR_DETAIL, code="NOT_HUB_COORDINATOR")
    return hub
