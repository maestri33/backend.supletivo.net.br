"""Client OmniRoute AI Gateway — OCR documental e multimodal via /v1/chat/completions.

Falar com o OmniRoute (CT 135 / 10.0.1.35) utilizando modelos de visão multimodal (ex: Gemini 2.5 Flash,
MiniMax-M3) para extrair texto de imagens de documentos (RG, CNH, comprovantes).
"""

from __future__ import annotations

import base64
import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()

_OCR_SYSTEM_PROMPT = (
    "Você é um motor OCR especializado de alta precisão. "
    "Transcreva TODO o texto legível da imagem exatamente como aparece. "
    "Mantenha nomes, números de documentos (RG, CPF, CNH), datas e endereços intactos. "
    "Não adicione comentários, saudações, explicações ou tags markdown. "
    "Retorne estritamente o texto bruto extraído."
)


class OmniRouteOCRError(Exception):
    """Erro ao processar OCR via OmniRoute Gateway."""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class OmniRouteOCRClient:
    """Cliente de OCR via OmniRoute Gateway com interface OpenAI-compatible."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ):
        raw_base = base_url if base_url is not None else getattr(settings, "OMNIROUTE_BASE_URL", "https://ai.v7m.live/v1")
        self._base_url = raw_base.rstrip("/")
        if not self._base_url.endswith("/v1") and not self._base_url.endswith("/chat/completions"):
            self._base_url = f"{self._base_url}/v1"
        self._api_key = api_key if api_key is not None else getattr(settings, "OMNIROUTE_API_KEY", "")
        self._model = model or getattr(settings, "OMNIROUTE_OCR_MODEL", "gemini-2.5-flash")
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def detect_text(self, image_bytes: bytes, *, document: bool = False) -> str:
        """Extrai o texto de uma imagem usando visão multimodal no OmniRoute."""
        if not image_bytes:
            return ""

        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        prompt = (
            "Extraia todo o texto deste documento oficial (RG, CNH, Certidão ou Comprovante) com máxima precisão."
            if document
            else "Extraia todo o texto visível nesta imagem."
        )

        payload = {
            "model": self._model,
            "stream": False,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": _OCR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                        },
                    ],
                },
            ],
        }

        url = f"{self._base_url}/chat/completions"
        async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout, connect=10.0)) as client:
            try:
                resp = await client.post(url, json=payload, headers=self._headers())
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                logger.warning("omniroute_ocr.transport_error", error=str(exc), url=url)
                raise OmniRouteOCRError(f"Falha de conexão com OmniRoute: {exc}", retryable=True) from exc

        if resp.status_code in {429, 500, 502, 503, 504}:
            raise OmniRouteOCRError(
                f"OmniRoute OCR HTTP {resp.status_code}: {resp.text[:200]}",
                retryable=True,
                status_code=resp.status_code,
            )
        if resp.status_code >= 400:
            raise OmniRouteOCRError(
                f"OmniRoute OCR HTTP {resp.status_code}: {resp.text[:200]}",
                retryable=False,
                status_code=resp.status_code,
            )

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""

        text = choices[0].get("message", {}).get("content", "") or ""
        clean_text = text.strip()
        logger.info(
            "omniroute_ocr.done",
            model=self._model,
            bytes=len(image_bytes),
            chars=len(clean_text),
        )
        return clean_text
