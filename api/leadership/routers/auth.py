"""Router de autenticação do grupo Leadership (Coordenador de Polo)."""

from __future__ import annotations

from ninja import Router

from api.base import add_auth_refresh
from api.leadership.base import NOT_COORDINATOR_DETAIL
from api.leadership.schemas import CoordinatorCheckOut
from api.schemas.auth import CheckIn, LoginIn, TokenOut
from hub import interface as hub_iface
from users.auth import service as auth_iface
from users.auth.models import User
from users.exceptions import Forbidden, NotFound

router = Router(tags=["auth"])


@router.post("/check", response=CoordinatorCheckOut, auth=None, summary="Verificação de coordenador")
def check(request, payload: CheckIn):
    """Verifica usuário e valida se coordena um polo."""
    from core.webhook_auth import service_secret_ok

    result = auth_iface.check(
        cpf=payload.cpf,
        phone=payload.phone,
        external_id=payload.external_id,
        send_otp=payload.send_otp,
        service_authed=service_secret_ok(request),
    )
    if not result.get("found"):
        return result
    user = User.objects.filter(
        external_id=result["external_id"], is_active=True
    ).first()
    hub = hub_iface.coordinated_by(user) if user else None
    if hub is None:
        return {**result, "is_coordinator": False, "detail": NOT_COORDINATOR_DETAIL}
    return {
        **result,
        "is_coordinator": True,
        "hub": {"external_id": str(hub.external_id), "brand": hub.brand},
    }


@router.post("/login", response=TokenOut, auth=None, summary="Login do coordenador")
def login(request, payload: LoginIn):
    """Login passwordless (OTP) do coordenador."""
    user = User.objects.filter(external_id=payload.external_id, is_active=True).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    if hub_iface.coordinated_by(user) is None:
        raise Forbidden(NOT_COORDINATOR_DETAIL, code="NOT_HUB_COORDINATOR")
    return auth_iface.login(
        external_id=payload.external_id, role="coordinator", otp=payload.otp
    )


add_auth_refresh(router)
