"""Router da fase de Lead (Funil do Aluno)."""

from __future__ import annotations

from ninja import Router

from api.auth import require_roles
from api.clients.schemas import (
    CheckoutOut,
    CheckoutSetIn,
    EmailIn,
    EmailOut,
    IdentityIn,
    IdentityOut,
    LeadMeOut,
    UrlOut,
)
from users.auth import service as auth_iface
from users.exceptions import NotFound
from users.roles.lead import service as lead_iface

router = Router(tags=["lead"])

FUNNEL_ROLES = ("veteran", "student", "enrollment", "lead")


def _lead_guard(request):
    """Devolve o lead do usuário logado (404 se não houver). Aceita qualquer role do funil."""
    require_roles(request.auth, *FUNNEL_ROLES)
    lead = lead_iface.get_for_user_external_id(request.auth.external_id)
    if lead is None:
        raise NotFound("Lead não encontrado.", code="LEAD_NOT_FOUND")
    return lead


@router.get("/me", response=LeadMeOut, summary="Dados completos do lead logado")
def lead_me(request):
    """TODOS os dados do lead do cliente logado, incl. checkout/recibo."""
    return lead_iface.lead_self_dict(_lead_guard(request))


@router.get("/checkout-url", response=UrlOut, summary="URL de checkout do lead")
def lead_checkout_url(request):
    """Só a URL de pagamento/recibo do lead."""
    url = lead_iface.checkout_url_for(_lead_guard(request))
    if url is None:
        raise NotFound("Checkout não encontrado.", code="CHECKOUT_NOT_FOUND")
    return {"url": url}


@router.post("/identity", response=IdentityOut, summary="Confirmação de CPF (Passo 3)")
def lead_identity(request, payload: IdentityIn):
    """Passo 3 — confirma o CPF e devolve a identidade (pergaminho)."""
    require_roles(request.auth, "lead")
    return auth_iface.confirm_identity(
        user_external_id=request.auth.external_id, cpf=payload.cpf
    )


@router.post("/email", response=EmailOut, summary="Gravação de e-mail (Passo 5)")
def lead_email(request, payload: EmailIn):
    """Passo 5 — grava o e-mail do lead."""
    require_roles(request.auth, "lead")
    return auth_iface.set_email(
        user_external_id=request.auth.external_id, email=payload.email
    )


@router.post("/checkout", response=CheckoutOut, summary="Escolha/Troca de pagamento (Passo 6)")
def lead_set_checkout(request, payload: CheckoutSetIn):
    """Passo 6 — define (ou troca) a forma de pagamento e cria o checkout."""
    require_roles(request.auth, "lead")
    return lead_iface.set_checkout(
        user_external_id=request.auth.external_id,
        payment_method=payload.payment_method,
    )
