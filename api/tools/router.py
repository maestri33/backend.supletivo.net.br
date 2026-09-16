from __future__ import annotations

from datetime import datetime

from api.base import COMMON_ERROR_REGISTRY, build_group
from api.tools.schemas import (
    CronJobItemOut,
    CronRunOut,
    ToolLeadOut,
    ToolsNotifyIn,
    ToolsNotifySentOut,
    TurnstileVerifyIn,
    TurnstileVerifyOut,
)
from core.net import require_internal_ip
from core.webhook_auth import service_secret_ok
from users.exceptions import ValidationError
from users.profiles import interface as profiles
from users.roles.lead import service as lead_iface
from users.roles.lead.models import Lead


def service_secret_auth(request):
    """Auth callable do Ninja: exige o segredo de serviço interno (mesmo dos webhooks/bot login).

    Truthy => vira `request.auth`; None => Ninja levanta `AuthenticationError` → 401 padronizado
    (`api/base.py`). Fail-closed: `BOT_SERVICE_SECRET` vazio no .env => `service_secret_ok` False =>
    401. É a auth REAL exigida ALÉM do gate de IP (`require_internal_ip`) nas rotas abaixo."""
    return True if service_secret_ok(request) else None


def cron_secret_auth(request):
    """Auth para endpoints de Cron Trigger (Cloudflare Cron / agendadores externos).

    Segregação de privilégios: aceita CRON_SERVICE_SECRET dedicado (header x-cron-secret)
    ou BOT_SERVICE_SECRET como fallback seguro.
    """
    from core.webhook_auth import cron_secret_ok

    return True if cron_secret_ok(request) else None


_ERROR_REGISTRY = (
    COMMON_ERROR_REGISTRY
    + """
### Códigos específicos de tools (serviços externos)

| code | quando | extras |
|---|---|---|
| `UNAUTHORIZED` | sem o segredo de serviço no header (401) | — |
| `INVALID_STATUS` | `status` fora de pending/paid/failed (422) | — |
| `DATE_INVALID` | `created_after` não é ISO-8601 (422) | — |
"""
)

api = build_group(
    "tools",
    "Ferramentas internas de integração — radar de leads + disparo de notificação. "
    "Rotas de negócio exigem segredo de serviço (header) ALÉM de IP interno (DMZ).\n"
    + _ERROR_REGISTRY,
)

_MAX_LIMIT = 500


@api.get(
    "/leads",
    response=list[ToolLeadOut],
    auth=service_secret_auth,
    tags=["tools"],
    summary="Radar de leads para integrações",
)
def tools_leads(
    request,
    status: str | None = None,
    created_after: str | None = None,
    limit: int = 100,
):
    """Radar de leads: todos os leads (mais novos primeiro), com nome/telefone/link de pagamento.

    Filtros: `status` (pending/paid/failed), `created_after` (ISO-8601), `limit` (1..500, default 100)."""
    require_internal_ip(request)
    if status and status not in Lead.Status.values:
        raise ValidationError(
            f"Status inválido: {status} (use {'/'.join(Lead.Status.values)}).",
            code="INVALID_STATUS",
        )
    parsed_after = None
    if created_after:
        try:
            parsed_after = datetime.fromisoformat(created_after)
        except ValueError as exc:
            raise ValidationError(
                "created_after inválido (use ISO-8601, ex.: 2026-07-01 ou 2026-07-01T12:00:00-03:00).",
                code="DATE_INVALID",
            ) from exc
    limit = max(1, min(limit, _MAX_LIMIT))
    rows = lead_iface.list_leads(
        hub=None, status=status, created_after=parsed_after, limit=limit
    )
    pmap = profiles.get_map([lead.user for lead in rows])
    return [lead_iface.lead_to_dict(lead, profile=pmap.get(lead.user_id)) for lead in rows]


@api.post(
    "/notifications/send",
    response=ToolsNotifySentOut,
    auth=service_secret_auth,
    tags=["tools"],
    summary="Disparo ad-hoc de notificações",
)
def tools_notifications_send(request, payload: ToolsNotifyIn):
    """Gatilho de disparo: envia WhatsApp e/ou e-mail a um USUÁRIO (`user_external_id`, herda
    phone/email do Profile) OU a um destino LIVRE (`phone`/`email`). `channels` opcional (default:
    todos com destino). Devolve o `external_id` da notificação enfileirada (audit no notify)."""
    require_internal_ip(request)

    from notify.interface.send import send_adhoc

    external_id = send_adhoc(
        message=payload.message,
        to_user=payload.user_external_id,
        phone=payload.phone,
        email=payload.email,
        subject=payload.subject,
        channels=payload.channels,
        caller="tools.send",
    )
    return {"external_id": external_id}


