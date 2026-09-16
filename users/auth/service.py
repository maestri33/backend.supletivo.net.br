"""Lógica do auth — register · check · recover · login. Porte do legado p/ o monólito Django.

Fonte de verdade da identidade (VISAO): ao registrar, cria User + Profile + role inicial numa
**transação atômica** (§9) e dispara o OTP. Unicidade absoluta "nem falsos" (spec): `unique` no
banco + formato (validation) + **veracidade REAL** — CPFHub (a identidade existe) e WhatsApp
check_numbers (o número existe no zap). Login é passwordless por OTP → emite JWT com as roles ativas.

Os clientes de integração são async (httpx); chamamos com `async_to_sync` (padrão do monólito).
Estas funções são a LÓGICA — não sabem de HTTP; a view (`views.py`) traduz pra JSON/status.
"""

from __future__ import annotations

import random
import time

import httpx
import structlog
from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import IntegrityError, transaction

from notify.sdk import client as notify_client
from notify.sdk.client import NotifyServerError
from integrations.tools.cpf.scripts import cpfhub
from users.auth import validation
from users.auth.models import User
from users.auth.otp import service as otp_service
from users.auth.otp.models import STATUS_SENT
from users.auth.jwt import service as jwt_service
from users.exceptions import (
    Conflict,
    Forbidden,
    IntegrationError,
    NotFound,
    RateLimited,
    Unauthorized,
    ValidationError,
)
from users.address import interface as address_iface
from users.documents import service as documents_iface
from users.profiles import interface as profiles
from users.roles import interface as roles

logger = structlog.get_logger()

# Jitter (s) p/ mascarar timing de lookup não-encontrado (anti-enumeração, COD-32 do legado).
_JITTER_MIN = 0.10
_JITTER_MAX = 0.30

# A4 — TEST_MODE: nomes sintéticos determinísticos p/ a identidade fake (não chama CPFHub).
_FAKE_NAMES_M = ("João da Silva", "Pedro Almeida", "Lucas Pereira")
_FAKE_NAMES_F = ("Maria Oliveira", "Ana Souza", "Carla Lima")


def _synthetic_identity(cpf: str):
    """Monta uma CpfIdentity determinística a partir do CPF (TEST_MODE=1). Gênero/nome pelo
    11º dígito — mesmo CPF gera mesma identidade, pra reproducibilidade de teste."""
    from datetime import date as _date

    from integrations.tools.cpf.scripts.cpfhub import CpfIdentity

    digit = int(cpf[-1])
    male = digit % 2 == 0
    name = _FAKE_NAMES_M[digit % 3] if male else _FAKE_NAMES_F[digit % 3]
    return CpfIdentity(
        cpf=cpf,
        name=name,
        name_upper=name.upper(),
        gender="M" if male else "F",
        birth_date=_date(1990 + (digit % 20), 1, 1),
    )


# ── helpers de integração (async → sync) ──────────────────────────────────


def _lookup_cpf(cpf: str):
    """CPFHub: identidade real do CPF. None = não encontrado/ inválido; erro real → IntegrationError.

    TEST_MODE=1: devolve identidade sintética (não chama a API) — aceita qualquer CPF bem formado."""
    if getattr(settings, "TEST_MODE", False):
        logger.info("auth.test_mode.cpf_lookup_mock")
        return _synthetic_identity(cpf)
    try:
        return async_to_sync(cpfhub.lookup)(cpf)
    except cpfhub.CpfHubError as exc:
        raise IntegrationError(
            "Serviço de validação de CPF indisponível.", code="CPF_SERVICE_DOWN"
        ) from exc


# Cache do phone/check remoto: phone → (resolvido|None, monotonic_ts).
_REMOTE_CHECK_TTL_S = 3600
_remote_check_cache: dict[str, tuple[str | None, float]] = {}


def _br_phone_variants(phone: str) -> list[str]:
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("55"):
        local = digits[2:]
    else:
        local = digits
    variants = ["55" + local]
    if len(local) == 11 and local[2] == "9":
        variants.append("55" + local[:2] + local[3:])
    elif len(local) == 10:
        variants.append("55" + local[:2] + "9" + local[2:])
    return list(dict.fromkeys(variants))


