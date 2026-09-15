from __future__ import annotations

import structlog
from django.conf import settings
from django.db import transaction

from hub import interface as hub_iface
from users.auth import service as auth_iface
from users.auth.models import User
from users.profiles import interface as profiles
from users.exceptions import DomainError
from users.roles import interface as roles
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import (
    CandidateError,
    _S,
    _COLLABORATOR_ROLES,
    logger,
    get_for_user_external_id,
)

def _resolve_capture_hub(hub):
    hub_obj, ref_reason = hub_iface.resolve_capture_hub(hub)
    if hub_obj is None:
        raise CandidateError(
            "Nenhum polo disponível para o cadastro.", code="NO_HUB"
        )  # nem o polo padrão existe (seed_defaults não rodou)
    if ref_reason.endswith("_default") and ref_reason != "no_ref_default":
        # veio um ref mas não resolveu pro polo dele (inválido / promotor sem hub / polo sem coord)
        # → caiu no padrão. Loga pro staff monitorar links de captação ruins.
        logger.warning(
            "candidate.ref_fallback",
            ref=hub,
            reason=ref_reason,
            hub=str(hub_obj.external_id),
        )
    return hub_obj, ref_reason


def check_or_capture(
    *,
    cpf: str | None = None,
    phone: str | None = None,
    external_id: str | None = None,
    send_otp: bool = True,
    service_authed: bool = False,
    hub: str | None = None,
) -> dict:
    """`POST collaborators/auth/check`: check normal E captura automática de promotor (candidato).

    - Usuário EXISTE → comporta igual ao `auth.check` (OTP + found + roles honestos).
    - NÃO existe, veio `phone` e o WhatsApp CONFIRMOU o número → **cria a conta na hora**
      (User + Profile(phone) + role candidate + Candidate(STARTED) ligado ao polo/hub) e dispara o OTP —
      resposta ganha `created: true` + `external_id` (o front segue direto pro OTP).
    - NÃO existe e WhatsApp negou (`whatsapp:false`) ou está fora (`whatsapp:null`) → NÃO cria;
      o front avisa número inválido / não confirmado.
    """
    result = auth_iface.check(
        cpf=cpf,
        phone=phone,
        external_id=external_id,
        send_otp=send_otp,
        service_authed=service_authed,
    )
    if result["found"] or not phone or not send_otp:
        return {**result, "created": False}
    if result.get("whatsapp") is not True:
        return {**result, "created": False}

    try:
        hub_obj, ref_reason = _resolve_capture_hub(hub)
        reg = auth_iface.register(
            role="candidate", phone=phone
        )
        user = User.objects.get(external_id=reg["external_id"])
        candidate = Candidate.objects.create(
            user=user, hub=hub_obj, status=_S.STARTED
        )
    except DomainError as exc:
        logger.warning("candidate.capture_on_check_failed", code=exc.code, error=exc.detail)
        return {**result, "created": False}

    logger.info(
        "candidate.captured_on_check",
        external_id=str(candidate.external_id),
        hub=str(hub_obj.external_id),
        ref_reason=ref_reason,
    )
    return {
        "found": False,
        "created": True,
        "external_id": reg["external_id"],
        "otp_sent": reg["otp_sent"],
        "otp_wait": None,
        "whatsapp": True,
        "roles": ["candidate"],
        "token": None,
    }


def create_candidate(*, cpf: str, phone: str, email: str, hub=None) -> dict:
    """Cria o candidato: register(role candidate) + Candidate(STARTED) ligado a um hub.

    `hub` = external_id do polo (landing `?ref=` do coordenador); sem hub → hub padrão (regra dura:
    candidato↔hub).
    """
    hub_obj, ref_reason = _resolve_capture_hub(hub)

    reg = auth_iface.register(role="candidate", phone=phone, cpf=cpf, email=email)
    user = User.objects.get(external_id=reg["external_id"])
    candidate = Candidate.objects.create(user=user, hub=hub_obj, status=_S.STARTED)
    logger.info(
        "candidate.created",
        external_id=str(candidate.external_id),
        hub=str(hub_obj.external_id),
        ref_reason=ref_reason,
    )
    return {
        "external_id": str(candidate.external_id),
        # external_id do USER — é o que o /auth/login consome (plan/15 A4).
        "user_external_id": reg["external_id"],
        "status": candidate.status,
    }


