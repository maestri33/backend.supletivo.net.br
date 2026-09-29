"""
integrations/cloudflare/cache.py — Serviço de Invalidação de Edge Cache na Cloudflare.
"""

from __future__ import annotations

from typing import Any
import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


def purge_edge_cache(
    *,
    urls: list[str] | None = None,
    tags: list[str] | None = None,
    purge_all: bool = False,
) -> bool:
    """
    Dispara purga de cache na Cloudflare via API REST v4.

    Suporta:
    - Purga por URLs exatas (Disponível em planos Free, Pro, Business e Enterprise).
    - Purga por Cache-Tags (Planos Enterprise).
    - Purga total (purge_everything).
    """
    zone_id = getattr(settings, "CLOUDFLARE_ZONE_ID", "")
    api_token = getattr(settings, "CLOUDFLARE_API_TOKEN", "")

    if not zone_id or not api_token:
        logger.warning("cloudflare.purge_skipped_no_credentials")
        return False

    api_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache"
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {}
    if purge_all:
        payload["purge_everything"] = True
    elif tags:
        payload["tags"] = tags
    elif urls:
        payload["files"] = urls
    else:
        return False

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(api_url, json=payload, headers=headers)
            data = resp.json()
            if resp.status_code == 200 and data.get("success"):
                logger.info("cloudflare.purge_success", targets=urls or tags or "everything")
                return True
            logger.error("cloudflare.purge_failed", status=resp.status_code, response=data)
            return False
    except Exception as exc:  # noqa: BLE001
        logger.exception("cloudflare.purge_exception", error=str(exc))
        return False


def purge_pricing_cache_async() -> None:
    """Dispara a purga dos endpoints de pricing de forma desacoplada."""
    base_url = getattr(settings, "EXTERNAL_URL", "https://backend.supletivo.net.br").rstrip("/")
    urls = [
        f"{base_url}/api/v1/clients/pricing",
    ]
    purge_edge_cache(urls=urls)
