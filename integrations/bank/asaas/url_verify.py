"""Verificação da URL pública (porte de config_url.py do micro legado p/ ORM Django).

Fluxo do "ping real" (escolha do Victor): o backend emite um nonce single-use, chama a PRÓPRIA
EXTERNAL_URL numa rota de echo (que consome o nonce) e confirma que voltou — provando que a URL
pública realmente chega no nosso backend. O nonce expira em URL_VERIFY_NONCE_TTL (default 600s) e
serve de auth da rota de echo (segredo single-use, CONVENTION §5 público).
"""

from __future__ import annotations

import secrets
from datetime import timedelta

import httpx
from django.conf import settings
from django.utils import timezone

from .models import UrlVerifyNonce

VERIFY_PATH = "/integrations/asaas/url-verify/"


def issue_nonce(url: str) -> tuple[str, str]:
    """Cria um nonce single-use ligado à url e devolve (nonce, echo_url).

    Limpa nonces pendentes antigos (higiene — não é obrigatório, mas evita acúmulo).
    """
    UrlVerifyNonce.objects.filter(consumed_at__isnull=True).delete()
    nonce = secrets.token_urlsafe(24)
    UrlVerifyNonce.objects.create(nonce=nonce, target_url=str(url), purpose="external")
    echo_url = f"{str(url).rstrip('/')}{VERIFY_PATH}{nonce}/"
    return nonce, echo_url


def consume_nonce(nonce: str) -> tuple[bool, str]:
    """Valida e marca o nonce como usado (single-use). Retorna (ok, reason)."""
    row = UrlVerifyNonce.objects.filter(nonce=nonce).first()
    if row is None:
        return False, "nonce_not_found"
    if row.consumed_at is not None:
        return False, "nonce_already_used"
    ttl = getattr(settings, "URL_VERIFY_NONCE_TTL", 600)
    if timezone.now() - row.created_at > timedelta(seconds=ttl):
        return False, "nonce_expired"
    row.consumed_at = timezone.now()
    row.save(update_fields=["consumed_at"])
    return True, "ok"


def self_ping() -> tuple[bool, str]:
    """O backend chama a própria EXTERNAL_URL (rota de echo) p/ provar a reachability pública.

    Retorna (verified, detail). verified=True só se o echo voltou 200 E o nonce ficou consumido no
    nosso DB (prova que a chamada chegou NESTE backend, não num proxy que devolve 200 pra tudo).
    """
    base = settings.EXTERNAL_URL
    if not base:
        return False, "external_url_not_set"
    nonce, echo_url = issue_nonce(base)
    try:
        r = httpx.get(echo_url, timeout=10.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        return False, f"ping_failed: {exc}"
    if r.status_code != 200:
        return False, f"echo_status={r.status_code}"
    row = UrlVerifyNonce.objects.filter(nonce=nonce).first()
    if row is None or row.consumed_at is None:
        return False, "nonce_not_consumed"
    return True, f"echo_ok url={echo_url}"