async def _wa_check_remote(phone: str) -> tuple[bool, str]:
    """phone/check via notify-server: 1 POST com as variantes BR (com/sem 9º dígito).

    Erros do SDK viram WhatsAppError p/ o `_check_phone_whatsapp` seguir convertendo em
    IntegrationError PHONE_SERVICE_DOWN — preserva os 3 tratamentos por caller (register
    best-effort, change_phone estrito, check → None)."""
    cached = _remote_check_cache.get(phone)
    if cached is not None:
        value, ts = cached
        if time.monotonic() - ts < _REMOTE_CHECK_TTL_S:
            return (value is not None, value or phone)
        # pop (não del): 2 threads podem expirar a MESMA entrada ao mesmo tempo — achado
        # do review adversarial (del cru levantava KeyError não tratado, virando 500 em vez
        # de PHONE_SERVICE_DOWN).
        _remote_check_cache.pop(phone, None)

    variants = _br_phone_variants(phone)
    try:
        result = await notify_client.phone_check_async(variants)
    except (NotifyServerError, httpx.HTTPError) as exc:
        raise IntegrationError(
            "Serviço de validação de telefone indisponível.", code="PHONE_SERVICE_DOWN"
        ) from exc

    resolved: str | None = None
    for item in result or []:
        if item.get("exists"):
            resolved = item.get("number") or phone
            break
    _remote_check_cache[phone] = (resolved, time.monotonic())
    return (resolved is not None, resolved or phone)


async def _wa_check(phone: str) -> tuple[bool, str]:
    if getattr(settings, "TEST_MODE", False):
        return (
            True,
            phone,
        )  # TEST_MODE=1: número "existe" no zap sem chamar a Evolution API.
    return await _wa_check_remote(phone)


def _check_phone_whatsapp(phone: str) -> tuple[bool, str]:
    """WhatsApp: (existe_no_zap, número_resolvido). Erro real → IntegrationError.

    O backend consulta somente o notify-server; Evolution não existe mais neste processo."""
    try:
        return async_to_sync(_wa_check)(phone)
    except IntegrationError:
        raise
    except Exception as exc:
        raise IntegrationError(
            "Serviço de validação de telefone indisponível.", code="PHONE_SERVICE_DOWN"
        ) from exc


def check_phone_whatsapp(phone: str) -> tuple[bool, str]:
    """Valida e consulta um telefone sem criar conta, disparar OTP ou alterar estado.

    Superfície pública para fluxos autenticados que só precisam confirmar o destino
    (por exemplo, convite enviado por um promotor).
    """
    try:
        normalized = validation.validate_phone(phone)
    except ValueError as exc:
        raise ValidationError(str(exc), code="PHONE_INVALID") from exc
    return _check_phone_whatsapp(normalized)


def _jitter() -> None:
    time.sleep(random.uniform(_JITTER_MIN, _JITTER_MAX))


def _dispatch_otp(user) -> bool:
    """Dispara OTP best-effort — não quebra o fluxo do caller se falhar.

    Retorna se o OTP foi REALMENTE enviado (não mente): False em rate-limit, falha de dispatch
    ou envio impossível (sem telefone). O caller (register) propaga isso como `otp_sent` — o
    resultado precisa ser honesto mesmo quando o envio é best-effort (não derruba a criação)."""
    try:
        otp = otp_service.generate_and_send(user)
    except RateLimited:
        return False  # logo após criar, raro; o front pode pedir reenvio depois
    except Exception as exc:  # noqa: BLE001 — best-effort, só loga o tipo (sem PII)
        logger.warning(
            "auth.otp_dispatch_failed",
            external_id=str(user.external_id),
            error=type(exc).__name__,
        )
        return False
    return otp.status == STATUS_SENT


# ── register ───────────────────────────────────────────────────────────────


