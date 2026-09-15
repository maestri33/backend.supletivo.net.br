"""Tasks Django-Q do lead: rede pesada FORA do request.

- `build_checkout`: cria a cobrança no GATEWAY fora do request do register. Auditoria front
  2026-06-11 (item 6): o register responde <2s com o link curto próprio; o provider
  (Asaas/InfinitePay) é resolvido aqui, com retry espaçado. Gateway fora do ar → o register
  continua 201 e o clique no link curto também tenta na hora (lazy — `checkout_links`).
- `fetch_whatsapp_avatar`: foto de perfil do WhatsApp pro pergaminho (funil v2, tela 3-4).
  Disparada quando a conta NASCE no check — a foto fica pronta minutos antes de ser precisa.
"""

from __future__ import annotations

from datetime import timedelta

import structlog
from django.conf import settings
from django.utils import timezone

logger = structlog.get_logger()

_MAX_ATTEMPTS = 5
_RETRY_DELAY_S = 60


def build_checkout(checkout_pk: int, attempt: int = 1) -> str:
    """Preenche o Checkout no gateway (idempotente). Falhou → reagenda (até _MAX_ATTEMPTS, 60s entre
    tentativas); esgotou → loga e desiste (o lazy do link curto continua cobrindo)."""
    from users.roles.lead import service
    from users.roles.lead.models import Checkout

    checkout = (
        Checkout.objects.select_related("lead__user").filter(pk=checkout_pk).first()
    )
    if checkout is None:
        return "gone"
    if checkout.checkout_url:
        return "already_filled"

    try:
        service.fill_checkout_from_provider(checkout)
    except Exception as exc:  # noqa: BLE001 — gateway fora/instável: retry espaçado
        if attempt >= _MAX_ATTEMPTS:
            logger.error(
                "lead.checkout_build_exhausted",
                checkout=checkout_pk,
                attempts=attempt,
                error=str(exc),
            )
            return "exhausted"
        from django_q.models import Schedule
        from django_q.tasks import schedule

        schedule(
            "users.roles.lead.tasks.build_checkout",
            checkout_pk,
            attempt + 1,
            schedule_type=Schedule.ONCE,
            next_run=timezone.now() + timedelta(seconds=_RETRY_DELAY_S),
        )
        logger.warning(
            "lead.checkout_build_retry",
            checkout=checkout_pk,
            attempt=attempt,
            error=str(exc),
        )
        return f"retry_scheduled_{attempt}"
    return "ok"


def fetch_whatsapp_avatar(profile_pk: int) -> str:
    """Busca a URL da foto de perfil do WhatsApp e grava no Profile (funil v2).

    Best-effort SEM retry: foto é enfeite do pergaminho — sem foto o front usa o
    monograma e nada quebra. TEST_MODE pula; produção usa somente o notify-server.
    Idempotente: já tem foto → no-op (não sobrescreve com um possível null)."""
    from users.profiles.models import Profile

    profile = Profile.objects.filter(pk=profile_pk).first()
    if profile is None:
        return "gone"
    if profile.whatsapp_photo_url:
        return "already_set"
    if getattr(settings, "TEST_MODE", False):
        return "test_mode"

    try:
        from notify.sdk import client as notify_client

        photo = notify_client.phone_avatar(profile.phone)
    except Exception as exc:  # noqa: BLE001 — enfeite: falhou, ficou sem foto
        logger.warning(
            "lead.avatar_fetch_failed", profile=profile_pk, error=type(exc).__name__
        )
        return "failed"

    if not photo:
        return "no_photo"
    profile.whatsapp_photo_url = photo
    profile.save(update_fields=["whatsapp_photo_url", "updated_at"])
    logger.info("lead.avatar_saved", profile=profile_pk)
    return "ok"
