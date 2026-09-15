"""Router de Promotores do Polo (Coordenador de Polo)."""

from __future__ import annotations

from ninja import Router

from api.leadership.base import get_coordinator, get_coordinator_hub
from api.leadership.schemas import HubPromoterRowOut, MaterialApproveOut
from users.roles.promoter import service as promoter_iface
from users.roles.training import service as training_iface

router = Router(tags=["promoter"])


@router.get("/promoters", response=list[HubPromoterRowOut], summary="Listagem de promotores do polo")
def list_hub_promoters(request):
    """Lista promotores do polo e status de trava de treino."""
    coordinator = get_coordinator(request)
    hub = get_coordinator_hub(coordinator)
    return promoter_iface.list_for_hub(hub)


@router.post("/promoters/{external_id}/suspend", response=HubPromoterRowOut, summary="Suspender promotor")
def suspend_promoter(request, external_id: str):
    """Suspende promotor do polo."""
    coordinator = get_coordinator(request)
    p = promoter_iface.suspend(user_external_id=external_id, coordinator=coordinator)
    from users.profiles import interface as profiles

    profile = profiles.get(p.user)
    return {
        "external_id": external_id,
        "name": profile.name if profile else None,
        "status": p.status,
        "locked": False,
    }


@router.post("/promoters/{external_id}/reactivate", response=HubPromoterRowOut, summary="Reativar promotor")
def reactivate_promoter(request, external_id: str):
    """Reativa promotor suspenso."""
    coordinator = get_coordinator(request)
    p = promoter_iface.reactivate(user_external_id=external_id, coordinator=coordinator)
    from users.profiles import interface as profiles

    profile = profiles.get(p.user)
    return {
        "external_id": external_id,
        "name": profile.name if profile else None,
        "status": p.status,
        "locked": False,
    }


@router.post(
    "/promoters/{external_id}/materials/{material_external_id}/approve",
    response=MaterialApproveOut,
    tags=["training"],
    summary="Aprovar matéria de promotor travado no treino",
)
def approve_open_material(request, external_id: str, material_external_id: str):
    """Coordenador aprova matéria em aberto para destravar promotor."""
    coordinator = get_coordinator(request)
    return training_iface.coordinator_approve_material(
        promoter_external_id=external_id,
        material_external_id=material_external_id,
        coordinator=coordinator,
    )
