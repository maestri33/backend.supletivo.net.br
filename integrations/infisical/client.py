"""Cliente HTTP para comunicação com o cofre Infisical via REST API."""

from __future__ import annotations

from typing import Any
import httpx
import structlog
from django.conf import settings

from core.system_config import get_setting

logger = structlog.get_logger()

DEFAULT_INFISICAL_BASE_URL = "http://10.0.1.61:8080"
DEFAULT_INFISICAL_PROJECT_ID = "1712fb45-2d75-4024-bc6b-0163d5e582a0"


class InfisicalClientError(Exception):
    """Erro de comunicação ou autenticação com o Infisical."""


class InfisicalClient:
    """Cliente para consulta e sincronização de segredos no Infisical."""

    def __init__(
        self,
        base_url: str | None = None,
        project_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        token: str | None = None,
        environment: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = (
            base_url
            or get_setting("INFISICAL_BASE_URL")
            or getattr(settings, "INFISICAL_BASE_URL", DEFAULT_INFISICAL_BASE_URL)
        ).rstrip("/")
        self.project_id = (
            project_id
            or get_setting("INFISICAL_PROJECT_ID")
            or getattr(settings, "INFISICAL_PROJECT_ID", DEFAULT_INFISICAL_PROJECT_ID)
        )
        self.client_id = (
            client_id
            or get_setting("INFISICAL_UNIVERSAL_AUTH_CLIENT_ID")
            or getattr(settings, "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID", "")
        )
        self.client_secret = (
            client_secret
            or get_setting("INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET")
            or getattr(settings, "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET", "")
        )
        self.token = (
            token
            or get_setting("INFISICAL_TOKEN")
            or getattr(settings, "INFISICAL_TOKEN", "")
        )
        self.environment = (
            environment
            or get_setting("INFISICAL_ENVIRONMENT")
            or getattr(settings, "INFISICAL_ENVIRONMENT", "dev")
        )
        self.timeout = timeout
        self.access_token: str | None = self.token or None

    def login(self) -> str:
        """Autentica via Universal Auth e obtém o accessToken."""
        if self.access_token:
            return self.access_token

        if not self.client_id or not self.client_secret:
            raise InfisicalClientError(
                "Credenciais de Universal Auth (client_id / client_secret) ou token não configuradas."
            )

        url = f"{self.base_url}/api/v1/auth/universal-auth/login"
        payload = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
        }

        try:
            with httpx.Client(timeout=self.timeout) as http:
                resp = http.post(url, json=payload)
                if resp.status_code != 200:
                    logger.warning(
                        "infisical.auth_failed",
                        status_code=resp.status_code,
                        body=resp.text[:200],
                    )
                    raise InfisicalClientError(
                        f"Falha na autenticação do Infisical: HTTP {resp.status_code}"
                    )
                data = resp.json()
                token = data.get("accessToken") or data.get("token")
                if not token:
                    raise InfisicalClientError("Token não retornado pelo Infisical no login.")
                self.access_token = token
                return token
        except httpx.RequestError as exc:
            logger.error("infisical.network_error", error=str(exc), url=url)
            raise InfisicalClientError(f"Erro de rede ao conectar no Infisical: {exc}") from exc

    def get_secrets(
        self,
        environment: str | None = None,
        secret_path: str = "/",
    ) -> dict[str, str]:
        """Puxa todos os segredos do ambiente e projeto informados.

        Retorna dicionário {CHAVE: VALOR}.
        """
        token = self.login()
        env = environment or self.environment
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        # Tentativa 1: workspaceId (Project ID)
        params: dict[str, Any] = {
            "workspaceId": self.project_id,
            "environment": env,
            "secretPath": secret_path,
        }
        url = f"{self.base_url}/api/v3/secrets/raw"

        try:
            with httpx.Client(timeout=self.timeout) as http:
                resp = http.get(url, params=params, headers=headers)
                # Se workspaceId falhar com 400/404, tenta projectId
                if resp.status_code in (400, 404):
                    params = {
                        "projectId": self.project_id,
                        "environment": env,
                        "secretPath": secret_path,
                    }
                    resp = http.get(url, params=params, headers=headers)

                if resp.status_code != 200:
                    logger.warning(
                        "infisical.get_secrets_failed",
                        status_code=resp.status_code,
                        project_id=self.project_id,
                        environment=env,
                    )
                    raise InfisicalClientError(
                        f"Falha ao obter segredos do Infisical: HTTP {resp.status_code}"
                    )

                data = resp.json()
                raw_secrets = data.get("secrets", [])
                result: dict[str, str] = {}
                for item in raw_secrets:
                    key = item.get("secretKey") or item.get("key")
                    val = item.get("secretValue") or item.get("value")
                    if key is not None and val is not None:
                        result[str(key)] = str(val)

                logger.info(
                    "infisical.secrets_fetched",
                    environment=env,
                    count=len(result),
                )
                return result
        except httpx.RequestError as exc:
            logger.error("infisical.network_error", error=str(exc), url=url)
            raise InfisicalClientError(f"Erro de rede ao buscar segredos do Infisical: {exc}") from exc

    def get_secret(
        self,
        secret_name: str,
        environment: str | None = None,
        secret_path: str = "/",
    ) -> str | None:
        """Busca o valor de um segredo específico."""
        secrets = self.get_secrets(environment=environment, secret_path=secret_path)
        return secrets.get(secret_name)
