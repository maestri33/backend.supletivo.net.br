"""Client Google Cloud Vision — OCR (texto em imagem), via REST (httpx, sem SDK).

API: `POST https://vision.googleapis.com/v1/images:annotate?key=...` com feature TEXT_DETECTION.
Config (key/base_url) vem do .env via settings (CONVENTION §10). Zero regra de negócio (§8).
"""

from __future__ import annotations

import base64

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


class VisionOCRError(Exception):
    """Erro ao falar com o Google Vision."""


class VisionOCRClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
    ):
        self._api_key = (
            api_key if api_key is not None else settings.GOOGLE_VISION_API_KEY
        )
        self._base_url = (base_url or settings.GOOGLE_VISION_BASE_URL).rstrip("/")
        self._timeout = timeout

    async def detect_text(self, image_bytes: bytes, *, document: bool = False) -> str:
        """Extrai o texto de uma imagem. `document=True` usa DOCUMENT_TEXT_DETECTION (denso)."""
        feature = "DOCUMENT_TEXT_DETECTION" if document else "TEXT_DETECTION"
        url = f"{self._base_url}/v1/images:annotate?key={self._api_key}"
        body = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(image_bytes).decode()},
                    "features": [{"type": feature}],
                }
            ]
        }
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0)
        ) as c:
            resp = await c.post(url, json=body)
        if resp.status_code >= 400:
            raise VisionOCRError(f"Vision HTTP {resp.status_code}: {resp.text[:300]}")
        result = (resp.json().get("responses") or [{}])[0]
        if result.get("error"):
            raise VisionOCRError(f"Vision erro: {result['error'].get('message')}")
        text = (result.get("fullTextAnnotation") or {}).get("text", "")
        if not text:
            anns = result.get("textAnnotations") or []
            text = anns[0].get("description", "") if anns else ""
        logger.info(
            "vision.ocr_done", feature=feature, bytes=len(image_bytes), chars=len(text)
        )
        return text.strip()
