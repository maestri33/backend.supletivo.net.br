"""OTP — gera código, envia por WhatsApp (via notify), valida. Porte do legado p/ Django.

Decisões (Portão 1/2 2026-06-01): código numérico (6 díg default), **hash SHA256** (plaintext nunca
persiste), TTL/tentativas/rate-limit no `.env`, rate-limit em **DB** (`OtpRateLimit`) já que não há
Redis. Envio pelo despachante puro do `notify` (`whatsapp=True`), com o `phone` vindo do Profile.
O OTP É o mecanismo de login (passwordless).
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

import structlog
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from users.auth.otp.models import (
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_GENERATED,
    STATUS_SENT,
    STATUS_VERIFIED,
    OtpCode,
    OtpRateLimit,
)
from users.exceptions import RateLimited

logger = structlog.get_logger()

_TEMPLATE_PATH = Path(__file__).parent / "otp.md"

# Desfechos de `verify` — o front do funil escolhe a tela por eles (ver docstring de verify).
OK = "ok"
INVALID = "invalid"
EXPIRED = "expired"


def _generate_code() -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(settings.OTP_NUM_DIGITS))


def _hash_code(code: str) -> str:
    """SHA256 — o código em texto plano NUNCA é persistido."""
    return hashlib.sha256(code.encode()).hexdigest()


def _render(code: str, ttl_minutos: int) -> str:
    raw = _TEMPLATE_PATH.read_text(encoding="utf-8")
    footer = settings.OTP_FOOTER
    rodape = f"\n\n{footer}" if footer else ""
    return (
        raw.replace("{{codigo}}", code)
        .replace("{{ttl_minutos}}", str(ttl_minutos))
        .replace("{{rodape}}", rodape)
        .rstrip()
        + "\n"
    )


def _check_and_record_rate_limit(user) -> None:
    """Janela curta (1 a cada WINDOW_S) + janela horária (máx HOURLY_MAX/h). Porte do legado.

    Checa e grava na mesma transação. Bloqueado => levanta RateLimited (vira 429 com retry_after).
    """
    now = timezone.now()
    window_s = settings.OTP_RATELIMIT_WINDOW_S
    hourly_max = settings.OTP_RATELIMIT_HOURLY_MAX

    try:
        with transaction.atomic():
            rl = OtpRateLimit.objects.select_for_update().filter(user=user).first()

            if rl is not None:
                elapsed = (now - rl.last_created_at).total_seconds()
                if elapsed < window_s:
                    retry = max(1, int(window_s - elapsed))
                    logger.info("otp.rate_limit.window_blocked", retry_after_s=retry)
                    raise RateLimited(
                        f"Aguarde {retry}s antes de pedir outro código.",
                        retry_after_s=retry,
                    )

                hourly_elapsed = (now - rl.hourly_window_start).total_seconds()
                if hourly_elapsed < 3600:
                    if rl.hourly_count >= hourly_max:
                        retry = max(1, int(3600 - hourly_elapsed))
                        logger.info(
                            "otp.rate_limit.hourly_blocked",
                            count=rl.hourly_count,
                            retry_after_s=retry,
                        )
                        raise RateLimited(
                            f"Limite de {hourly_max} códigos/hora atingido. Aguarde {retry}s.",
                            retry_after_s=retry,
                        )
                    rl.hourly_count += 1
                else:
                    rl.hourly_count = 1
                    rl.hourly_window_start = now
                rl.last_created_at = now
                rl.save(
                    update_fields=[
                        "last_created_at",
                        "hourly_count",
                        "hourly_window_start",
                    ]
                )
            else:
                OtpRateLimit.objects.create(
                    user=user,
                    last_created_at=now,
                    hourly_count=1,
                    hourly_window_start=now,
                )
    except IntegrityError:
        # baixa/#33: clique duplo — outro request concorrente criou o rate-limit entre o SELECT (que
        # não travou nada, pois não havia linha) e o INSERT. Não é 500: re-processa FORA do atomic já
        # revertido; agora o row existe e a janela curta bloqueia com 429 — o comportamento certo pra
        # dois pedidos de OTP simultâneos.
        _check_and_record_rate_limit(user)


def generate_and_send(user) -> OtpCode:
    """Gera o OTP, persiste (hash), e envia por WhatsApp via notify. Aplica rate-limit antes."""
    if not settings.OTP_ACTIVE:
        logger.warning("otp.generate.blocked_inactive", user=user.id)
        return OtpCode.objects.create(
            user=user, code_hash="", status=STATUS_FAILED, failure_reason="inactive"
        )

    _check_and_record_rate_limit(user)  # pode levantar RateLimited (429)

    # A4 — TEST_MODE: código fixo (TEST_MODE_OTP_CODE) p/ o fluxo de teste ser determinístico.
    code = (
        settings.TEST_MODE_OTP_CODE
        if getattr(settings, "TEST_MODE", False)
        else _generate_code()
    )
    otp = OtpCode.objects.create(
        user=user, code_hash=_hash_code(code), status=STATUS_GENERATED
    )
    logger.info("otp.generated", id=otp.id, user=user.id)

    # destinatário (phone) vem do Profile — import tardio evita ciclo de import.
    from users.profiles.interface import get as get_profile

    profile = get_profile(user)
    if profile is None or not profile.phone:
        otp.status = STATUS_FAILED
        otp.failure_reason = "no_phone"
        otp.save(update_fields=["status", "failure_reason"])
        logger.warning("otp.send.no_phone", id=otp.id, user=user.id)
        return otp

    ttl_min = settings.OTP_TTL_S // 60
    content = _render(code, ttl_min)

    from notify.interface.send import send

    notif_external_id = send(
        text=content,
        caller="users.auth.otp",
        phone=profile.phone,
        whatsapp=True,
    )
    otp.status = STATUS_SENT
    otp.notification_external_id = notif_external_id
    otp.save(update_fields=["status", "notification_external_id"])
    logger.info("otp.sent", id=otp.id, notification=notif_external_id)
    return otp


def verify(user, code: str, *, consume: bool = True) -> str:
    """Valida o último OTP pendente do user. Conta tentativas; invalida no máximo configurado.

    Devolve o MOTIVO, não um bool (funil v2, tela 2 — protótipo 2026-07-18): "código errado" e
    "código morto" são telas diferentes pro usuário (👀 "confere e digita de novo" × ⏳ "já te
    mandei um novo"), e um bool só não deixava o front escolher. Valores:

    - `OK`      → conferiu; o código foi consumido.
    - `INVALID` → errou o código, mas o código AINDA VALE: é só digitar de novo.
    - `EXPIRED` → não existe código utilizável (venceu, esgotou tentativas ou nunca houve um
      pendente). O caminho de saída é PEDIR OUTRO — tentar de novo aqui nunca vai passar.

    Tentativas esgotadas entram em EXPIRED de propósito: o código já morreu, então insistir é um
    beco sem saída. Antes disso a pessoa via "código incorreto" pra sempre — inclusive digitando
    o código certo — sem nenhuma pista de que precisava pedir outro.
    """
    if not settings.OTP_ACTIVE:
        logger.warning("otp.verify.blocked_inactive", user=user.id)
        return EXPIRED

    otp = (
        OtpCode.objects.filter(user=user, status__in=[STATUS_GENERATED, STATUS_SENT])
        .order_by("-created_at")
        .first()
    )
    if otp is None:
        # Sem pendente = já verificado, já expirado ou queimado nas tentativas. Em todos, o
        # que destrava é um código NOVO.
        logger.info("otp.verify.no_pending", user=user.id)
        return EXPIRED

    age_s = (timezone.now() - otp.created_at).total_seconds()
    if age_s > settings.OTP_TTL_S:
        otp.status = STATUS_EXPIRED
        otp.failure_reason = "expired"
        otp.save(update_fields=["status", "failure_reason"])
        logger.info("otp.verify.expired", id=otp.id)
        return EXPIRED

    if not secrets.compare_digest(otp.code_hash, _hash_code(code)):
        otp.attempts += 1
        if otp.attempts >= settings.OTP_MAX_ATTEMPTS:
            otp.status = STATUS_FAILED
            otp.failure_reason = "invalid_code"
            otp.error_detail = f"Esgotadas {settings.OTP_MAX_ATTEMPTS} tentativas"
            otp.save(
                update_fields=["attempts", "status", "failure_reason", "error_detail"]
            )
            logger.info("otp.verify.max_attempts", id=otp.id, attempts=otp.attempts)
            return EXPIRED
        otp.save(update_fields=["attempts"])
        logger.info("otp.verify.invalid", id=otp.id, attempts=otp.attempts)
        return INVALID

    if not consume:
        # confere sem queimar: quem chama consome depois, já dentro da própria transação
        return OK
    otp.status = STATUS_VERIFIED
    otp.verified_at = timezone.now()
    otp.save(update_fields=["status", "verified_at"])
    logger.info("otp.verify.ok", id=otp.id, user=user.id)
    return OK
