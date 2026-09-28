"""Jev Cognitive AI Model Router (TypeSafe System One).

Atua como a catraca cognitiva do backend:
1. Avalia a complexidade de raciocínio da requisição (Score 0 a 3) em < 300ms.
2. Roteia para o modelo de menor custo viável:
   - Score 0 (Trivial/FAQ): Cache local / FAQ ($0 custo, <10ms).
   - Score 1 (Simples/FAQ curto): Provedor rápido (Gemini 2.5 Flash / Groq) ~90% economia.
   - Score 2 (Moderado): Provedor intermediário (Llama 3.3 70B / Gemini Flash).
   - Score 3 (Complexo/Crítico): Modelo de fronteira (Claude 3.5 Sonnet).
3. Fail-Safe: Se a chamada ao Jev falhar ou exceder 400ms, aplica fallback automático para Gemini Flash.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()

TYPESAFE_API_URL = getattr(settings, "TYPESAFE_API_URL", "https://api.typesafe.ai/v1/systemone")
TYPESAFE_TIMEOUT_S = getattr(settings, "TYPESAFE_TIMEOUT_S", 0.6)


@dataclass(frozen=True)
class RoutingDecision:
    score: float
    tier: str  # "cache" | "fast" | "medium" | "frontier"
    recommended_model: str
    confidence: float
    source: str  # "jev" | "fallback"
    latency_ms: int
    raw_probabilities: dict[str, float]


def _get_api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key

    # Se estiver rodando dentro do backend, busca do cofre Infisical
    try:
        from integrations.infisical.client import InfisicalClient
        infisical_key = InfisicalClient().get_secret("TYPESAFE_API_KEY")
        if infisical_key:
            return infisical_key
    except Exception:
        pass

    return getattr(settings, "TYPESAFE_API_KEY", "")


def classify_complexity(prompt: str, context: dict[str, Any] | None = None) -> RoutingDecision:
    """Classifica a complexidade cognitiva da solicitação usando o Jev (System One)."""
    start_time = time.monotonic()
    api_key = _get_api_key()

    if not api_key:
        logger.warning("router.typesafe_api_key_missing", fallback="fast")
        return RoutingDecision(
            score=1.0,
            tier="fast",
            recommended_model="google/gemini-2.5-flash",
            confidence=0.5,
            source="fallback_missing_key",
            latency_ms=0,
            raw_probabilities={},
        )

    payload = {
        "model": "jev-latest",
        "state": {
            "prompt": prompt[:3000],
            "context": context or {},
        },
        "questions": {
            "complexidade": {
                "type": "score",
                "instructions": "Avalie a complexidade de raciocínio necessária para processar esta solicitação:",
                "criteria": [
                    "0 - Pergunta trivial, repetitiva, FAQ, status cadastral ou resposta fixa",
                    "1 - Tarefa simples de redação, formatação, extração ou resumo leve",
                    "2 - Pergunta técnica moderada, classificação ou resposta contextualizada",
                    "3 - Raciocínio profundo, ambiguidade alta, auditoria de fraude ou análise crítica",
                ],
            },
            "tier": {
                "type": "choice",
                "instructions": "Qual categoria de modelo de IA deve atender esta solicitação?",
                "criteria": {
                    "cache": "Resposta fixa, FAQ catalogado, dados estáticos de navegação",
                    "fast": "Resumo rápido, resposta direta, formatação de dados",
                    "medium": "Dúvida explicativa padrão, tradução ou classificação elaborada",
                    "frontier": "Redação criativa complexa, contestação, análise pedagógica ou fraude",
                },
            },
        },
    }

    try:
        with httpx.Client(timeout=TYPESAFE_TIMEOUT_S) as client:
            resp = client.post(
                TYPESAFE_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        latency_ms = int((time.monotonic() - start_time) * 1000)

        if resp.status_code == 200:
            data = resp.json()
            answers = data.get("answers", {})

            score_ans = answers.get("complexidade", {})
            tier_ans = answers.get("tier", {})

            score_val = float(score_ans.get("score", 1.0))
            tier_choice = str(tier_ans.get("choice", "fast"))
            confidence = float(score_ans.get("confidence", 0.8))

            # Mapeamento estrito do modelo recomendado
            if score_val < 0.4 or tier_choice == "cache":
                tier = "cache"
                model = "cache"
            elif score_val < 1.6 or tier_choice == "fast":
                tier = "fast"
                model = "google/gemini-2.5-flash"
            elif score_val < 2.5 or tier_choice == "medium":
                tier = "medium"
                model = "groq/llama-3.3-70b"
            else:
                tier = "frontier"
                model = "anthropic/claude-3-5-sonnet"

            logger.info(
                "router.classified",
                score=score_val,
                tier=tier,
                model=model,
                latency_ms=latency_ms,
            )

            return RoutingDecision(
                score=score_val,
                tier=tier,
                recommended_model=model,
                confidence=confidence,
                source="jev",
                latency_ms=latency_ms,
                raw_probabilities=score_ans.get("probabilities", {}),
            )

        logger.warning(
            "router.typesafe_api_error",
            status_code=resp.status_code,
            response=resp.text[:200],
        )

    except Exception as exc:
        latency_ms = int((time.monotonic() - start_time) * 1000)
        logger.warning("router.typesafe_timeout_or_error", error=str(exc), latency_ms=latency_ms)

    # Fail-Safe transparente: cai para Gemini Flash
    return RoutingDecision(
        score=1.0,
        tier="fast",
        recommended_model="google/gemini-2.5-flash",
        confidence=0.5,
        source="fallback_error",
        latency_ms=int((time.monotonic() - start_time) * 1000),
        raw_probabilities={},
    )
