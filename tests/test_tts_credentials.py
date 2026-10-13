"""Speech generation must use configured credentials or fail truthfully."""

import sys
from pathlib import Path

import httpx
import pytest
from django.conf import settings

from integrations.cloudflare import tts


@pytest.fixture
def unconfigured_tts(monkeypatch, settings):
    monkeypatch.setattr(tts, "get_setting", lambda key, default="": default)
    for name in (
        "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "WORKERS_AI_GATEWAY_URL",
        "WORKERS_AI_GATEWAY_TOKEN", "OMNIROUTER_API_KEY", "OPENCODE_API_KEY",
    ):
        monkeypatch.setattr(settings, name, "", raising=False)
    monkeypatch.setattr(settings, "WORKERS_AI_GATEWAY_URL", "", raising=False)
    monkeypatch.setattr(settings, "WORKERS_AI_GATEWAY_TOKEN", "", raising=False)
    monkeypatch.setattr(tts.default_storage, "exists", lambda path: False)
    monkeypatch.setattr(tts, "is_r2_configured", lambda: False)
    monkeypatch.setitem(sys.modules, "edge_tts", None)


def test_unconfigured_speech_does_not_send_hardcoded_credentials(unconfigured_tts, monkeypatch):
    requested = []

    def unavailable(self, url, **kwargs):
        requested.append(url)
        return httpx.Response(503, content=b"unavailable")

    monkeypatch.setattr(httpx.Client, "post", unavailable)

    with pytest.raises(tts.CloudflareTtsError, match="Cloudflare Workers AI TTS indisponível"):
        tts.synthesize_speech("Teste sem credenciais", caller="test.credentials")

    assert requested == []


def test_configured_cloudflare_speech_provider_produces_real_cached_audio(
    unconfigured_tts, monkeypatch, settings
):
    requested = []
    monkeypatch.setattr(settings, "WORKERS_AI_GATEWAY_URL", "https://gateway.example.test", raising=False)
    monkeypatch.setattr(settings, "WORKERS_AI_GATEWAY_TOKEN", "test-gateway-key", raising=False)
    audio = b"test-provider-audio"

    def synthesize(url, **kwargs):
        requested.append((url, kwargs["headers"]["Authorization"]))
        return httpx.Response(200, content=audio)

    monkeypatch.setattr(httpx, "post", synthesize)

    result = tts.synthesize_speech("Teste de credenciais Cloudflare", caller="test.credentials")

    assert result
    assert requested == [("https://gateway.example.test/v1/audio/speech", "Bearer test-gateway-key")]
    path = result.split("/media/", 1)[1]
    assert Path(settings.MEDIA_ROOT, path).read_bytes() == audio


def test_cloudflare_tts_r2_cache_hit_returns_public_url(
    unconfigured_tts, monkeypatch
):
    """A cached Cloudflare/R2 voice note must not hit an unbound local import."""
    from integrations.ai import cloudflare

    monkeypatch.setattr(cloudflare, "cloudflare_only", lambda: True)
    monkeypatch.setattr(tts.default_storage, "exists", lambda path: True)
    monkeypatch.setattr(tts, "is_r2_configured", lambda: True)
    monkeypatch.setattr(
        tts,
        "get_r2_public_url",
        lambda path: f"https://media.example.test/{path}",
    )

    result = tts.synthesize_speech("Mensagem em cache", gender="M", caller="test.cache")

    assert result.startswith("https://media.example.test/ai/tts/")
