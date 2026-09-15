"""Pacote de Health Checks da API Ninja."""

from __future__ import annotations

from api.health.router import health_api, staff_health_router

__all__ = ["health_api", "staff_health_router"]
