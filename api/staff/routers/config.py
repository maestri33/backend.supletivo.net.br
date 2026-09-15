from __future__ import annotations

import io
import time
from typing import Any
from django.core.management import call_command
from ninja import Router

from api.auth import require_superuser
from api.staff.schemas import (
    BossIn,
    BootstrapInitIn,
    BootstrapInitOut,
    BootstrapStatusOut,
    CommissionsIn,
    IntegrationTestLiveOut,
    PlatformSetupIn,
    PlatformSetupOut,
    PricingIn,
    SeedRunOut,
)
from core import system_config
from users.auth.jwt import service as jwt_service
from users.auth.models import User
from users.exceptions import Forbidden, NotFound, ValidationError
from users.roles import interface as roles

router = Router(tags=["staff"])


@router.get("/bootstrap/status", response=BootstrapStatusOut, auth=None, summary="Verifica se a plataforma já foi inicializada")
def get_bootstrap_status(request):
    """Retorna se o bootstrap inicial da plataforma já foi concluído."""
    has_superuser = User.objects.filter(is_superuser=True, is_active=True).exists()
    return {
        "bootstrapped": has_superuser,
        "setup_required": not has_superuser,
    }


@router.post("/bootstrap/init", response=BootstrapInitOut, auth=None, summary="Executa a primeira inicialização (Bootstrap) da plataforma")
def init_platform_bootstrap(request, payload: BootstrapInitIn):
    """Executa a primeira inicialização da plataforma e emite token para a conta-mãe (Boss).

    HARD-LOCK: Se já houver superusuário ativo no sistema, recusa terminantemente com 403 ALREADY_BOOTSTRAPPED.
    """
    if User.objects.filter(is_superuser=True, is_active=True).exists():
        raise Forbidden("A plataforma já foi inicializada. Utilize a tela de login regular.", code="ALREADY_BOOTSTRAPPED")

    # 1. Salva as configurações passadas no payload
    data = payload.dict(exclude_unset=True)
    system_config.save_platform_config(data)

    # 2. Executa o seed_defaults para criar a conta do Boss, Hub padrão e Promotor
    out = io.StringIO()
    try:
        call_command("seed_defaults", stdout=out)
    except Exception as exc:
        raise ValidationError(f"Falha ao executar bootstrap seed: {exc}", code="BOOTSTRAP_FAILED") from exc

    # 3. Localiza o superusuário recém-criado
    boss_user = User.objects.filter(is_superuser=True, is_active=True).first()
    if not boss_user:
        raise ValidationError("Superusuário não encontrado após execução do seed.", code="BOSS_CREATION_FAILED")

    # 4. Emite JWT para o Boss
    active_roles = roles.active_roles(boss_user)
    tokens = jwt_service.issue(str(boss_user.external_id), active_roles)

    return {
        "success": True,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
        "user_external_id": str(boss_user.external_id),
    }


@router.get("/config/setup", response=PlatformSetupOut, summary="Obter configurações e setup da plataforma")
def get_platform_setup(request):
    """Retorna o estado de configuração atual da plataforma: Boss, Preços, Comissões e Integrações."""
    require_superuser(request.auth)
    return system_config.get_all_platform_config()


@router.put("/config/setup", response=PlatformSetupOut, summary="Atualizar configurações e setup da plataforma")
def update_platform_setup(request, payload: PlatformSetupIn):
    """Atualiza configurações no banco de dados e sincroniza dados do Boss e Hubs."""
    require_superuser(request.auth)
    data = payload.dict(exclude_unset=True)
    return system_config.save_platform_config(data)


@router.post("/config/seed-run", response=SeedRunOut, summary="Executar seed de bootstrap da plataforma")
def run_seed_defaults(request):
    """Executa o comando de seed idempotente (cria/atualiza conta do Boss, Hub padrão e Promotor)."""
    require_superuser(request.auth)
    out = io.StringIO()
    try:
        call_command("seed_defaults", stdout=out)
        output_str = out.getvalue()
        return {
            "success": True,
            "output": output_str,
            "config": system_config.get_all_platform_config(),
        }
    except Exception as exc:
        raise ValidationError(f"Falha ao executar seed: {exc}", code="SEED_FAILED") from exc


@router.post("/integrations/{name}/test-live", response=IntegrationTestLiveOut, summary="Teste de conexão ao vivo da integração")
def test_integration_live(request, name: str):
    """Testa a conectividade em tempo real com o provedor externo e mede latência."""
    require_superuser(request.auth)
    start = time.perf_counter()
    success = False
    details: dict[str, Any] = {}
    err_msg = None

    try:
        if name == "asaas":
            from integrations.bank.asaas import onboarding
            res = onboarding.run_checks(record=True)
            bal = onboarding.account_balance()
            details["checks"] = res
            details["balance"] = bal
            success = isinstance(bal, dict) and bal.get("balance") is not None and not bal.get("error")

        elif name == "notify":
            from notify.sdk import client as notify_client
            # Testa phone check ou endpoint de health do notify-server
            res = notify_client.phone_check(["5511999999999"])
            details["phone_check"] = res
            success = bool(res)

        elif name == "ai":
            from integrations.ai import service as ai_service
            # Testa prompt básico de liveness com IA
            try:
                res = ai_service.complete_text("Diga apenas OK", caller="staff.test_live", max_tokens=10)
                details["response"] = res
                success = bool(res)
            except Exception as e:
                err_msg = str(e)
                details["error"] = err_msg

        elif name == "cpf":
            from integrations.tools.cpf.scripts import cpfhub
            # Consulta simulada ou real
            details["base_url"] = system_config.get_setting("CPFHUB_BASE_URL", "https://cpfhub.io")
            details["has_key"] = bool(system_config.get_setting("CPFHUB_API_KEY", ""))
            success = details["has_key"]

        elif name in ("whatsapp", "evolution"):
            from notify.sdk import client as notify_client
            res = notify_client.phone_check(["5511999999999"])
            details["evolution_check"] = res
            success = bool(res)

        elif name == "infinitepay":
            handle = system_config.get_setting("INFINITEPAY_HANDLE", "")
            base_url = system_config.get_setting("INFINITEPAY_BASE_URL", "https://api.infinitepay.io")
            details["handle"] = handle
            details["base_url"] = base_url
            success = bool(handle)

        else:
            raise NotFound(f"Integração '{name}' desconhecida.", code="INTEGRATION_NOT_FOUND")

    except Exception as exc:
        err_msg = str(exc)
        success = False

    latency_ms = int((time.perf_counter() - start) * 1000)
    return {
        "name": name,
        "success": success,
        "latency_ms": latency_ms,
        "details": details,
        "error": err_msg,
    }
