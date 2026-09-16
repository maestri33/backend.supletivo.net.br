"""Unit tests for Wave 3: AI Decoupling & Cloudflare Workers AI Whisper STT."""

from __future__ import annotations

from unittest import mock
import pytest

from integrations.ai.cloudflare import (
    CloudflareWorkersAIClient,
    CloudflareWorkersAIError,
    is_workers_ai_configured,
)
from integrations.ai import service as ai_service
from integrations.ai.models import AiCall


def test_is_workers_ai_configured_flags(settings):
    settings.CLOUDFLARE_API_TOKEN = ""
    settings.CLOUDFLARE_ACCOUNT_ID = ""
    assert not is_workers_ai_configured()

    settings.CLOUDFLARE_API_TOKEN = "cf_token_123"
    settings.CLOUDFLARE_ACCOUNT_ID = "cf_account_456"
    assert is_workers_ai_configured()


@pytest.mark.asyncio
async def test_cloudflare_workers_ai_transcribe_success(settings):
    settings.CLOUDFLARE_API_TOKEN = "cf_token_123"
    settings.CLOUDFLARE_ACCOUNT_ID = "cf_account_456"

    client = CloudflareWorkersAIClient()
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "result": {"text": "Olá, esta é uma resposta de teste."},
    }

    with mock.patch("integrations.ai.cloudflare.get_ai_http_client") as mock_get_client:
        mock_http = mock.AsyncMock()
        mock_http.post.return_value = mock_resp
        mock_get_client.return_value = mock_http

        text = await client.transcribe(b"fake_audio_bytes")
        assert text == "Olá, esta é uma resposta de teste."
        mock_http.post.assert_awaited_once()
        args, kwargs = mock_http.post.await_args
        assert "cf_account_456/ai/run/@cf/openai/whisper" in args[0]
        assert kwargs["headers"]["Authorization"] == "Bearer cf_token_123"


@pytest.mark.django_db
def test_ai_service_transcribe_prefers_workers_ai(settings):
    """ai_service.transcribe calls Cloudflare Workers AI first when configured."""
    settings.CLOUDFLARE_API_TOKEN = "cf_token_123"
    settings.CLOUDFLARE_ACCOUNT_ID = "cf_account_456"

    with mock.patch("integrations.ai.cloudflare.CloudflareWorkersAIClient.transcribe", new_callable=mock.AsyncMock) as mock_cf_transcribe:
        mock_cf_transcribe.return_value = "Transcrição via Cloudflare Workers AI"

        result = ai_service.transcribe(b"audio", caller="test.training")
        assert result == "Transcrição via Cloudflare Workers AI"
        mock_cf_transcribe.assert_awaited_once()

        # Check AiCall record was created for cloudflare
        call = AiCall.objects.filter(caller="test.training", operation=AiCall.Operation.STT).latest("id")
        assert call.provider == "cloudflare"
        assert call.model == "@cf/openai/whisper"
        assert call.status == AiCall.Status.SUCCESS


@pytest.mark.django_db
def test_ai_service_transcribe_falls_back_to_gemini(settings):
    """When Cloudflare Workers AI fails, transcribe gracefully falls back to Gemini STT."""
    settings.CLOUDFLARE_API_TOKEN = "cf_token_123"
    settings.CLOUDFLARE_ACCOUNT_ID = "cf_account_456"
    settings.GEMINI_API_KEY = "gemini_key_123"

    with mock.patch("integrations.ai.cloudflare.CloudflareWorkersAIClient.transcribe", new_callable=mock.AsyncMock) as mock_cf, \
         mock.patch("integrations.ai.gemini.GeminiClient.transcribe", new_callable=mock.AsyncMock) as mock_gemini:
        mock_cf.side_effect = CloudflareWorkersAIError("Rate limited", status_code=429)
        mock_gemini.return_value = "Transcrição via Gemini Fallback"

        result = ai_service.transcribe(b"audio", caller="test.training_fallback")
        assert result == "Transcrição via Gemini Fallback"

        # Check that both calls were recorded in AiCall
        calls = list(AiCall.objects.filter(caller="test.training_fallback", operation=AiCall.Operation.STT).order_by("id"))
        assert len(calls) == 2
        assert calls[0].provider == "cloudflare"
        assert calls[0].status == AiCall.Status.ERROR
        assert calls[1].provider == "gemini"
        assert calls[1].status == AiCall.Status.SUCCESS
