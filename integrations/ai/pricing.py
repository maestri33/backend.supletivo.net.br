"""Custo monetário por chamada de IA — tabela de preços vinda do `.env` (CONVENTION §8, §10).

O `AiCall.cost` nasce `null` de propósito: preço é dinheiro real, não se inventa (§8). Aqui mora o
cálculo OPCIONAL: quando (e só quando) o Victor configurar os preços no `.env`, `cost_for` devolve o
custo da chamada a partir dos tokens; sem config → `None` (estado de hoje, nada muda no painel).

Formato no `.env` (preço por 1 MILHÃO de tokens, na moeda que o Victor escolher — USD em geral):

    IA_PRICES="deepseek:deepseek-chat:0.27:1.10, minimax:MiniMax-M3:0.30:1.20"
              └ provider ┘└─ model ──┘ └in┘ └out┘

`in` = preço por 1M tokens de prompt; `out` = por 1M de completion. Modelo sem entrada na tabela →
`None` (não estima). Visão/OCR/STT via clients REST não reportam tokens e também ficam sem custo.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings

_PER_MILLION = Decimal("1000000")


def cost_for(
    *,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> Decimal | None:
    """Custo (Decimal, 6 casas) da chamada pelos tokens, ou `None` se não há preço configurado.

    Lê `settings.IA_PRICES[(provider, model)] = (input_per_million, output_per_million)`. Sem
    entrada pra esse par → `None` (não estima — §8). Tokens 0 com preço configurado → custo 0
    (válido: chamada que não gastou token, ex.: erro antes de gerar)."""
    table = getattr(settings, "IA_PRICES", None) or {}
    price = table.get((provider, model))
    if price is None:
        return None
    input_per_m, output_per_m = price
    cost = (
        Decimal(prompt_tokens) * input_per_m + Decimal(completion_tokens) * output_per_m
    ) / _PER_MILLION
    return cost.quantize(Decimal("0.000001"))
