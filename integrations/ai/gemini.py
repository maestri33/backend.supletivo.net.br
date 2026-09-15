"""Client Gemini de transcrição, via REST (httpx, sem SDK).

API: generativelanguage.googleapis.com/v1beta — `POST /models/<model>:generateContent?key=...`.
STT manda mídia inline e recebe texto.
Config (key/base_url/modelos) vem do .env via settings (CONVENTION §10). Zero regra de negócio (§8).
"""

from __future__ import annotations

import base64

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


class GeminiError(Exception):
    """Erro ao falar com o Gemini."""


class GeminiClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
    ):
        self._api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self._base_url = (base_url or settings.GEMINI_BASE_URL).rstrip("/")
        self._stt_model = settings.GEMINI_STT_MODEL
        self._timeout = timeout

    async def _generate(self, model: str, body: dict) -> dict:
        url = f"{self._base_url}/models/{model}:generateContent?key={self._api_key}"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0)
        ) as c:
            resp = await c.post(url, json=body)
        if resp.status_code >= 400:
            raise GeminiError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def transcribe(
        self, audio_bytes: bytes, *, mime_type: str = "audio/mpeg"
    ) -> str:
        """Transcreve um áudio (STT) — mesmo generateContent da visão, com parte de áudio inline."""
        instruction = (
            "Transcreva fielmente o audio a seguir em portugues brasileiro. "
            "Responda APENAS a transcricao, sem comentarios nem formatacao."
        )
        body = {
            "contents": [
                {
                    "parts": [
                        {"text": instruction},
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": base64.b64encode(audio_bytes).decode(),
                            }
                        },
                    ]
                }
            ]
        }
        data = await self._generate(self._stt_model, body)
        text = self._first_text(data)
        logger.info(
            "gemini.stt_done",
            model=self._stt_model,
            bytes=len(audio_bytes),
            chars=len(text),
        )
        return text.strip()

    @staticmethod
    def _parts(data: dict) -> list[dict]:
        candidates = data.get("candidates") or [{}]
        return (candidates[0].get("content") or {}).get("parts") or []

    def _first_text(self, data: dict) -> str:
        for part in self._parts(data):
            if part.get("text"):
                return part["text"]
        return ""
