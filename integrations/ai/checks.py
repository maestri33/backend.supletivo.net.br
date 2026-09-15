"""System check do app ia — avisa no boot quando a config de IA está incompleta.

Roda em todo runserver/manage (framework de checks do Django), então fica "printando" vermelho até o
.env ser preenchido. Padrão pedido pelo Victor (igual asaas, CONVENTION §8): integração não sobe
silenciosa sem credencial real.

- `ai.E001` (Error): nenhum provider habilitado com base_url+api_key → o engine não fala com IA.
- `ai.E002` (Error): IA_FALLBACK_CHAIN vazia → não há o que chamar.
- `ai.E003` (Error): a cadeia referencia provider sem credencial no .env.
Os E* TRAVAM o manage.py (padrão asaas: o núcleo LLM não sobe sem credencial real).

As modalidades de mídia são opcionais: Gemini (STT) e Google Vision (OCR).
"""

from django.conf import settings
from django.core.checks import Error, Warning


def check_ia_config(app_configs, **kwargs):
    errors = []
    providers = getattr(settings, "IA_PROVIDERS", {})
    chain = getattr(settings, "IA_FALLBACK_CHAIN", [])

    if not providers:
        errors.append(
            Error(
                "Nenhum provider de IA configurado — o app ia não consegue falar com nenhuma IA.",
                hint="No .env: IA_PROVIDERS=deepseek,... e, p/ cada um, IA_<NAME>_BASE_URL + "
                "IA_<NAME>_API_KEY.",
                id="ai.E001",
            )
        )
    if not chain:
        errors.append(
            Error(
                "IA_FALLBACK_CHAIN vazia — sem cadeia (provider:model) não há o que chamar.",
                hint="No .env: IA_FALLBACK_CHAIN=deepseek:deepseek-v4-pro,dashscope:qwen3.7-max,...",
                id="ai.E002",
            )
        )
    missing = sorted({p for (p, _m) in chain if p not in providers})
    if missing:
        errors.append(
            Error(
                f"IA_FALLBACK_CHAIN referencia provider(s) sem base_url/api_key no .env: {missing}.",
                hint="Adicione IA_<NAME>_BASE_URL + IA_<NAME>_API_KEY ou tire da cadeia.",
                id="ai.E003",
            )
        )

    # Modalidades de mídia — opcionais: avisam (não travam) se a key faltar.
    for key_attr, wid, nome in [
        ("GEMINI_API_KEY", "ai.W001", "Gemini (STT)"),
        ("GOOGLE_VISION_API_KEY", "ai.W003", "Google Vision (OCR)"),
    ]:
        if not getattr(settings, key_attr, ""):
            errors.append(
                Warning(
                    f"{key_attr} ausente — a modalidade {nome} fica indisponível (as demais funcionam).",
                    hint=f"Opcional: cole {key_attr}=... no .env quando for usar.",
                    id=wid,
                )
            )
    return errors
