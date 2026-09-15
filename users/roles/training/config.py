"""Config do training — nota de corte (lida do `.env`, CONVENTION §10). DEV/padrão = 6 (palavra do dono)."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings


def pass_score() -> Decimal:
    """Nota mínima (0–10) para aprovar uma submissão. Default 6."""
    return Decimal(str(getattr(settings, "TRAINING_PASS_SCORE", "6")))