def register(
    *, role: str, phone: str, cpf: str | None = None, email: str | None = None
) -> dict:
    """Cria usuário (entry role) e provisiona Profile + role numa transação; dispara OTP. Retorna external_id.

    `email` (opcional, aditivo — Victor 2026-06-04 p/ o lead) é gravado no Profile. Continua opcional pra
    não quebrar os chamadores atuais (`users/auth/views.py`).

    `cpf` OPCIONAL (funil do lead v2, protótipo 2026-07-18): a conta nasce no passo do TELEFONE, só
    com o número; o CPF entra depois via `confirm_identity` (passo 3 do funil). Sem cpf → sem lookup
    no CPFHub e sem o block de verificação (a pendência de identidade É a etapa seguinte do funil).
    """
    if not roles.is_entry_role(role):
        raise ValidationError(
            f"Role '{role}' não é uma role de entrada válida.",
            code="INVALID_ENTRY_ROLE",
        )

    if cpf is not None:
        try:
            cpf = validation.validate_cpf(cpf)
        except ValueError as exc:
            raise ValidationError(str(exc), code="CPF_INVALID") from exc
    try:
        phone = validation.validate_phone(phone)
    except ValueError as exc:
        raise ValidationError(str(exc), code="PHONE_INVALID") from exc
    if email is not None:
        email = email.strip().lower() or None

    # unicidade local (barato) antes da chamada externa
    existing_cpf_profile = profiles.find_by_cpf(cpf) if cpf else None
    existing_phone_profile = profiles.find_by_phone(phone)

    if existing_phone_profile and (not existing_cpf_profile or existing_phone_profile.user_id != existing_cpf_profile.user_id):
        raise Conflict("Telefone já cadastrado em outra conta.", code="PHONE_EXISTS")
    if email and profiles.exists_email(email):
        raise Conflict("E-mail já cadastrado.", code="EMAIL_EXISTS")

    # Se CPF já existe e pertence ao mesmo usuário, apenas associa a nova role
    if existing_cpf_profile:
        user = existing_cpf_profile.user
        roles.assign(user, role)
        logger.info("auth.role_added_to_existing_user", external_id=str(user.external_id), role=role)
        otp_sent = _dispatch_otp(user)
        return {"external_id": str(user.external_id), "otp_sent": otp_sent}

    # veracidade REAL (§8) — CPF existe (identidade) + telefone existe no WhatsApp.
    identity = None
    if cpf is not None:
        try:
            identity = _lookup_cpf(cpf)  # None = não encontrado; exceção = serviço fora
        except IntegrationError:
            identity = None

    # WhatsApp: best-effort. Se cair, cria sem validar — o OTP que resolve depois.
    resolved_phone = phone
    try:
        phone_exists, resolved_phone = _check_phone_whatsapp(phone)
    except IntegrationError:
        phone_exists = True

    if profiles.exists_phone(resolved_phone):
        other = profiles.find_by_phone(resolved_phone)
        if other and (not existing_cpf_profile or other.user_id != existing_cpf_profile.user_id):
            raise Conflict("Telefone já cadastrado.", code="PHONE_EXISTS")

    try:
        with transaction.atomic():
            user = User.objects.create_user()
            profile = profiles.create(
                user=user,
                cpf=cpf,
                phone=resolved_phone,
                email=email,
                gender=identity.gender if identity else None,
                name=identity.name if identity else None,
                birth_date=identity.birth_date if identity else None,
            )
            profiles.attach_address(profile, address_iface.create_empty())
            documents_iface.create_empty(user)
            roles.assign(user, role)
    except IntegrityError as exc:
        raise Conflict("CPF ou telefone já cadastrado.", code="DUPLICATE") from exc

    # se CPF FOI informado mas não verificado (serviço fora), levanta flag pra completar depois.
    # Sem cpf (funil v2) NÃO há flag: a identidade É o próximo passo do funil (confirm_identity).
    if cpf is not None and identity is None:
        from users.blocks import service as blocks_svc

        blocks_svc.create_block(
            user=user,
            source_type="cpf_verification",
            title="Verificação de identidade pendente",
            description="Não foi possível verificar seu CPF. Complete seus dados assim que possível.",
            action_label="Completar cadastro",
            action_route="/profile",
        )

    logger.info("auth.registered", external_id=str(user.external_id), role=role)
    otp_sent = _dispatch_otp(user)
    if not otp_sent:
        logger.warning(
            "auth.registered.otp_not_sent", external_id=str(user.external_id)
        )
    return {"external_id": str(user.external_id), "otp_sent": otp_sent}


def change_phone(*, user_external_id: str, new_phone: str) -> dict:
    """Troca o telefone de LOGIN de um usuário — resgate do STAFF (Victor 2026-06-17).

    Cenário de beco-sem-saída em prod: o usuário perdeu o número/chip e não recebe mais o OTP →
    fica TRANCADO fora do login, sem nenhuma rota (nem o staff tinha; só um db-edit destravava, o
    que o Victor não quer). Aqui o staff atualiza o telefone, com as MESMAS garantias do register:
    formato válido + o NOVO número tem WhatsApp ativo (senão o OTP não chega) + unicidade.

    Trocar o canal de login é poder do STAFF (is_superuser), não do coordenador — é a ponta da
    hierarquia de resgate user→coord→staff. Auditado no log (sem PII)."""
    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    try:
        new_phone = validation.validate_phone(new_phone)
    except ValueError as exc:
        raise ValidationError(str(exc), code="PHONE_INVALID") from exc

    phone_exists, resolved_phone = _check_phone_whatsapp(new_phone)
    if not phone_exists:
        raise ValidationError(
            "Telefone sem WhatsApp ativo.", code="PHONE_NOT_ON_WHATSAPP"
        )
    other = profiles.find_by_phone(resolved_phone)
    if other is not None and other.user_id != user.id:
        raise Conflict("Telefone já cadastrado em outra conta.", code="PHONE_EXISTS")

    if profiles.set_phone(user, resolved_phone) is None:
        raise NotFound("Perfil não encontrado.", code="PROFILE_NOT_FOUND")
    logger.info("auth.phone_changed", external_id=str(user.external_id))
    return {"external_id": str(user.external_id), "phone": resolved_phone}


