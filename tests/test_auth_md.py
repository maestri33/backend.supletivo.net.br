"""
Tests for Auth.md Agent Registration Discovery endpoints.

Verifies compliance with:
- /auth.md specification (H1 heading containing auth.md, self-contained guide)
- RFC 9728 OAuth Protected Resource Metadata (PRM)
- RFC 8414 OAuth Authorization Server Metadata with agent_auth profile extension
"""

import json
import pytest
from django.test import Client


@pytest.fixture
def client():
    return Client()


def test_auth_md_endpoint_serves_markdown(client):
    """
    Test /auth.md returns 200, markdown content-type, and H1 heading with 'auth.md'.
    """
    response = client.get("/auth.md")
    assert response.status_code == 200
    assert "text/markdown" in response["Content-Type"]

    content = response.content.decode("utf-8")
    assert any(
        line.strip().startswith("#") and "auth.md" in line.lower()
        for line in content.splitlines()
    ), "auth.md must contain an H1 heading with 'auth.md'"

    # Verify self-contained guide elements
    assert "agent" in content.lower()
    assert "urn:ietf:params:oauth:token-type:id-jag" in content
    assert "claim" in content.lower()
    assert "Bearer" in content
    assert "revocation" in content.lower()


def test_oauth_protected_resource_metadata(client):
    """
    Test /.well-known/oauth-protected-resource returns valid RFC 9728 PRM document.
    """
    response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    assert "application/json" in response["Content-Type"]

    data = json.loads(response.content.decode("utf-8"))

    # Required fields in PRM
    assert "resource" in data
    assert "authorization_servers" in data
    assert isinstance(data["authorization_servers"], list)
    assert len(data["authorization_servers"]) > 0
    assert "scopes_supported" in data
    assert isinstance(data["scopes_supported"], list)
    assert "bearer_methods_supported" in data
    assert "header" in data["bearer_methods_supported"]


def test_oauth_authorization_server_metadata(client):
    """
    Test /.well-known/oauth-authorization-server returns valid RFC 8414 metadata
    and complete agent_auth extension block.
    """
    prm_response = client.get("/.well-known/oauth-protected-resource")
    prm_data = json.loads(prm_response.content.decode("utf-8"))

    as_response = client.get("/.well-known/oauth-authorization-server")
    assert as_response.status_code == 200
    assert "application/json" in as_response["Content-Type"]

    data = json.loads(as_response.content.decode("utf-8"))

    # Issuer must match authorization_servers in PRM
    assert "issuer" in data
    assert data["issuer"] in prm_data["authorization_servers"]

    assert "token_endpoint" in data
    assert "revocation_endpoint" in data
    assert "grant_types_supported" in data

    # agent_auth block verification
    assert "agent_auth" in data
    agent_auth = data["agent_auth"]

    assert "skill" in agent_auth
    assert agent_auth["skill"].endswith("/auth.md")
    assert "register_uri" in agent_auth

    # Identity types verification
    identity_types = agent_auth.get("identity_types_supported", [])
    assert "identity_assertion" in identity_types
    assert "anonymous" in identity_types

    # ID-JAG and Verified Email assertion flow metadata
    assert "identity_assertion" in agent_auth
    id_assertion = agent_auth["identity_assertion"]
    assert "assertion_types_supported" in id_assertion
    assert "urn:ietf:params:oauth:token-type:id-jag" in id_assertion["assertion_types_supported"]
    assert "verified_email" in id_assertion["assertion_types_supported"]
    assert "credential_types_supported" in id_assertion
    assert "bearer_token" in id_assertion["credential_types_supported"]

    # Anonymous flow metadata
    assert "anonymous" in agent_auth
    anon = agent_auth["anonymous"]
    assert "credential_types_supported" in anon
    assert "bearer_token" in anon["credential_types_supported"]
    assert "claim_uri" in agent_auth

    # Revocation and events metadata
    assert "revocation_uri" in agent_auth
    assert "events_supported" in agent_auth
    assert any("revoked" in ev or "revocation" in ev for ev in agent_auth["events_supported"])


def test_agent_auth_endpoint(client):
    """
    Test /api/v1/agent/auth responds gracefully to GET and protects against accidental probing.
    """
    # GET returns active discovery information
    response = client.get("/api/v1/agent/auth")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"
    assert "discovery" in data

    # POST empty body returns 400
    post_empty = client.post("/api/v1/agent/auth", data="", content_type="application/json")
    assert post_empty.status_code == 400

    # POST with registration payload returns 202
    post_valid = client.post(
        "/api/v1/agent/auth",
        data=json.dumps({"type": "anonymous"}),
        content_type="application/json",
    )
    assert post_valid.status_code == 202
    assert "claim_uri" in post_valid.json()
