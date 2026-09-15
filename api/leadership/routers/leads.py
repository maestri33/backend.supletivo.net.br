"""Router de Leads do Polo (Coordenador de Polo)."""

from __future__ import annotations

from ninja import Router

from api.leadership.base import get_coordinator, get_coordinator_hub
from api.leadership.schemas import HubLeadDetailOut, HubLeadRowOut
from users.exceptions import NotFound
from users.profiles import interface as profiles
from users.roles.lead import service as lead_iface

router = Router(tags=["lead"])


@router.get("/leads", response=list[HubLeadRowOut], summary="Listagem de leads do polo")
def list_hub_leads(request, status: str | None = None):
    """Lista os leads do polo do coordenador."""
    coordinator = get_coordinator(request)
    hub = get_coordinator_hub(coordinator)
    leads = lead_iface.list_leads(hub=hub, status=status)
    pmap = profiles.get_map([lead.user for lead in leads])
    return [lead_iface.lead_to_dict(lead, profile=pmap.get(lead.user_id)) for lead in leads]


@router.get("/leads/{external_id}", response=HubLeadDetailOut, summary="Detalhe de lead do polo")
def get_hub_lead(request, external_id: str):
    """Detalhe completo de um lead do polo."""
    coordinator = get_coordinator(request)
    hub = get_coordinator_hub(coordinator)
    lead = lead_iface.get_lead_for_hub(external_id=external_id, hub=hub)
    if lead is None:
        raise NotFound("Lead não encontrado neste polo.", code="LEAD_NOT_FOUND")
    return lead_iface.lead_self_dict(lead)
