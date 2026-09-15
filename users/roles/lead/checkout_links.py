"""Link curto e único pro checkout (cartão InfinitePay / PIX Asaas).

O destino é gigante e feio (ex.: `checkout.infinitepay.io/v7m?lenc=...`, ou a nossa página PIX) —
não dá pra mandar por WhatsApp. Aqui geramos um token curto, guardamos `token -> url do gateway` no
**cache do Django** (`django.core.cache`; em prod = Redis, em dev = LocMem do runserver) e expomos
`GET /lead/checkout/<token>` (a view mora em `lead/views.py`) que **redireciona 302** pro checkout. O retorno pós-pagamento é do próprio
gateway (`redirect_url` do InfinitePay / `callback.successUrl` do Asaas → `frontend_url`).

No PIX o destino NÃO é do gateway: o QR estático (`/v3/pix/qrCodes/static`) não tem fatura
hospedada, então o token aponta pra `pix_page_url()` — a nossa página, que renderiza o
copia-e-cola/PNG já persistidos no `Checkout` (issue #158).

O token nasce JUNTO com o register (criação do checkout no gateway é ASSÍNCRONA — auditoria front
2026-06-11): se o clique chegar antes do gateway responder, a view tenta criar NA HORA (lazy); gateway
fora do ar → 503 amigável (o link continua válido).

⚠️ Em prod com vários workers, o cache PRECISA ser compartilhado (Redis) — senão o worker que atende o
redirect não vê o token. Fallback robusto: se o cache não tiver o token, a view recupera a URL pelo
`Checkout` persistido (`short_token`) e re-popula o cache.
"""

from __future__ import annotations

import secrets

import structlog
from django.conf import settings
from django.core.cache import cache

logger = structlog.get_logger()

_PREFIX = "checkout_link:"
_TTL = 60 * 60 * 48  # 48h


def new_token() -> str:
    """Token curto SEM URL ainda (o gateway responde depois, async). `bind()` liga quando ela existir."""
    return secrets.token_urlsafe(9)


def bind(token: str | None, url: str) -> None:
    """Liga `token -> url do gateway` no cache (chamado quando o provider responde)."""
    if token:
        cache.set(_PREFIX + token, url, _TTL)


def unbind(token: str | None) -> None:
    """Apaga o `token -> url` do cache (checkout substituído na troca de forma de pagamento).

    Sem isso o link antigo continuava redirecionando pelo cache (TTL de 48h) mesmo com a linha
    do `Checkout` já deletada — o lead caía numa página PIX de um checkout que não existe mais."""
    if token:
        cache.delete(_PREFIX + token)


def short_url(token: str | None) -> str | None:
    if not token:
        return None
    from core.system_config import get_setting
    base = (get_setting("EXTERNAL_URL", getattr(settings, "EXTERNAL_URL", "")) or "").rstrip("/")
    return f"{base}/lead/checkout/{token}"


# rota da página PIX PRÓPRIA no front (Next: apps/supletivo/src/app/pix/[token]/page.tsx).
PIX_PAGE_PATH = "/pix"


def pix_page_url(token: str | None) -> str | None:
    """URL da **nossa** página PIX (`{FRONTEND_URL}/pix/<token>`) — destino do link curto no PIX.

    O QR estático (`/v3/pix/qrCodes/static`) NÃO tem fatura hospedada: não existe página do
    gateway pra onde redirecionar (issue #158 — era isso que deixava o link curto sem destino e
    o lead em 503 eterno). Quem mostra o copia-e-cola + o PNG é a nossa página, lendo o
    `qrcode_payload`/`qrcode_image` já persistidos no `Checkout`.

    Sem `FRONTEND_URL` → `None`, e aí a view do link curto (`lead/views.py`) renderiza a página
    PIX mínima servida pelo próprio Django. O link NUNCA fica sem destino."""
    if not token:
        return None
    from users.roles.lead import config

    base = (config.frontend_url() or "").rstrip("/")
    if not base:
        return None
    return f"{base}{PIX_PAGE_PATH}/{token}"


def resolve(token: str) -> str | None:
    """token -> URL de destino do redirect.

    Se o checkout JÁ FOI PAGO (o lead virou enrollment/student) → manda pro **comprovante**
    (`receipt_url`) em vez do gateway (Victor 2026-06-05). Senão → URL do gateway (cache; fallback no
    Checkout persistido, re-popula o cache)."""
    from users.roles.lead.models import Checkout

    c = Checkout.objects.filter(short_token=token).first()
    if c and c.is_paid:
        return (
            c.receipt_url or None
        )  # pago: vai pro recibo (sem recibo → 404, link já consumido)
    url = cache.get(_PREFIX + token)
    if url:
        return url
    if c and c.checkout_url:
        cache.set(_PREFIX + token, c.checkout_url, _TTL)
        return c.checkout_url
    return None
