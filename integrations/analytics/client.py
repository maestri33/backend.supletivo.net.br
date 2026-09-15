"""Base client e exceções para integrações de Analytics."""

from __future__ import annotations

from typing import Any
import structlog

logger = structlog.get_logger()

_PERMANENT_STATUSES = frozenset({400, 404, 422})


class AnalyticsError(Exception):
    """Exceção base para erros em chamadas de APIs de analytics."""

    def __init__(self, status_code: int, body: Any, message: str = ""):
        self.status_code = status_code
        self.body = body
        super().__init__(message or f"Analytics HTTP {status_code}: {body!r}")

    @property
    def is_permanent(self) -> bool:
        return self.status_code in _PERMANENT_STATUSES


class PermanentAnalyticsError(AnalyticsError):
    """Erro permanente retornado pela API remota (não retentável)."""

    pass
