"""System checks do `hub` (CONVENTION §10). Só AVISOS — config de marca não trava o boot.

`hub.W001`: catálogo de marcas vazio. `hub.W002`: marca do hub padrão fora do catálogo.
"""

from __future__ import annotations

from django.core.checks import Warning as DjangoWarning


def check_hub_config(app_configs, **kwargs):
    from hub import config

    warnings = []
    if not config.brands():
        warnings.append(
            DjangoWarning(
                "HUB_BRANDS vazio — nenhuma marca de polo configurada.",
                hint="Defina HUB_BRANDS no .env (ex.: wyden,estacio,standard).",
                id="hub.W001",
            )
        )
    elif config.default_brand() not in config.brands():
        warnings.append(
            DjangoWarning(
                f"DEFAULT_HUB_BRAND '{config.default_brand()}' não está em HUB_BRANDS.",
                hint="Ajuste DEFAULT_HUB_BRAND ou HUB_BRANDS no .env.",
                id="hub.W002",
            )
        )
    return warnings
