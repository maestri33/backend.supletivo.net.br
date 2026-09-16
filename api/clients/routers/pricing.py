"""Router de vitrine de preços e indicação pública (Funil do Aluno)."""

from __future__ import annotations

from django.http import HttpResponse
from ninja import Router

from api.clients.schemas import PricingOut, ReferralOut
from users.roles.lead import service as lead_iface

router = Router(tags=["pricing"])


@router.get("/pricing", response=PricingOut, auth=None, summary="Preço de vitrine público")
def pricing(request, response: HttpResponse, ref: str | None = None):
    """Preço de VITRINE público (sem login): PIX + cartão em 12x (com suporte a desconto por ref de indicação)."""
    if not ref:
        response["Cache-Control"] = "public, s-maxage=300, stale-while-revalidate=600"
        response["Vary"] = "Origin"
    return lead_iface.pricing(ref=ref)


@router.get("/referral/{ref}", response=ReferralOut, auth=None, summary="Selo de indicação por promotor")
def referral(request, ref: str):
    """Resolve o primeiro nome do promotor para o selo de indicação."""
    return {"name": lead_iface.referral_name(ref)}
