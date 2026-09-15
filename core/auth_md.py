"""
Auth.md Agent Registration Discovery — Open standard for AI agent authentication.

Implements:
- RFC 9728: OAuth 2.0 Protected Resource Metadata (PRM)
- RFC 8414: OAuth 2.0 Authorization Server Metadata
- Auth.md: Agentic registration discovery protocol with agent_auth profile extension
"""

from __future__ import annotations

import json
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods


def _get_base_url(request: HttpRequest) -> str:
    """Resolve the canonical base URL from request or forwarded headers."""
    return request.build_absolute_uri("/").rstrip("/")


@require_GET
def auth_md_view(request: HttpRequest) -> HttpResponse:
    """
    Serve /auth.md from the service root as Markdown with an H1 heading containing 'auth.md'.

    Provides human and machine-readable instructions for autonomous AI agents to
    discover, register, claim, and authenticate with the Supletivo Brasil Platform API.
    """
    base_url = _get_base_url(request)

    markdown_content = f"""# Supletivo Brasil Platform auth.md

You are an AI agent. The **Supletivo Brasil Platform API** supports **agentic registration**:
discover → register → (claim if needed) → exchange for an access token → call API → handle revocation.

Follow the steps in order; do not skip ahead.

## Agent Audience & Scope
- **Audience**: Autonomous AI agents acting on behalf of students, promoters, collaborators, or administrative systems within the Supletivo Brasil educational ecosystem.
- **Resource Server**: `{base_url}`
- **Authorization Server**: `{base_url}`
- **Documentation & Open Standards**: Complements RFC 9728 (Protected Resource Metadata) and RFC 8414 (Authorization Server Metadata).

---

## Step 1 — Discovery (Two-Hop Chain)

When an unauthenticated call is made, the service responds with:
```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer resource_metadata="{base_url}/.well-known/oauth-protected-resource"
```

### 1a. Protected Resource Metadata (PRM)
Endpoint: `GET {base_url}/.well-known/oauth-protected-resource`

Response returns canonical resource identity, authorization servers, supported scopes, and bearer methods (`header`).

### 1b. Authorization Server Metadata
Endpoint: `GET {base_url}/.well-known/oauth-authorization-server`

Contains the `agent_auth` block detailing registration URLs, supported identity types, credential types, and revocation endpoints.

---

## Step 2 — Registration Methods

The service supports three registration methods:

1. **ID-JAG (`urn:ietf:params:oauth:token-type:id-jag`)**:
   - For agents with user session identity issued by an approved IdP.
   - Requires minting an Identity Assertion JWT bound to `aud = {base_url}`.
   - Credential types: `bearer_token`, `api_key`.
   - Revocation supported via `{base_url}/api/v1/agent/revoke`.

2. **Verified Email**:
   - For agents operating with user consent verified via email challenge.
   - Claim URL provided for user confirmation: `{base_url}/api/v1/agent/claim`.
   - Credential types: `bearer_token`, `api_key`.

3. **Anonymous**:
   - For exploratory or pre-registration workflows without immediate user identity.
   - Credential types: `bearer_token`, `api_key`.
   - Allows upgrading/claiming later at `{base_url}/api/v1/agent/claim`.

---

## Step 3 — Credential Use & API Calling

Once an access token or API key is obtained:
- Present the credential in the HTTP `Authorization` header:
  ```http
  Authorization: Bearer <access_token>
  ```
- Scopes supported include:
  - `clients:read`, `clients:write` (Student portal and enrollment)
  - `collaborators:read`, `collaborators:write` (Promoter operations)
  - `staff:read`, `staff:write` (Internal operations)
  - `leadership:read`, `leadership:write` (Administrative access)

---

## Step 4 — Revocation & Lifecycle

- Revocation endpoint: `{base_url}/api/v1/agent/revoke`
- Token revocation conforms to RFC 7009 (`POST {base_url}/oauth2/revoke`).
- Upstream revocation events are accepted at the events notification handler.
"""

    return HttpResponse(
        markdown_content.strip(),
        content_type="text/markdown; charset=utf-8",
    )


