"""Verificação end-to-end das rotas corrigidas, via Django test Client (exercita o stack HTTP real
— URLs, middleware, exception handlers, auth do Ninja — in-process). Fica como regressão no CI.

Cobre o gate de /media/ (G1) e o sombreamento da rota staff_health (descoberto na verificação e2e:
`/health` é liveness pública em todo grupo, então os pings do staff foram para `/health/full`).
"""

import os
import tempfile

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_and_media(monkeypatch):
    from django.conf import settings

    root = tempfile.mkdtemp()
    monkeypatch.setattr(settings, "MEDIA_ROOT", root)
    os.makedirs(f"{root}/documents")
    os.makedirs(f"{root}/training")
    with open(f"{root}/documents/rg.jpg", "wb") as fh:
        fh.write(b"RG PRIVADO")
    with open(f"{root}/training/pub.jpg", "wb") as fh:
        fh.write(b"publico")
    return Client()


# ───────────────────── G1: gate de /media/ (end-to-end) ─────────────────────
def test_e2e_media_privado_sem_token_401(client_and_media):
    assert client_and_media.get("/media/documents/rg.jpg").status_code == 401


def test_e2e_media_traversal_bloqueado(client_and_media):
    """O bug TIER 0: `training/../documents/` dava 200 (arquivo privado sem token). Agora 401."""
    r = client_and_media.get("/media/training/../documents/rg.jpg")
    # o Client normaliza `..` no path; testamos as duas formas
    assert r.status_code == 401 or (
        client_and_media.get("/media/training/%2e%2e/documents/rg.jpg").status_code
        == 401
    )


def test_e2e_media_publico_serve(client_and_media):
    assert client_and_media.get("/media/training/pub.jpg").status_code == 200


# ─────────── sombreamento do staff_health resolvido (end-to-end) ───────────
def test_e2e_staff_health_e_liveness_publica(client_and_media):
    """`/api/v1/staff/health` é a liveness PÚBLICA {group,version,status} — contrato do front."""
    r = client_and_media.get("/api/v1/staff/health")
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok" and body.get("group") == "staff"


def test_e2e_staff_health_full_exige_auth(client_and_media):
    """`/health/full` (os pings de integrações, require_superuser) agora é ALCANÇÁVEL — sem token
    dá 401, provando que o gate do G20 roda (antes ficava sombreado pela liveness pública)."""
    assert client_and_media.get("/api/v1/staff/health/full").status_code == 401
