"""Health check endpoints — público /healthz + rotas de staff health."""

from __future__ import annotations

import time

import httpx
from typing import Any
from django.conf import settings
from django.db import connections
from ninja import Router, Schema

from api.auth import JWTAuth, require_superuser
from api.base import build_group

# ── público: grupo health (auth=None) ──

health_api = build_group(
    "health", "Health check público — sem autenticação.", auth_override=None
)

staff_health_router = Router(tags=["staff-health"])


class HealthzOut(Schema):
    status: str
    version: str = "0.1.0-alpha.1"
    db: bool
    migrations_pending: int
    sha: str | None = None
    built_at: str | None = None


class StaffHealthFullOut(Schema):
    db: dict[str, Any]
    asaas: dict[str, Any]
    infinitepay: dict[str, Any]
    omniroute: dict[str, Any]
    notify: dict[str, Any]
    migrations_pending: int
    deploy: dict[str, Any]


def _ping(url: str, timeout: float = 5.0) -> dict:
    try:
        r = httpx.get(url, timeout=timeout)
        return {
            "ok": r.status_code < 500,
            "status": r.status_code,
            "ms": round(r.elapsed.total_seconds() * 1000),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def _ping_db() -> dict:
    try:
        t0 = time.monotonic()
        with connections["default"].cursor() as c:
            c.execute("SELECT 1")
        return {"ok": True, "ms": round((time.monotonic() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def _pending_migrations() -> int:
    """Nº de migrations não aplicadas, IN-PROCESS via MigrationExecutor."""
    try:
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connections["default"])
        targets = executor.loader.graph.leaf_nodes()
        return len(executor.migration_plan(targets))
    except Exception:
        return -1


def _deploy_info() -> dict:
    build_file = settings.BASE_DIR / "build.txt"
    sha = build_file.read_text().strip() if build_file.exists() else None
    return {"sha": sha, "built_at": None}


@health_api.get("/healthz", response=HealthzOut, summary="Health check público")
def healthz(request):
    """Health check público — sem auth. DB ping + migrations pendentes + build info."""
    db_ok = _ping_db()["ok"]
    deploy = _deploy_info()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": getattr(settings, "APP_VERSION", "0.1.0-alpha.1"),
        "db": db_ok,
        "migrations_pending": _pending_migrations(),
        "sha": deploy["sha"],
        "built_at": deploy["built_at"],
    }


@staff_health_router.get("/health/full", response=StaffHealthFullOut, auth=JWTAuth(), summary="Diagnóstico profundo de integrações")
def staff_health(request):
    """Diagnóstico profundo para o staff (exige superuser)."""
    require_superuser(request.auth)
    return {
        "db": _ping_db(),
        "asaas": _ping(settings.ASAAS_BASE_URL + "/status")
        if settings.ASAAS_BASE_URL
        else {"ok": None, "note": "não configurado"},
        "infinitepay": _ping("https://api.checkout.infinitepay.io/")
        if settings.INFINITEPAY_HANDLE
        else {"ok": None, "note": "não configurado"},
        "omniroute": _ping(
            getattr(settings, "IA_OMNIROUTE_BASE_URL", "") + "/v1/models"
        )
        if getattr(settings, "IA_OMNIROUTE_BASE_URL", "")
        else {"ok": None, "note": "não configurado"},
        "notify": _ping(settings.NOTIFY_SERVER_URL.rstrip("/") + "/v1/ready")
        if settings.NOTIFY_SERVER_URL
        else {"ok": None, "note": "não configurado"},
        "migrations_pending": _pending_migrations(),
        "deploy": _deploy_info(),
    }
