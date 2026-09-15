"""Client MiniMax — visão com MiniMax-M3, via REST (httpx, sem SDK).

API: base `https://api.minimax.io`, auth `Authorization: Bearer <key>`.
- Visão: `POST /v1/chat/completions` (OpenAI-compatible) com `MiniMax-M3` + a imagem inline
          (data-URL base64) + `thinking: disabled` (mata o bloco <think> do raciocínio) → texto.

Config (key/base_url/modelo) vem do .env via settings (CONVENTION §10). Zero regra de
negócio (§8): só fala com o provider e devolve o resultado cru. Consumido pelo `service.py` (mídia).
"""

from __future__ import annotations

import base64

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


class MiniMaxError(Exception):
    """Erro ao falar com o MiniMax."""


class MiniMaxClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
        direct: bool = False,
    ):
        # ponytail: se direct=True, fala DIRETO com MiniMax (sem gateway).
        # Usado pelo fallback quando OmniRoute cai.
        if direct and getattr(settings, "MINIMAX_DIRECT_API_KEY", ""):
            self._api_key = api_key or settings.MINIMAX_DIRECT_API_KEY
            self._base_url = (
                base_url
                or getattr(
                    settings, "MINIMAX_DIRECT_BASE_URL", "https://api.minimax.io"
                )
            ).rstrip("/")
        else:
            self._api_key = api_key if api_key is not None else settings.MINIMAX_API_KEY
            self._base_url = (base_url or settings.MINIMAX_BASE_URL).rstrip("/")
        self._vision_model = settings.MINIMAX_VISION_MODEL
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        api_key = str(self._api_key or "").strip()
        if not api_key:
            raise MiniMaxError("MiniMax API key não configurada.")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def describe(
        self,
        image_bytes: bytes,
        *,
        mime_type: str = "image/jpeg",
        prompt: str | None = None,
    ) -> str:
        """Descreve/analisa uma imagem com MiniMax-M3 (visão). Devolve o texto, sem o bloco <think>."""
        instruction = (
            prompt
            or "Descreva esta imagem em portugues brasileiro de forma clara e objetiva."
        )
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"
        body = {
            "model": self._vision_model,
            "thinking": {"type": "disabled"},  # sem o bloco <think> de raciocínio
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_completion_tokens": 800,
        }
        url = f"{self._base_url}/v1/chat/completions"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0)
        ) as c:
            resp = await c.post(url, json=body, headers=self._headers())
        if resp.status_code >= 400:
            raise MiniMaxError(
                f"MiniMax visão HTTP {resp.status_code}: {resp.text[:300]}"
            )
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            base = data.get("base_resp") or {}
            raise MiniMaxError(
                f"MiniMax visão sem resposta (status {base.get('status_code')}: "
                f"{base.get('status_msg')})"
            )
        text = (choices[0].get("message") or {}).get("content") or ""
        logger.info(
            "minimax.vision_done",
            model=self._vision_model,
            bytes=len(image_bytes),
            chars=len(text),
        )
        return text.strip()
