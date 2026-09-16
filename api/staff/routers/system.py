"""Router de Diagnóstico de Sistema, Integrações e Logs (Staff)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from ninja import Query, Router

from api.auth import require_superuser
from api.staff.schemas import (
    AiCallLogFilterSchema,
    AiCallLogOut,
    IntegrationDetailOut,
    IntegrationStatusOut,
    SystemStatusOut,
    ValidationCheckLogFilterSchema,
    ValidationCheckLogOut,
)
from integrations import status as integ_status
from users.exceptions import NotFound

router = Router(tags=["staff"])


@router.get("/integrations", response=list[IntegrationStatusOut], summary="Listagem de integrações")
def list_integrations(request):
    """Saúde e configuração das integrações."""
    require_superuser(request.auth)
    return integ_status.list_integrations()


@router.get("/integrations/{name}", response=IntegrationDetailOut, summary="Detalhe de integração")
def integration_detail(request, name: str):
    """Detalhe de integração específica."""
    require_superuser(request.auth)
    data = integ_status.integration_detail(name)
    if data is None:
        raise NotFound("Integração não encontrada.", code="INTEGRATION_NOT_FOUND")
    return data


@router.post("/integrations/asaas/setup", response=dict[str, Any], summary="Configurar webhook Asaas")
def integration_setup(request):
    """Cadastra ou atualiza webhook do Asaas."""
    require_superuser(request.auth)
    from integrations.bank.asaas import onboarding

    return onboarding.setup()


@router.post("/integrations/asaas/test", response=dict[str, Any], summary="Testar integração Asaas")
def integration_test(request):
    """Executa testes de conectividade do Asaas."""
    require_superuser(request.auth)
    from integrations.bank.asaas import onboarding

    return onboarding.run_checks(record=True)


@router.get("/system", response=SystemStatusOut, summary="Status do servidor e infraestrutura")
def system_status(request):
    """Saúde do servidor: banco, migrations, Django-Q e filas."""
    require_superuser(request.auth)
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    db_ok = True
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
    except Exception:
        db_ok = False
    executor = MigrationExecutor(connection)
    pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    clusters: list = []
    queued = None
    success_count = 0
    failure_count = 0
    qcluster_alive = False
    try:
        from django_q.models import OrmQ, Success, Failure
        from django_q.status import Stat
        from django.utils import timezone
        import datetime

        clusters = [s.cluster_id for s in Stat.get_all()]
        queued = OrmQ.objects.count()
        success_count = Success.objects.count()
        failure_count = Failure.objects.count()

        # Verifica se há clusters vivos via Stat OU execução recente de tarefas (últimos 15 min)
        recent_cutoff = timezone.now() - datetime.timedelta(minutes=15)
        recent_activity = Success.objects.filter(stopped__gte=recent_cutoff).exists()
        qcluster_alive = bool(clusters) or recent_activity
    except Exception:
        pass
    return {
        "db_ok": db_ok,
        "migrations_pending": [f"{m.app_label}.{m.name}" for m, _ in pending],
        "qcluster_alive": qcluster_alive,
        "qcluster_count": len(clusters),
        "queued_tasks": queued,
        "success_tasks": success_count,
        "failure_tasks": failure_count,
        "debug": settings.DEBUG,
        "external_url": settings.EXTERNAL_URL,
    }



@router.get("/logs/ai-calls", response=list[AiCallLogOut], summary="Logs de chamadas de IA")
def logs_ai_calls(
    request,
    filters: AiCallLogFilterSchema = Query(default=None),
    limit: int = 100,
):
    """Histórico de chamadas de modelos de IA."""
    require_superuser(request.auth)
    from integrations.ai.models import AiCall

    f = filters if isinstance(filters, AiCallLogFilterSchema) else AiCallLogFilterSchema()
    qs = AiCall.objects.order_by("-created_at")
    if f.status:
        qs = qs.filter(status=f.status)
    return [
        {
            "provider": a.provider,
            "model": a.model,
            "operation": a.operation,
            "caller": a.caller,
            "status": a.status,
            "cost": str(a.cost) if a.cost is not None else None,
            "latency_ms": a.latency_ms,
            "error": a.error,
            "created_at": a.created_at.isoformat(),
        }
        for a in qs[:limit]
    ]


@router.get("/logs/checks", response=list[ValidationCheckLogOut], summary="Logs de verificações de validação")
def logs_checks(
    request,
    filters: ValidationCheckLogFilterSchema = Query(default=None),
    limit: int = 100,
):
    """Histórico do ledger de validações."""
    require_superuser(request.auth)
    from core.models import ValidationCheck

    f = filters if isinstance(filters, ValidationCheckLogFilterSchema) else ValidationCheckLogFilterSchema()
    qs = ValidationCheck.objects.order_by("-checked_at")
    if f.scope:
        qs = qs.filter(scope=f.scope)
    return [
        {
            "scope": c.scope,
            "name": c.name,
            "passed": c.passed,
            "mode": c.mode,
            "detail": c.detail,
            "checked_at": c.checked_at.isoformat(),
        }
        for c in qs[:limit]
    ]
