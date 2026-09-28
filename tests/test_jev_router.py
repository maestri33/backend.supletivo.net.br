"""Testes unitários e de integração do Jev Cognitive AI Model Router."""

import pytest
from unittest.mock import patch, MagicMock

from integrations.ai.router import classify_complexity, RoutingDecision


def test_router_fallback_when_api_key_missing(monkeypatch):
    """Garante que sem chave de API o router não quebra e cai em fallback para Gemini Flash."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with patch("integrations.ai.router._get_api_key", return_value=""):
        decision = classify_complexity("Qual o horário da aula?")
        assert decision.tier == "fast"
        assert decision.recommended_model == "google/gemini-2.5-flash"
        assert "fallback" in decision.source


def test_router_fallback_on_timeout():
    """Garante que em caso de timeout/erro HTTP o router cai para Gemini Flash transparentemente."""
    with patch("integrations.ai.router._get_api_key", return_value="test_key"):
        with patch("httpx.Client.post", side_effect=Exception("Connection timed out")):
            decision = classify_complexity("Pergunta teste")
            assert decision.tier == "fast"
            assert decision.recommended_model == "google/gemini-2.5-flash"
            assert decision.source == "fallback_error"


def test_router_classifies_simple_query():
    """Simula resposta do Jev para query trivial/FAQ."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "answers": {
            "complexidade": {"score": 0.15, "confidence": 0.95},
            "tier": {"choice": "cache"},
        }
    }

    with patch("integrations.ai.router._get_api_key", return_value="valid_key"):
        with patch("httpx.Client.post", return_value=mock_resp):
            decision = classify_complexity("qual o link para acessar a sala de aula virtual?")
            assert decision.tier == "cache"
            assert decision.recommended_model == "cache"
            assert decision.score < 0.4
            assert decision.source == "jev"


def test_router_classifies_complex_query():
    """Simula resposta do Jev para query de redação ou raciocínio complexo."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "answers": {
            "complexidade": {"score": 2.85, "confidence": 0.92},
            "tier": {"choice": "frontier"},
        }
    }

    with patch("integrations.ai.router._get_api_key", return_value="valid_key"):
        with patch("httpx.Client.post", return_value=mock_resp):
            decision = classify_complexity(
                "Preciso de uma redação modelo analisando os impactos da LDB 9394/96 na EJA com teses contrapostas."
            )
            assert decision.tier == "frontier"
            assert decision.recommended_model == "anthropic/claude-3-5-sonnet"
            assert decision.score >= 2.5
            assert decision.source == "jev"


def test_payment_failure_and_expiration_hooks():
    """Testa que os hooks on_payment_failed e on_payment_expired delegam para o service."""
    from users.roles.lead.hooks import on_payment_failed, on_payment_expired

    with patch("users.roles.lead.service.mark_payment_failed", return_value=True) as mock_fail:
        res = on_payment_failed(provider="infinitepay", provider_payment_id="pay_fail_1", reason="insufficient_funds")
        assert res is True
        mock_fail.assert_called_once_with(provider="infinitepay", provider_payment_id="pay_fail_1", reason="insufficient_funds")

    with patch("users.roles.lead.service.mark_payment_expired", return_value=True) as mock_exp:
        res = on_payment_expired(provider="infinitepay", provider_payment_id="pay_exp_1", reason="pix_expired")
        assert res is True
        mock_exp.assert_called_once_with(provider="infinitepay", provider_payment_id="pay_exp_1", reason="pix_expired")


def test_notify_payment_recovery_execution():
    """Testa que _notify_payment_recovery constrói idempotency_key com time e despacha send_event."""
    from users.roles.lead.service import _notify_payment_recovery

    mock_lead = MagicMock()
    mock_lead.external_id = "test-lead-uuid"
    mock_lead.user = MagicMock()
    mock_lead.checkout = MagicMock()
    mock_lead.checkout.short_token = "tok123"

    mock_profile = MagicMock()
    mock_profile.name = "Carlos Silva"

    with patch("users.profiles.interface.get", return_value=mock_profile):
        with patch("notify.interface.events.send_event") as mock_send:
            _notify_payment_recovery(mock_lead, "lead.card_declined", "insufficient_funds")
            assert mock_send.called
            call_args = mock_send.call_args
            assert call_args[0][0] == "lead.card_declined"
            assert call_args[1]["ctx"]["nome"] == "Carlos"
            assert "lead.card_declined_test-lead-uuid_" in call_args[1]["idempotency_key"]


def test_tools_ai_classify_route_endpoint():
    """Testa o endpoint Ninja POST /api/v1/tools/ai/classify-route com autenticação de serviço."""
    from ninja.testing import TestClient
    from api.tools.router import api as tools_api

    client = TestClient(tools_api)

    with patch("api.tools.router.service_secret_ok", return_value=True):
        with patch("integrations.ai.router.classify_complexity") as mock_classify:
            mock_classify.return_value = RoutingDecision(
                score=0.2,
                tier="cache",
                recommended_model="cache",
                confidence=0.98,
                source="jev",
                latency_ms=12,
                raw_probabilities={},
            )

            resp = client.post(
                "/ai/classify-route",
                json={"prompt": "como emitir segunda via do certificado?", "context": {}},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["tier"] == "cache"
            assert data["recommended_model"] == "cache"
            assert data["score"] == 0.2
            assert data["source"] == "jev"

