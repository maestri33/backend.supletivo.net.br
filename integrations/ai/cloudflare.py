"""Cloudflare-hosted inference through a protected Workers AI gateway."""
from __future__ import annotations

import asyncio
import base64
import re

import httpx
from django.conf import settings

from .client import ChatResult, LLMClient, LLMError
from .http import get_ai_http_client

DEFAULT_TEXT_MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"
DEFAULT_VISION_MODEL = "@cf/google/gemma-4-26b-a4b-it"
DEFAULT_WHISPER_MODEL = "@cf/openai/whisper"


def _setting(name: str, default: str = "") -> str:
    from core.system_config import get_setting
    return str(get_setting(name, default) or default).strip()


def cloudflare_only() -> bool:
    return getattr(settings, "APP_ENV", "prod") == "prod" or getattr(settings, "IA_CLOUDFLARE_ONLY", True)


def cloudflare_model(name: str, default: str) -> str:
    model = _setting(name, default)
    if not re.fullmatch(r"@cf/[a-z0-9_.-]+/[a-zA-Z0-9_.-]+", model):
        raise LLMError("Somente modelos hospedados no Workers AI são permitidos.", retryable=False)
    return model


def connection() -> tuple[str, str]:
    url = _setting("WORKERS_AI_GATEWAY_URL")
    token = _setting("WORKERS_AI_GATEWAY_TOKEN")
    if not url or not url.startswith("https://") or not token:
        raise LLMError("Gateway protegido de Workers AI não configurado.", retryable=False)
    return url.rstrip("/"), token


def is_workers_ai_configured() -> bool:
    try:
        connection()
        return True
    except LLMError:
        return False


class CloudflareWorkersAIError(LLMError):
    def __init__(self, message: str, status_code: int = 0, *, error_kind: str = "provider_error"):
        super().__init__(message, retryable=status_code in (0, 429, 500, 502, 503, 504), status_code=status_code)
        self.error_kind = error_kind


class CloudflareWorkersAIClient(LLMClient):
    def __init__(self, *, timeout: float = 60.0, **kwargs):
        endpoint, token = connection()
        super().__init__(provider="cloudflare", base_url=endpoint, api_key=token,
                         temperature=getattr(settings, "IA_DEFAULT_TEMPERATURE", 0.3),
                         max_tokens=getattr(settings, "IA_MAX_TOKENS", 4096), timeout=timeout)

    async def _request(self, payload: dict) -> ChatResult:
        client = get_ai_http_client(timeout=self._timeout)
        try:
            # Pool reuse must not inherit another operation's timeout. HTTPX's
            # inactivity limits are also bounded by the total wall-clock limit.
            async with asyncio.timeout(self._timeout):
                response = await client.post(f"{self._base_url}/v1/chat/completions", json=payload, headers=self._headers(),
                                             timeout=httpx.Timeout(self._timeout, connect=min(10.0, self._timeout)))
        except httpx.TimeoutException as exc:
            kind = re.sub(r"(?<!^)(?=[A-Z])", "_", type(exc).__name__).lower()
            raise CloudflareWorkersAIError(f"Workers AI indisponível ({kind}).", error_kind=kind) from exc
        except TimeoutError as exc:
            raise CloudflareWorkersAIError("Workers AI indisponível (total_timeout).", error_kind="total_timeout") from exc
        except httpx.TransportError as exc:
            raise CloudflareWorkersAIError("Workers AI indisponível (transport_error).", error_kind="transport_error") from exc
        if response.status_code >= 400:
            raise CloudflareWorkersAIError(f"Workers AI HTTP {response.status_code}.", response.status_code, error_kind=f"http_{response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise CloudflareWorkersAIError("Resposta inválida do Workers AI.", 502) from exc
        if not isinstance(body, dict) or not isinstance(body.get("choices"), list):
            raise CloudflareWorkersAIError("Workers AI não entregou um resultado válido.", 502)
        return self._extract_result(body)

    async def transcribe(self, audio_bytes: bytes, *, mime_type: str = "audio/mpeg", model: str = DEFAULT_WHISPER_MODEL) -> str:
        client = get_ai_http_client(timeout=self._timeout)
        try:
            response = await client.post(f"{self._base_url}/v1/transcriptions", json={"audio": base64.b64encode(audio_bytes).decode("ascii")}, headers=self._headers())
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise CloudflareWorkersAIError("Workers AI indisponível por falha de rede.") from exc
        if response.status_code >= 400:
            raise CloudflareWorkersAIError(f"Workers AI HTTP {response.status_code}.", response.status_code)
        text = response.json().get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise CloudflareWorkersAIError("Workers AI retornou transcrição vazia.", 502)
        return text.strip()


def audio_speech(text: str, *, voice: str, caller: str, timeout: float = 30.0) -> bytes:
    """Synthesis is exposed by the same Cloudflare gateway; callers decide storage."""
    endpoint, token = connection()
    model = "@cf/deepgram/aura-2-es"
    response = httpx.post(f"{endpoint}/v1/audio/speech", json={"model": model, "input": text, "voice": voice, "response_format": "mp3"}, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
    if response.status_code >= 400 or not response.content:
        raise CloudflareWorkersAIError(f"Workers AI TTS HTTP {response.status_code}.", response.status_code)
    return response.content