@api.post(
    "/turnstile/verify",
    response=TurnstileVerifyOut,
    auth=None,
    tags=["tools"],
    summary="Validação e diagnóstico de token Cloudflare Turnstile",
)
def tools_turnstile_verify(request, payload: TurnstileVerifyIn):
    """Valida um token emitido pelo widget Cloudflare Turnstile contra a API siteverify."""
    from core.request import get_client_ip
    from integrations.turnstile import verify_turnstile

    client_ip = payload.remote_ip or get_client_ip(request)
    result = verify_turnstile(payload.token, remote_ip=client_ip)
    return {
        "success": result.success,
        "challenge_ts": result.challenge_ts,
        "hostname": result.hostname,
        "error_codes": result.error_codes,
        "action": result.action,
        "cdata": result.cdata,
    }


# ── Cron Triggers Endpoints (Cloudflare-first / zero 24/7 worker cost) ───────

@api.get(
    "/cron/jobs",
    response=list[CronJobItemOut],
    auth=service_secret_auth,
    tags=["cron"],
    summary="Listar tarefas agendadas registradas para Cron Trigger",
)
def cron_jobs_list(request):
    """Lista todos os jobs seguros disponíveis para disparo por Cron Trigger."""
    from core.tasks import CRON_REGISTRY

    return [
        {"job": k, "func": v["func"], "description": v["description"]}
        for k, v in CRON_REGISTRY.items()
    ]


@api.post(
    "/cron/run/{job_name}",
    response=CronRunOut,
    auth=cron_secret_auth,
    tags=["cron"],
    summary="Executar job do CRON_REGISTRY por nome",
)
def cron_run_job(request, job_name: str):
    """Dispara a execução de um job agendado cadastrado no CRON_REGISTRY."""
    from ninja.errors import HttpError
    from core.tasks import run_cron_job

    try:
        res = run_cron_job(job_name)
    except ValueError as exc:
        raise ValidationError(str(exc), code="INVALID_JOB") from exc

    if res.get("status") == "failure":
        raise HttpError(500, res.get("error", "Erro na execução do job agendado"))
    return res


@api.post(
    "/cron/finance/weekly-closing",
    response=CronRunOut,
    auth=cron_secret_auth,
    tags=["cron"],
    summary="Webhook para Cloudflare Cron Trigger: Fechamento semanal financeiro",
)
def cron_finance_weekly_closing(request):
    """Gatilho semanal (sexta 18h): fecha a semana e cria as solicitações de pagamento."""
    from ninja.errors import HttpError
    from core.tasks import run_cron_job

    res = run_cron_job("finance_weekly_closing")
    if res.get("status") == "failure":
        raise HttpError(500, res.get("error", "Erro no fechamento financeiro semanal"))
    return res


@api.post(
    "/cron/finance/payouts",
    response=CronRunOut,
    auth=cron_secret_auth,
    tags=["cron"],
    summary="Webhook para Cloudflare Cron Trigger: Processamento de payouts",
)
def cron_finance_payouts(request):
    """Gatilho periódico: envia e reconcilia solicitações de pagamento pendentes."""
    from ninja.errors import HttpError
    from core.tasks import run_cron_job

    res = run_cron_job("finance_payouts")
    if res.get("status") == "failure":
        raise HttpError(500, res.get("error", "Erro no processamento de payouts"))
    return res


@api.post(
    "/cron/selfies/age-stale",
    response=CronRunOut,
    auth=cron_secret_auth,
    tags=["cron"],
    summary="Webhook para Cloudflare Cron Trigger: Envelhecimento de selfies pendentes (TTL)",
)
def cron_selfies_age_stale(request):
    """Gatilho a cada 10 min: marca selfies pending com TTL estourado como review."""
    from ninja.errors import HttpError
    from core.tasks import run_cron_job

    res = run_cron_job("all_age_stale_selfies")
    if res.get("status") == "failure":
        raise HttpError(500, res.get("error", "Erro no envelhecimento de selfies"))
    return res

