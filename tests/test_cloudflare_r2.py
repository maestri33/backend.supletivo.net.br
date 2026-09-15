"""Testes unitários para integração com Cloudflare R2 (S3 SigV4 sem boto3)."""

import pytest
from django.test import override_settings

from core.media import replace_media, save_media
from integrations.cloudflare.r2 import (
    delete_from_r2,
    get_r2_public_url,
    is_r2_configured,
    upload_to_r2,
)


def test_is_r2_configured_false_by_default():
    assert is_r2_configured() is False


@override_settings(
    R2_ENABLED=True,
    R2_ACCOUNT_ID="test-acc",
    R2_ACCESS_KEY_ID="test-key",
    R2_SECRET_ACCESS_KEY="test-secret",
    R2_BUCKET_NAME="supletivo-media",
    R2_PUBLIC_URL="https://media.supletivo.net.br",
)
def test_is_r2_configured_true_when_set():
    assert is_r2_configured() is True
    assert get_r2_public_url("documents/doc123.pdf") == "https://media.supletivo.net.br/documents/doc123.pdf"


@override_settings(
    R2_ENABLED=True,
    R2_ACCOUNT_ID="test-acc",
    R2_ACCESS_KEY_ID="test-key",
    R2_SECRET_ACCESS_KEY="test-secret",
    R2_BUCKET_NAME="supletivo-media",
    R2_PUBLIC_URL="https://media.supletivo.net.br",
)
def test_upload_to_r2_success(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = "OK"

    recorded = {}

    def fake_put(url, content, headers, timeout):
        recorded["url"] = url
        recorded["content"] = content
        recorded["headers"] = headers
        return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "put", fake_put)

    url = upload_to_r2(b"pdf-binary-data", "documents/doc123.pdf", content_type="application/pdf")
    assert url == "https://media.supletivo.net.br/documents/doc123.pdf"
    assert "test-acc.r2.cloudflarestorage.com" in recorded["url"]
    assert "supletivo-media" in recorded["url"]
    assert "AWS4-HMAC-SHA256" in recorded["headers"]["Authorization"]
    assert recorded["headers"]["Content-Type"] == "application/pdf"


@override_settings(
    R2_ENABLED=True,
    R2_ACCOUNT_ID="test-acc",
    R2_ACCESS_KEY_ID="test-key",
    R2_SECRET_ACCESS_KEY="test-secret",
    R2_BUCKET_NAME="supletivo-media",
)
def test_delete_from_r2_success(monkeypatch):
    class FakeResponse:
        status_code = 204
        text = ""

    recorded = {}

    def fake_delete(url, headers, timeout):
        recorded["url"] = url
        recorded["headers"] = headers
        return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "delete", fake_delete)

    ok = delete_from_r2("documents/doc123.pdf")
    assert ok is True
    assert "test-acc.r2.cloudflarestorage.com" in recorded["url"]
    assert "AWS4-HMAC-SHA256" in recorded["headers"]["Authorization"]


@override_settings(
    R2_ENABLED=True,
    R2_ACCOUNT_ID="test-acc",
    R2_ACCESS_KEY_ID="test-key",
    R2_SECRET_ACCESS_KEY="test-secret",
    R2_BUCKET_NAME="supletivo-media",
)
def test_save_and_replace_media_calls_r2(monkeypatch):
    uploaded = []
    deleted = []

    monkeypatch.setattr(
        "integrations.cloudflare.r2.upload_to_r2",
        lambda data, path, content_type: uploaded.append((path, content_type)),
    )
    monkeypatch.setattr(
        "integrations.cloudflare.r2.delete_from_r2",
        lambda path: deleted.append(path) or True,
    )

    path1 = save_media(prefix="documents", data=b"data1", ext="png")
    assert len(uploaded) == 1
    assert uploaded[0][0] == path1
    assert uploaded[0][1] == "image/png"

    path2 = replace_media(old=path1, prefix="documents", data=b"data2", ext="jpg")
    assert len(uploaded) == 2
    assert len(deleted) == 1
    assert deleted[0] == path1