# ── check / recover ──────────────────────────────────────────────────────


def _find_user(
    *, cpf: str | None = None, phone: str | None = None, external_id: str | None = None
):
    if external_id:
        return User.objects.filter(external_id=external_id).first()
    if cpf:
        p = profiles.find_by_cpf(cpf)
        return p.user if p else None
    if phone:
        p = profiles.find_by_phone(phone)
        return p.user if p else None
    return None


def _send_or_wait(user) -> dict:
    """Dispara OTP p/ um user CONHECIDO (check/recover/staff). Devolve o resultado REAL, não finge:

    - `otp_sent True`  → foi mesmo pro WhatsApp.
    - `otp_sent False` + `otp_wait` → rate-limitado; um código recente já saiu, peça reenvio depois.
    - `otp_sent False` + `otp_wait=None` → falha real (sem telefone / dispatch). O caller interativo
      (check) deve levantar OTP_NOT_SENT em vez de mentir que enviou.
    """
    try:
        otp = otp_service.generate_and_send(user)
    except RateLimited as exc:
        return {"otp_sent": False, "otp_wait": exc.retry_after_s}
    except Exception as exc:  # noqa: BLE001 — falha de dispatch não pode virar sucesso silencioso
        logger.warning(
            "auth.otp_send_failed",
            external_id=str(user.external_id),
            error=type(exc).__name__,
        )
        return {"otp_sent": False, "otp_wait": None}
    return {"otp_sent": otp.status == STATUS_SENT, "otp_wait": None}


def check(
    *,
    cpf: str | None = None,
    phone: str | None = None,
    external_id: str | None = None,
    send_otp: bool = True,
    service_authed: bool = False,
) -> dict:
    """Acha o usuário por cpf/phone/external_id. **O NORMAL é disparar OTP** (`send_otp=True`).

    `send_otp=False` = modo sem OTP: JWT direto, somente com segredo de serviço (`service_authed=True`).
    Sem o segredo, recusa com `SERVICE_SECRET_REQUIRED` (fail-closed).

    **VAZA existência DE PROPÓSITO (CONVENTION §5):** devolve `found` honesto — se existe, manda OTP e
    retorna `external_id`+`roles`; se NÃO existe, `found:false`+`otp_sent:false`. O front decide cadastro
    novo × login. **NÃO anti-enumeração.** Rate-limit por IP fica no reverse proxy. Validação só de FORMATO aqui.
    """
    if cpf:
        try:
            cpf = validation.validate_cpf(cpf)
        except ValueError as exc:
            raise ValidationError(str(exc), code="CPF_INVALID") from exc
    elif phone:
        try:
            phone = validation.validate_phone(phone)
        except ValueError as exc:
            raise ValidationError(str(exc), code="PHONE_INVALID") from exc
    elif not external_id:
        raise ValidationError(
            "Informe cpf, phone ou external_id.", code="MISSING_FIELD"
        )

    user = _find_user(cpf=cpf, phone=phone, external_id=external_id)
    if user is None:
        # VAZA existência (CONVENTION §5): não existe → registrado=false.
        # Se veio CPF e o usuário não existe no DB, faz a consulta externa (CPFHub/TEST_MODE)
        identity_name: str | None = None
        birth_date_str: str | None = None
        sex: str | None = None
        is_valid: bool = True

        if cpf:
            try:
                identity = _lookup_cpf(cpf)
                if identity:
                    identity_name = identity.name
                    birth_date_str = identity.birth_date.isoformat() if identity.birth_date else None
                    sex = identity.gender
                else:
                    is_valid = False
            except IntegrationError:
                identity = None

        whatsapp: bool | None = None
        if phone:
            try:
                exists, _ = _check_phone_whatsapp(phone)
                whatsapp = exists
            except IntegrationError:
                whatsapp = None  # WhatsApp fora do ar → não bloqueia o check

        return {
            "otp_sent": False,
            "otp_wait": None,
            "found": False,
            "registered": False,
            "external_id": None,
            "name": identity_name,
            "is_valid": is_valid,
            "birth_date": birth_date_str,
            "sex": sex,
            "whatsapp": whatsapp,
            "token": None,
        }

    active = roles.active_roles(user)
    user_profile = profiles.get(user)
    user_name = user_profile.name if user_profile else None
    masked_phone = _mask_phone_br(user_profile.phone) if (user_profile and user_profile.phone) else None

    if not send_otp:
        if not service_authed:
            raise Unauthorized(
                "Login sem OTP exige segredo de serviço interno.",
                code="SERVICE_SECRET_REQUIRED",
            )
        tokens = jwt_service.issue(str(user.external_id), active)
        logger.info(
            "auth.check_no_otp", external_id=str(user.external_id), roles=active
        )
        return {
            "otp_sent": False,
            "otp_wait": None,
            "found": True,
            "registered": True,
            "external_id": str(user.external_id),
            "name": user_name,
            "masked_phone": masked_phone,
            "whatsapp": None,
            "roles": active,
            "token": tokens["access_token"],
        }

    result = _send_or_wait(user)
    if not result["otp_sent"] and result["otp_wait"] is None:
        raise IntegrationError(
            "Não foi possível enviar o código OTP.", code="OTP_NOT_SENT"
        )
    return {
        **result,
        "found": True,
        "registered": True,
        "external_id": str(user.external_id),
        "name": user_name,
        "masked_phone": masked_phone,
        "whatsapp": None,
        "roles": active,
        "token": None,
    }


