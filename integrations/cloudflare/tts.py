"""Módulo de Síntese de Voz (TTS) via Cloudflare Workers AI & R2 Storage.

TTS provider order: ElevenLabs Turbo via OmniRoute, ElevenLabs Multilingual,
then Brazilian Edge-TTS. Cloudflare Aura Spanish is skipped for pt-BR.
Male recipient -> female voice; female/unknown recipient -> male voice.
Audio storage remains Cloudflare R2 with local storage fallback.
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any
from urllib.parse import quote

import httpx
import structlog
from django.conf import settings
from django.core.files.storage import default_storage

from core.media import save_media_at
from core.system_config import get_setting
from integrations.cloudflare.r2 import is_r2_configured, upload_to_r2, get_r2_public_url

logger = structlog.get_logger()

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
_COLON_URL_RE = re.compile(r":\s*\n?\s*(?:https?://\S+|www\.\S+|wa\.me/\S+)")
_URL_STRIP_RE = re.compile(r"https?://\S+|www\.\S+|wa\.me/\S+")
_RAW_VAR_RE = re.compile(r"\{[a-zA-Z0-9_-]+\}")
_BULLET_RE = re.compile(r"[•●▪▫◦★☆]")
_EMOJI_RE = re.compile(r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]")
_MD_STRIP_RE = re.compile(r"[*_~`#>]")
_SPACE_CLEAN_RE = re.compile(r"\s+")

class CloudflareTtsError(Exception):
    """Erro na geração de áudio TTS."""
    def __init__(self, message: str, status_code: int = 0):
        self.status_code = status_code
        super().__init__(message)


def clean_text_for_speech(text: str) -> str:
    """Prepara o texto de notificação para síntese de voz (TTS).

    - Converte links Markdown [texto](url) para 'texto'.
    - Transforma comandos com links finais (ex: 'pelo painel:\\nhttps://...') em encerramento natural ('.').
    - Substitui URLs restantes por 'pelo link' para que links e domínios não sejam soletrados no áudio.
    - Remove variáveis de template cruas ({link_painel}, etc.) que possam ter sobrado.
    - Remove emojis e caracteres especiais como bullets ('•').
    - Remove marcações markdown (*, _, ~, `, #, >).
    - Normaliza espaçamentos e pontuação para fluidez na fala.
    """
    if not text:
        return ""
    t = _MD_LINK_RE.sub(r"\1", text)
    t = _COLON_URL_RE.sub(".", t)
    t = _URL_STRIP_RE.sub("pelo link", t)
    t = _RAW_VAR_RE.sub("", t)
    t = _BULLET_RE.sub(", ", t)
    t = _EMOJI_RE.sub("", t)
    t = _MD_STRIP_RE.sub("", t)
    t = re.sub(r"\s*([.,;:])\s*\1+", r"\1", t)
    t = re.sub(r"\s*:\s*\.", ".", t)
    return _SPACE_CLEAN_RE.sub(" ", t).strip()


def resolve_cross_gender_voice(gender: str | None) -> dict[str, str]:
    """Aplica a REGRA CRUZADA de gênero estipulada pelo Victor:
    - Homem (M) -> Voz Feminina ('bella' no ElevenLabs Turbo v2.5)
    - Mulher (F) -> Voz Masculina ('antoni' no ElevenLabs Turbo v2.5)
    - Sem sexo (None) -> Voz Masculina ('antoni' fallback)
    """
    clean_g = str(gender or "").upper().strip()
    if clean_g == "M":
        return {
            "gender_applied": "M",
            "voice_gender": "female",
            "eleven_model": "elevenlabs/eleven_turbo_v2_5",
            "eleven_voice": "bella",
            "aura2_speaker": "carina",
            "aura1_speaker": "asteria",
            "omniroute_voice": "bella",
        }
    # Mulher ou Não Informado
    return {
        "gender_applied": clean_g or "UNKNOWN",
        "voice_gender": "male",
        "eleven_model": "elevenlabs/eleven_turbo_v2_5",
        "eleven_voice": "antoni",
        "aura2_speaker": "alvaro",
        "aura1_speaker": "orion",
        "omniroute_voice": "antoni",
    }


def _get_cf_credentials() -> tuple[str, str]:
    token = (
        get_setting("CLOUDFLARE_API_TOKEN", "")
        or getattr(settings, "CLOUDFLARE_API_TOKEN", "")
    )
    account = (
        get_setting("CLOUDFLARE_ACCOUNT_ID", "")
        or getattr(settings, "CLOUDFLARE_ACCOUNT_ID", "")
    )
    return token, account


def _get_omniroute_credentials() -> tuple[str, str]:
    url = (
        get_setting("OMNIROUTER_URL", "")
        or getattr(settings, "OMNIROUTER_URL", "")
        or getattr(settings, "OMNIROUTE_BASE_URL", "")
        or ""
    ).rstrip("/")
    if url and not url.endswith("/v1"):
        endpoint = f"{url}/v1"
    else:
        endpoint = url
    token = (
        get_setting("OMNIROUTE_API_KEY", "")
        or get_setting("OMNIROUTER_API_KEY", "")
        or getattr(settings, "OMNIROUTE_API_KEY", "")
        or getattr(settings, "OMNIROUTER_API_KEY", "")
        or getattr(settings, "OPENCODE_API_KEY", "")
        or ""
    )
    return endpoint, token


def synthesize_speech(
    text: str,
    *,
    gender: str | None = None,
    caller: str = "notify.dispatch",
    timeout: float = 30.0,
) -> str | None:
    """Sintetiza texto em áudio via ElevenLabs Turbo v2.5 (OmniRoute) com distribuição via R2/Local."""
    spoken_text = clean_text_for_speech(text)
    if not spoken_text:
        return None

    voice_cfg = resolve_cross_gender_voice(gender)
    chosen_model = voice_cfg["eleven_model"]
    chosen_voice = voice_cfg["eleven_voice"]

    direct_key = get_setting("ELEVENLABS_API_KEY", "") or getattr(settings, "ELEVENLABS_API_KEY", "")
    if direct_key:
        voice_setting = "ELEVENLABS_VOICE_FEMALE" if voice_cfg["voice_gender"] == "female" else "ELEVENLABS_VOICE_MALE"
        chosen_voice = get_setting(voice_setting, "") or getattr(settings, voice_setting, "")
        if not re.fullmatch(r"[a-zA-Z0-9]{20}", chosen_voice):
            raise CloudflareTtsError("Configure a voz brasileira do ElevenLabs para este destinatário.")

    # Identificador de cache SHA-256
    cache_key = f"tts:{chosen_model}:{chosen_voice}:{spoken_text}"
    audio_hash = hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24]
    rel_path = f"ai/tts/{audio_hash}.mp3"
    ext_base = (
        get_setting("EXTERNAL_URL", "")
        or getattr(settings, "EXTERNAL_URL", "")
        or "https://backend.supletivo.net.br"
    ).rstrip("/")
    local_public_url = f"{ext_base}/media/{rel_path}"

    # 1. Verifica cache no storage local ou R2
    if default_storage.exists(rel_path):
        logger.info("tts.cache_hit", hash=audio_hash, caller=caller)
        if is_r2_configured():
            return get_r2_public_url(rel_path)
        return local_public_url

    audio_bytes: bytes | None = None
    failures: list[str] = []

    omni_base, omni_token = _get_omniroute_credentials()
    for model in ("eleven_turbo_v2_5", "eleven_multilingual_v2"):
        try:
            if direct_key:
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{chosen_voice}"
                headers = {"xi-api-key": direct_key}
                payload = {"text": spoken_text, "model_id": model, "language_code": "pt"}
            elif omni_token:
                url = f"{omni_base}/audio/speech"
                headers = {"Authorization": f"Bearer {omni_token}"}
                payload = {"model": f"elevenlabs/{model}", "input": spoken_text, "voice": chosen_voice}
            else:
                failures.append("ElevenLabs: credencial direta ou OmniRoute não configurada.")
                break
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
            if resp.status_code == 200 and resp.content and resp.headers.get("content-type", "audio/mpeg").startswith("audio/"):
                audio_bytes = resp.content
                logger.info("tts.success", provider="elevenlabs_direct" if direct_key else "omniroute", model=model, voice=chosen_voice)
                break
            failures.append(f"{model}: HTTP {resp.status_code}")
        except Exception as exc:
            failures.append(f"{model}: {type(exc).__name__}")

    # Aura's Spanish voices cannot satisfy Brazilian Portuguese notifications.
    # Keep the legacy slot explicit, then proceed to the Brazilian fallback.
    if not audio_bytes:
        failures.append("cf/aura-2-es: Portuguese Brazilian voice unsupported")

    # 5. Tentativa 4: Edge-TTS Neural (pt-BR-AntonioNeural / pt-BR-FranciscaNeural)
    if not audio_bytes:
        try:
            import asyncio
            import edge_tts

            edge_voice = (
                "pt-BR-FranciscaNeural"
                if str(gender or "").upper() == "M"
                else "pt-BR-AntonioNeural"
            )

            async def _run_edge():
                comm = edge_tts.Communicate(spoken_text, edge_voice)
                data = bytearray()
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        data.extend(chunk["data"])
                return bytes(data)

            audio_bytes = asyncio.run(_run_edge())
            if audio_bytes:
                logger.info("tts.edge_tts_success", voice=edge_voice)
        except Exception as exc:
            failures.append(f"edge-tts: {exc}")
            logger.warning("tts.edge_tts_failed", error=str(exc))

    if not audio_bytes:
        error_msg = f"Nenhum provedor de TTS entregou áudio. Falhas: {' · '.join(failures)}"
        logger.error("tts.all_providers_failed", failures=failures, caller=caller)
        raise CloudflareTtsError(error_msg)

    # 6. Salva o áudio no Cloudflare R2 e no Storage local
    public_url = local_public_url
    try:
        save_media_at(path=rel_path, data=audio_bytes)
    except Exception as e:
        logger.warning("cloudflare.tts_local_save_failed", error=str(e))

    if is_r2_configured():
        try:
            r2_url = upload_to_r2(content=audio_bytes, key=rel_path, content_type="audio/mpeg")
            if r2_url:
                public_url = r2_url
                logger.info("cloudflare.tts_uploaded_r2", url=r2_url)
        except Exception as e:
            logger.warning("cloudflare.tts_r2_upload_failed", error=str(e))

    return public_url
