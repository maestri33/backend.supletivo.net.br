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
    return lead_iface.check_or_capture(
        cpf=payload.cpf,
        phone=payload.phone,
        external_id=payload.external_id,
        send_otp=payload.send_otp,
        service_authed=service_secret_ok(request),
        ref=payload.ref,
    )


add_funnel_login(
    router,
    funnel_roles=FUNNEL_ROLES,
    not_in_funnel_msg="Usuário não faz parte do funil do aluno.",
)
add_auth_refresh(router)