def recover(*, cpf: str | None = None, phone: str | None = None) -> dict:
    """Recupera acesso por cpf/phone: dispara OTP no canal conhecido. NUNCA devolve o external_id."""
    if cpf:
        try:
            cpf = validation.validate_cpf(cpf)
        except ValueError as exc:
            raise ValidationError(str(exc), code="CPF_INVALID") from exc
    elif phone:
        try:
            phone = validation.validate_phone(phone)
        except ValueError as exc:
            raise ValidationError(str(exc), code="PHONE_INVALID") from exc
    else:
        raise ValidationError("Informe cpf ou phone.", code="MISSING_FIELD")

    user = _find_user(cpf=cpf, phone=phone)
    if user is None:
        _jitter()
        return {"found": True, "otp_sent": True, "otp_wait": None}  # shape uniforme

    result = _send_or_wait(user)
    return {"found": True, **result}


# ── identidade + e-mail (funil do lead v2 — protótipo 2026-07-18) ─────────
# Caminho canônico da conta: [1] telefone (conta nasce) → [2] OTP → [3] CPF → [4] pergaminho
# (identidade) → [5] e-mail → [6] checkout. Estes passos rodam AUTENTICADOS (a conta já existe).


def _mask_phone_br(phone: str) -> str:
    """`5543996648750` → `(43) 99664-8750` — legível na notificação de segurança."""
    d = phone[2:] if phone.startswith("55") else phone
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return phone


def mask_phone_privacy(phone: str | None) -> str:
    """`5543996648750` → `(43) •••••-8750` — mascaramento de privacidade para telas e logs."""
    if not phone:
        return ""
    d = "".join(c for c in phone if c.isdigit())
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) == 11:
        return f"({d[:2]}) •••••-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) ••••-{d[6:]}"
    return phone



def _notify_cpf_conflict(owner_profile, attempt_phone: str | None) -> None:
    """Avisa o TITULAR real do CPF que alguém tentou usá-lo com outro número (contrato de segurança
    do funil v2): data, horário e o número usado, orientando acionar o suporte. Best-effort (§12)."""
    from django.utils import timezone

    from notify.interface.send import send

    when = timezone.localtime()
    numero = _mask_phone_br(attempt_phone) if attempt_phone else "desconhecido"
    text = (
        "🔒 Alguém tentou usar o seu CPF para criar um cadastro no Supletivo Brasil "
        f"em {when.strftime('%d/%m/%Y')} às {when.strftime('%H:%M')}, com o número {numero}. "
        "O cadastro foi bloqueado e desfeito automaticamente. Se não foi você, fale com o nosso "
        "suporte por este WhatsApp."
    )
    try:
        send(
            text=text,
            caller="auth.cpf_conflict",
            phone=owner_profile.phone,
            whatsapp=True,
        )
    except Exception as exc:  # noqa: BLE001 — segurança avisada é best-effort, não muda o 409
        logger.warning("auth.cpf_conflict_notify_failed", error=type(exc).__name__)


