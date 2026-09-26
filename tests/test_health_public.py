import pytest


pytestmark = pytest.mark.django_db


def test_healthz_e_publico_e_reporta_banco(client):
    from django.conf import settings

    response = client.get("/api/v1/health/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["db"] is True
    assert response.json()["version"] == settings.APP_VERSION
    assert response.headers.get("X-Platform-Version") == settings.APP_VERSION


def test_grupos_normais_continuam_exigindo_jwt(client):
    response = client.get("/api/v1/collaborators/whoami")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
