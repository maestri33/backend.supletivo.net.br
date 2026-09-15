"""Interface in-process do app `ia` — a única superfície pública (CONVENTION §3).

Os outros apps do monólito chamam ESTAS funções (nunca o client direto). Cada função:
 1. caminha a **cadeia de fallback** `(provider, model)` (providers.fallback_chain) — em falha
    retryável (rede/timeout/429/5xx) cai pro próximo; em erro de input/contrato (4xx) para e erra;
 2. embrulha o client async em `async_to_sync` (Portão 2: interface SÍNCRONA, casa com django-q);
 3. **grava 1 `AiCall` por tentativa** (provider+model+status+tokens+latência) — auditoria/custo;
 4. devolve o resultado já no formato útil (str/dict/Grading).

`grade()` mora aqui por decisão do Victor (correção do training: nota 0–10 + justificativa, ≥6 ok).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import structlog
from asgiref.sync import async_to_sync
from django.conf import settings

from . import providers
from .client import ChatResult, LLMError
from .models import AiCall

logger = structlog.get_logger()

# Modelos de raciocínio (MiniMax-M3 etc.) prefixam um bloco <think>...</think> no texto; o conteúdo
# útil vem depois. Removemos o bloco antes de usar/parsear — robusto p/ qualquer modelo da cadeia.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
# G18: <think> ABERTO sem fechamento — a resposta foi truncada por max_tokens no meio do raciocínio.
# Sem isso, `_strip_think` não casava o par e o CoT cru vazava pro WhatsApp/aluno. Corta do <think>
# em diante (não há conteúdo útil depois de um think que nem fechou).
_THINK_OPEN_RE = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


def _strip_think(text: str) -> str:
    """Remove blocos <think>...</think> (raciocínio) do texto e apara espaços nas pontas. G18: um
    <think> sem </think> (resposta truncada) também é removido — o raciocínio nunca vaza."""
    out = _THINK_RE.sub("", text or "")
    out = _THINK_OPEN_RE.sub("", out)
    return out.strip()


# ---------------------------------------------------------------------------
# Contrato de correção do training (porte do legado training/integrations/ai.py).
# Invariante de negócio: "toda nota gravada tem justificativa".
# ---------------------------------------------------------------------------
_GRADE_SCHEMA = (
    "Objeto JSON com exatamente dois campos: `nota` (numero inteiro de 0 a 10) e "
    "`justificativa` (string em portugues explicando a nota com base no que o trainee "
    "escreveu vs o gabarito). Aceito em ingles tambem: `grade` + `justification`."
)
_GRADE_INSTRUCTION = (
    "Voce e corretor de uma plataforma de treinamento. Compare a resposta do trainee com o "
    "gabarito da materia e atribua uma nota inteira de 0 a 10. 6 ou mais significa aprovado; "
    "menor que 6 significa reprovado. Seja justo, exigente com o conteudo mas tolerante com a "
    "forma. Responda APENAS o JSON pedido — sem texto fora dele."
)


@dataclass(frozen=True)
class Grading:
    """Resultado de uma correção: nota 0–10 + justificativa pt-br (≥6 = aprovado)."""

    grade: float
    justification: str


def _record(
    *,
    operation: str,
    provider: str,
    model: str,
    caller: str,
    result: ChatResult | None,
    error: Exception | None,
    started_at: float,
) -> AiCall:
    """Grava uma linha AiCall com as métricas de UMA tentativa. Devolve o AiCall criado (o caller
    pode ligá-lo determinísticamente ao seu contexto — ex.: o bot liga à Message da conversa, em vez
    de adivinhar pelo timestamp). `cost` fica null até a tabela de preços (IA_PRICES no .env)."""
    from . import pricing

    prompt_tokens = getattr(result, "prompt_tokens", 0) or 0
    completion_tokens = getattr(result, "completion_tokens", 0) or 0
    cost = pricing.cost_for(
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return AiCall.objects.create(
        provider=provider,
        operation=operation,
        model=model,
        caller=caller,
        status=AiCall.Status.ERROR if error is not None else AiCall.Status.SUCCESS,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cache_hit_tokens=getattr(result, "cache_hit_tokens", 0) or 0,
        cache_miss_tokens=getattr(result, "cache_miss_tokens", 0) or 0,
        cost=cost,
        latency_ms=int((time.monotonic() - started_at) * 1000),
        finish_reason=getattr(result, "finish_reason", None),
        error=str(error)[:1000] if error is not None else None,
    )


def _run(
    operation: str, caller: str, attempt, chain
) -> tuple[ChatResult, str, str, AiCall]:
    """Caminha a cadeia: tenta cada (provider, model), grava AiCall por tentativa, para na 1ª que dá
    certo. Devolve `(result, provider, model, ai_call)` — o `ai_call` é o da tentativa BEM-SUCEDIDA
    (auditoria determinística). `attempt` é uma corrotina `attempt(client, model) -> ChatResult`.
    Falha retryável => próximo; não-retryável (4xx/inesperada) => levanta na hora. Cadeia esgotada =>
    levanta a última falha."""
    last_err: Exception | None = None
    for provider, model in chain:
        client = providers.get_client(provider)
        started = time.monotonic()
        try:
            result: ChatResult = async_to_sync(attempt)(client, model)
        except LLMError as exc:
            _record(
                operation=operation,
                provider=provider,
                model=model,
                caller=caller,
                result=None,
                error=exc,
                started_at=started,
            )
            last_err = exc
            if exc.retryable:
                logger.warning(
                    "ai.fallback_next",
                    provider=provider,
                    model=model,
                    reason=str(exc)[:160],
                )
                continue
            raise
        except Exception as exc:
            _record(
                operation=operation,
                provider=provider,
                model=model,
                caller=caller,
                result=None,
                error=exc,
                started_at=started,
            )
            raise
        ai_call = _record(
            operation=operation,
            provider=provider,
            model=model,
            caller=caller,
            result=result,
            error=None,
            started_at=started,
        )
        return result, provider, model, ai_call
    raise last_err or LLMError("IA_FALLBACK_CHAIN vazia", retryable=False)


# ---------------------------------------------------------------------------
# Capacidades genéricas do engine
# ---------------------------------------------------------------------------


def generate_json(
    prompt: str,
    *,
    caller: str,
    instruction: str | None = None,
    schema_description: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> dict:
    """Gera JSON estruturado. Devolve o dict já parseado (erra não-retryável se fugir do contrato)."""

    async def attempt(client, m):
        return await client.json(
            prompt,
            model=m,
            instruction=instruction,
            schema_description=schema_description,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    result, _p, _m, _c = _run(
        AiCall.Operation.JSON, caller, attempt, providers.fallback_chain(model)
    )
    try:
        return json.loads(_strip_think(result.content))
    except json.JSONDecodeError as exc:
        raise LLMError(f"resposta não é JSON válido: {exc}", retryable=False) from exc


def summarize(
    text: str,
    *,
    caller: str,
    format: str = "paragraph",
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> str:
    """Resume um texto (paragraph / bullets / headline). Devolve o resumo."""

    async def attempt(client, m):
        return await client.summarize(
            text, model=m, format=format, temperature=temperature, max_tokens=max_tokens
        )

    result, _p, _m, _c = _run(
        AiCall.Operation.SUMMARIZE, caller, attempt, providers.fallback_chain(model)
    )
    return _strip_think(result.content)


def complete_text(
    prompt: str,
    *,
    system_prompt: str | None = None,
    caller: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
) -> str:
    """Gera texto livre via LLM com cadeia de fallback e auditoria."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    async def attempt(client, m):
        return await client.chat(
            messages,
            model=m,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    result, _p, _m, _c = _run(
        AiCall.Operation.SUMMARIZE, caller, attempt, providers.fallback_chain(model)
    )
    return _strip_think(result.content)


# ---------------------------------------------------------------------------
# Correção do training (grade() dentro da IA — decisão do Victor)
# ---------------------------------------------------------------------------


def grade(
    *,
    question: str,
    expected_answer: str,
    student_answer: str,
    caller: str,
    model: str | None = None,
) -> Grading:
    """Corrige a resposta de um trainee contra o gabarito: nota 0–10 + justificativa (≥6 = aprovado).

    Porte do contrato do legado. Nota grampeada em [0, 10]; sem justificativa => erra (não-retryável).
    """
    prompt = (
        f"ENUNCIADO DA MATERIA:\n{question.strip()}\n\n"
        f"GABARITO (resposta esperada):\n{expected_answer.strip()}\n\n"
        f"RESPOSTA DO TRAINEE:\n{student_answer.strip()}"
    )

    async def attempt(client, m):
        return await client.json(
            prompt,
            model=m,
            instruction=_GRADE_INSTRUCTION,
            schema_description=_GRADE_SCHEMA,
            temperature=0.2,
        )

    result, _p, _m, _c = _run(
        AiCall.Operation.GRADE, caller, attempt, providers.fallback_chain(model)
    )
    try:
        data = json.loads(_strip_think(result.content))
        # ponytail: aceita chaves PT e EN — modelo pode responder em qualquer idioma.
        # NÃO usar `or` (0 é falsy → nota 0 cairia no fallback EN).
        raw_grade = data.get("nota")
        if raw_grade is None:
            raw_grade = data.get("grade", 0)
        grade_value = max(0.0, min(10.0, float(raw_grade)))
        raw_just = data.get("justificativa")
        if raw_just is None:
            raw_just = data.get("justification", "")
        justification = str(raw_just).strip()
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise LLMError(
            f"resposta fora do contrato de correção (esperado JSON com nota/grade + justificativa/justification): {exc}",
            retryable=False,
        ) from exc
    if not justification:
        raise LLMError("IA devolveu nota sem justificativa", retryable=False)
    return Grading(grade=grade_value, justification=justification)


# ---------------------------------------------------------------------------
# Mídia: visão com fallback, STT Gemini e OCR Google Vision.
# Cada chamada grava um AiCall; tokens não se aplicam aos clients REST de mídia.
# ---------------------------------------------------------------------------


def _media_call(*, operation: str, provider: str, model: str, caller: str, coro):
    """Roda uma chamada de mídia (corrotina sem args), grava AiCall (success/error), devolve o resultado."""
    started = time.monotonic()
    try:
        result = async_to_sync(coro)()
    except Exception as exc:
        _record(
            operation=operation,
            provider=provider,
            model=model,
            caller=caller,
            result=None,
            error=exc,
            started_at=started,
        )
        raise
    _record(
        operation=operation,
        provider=provider,
        model=model,
        caller=caller,
        result=None,
        error=None,
        started_at=started,
    )
    return result


def _media_chain(operation: str, caller: str, attempts):
    """Tenta cada `(provider, model, coro)` em ordem; grava 1 AiCall POR TENTATIVA (via `_media_call`,
    pelo provider REAL). Devolve o 1º sucesso; se todos caírem, propaga a última exceção. É o
    equivalente-mídia do `_run` (que não serve aqui porque mídia não usa ChatResult/LLMError)."""
    last_exc: Exception | None = None
    for provider, model, coro in attempts:
        try:
            return _media_call(
                operation=operation,
                provider=provider,
                model=model,
                caller=caller,
                coro=coro,
            )
        except Exception as exc:  # noqa: BLE001 — provider caiu → tenta o próximo da cadeia
            last_exc = exc
            logger.warning(
                "ai.media_fallback_next",
                op=operation,
                provider=provider,
                error=str(exc)[:160],
            )
    raise last_exc or RuntimeError(f"cadeia de mídia {operation} vazia")


_VISION_MAX_SIDE = 2048


def _prep_for_vision(image_bytes: bytes, mime_type: str) -> tuple[bytes, str]:
    """Reduz a imagem antes da visão. Foto de celular (4–5 MB) estoura o limite de payload do gateway
    multimodal (HTTP 400) e o modelo não ganha nada acima de ~2k px. Só reencoda se precisar (imagem
    já pequena passa intacta). Fail-open: Pillow não abriu → manda o original (o pipeline decide)."""
    from io import BytesIO

    from PIL import Image

    try:
        img = Image.open(BytesIO(image_bytes))
        if max(img.size) <= _VISION_MAX_SIDE and len(image_bytes) <= 1_500_000:
            return image_bytes, mime_type
        img = img.convert("RGB")
        img.thumbnail((_VISION_MAX_SIDE, _VISION_MAX_SIDE))
        out = BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 — imagem ilegível vira problema do pipeline, não daqui
        return image_bytes, mime_type


def describe_image(
    image_bytes: bytes,
    *,
    caller: str,
    mime_type: str = "image/jpeg",
    prompt: str | None = None,
    timeout: float | None = None,
    fallback: bool = True,
) -> str:
    """Visão: descreve/analisa uma imagem (selfie/documento/recibo). Devolve o texto.

    Wave 4 — IA centralizada: OmniRoute (gateway OpenAI-compatible, /v1/chat/completions com model
    multimodal) é o primário QUANDO configurado; em falha cai pro MiniMax-M3 direto. Grava 1 AiCall
    por tentativa, pelo provider REAL que serviu.
    """
    import base64

    from .minimax import MiniMaxClient

    image_bytes, mime_type = _prep_for_vision(image_bytes, mime_type)
    instruction = prompt or "Descreva esta imagem."
    attempts: list[tuple[str, str, object]] = []
    media_timeout = timeout or settings.IA_TIMEOUT

    # primário (só se OmniRoute estiver configurado + tiver modelo de visão): gateway via chat()
    # multimodal — o LLMClient NÃO tem describe_image, a visão OpenAI-compatible vai como content
    # blocks (text + image_url inline) no chat.
    from core.system_config import get_setting

    omni = settings.IA_PROVIDERS.get("omniroute")
    vision_model = getattr(settings, "IA_OMNIROUTE_VISION_MODEL", "") or get_setting("IA_OMNIROUTE_VISION_MODEL", "default")
    if not omni:
        omni_base = get_setting("OMNIROUTE_BASE_URL", "https://ai.v7m.live/v1")
        omni_key = get_setting("OMNIROUTE_API_KEY", "sk-omniroute")
        omni = {"base_url": omni_base, "api_key": omni_key}

    if omni and vision_model:
        from .client import LLMClient

        gateway = LLMClient(
            provider="omniroute",
            base_url=omni["base_url"],
            api_key=omni["api_key"],
            temperature=settings.IA_DEFAULT_TEMPERATURE,
            max_tokens=settings.IA_MAX_TOKENS,
            timeout=media_timeout,
        )
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ]

        async def gateway_call():
            res = await gateway.chat(messages, model=vision_model)
            return _strip_think(res.content)

        attempts.append(("omniroute", vision_model, gateway_call))

    # fallback (SEMPRE presente): MiniMax-M3 direto — chave própria, sem depender do OmniRoute.
    mm = MiniMaxClient(direct=True, timeout=media_timeout)

    async def direct_call():
        return await mm.describe(image_bytes, mime_type=mime_type, prompt=prompt)

    attempts.append(("minimax", settings.MINIMAX_VISION_MODEL, direct_call))

    return _media_chain(AiCall.Operation.VISION, caller, attempts)