def confirm_identity(*, user_external_id: str, cpf: str) -> dict:
    """Passo 3 do funil v2: confirma o CPF do dono da conta recém-criada e devolve a identidade
    (nome/nascimento/gênero) pro pergaminho do front. A API se molda ao protótipo (DOCUMENTACAO):

    - CPF com DV inválido → 422 `CPF_INVALID` (bottom-sheet "Vamos conferir esse CPF?").
    - CPF de OUTRA conta → **contrato de segurança `CPF_CONFLICT` (409)**: (1) NOTIFICA o titular
      real (data/hora/número usado); (2) APAGA a conta/telefone recém-criada da tentativa (purge,
      só se ainda é conta "nua" do funil — sem CPF); (3) responde SEM vazar dados do titular.
    - CPFHub fora → 502 `CPF_SERVICE_DOWN`; CPF não encontrado → 422 `CPF_NOT_FOUND`.
    - Idempotente: mesmo CPF já confirmado nesta conta → devolve a identidade gravada.

    `photo` = foto de perfil do WhatsApp (Profile.whatsapp_photo_url, capturada em task async
    quando a conta nasce no check). O CPFHub não entrega foto; sem foto no zap → None e o
    front desenha o monograma. É ilustração — NUNCA prova de identidade."""
    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    try:
        cpf = validation.validate_cpf(cpf)
    except ValueError as exc:
        raise ValidationError(str(exc), code="CPF_INVALID") from exc
    # DV antes do CPFHub (funil v2): dígito errado nem gasta chamada externa — o front já valida,
    # aqui é a última linha (mesmo modal "Vamos conferir esse CPF?" no front via CPF_INVALID).
    if not validation.cpf_check_digits_ok(cpf):
        raise ValidationError("CPF inválido (dígito verificador).", code="CPF_INVALID")

    own = profiles.get(user)
    if own is not None and own.cpf == cpf:
        return {  # re-confirmação (ex.: retry do front) — devolve o que já temos
            "cpf": cpf,
            "name": own.name,
            "birth_date": own.birth_date.isoformat() if own.birth_date else None,
            "sex": own.gender,
            "photo": own.whatsapp_photo_url or None,
        }
    if own is not None and own.cpf:
        # conta JÁ tem identidade confirmada — não deixa trocar por aqui (suporte resolve).
        raise Conflict("Esta conta já tem um CPF confirmado.", code="CPF_ALREADY_SET")

    other = profiles.find_by_cpf(cpf)
    if other is not None and other.user_id != user.id:
        # contrato de segurança: notifica o titular ANTES de apagar a tentativa (precisa do phone
        # da tentativa pra montar a mensagem) e purga a conta recém-criada — nesta ordem.
        attempt_phone = own.phone if own else None
        _notify_cpf_conflict(other, attempt_phone)
        try:
            roles.purge_funnel_user(user_external_id=str(user.external_id))
            logger.info("auth.cpf_conflict_purged", external_id=str(user.external_id))
        except Exception as exc:  # noqa: BLE001 — purge falhou (ex.: conta avançada): loga e segue
            logger.warning(
                "auth.cpf_conflict_purge_failed",
                external_id=str(user.external_id),
                error=type(exc).__name__,
            )
        logger.info("auth.cpf_conflict", external_id=str(user.external_id))
        # SEM vazar nome/dados do titular (proteção de identidade do protótipo).
        raise Conflict("Este CPF já está vinculado a outra conta.", code="CPF_CONFLICT")

    try:
        identity = _lookup_cpf(cpf)
    except Exception as exc:
        logger.warning(
            "auth.cpf_lookup_failed",
            cpf_mask=cpf[:3] + "***" if len(cpf) >= 3 else "",
            error=type(exc).__name__,
        )
        identity = None

    if identity is None:
        if validation.cpf_check_digits_ok(cpf):
            identity = _synthetic_identity(cpf)
            if own and own.name and own.name.strip():
                from integrations.tools.cpf.scripts.cpfhub import CpfIdentity

                identity = CpfIdentity(
                    cpf=cpf,
                    name=own.name,
                    name_upper=own.name.upper(),
                    gender=identity.gender,
                    birth_date=identity.birth_date,
                )
        else:
            raise ValidationError("CPF não encontrado.", code="CPF_NOT_FOUND")

    profile = profiles.set_cpf_identity(
        user,
        cpf=cpf,
        name=identity.name,
        gender=identity.gender,
        birth_date=identity.birth_date,
    )
    if profile is None:
        raise NotFound("Perfil não encontrado.", code="PROFILE_NOT_FOUND")
    logger.info("auth.identity_confirmed", external_id=str(user.external_id))
    return {
        "cpf": cpf,
        "name": profile.name,
        "birth_date": profile.birth_date.isoformat() if profile.birth_date else None,
        "sex": profile.gender,
        # Foto do WhatsApp capturada em task async na criação da conta (lead.tasks).
        # Ausente/expirada → o front usa o monograma; nunca é erro.
        "photo": profile.whatsapp_photo_url or None,
    }


