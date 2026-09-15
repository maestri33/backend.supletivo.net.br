"""Testes unitários e de integração para a sincronização de segredos com o Infisical."""

from unittest.mock import MagicMock, patch
import pytest
from django.core.management import call_command
from io import StringIO

from core.models import PlatformSetting
from core.system_config import get_setting, _SETTINGS_CACHE
from integrations.infisical.client import InfisicalClient, InfisicalClientError
from integrations.infisical.sync import sync_secrets_to_platform
from integrations.infisical.checks import check_infisical_env


@pytest.mark.django_db
def test_infisical_client_initialization():
    client = InfisicalClient(
        base_url="http://custom-infisical:8080",
        project_id="test-proj-id",
        client_id="test-client-id",
        client_secret="test-client-secret",
        environment="staging",
    )
    assert client.base_url == "http://custom-infisical:8080"
    assert client.project_id == "test-proj-id"
    assert client.client_id == "test-client-id"
    assert client.client_secret == "test-client-secret"
    assert client.environment == "staging"


@pytest.mark.django_db
def test_infisical_client_login_success():
    client = InfisicalClient(
        base_url="http://10.0.1.61:8080",
        client_id="test-id",
        client_secret="test-secret",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"accessToken": "mocked-jwt-token-123"}

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        token = client.login()
        assert token == "mocked-jwt-token-123"
        assert client.access_token == "mocked-jwt-token-123"
        mock_post.assert_called_once_with(
            "http://10.0.1.61:8080/api/v1/auth/universal-auth/login",
            json={"clientId": "test-id", "clientSecret": "test-secret"},
        )


@pytest.mark.django_db
def test_infisical_client_login_failure():
    client = InfisicalClient(
        base_url="http://10.0.1.61:8080",
        client_id="bad-id",
        client_secret="bad-secret",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(InfisicalClientError, match="Falha na autenticação"):
            client.login()


@pytest.mark.django_db
def test_infisical_client_get_secrets_success():
    client = InfisicalClient(
        base_url="http://10.0.1.61:8080",
        project_id="1712fb45-2d75-4024-bc6b-0163d5e582a0",
        token="existing-token",
        environment="prod",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "secrets": [
            {"secretKey": "ASAAS_API_KEY", "secretValue": "$aact_prod_123"},
            {"secretKey": "INFINITEPAY_HANDLE", "secretValue": "v7m"},
            {"secretKey": "CPFHUB_API_KEY", "secretValue": "hex_key_456"},
        ]
    }

    with patch("httpx.Client.get", return_value=mock_resp) as mock_get:
        secrets = client.get_secrets(environment="prod")
        assert len(secrets) == 3
        assert secrets["ASAAS_API_KEY"] == "$aact_prod_123"
        assert secrets["INFINITEPAY_HANDLE"] == "v7m"
        assert secrets["CPFHUB_API_KEY"] == "hex_key_456"

        assert client.get_secret("INFINITEPAY_HANDLE", environment="prod") == "v7m"


@pytest.mark.django_db
def test_sync_secrets_to_platform():
    client = InfisicalClient(
        base_url="http://10.0.1.61:8080",
        project_id="1712fb45-2d75-4024-bc6b-0163d5e582a0",
        token="valid-token",
        environment="dev",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "secrets": [
            {"secretKey": "TEST_KEY_A", "secretValue": "secret_value_a"},
            {"secretKey": "TEST_KEY_B", "secretValue": "secret_value_b"},
        ]
    }

    with patch("httpx.Client.get", return_value=mock_resp):
        report = sync_secrets_to_platform(environment="dev", client=client)
        assert report["status"] == "ok"
        assert report["synced_count"] == 2
        assert "TEST_KEY_A" in report["keys"]
        assert "TEST_KEY_B" in report["keys"]

        # Verifica persistência no banco e cache
        assert get_setting("TEST_KEY_A") == "secret_value_a"
        assert get_setting("TEST_KEY_B") == "secret_value_b"
        assert PlatformSetting.objects.filter(key="TEST_KEY_A").exists()


@pytest.mark.django_db
def test_sync_secrets_resilient_on_error():
    client = InfisicalClient(
        base_url="http://10.0.1.61:8080",
        project_id="1712fb45-2d75-4024-bc6b-0163d5e582a0",
        token="invalid-token",
        environment="dev",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    with patch("httpx.Client.get", return_value=mock_resp):
        report = sync_secrets_to_platform(environment="dev", client=client)
        assert report["status"] == "error"
        assert report["synced_count"] == 0
        assert "Falha ao obter segredos" in report["error"]


@pytest.mark.django_db
def test_management_command_sync_infisical_secrets():
    out = StringIO()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "secrets": [
            {"secretKey": "SYNC_TEST_KEY", "secretValue": "val_123"},
        ]
    }

    with patch("httpx.Client.get", return_value=mock_resp):
        call_command(
            "sync_infisical_secrets",
            "--token=dummy_token",
            "--env=dev",
            stdout=out,
        )
        output = out.getvalue()
        assert "Sincronização concluída com sucesso" in output
        assert "SYNC_TEST_KEY" in output
        assert get_setting("SYNC_TEST_KEY") == "val_123"


def test_system_check_infisical_env():
    warnings = check_infisical_env(None)
    # Deve retornar lista de warnings caso não configurado, sem levantar exceção
    assert isinstance(warnings, list)
