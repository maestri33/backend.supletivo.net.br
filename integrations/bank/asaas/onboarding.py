"""Onboarding/self-test do asaas: a bateria que roda no boot e no POST /setup/, e o auto-cadastro
do webhook de eventos no Asaas (porte de config_key.py/config_status.py do micro legado, sem o HMAC
— que era delírio; o Asaas autentica o webhook só pelo header `asaas-access-token`).

- `run_checks()`  -> READ-ONLY: relatório de prontidão (env + testa a key via saldo + lista os
  webhooks e diz se o nosso já está cadastrado). Não muta o Asaas. Carimba cada sub-check no ledger.
- `setup(force)`  -> a bateria + ping REAL da EXTERNAL_URL (url_verify) + auto-cadastro do webhook se
  a URL voltou. Idempotente: webhook já cadastrado (casa por URL) e não-force => NÃO recria (evita
  churn a cada boot); force=True deleta+recria (resync do authToken). É o que o boot e o /setup/ chamam.
"""

from __future__ import annotations

import asyncio

import structlog
from django.conf import settings

from core.validation import record_check

from . import url_verify
from .client import AsaasError, get_client

logger = structlog.get_logger()

# Eventos assinados no webhook — porte da WEBHOOK_EVENTS do legado (7 TRANSFER_* + 19 PAYMENT_*).
# Eventos não mapeados permanecem no WebhookEvent bruto e geram warning.
WEBHOOK_EVENTS = [
    # outbound (TRANSFER_*)
    "TRANSFER_CREATED",
    "TRANSFER_PENDING",
    "TRANSFER_IN_BANK_PROCESSING",
    "TRANSFER_DONE",
    "TRANSFER_FAILED",
    "TRANSFER_CANCELLED",
    "TRANSFER_BLOCKED",
    # inbound (PAYMENT_*)
    "PAYMENT_CREATED",
    "PAYMENT_AWAITING_RISK_ANALYSIS",
    "PAYMENT_APPROVED_BY_RISK_ANALYSIS",
    "PAYMENT_REPROVED_BY_RISK_ANALYSIS",
    "PAYMENT_UPDATED",
    "PAYMENT_CONFIRMED",
    "PAYMENT_RECEIVED",
    "PAYMENT_OVERDUE",
    "PAYMENT_DELETED",
    "PAYMENT_RESTORED",
    "PAYMENT_REFUNDED",
    "PAYMENT_RECEIVED_IN_CASH_UNDONE",
    "PAYMENT_CHARGEBACK_REQUESTED",
    "PAYMENT_CHARGEBACK_DISPUTE",
    "PAYMENT_AWAITING_CHARGEBACK_REVERSAL",
    "PAYMENT_DUNNING_RECEIVED",
    "PAYMENT_DUNNING_REQUESTED",
    "PAYMENT_BANK_SLIP_VIEWED",
    "PAYMENT_CHECKOUT_VIEWED",
]

WEBHOOK_PATH = "/integrations/asaas/webhook/"


def target_webhook_url() -> str:
    """URL pública do nosso receiver (EXTERNAL_URL + path). '' se não houver EXTERNAL_URL."""
    from core.system_config import get_setting

    base = (get_setting("EXTERNAL_URL", getattr(settings, "EXTERNAL_URL", "")) or "").rstrip("/")
    return f"{base}{WEBHOOK_PATH}" if base else ""


def _find_our_webhook(webhooks_resp: dict | None) -> dict | None:
    """Acha o NOSSO webhook na lista do Asaas: casa por URL do receiver (nome só como fallback).

    Casar por URL evita confundir com o webhook legado (`asaas-app-managed` -> api.maestri.group).
    """
    if not webhooks_resp:
        return None
    wanted_url = target_webhook_url()
    name = getattr(settings, "ASAAS_WEBHOOK_NAME", "dmz-asaas-managed")
    for w in webhooks_resp.get("data") or []:
        if wanted_url and w.get("url") == wanted_url:
            return w
        if w.get("name") == name:
            return w
    return None


# ── bateria read-only ────────────────────────────────────────────────────────────────


async def _probe() -> dict:
    """Chamadas de LEITURA ao Asaas (não move/cria nada): saldo + lista de webhooks."""
    async with get_client() as c:
        balance = await c.get_balance()
        try:
            webhooks = await c.list_webhooks()
        except AsaasError:
            webhooks = None
    return {"balance": balance, "webhooks": webhooks}


