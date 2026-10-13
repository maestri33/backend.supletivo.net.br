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
        "WORKERS_AI_GATEWAY_TOKEN", "OMNIROUTER_API_KEY", "OMNIROUTE_API_KEY", "OPENCODE_API_KEY",
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

    with pytest.raises(tts.CloudflareTtsError, match="Nenhum provedor de TTS"):
        tts.synthesize_speech("Teste sem credenciais", caller="test.credentials")

    assert requested == []


def test_elevenlabs_failure_advances_to_multilingual(unconfigured_tts, monkeypatch, settings):
    monkeypatch.setattr(settings, "OMNIROUTE_API_KEY", "configured-test-key", raising=False)
    monkeypatch.setattr(settings, "OMNIROUTE_BASE_URL", "https://gateway.example.test/v1", raising=False)
    calls = []
    def post(self, url, **kwargs):
        calls.append(kwargs["json"]["model"])
        return httpx.Response(503, text="unavailable") if len(calls) == 1 else httpx.Response(200, content=b"provider-audio")
    monkeypatch.setattr(httpx.Client, "post", post)
    result = tts.synthesize_speech("Teste da cadeia", gender="M")
    assert result
    assert calls == ["elevenlabs/eleven_turbo_v2_5", "elevenlabs/eleven_multilingual_v2"]


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