def check_or_capture_candidate(
    *,
    cpf: str | None = None,
    phone: str | None = None,
    external_id: str | None = None,
    send_otp: bool = True,
    service_authed: bool = False,
    hub=None,
) -> dict:
    """Check de telefone/CPF para o funil do colaborador (/group).

    - Se usuário já existe: retorna check padrão (OTP disparado se send_otp=True).
    - Se NÃO existe e veio phone com whatsapp válido: registra usuário com role 'candidate',
      cria Candidate(STARTED) ligado ao polo (hub) e dispara OTP.
    """
    result = auth_iface.check(
        cpf=cpf,
        phone=phone,
        external_id=external_id,
        send_otp=send_otp,
        service_authed=service_authed,
    )
    if result["found"] or not phone or not send_otp:
        return {**result, "created": False}
    if result.get("whatsapp") is not True:
        return {**result, "created": False}

    try:
        hub_obj, ref_reason = _resolve_capture_hub(hub)
        reg = auth_iface.register(role="candidate", phone=phone, cpf=cpf)
        user = User.objects.get(external_id=reg["external_id"])
        candidate = Candidate.objects.create(user=user, hub=hub_obj, status=_S.STARTED)
        logger.info(
            "candidate.capture_on_check",
            external_id=str(candidate.external_id),
            hub=str(hub_obj.external_id),
            ref_reason=ref_reason,
        )
        return {
            **result,
            "found": True,
            "created": True,
            "external_id": str(user.external_id),
            "otp_sent": reg.get("otp_sent", True),
            "roles": ["candidate"],
        }
    except DomainError as exc:
        logger.warning("candidate.capture_on_check_failed", code=exc.code, error=exc.detail)
        return {**result, "created": False}
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.capture_on_check_failed", error=str(exc))
        return {**result, "created": False}


def _ensure_candidate_inner(user, hub) -> None:
    """Regra compartilhada (join/web): garante role `candidate` + linha `Candidate` pro user.

    O CHAMADOR já provou posse (OTP no `join_candidate`; sessão web autenticada no
    `ensure_candidate`) e já segura a transação/lock. Preserva roles existentes."""
    active = roles.active_roles(user)

    if not any(role in active for role in _COLLABORATOR_ROLES):
        profile = profiles.get(user)
        required = {
            "cpf": getattr(profile, "cpf", None),
            "email": getattr(profile, "email", None),
            "name": getattr(profile, "name", None),
            "birth_date": getattr(profile, "birth_date", None),
        }
        missing_fields = [name for name, value in required.items() if not value]
        if missing_fields:
            raise CandidateError(
                "Seu cadastro anterior precisa ser completado antes de entrar no programa de promotores.",
                code="JOIN_PROFILE_INCOMPLETE",
                extra={"missing_fields": missing_fields},
            )

        hub_obj, ref_reason = _resolve_capture_hub(hub)
        candidate = Candidate.objects.filter(user=user).first()
        if candidate is None:
            candidate = Candidate.objects.create(
                user=user, hub=hub_obj, status=_S.STARTED
            )
        roles.assign(user, "candidate")
        logger.info(
            "candidate.joined_existing_user",
            external_id=str(candidate.external_id),
            hub=str(hub_obj.external_id),
            ref_reason=ref_reason,
            previous_roles=active,
        )
    elif "candidate" in active and not Candidate.objects.filter(user=user).exists():
        hub_obj, ref_reason = _resolve_capture_hub(hub)
        candidate = Candidate.objects.create(user=user, hub=hub_obj, status=_S.STARTED)
        logger.warning(
            "candidate.repaired_missing_row",
            external_id=str(candidate.external_id),
            hub=str(hub_obj.external_id),
            ref_reason=ref_reason,
        )


def join_candidate(*, user_external_id: str, otp: str, hub=None) -> dict:
    """Adere uma identidade existente ao funil do colaborador após provar posse via OTP.

    Preserva os papéis já usados no Supletivo e só cria `candidate` depois da prova de posse do
    WhatsApp.
    """
    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")

    # Duas fases de propósito (E2E 2026-07-29):
    # 1) CONFERE fora da transação — assim a tentativa ERRADA persiste o `attempts += 1`. Antes,
    #    a exceção dentro do atomic fazia rollback do contador e o código de 6 dígitos ficava
    #    aberto a brute-force (3 erros e o contador seguia em 0).
    # 2) CONSOME dentro da transação — se o passo seguinte falhar (ex.: NO_HUB), o código CERTO
    #    não é queimado e a pessoa tenta de novo, que é o contrato dos testes de join.
    auth_iface.verify_otp_for_user(user=user, otp=otp, consume=False)

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        auth_iface.verify_otp_for_user(user=user, otp=otp)
        _ensure_candidate_inner(user, hub)
        return auth_iface.issue_tokens_for_user(user)


def ensure_candidate(*, user_external_id: str, hub=None) -> None:
    """Funil WEB (sessão Django server-side, posse já provada no login por OTP): garante a role
    `candidate` + a linha `Candidate` sem consumir OTP — mesma regra do `join_candidate`.
    Idempotente; `JOIN_PROFILE_INCOMPLETE` se o perfil de outro funil ainda não tem identidade."""
    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        _ensure_candidate_inner(user, hub)

