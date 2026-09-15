"""View DMZ do link curto de checkout: `GET /lead/checkout/<token>` (ligada em `core/urls.py`).

Mora aqui, e não em `checkout_links.py`, porque é a ÚNICA coisa do módulo que precisa do
`lead.service` — e o `service` importa `checkout_links` em 7 lugares. Com a view junto, os dois
módulos se importavam em ciclo, e o ciclo só não estourava no boot porque os imports estavam
escondidos dentro das funções. Separando view (casca HTTP) de helper (token/URL), `checkout_links`
vira folha e o `service` pode importá-lo no topo.
"""

from __future__ import annotations

import structlog
from django.http import HttpResponse, HttpResponseNotFound, HttpResponseRedirect

from users.roles.lead import checkout_links, service
from users.roles.lead.models import Checkout

logger = structlog.get_logger()


def checkout_redirect(request, token: str):
    """`GET /lead/checkout/<token>` → 302 pro checkout do gateway (ou recibo, se pago).

    Checkout ainda SEM URL (criação async não terminou) → tenta criar no gateway NA HORA; gateway
    fora → **503** com texto amigável (o link continua válido pra tentar de novo)."""
    url = checkout_links.resolve(token)
    if url:
        return HttpResponseRedirect(url)

    c = Checkout.objects.select_related("lead__user").filter(short_token=token).first()
    if c is None or c.is_paid:  # pago sem recibo = link consumido
        return HttpResponseNotFound("Link de pagamento inválido ou expirado.")
    try:
        service.fill_checkout_from_provider(c)
        c.refresh_from_db()
    except Exception as exc:  # noqa: BLE001 — gateway fora: o link curto segue válido
        logger.warning("lead.checkout_lazy_build_failed", token=token, error=str(exc))
    if c.checkout_url:
        return HttpResponseRedirect(c.checkout_url)
    return HttpResponse(
        "Estamos gerando seu link de pagamento — tente de novo em alguns instantes.",
        status=503,
    )