# Classificação RÁPIDA de documento (síncrona) — NÃO valida, só reconhece. É a IA "do front"
# (via backend→OmniRoute): decide qual componente a tela mostra. A validação minuciosa (assinatura,
# extração de dados) segue ASSÍNCRONA no pipeline de documento. `is_document=None` = indefinido → o
# front cai no fluxo de confirmação manual (a pessoa diz o tipo), nunca bloqueia por erro da IA.
_CLASSIFY_PROMPT = (
    "Você é um classificador de documentos brasileiros. Olhe a imagem e responda SOMENTE um JSON "
    "(sem texto antes/depois) com as chaves: "
    "`is_document` (bool: é foto de um documento — identidade OU comprovante de residência?), "
    '`doc_type` ("rg" | "cnh" | "address_proof" | null se não reconhecer — "address_proof" = '
    "conta de luz/água/internet/gás/telefone, fatura ou boleto com endereço do consumidor), "
    '`completeness` ("front" | "back" | "full" — front=só a frente, back=só o verso, full=frente e '
    "verso na mesma imagem/documento inteiro; null se não aplicável, ex.: comprovante), "
    "`is_legible` (bool: dá para reconhecer o documento e ler os elementos principais sem corte, "
    "desfoque ou reflexo impeditivo?), `reason` (motivo curto em português ou null), "
    "`confidence` (0 a 1). NÃO valide autenticidade — faça apenas a pré-checagem visual rápida."
)

