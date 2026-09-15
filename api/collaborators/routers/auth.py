"""Router de autenticação do grupo Collaborators (Funil do Promotor)."""

from __future__ import annotations

from ninja import Router
from ninja.responses import Status

from api.base import add_auth_refresh, add_funnel_login
from api.collaborators.schemas import CandidateCreateIn, CandidateJoinIn, CandidateOut
from api.schemas.auth import CheckIn, CheckOut, TokenOut
from core.webhook_auth import service_secret_ok
from users.auth import service as auth_iface
from users.roles.candidate import service as candidate_iface

router = Router(tags=["auth"])

FUNNEL_ROLES = ("coordinator", "promoter", "training", "candidate")


@router.post("/register", response={201: CandidateOut}, auth=None, summary="Cadastro do candidato")
def register(request, payload: CandidateCreateIn):
    """Cadastro do candidato: cria o user + Candidate ligado a um polo."""
    return Status(
        201,
        candidate_iface.create_candidate(
            cpf=payload.cpf, phone=payload.phone, email=payload.email, hub=payload.hub
        ),
    )


@router.post("/check", response=CheckOut, auth=None, summary="Verificação de conta / disparo de OTP ou cadastro de candidato")
def check(request, payload: CheckIn):
    """Check de telefone/CPF: dispara OTP ou captura promotor (candidato) no funil de entrada."""
    return candidate_iface.check_or_capture(
        cpf=payload.cpf,
        phone=payload.phone,
        external_id=payload.external_id,
        send_otp=payload.send_otp,
        service_authed=service_secret_ok(request),
        hub=payload.ref,
    )


@router.post("/join", response=TokenOut, auth=None, summary="Ativação de promotor em conta existente")
def join(request, payload: CandidateJoinIn):
    """Ativa o acesso de promotor para uma conta existente após validar o OTP."""
    return candidate_iface.join_candidate(
        user_external_id=payload.external_id,
        otp=payload.otp,
        hub=payload.hub,
    )


add_funnel_login(
    router,
    funnel_roles=FUNNEL_ROLES,
    not_in_funnel_msg="Usuário não faz parte do funil do colaborador.",
)
add_auth_refresh(router)
