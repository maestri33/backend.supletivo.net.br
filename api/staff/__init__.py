"""Grupo `staff` — administração da plataforma (superuser puro)."""

from __future__ import annotations

from api.base import build_group
from api.health import staff_health_router
from api.staff.routers.auth import router as auth_router
from api.staff.routers.config import router as config_router
from api.staff.routers.coordinators import router as coordinators_router
from api.staff.routers.documents import router as documents_router
from api.staff.routers.finance import router as finance_router
from api.staff.routers.hubs import router as hubs_router
from api.staff.routers.materials import router as materials_router
from api.staff.routers.network import router as network_router
from api.staff.routers.notify import router as notify_router
from api.staff.routers.system import router as system_router
from api.staff.routers.training import router as training_router
from api.staff.routers.users import router as users_router


api = build_group(
    "staff", "Administração da plataforma: hub, coordenador, saúde dos serviços."
)

api.add_router("/auth", auth_router)
api.add_router("", hubs_router)
api.add_router("", materials_router)
api.add_router("", finance_router)
api.add_router("", users_router)
api.add_router("", coordinators_router)
api.add_router("", config_router)
api.add_router("", notify_router)
api.add_router("", documents_router)
api.add_router("", network_router)
api.add_router("", training_router)
api.add_router("", system_router)
api.add_router("", staff_health_router)

__all__ = ["api"]


