"""Testes automatizados e de homologação do OmniRoute AI Gateway (LLM, OCR, TTS)."""

from __future__ import annotations

import httpx
import pytest
from django.test import override_settings

from integrations.ai.client import LLMClient, LLMError
from integrations.ai.models import AiCall
from integrations.ai.omniroute_ocr import OmniRouteOCRClient, OmniRouteOCRError
from integrations.ai.service import ocr
from integrations.ai.tts import (
    clean_text_for_speech,
    get_tts_chain,
    probe_tts,
    synthesize_voice_note,
    TtsOption,
)


# ── OmniRoute OCR Client ─────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_omniroute_ocr_detect_text_success():
    fake_image = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"

    def handler(request: httpx.Request):
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "REPÚBLICA FEDERATIVA DO BRASIL\nREGISTRO GERAL 12.345.678-9\nNOME: JOAO DA SILVA",
                        }
                    }
                ]
            },
        )

    client = OmniRouteOCRClient(base_url="http://10.0.1.35/v1", api_key="sk-test")
    # Patch the httpx transport inside detect_text
    orig_post = httpx.AsyncClient.post

    async def mock_post(self, url, *args, **kwargs):
        req = httpx.Request("POST", url, headers=kwargs.get("headers"), content=kwargs.get("content"))
        return handler(req)

    import unittest.mock as mock
    with mock.patch.object(httpx.AsyncClient, "post", mock_post):
        text = await client.detect_text(fake_image, document=True)

    assert "JOAO DA SILVA" in text
    assert "12.345.678-9" in text


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_omniroute_ocr_retryable_error_on_503():
    fake_image = b"test_img"

    async def mock_post(self, url, *args, **kwargs):
        return httpx.Response(503, text="Service Unavailable")

    import unittest.mock as mock
    client = OmniRouteOCRClient(base_url="http://10.0.1.35/v1")
    with mock.patch.object(httpx.AsyncClient, "post", mock_post):
        with pytest.raises(OmniRouteOCRError) as exc_info:
            await client.detect_text(fake_image)

    assert exc_info.value.retryable is True
    assert exc_info.value.status_code == 503


# ── OCR Fallback Chain (OmniRoute -> Google Vision) ──────────────────────────


@pytest.mark.django_db
def test_ocr_fallback_to_google_vision_when_omniroute_fails():
    fake_image = b"fake_document_content"

    async def mock_omni_detect(self, image_bytes, document=False):
        raise OmniRouteOCRError("OmniRoute 500 error", retryable=True, status_code=500)

    async def mock_vision_detect(self, image_bytes, document=False):
        return "NOME: MARIA OLIVEIRA CPF: 123.456.789-00"

    import unittest.mock as mock
    with mock.patch("integrations.ai.omniroute_ocr.OmniRouteOCRClient.detect_text", mock_omni_detect):
        with mock.patch("integrations.ai.vision_ocr.VisionOCRClient.detect_text", mock_vision_detect):
            with override_settings(OMNIROUTE_BASE_URL="http://10.0.1.35/v1"):
                result = ocr(fake_image, caller="test.ocr_fallback", document=True)

    assert "MARIA OLIVEIRA" in result
    # Verifica que registrou AiCall de erro pro OmniRoute e de sucesso pro Google Vision
    calls = list(AiCall.objects.filter(caller="test.ocr_fallback"))
    assert len(calls) == 2
    omni_call = next(c for c in calls if c.provider == "omniroute")
    vision_call = next(c for c in calls if c.provider == "google_vision")
    assert omni_call.status == AiCall.Status.ERROR
    assert vision_call.status == AiCall.Status.SUCCESS


# ── TTS & Victor Rule ─────────────────────────────────────────────────────────


def test_clean_text_for_speech():
    raw = "Olá *Victor*, acesse https://supletivo.net.br/matricula para conferir seus _documentos_!"
    cleaned = clean_text_for_speech(raw)
    assert "*" not in cleaned
    assert "_" not in cleaned
    assert "https://" not in cleaned
    assert "pelo link enviado" in cleaned
    assert "Olá Victor, acesse pelo link enviado para conferir seus documentos!" == cleaned


def test_tts_victor_cross_gender_rule():
    opt = TtsOption(
        model="minimax/speech-01-hd",
        voice_female="Portuguese_SereneWoman",
        voice_male="Portuguese_GentleTeacher",
    )
    # Destinatário Homem (M) recebe voz Feminina
    assert opt.voice_for("M") == "Portuguese_SereneWoman"
    assert opt.voice_for("m") == "Portuguese_SereneWoman"

    # Destinatário Mulher (F) recebe voz Masculina
    assert opt.voice_for("F") == "Portuguese_GentleTeacher"
    assert opt.voice_for("f") == "Portuguese_GentleTeacher"

    # Destinatário desconhecido (None / vazio) recebe voz Feminina padrão
    assert opt.voice_for(None) == "Portuguese_SereneWoman"
    assert opt.voice_for("") == "Portuguese_SereneWoman"


@pytest.mark.django_db
def test_synthesize_voice_note_with_omniroute():
    def mock_post(self, url, *args, **kwargs):
        assert "/v1/audio/speech" in url
        # Retorna fake ogg bytes
        return httpx.Response(200, content=b"OggS_fake_audio_stream_bytes_here")

    import unittest.mock as mock
    with mock.patch.object(httpx.Client, "post", mock_post):
        url = synthesize_voice_note(
            "Mensagem de teste para o aluno.",
            gender="M",
            caller="test.tts",
        )

    assert url is not None
    assert "/media/ai/tts/" in url
    assert url.endswith(".ogg")


def test_probe_tts_diagnostics():
    def mock_post(self, url, *args, **kwargs):
        return httpx.Response(200, content=b"OggS_probe_sample")

    import unittest.mock as mock
    with mock.patch.object(httpx.Client, "post", mock_post):
        diag = probe_tts("Teste de áudio diagnóstico", gender="F")

    assert diag["ok"] is True
    assert "omniroute_url" in diag
    assert len(diag["chain_results"]) > 0
    assert diag["chain_results"][0]["ok"] is True
