"""Cliente Cloudflare Workers AI para inferência serverless de alta velocidade e baixo custo.

Suporta primariamente o modelo Whisper (`@cf/openai/whisper`) para transcrição
de áudio (STT) com Keep-Alive reutilizável via integrations.ai.http.
"""

from __future__ import annotations

import httpx
import structlog
from django.conf import settings

from .http import get_ai_http_client

logger = structlog.get_logger()

DEFAULT_WHISPER_MODEL = "@cf/openai/whisper"


def is_workers_ai_configured() -> bool:
    """Retorna True se o token de API e o Account ID da Cloudflare estiverem configurados."""
    return bool(
        getattr(settings, "CLOUDFLARE_API_TOKEN", "")
        and getattr(settings, "CLOUDFLARE_ACCOUNT_ID", "")
    )


class CloudflareWorkersAIError(Exception):
    """Erro retornado pela API do Cloudflare Workers AI."""
    def __init__(self, message: str, status_code: int = 0):
        self.status_code = status_code
        super().__init__(message)


class CloudflareWorkersAIClient:
    """Cliente assíncrono para o Cloudflare Workers AI."""

    def __init__(
        self,
        *,
        account_id: str | None = None,
        api_token: str | None = None,
        timeout: float = 60.0,
    ):
        self.account_id = account_id or getattr(settings, "CLOUDFLARE_ACCOUNT_ID", "")
        self.api_token = api_token or getattr(settings, "CLOUDFLARE_API_TOKEN", "")
        self.timeout = timeout
        self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}/ai/run"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
        }

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        mime_type: str = "audio/mpeg",
        model: str = DEFAULT_WHISPER_MODEL,
    ) -> str:
        """Transcreve áudio para texto via @cf/openai/whisper no Cloudflare Workers AI."""
        if not self.account_id or not self.api_token:
            raise CloudflareWorkersAIError("Cloudflare Workers AI não configurado (account_id ou api_token ausente).")

        url = f"{self.base_url}/{model}"
        headers = self._headers()
        headers["Content-Type"] = "application/octet-stream"

        client = get_ai_http_client(timeout=self.timeout)
        try:
            resp = await client.post(url, content=audio_bytes, headers=headers)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.warning("workers_ai.transport_error", model=model, error=str(exc))
            raise CloudflareWorkersAIError(f"Erro de transporte Workers AI: {exc}") from exc

        if resp.status_code != 200:
            logger.warning(
                "workers_ai.http_error",
                model=model,
                status=resp.status_code,
                detail=resp.text[:200],
            )
            raise CloudflareWorkersAIError(
                f"Cloudflare Workers AI HTTP {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )

        data = resp.json()
        result = data.get("result", {})
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        logger.info("workers_ai.transcribed", model=model, text_len=len(text), bytes=len(audio_bytes))
        return text.strip()