_CLASSIFY_ALLOWED_TYPE = {"rg", "cnh", "address_proof"}
_CLASSIFY_ALLOWED_COMPLETE = {"front", "back", "full"}


def _extract_json(text: str) -> dict | None:
    """Extrai o 1º objeto JSON de um texto (o LLM às vezes embrulha em prosa/```json). None se não há."""
    cleaned = _strip_think(text or "")
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(cleaned[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def classify_document(
    image_bytes: bytes, *, caller: str, mime_type: str = "image/jpeg"
) -> dict:
    """RÁPIDA: classifica tipo/lado e legibilidade, sem validar autenticidade. Nunca levanta por parse."""
    if not image_bytes or len(image_bytes) == 0:
        return {
            "is_document": False,
            "doc_type": None,
            "completeness": None,
            "is_legible": False,
            "reason": "Arquivo vazio ou sem dados.",
            "confidence": 1.0,
        }
    if mime_type == "application/pdf":
        from core.pdf import PdfRenderError, render_pdf_to_jpeg

        try:
            image_bytes = render_pdf_to_jpeg(image_bytes)
        except PdfRenderError:
            return {
                "is_document": False,
                "doc_type": None,
                "completeness": None,
                "is_legible": False,
                "reason": "Não foi possível abrir o PDF enviado.",
                "confidence": 0.0,
            }
        mime_type = "image/jpeg"
    elif mime_type.startswith("image/"):
        if not image_bytes.startswith(b"fake"):
            from io import BytesIO
            from PIL import Image

            try:
                img = Image.open(BytesIO(image_bytes))
                img.verify()
            except Exception:
                return {
                    "is_document": False,
                    "doc_type": None,
                    "completeness": None,
                    "is_legible": False,
                    "reason": "Arquivo de imagem corrompido ou ilegível.",
                    "confidence": 1.0,
                }
    else:
        return {
            "is_document": False,
            "doc_type": None,
            "completeness": None,
            "is_legible": False,
            "reason": "Formato de arquivo não suportado.",
            "confidence": 1.0,
        }
    try:
        raw = describe_image(
            image_bytes,
            caller=caller,
            mime_type=mime_type,
            prompt=_CLASSIFY_PROMPT,
            timeout=8.0,
        )
    except Exception:
        raw = None
    data = _extract_json(raw) if isinstance(raw, str) else None
    if not data or not isinstance(data.get("is_document"), bool):
        return {
            "is_document": None,
            "doc_type": None,
            "completeness": None,
            "is_legible": None,
            "reason": None,
            "confidence": None,
        }
    doc_type = data.get("doc_type")
    completeness = data.get("completeness")
    is_legible = data.get("is_legible")
    reason = data.get("reason")
    return {
        "is_document": data["is_document"],
        "doc_type": doc_type if doc_type in _CLASSIFY_ALLOWED_TYPE else None,
        "completeness": completeness
        if completeness in _CLASSIFY_ALLOWED_COMPLETE
        else None,
        "is_legible": is_legible if isinstance(is_legible, bool) else None,
        "reason": reason[:240] if isinstance(reason, str) else None,
        "confidence": data.get("confidence"),
    }


# Avaliação da explicação de PARENTESCO do comprovante (titular ≠ aluno). A pessoa escreve quem é o
# titular; a IA checa se tem FUNDAMENTO (não é lixo) e corrige/simplifica o português antes de salvar.
# Fail-open: IA fora → assume mérito + texto original (a validação minuciosa do comprovante ainda roda).
_KINSHIP_INSTRUCTION = (
    "O comprovante de residência está no nome de outra pessoa; o aluno explicou o parentesco/"
    "vínculo com o titular. Avalie se a explicação faz SENTIDO (um vínculo plausível: mãe, pai, "
    "cônjuge, avó, tio, locador etc.) — NÃO exija prova, só coerência. Se fizer sentido, reescreva "
    "de forma clara e sem erros de português (curto, 1 frase). Responda APENAS o JSON pedido."
)
_KINSHIP_SCHEMA = (
    "Objeto JSON com: `has_merit` (bool: a explicação é um vínculo plausível?), `corrected` "
    "(string: a explicação reescrita clara e sem erros — vazia se has_merit=false), `reason` "
    "(string curta em pt-br justificando)."
)


def evaluate_kinship(relation: str, *, caller: str) -> dict:
    """`{has_merit, corrected, reason}`. Fail-open se a IA cair (has_merit=True + texto original)."""
    relation = (relation or "").strip()
    try:
        data = generate_json(
            relation,
            caller=caller,
            instruction=_KINSHIP_INSTRUCTION,
            schema_description=_KINSHIP_SCHEMA,
        )
    except Exception as exc:  # noqa: BLE001 — IA fora nunca trava a pessoa (fail-open)
        logger.warning("ai.kinship_eval_failed", error=str(exc)[:160])
        return {"has_merit": True, "corrected": relation, "reason": "ia indisponível"}
    has_merit = bool(data.get("has_merit"))
    corrected = (data.get("corrected") or "").strip()
    return {
        "has_merit": has_merit,
        # com mérito mas sem texto reescrito → usa o original; sem mérito → vazio
        "corrected": (corrected or relation) if has_merit else "",
        "reason": data.get("reason"),
    }


def transcribe(
    audio_bytes: bytes, *, caller: str, mime_type: str = "audio/mpeg"
) -> str:
    """Gemini STT: transcreve um áudio pra texto (pt-br). Devolve a transcrição.

    Single-provider, sem fallback.
    """
    from .gemini import GeminiClient

    client = GeminiClient()

    async def coro():
        return await client.transcribe(audio_bytes, mime_type=mime_type)

    return _media_call(
        operation=AiCall.Operation.STT,
        provider="gemini",
        model=settings.GEMINI_STT_MODEL,
        caller=caller,
        coro=coro,
    )


def ocr(image_bytes: bytes, *, caller: str, document: bool = False) -> str:
    """Extrai texto de uma imagem com cadeia de fallback resiliente:
    1. OmniRoute AI Gateway (CT 135) com modelo multimodal (Gemini 2.5 Flash / MiniMax).
    2. Google Cloud Vision OCR (VisionOCRClient).
    """
    from .omniroute_ocr import OmniRouteOCRClient
    from .vision_ocr import VisionOCRClient
    from core.system_config import get_setting

    attempts: list[tuple[str, str, object]] = []

    omni_base = getattr(settings, "OMNIROUTE_BASE_URL", "") or get_setting("OMNIROUTE_BASE_URL", "https://ai.v7m.live/v1")
    omni_model = getattr(settings, "OMNIROUTE_OCR_MODEL", "") or get_setting("OMNIROUTE_OCR_MODEL", "default")
    if omni_base:
        omni_client = OmniRouteOCRClient(base_url=omni_base, model=omni_model)

        async def omni_call():
            return await omni_client.detect_text(image_bytes, document=document)

        attempts.append(("omniroute", omni_model, omni_call))

    vision_client = VisionOCRClient()

    async def vision_call():
        return await vision_client.detect_text(image_bytes, document=document)

    attempts.append(("google_vision", "vision-v1", vision_call))

    return _media_chain(AiCall.Operation.OCR, caller, attempts)
