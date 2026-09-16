"""Router de autenticação do grupo Clients (Funil do Aluno)."""

from __future__ import annotations

from django.conf import settings
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from api.base import add_auth_refresh, add_funnel_login
from api.clients.schemas import LeadCreateIn, LeadOut
from api.schemas.auth import CheckIn, CheckOut
from core.request import get_client_ip
from core.webhook_auth import service_secret_ok
from integrations.turnstile import verify_turnstile
from users.roles.lead import service as lead_iface

router = Router(tags=["auth"])

FUNNEL_ROLES = ("veteran", "student", "enrollment", "lead")


@router.post("/register", response={201: LeadOut}, auth=None, summary="Cadastro inicial do lead")
def register(request, payload: LeadCreateIn):
    """Cadastro do cliente: cria lead + checkout e devolve o pagamento."""
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

    result = lead_iface.create_lead(
        cpf=payload.cpf,
        phone=payload.phone,
        email=payload.email,
        payment_method=payload.payment_method,
        ref=effective_ref,
        attribution=attr_data or None,
    )
    from integrations.posthog import track_funnel_created

    distinct_id = getattr(result, "external_id", None) or payload.cpf
    track_funnel_created(distinct_id, payment_method=payload.payment_method, ref=effective_ref)

    return Status(201, result)


@router.post("/check", response=CheckOut, auth=None, summary="Verificação e disparo de OTP ou captura")
def check(request, payload: CheckIn):
    """Check de telefone/CPF: dispara OTP ou captura lead no funil v2."""
    client_ip = get_client_ip(request)
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:400]

    service_authed = service_secret_ok(request)
    if getattr(settings, "TURNSTILE_ENABLED", False) and not service_authed:
        if not payload.turnstile_token:
            raise HttpError(400, "Token Turnstile obrigatório.")
        result = verify_turnstile(payload.turnstile_token, remote_ip=client_ip)
        if not result.success:
            raise HttpError(400, "Falha na verificação de segurança (Turnstile).")

    attr_data = payload.attribution.dict(exclude_unset=True) if payload.attribution else {}
    if client_ip and "client_ip" not in attr_data:
        attr_data["client_ip"] = client_ip
    if user_agent and "user_agent" not in attr_data:
        attr_data["user_agent"] = user_agent

    effective_ref = payload.ref or attr_data.get("ref")

    res = lead_iface.check_or_capture(
        cpf=payload.cpf,
        phone=payload.phone,
        external_id=payload.external_id,
        send_otp=payload.send_otp,
        service_authed=service_authed,
        ref=effective_ref,
        attribution=attr_data or None,
    )

    from integrations.posthog import track_funnel_checked

    distinct_id = getattr(res, "external_id", None) or payload.cpf or payload.phone or "anonymous"
    track_funnel_checked(
        distinct_id,
        found=getattr(res, "found", False),
        registered=getattr(res, "registered", True),
        ref=effective_ref,
    )

    return res


add_funnel_login(
    router,
    funnel_roles=FUNNEL_ROLES,
    not_in_funnel_msg="Usuário não faz parte do funil do aluno.",
)
add_auth_refresh(router)
