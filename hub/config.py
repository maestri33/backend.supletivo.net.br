"""Config do `hub` lida do `.env` via `settings` (CONVENTION §10: um .env, nada hardcoded).

As marcas de polo vivem no `.env` (`HUB_BRANDS`) como catálogo — mesma filosofia das roles (§9):
lista no `.env`, validada no `interface`, NÃO `choices` fixo no model.
"""

from __future__ import annotations

from django.conf import settings


def brands() -> list[str]:
    """Marcas válidas de polo (catálogo `HUB_BRANDS` do .env)."""
    return list(getattr(settings, "HUB_BRANDS", []))


def default_brand() -> str:
    """Marca usada no hub PADRÃO criado pelo seed."""
    return getattr(settings, "DEFAULT_HUB_BRAND", "standard")


def is_valid_brand(brand: str) -> bool:
    """True se `brand` está no catálogo do .env."""
    return brand in brands()
