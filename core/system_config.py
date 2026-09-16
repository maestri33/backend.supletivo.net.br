"""Serviço de Configuração Dinâmica da Plataforma (SystemConfig).

Permite que o Staff / Boss gerencie e sobrescreva preços, regras de comissão,
chaves de integração e parâmetros de bootstrap em tempo de execução via banco
(PlatformSetting), mantendo fallback seguro para os valores de core/settings.py.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
import structlog
from django.conf import settings
from django.db import transaction

from core.models import PlatformSetting

logger = structlog.get_logger()

# Config keys catalog
PRICING_KEYS = {
    "ENROLLMENT_PRICE_PIX": "5",
    "ENROLLMENT_PRICE_CARD_CENTS": "100",
    "ENROLLMENT_PROMO_PRICE_PIX": "5",
    "ENROLLMENT_PROMO_PRICE_CARD_CENTS": "100",
    "ENROLLMENT_ANCHOR_FULL": "1615",
    "PROMOTER_STUDY_UNLOCK_THRESHOLD": "3",
    "PROMOTER_STUDY_COMPLETE_THRESHOLD": "10",
    "ENROLLMENT_PRICE_PROMOTER_PIX": "5",
    "ENROLLMENT_PRICE_PROMOTER_CARD_CENTS": "100",
    "CARD_INSTALLMENTS": "12",
    "ENROLLMENT_DESCRIPTION": "Matrícula Supletivo",
}

COMMISSION_KEYS = {
    "COMMISSION_DIRECT": "1",
    "COMMISSION_BONUS_FLAT": "5",
    "COMMISSION_BONUS_THRESHOLD": 3,
    "COMMISSION_COORDINATOR": "1",
    "COMMISSION_CLOSING_WEEKDAY": "4",
    "COMMISSION_CLOSING_HOUR": "18",
}

INTEGRATION_KEYS = {
    "ASAAS_API_KEY": True,  # is_secret
    "ASAAS_BASE_URL": False,
    "ASAAS_WEBHOOK_SECRET": True,
    "INFINITEPAY_HANDLE": False,
    "INFINITEPAY_BASE_URL": False,
    "NOTIFY_SERVER_URL": False,
    "NOTIFY_API_KEY": True,
    "OMNIROUTE_BASE_URL": False,
    "OMNIROUTE_API_KEY": True,
    "GEMINI_API_KEY": True,
    "MINIMAX_API_KEY": True,
    "GOOGLE_VISION_API_KEY": True,
    "CPFHUB_API_KEY": True,
    "CPFHUB_BASE_URL": False,
    "INFISICAL_BASE_URL": False,
    "INFISICAL_PROJECT_ID": False,
    "INFISICAL_ENVIRONMENT": False,
    "INFISICAL_UNIVERSAL_AUTH_CLIENT_ID": False,
    "INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET": True,
    "INFISICAL_TOKEN": True,
    "EXTERNAL_URL": False,
    "FRONTEND_URL": False,
    "ASTRO_REBUILD_WEBHOOK_URL": False,
}

BOSS_KEYS = {
    "DEFAULT_STAFF_NAME": "Victor",
    "DEFAULT_STAFF_CPF": "",
    "DEFAULT_STAFF_PHONE": "",
    "DEFAULT_STAFF_EMAIL": "",
    "DEFAULT_STAFF_PIX": "",
    "DEFAULT_HUB_BRAND": "standard",
}


import time

_SETTINGS_CACHE: dict[str, str] = {}
_CACHE_INITIALIZED: bool = False
_CACHE_EXPIRES_AT: float = 0.0
_CACHE_TTL_SECONDS: float = 60.0


def load_all_settings_into_cache() -> None:
    """Carrega todas as configurações do PlatformSetting na memória do processo com TTL."""
    global _CACHE_INITIALIZED, _CACHE_EXPIRES_AT
    try:
        fresh: dict[str, str] = {}
        for row in PlatformSetting.objects.all():
            if row.key and row.value is not None:
                fresh[row.key] = row.value
        _SETTINGS_CACHE.clear()
        _SETTINGS_CACHE.update(fresh)
        _CACHE_INITIALIZED = True
        _CACHE_EXPIRES_AT = time.monotonic() + _CACHE_TTL_SECONDS
    except Exception:
        pass


def clear_settings_cache() -> None:
    """Limpa o cache em memória das configurações da plataforma."""
    global _CACHE_INITIALIZED, _CACHE_EXPIRES_AT
    _SETTINGS_CACHE.clear()
    _CACHE_INITIALIZED = False
    _CACHE_EXPIRES_AT = 0.0


def get_setting(key: str, default: Any = None) -> Any:
    """Busca o valor da configuração no banco (PlatformSetting) ou faz fallback para settings."""
    global _CACHE_INITIALIZED, _CACHE_EXPIRES_AT
    now = time.monotonic()
    if not _CACHE_INITIALIZED or now >= _CACHE_EXPIRES_AT:
        load_all_settings_into_cache()
    # Fast path: check in-memory cache first
    if key in _SETTINGS_CACHE and _SETTINGS_CACHE[key] != "":
        return _SETTINGS_CACHE[key]
    try:
        row = PlatformSetting.objects.filter(key=key).first()
        if row is not None and row.value is not None and row.value != "":
            _SETTINGS_CACHE[key] = row.value
            return row.value
    except Exception:
        pass
    return _SETTINGS_CACHE.get(key) or getattr(settings, key, default)


def set_setting(key: str, value: Any, description: str = "", is_secret: bool = False) -> PlatformSetting:
    """Grava ou atualiza uma configuração dinâmica."""
    val_str = str(value) if value is not None else ""
    _SETTINGS_CACHE[key] = val_str
    row, _ = PlatformSetting.objects.update_or_create(
        key=key,
        defaults={
            "value": val_str,
            "description": description,
            "is_secret": is_secret,
        },
    )
    return row


def mask_secret(value: str | None) -> str | None:
    """Mascara chaves de segredo para visualização segura no painel."""
    if not value:
        return ""
    if len(value) <= 8:
        return "••••••••"
    return f"{value[:4]}••••••••{value[-4:]}"


def get_all_platform_config() -> dict:
    """Monta o payload completo de configuração e estado do sistema."""
    # 1. Boss Info
    boss_cpf = get_setting("DEFAULT_STAFF_CPF", getattr(settings, "DEFAULT_STAFF_CPF", ""))
    boss_phone = get_setting("DEFAULT_STAFF_PHONE", getattr(settings, "DEFAULT_STAFF_PHONE", ""))
    boss_name = get_setting("DEFAULT_STAFF_NAME", getattr(settings, "DEFAULT_STAFF_NAME", "Victor"))
    boss_email = get_setting("DEFAULT_STAFF_EMAIL", getattr(settings, "DEFAULT_STAFF_EMAIL", ""))
    boss_pix = get_setting("DEFAULT_STAFF_PIX", getattr(settings, "DEFAULT_STAFF_PIX", ""))
    default_brand = get_setting("DEFAULT_HUB_BRAND", getattr(settings, "DEFAULT_HUB_BRAND", "standard"))

    # Verifica se o boss já existe no banco
    from users.profiles.models import Profile
    existing_boss = Profile.objects.filter(user__is_superuser=True).first()
    boss_configured = existing_boss is not None

    if existing_boss:
        boss_cpf = boss_cpf or existing_boss.cpf or ""
        boss_phone = boss_phone or existing_boss.phone or ""
        boss_name = boss_name or existing_boss.name or ""
        boss_email = boss_email or existing_boss.email or ""
        boss_pix = boss_pix or existing_boss.pix_key or ""

    # 2. Preços
    price_pix = str(get_setting("ENROLLMENT_PRICE_PIX", getattr(settings, "ENROLLMENT_PRICE_PIX", "5")))
    price_card_cents = int(get_setting("ENROLLMENT_PRICE_CARD_CENTS", getattr(settings, "ENROLLMENT_PRICE_CARD_CENTS", 100)))
    promo_price_pix = str(get_setting("ENROLLMENT_PROMO_PRICE_PIX", getattr(settings, "ENROLLMENT_PROMO_PRICE_PIX", price_pix)))
    promo_price_card_cents = int(get_setting("ENROLLMENT_PROMO_PRICE_CARD_CENTS", getattr(settings, "ENROLLMENT_PROMO_PRICE_CARD_CENTS", price_card_cents)))
    promoter_study_unlock_threshold = int(get_setting("PROMOTER_STUDY_UNLOCK_THRESHOLD", getattr(settings, "PROMOTER_STUDY_UNLOCK_THRESHOLD", 3)))
    promoter_study_complete_threshold = int(get_setting("PROMOTER_STUDY_COMPLETE_THRESHOLD", getattr(settings, "PROMOTER_STUDY_COMPLETE_THRESHOLD", 10)))
    promoter_price_pix = str(get_setting("ENROLLMENT_PRICE_PROMOTER_PIX", getattr(settings, "ENROLLMENT_PRICE_PROMOTER_PIX", price_pix)))
    promoter_price_card_cents = int(get_setting("ENROLLMENT_PRICE_PROMOTER_CARD_CENTS", getattr(settings, "ENROLLMENT_PRICE_PROMOTER_CARD_CENTS", price_card_cents)))
    card_installments = int(get_setting("CARD_INSTALLMENTS", 12))
    anchor_full = str(get_setting("ENROLLMENT_ANCHOR_FULL", getattr(settings, "ENROLLMENT_ANCHOR_FULL", "1615")))
    description = str(get_setting("ENROLLMENT_DESCRIPTION", getattr(settings, "ENROLLMENT_DESCRIPTION", "Matrícula Supletivo")))

    # 3. Comissões
    commission_direct = str(get_setting("COMMISSION_DIRECT", getattr(settings, "COMMISSION_DIRECT", "50")))
    commission_bonus_flat = str(get_setting("COMMISSION_BONUS_FLAT", getattr(settings, "COMMISSION_BONUS_FLAT", "200")))
    commission_bonus_threshold = int(get_setting("COMMISSION_BONUS_THRESHOLD", getattr(settings, "COMMISSION_BONUS_THRESHOLD", 3)))
    commission_coordinator = str(get_setting("COMMISSION_COORDINATOR", getattr(settings, "COMMISSION_COORDINATOR", "25")))
    commission_closing_weekday = int(get_setting("COMMISSION_CLOSING_WEEKDAY", getattr(settings, "COMMISSION_CLOSING_WEEKDAY", 4)))
    commission_closing_hour = int(get_setting("COMMISSION_CLOSING_HOUR", getattr(settings, "COMMISSION_CLOSING_HOUR", 18)))

    # 4. Integrações
    integ_values: dict[str, dict] = {}
    for k, is_secret in INTEGRATION_KEYS.items():
        raw = get_setting(k, getattr(settings, k, ""))
        raw_str = str(raw) if raw is not None else ""
        integ_values[k] = {
            "value": mask_secret(raw_str) if is_secret else raw_str,
            "configured": bool(raw_str),
            "is_secret": is_secret,
        }

    return {
        "boss": {
            "name": boss_name,
            "cpf": boss_cpf,
            "phone": boss_phone,
            "email": boss_email,
            "pix_key": boss_pix,
            "default_brand": default_brand,
            "is_configured": boss_configured,
            "external_id": str(existing_boss.user.external_id) if existing_boss else None,
        },
        "pricing": {
            "price_pix": price_pix,
            "price_card_cents": price_card_cents,
            "price_card_reais": f"{(Decimal(price_card_cents) / 100):.2f}",
            "promo_price_pix": promo_price_pix,
            "promo_price_card_cents": promo_price_card_cents,
            "promo_price_card_reais": f"{(Decimal(promo_price_card_cents) / 100):.2f}",
            "promoter_study_unlock_threshold": promoter_study_unlock_threshold,
            "promoter_study_complete_threshold": promoter_study_complete_threshold,
            "promoter_price_pix": promoter_price_pix,
            "promoter_price_card_cents": promoter_price_card_cents,
            "promoter_price_card_reais": f"{(Decimal(promoter_price_card_cents) / 100):.2f}",
            "card_installments": card_installments,
            "anchor_full": anchor_full,
            "description": description,
        },
        "commissions": {
            "commission_direct": commission_direct,
            "commission_bonus_flat": commission_bonus_flat,
            "commission_bonus_threshold": commission_bonus_threshold,
            "commission_coordinator": commission_coordinator,
            "commission_closing_weekday": commission_closing_weekday,
            "commission_closing_hour": commission_closing_hour,
        },
        "integrations": integ_values,
    }


def save_platform_config(payload: dict) -> dict:
    """Atualiza configurações no banco de dados e sincroniza Boss/Hub se informado."""
    with transaction.atomic():
        # Preços
        if "pricing" in payload:
            p = payload["pricing"]
            if "price_pix" in p and p["price_pix"] is not None:
                set_setting("ENROLLMENT_PRICE_PIX", str(p["price_pix"]), "Preço PIX Matrícula")
            if "price_card_cents" in p and p["price_card_cents"] is not None:
                set_setting("ENROLLMENT_PRICE_CARD_CENTS", int(p["price_card_cents"]), "Preço Cartão (centavos)")
            if "promo_price_pix" in p and p["promo_price_pix"] is not None:
                set_setting("ENROLLMENT_PROMO_PRICE_PIX", str(p["promo_price_pix"]), "Preço Promocional PIX")
            if "promo_price_card_cents" in p and p["promo_price_card_cents"] is not None:
                set_setting("ENROLLMENT_PROMO_PRICE_CARD_CENTS", int(p["promo_price_card_cents"]), "Preço Promocional Cartão (centavos)")
            if "promoter_study_unlock_threshold" in p and p["promoter_study_unlock_threshold"] is not None:
                set_setting("PROMOTER_STUDY_UNLOCK_THRESHOLD", int(p["promoter_study_unlock_threshold"]), "Meta de alunos para liberar auto-matrícula")
            if "promoter_study_complete_threshold" in p and p["promoter_study_complete_threshold"] is not None:
                set_setting("PROMOTER_STUDY_COMPLETE_THRESHOLD", int(p["promoter_study_complete_threshold"]), "Meta de alunos para quitação/prova")
            if "promoter_price_pix" in p and p["promoter_price_pix"] is not None:
                set_setting("ENROLLMENT_PRICE_PROMOTER_PIX", str(p["promoter_price_pix"]), "Preço PIX Promotor")
            if "promoter_price_card_cents" in p and p["promoter_price_card_cents"] is not None:
                set_setting("ENROLLMENT_PRICE_PROMOTER_CARD_CENTS", int(p["promoter_price_card_cents"]), "Preço Cartão Promotor (centavos)")
            if "card_installments" in p and p["card_installments"] is not None:
                set_setting("CARD_INSTALLMENTS", int(p["card_installments"]), "Parcelas Cartão")
            if "anchor_full" in p and p["anchor_full"] is not None:
                set_setting("ENROLLMENT_ANCHOR_FULL", str(p["anchor_full"]), "Preço Âncora Riscado (marketing)")
            if "description" in p and p["description"] is not None:
                set_setting("ENROLLMENT_DESCRIPTION", str(p["description"]), "Descrição da cobrança")

        # Comissões
        if "commissions" in payload:
            c = payload["commissions"]
            if "commission_direct" in c and c["commission_direct"] is not None:
                set_setting("COMMISSION_DIRECT", str(c["commission_direct"]), "Comissão direta")
            if "commission_bonus_flat" in c and c["commission_bonus_flat"] is not None:
                set_setting("COMMISSION_BONUS_FLAT", str(c["commission_bonus_flat"]), "Bônus meta")
            if "commission_bonus_threshold" in c and c["commission_bonus_threshold"] is not None:
                set_setting("COMMISSION_BONUS_THRESHOLD", int(c["commission_bonus_threshold"]), "Meta indicações")
            if "commission_coordinator" in c and c["commission_coordinator"] is not None:
                set_setting("COMMISSION_COORDINATOR", str(c["commission_coordinator"]), "Comissão coordenador")
            if "commission_closing_weekday" in c and c["commission_closing_weekday"] is not None:
                set_setting("COMMISSION_CLOSING_WEEKDAY", int(c["commission_closing_weekday"]), "Dia fechamento")
            if "commission_closing_hour" in c and c["commission_closing_hour"] is not None:
                set_setting("COMMISSION_CLOSING_HOUR", int(c["commission_closing_hour"]), "Hora fechamento")

        # Integrações
        if "integrations" in payload:
            for k, val in payload["integrations"].items():
                if k in INTEGRATION_KEYS and val is not None and str(val).strip() != "" and not str(val).startswith("••••"):
                    set_setting(k, str(val).strip(), f"Chave {k}", is_secret=INTEGRATION_KEYS[k])

        # Boss
        if "boss" in payload:
            b = payload["boss"]
            for k, key_name in [
                ("name", "DEFAULT_STAFF_NAME"),
                ("cpf", "DEFAULT_STAFF_CPF"),
                ("phone", "DEFAULT_STAFF_PHONE"),
                ("email", "DEFAULT_STAFF_EMAIL"),
                ("pix_key", "DEFAULT_STAFF_PIX"),
                ("default_brand", "DEFAULT_HUB_BRAND"),
            ]:
                if k in b and b[k] is not None and str(b[k]).strip() != "":
                    set_setting(key_name, str(b[k]).strip(), f"Boss {k}")

            if "password" in b and b["password"] and str(b["password"]).strip() != "":
                set_setting("DEFAULT_STAFF_PASSWORD", str(b["password"]).strip(), "Senha Master do Staff", is_secret=True)

            # Se o Boss já existir, atualiza o Profile e User password
            from users.profiles.models import Profile
            from users.auth import validation as auth_val
            existing_boss = Profile.objects.filter(user__is_superuser=True).first()
            if existing_boss:
                changed = []
                if "name" in b and b["name"] and existing_boss.name != b["name"]:
                    existing_boss.name = b["name"]
                    changed.append("name")
                if "phone" in b and b["phone"]:
                    try:
                        clean_phone = auth_val.validate_phone_strict(b["phone"])
                        if existing_boss.phone != clean_phone:
                            existing_boss.phone = clean_phone
                            changed.append("phone")
                    except Exception:
                        pass
                if "email" in b and b["email"] and existing_boss.email != b["email"]:
                    existing_boss.email = b["email"]
                    changed.append("email")
                if "pix_key" in b and b["pix_key"] and existing_boss.pix_key != b["pix_key"]:
                    existing_boss.pix_key = b["pix_key"]
                    changed.append("pix_key")
                if changed:
                    existing_boss.save(update_fields=[*changed, "updated_at"])

                if "password" in b and b["password"] and str(b["password"]).strip() != "":
                    existing_boss.user.set_password(str(b["password"]).strip())
                    existing_boss.user.save(update_fields=["password"])

    if "pricing" in payload:
        trigger_astro_rebuild(payload.get("pricing"))

    return get_all_platform_config()


def trigger_astro_rebuild(pricing_data: dict | None = None) -> bool:
    """Dispara o rebuild e atualização das páginas e ilhas do Astro quando os preços forem alterados."""
    from core import hooks

    logger.info("astro.rebuild_requested", pricing=pricing_data)
    hooks.dispatch("platform.pricing_updated", pricing=pricing_data)

    webhook_url = get_setting("ASTRO_REBUILD_WEBHOOK_URL", getattr(settings, "ASTRO_REBUILD_WEBHOOK_URL", ""))

    import threading

    def _dispatch_webhook() -> None:
        if not webhook_url:
            return
        import json
        import urllib.request

        try:
            body = json.dumps({
                "event": "pricing_updated",
                "pricing": pricing_data or {},
                "timestamp": __import__("time").time(),
            }).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": "SupletivoBrasil-Backend-SystemConfig"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info("astro.rebuild_webhook_dispatched", url=webhook_url, status=resp.status)
        except Exception as exc:
            logger.warning("astro.rebuild_webhook_failed", url=webhook_url, error=str(exc))

    t = threading.Thread(target=_dispatch_webhook, daemon=True)
    t.start()
    return True
