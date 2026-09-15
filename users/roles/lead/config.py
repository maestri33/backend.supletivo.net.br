"""Config do lead — preço da matrícula por gateway + descrição (lido do `.env`, CONVENTION §10).

DEV (Victor 2026-06-04): **Cartão R$1** / **PIX R$5**. PROD = pedir ao Victor (§8).

O R$5 do PIX era o piso da FATURA gerenciada (`/v3/payments`). O funil migrou pro **QR Code
estático** (`/v3/pix/qrCodes/static`), cujo contrato de API NÃO documenta valor mínimo — `value`
é um `number` livre (issue #158). Ou seja: o valor emitido é o valor EXATO desta config, sem
piso do nosso lado. Se o Victor quiser cobrar abaixo de R$5, basta baixar `ENROLLMENT_PRICE_PIX`
— «PENDÊNCIA»: confirmar com o suporte do Asaas se a CONTA impõe piso comercial (a doc pública
da API não impõe).
Valores em REAIS (Decimal); o InfinitePay converte pra centavos internamente (×100).
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings


from core.system_config import get_setting


def _money(name: str, default: str) -> Decimal:
    val = get_setting(name, getattr(settings, name, default))
    return Decimal(str(val))


def card_cents() -> int:
    """Preço do cartão em CENTAVOS (total), do `.env` ou DB. **Fonte única**: cobrança + vitrine. DEV=100 (R$1)."""
    return int(get_setting("ENROLLMENT_PRICE_CARD_CENTS", getattr(settings, "ENROLLMENT_PRICE_CARD_CENTS", 100)))


def price_card() -> Decimal:
    """Preço da matrícula no cartão, em REAIS = `card_cents()` ÷ 100. Cobrado E exibido (Victor 2026-06-07)."""
    return (Decimal(card_cents()) / 100).quantize(Decimal("0.01"))


def price_pix() -> Decimal:
    """Preço da matrícula no PIX (Asaas), valor CHEIO em reais, do `.env` ou DB. DEV=5.

    É EXATAMENTE o que vai no `value` do QR estático — sem piso, sem arredondar (ver docstring
    do módulo)."""
    return _money("ENROLLMENT_PRICE_PIX", "5")


def promo_card_cents() -> int:
    """Preço promocional do cartão em CENTAVOS."""
    return int(get_setting("ENROLLMENT_PROMO_PRICE_CARD_CENTS", getattr(settings, "ENROLLMENT_PROMO_PRICE_CARD_CENTS", card_cents())))


def promo_price_card() -> Decimal:
    """Preço promocional da matrícula no cartão em REAIS."""
    return (Decimal(promo_card_cents()) / 100).quantize(Decimal("0.01"))


def promo_price_pix() -> Decimal:
    """Preço promocional da matrícula no PIX em REAIS."""
    return _money("ENROLLMENT_PROMO_PRICE_PIX", str(price_pix()))


# ── auto-matrícula do PROMOTOR (Victor 2026-06-16): preço PRÓPRIO, fluxo próprio, SEM comissão. ──
# DEV: default = o preço normal (mini, fallback). PROD: «PENDÊNCIA» — Victor define o valor do promotor.
def promoter_card_cents() -> int:
    return int(get_setting("ENROLLMENT_PRICE_PROMOTER_CARD_CENTS", getattr(settings, "ENROLLMENT_PRICE_PROMOTER_CARD_CENTS", card_cents())))


def promoter_price_card() -> Decimal:
    return (Decimal(promoter_card_cents()) / 100).quantize(Decimal("0.01"))


def promoter_price_pix() -> Decimal:
    return _money("ENROLLMENT_PRICE_PROMOTER_PIX", str(price_pix()))


# parcelas do cartão exibidas na vitrine (o front mostra "12x de ..."). É só EXIBIÇÃO
def card_installments() -> int:
    return int(get_setting("CARD_INSTALLMENTS", getattr(settings, "CARD_INSTALLMENTS", 12)))


CARD_INSTALLMENTS = 12


def anchor_full() -> Decimal:
    """Preço cheio de vitrine marketing ("de R$ 1.615"), do DB ou .env."""
    return _money("ENROLLMENT_ANCHOR_FULL", "1615")


def description() -> str:
    """Descrição da cobrança (aparece pro pagador)."""
    return str(get_setting("ENROLLMENT_DESCRIPTION", getattr(settings, "ENROLLMENT_DESCRIPTION", "Matrícula Supletivo")))



def frontend_url() -> str:
    """URL do FRONT pra onde o gateway redireciona APÓS o pagamento (`.env` FRONTEND_URL).

    Vazia enquanto o front não existe — **NÃO** cai em EXTERNAL_URL: a raiz da API dá 404, e mandar
    esse redirect ao Asaas (`callback.successUrl`) faria o gateway exigir um domínio cadastrado na
    conta à toa (erro real visto 2026-06-05). Sem front → sem redirect: o Asaas não recebe `callback`
    (a cobrança PIX passa) e o InfinitePay usa o próprio fallback (`INFINITEPAY_REDIRECT_URL`/EXTERNAL_URL).
    Quando o front existir, basta setar `FRONTEND_URL` (e cadastrar o domínio no Asaas p/ o callback).

    Lê pelo `get_setting` (DB > `.env`) como o `EXTERNAL_URL`: a chave está no catálogo do
    `core/system_config.py`, então o staff pode corrigir o domínio sem redeploy — e o PIX depende
    dela pra montar o link da página própria (issue #158).
    """
    return str(get_setting("FRONTEND_URL", getattr(settings, "FRONTEND_URL", "")) or "")


def enrollment_docs_url() -> str:
    """Deep-link para preenchimento de documentos da matrícula pós-pagamento (Issue #165)."""
    base = frontend_url().rstrip("/")
    if not base:
        return ""
    return base + getattr(settings, "ENROLLMENT_RESUME_PATH", "/matricula")

