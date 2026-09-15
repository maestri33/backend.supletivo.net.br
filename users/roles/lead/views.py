"""View DMZ do link curto de checkout: `GET /lead/checkout/<token>` (ligada em `core/urls.py`).

Mora aqui, e não em `checkout_links.py`, porque é a ÚNICA coisa do módulo que precisa do
`lead.service` — e o `service` importa `checkout_links` em 7 lugares. Com a view junto, os dois
módulos se importavam em ciclo, e o ciclo só não estourava no boot porque os imports estavam
escondidos dentro das funções. Separando view (casca HTTP) de helper (token/URL), `checkout_links`
vira folha e o `service` pode importá-lo no topo.

PIX (issue #158): o QR estático não tem fatura hospedada, então o destino do link curto é a NOSSA
página PIX. Se o QR já está persistido no `Checkout`, o link resolve SEM tocar no gateway — e sem
`FRONTEND_URL` a própria view devolve uma página PIX mínima. 503 aqui é só pro caso em que
realmente não existe cobrança nenhuma ainda.
"""

from __future__ import annotations

import structlog
from django.http import HttpResponse, HttpResponseNotFound, HttpResponseRedirect
from django.utils.html import escape

from users.roles.lead import checkout_links, service
from users.roles.lead.models import Checkout

logger = structlog.get_logger()


def checkout_redirect(request, token: str):
    """`GET /lead/checkout/<token>` → 302 pro checkout (ou recibo, se pago; ou a página PIX).

    Checkout ainda SEM cobrança (criação async não terminou) → tenta criar no gateway NA HORA;
    gateway fora → **503** com texto amigável (o link continua válido pra tentar de novo)."""
    url = checkout_links.resolve(token)
    if url:
        return HttpResponseRedirect(url)

    c = Checkout.objects.select_related("lead__user").filter(short_token=token).first()
    if c is None or c.is_paid:  # pago sem recibo = link consumido
        return HttpResponseNotFound("Link de pagamento inválido ou expirado.")

    # PIX com QR JÁ emitido: o destino é nosso, não do gateway. Serve ANTES de tentar build —
    # tentar recriar o QR com o mesmo `pid` era exatamente o que estourava e virava 503 eterno.
    served = _serve_pix(c)
    if served is not None:
        return served

    build_error: Exception | None = None
    try:
        service.fill_checkout_from_provider(c)
        c.refresh_from_db()
    except Exception as exc:  # noqa: BLE001 — gateway fora: o link curto segue válido
        build_error = exc
        logger.warning("lead.checkout_lazy_build_failed", token=token, error=str(exc))

    served = _serve_pix(c)
    if served is not None:
        return served
    if c.checkout_url:
        return HttpResponseRedirect(c.checkout_url)

    # Aqui não há cobrança nenhuma: 503 honesto, com o motivo no log (não mais mudo).
    logger.error(
        "lead.checkout_link_dead_end",
        token=token,
        payment_method=c.payment_method,
        provider=c.provider,
        has_payment_id=bool(c.provider_payment_id),
        error=str(build_error) if build_error else None,
    )
    return HttpResponse(
        "Estamos gerando seu link de pagamento — tente de novo em alguns instantes.",
        status=503,
    )


def _serve_pix(c: Checkout):
    """PIX com QR persistido → resposta pronta (302 pra página do front, ou HTML de fallback).

    `None` quando não é PIX ou o QR ainda não existe (aí o caller tenta o build)."""
    if c.payment_method != Checkout.Method.PIX or not c.qrcode_payload:
        return None
    url = c.checkout_url or checkout_links.pix_page_url(c.short_token)
    if url:
        # re-popula o cache do link curto (checkouts criados antes da issue #158 nasceram com
        # `checkout_url` nulo; a partir daqui o token resolve direto).
        checkout_links.bind(c.short_token, url)
        if not c.checkout_url:
            c.checkout_url = url
            c.save(update_fields=["checkout_url", "updated_at"])
        return HttpResponseRedirect(url)
    return _pix_fallback_page(c)


_PIX_FALLBACK_HTML = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pague sua matrícula com PIX</title>
<style>
 body{{margin:0;padding:24px;font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
   background:#f4f6fb;color:#0b1b3b;display:flex;justify-content:center}}
 main{{width:100%;max-width:420px;background:#fff;border-radius:20px;padding:24px;
   box-shadow:0 16px 40px -12px rgba(11,27,59,.2);text-align:center}}
 h1{{font-size:20px;margin:0 0 4px}} .amount{{font-size:28px;font-weight:800;margin:8px 0 16px}}
 img{{width:220px;height:220px;object-fit:contain}}
 textarea{{width:100%;box-sizing:border-box;min-height:96px;font:12px/1.4 monospace;
   border:1px solid #d7dced;border-radius:12px;padding:10px;resize:vertical}}
 p{{color:#5a6785;font-size:13px}}
</style></head><body><main>
 <h1>Pague com PIX</h1>
 <div class="amount">R$ {amount}</div>
 {image}
 <p>Escaneie o QR Code ou copie o código abaixo no app do seu banco.</p>
 <textarea readonly onclick="this.select()">{payload}</textarea>
 <p>A matrícula é liberada automaticamente assim que o pagamento for confirmado.</p>
</main></body></html>"""


def _pix_fallback_page(c: Checkout) -> HttpResponse:
    """Página PIX mínima servida pelo próprio Django — usada quando não há `FRONTEND_URL`.

    Não é a tela bonita do funil (essa é o `/pix/<token>` do Next): é a garantia de que o link
    que o lead recebeu no WhatsApp SEMPRE mostra o copia-e-cola, mesmo com o front sem URL
    configurada. Sem JS, sem dependência externa."""
    image = (
        f'<img src="{escape(c.qrcode_image)}" alt="QR Code PIX">'
        if c.qrcode_image
        else ""
    )
    html = _PIX_FALLBACK_HTML.format(
        amount=escape(f"{c.amount}"),
        image=image,
        payload=escape(c.qrcode_payload or ""),
    )
    return HttpResponse(html, content_type="text/html; charset=utf-8")
