"""Registry de providers de IA + a cadeia de fallback — montado do .env via settings (CONVENTION §10).

Um provider é só `{base_url, api_key}` (CONVENTION §8). Como todos são OpenAI-compatible, somar um
provider novo é só linhas no `.env` — zero código aqui. A cadeia de fallback (`IA_FALLBACK_CHAIN`) é
uma lista ordenada de `(provider, model)`: o 1º é o default; em falha retryável o service cai pro próximo.
"""

from __future__ import annotations

from django.conf import settings

from .client import LLMClient, LLMError


def get_client(provider: str) -> LLMClient:
    """Instancia o client de um provider habilitado (com base_url/api_key do .env ou PlatformSetting)."""
    cfg = settings.IA_PROVIDERS.get(provider)
    if not cfg:
        from core.system_config import get_setting

        omni_base = get_setting("OMNIROUTE_BASE_URL", "https://ai.v7m.live/v1")
        omni_key = get_setting("OMNIROUTE_API_KEY", "sk-omniroute")
        if provider == "omniroute" and omni_base:
            cfg = {"base_url": omni_base, "api_key": omni_key}
        else:
            raise LLMError(
                f"provider de IA desconhecido ou sem credencial no .env: {provider!r}",
                retryable=False,
            )
    return LLMClient(
        provider=provider,
        base_url=cfg["base_url"],
        api_key=cfg.get("api_key", ""),
        temperature=settings.IA_DEFAULT_TEMPERATURE,
        max_tokens=settings.IA_MAX_TOKENS,
        timeout=settings.IA_TIMEOUT,
    )


def fallback_chain(model: str | None = None) -> list[tuple[str, str]]:
    """A cadeia `(provider, model)` a tentar. Com OmniRoute dinâmico como primário resiliente."""
    from core.system_config import get_setting

    omni_base = get_setting("OMNIROUTE_BASE_URL", "http://10.0.1.35/v1")
    omni_model = get_setting("OMNIROUTE_MODEL", "default")

    chain: list[tuple[str, str]] = list(getattr(settings, "IA_FALLBACK_CHAIN", []))
    if omni_base and ("omniroute", omni_model) not in chain:
        chain.insert(0, ("omniroute", omni_model))

    if not model:
        return chain
    filtered = [(p, m) for (p, m) in chain if m == model or p == "omniroute"]
    if not filtered:
        return [("omniroute", omni_model)] if omni_base else []
    return filtered


def enabled_providers() -> list[str]:
    from core.system_config import get_setting

    providers = list(settings.IA_PROVIDERS)
    if get_setting("OMNIROUTE_BASE_URL") and "omniroute" not in providers:
        providers.insert(0, "omniroute")
    return providers
