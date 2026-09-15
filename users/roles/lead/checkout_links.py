"""Link curto e único pro checkout (cartão InfinitePay / PIX Asaas).

O link do gateway é gigante e feio (ex.: `checkout.infinitepay.io/v7m?lenc=...` ou a página do Asaas) —
não dá pra mandar por WhatsApp. Aqui geramos um token curto, guardamos `token -> url do gateway` no
**cache do Django** (`django.core.cache`; em prod = Redis, em dev = LocMem do runserver) e expomos
`GET /lead/checkout/<token>` (a view mora em `lead/views.py`) que **redireciona 302** pro checkout. O retorno pós-pagamento é do próprio
gateway (`redirect_url` do InfinitePay / `callback.successUrl` do Asaas → `frontend_url`).

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


def short_url(token: str | None) -> str | None:
    if not token:
        return None
    from core.system_config import get_setting
    base = (get_setting("EXTERNAL_URL", getattr(settings, "EXTERNAL_URL", "")) or "").rstrip("/")
    return f"{base}/lead/checkout/{token}"


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
