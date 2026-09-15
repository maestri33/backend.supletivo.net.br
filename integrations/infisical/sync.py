"""Serviço de sincronização de segredos do Infisical para a plataforma."""

from __future__ import annotations

from typing import Any
import structlog

from core.system_config import set_setting
from .client import InfisicalClient, InfisicalClientError

logger = structlog.get_logger()


def sync_secrets_to_platform(
    *,
    environment: str | None = None,
    client: InfisicalClient | None = None,
    overwrite_existing: bool = True,
) -> dict[str, Any]:
    """Sincroniza todos os segredos do Infisical para o PlatformSetting e cache em memória.

    Retorna relatório com status, quantidade e chaves sincronizadas.
    Não lança exceção não tratada caso o cofre esteja indisponível, garantindo resiliência.
    """
    cli = client or InfisicalClient(environment=environment)
    target_env = environment or cli.environment

    try:
        secrets = cli.get_secrets(environment=target_env)
        if not secrets:
            logger.info("infisical.sync_empty", environment=target_env)
            return {
                "status": "ok",
                "synced_count": 0,
                "environment": target_env,
                "keys": [],
            }

        synced_keys: list[str] = []
        for key, value in secrets.items():
            set_setting(
                key=key,
                value=value,
                description=f"Sincronizado via Infisical ({target_env})",
                is_secret=True,
            )
            synced_keys.append(key)

        logger.info(
            "infisical.sync_success",
            environment=target_env,
            synced_count=len(synced_keys),
            keys=synced_keys,
        )

        return {
            "status": "ok",
            "synced_count": len(synced_keys),
            "environment": target_env,
            "keys": synced_keys,
        }
    except InfisicalClientError as exc:
        logger.warning(
            "infisical.sync_skipped",
            environment=target_env,
            error=str(exc),
        )
        return {
            "status": "error",
            "error": str(exc),
            "synced_count": 0,
            "environment": target_env,
            "keys": [],
        }
    except Exception as exc:
        logger.error(
            "infisical.sync_unhandled_error",
            environment=target_env,
            error=str(exc),
        )
        return {
            "status": "error",
            "error": f"Erro inesperado: {exc}",
            "synced_count": 0,
            "environment": target_env,
            "keys": [],
        }
