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
        "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "OMNIROUTER_API_KEY", "OPENCODE_API_KEY",
    ):
        monkeypatch.setattr(settings, name, "", raising=False)
    monkeypatch.setattr(settings, "OMNIROUTER_URL", "http://tts.example.test/v1", raising=False)
    monkeypatch.setattr(tts.default_storage, "exists", lambda path: False)
    monkeypatch.setattr(tts, "is_r2_configured", lambda: False)
    monkeypatch.setitem(sys.modules, "edge_tts", None)


def test_unconfigured_speech_does_not_send_hardcoded_credentials(unconfigured_tts, monkeypatch):
    requested = []

    def unavailable(self, url, **kwargs):
        requested.append(url)
        return httpx.Response(503, content=b"unavailable")

    monkeypatch.setattr(httpx.Client, "post", unavailable)

    with pytest.raises(tts.CloudflareTtsError, match="Nenhum provedor"):
        tts.synthesize_speech("Teste sem credenciais", caller="test.credentials")

    assert requested == []


@pytest.mark.parametrize("provider", ["omniroute", "cloudflare"])
def test_configured_speech_provider_produces_real_cached_audio(
    unconfigured_tts, monkeypatch, settings, provider
):
    requested = []
    configured = (
        {"OMNIROUTER_API_KEY": "test-omni-key"}
        if provider == "omniroute"
        else {"CLOUDFLARE_API_TOKEN": "test-cf-key", "CLOUDFLARE_ACCOUNT_ID": "test-account"}
    )
    monkeypatch.setattr(tts, "get_setting", lambda key, default="": configured.get(key, default))
    audio = b"test-provider-audio"

    def synthesize(self, url, **kwargs):
        requested.append((url, kwargs["headers"]["Authorization"]))
        return httpx.Response(200, content=audio)

    monkeypatch.setattr(httpx.Client, "post", synthesize)

    result = tts.synthesize_speech(f"Teste de credenciais {provider}", caller="test.credentials")

    assert result
    if provider == "omniroute":
        assert requested == [("http://tts.example.test/v1/audio/speech", "Bearer test-omni-key")]
    else:
        assert requested == [(
            "https://api.cloudflare.com/client/v4/accounts/test-account/ai/run/@cf/deepgram/aura-2-es",
            "Bearer test-cf-key",
        )]
    path = result.split("/media/", 1)[1]
    assert Path(settings.MEDIA_ROOT, path).read_bytes() == audio
