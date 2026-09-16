"""Unit tests for Issue #4:
- GET /api/v1/clients/pricing public pricing endpoint
- Edge Anycast Cache-Control header
- CORS origins verification
"""

from __future__ import annotations

import pytest
from django.test import Client, override_settings

from hub.models import Hub
from users.address.models import Address
from users.auth.models import User
from users.profiles.models import Profile
from users.roles.promoter.models import Promoter


@pytest.mark.django_db
def test_pricing_endpoint_without_ref(client: Client):
    """GET /api/v1/clients/pricing without ref returns edge cache headers and standard pricing."""
    resp = client.get("/api/v1/clients/pricing")
    assert resp.status_code == 200
    data = resp.json()

    # Schema assertions
    assert "pix" in data
    assert "card" in data
    assert data["card"]["installments"] == 12
    assert data["has_discount"] is False
    assert data["promoter_name"] is None

    # Performance & Cloudflare edge cache assertion
    cache_header = resp.headers.get("Cache-Control", "")
    assert "public" in cache_header
    assert "s-maxage=300" in cache_header
    assert "stale-while-revalidate=600" in cache_header
    assert resp.headers.get("Vary") == "Origin"


@pytest.mark.django_db
def test_pricing_endpoint_with_valid_ref(client: Client):
    """GET /api/v1/clients/pricing with valid promoter ref returns discount and promoter name."""
    promoter_user = User.objects.create_user()
    Profile.objects.create(user=promoter_user, name="Carlos Silva Consultor")
    address = Address.objects.create(
        zipcode="01310100",
        street="Av Paulista",
        number="1000",
        neighborhood="Bela Vista",
        city="Sao Paulo",
        state="SP",
    )
    hub = Hub.objects.create(
        address=address,
        brand="supletivo",
        coordinator=promoter_user,
        is_default=True,
    )
    Promoter.objects.create(
        user=promoter_user,
        hub=hub,
        status=Promoter.Status.ACTIVE,
    )

    resp = client.get(f"/api/v1/clients/pricing?ref={promoter_user.external_id}")
    assert resp.status_code == 200
    data = resp.json()

    # Discount & promoter name populated
    assert data["has_discount"] is True
    assert data["promoter_name"] == "Carlos"
    assert data["promo_pix"] is not None
    assert data["promo_card"] is not None

    # Dynamic personalized responses must not have public s-maxage=300
    cache_header = resp.headers.get("Cache-Control", "")
    assert "s-maxage=300" not in cache_header


@pytest.mark.django_db
@override_settings(CORS_ALLOW_ALL_ORIGINS=False)
def test_pricing_cors_headers(client: Client):
    """Verify CORS Allow-Origin header for configured frontend origins."""
    for origin in ("https://supletivo.net.br", "http://localhost:3000", "http://localhost:3011"):
        resp = client.get("/api/v1/clients/pricing", HTTP_ORIGIN=origin)
        assert resp.status_code == 200
        assert resp.headers.get("Access-Control-Allow-Origin") == origin