@require_GET
def oauth_protected_resource_view(request: HttpRequest) -> JsonResponse:
    """
    Serve RFC 9728 Protected Resource Metadata (PRM).

    Returns:
    - resource: Canonical URL of the protected resource
    - authorization_servers: List of advertised authorization server base URLs
    - scopes_supported: Scopes supported by the resource server
    - bearer_methods_supported: ["header"]
    """
    base_url = _get_base_url(request)

    data = {
        "resource": f"{base_url}/",
        "resource_name": "Supletivo Brasil Platform API",
        "authorization_servers": [
            f"{base_url}/",
        ],
        "scopes_supported": [
            "clients:read",
            "clients:write",
            "collaborators:read",
            "collaborators:write",
            "staff:read",
            "staff:write",
            "leadership:read",
            "leadership:write",
        ],
        "bearer_methods_supported": [
            "header",
        ],
    }
    return JsonResponse(data, json_dumps_params={"indent": 2})


@require_GET
def oauth_authorization_server_view(request: HttpRequest) -> JsonResponse:
    """
    Serve RFC 8414 OAuth 2.0 Authorization Server Metadata with agent_auth extension.

    Provides the agent_auth bootstrap block for autonomous agent registration:
    - ID-JAG: identity_assertion with urn:ietf:params:oauth:token-type:id-jag
    - Verified Email: identity_assertion with verified_email and claim_uri
    - Anonymous: anonymous with credential_types and claim_uri
    - revocation_uri and events_supported
    """
    base_url = _get_base_url(request)

    data = {
        "issuer": f"{base_url}/",
        "authorization_endpoint": f"{base_url}/oauth2/authorize",
        "token_endpoint": f"{base_url}/oauth2/token",
        "revocation_endpoint": f"{base_url}/oauth2/revoke",
        "grant_types_supported": [
            "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "urn:workos:agent-auth:grant-type:claim",
            "client_credentials",
        ],
        "scopes_supported": [
            "clients:read",
            "clients:write",
            "collaborators:read",
            "collaborators:write",
            "staff:read",
            "staff:write",
            "leadership:read",
            "leadership:write",
        ],
        "bearer_methods_supported": [
            "header",
        ],
        "agent_auth": {
            "skill": f"{base_url}/auth.md",
            "register_uri": f"{base_url}/api/v1/agent/auth",
            "identity_endpoint": f"{base_url}/api/v1/agent/identity",
            "claim_uri": f"{base_url}/api/v1/agent/claim",
            "claim_endpoint": f"{base_url}/api/v1/agent/claim",
            "revocation_uri": f"{base_url}/api/v1/agent/revoke",
            "identity_types_supported": [
                "identity_assertion",
                "anonymous",
            ],
            "identity_assertion": {
                "assertion_types_supported": [
                    "urn:ietf:params:oauth:token-type:id-jag",
                    "verified_email",
                ],
                "credential_types_supported": [
                    "bearer_token",
                    "api_key",
                ],
            },
            "anonymous": {
                "credential_types_supported": [
                    "bearer_token",
                    "api_key",
                ],
            },
            "events_supported": [
                "https://schemas.workos.com/events/agent/auth/identity/assertion/revoked",
                "revocation",
            ],
        },
    }
    return JsonResponse(data, json_dumps_params={"indent": 2})


@csrf_exempt
@require_http_methods(["GET", "POST"])
def agent_auth_view(request: HttpRequest) -> JsonResponse:
    """
    Agent authentication / registration entrypoint (/api/v1/agent/auth).

    Guards against unintended account creation during passive scans.
    Per Auth.md spec: 'Do not probe POST /agent/auth during passive scans.
    Registration can create accounts, send email, or issue credentials.
    Public discovery documents are the safe source of truth.'
    """
    base_url = _get_base_url(request)

    if request.method == "GET":
        return JsonResponse(
            {
                "status": "active",
                "message": "Supletivo Brasil Agent Authentication Discovery Endpoint. Refer to /auth.md for complete protocol steps.",
                "discovery": {
                    "skill": f"{base_url}/auth.md",
                    "protected_resource": f"{base_url}/.well-known/oauth-protected-resource",
                    "authorization_server": f"{base_url}/.well-known/oauth-authorization-server",
                },
            },
            status=200,
        )

    try:
        payload = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        payload = {}

    if not payload:
        return JsonResponse(
            {
                "error": "invalid_request",
                "error_description": "Empty payload. To register an agent, provide identity assertion or registration payload. Consult discovery document at /auth.md.",
            },
            status=400,
        )

    return JsonResponse(
        {
            "status": "pending_verification",
            "message": "Payload received. Complete agent verification via claim ceremony or token exchange.",
            "claim_uri": f"{base_url}/api/v1/agent/claim",
        },
        status=202,
    )
