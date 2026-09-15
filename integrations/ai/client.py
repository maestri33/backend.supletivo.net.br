"""Client LLM genérico — qualquer provider OpenAI-compatible (POST /chat/completions).

DeepSeek, DashScope (Alibaba), Groq, OpenAI, OpenRouter, NVIDIA… todos falam o mesmo protocolo;
o que muda é `base_url` + `api_key` (vêm do registry, montado do .env via settings — CONVENTION §10).
**Zero regra de negócio aqui** (CONVENTION §8): só fala com o provider e devolve o resultado cru +
métricas. Quem dá sentido (parse/contrato) é a interface (service.py).

Erros são tipados com `retryable`: rede/timeout/429/5xx = retryable (o service cai pro próximo
provider da cadeia); 4xx de input = não-retryable (é bug do caller, não do provider).
Métricas de cache (prompt_cache_hit/miss_tokens) são lidas com default 0 — só o DeepSeek as manda.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
import structlog

logger = structlog.get_logger()

# Status HTTP que valem nova tentativa (intra-provider) e, esgotadas, fallback (inter-provider).
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# System prompt padrão pt-br (porte do legado). Mantém o tom e evita lixo no output.
SYSTEM_PROMPT_PT = (
    "Voce responde SEMPRE em portugues brasileiro com acentuacao e pontuacao corretas. "
    "Tom natural, nao-formal, nao-robotico. "
    "NUNCA use {{variavel}} no output. "
    "Sem meta-comentarios, sem aspas, sem markdown."
)


class LLMError(Exception):
    """Erro ao falar com um provider de IA. `retryable` decide se o service tenta o próximo da cadeia."""

    def __init__(
        self, message: str, *, retryable: bool, status_code: int | None = None
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@dataclass
class ChatResult:
    """Resultado de uma chamada ao modelo: o texto + as métricas de token/cache."""

    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    finish_reason: str | None = None


class LLMClient:
    """Cliente fino sobre um provider OpenAI-compatible. Cada método devolve ChatResult."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str,
        temperature: float = 0.3,
        max_tokens: int = 0,
        timeout: float = 60.0,
    ) -> None:
        self.provider = provider
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._default_temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout

    # ---------- low-level ----------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _build_payload(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> dict:
        payload: dict = {
            "model": model,
            "messages": messages,
            # o app SEMPRE aguarda a resposta inteira (nunca consome stream); alguns gateways
            # OpenAI-compatible (OmniRoute) fazem streaming por default e o `resp.json()` quebra
            # com "Expecting value" — desligar aqui é o correto pra todas as chamadas.
            "stream": False,
            "temperature": (
                temperature if temperature is not None else self._default_temperature
            ),
        }
        resolved_max_tokens = max_tokens if max_tokens is not None else self._max_tokens
        if resolved_max_tokens:
            payload["max_tokens"] = resolved_max_tokens
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _extract_result(self, body: dict) -> ChatResult:
        choice = (body.get("choices") or [{}])[0]
        usage = body.get("usage") or {}
        return ChatResult(
            content=choice.get("message", {}).get("content", "") or "",
            prompt_tokens=usage.get("prompt_tokens", 0) or 0,
            completion_tokens=usage.get("completion_tokens", 0) or 0,
            cache_hit_tokens=usage.get("prompt_cache_hit_tokens", 0) or 0,
            cache_miss_tokens=usage.get("prompt_cache_miss_tokens", 0) or 0,
            finish_reason=choice.get("finish_reason"),
        )

    async def _send_with_retry(
        self,
        client: httpx.AsyncClient,
        payload: dict,
        *,
        max_attempts: int = 3,
        backoff_base: float = 0.5,
    ) -> httpx.Response:
        url = f"{self._base_url}/chat/completions"
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await client.post(url, json=payload, headers=self._headers())
                if resp.status_code in RETRYABLE_STATUS and attempt < max_attempts:
                    logger.warning(
                        "llm.retry",
                        provider=self.provider,
                        status=resp.status_code,
                        attempt=attempt,
                    )
                    await asyncio.sleep(backoff_base * 2 ** (attempt - 1))
                    continue
                return resp
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning(
                    "llm.transport_error",
                    provider=self.provider,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt == max_attempts:
                    raise LLMError(
                        f"{self.provider}: falha de rede: {exc}", retryable=True
                    ) from exc
                await asyncio.sleep(backoff_base * 2 ** (attempt - 1))
        raise LLMError(f"{self.provider}: falha de rede: {last_exc}", retryable=True)

    async def _request(self, payload: dict) -> ChatResult:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0)
        ) as client:
            resp = await self._send_with_retry(client, payload)
        if resp.status_code >= 400:
            # 429/5xx = retryable (provider em apuros → fallback). Demais 4xx = bug do caller.
            retryable = resp.status_code in RETRYABLE_STATUS
            raise LLMError(
                f"{self.provider} HTTP {resp.status_code}: {resp.text[:300]}",
                retryable=retryable,
                status_code=resp.status_code,
            )
        result = self._extract_result(resp.json())
        logger.info(
            "llm.chat_done",
            provider=self.provider,
            model=payload["model"],
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cache_hit=result.cache_hit_tokens,
            cache_miss=result.cache_miss_tokens,
        )
        return result

    # ---------- capacidades (cada uma devolve ChatResult cru) ----------

    async def json(
        self,
        prompt: str,
        *,
        model: str,
        instruction: str | None = None,
        schema_description: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """JSON estruturado (response_format=json_object). O conteúdo vem como string JSON."""
        schema_note = (
            f"O JSON deve seguir este schema: {schema_description}"
            if schema_description
            else ""
        )
        instruction_line = f"Instrucao: {instruction}" if instruction else ""
        payload = self._build_payload(
            [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT_PT
                    + " Retorne APENAS um JSON valido. "
                    + schema_note,
                },
                {"role": "user", "content": f"Prompt: {prompt}\n{instruction_line}"},
            ],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
        )
        return await self._request(payload)

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> ChatResult:
        """Chat multi-turn cru. messages = [{"role": ..., "content": ...}]."""
        payload = self._build_payload(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
        return await self._request(payload)

    async def summarize(
        self,
        text: str,
        *,
        model: str,
        format: str = "paragraph",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        """Resume um texto no formato pedido: paragraph, bullets ou headline."""
        format_prompts = {
            "paragraph": "Resuma o texto em um unico paragrafo coeso e direto:",
            "bullets": "Resuma o texto em topicos com marcadores, um por linha:",
            "headline": "Resuma o texto em uma unica manchete impactante (max 120 chars):",
        }
        instruction = format_prompts.get(format, format_prompts["paragraph"])
        payload = self._build_payload(
            [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT_PT
                    + " Voce e um especialista em sumarizacao.",
                },
                {"role": "user", "content": f"{instruction}\n\n{text}"},
            ],
            model=model,
            temperature=temperature if temperature is not None else 0.3,
            max_tokens=max_tokens,
        )
        return await self._request(payload)

    async def list_models(self) -> list[str]:
        """GET /models — lista os modelos reais do provider (valida a key de quebra). Usado no §8."""
        url = f"{self._base_url}/models"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=10.0)
        ) as client:
            resp = await client.get(url, headers=self._headers())
        if resp.status_code >= 400:
            retryable = resp.status_code in RETRYABLE_STATUS
            raise LLMError(
                f"{self.provider} /models HTTP {resp.status_code}: {resp.text[:200]}",
                retryable=retryable,
                status_code=resp.status_code,
            )
        data = resp.json().get("data") or []
        return [m.get("id", "") for m in data if m.get("id")]
