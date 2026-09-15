"""Cliente de telemetria e eventos server-side do PostHog.

Implementação leve usando httpx e threading (sem dependência pesada de SDK externo),
com sanitização e mascaramento estrito de dados sensíveis conforme LGPD.
"""

from __future__ import annotations

import datetime
import threading
from typing import Any

import httpx
import structlog
from django.conf import settings

from core.sentry import mask_pii_text

logger = structlog.get_logger()

# Chaves cuja presença no dicionário de propriedades deve ser filtrada (LGPD)
_PII_KEYS = frozenset({
    "cpf",
    "rg",
    "cnh",
    "phone",
    "telefone",
    "celular",
    "whatsapp",
    "email",
    "e_mail",
    "pix",
    "chave_pix",
    "pix_key",
    "password",
    "senha",
    "token",
    "otp",
    "otp_code",
    "codigo",
    "birth_date",
    "nascimento",
    "mother_name",
    "nome_mae",
    "address",
    "endereco",
})


def is_posthog_enabled() -> bool:
    """Verifica se a integração do PostHog está ativa e configurada."""
    return bool(
        getattr(settings, "POSTHOG_ENABLED", False)
        and getattr(settings, "POSTHOG_API_KEY", "")
    )


def _scrub_properties(properties: dict[str, Any] | None) -> dict[str, Any]:
    """Sanitiza e mascara propriedades para proteger a privacidade (LGPD)."""
    if not properties:
        return {}

    scrubbed = {}
    for key, value in properties.items():
        k_lower = str(key).lower()
        if k_lower in _PII_KEYS:
            continue  # Descarta valores PII brutos
        if isinstance(value, str):
            scrubbed[key] = mask_pii_text(value)
        elif isinstance(value, dict):
            scrubbed[key] = _scrub_properties(value)
        else:
            scrubbed[key] = value

    return scrubbed


def _dispatch_posthog_payload(payload: dict[str, Any], timeout: float = 3.0) -> None:
    """Envia o payload via HTTP POST para a API do PostHog."""
    host = getattr(settings, "POSTHOG_HOST", "https://us.i.posthog.com").rstrip("/")
    url = f"{host}/capture/"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                logger.debug("posthog.event_sent", event_name=payload.get("event"))
            else:
                logger.warning(
                    "posthog.event_rejected",
                    status=resp.status_code,
                    body=resp.text[:160],
                    event_name=payload.get("event"),
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("posthog.dispatch_error", error=str(exc)[:160], event_name=payload.get("event"))


def capture_event(
    event: str,
    distinct_id: str,
    properties: dict[str, Any] | None = None,
    *,
    sync: bool = False,
) -> bool:
    """Captura um evento de produto/funil no PostHog.
    
    Por padrão roda assincronamente em thread desacoplada (fire-and-forget).
    """
    if not is_posthog_enabled():
        return False

    api_key = settings.POSTHOG_API_KEY
    clean_props = _scrub_properties(properties)
    clean_props["$lib"] = "backend.supletivo.net.br"

    payload = {
        "api_key": api_key,
        "event": event,
        "distinct_id": str(distinct_id),
        "properties": clean_props,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    if sync:
        _dispatch_posthog_payload(payload)
    else:
        # Envio em background para não bloquear o tempo de resposta da API
        thread = threading.Thread(
            target=_dispatch_posthog_payload,
            args=(payload,),
            daemon=True,
        )
        thread.start()

    return True


# ── Helpers de Negócio (Eventos de Alto Valor) ───────────────────────────────

def track_funnel_checked(
    distinct_id: str,
    *,
    found: bool,
    registered: bool,
    ref: str | None = None,
) -> bool:
    """Registra evento de verificação de entrada no funil."""
    props = {
        "found": found,
        "registered": registered,
        "ref": ref or "",
    }
    return capture_event("funnel_lead_checked", distinct_id=distinct_id, properties=props)


def track_funnel_created(
    distinct_id: str,
    *,
    payment_method: str | None,
    ref: str | None = None,
) -> bool:
    """Registra criação de cadastro no funil."""
    props = {
        "payment_method": payment_method or "unknown",
        "ref": ref or "",
    }
    return capture_event("funnel_lead_created", distinct_id=distinct_id, properties=props)


def track_otp_event(distinct_id: str, *, action: str) -> bool:
    """Registra eventos do ciclo de vida de OTP (sent / verified)."""
    return capture_event(f"auth_otp_{action}", distinct_id=distinct_id, properties={"action": action})


def track_payment_event(
    distinct_id: str,
    *,
    action: str,
    amount: Any = None,
    method: str | None = None,
    provider: str | None = None,
) -> bool:
    """Registra confirmação ou falha de pagamento no funil."""
    props = {
        "action": action,
        "amount": str(amount) if amount is not None else None,
        "payment_method": method or "",
        "provider": provider or "",
    }
    return capture_event(f"payment_{action}", distinct_id=distinct_id, properties=props)
