"""
tests/test_edge_cache_and_cloudflare.py — Testes Unitários de Edge Cache e Validação Cloudflare.
"""

from __future__ import annotations

from unittest import mock
import pytest
from django.test import Client, override_settings
from django.urls import path
from ninja import NinjaAPI, Router

from core.edge_cache import EdgeCacheMiddleware, edge_cache
from integrations.cloudflare.cache import purge_edge_cache


# Setup de Router e API de Teste
test_api = NinjaAPI()
test_router = Router()


@test_router.get("/public-pricing")
@edge_cache(max_age=60, s_maxage=300, stale_while_revalidate=600)
def mock_pricing(request, ref: str | None = None):
    return {"plan": "EJA", "price": 99.0, "ref": ref}


@test_router.get("/public-hubs")
@edge_cache(max_age=60, s_maxage=300, stale_while_revalidate=600)
def mock_hubs(request):
    return [{"hub_id": "hub-sp-01", "city": "São Paulo"}]


test_api.add_router("", test_router)
urlpatterns = [path("api/v1/clients/", test_api.urls)]


@pytest.fixture
def cache_client(settings):
    """Cliente de teste com o EdgeCacheMiddleware ativado."""
    middleware = [
        "core.edge_cache.EdgeCacheMiddleware",
        "django.middleware.common.CommonMiddleware",
    ]
    with override_settings(MIDDLEWARE=middleware, ROOT_URLCONF=__name__):
        yield Client()


def test_pricing_cache_headers_and_etag(cache_client: Client):
    """Verifica se os cabeçalhos de borda e ETag são gerados corretamente."""
    resp = cache_client.get("/api/v1/clients/public-pricing?ref=consultor123")
    assert resp.status_code == 200

    # 1. Cache-Control completo
    cc = resp.headers.get("Cache-Control", "")
    assert "public" in cc
    assert "max-age=60" in cc
    assert "s-maxage=300" in cc
    assert "stale-while-revalidate=600" in cc

    # 2. Vary completo
    vary = resp.headers.get("Vary", "")
    assert "Accept-Encoding" in vary
    assert "Origin" in vary

    # 3. ETag gerado
    etag = resp.headers.get("ETag")
    assert etag is not None
    assert etag.startswith('"') and etag.endswith('"')

    # 4. Dados corretos do Ninja
    data = resp.json()
    assert data["plan"] == "EJA"
    assert data["ref"] == "consultor123"


def test_conditional_get_http_304_not_modified(cache_client: Client):
    """Verifica se uma requisição com If-None-Match idêntico retorna HTTP 304 sem payload."""
    resp1 = cache_client.get("/api/v1/clients/public-pricing")
    assert resp1.status_code == 200
    etag = resp1.headers.get("ETag")
    assert etag is not None

    # Envia If-None-Match
    resp2 = cache_client.get("/api/v1/clients/public-pricing", HTTP_IF_NONE_MATCH=etag)
    assert resp2.status_code == 304
    assert len(resp2.content) == 0  # Corpo vazio no 304
    assert resp2.headers.get("ETag") == etag


def test_security_auth_header_bypasses_public_cache(cache_client: Client):
    """Se o usuário estiver autenticado (Authorization header), o cache DEVE ser desativado."""
    resp = cache_client.get(
        "/api/v1/clients/public-pricing",
        HTTP_AUTHORIZATION="Bearer fake_jwt_token",
    )
    assert resp.status_code == 200
    cc = resp.headers.get("Cache-Control", "")
    assert "public" not in cc
    assert "private" in cc
    assert "no-store" in cc
    assert "ETag" not in resp.headers


def test_cloudflare_purge_api_call(settings):
    """Testa a integração com a API de Purge da Cloudflare."""
    settings.CLOUDFLARE_ZONE_ID = "mock_zone_123"
    settings.CLOUDFLARE_API_TOKEN = "mock_token_abc"

    with mock.patch("httpx.Client.post") as mock_post:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"success": True, "errors": [], "messages": []}

        success = purge_edge_cache(urls=["https://backend.supletivo.net.br/api/v1/clients/pricing"])
        assert success is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "mock_zone_123/purge_cache" in args[0]
        assert kwargs["json"] == {"files": ["https://backend.supletivo.net.br/api/v1/clients/pricing"]}


def test_live_pricing_endpoint_has_edge_cache_headers(client: Client):
    """Testa se a rota real /api/v1/clients/pricing recebe os cabeçalhos de edge cache."""
    resp = client.get("/api/v1/clients/pricing")
    assert resp.status_code == 200
    cc = resp.headers.get("Cache-Control", "")
    assert "public" in cc
    assert "s-maxage=300" in cc
