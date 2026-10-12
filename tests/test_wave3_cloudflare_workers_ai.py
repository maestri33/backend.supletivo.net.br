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
    settings.WORKERS_AI_GATEWAY_URL = ""
    settings.WORKERS_AI_GATEWAY_TOKEN = ""
    settings.CLOUDFLARE_API_TOKEN = ""
    settings.CLOUDFLARE_ACCOUNT_ID = ""
    assert not is_workers_ai_configured()

    settings.WORKERS_AI_GATEWAY_URL = "https://gateway.example.test"
    settings.WORKERS_AI_GATEWAY_TOKEN = "gateway_token_123"
    assert is_workers_ai_configured()


@pytest.mark.asyncio
async def test_cloudflare_workers_ai_transcribe_success(settings):
    settings.WORKERS_AI_GATEWAY_URL = "https://gateway.example.test"
    settings.WORKERS_AI_GATEWAY_TOKEN = "gateway_token_123"

    client = CloudflareWorkersAIClient()
    mock_resp = mock.MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "success": True,
        "text": "Olá, esta é uma resposta de teste.",
    }

    with mock.patch("integrations.ai.cloudflare.get_ai_http_client") as mock_get_client:
        mock_http = mock.AsyncMock()
        mock_http.post.return_value = mock_resp
        mock_get_client.return_value = mock_http

        text = await client.transcribe(b"fake_audio_bytes")
        assert text == "Olá, esta é uma resposta de teste."
        mock_http.post.assert_awaited_once()
        args, kwargs = mock_http.post.await_args
        assert "gateway.example.test/v1/transcriptions" in args[0]
        assert kwargs["headers"]["Authorization"] == "Bearer gateway_token_123"


@pytest.mark.django_db
def test_ai_service_transcribe_prefers_workers_ai(settings):
    """ai_service.transcribe calls Cloudflare Workers AI first when configured."""
    settings.WORKERS_AI_GATEWAY_URL = "https://gateway.example.test"
    settings.WORKERS_AI_GATEWAY_TOKEN = "gateway_token_123"

    with mock.patch("integrations.ai.cloudflare.CloudflareWorkersAIClient.transcribe", new_callable=mock.AsyncMock) as mock_cf_transcribe:
        mock_cf_transcribe.return_value = "Transcrição via Cloudflare Workers AI"

        result = ai_service.transcribe(b"audio", caller="test.training")
        assert result == "Transcrição via Cloudflare Workers AI"
        mock_cf_transcribe.assert_awaited_once()

        # Check AiCall record was created for the protected Cloudflare gateway.
        call = AiCall.objects.filter(caller="test.training", operation=AiCall.Operation.STT).latest("id")
        assert call.provider == "cloudflare"
        assert call.model == "@cf/openai/whisper"
        assert call.status == AiCall.Status.SUCCESS


@pytest.mark.django_db
def test_ai_service_transcribe_does_not_fallback_to_gemini(settings):
    """Production is Cloudflare-only: a gateway failure must remain visible."""
    settings.WORKERS_AI_GATEWAY_URL = "https://gateway.example.test"
    settings.WORKERS_AI_GATEWAY_TOKEN = "gateway_token_123"

    with mock.patch("integrations.ai.cloudflare.CloudflareWorkersAIClient.transcribe", new_callable=mock.AsyncMock) as mock_cf, \
         mock.patch("integrations.ai.gemini.GeminiClient.transcribe", new_callable=mock.AsyncMock) as mock_gemini:
        mock_cf.side_effect = CloudflareWorkersAIError("Rate limited", status_code=429)
        with pytest.raises(CloudflareWorkersAIError, match="Rate limited"):
            ai_service.transcribe(b"audio", caller="test.training_no_fallback")
        mock_gemini.assert_not_awaited()

        call = AiCall.objects.filter(caller="test.training_no_fallback", operation=AiCall.Operation.STT).latest("id")
        assert call.provider == "cloudflare"
        assert call.status == AiCall.Status.ERROR
