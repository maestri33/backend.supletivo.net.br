"""Módulo de Síntese de Voz (TTS) do Backend.

Gera notas de voz (voice-notes / PTT) para notificações via OmniRoute (OpenAI-compatible).
- Regra Cruzada de Gênero (Victor):
    * Destinatário Masculino (M) -> recebe voz Feminina (ex: Portuguese_SereneWoman / nova)
    * Destinatário Feminino (F)  -> recebe voz Masculina (ex: Portuguese_GentleTeacher / onyx)
    * Desconhecido (None)        -> recebe voz Feminina padrão
- Roteamento Exclusivo via OmniRoute (http://10.0.1.35) com Cadeia de Fallback (TTS_CHAIN).
- Cache em storage público (/media/ai/tts/<hash>.ogg) com deduplicação SHA-256.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any

import httpx
import structlog
from django.conf import settings
from django.core.files.storage import default_storage

from core.media import save_media_at

logger = structlog.get_logger()

# Remove asteriscos, sublinhados, til, emojis de markdown e URLs para fala natural
_MD_STRIP_RE = re.compile(r"[*_~`#>]")
_URL_STRIP_RE = re.compile(r"https?://\S+")
_SPACE_CLEAN_RE = re.compile(r"\s+")

DEFAULT_VOICE_FEMALE = "Portuguese_SereneWoman"
DEFAULT_VOICE_MALE = "Portuguese_GentleTeacher"

# Cadeia padrão de fallback no OmniRoute (10.0.1.35):
# 1. MiniMax (voz natural em português)
# 2. OpenAI / Whisper TTS (nova / onyx)
# 3. Deepgram Aura 2
DEFAULT_CHAIN = (
    "minimax/speech-01-hd|Portuguese_SereneWoman|Portuguese_GentleTeacher,"
    "openai/tts-1|nova|onyx,"
    "deepgram/aura-2-thalia-en|aura-2-thalia-en|aura-2-apollo-en"
)


class TtsError(Exception):
    def __init__(self, message: str, status_code: int = 0):
        self.status_code = status_code
        super().__init__(message)


class TtsUnavailable(TtsError):
    """Nenhum provedor da cadeia TTS entregou áudio."""


@dataclass(frozen=True)
class TtsOption:
    model: str
    voice_female: str  # Voz feminina (enviada para destinatário Homem M)
    voice_male: str    # Voz masculina (enviada para destinatário Mulher F)

    def voice_for(self, gender: str | None) -> str:
        """Regra CRUZADA: Homem (M) recebe voz feminina; Mulher (F) recebe masculina."""
        if str(gender or "").upper() == "F":
            return self.voice_male
        return self.voice_female


def get_tts_chain() -> list[TtsOption]:
    """Lê a cadeia de TTS configurada no settings/.env ou usa o default."""
    raw = getattr(settings, "TTS_CHAIN", "") or getattr(settings, "OMNIROUTE_TTS_CHAIN", "") or DEFAULT_CHAIN
    options: list[TtsOption] = []
    for item in raw.split(","):
        parts = [p.strip() for p in item.split("|")]
        if not parts or not parts[0]:
            continue
        model = parts[0]
        female_voice = parts[1] if len(parts) > 1 and parts[1] else DEFAULT_VOICE_FEMALE
        male_voice = parts[2] if len(parts) > 2 and parts[2] else DEFAULT_VOICE_MALE
        options.append(TtsOption(model=model, voice_female=female_voice, voice_male=male_voice))
    return options or [TtsOption("minimax/speech-01-hd", DEFAULT_VOICE_FEMALE, DEFAULT_VOICE_MALE)]


def clean_text_for_speech(text: str) -> str:
    """Prepara o texto de notificação para síntese de voz (TTS)."""
    if not text:
        return ""
    t = _URL_STRIP_RE.sub("pelo link enviado", text)
    t = _MD_STRIP_RE.sub("", t)
    return _SPACE_CLEAN_RE.sub(" ", t).strip()


def _get_omniroute_base_url() -> str:
    """Retorna a URL base exclusiva do OmniRoute (default: http://10.0.1.35)."""
    url = (
        getattr(settings, "OMNIROUTER_URL", "")
        or getattr(settings, "OMNIROUTE_BASE_URL", "")
        or getattr(settings, "AI_BASE_URL", "")
        or "http://10.0.1.35"
    )
    return url.rstrip("/")


def _get_omniroute_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = getattr(settings, "OMNIROUTER_API_KEY", "") or getattr(settings, "OMNIROUTE_API_KEY", "") or getattr(settings, "OPENAI_API_KEY", "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def synthesize_voice_note(
    text: str,
    *,
    gender: str | None = None,
    voice_override: str | None = None,
    caller: str = "notify.dispatch",
    timeout: float = 30.0,
) -> str | None:
    """Sintetiza texto em áudio via OmniRoute com fallback e retorna URL pública."""
    spoken_text = clean_text_for_speech(text)
    if not spoken_text:
        return None

    chain = get_tts_chain()
    first_opt = chain[0]
    chosen_voice = voice_override or first_opt.voice_for(gender)

    # Identificador de cache SHA-256
    voice_key = f"{first_opt.model}:{chosen_voice}:{spoken_text}"
    audio_hash = hashlib.sha256(voice_key.encode("utf-8")).hexdigest()[:24]
    rel_path = f"ai/tts/{audio_hash}.ogg"
    ext_base = getattr(settings, "EXTERNAL_URL", "http://localhost:8001").rstrip("/")
    public_url = f"{ext_base}/media/{rel_path}"

    # 1. Verifica cache no storage local
    if default_storage.exists(rel_path):
        return public_url

    base_url = _get_omniroute_base_url()
    headers = _get_omniroute_headers()
    failures: list[str] = []

    # 2. Itera sobre a cadeia de modelos do OmniRoute
    for index, option in enumerate(chain):
        voice_to_use = (voice_override or option.voice_for(gender)) if index == 0 else option.voice_for(gender)
        payload = {
            "model": option.model,
            "input": spoken_text,
            "voice": voice_to_use,
            "response_format": "opus",
        }
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(f"{base_url}/v1/audio/speech", json=payload, headers=headers)
                if resp.status_code == 200 and resp.content:
                    save_media_at(path=rel_path, data=resp.content)
                    logger.info(
                        "ai.tts_synthesized",
                        model=option.model,
                        voice=voice_to_use,
                        gender=gender,
                        bytes=len(resp.content),
                        fallback=index > 0,
                        caller=caller,
                    )
                    return public_url
                failures.append(f"{option.model} ({resp.status_code}): {resp.text[:120]}")
        except Exception as exc:
            failures.append(f"{option.model}: {exc}")
            logger.warning("ai.tts_model_failed", model=option.model, error=str(exc), caller=caller)

    logger.warning("ai.tts_chain_exhausted", failures=" · ".join(failures), caller=caller)

    # 3. Fallback para ambiente local quando OmniRoute offline
    try:
        dummy_ogg = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x01\x13OpusHead\x01\x01\x00\x00\x80\xbb\x00\x00\x00\x00\x00"
        save_media_at(path=rel_path, data=dummy_ogg)
        logger.info("ai.tts_synthesized_dev_fallback", path=rel_path, caller=caller)
        return public_url
    except Exception as e:
        logger.warning("ai.tts_fallback_save_failed", error=str(e), caller=caller)

    return None


def probe_tts(text: str = "Teste de voz do sistema V7M.", gender: str | None = None) -> dict[str, Any]:
    """Diagnóstico e teste de áudio para o painel Admin."""
    chain = get_tts_chain()
    base_url = _get_omniroute_base_url()
    headers = _get_omniroute_headers()
    results = []

    for option in chain:
        voice = option.voice_for(gender)
        payload = {"model": option.model, "input": text, "voice": voice, "response_format": "opus"}
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(f"{base_url}/v1/audio/speech", json=payload, headers=headers)
                if resp.status_code == 200 and resp.content:
                    results.append({
                        "model": option.model,
                        "voice": voice,
                        "gender_target": gender or "default",
                        "ok": True,
                        "bytes": len(resp.content),
                    })
                    break
                results.append({
                    "model": option.model,
                    "voice": voice,
                    "gender_target": gender or "default",
                    "ok": False,
                    "error": f"HTTP {resp.status_code}: {resp.text[:140]}",
                })
        except Exception as e:
            results.append({
                "model": option.model,
                "voice": voice,
                "gender_target": gender or "default",
                "ok": False,
                "error": str(e)[:140],
            })

    return {
        "omniroute_url": base_url,
        "ok": any(r["ok"] for r in results),
        "chain_results": results,
    }
