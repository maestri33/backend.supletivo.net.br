"""Testes de validação da infraestrutura, startup seed, PIX no DICT, auto-teste OTP e endpoints de schedules (#69)."""

import io
import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client, override_settings

from core import system_config
from core.models import PlatformSetting
from integrations.bank.asaas.models import PixKey
from users.auth.jwt import service as jwt_service
from users.auth.models import User
from users.profiles.models import Profile
from users.roles.promoter import service as promoter_iface


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def enable_test_external_adapters(settings):
    settings.TEST_EXTERNAL_ADAPTERS = True


def _auth_superuser_token() -> str:
    user = User.objects.filter(is_superuser=True, is_active=True).first()
    if not user:
        user = User.objects.create_superuser(password="superpass123")
    tokens = jwt_service.issue(str(user.external_id), ["staff", "promoter", "coordinator"])
    return tokens["access_token"]


def test_seed_defaults_registers_pix_in_dict_and_validates():
    """Valida que seed_defaults grava DEFAULT_STAFF_PIX e cria registro em PixKey (asaas_pixkey)."""
    system_config.set_setting("DEFAULT_STAFF_CPF", "09126367939")
    system_config.set_setting("DEFAULT_STAFF_PHONE", "5543996648750")
    system_config.set_setting("DEFAULT_STAFF_PIX", "09126367939")
    system_config.set_setting("DEFAULT_STAFF_NAME", "Victor Maestri")

    out = io.StringIO()
    call_command("seed_defaults", stdout=out)
    output = out.getvalue()
    assert "staff external_id=" in output

    profile = Profile.objects.filter(cpf="09126367939").first()
    assert profile is not None
    assert profile.pix_key == "09126367939"
    assert profile.pix_key_type == "CPF"

    # Confirma que PixKey foi criada/validada
    pix_record = PixKey.objects.filter(key="09126367939").first()
    assert pix_record is not None
    assert pix_record.key_type == "CPF"
    assert pix_record.holder_document == "09126367939"

    # Confirma que promoter_me enxerga pix_validated = True
    promoter = promoter_iface.get_for_user(profile.user)
    assert promoter is not None
    me_data = promoter_iface.to_dict(promoter)
    assert me_data["pix_key"] == "09126367939"
    assert me_data["pix_validated"] is True


def test_test_principal_user_apis_command():
    """Valida execução do comando test_principal_user_apis com flags de controle."""
    system_config.set_setting("DEFAULT_STAFF_CPF", "09126367939")
    system_config.set_setting("DEFAULT_STAFF_PHONE", "5543996648750")
    system_config.set_setting("DEFAULT_STAFF_PIX", "09126367939")

    # Garante que seed_defaults rodou
    call_command("seed_defaults")

    out = io.StringIO()
    call_command("test_principal_user_apis", "--skip-payout", "--skip-otp", stdout=out)
    res = out.getvalue()
    assert "INICIANDO AUTO-TESTE DAS APIS DO USUÁRIO PRINCIPAL" in res
    assert "DIAGNÓSTICO E AUTO-TESTE FINALIZADOS COM SUCESSO" in res
    assert "Chave PIX Validada no DICT" in res


def test_commissions_config_via_setup_endpoints(db):
    """Valida leitura e atualização das configurações de comissão via GET e PUT /config/setup."""
    from core.system_config import clear_settings_cache
    PlatformSetting.objects.filter(
        key__in=[
            "COMMISSION_DIRECT",
            "COMMISSION_BONUS_FLAT",
            "COMMISSION_BONUS_THRESHOLD",
            "COMMISSION_COORDINATOR",
            "COMMISSION_CLOSING_WEEKDAY",
            "COMMISSION_CLOSING_HOUR",
        ]
    ).delete()
    clear_settings_cache()

    client = Client()
    token = _auth_superuser_token()
    auth_header = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    # 1. GET /config/setup traz comissões padrão de produção alvo (50, 200, 25, threshold 3)
    res_get = client.get("/api/v1/staff/config/setup", **auth_header)
    assert res_get.status_code == 200
    data = res_get.json()
    assert "commissions" in data
    assert data["commissions"]["commission_direct"] == "1"
    assert data["commissions"]["commission_bonus_flat"] == "5"
    assert data["commissions"]["commission_coordinator"] == "1"
    assert data["commissions"]["commission_bonus_threshold"] == 3

    # 2. PUT /config/setup altera os valores em PlatformSetting
    update_payload = {
        "commissions": {
            "commission_direct": "60",
            "commission_bonus_flat": "250",
            "commission_bonus_threshold": 4,
            "commission_coordinator": "30",
            "commission_closing_weekday": 4,
            "commission_closing_hour": 19,
        }
    }
    res_put = client.put(
        "/api/v1/staff/config/setup",
        data=update_payload,
        content_type="application/json",
        **auth_header,
    )
    assert res_put.status_code == 200
    put_data = res_put.json()
    assert put_data["commissions"]["commission_direct"] == "60"
    assert put_data["commissions"]["commission_bonus_flat"] == "250"
    assert put_data["commissions"]["commission_bonus_threshold"] == 4
    assert put_data["commissions"]["commission_coordinator"] == "30"

    # Confirma no banco real
    assert PlatformSetting.objects.filter(key="COMMISSION_DIRECT", value="60").exists()
    assert PlatformSetting.objects.filter(key="COMMISSION_BONUS_FLAT", value="250").exists()
    assert PlatformSetting.objects.filter(key="COMMISSION_BONUS_THRESHOLD", value="4").exists()
    assert PlatformSetting.objects.filter(key="COMMISSION_COORDINATOR", value="30").exists()


def test_finance_schedules_list_and_run_endpoints():
    """Valida listagem e disparo manual dos schedules financeiros."""
    client = Client()
    token = _auth_superuser_token()
    auth_header = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    # 1. GET /finance/schedules
    res_list = client.get("/api/v1/staff/finance/schedules", **auth_header)
    assert res_list.status_code == 200
    schedules = res_list.json()
    assert len(schedules) >= 2
    names = [s["name"] for s in schedules]
    assert "finance.weekly_closing" in names
    assert "finance.process_payouts" in names

    # 2. POST /finance/schedules/finance.weekly_closing/run
    res_run_closing = client.post(
        "/api/v1/staff/finance/schedules/finance.weekly_closing/run",
        **auth_header,
    )
    assert res_run_closing.status_code == 200
    run_data = res_run_closing.json()
    assert run_data["success"] is True
    assert run_data["schedule_name"] == "finance.weekly_closing"
    assert run_data["func"] == "finance.tasks.weekly_closing"
    assert isinstance(run_data["result"], dict)

    # 3. POST /finance/schedules/finance.process_payouts/run
    res_run_payouts = client.post(
        "/api/v1/staff/finance/schedules/finance.process_payouts/run",
        **auth_header,
    )
    assert res_run_payouts.status_code == 200
    payout_data = res_run_payouts.json()
    assert payout_data["success"] is True
    assert payout_data["schedule_name"] == "finance.process_payouts"
    assert payout_data["func"] == "finance.tasks.process_payouts"
    assert isinstance(payout_data["result"], dict)
