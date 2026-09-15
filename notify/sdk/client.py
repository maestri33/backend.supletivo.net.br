"""Cliente HTTP fino do notify-server.

Fala com a API /v1 do notify-server: send, send-event, notifications e phone/check. Zero regra de negócio — payload pronto entra, dict da
resposta sai; roteamento/montagem moram em notify/interface e o retry no Django-Q (notify/sdk/push).

Convenções do servidor (recon R6):
- Auth: header `Authorization: Bearer <NOTIFY_API_KEY>` — NUNCA logar a key.
- A chave de idempotência chama-se `external_id` no POST /v1/send e `idempotency_key` no
  POST /v1/send-event (mesmo campo no servidor; nomenclatura herdada da API).
- 404 do /v1/send-event = evento inexistente/trigger inativo/sem canal → None (paridade com o
  None do caminho local). Qualquer outro >=400 vira NotifyServerError(status_code, body).
"""

from __future__ import annotations

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


class NotifyServerError(Exception):
    """notify-server respondeu não-2xx. Guarda status_code + body p/ quem chama mapear."""

    def __init__(self, status_code: int, body, message: str = ""):
        self.status_code = status_code
        self.body = body
        super().__init__(message or f"notify-server {status_code}: {body!r}")


def _request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    timeout: float | None = None,
) -> httpx.Response:
    """Monta e executa a chamada HTTP (síncrona). Ponto ÚNICO de rede — monkeypatch nos testes."""
    if timeout is None:
        timeout = settings.NOTIFY_TIMEOUT
    with httpx.Client(
        base_url=settings.NOTIFY_SERVER_URL,
        headers={"Authorization": f"Bearer {settings.NOTIFY_API_KEY}"},
        timeout=timeout,
    ) as client:
        return client.request(method, path, json=json, params=params)


async def _request_async(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    timeout: float | None = None,
) -> httpx.Response:
    """Versão async do `_request` — p/ callers que já rodam dentro de event loop (_wa_check)."""
    if timeout is None:
        timeout = settings.NOTIFY_TIMEOUT
    async with httpx.AsyncClient(
        base_url=settings.NOTIFY_SERVER_URL,
        headers={"Authorization": f"Bearer {settings.NOTIFY_API_KEY}"},
        timeout=timeout,
    ) as client:
        return await client.request(method, path, json=json)


def _error_body(resp):
    """Body do erro decodificado (JSON quando dá; 500 do servidor vem em HTML → texto cru)."""
    try:
        return resp.json()
    except Exception:  # noqa: BLE001 — body de erro pode ser qualquer coisa
        return resp.text


def _ok(resp, method: str, path: str):
    """2xx → JSON da resposta; >=400 → NotifyServerError (log warning, sem a key)."""
    if resp.status_code >= 400:
        logger.warning(
            "notify.sdk.error", method=method, path=path, status=resp.status_code
        )
        raise NotifyServerError(resp.status_code, _error_body(resp))
    logger.debug(
        "notify.sdk.request", method=method, path=path, status=resp.status_code
    )
    return resp.json()


def post_send(payload: dict, *, run_sync: bool = False) -> dict:
    """POST /v1/send (payload no shape SendIn). run_sync usa o timeout folgado (despacho inline)."""
    timeout = settings.NOTIFY_SYNC_TIMEOUT if run_sync else settings.NOTIFY_TIMEOUT
    resp = _request("POST", "/v1/send", json=payload, timeout=timeout)
    return _ok(resp, "POST", "/v1/send")


def post_send_event(payload: dict, *, run_sync: bool = False) -> dict | None:
    """POST /v1/send-event (shape SendEventIn). 404 = não disparado → None (paridade local)."""
    timeout = settings.NOTIFY_SYNC_TIMEOUT if run_sync else settings.NOTIFY_TIMEOUT
    resp = _request("POST", "/v1/send-event", json=payload, timeout=timeout)
    if resp.status_code == 404:
        logger.debug(
            "notify.sdk.request", method="POST", path="/v1/send-event", status=404
        )
        return None
    return _ok(resp, "POST", "/v1/send-event")


def get_notifications(
    caller: str | None = None,
    whatsapp_status: str | None = None,
    email_status: str | None = None,
    tts_status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """GET /v1/notifications com os filtros opcionais do servidor (proxy do /history do staff)."""
    params: dict = {"limit": limit}
    if caller:
        params["caller"] = caller
    if whatsapp_status:
        params["whatsapp_status"] = whatsapp_status
    if email_status:
        params["email_status"] = email_status
    if tts_status:
        params["tts_status"] = tts_status
    resp = _request("GET", "/v1/notifications", params=params)
    return _ok(resp, "GET", "/v1/notifications")


def get_notification(external_id: str) -> dict | None:
    """GET /v1/notifications/{external_id}. 404 → None (usado pelo CLI notify_send em modo remote,
    onde não existe row local pra consultar — achado do review adversarial)."""
    path = f"/v1/notifications/{external_id}"
    resp = _request("GET", path)
    if resp.status_code == 404:
        return None
    return _ok(resp, "GET", path)


def phone_check(numbers: list[str]) -> list[dict]:
    """POST /v1/phone/check → [{number, exists}] (na ordem enviada, resolvida pela Evolution)."""
    resp = _request("POST", "/v1/phone/check", json={"numbers": numbers})
    return _ok(resp, "POST", "/v1/phone/check")


def phone_avatar(number: str) -> str | None:
    """POST /v1/phone/avatar → {number, photo} — URL da foto de perfil, ou null.

    Rota SEPARADA do phone/check de propósito: o check roda DENTRO do request do
    auth.check (latência conta); a foto é buscada em task async (lead.tasks) só
    quando a conta acabou de nascer. Sem foto/privada → photo:null → None."""
    resp = _request("POST", "/v1/phone/avatar", json={"number": number})
    data = _ok(resp, "POST", "/v1/phone/avatar")
    photo = (data or {}).get("photo")
    return photo if isinstance(photo, str) and photo else None


async def phone_check_async(numbers: list[str]) -> list[dict]:
    """Versão async do `phone_check` — o `_wa_check` do auth roda dentro do event loop."""
    resp = await _request_async("POST", "/v1/phone/check", json={"numbers": numbers})
    return _ok(resp, "POST", "/v1/phone/check")
