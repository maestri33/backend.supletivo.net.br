"""Tasks Django-Q do modo remote (Fase 2): POST ao notify-server DEPOIS do commit do caller.

Contrato de retry (Q_CLUSTER: retry 300s, max_attempts 3):
- 400/404/422 = permanente (payload/evento inválido — repetir não muda nada) → loga
  `notify.sdk.push_dropped` e NÃO re-levanta.
- Resto (5xx, timeout, conexão) → raise; o Django-Q re-tenta com a MESMA idempotency_key e o
  servidor deduplica, então retry nunca duplica mensagem.
"""

from __future__ import annotations

import structlog

from notify.sdk import client

logger = structlog.get_logger()

_PERMANENT_STATUSES = frozenset({400, 404, 422})


def push_send(payload: dict) -> None:
    """Empurra um SendIn pro servidor. `payload['external_id']` = handle devolvido ao caller."""
    try:
        resp = client.post_send(payload)
    except client.NotifyServerError as exc:
        if exc.status_code in _PERMANENT_STATUSES:
            logger.warning(
                "notify.sdk.push_dropped",
                external_id=payload.get("external_id"),
                caller=payload.get("caller"),
                status=exc.status_code,
            )
            return
        raise
    logger.info(
        "notify.sdk.pushed",
        external_id=payload.get("external_id"),
        server_id=resp.get("external_id"),
        caller=payload.get("caller"),
    )


def push_send_event(payload: dict) -> None:
    """Empurra um SendEventIn. Resposta None (404) = evento não disparado — descarte logado."""
    try:
        resp = client.post_send_event(payload)
    except client.NotifyServerError as exc:
        if exc.status_code in _PERMANENT_STATUSES:
            logger.warning(
                "notify.sdk.push_dropped",
                event_key=payload.get("event"),
                external_id=payload.get("idempotency_key"),
                status=exc.status_code,
            )
            return
        raise
    if resp is None:
        logger.warning(
            "notify.sdk.event_not_dispatched",
            event_key=payload.get("event"),
            external_id=payload.get("idempotency_key"),
        )
        return
    logger.info(
        "notify.sdk.pushed",
        external_id=payload.get("idempotency_key"),
        server_id=resp.get("external_id"),
        event_key=payload.get("event"),
    )
