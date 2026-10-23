"""Router da fase de Lead (Funil do Aluno)."""

from __future__ import annotations

from django.conf import settings
from ninja import Router, Schema, Field
from ninja.errors import HttpError

from api.auth import require_roles
from api.clients.schemas import (
    CheckoutOut,
    CheckoutSetIn,
    EmailIn,
    EmailOut,
    IdentityIn,
    IdentityOut,
    LeadCaptureIn,
    LeadCaptureOut,
    LeadMeOut,
    PixPageOut,
    UrlOut,
)

from core.request import get_client_ip
from core.webhook_auth import service_secret_ok
from integrations.turnstile import verify_turnstile
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


class CardConfirmationIn(Schema):
    order_nsu: str = Field(min_length=1, max_length=128)
    transaction_nsu: str = Field(min_length=1, max_length=128)
    slug: str = Field(min_length=1, max_length=128)


@router.post("/card-confirmation", response=LeadMeOut, summary="Conferir retorno do cartão na API do provedor")
def lead_card_confirmation(request, payload: CardConfirmationIn):
    from users.roles.lead.models import PaymentAttempt
    from integrations.bank import recovery
    lead = _lead_guard(request)
    # Return parameters identify a charge; they are never financial proof.
    attempt = PaymentAttempt.objects.filter(lead=lead, user_external_id=request.auth.external_id,
        provider="infinitepay", provider_payment_id=payload.order_nsu).first()
    if attempt is None:
        raise NotFound("Cobrança não pertence a esta conta.", code="CHECKOUT_NOT_FOUND")
    from django.utils import timezone
    from datetime import timedelta
    from integrations.bank.infinitepay.models import WebhookEvent
    row = WebhookEvent.objects.filter(order_nsu=payload.order_nsu,
        payload__transaction_nsu=payload.transaction_nsu, payload__slug=payload.slug,
        received_at__gte=timezone.now() - timedelta(seconds=30)).order_by("-received_at").first()
    row = row or recovery.receive("infinitepay", payload.dict(), order_nsu=payload.order_nsu)
    recovery.process("infinitepay", row.pk)
    return lead_iface.lead_self_dict(_lead_guard(request))


@router.get("/checkout-url", response=UrlOut, summary="URL de checkout do lead")
def lead_checkout_url(request):
    """Só a URL de pagamento/recibo do lead."""
    url = lead_iface.checkout_url_for(_lead_guard(request))
    if url is None:
        raise NotFound("Checkout não encontrado.", code="CHECKOUT_NOT_FOUND")
    return {"url": url}


@router.get(
    "/pix/{token}",
    response=PixPageOut,
    auth=None,
    summary="QR PIX do checkout pelo token do link curto (público)",
)
def lead_pix_page(request, token: str):
    """Dados da página PIX PRÓPRIA — copia-e-cola + PNG do QR estático já emitido.

    PÚBLICO (sem login) porque o lead chega pelo link que recebeu no WhatsApp; o `token` é o
    MESMO segredo do link curto `/lead/checkout/<token>`, então não abre superfície nova. Só
    responde checkout PIX: cartão tem página do gateway (issue #158)."""
    data = lead_iface.pix_page_dict(token)
    if data is None:
        raise NotFound("Checkout PIX não encontrado.", code="CHECKOUT_NOT_FOUND")
    return data


@router.post("/identity", response=IdentityOut, summary="Confirmação de CPF (Passo 3)")
def lead_identity(request, payload: IdentityIn):
    """Passo 3 — enfileira a confirmação CPFHub e devolve o estado do job."""
    require_roles(request.auth, "lead")
    return auth_iface.confirm_identity(
        user_external_id=request.auth.external_id, cpf=payload.cpf
    )


@router.get("/identity/status", response=IdentityOut, summary="Estado da confirmação CPFHub")
def lead_identity_status(request):
    """Consulta o último job CPFHub do lead sem repetir chamada externa."""
    require_roles(request.auth, "lead")
    return auth_iface.get_identity_lookup(user_external_id=request.auth.external_id)


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
    client_ip = get_client_ip(request)
    if getattr(settings, "TURNSTILE_ENABLED", False) and not service_secret_ok(request):
        if not payload.turnstile_token:
            raise HttpError(400, "Token Turnstile obrigatório.")
        result = verify_turnstile(payload.turnstile_token, remote_ip=client_ip)
        if not result.success:
            raise HttpError(400, "Falha na verificação de segurança (Turnstile).")

    attr_data = payload.attribution.dict(exclude_unset=True) if payload.attribution else {}
    if client_ip and "client_ip" not in attr_data:
        attr_data["client_ip"] = client_ip
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:400]
    if user_agent and "user_agent" not in attr_data:
        attr_data["user_agent"] = user_agent

    return lead_iface.set_checkout(
        user_external_id=request.auth.external_id,
        payment_method=payload.payment_method,
        attribution=attr_data or None,
    )


@router.post(
    "/capture",
    response=LeadCaptureOut,
    auth=None,
    summary="Captura inteligente de lead (zero-friction)",
)
def lead_capture(request, payload: LeadCaptureIn):
    """Zero-friction lead capture com validação de CPF, enriquecimento e recuperação amigável."""
    client_ip = get_client_ip(request)
    if getattr(settings, "TURNSTILE_ENABLED", False) and not service_secret_ok(request):
        if not payload.turnstile_token:
            raise HttpError(400, "Token Turnstile obrigatório.")
        result = verify_turnstile(payload.turnstile_token, remote_ip=client_ip)
        if not result.success:
            raise HttpError(400, "Falha na verificação de segurança (Turnstile).")

    attr_data = payload.attribution.dict(exclude_unset=True) if payload.attribution else {}
    if client_ip and "client_ip" not in attr_data:
        attr_data["client_ip"] = client_ip
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:400]
    if user_agent and "user_agent" not in attr_data:
        attr_data["user_agent"] = user_agent

    effective_ref = payload.ref or attr_data.get("ref")

    res = lead_iface.capture_lead(
        phone=payload.phone,
        cpf=payload.cpf,
        name=payload.name,
        ref=effective_ref,
        attribution=attr_data or None,
    )

    from integrations.posthog import track_funnel_checked

    distinct_id = res.get("external_id") or payload.cpf or payload.phone or "anonymous"
    track_funnel_checked(
        distinct_id,
        found=res.get("found", False),
        registered=not res.get("created", False),
        ref=effective_ref,
    )

    return res

