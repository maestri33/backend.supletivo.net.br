"""Utilitários de requisição HTTP (extração de IP e headers de proxy)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.http import HttpRequest


def get_client_ip(request: HttpRequest) -> str:
    """Extrai o IP real do cliente, priorizando Cloudflare e proxies reversos.
    
    1. HTTP_CF_CONNECTING_IP (injetado e autenticado pela Cloudflare Edge)
    2. Primeiro IP de HTTP_X_FORWARDED_FOR (passado por proxies como Caddy/Nginx)
    3. REMOTE_ADDR (conexão TCP direta)
    """
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_ip and cf_ip.strip():
        return cf_ip.strip()

    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded and forwarded.strip():
        return forwarded.split(",")[0].strip()

    remote_addr = request.META.get("REMOTE_ADDR")
    if remote_addr and remote_addr.strip():
        return remote_addr.strip()

    return "127.0.0.1"
