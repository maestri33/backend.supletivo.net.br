"""Router de autenticação do grupo Clients (Funil do Aluno)."""

from __future__ import annotations

from ninja import Router
from ninja.responses import Status

from api.base import add_auth_refresh, add_funnel_login
from api.clients.schemas import LeadCreateIn, LeadOut
from api.schemas.auth import CheckIn, CheckOut
from core.webhook_auth import service_secret_ok
from users.roles.lead import service as lead_iface

router = Router(tags=["auth"])

FUNNEL_ROLES = ("veteran", "student", "enrollment", "lead")


@router.post("/register", response={201: LeadOut}, auth=None, summary="Cadastro inicial do lead")
def register(request, payload: LeadCreateIn):
    """Cadastro do cliente: cria lead + checkout e devolve o pagamento."""
    result = lead_iface.create_lead(
        cpf=payload.cpf,
        phone=payload.phone,
        email=payload.email,
        payment_method=payload.payment_method,
        ref=payload.ref,
    )
    return Status(201, result)


@router.post("/check", response=CheckOut, auth=None, summary="Verificação e disparo de OTP ou captura")
def check(request, payload: CheckIn):
    """Check de telefone/CPF: dispara OTP ou captura lead no funil v2."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    client_ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    user_agent = request.META.get("HTTP_USER_AGENT", "")[:400]

    attr_data = payload.attribution.dict(exclude_unset=True) if payload.attribution else {}
    if client_ip and "client_ip" not in attr_data:
        attr_data["client_ip"] = client_ip
    if user_agent and "user_agent" not in attr_data:
        attr_data["user_agent"] = user_agent

    effective_ref = payload.ref or attr_data.get("ref")

    return lead_iface.check_or_capture(
        cpf=payload.cpf,
        phone=payload.phone,
        external_id=payload.external_id,
        send_otp=payload.send_otp,
        service_authed=service_secret_ok(request),
        ref=effective_ref,
        attribution=attr_data or None,
    )


add_funnel_login(
    router,
    funnel_roles=FUNNEL_ROLES,
    not_in_funnel_msg="Usuário não faz parte do funil do aluno.",
)
add_auth_refresh(router)
