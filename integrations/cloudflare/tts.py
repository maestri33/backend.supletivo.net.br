"""Módulo de Síntese de Voz (TTS) via Cloudflare Workers AI & R2 Storage.

Diretivas Canônicas do Projeto (Victor Maestri):
- Regra Cruzada de Gênero:
    * Destinatário Masculino (M) -> Voz Feminina ('carina' / 'asteria' / 'Portuguese_SereneWoman')
    * Destinatário Feminino (F)  -> Voz Masculina ('alvaro' / 'orion' / 'Portuguese_GentleTeacher')
    * Desconhecido (None)        -> Voz Masculina fallback ('alvaro' / 'Portuguese_GentleTeacher')
- Provedor Principal: Cloudflare Workers AI (@cf/deepgram/aura-2-es e @cf/deepgram/aura-1)
- Fallback em Alta Disponibilidade: OmniRoute (10.0.1.35)
- Armazenamento e Distribuição: Cloudflare R2 com CDN Global + Fallback em storage local.
- Cache SHA-256 com zero reprocessamento de textos já sintetizados.
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

# Fallback token do Wrangler caso não esteja no settings/env
_WRANGLER_FALLBACK_TOKEN = "cfoat_8eEIIwkVr-Olz2tnyeV6NCJUq6W4wjlT2d8GXdgdHdI.LU6JpZ0BDNLK3fnCPBfN-WNGmMixqf3NzUZF70a2YGM"
_WRANGLER_FALLBACK_ACCOUNT = "e0814c592e43284a2f6f9984bef32631"


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
        or _WRANGLER_FALLBACK_TOKEN
    )
    account = (
        get_setting("CLOUDFLARE_ACCOUNT_ID", "")
        or getattr(settings, "CLOUDFLARE_ACCOUNT_ID", "")
        or _WRANGLER_FALLBACK_ACCOUNT
    )
    return token, account


def _get_omniroute_credentials() -> tuple[str, str]:
    url = (
        get_setting("OMNIROUTER_URL", "")
        or getattr(settings, "OMNIROUTER_URL", "")
        or getattr(settings, "OMNIROUTE_BASE_URL", "")
        or "http://10.0.1.35/v1"
    ).rstrip("/")
    if not url.endswith("/v1"):
        endpoint = f"{url}/v1"
    else:
        endpoint = url
    token = (
        get_setting("OMNIROUTER_API_KEY", "")
        or getattr(settings, "OMNIROUTER_API_KEY", "")
        or getattr(settings, "OPENCODE_API_KEY", "")
        or "sk-K24JZCN5VGMu2yXL9ItYOO8F9Xp9aaVtkhr5tUyjzYi98D3WeTk8EADVEtsF5VFo"
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
            from integrations.cloudflare.r2 import get_r2_public_url
            return get_r2_public_url(rel_path)
        return local_public_url

    audio_bytes: bytes | None = None
    failures: list[str] = []

    # 2. Tentativa 1: ElevenLabs Turbo v2.5 via OmniRoute (Nativo Brasileiro, ~0.3s)
    omni_base, omni_token = _get_omniroute_credentials()
    try:
        url = f"{omni_base}/audio/speech"
        headers = {
            "Authorization": f"Bearer {omni_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "elevenlabs/eleven_turbo_v2_5",
            "input": spoken_text,
            "voice": chosen_voice,
        }
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code == 200 and resp.content:
                audio_bytes = resp.content
                logger.info(
                    "tts.success",
                    provider="omniroute_elevenlabs_turbo",
                    model="elevenlabs/eleven_turbo_v2_5",
                    voice=chosen_voice,
                )
            else:
                failures.append(f"omni/eleven-turbo ({resp.status_code}): {resp.text[:100]}")
    except Exception as exc:
        failures.append(f"omni/eleven-turbo: {exc}")
        logger.warning("tts.provider_failed", provider="omniroute_elevenlabs_turbo", error=str(exc))

    # 3. Tentativa 2: ElevenLabs Multilingual v2 via OmniRoute
    if not audio_bytes:
        try:
            url = f"{omni_base}/audio/speech"
            headers = {
                "Authorization": f"Bearer {omni_token}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "elevenlabs/eleven_multilingual_v2",
                "input": spoken_text,
                "voice": chosen_voice,
            }
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
                if resp.status_code == 200 and resp.content:
                    audio_bytes = resp.content
                    logger.info(
                        "tts.success",
                        provider="omniroute_elevenlabs_v2",
                        model="elevenlabs/eleven_multilingual_v2",
                        voice=chosen_voice,
                    )
                else:
                    failures.append(f"omni/eleven-v2 ({resp.status_code}): {resp.text[:100]}")
        except Exception as exc:
            failures.append(f"omni/eleven-v2: {exc}")
            logger.warning("tts.provider_failed", provider="omniroute_elevenlabs_v2", error=str(exc))

    # 4. Tentativa 3: Fallback Cloudflare Workers AI - Deepgram Aura-2
    if not audio_bytes:
        token, account_id = _get_cf_credentials()
        cf_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/deepgram/aura-2-es"
            payload = {"text": spoken_text, "speaker": voice_cfg["aura2_speaker"]}
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload, headers=cf_headers)
                if resp.status_code == 200 and resp.content:
                    audio_bytes = resp.content
                    logger.info("tts.cf_fallback_success", model="@cf/deepgram/aura-2-es")
                else:
                    failures.append(f"cf/aura-2-es ({resp.status_code}): {resp.text[:100]}")
        except Exception as exc:
            failures.append(f"cf/aura-2-es: {exc}")

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
