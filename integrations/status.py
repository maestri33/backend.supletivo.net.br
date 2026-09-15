"""Status unificado das integrações externas pro painel do STAFF (WP6, Victor 2026-06-16).

Cada integração tem um fluxo próprio. Aqui a visão READ-ONLY (env presente — só BOOL, nunca o valor do
secret — + o último resultado do ledger `ValidationCheck`) + ações (asaas tem setup/teste AO VIVO; os
demais reportam o último do ledger, já que o health real deles roda por command assíncrono/pesado).
"""

from __future__ import annotations

from django.conf import settings

from core.validation import latest_checks

_REGISTRY: dict[str, dict] = {
    "asaas": {
        "env": [
            "ASAAS_API_KEY",
            "ASAAS_WEBHOOK_SECRET",
            "ASAAS_BASE_URL",
            "EXTERNAL_URL",
        ],
        "scope": "asaas",
        "flow": "onboarding → auto-cadastro do webhook → self-test (saldo) + transfer-validation",
    },
    "infinitepay": {
        "env": ["INFINITEPAY_HANDLE", "INFINITEPAY_BASE_URL", "EXTERNAL_URL"],
        "scope": "infinitepay",
        "flow": "checkout (autentica pelo handle) → webhook (order_nsu opaco) → payment_check",
    },
    "notify": {
        "env": ["NOTIFY_SERVER_URL", "NOTIFY_API_KEY"],
        "scope": "notify",
        "flow": "notify-server: WhatsApp, e-mail, TTS, templates e histórico",
    },
    "ai": {
        "env": [
            "OMNIROUTE_BASE_URL",
            "OMNIROUTE_API_KEY",
            "MINIMAX_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_VISION_API_KEY",
        ],
        "scope": "ai",
        "flow": "OmniRoute (http://10.0.1.35/v1) + LLM router + visão + OCR",
    },
    "biometric": {
        "env": ["BIOMETRIC_MODEL_NAME"],
        "scope": "biometric",
        "flow": "InsightFace buffalo_l (CPU): face-match documento×selfie",
    },
    "cep": {
        "env": [],
        "scope": "cep",
        "flow": "ViaCEP (API pública, sem key)",
    },
    "cpf": {
        "env": ["CPFHUB_API_KEY", "CPFHUB_BASE_URL"],
        "scope": "cpf",
        "flow": "CPFHub.io (header x-api-key): CPF → identidade",
    },
}


def _config(integ: dict) -> dict:
    """Só BOOL de presença da env (NUNCA o valor do secret)."""
    return {name: bool(getattr(settings, name, "")) for name in integ.get("env", [])}


def _summary(name: str, integ: dict) -> dict:
    cfg = _config(integ)
    try:
        checks = latest_checks(integ.get("scope", name))
    except Exception:
        checks = {}
    return {
        "name": name,
        "configured": all(cfg.values()) if cfg else True,  # cep não tem env
        "config": cfg,
        "flow": integ.get("flow", ""),
        "checks": checks or {},
    }


def list_integrations() -> list[dict]:
    """Visão READ-ONLY de TODAS as integrações (config + último resultado do ledger). Sem rede."""
    try:
        return [_summary(name, integ) for name, integ in _REGISTRY.items()]
    except Exception:
        return []


def integration_detail(name: str) -> dict | None:
    """Detalhe de uma integração. Pro asaas, faz o run_checks AO VIVO (saldo + webhook — rede)."""
    integ = _REGISTRY.get(name)
    if integ is None:
        return None
    try:
        data = _summary(name, integ)
    except Exception:
        data = {"name": name, "configured": False, "config": {}, "flow": "", "checks": {}}
    if name == "asaas":
        from integrations.bank.asaas import onboarding

        try:  # run_checks faz rede (saldo/webhook); timeout/erro não-AsaasError → erro estruturado
            data["live"] = onboarding.run_checks(record=False)
        except Exception as e:  # noqa: BLE001
            data["live"] = {"error": str(e)}
    return data
