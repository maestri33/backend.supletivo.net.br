"""
Tests for Agentic Commerce Protocol (ACP) Discovery Document.
"""

from __future__ import annotations

import json
import pytest
from django.test import Client


@pytest.mark.django_db
def test_acp_discovery_returns_200_and_json():
    client = Client()
    response = client.get("/.well-known/acp.json")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    assert response["Access-Control-Allow-Origin"] == "*"

    data = json.loads(response.content.decode("utf-8"))

    # Protocol requirements
    assert "protocol" in data
    assert isinstance(data["protocol"], dict)
    assert data["protocol"].get("name") == "acp"
    assert isinstance(data["protocol"].get("version"), str)
    assert len(data["protocol"]["version"]) > 0

    # API base URL requirement
    assert "api_base_url" in data
    assert isinstance(data["api_base_url"], str)
    assert data["api_base_url"].startswith("http://") or data["api_base_url"].startswith("https://")

    # Transports requirement: non-empty array
    assert "transports" in data
    assert isinstance(data["transports"], list)
    assert len(data["transports"]) > 0
    assert "rest" in data["transports"]

    # Capabilities.services requirement: non-empty array
    assert "capabilities" in data
    assert isinstance(data["capabilities"], dict)
    assert "services" in data["capabilities"]
    assert isinstance(data["capabilities"]["services"], list)
    assert len(data["capabilities"]["services"]) > 0
    assert "checkout" in data["capabilities"]["services"]


@pytest.mark.django_db
def test_acp_discovery_respects_forwarded_headers():
    client = Client()
    response = client.get(
        "/.well-known/acp.json",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_X_FORWARDED_HOST="api.supletivo.net.br",
    )

    assert response.status_code == 200
    data = json.loads(response.content.decode("utf-8"))
    assert data["api_base_url"] == "https://api.supletivo.net.br"