def run_checks(*, record: bool = True) -> dict:
    """Relatório read-only de prontidão do asaas. NÃO muta o Asaas. Carimba o ledger se record=True."""
    from core.system_config import get_setting

    api_key = get_setting("ASAAS_API_KEY", getattr(settings, "ASAAS_API_KEY", ""))
    webhook_secret = get_setting("ASAAS_WEBHOOK_SECRET", getattr(settings, "ASAAS_WEBHOOK_SECRET", ""))
    external_url = get_setting("EXTERNAL_URL", getattr(settings, "EXTERNAL_URL", ""))

    out = {
        "integration": "asaas",
        "api_key_in_env": bool(api_key),
        "webhook_secret_in_env": bool(webhook_secret),
        "external_url_in_env": bool(external_url),
        "api_key_tested_ok": False,
        "webhook_registered": None,
        "ready": False,
        "hints": [],
    }

    if not out["api_key_in_env"]:
        out["hints"].append(
            "Cole ASAAS_API_KEY no .env (sem ela o boot erra: asaas.E001)."
        )
        return out

    try:
        probe = asyncio.run(_probe())
    except AsaasError as e:
        out["error"] = {"status_code": e.status_code, "body": e.body}
        out["hints"].append(
            "A key não validou no Asaas (ver error). Confira ASAAS_API_KEY."
        )
        if record:
            record_check(
                "asaas",
                "api_key_tested_ok",
                False,
                mode="real",
                detail=f"asaas {e.status_code}: {e.body}",
            )
        return out

    out["api_key_tested_ok"] = True
    out["balance"] = probe["balance"].get("balance") if probe["balance"] else None
    out["webhook_registered"] = _find_our_webhook(probe["webhooks"])
    if record:
        record_check(
            "asaas",
            "api_key_tested_ok",
            True,
            mode="real",
            detail=f"balance={out['balance']}",
        )
        record_check(
            "asaas",
            "webhook_registered",
            bool(out["webhook_registered"]),
            mode="real",
            detail=(out["webhook_registered"] or {}).get("id") or "ausente",
        )

    if not out["webhook_secret_in_env"]:
        out["hints"].append(
            "Defina ASAAS_WEBHOOK_SECRET no .env (authToken do webhook)."
        )
    if not out["external_url_in_env"]:
        out["hints"].append("Defina EXTERNAL_URL no .env (URL pública do webhook).")
    if not out["webhook_registered"]:
        out["hints"].append(
            "Webhook não cadastrado — rode POST /integrations/asaas/setup/."
        )

    out["ready"] = bool(
        out["api_key_tested_ok"]
        and out["webhook_secret_in_env"]
        and out["external_url_in_env"]
        and out["webhook_registered"]
    )
    return out


# ── auto-cadastro do webhook ──────────────────────────────────────────────────────────


async def _list_and_find(client) -> dict | None:
    try:
        res = await client.list_webhooks()
    except AsaasError:
        return None
    return _find_our_webhook(res)


async def register_webhook(*, force: bool = False) -> tuple[dict, str]:
    """Cadastra (ou recria, se force) o webhook de eventos. Retorna (webhook, action).

    action: `already_registered` (achou e não forçou) | `created` | `recreated`. authToken =
    ASAAS_WEBHOOK_SECRET — é o que o Asaas ecoa em `asaas-access-token` e o nosso check valida.
    """
    target = target_webhook_url()
    async with get_client() as c:
        existing = await _list_and_find(c)
        if existing and not force:
            return existing, "already_registered"
        if existing and force:
            try:
                await c.delete_webhook(existing["id"])
            except AsaasError:
                pass
        # o Asaas exige email não-vazio no webhook -> usa o da conta autenticada
        account = await c.get_my_account()
        from core.system_config import get_setting

        webhook_secret = get_setting("ASAAS_WEBHOOK_SECRET", getattr(settings, "ASAAS_WEBHOOK_SECRET", ""))
        payload = {
            "name": getattr(settings, "ASAAS_WEBHOOK_NAME", "dmz-asaas-managed"),
            "url": target,
            "email": account.get("email") or "webhook@invalid.local",
            "enabled": True,
            "interrupted": False,
            "apiVersion": 3,
            "authToken": webhook_secret,
            "sendType": "SEQUENTIALLY",  # obrigatório (confirmado no teste 1a-iv)
            "events": WEBHOOK_EVENTS,
        }
        created = await c.create_webhook(payload)
        return created, ("recreated" if existing else "created")