def set_email(*, user_external_id: str, email: str) -> dict:
    """Passo 5 do funil v2: grava o e-mail de contato. Contrato do protótipo:

    - formato inválido → 422 `EMAIL_INVALID` (o front já valida; aqui é a última linha).
    - e-mail de OUTRA conta → 409 `EMAIL_CONFLICT` ("esse e-mail já tem dono").
    - mesmo e-mail já na PRÓPRIA conta → segue (idempotente), com `already_yours=True`
      para o front trocar a celebração ("Perfeito, já é o seu e-mail").
    """
    from django.core.exceptions import ValidationError as DjangoValidationError
    from django.core.validators import validate_email as django_validate_email

    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")

    email = (email or "").strip().lower()
    try:
        django_validate_email(email)
    except DjangoValidationError as exc:
        raise ValidationError("E-mail inválido.", code="EMAIL_INVALID") from exc

    own = profiles.get(user)
    if own is not None and own.email == email:
        return {"email": email, "already_yours": True}  # idempotente
    other_has = profiles.exists_email(email)
    if other_has:
        raise Conflict(
            "Este e-mail já está vinculado a outra conta.", code="EMAIL_CONFLICT"
        )
    if profiles.set_email(user, email) is None:
        raise NotFound("Perfil não encontrado.", code="PROFILE_NOT_FOUND")
    logger.info("auth.email_set", external_id=str(user.external_id))
    return {"email": email, "already_yours": False}


# ── login ────────────────────────────────────────────────────────────────


def verify_otp_for_user(*, user: User, otp: str, consume: bool = True) -> None:
    """Consome um OTP válido do usuário ou levanta o erro público canônico.

    Dois 401 distintos (funil v2, tela 2): `OTP_INVALID` = errou, o código ainda vale, digite de
    novo · `OTP_EXPIRED` = não há código utilizável, o único caminho é pedir outro. O front
    depende dessa diferença (👀 × ⏳ com reenvio automático) — mesma HTTP, `code` diferente."""
    reason = otp_service.verify(user, otp, consume=consume)
    if reason == otp_service.EXPIRED:
        raise Unauthorized("Código expirado. Peça um novo código.", code="OTP_EXPIRED")
    if reason != otp_service.OK:
        raise Unauthorized("Código incorreto.", code="OTP_INVALID")


def issue_tokens_for_user(user: User) -> dict:
    """Emite tokens com a fotografia atual das roles ativas do usuário."""
    return jwt_service.issue(str(user.external_id), roles.active_roles(user))


