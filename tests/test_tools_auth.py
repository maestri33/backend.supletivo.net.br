"""Grupo `tools` (api/tools.py): as rotas de negócio (`GET /leads`, `POST /notifications/send`)
vazavam PII / disparavam notificação protegidas SÓ por IP (`require_internal_ip`) — `auth=None`.

Hardening 2026-07-10: além do IP interno (satisfeito pelo REMOTE_ADDR 127.0.0.1 do test client),
exigem o SEGREDO DE SERVIÇO no header (`service_secret_auth` → mesmo mecanismo dos webhooks/bot).
Sem o segredo → 401, MESMO vindo de IP interno. Com o segredo → passa a auth.
"""

import pytest

pytestmark = pytest.mark.django_db


def test_leads_sem_segredo_de_ip_interno_401(client):
    """CORE do fix: IP interno NÃO basta mais — sem o segredo de serviço a rota 401a."""
    resp = client.get("/api/v1/tools/leads")
    assert resp.status_code == 401


def test_notifications_send_sem_segredo_401(client):
    resp = client.post(
        "/api/v1/tools/notifications/send",
        data={"message": "oi"},
        content_type="application/json",
    )
    assert resp.status_code == 401


def test_leads_com_segredo_e_ip_interno_passa(client, bot_headers):
    """Caminho legítimo (bot/serviço interno com o segredo): auth OK → 200 (lista vazia no DB limpo)."""
    resp = client.get("/api/v1/tools/leads", **bot_headers)
    assert resp.status_code == 200
    assert resp.json() == []


def test_leads_com_segredo_errado_401(client):
    resp = client.get("/api/v1/tools/leads", HTTP_X_BOT_SERVICE_TOKEN="segredo_errado")
    assert resp.status_code == 401
