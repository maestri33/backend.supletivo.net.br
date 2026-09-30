"""Router de vitrine de preços e indicação pública (Funil do Aluno)."""

from __future__ import annotations

from django.http import HttpResponse
from ninja import Router

from api.clients.schemas import PricingOut, ReferralOut
from core.edge_cache import apply_edge_cache, edge_cache
from users.roles.lead import service as lead_iface

router = Router(tags=["pricing"])


def _get_auth_lead(request):
    """Tenta extrair o lead autenticado via Bearer token (se presente)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    try:
        from users.auth.jwt import service as jwt_service
        from users.roles.lead.models import Lead

        payload = jwt_service.decode(token)
        ext_id = payload.get("external_id")
        if ext_id:
            return Lead.objects.filter(user__external_id=ext_id).first()
    except Exception:
        return None
    return None


@router.get("/pricing", response=PricingOut, auth=None, summary="Preço de vitrine público")
def pricing(request, response: HttpResponse, ref: str | None = None):
    """Preço de VITRINE: se o visitante já for um lead autenticado, devolve o preço imutável travado na sua criação."""
    lead = _get_auth_lead(request)
    if lead:
        return lead.get_pricing_dict()

    if not ref:
        apply_edge_cache(
            response,
            max_age=60,
            s_maxage=300,
            stale_while_revalidate=600,
            vary=("Origin", "Authorization"),
        )
    return lead_iface.pricing(ref=ref)



@router.get("/referral/{ref}", response=ReferralOut, auth=None, summary="Selo de indicação por promotor")
@edge_cache(max_age=60, s_maxage=300, stale_while_revalidate=600)
def referral(request, response: HttpResponse, ref: str):
    """Resolve o primeiro nome do promotor para o selo de indicação."""
    return {"name": lead_iface.referral_name(ref)}