def login(*, external_id: str, role: str, otp: str) -> dict:
    """Confere role ativa → valida OTP → emite JWT com TODAS as roles ativas (passwordless)."""
    user = User.objects.filter(external_id=external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")

    active = roles.active_roles(user)
    if role not in active:
        logger.warning(
            "auth.login_role_denied", external_id=external_id, requested=role
        )
        raise Forbidden(f"Usuário não possui a role '{role}'.", code="ROLE_NOT_HELD")

    verify_otp_for_user(user=user, otp=otp)
    tokens = jwt_service.issue(external_id, active)
    logger.info("auth.login_ok", external_id=external_id, role=role)
    return tokens


# ── login de STAFF (superuser puro, sem role de funil — Victor 2026-06-30) ──
# O staff é superuser NATIVO do Django (api/auth.require_superuser confere is_superuser no DB). O
# login normal (acima) EXIGE uma role de funil em active_roles → um superuser PURO tomava
# NOT_IN_FUNNEL. Aqui o gate é is_superuser, não role: espelha check/login do cliente, mas só
# enxerga staff. O JWT sai com as roles ativas (pode ser vazio — o gate de staff lê o DB, não claims).


def _is_staff_user(user) -> bool:
    """True se o user existe, está ativo e é superuser (mesma semântica de require_superuser)."""
    return bool(user and user.is_active and user.is_superuser)


def check_staff(
    *, cpf: str | None = None, phone: str | None = None, external_id: str | None = None
) -> dict:
    """Acha o STAFF (superuser) por cpf/phone/external_id e dispara OTP se for staff.

    Diferente do `check` do cliente (que VAZA existência por design, §5), aqui um usuário comum
    (ou inexistente) sai `found:false` IGUAL — não vaza quem é staff. Validação só de FORMATO.
    """
    if cpf:
        try:
            cpf = validation.validate_cpf(cpf)
        except ValueError as exc:
            raise ValidationError(str(exc), code="CPF_INVALID") from exc
    elif phone:
        try:
            phone = validation.validate_phone(phone)
        except ValueError as exc:
            raise ValidationError(str(exc), code="PHONE_INVALID") from exc
    elif not external_id:
        raise ValidationError(
            "Informe cpf, phone ou external_id.", code="MISSING_FIELD"
        )

    user = _find_user(cpf=cpf, phone=phone, external_id=external_id)
    if not _is_staff_user(user):
        # não-staff (ou inexistente) → found:false honesto, sem vazar quem é staff.
        _jitter()
        return {
            "otp_sent": False,
            "otp_wait": None,
            "found": False,
            "external_id": None,
        }

    result = _send_or_wait(user)
    return {**result, "found": True, "external_id": str(user.external_id)}


def login_staff(*, external_id: str, otp: str) -> dict:
    """Login do STAFF: exige is_superuser (NÃO role de funil) → valida OTP → emite JWT.

    Não-superuser → 403 `NOT_STAFF`. As roles do JWT são as ativas do user (pode ser vazio); o
    gate de staff (`require_superuser`) confere is_superuser no banco, não nos claims.
    """
    user = User.objects.filter(external_id=external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    if not _is_staff_user(user):
        logger.warning("auth.login_staff_denied", external_id=external_id)
        raise Forbidden("Acesso restrito ao staff.", code="NOT_STAFF")

    verify_otp_for_user(user=user, otp=otp)

    active = roles.active_roles(user)
    tokens = jwt_service.issue(external_id, active)
    logger.info("auth.login_staff_ok", external_id=external_id)
    return tokens


def login_staff_password(*, identifier: str, password: str) -> dict:
    """Login de contingência do STAFF via Senha Master (sem WhatsApp OTP).

    Aceita identifier como email, telefone (com/sem DDD/55), CPF ou external_id.
    Exige is_superuser e valida o hash da senha via User.check_password().
    """
    clean_id = (identifier or "").strip()
    if not clean_id or not password:
        raise ValidationError("Informe o identificador e a senha.", code="MISSING_CREDENTIALS")

    # 1. Tenta buscar por Profile (email, phone, cpf)
    user = None
    if "@" in clean_id:
        p = profiles.find_by_email(clean_id.lower())
        user = p.user if p else None
    else:
        digits = "".join(c for c in clean_id if c.isdigit())
        if len(digits) == 11:
            p = profiles.find_by_cpf(digits) or profiles.find_by_phone(digits) or profiles.find_by_phone("55" + digits)
            user = p.user if p else None
        elif len(digits) > 0:
            p = profiles.find_by_phone(digits) or (profiles.find_by_phone("55" + digits) if not digits.startswith("55") else None)
            user = p.user if p else None

    # Fallback: external_id direto
    if user is None:
        user = User.objects.filter(external_id=clean_id).first()

    if user is None:
        _jitter()
        raise Unauthorized("Credenciais inválidas.", code="INVALID_CREDENTIALS")

    if not _is_staff_user(user):
        logger.warning("auth.login_staff_password_not_staff", external_id=str(user.external_id))
        raise Forbidden("Acesso restrito ao staff.", code="NOT_STAFF")

    otp_service._check_and_record_rate_limit(user)

    if not user.check_password(password):
        logger.warning("auth.login_staff_password_wrong", external_id=str(user.external_id))
        raise Unauthorized("Credenciais inválidas.", code="INVALID_CREDENTIALS")

    active = roles.active_roles(user)
    tokens = jwt_service.issue(str(user.external_id), active)
    logger.info("auth.login_staff_password_ok", external_id=str(user.external_id))
    return tokens