def account_balance() -> dict:
    """Saldo da conta Asaas (read-only, wrapper sync) — pro painel financeiro do staff (WP6).

    Roda na thread do request (runserver/gunicorn), onde `asyncio.run` é seguro. Sem mutar nada."""
    from core.system_config import get_setting

    api_key = get_setting("ASAAS_API_KEY", getattr(settings, "ASAAS_API_KEY", ""))

    async def _b():
        async with get_client() as c:
            return await c.get_balance()

    if not api_key:
        return {"error": "ASAAS_API_KEY ausente no .env"}
    try:
        return asyncio.run(_b())
    except AsaasError as e:
        return {"error": {"status_code": e.status_code, "body": e.body}}
    except Exception as e:  # noqa: BLE001 — rede/timeout: painel vê erro estruturado, não 500
        return {"error": {"detail": str(e)}}


def setup(*, force: bool = False) -> dict:
    """Bateria + ping REAL da EXTERNAL_URL + auto-cadastro do webhook. Chamado pelo boot e pelo /setup/.

    Pré-requisitos pra cadastrar: key válida + ASAAS_WEBHOOK_SECRET + EXTERNAL_URL no .env + a URL
    verificada pelo ping. Faltou algo -> reporta e não cadastra (só leitura).
    """
    from core.system_config import get_setting

    webhook_secret = get_setting("ASAAS_WEBHOOK_SECRET", getattr(settings, "ASAAS_WEBHOOK_SECRET", ""))
    external_url = get_setting("EXTERNAL_URL", getattr(settings, "EXTERNAL_URL", ""))

    report = run_checks(record=True)
    report["url_verified"] = None
    report["webhook_action"] = "skipped"

    if not report.get("api_key_tested_ok"):
        return report
    if not webhook_secret:
        report["hints"].append(
            "Sem ASAAS_WEBHOOK_SECRET no .env — webhook NÃO cadastrado."
        )
        return report
    if not external_url:
        report["hints"].append("Sem EXTERNAL_URL no .env — webhook NÃO cadastrado.")
        return report

    # já cadastrado e não forçando -> idempotente: não pinga nem recria (evita churn a cada boot)
    if report.get("webhook_registered") and not force:
        report["webhook_action"] = "already_registered"
        return report

    # Ping da EXTERNAL_URL = sinal BEST-EFFORT (informativo), NÃO é o gate. De dentro deste host de
    # dev o app não alcança o domínio público (egress — ver skill testar-url-via-exit-node; a
    # «PENDÊNCIA: egress do app pelo Oracle» segue sem definição, então não roteamos por conta). O
    # GATE de cadastro é a PRESENÇA de EXTERNAL_URL no .env (spec original do Victor, asaas2.md); a
    # reachability pública REAL é verificada à parte pelo exit-node e registrada em .claude/tests.
    # Onde o ping funcionar (prod), vira prova forte; onde não, é só informativo e não bloqueia.
    verified, detail = url_verify.self_ping()
    report["url_verified"] = verified
    record_check("asaas", "webhook_url_verified", verified, mode="real", detail=detail)

    try:
        webhook, action = asyncio.run(register_webhook(force=force))
    except AsaasError as e:
        report["webhook_action"] = "failed"
        report["error"] = {"status_code": e.status_code, "body": e.body}
        record_check(
            "asaas",
            "webhook_registered",
            False,
            mode="real",
            detail=f"asaas {e.status_code}: {e.body}",
        )
        return report

    report["webhook_action"] = action
    report["webhook_registered"] = webhook
    record_check(
        "asaas",
        "webhook_registered",
        True,
        mode="real",
        detail=f"{action} id={webhook.get('id')} url={webhook.get('url')}",
    )
    report["ready"] = bool(
        webhook_secret and external_url and webhook
    )
    return report


def boot_selftest() -> dict | None:
    """Task do Django-Q enfileirada no boot (AsaasConfig): roda a bateria + auto-cadastro do webhook
    num WORKER estável, em vez de numa thread daemon do boot.

    Por que task e não thread: `setup()` faz I/O de rede via `asyncio.run()`. Rodá-la numa thread
    daemon do boot quebrava sob o qcluster — `RuntimeError: cannot schedule new futures after
    interpreter shutdown` (o executor padrão do asyncio recusa futures quando o processo entra em
    shutdown). No worker do Django-Q o `asyncio.run()` roda igual ao payout/charge/qrpay (provado),
    sem corrida com o shutdown. Falha de rede só loga — NÃO relança (sem retry em loop).
    """
    try:
        report = setup()
    except Exception as exc:  # noqa: BLE001 — task de boot nunca deve estourar nem entrar em retry-loop
        logger.error("asaas_boot_selftest_failed", error=str(exc))
        return None
    logger.info(
        "asaas_boot_selftest",
        api_key_tested_ok=report.get("api_key_tested_ok"),
        url_verified=report.get("url_verified"),
        webhook_action=report.get("webhook_action"),
        webhook_registered=bool(report.get("webhook_registered")),
        ready=report.get("ready"),
    )
    return report
