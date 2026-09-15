"""Testes de integração do fluxo de Primeira Inicialização (Bootstrap) e Hard-Lock."""

import pytest
from django.test import Client
from users.auth.models import User
from core.models import PlatformSetting


@pytest.mark.django_db
def test_bootstrap_full_lifecycle():
    client = Client()

    # 1. Garante que o banco está sem superusuários (estado virgem)
    User.objects.filter(is_superuser=True).delete()
    assert User.objects.filter(is_superuser=True).count() == 0

    # 2. Testa o probe público
    res = client.get("/api/v1/staff/bootstrap/status")
    assert res.status_code == 200
    data = res.json()
    assert data["bootstrapped"] is False
    assert data["setup_required"] is True

    # 3. Executa a primeira inicialização (Bootstrap)
    payload = {
        "boss": {
            "name": "Carlos Master Boss",
            "phone": "11988887777",
            "cpf": "11144477735",
            "email": "boss@v7m.org",
            "pix_key": "boss@v7m.org",
            "default_brand": "polo-matriz",
        },
        "pricing": {
            "price_pix": "97",
            "price_card_cents": 9700,
            "promo_price_pix": "77",
            "promo_price_card_cents": 7700,
            "promoter_study_unlock_threshold": 3,
            "promoter_study_complete_threshold": 10,
            "promoter_price_pix": "47",
            "promoter_price_card_cents": 4700,
            "card_installments": 12,
            "description": "Matrícula V7M Oficial",
        },
        "commissions": {
            "commission_direct": "35",
            "commission_bonus_flat": "50",
            "commission_bonus_threshold": 5,
            "commission_coordinator": "10",
            "commission_closing_weekday": 4,
            "commission_closing_hour": 18,
        },
        "integrations": {
            "ASAAS_API_KEY": "test_asaas_secret_key",
        },
    }

    res_init = client.post(
        "/api/v1/staff/bootstrap/init",
        data=payload,
        content_type="application/json",
    )
    assert res_init.status_code == 200, res_init.content.decode()
    init_data = res_init.json()

    assert init_data["success"] is True
    assert "access_token" in init_data
    assert "refresh_token" in init_data
    token = init_data["access_token"]
    assert len(token) > 20

    # 4. Verifica no banco real se o superusuário, profile e settings foram persistidos
    boss = User.objects.filter(is_superuser=True).first()
    assert boss is not None
    assert str(boss.external_id) == init_data["user_external_id"]
    assert boss.profile.name == "Carlos Master Boss"
    assert boss.profile.phone == "5511988887777" or boss.profile.phone == "11988887777" or "988887777" in boss.profile.phone

    # 5. Verifica se as configurações foram salvas em PlatformSetting
    assert PlatformSetting.objects.filter(key="ENROLLMENT_PRICE_PIX", value="97").exists()
    assert PlatformSetting.objects.filter(key="ENROLLMENT_PROMO_PRICE_PIX", value="77").exists()
    assert PlatformSetting.objects.filter(key="PROMOTER_STUDY_UNLOCK_THRESHOLD", value="3").exists()
    assert PlatformSetting.objects.filter(key="PROMOTER_STUDY_COMPLETE_THRESHOLD", value="10").exists()
    assert PlatformSetting.objects.filter(key="COMMISSION_DIRECT", value="35").exists()
    assert PlatformSetting.objects.filter(key="DEFAULT_HUB_BRAND", value="polo-matriz").exists()

    # 6. Faz uma requisição autenticada usando o token emitido
    auth_header = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    res_setup = client.get("/api/v1/staff/config/setup", **auth_header)
    assert res_setup.status_code == 200
    setup_data = res_setup.json()
    assert setup_data["boss"]["name"] == "Carlos Master Boss"
    assert setup_data["pricing"]["price_pix"] == "97"
    assert setup_data["pricing"]["promo_price_pix"] == "77"
    assert setup_data["pricing"]["promoter_study_unlock_threshold"] == 3
    assert setup_data["pricing"]["promoter_study_complete_threshold"] == 10
    assert setup_data["commissions"]["commission_direct"] == "35"

    # 7. Verifica que o probe agora retorna bootstrapped = True
    res_status_after = client.get("/api/v1/staff/bootstrap/status")
    assert res_status_after.status_code == 200
    assert res_status_after.json()["bootstrapped"] is True
    assert res_status_after.json()["setup_required"] is False

    # 8. HARD-LOCK: Tenta rodar o init de novo e valida que é barrado com 403 ALREADY_BOOTSTRAPPED
    res_hacker = client.post(
        "/api/v1/staff/bootstrap/init",
        data={"boss": {"name": "Invasor", "phone": "11988887777", "cpf": "11144477735"}},
        content_type="application/json",
    )
    assert res_hacker.status_code == 403
    assert res_hacker.json()["code"] == "ALREADY_BOOTSTRAPPED"


@pytest.mark.django_db
def test_bootstrap_boss_cpf_and_phone_validation():
    client = Client()
    User.objects.filter(is_superuser=True).delete()

    # 1. CPF Inválido (dígitos verificadores errados)
    res_bad_cpf = client.post(
        "/api/v1/staff/bootstrap/init",
        data={
            "boss": {
                "name": "Boss Test",
                "cpf": "12345678900",
                "phone": "11988887777",
            }
        },
        content_type="application/json",
    )
    assert res_bad_cpf.status_code == 422
    assert "CPF inválido" in str(res_bad_cpf.json())

    # 2. Celular Inválido (número não existe/malformado para o padrão BR)
    res_bad_phone = client.post(
        "/api/v1/staff/bootstrap/init",
        data={
            "boss": {
                "name": "Boss Test",
                "cpf": "52998224725",
                "phone": "12345",
            }
        },
        content_type="application/json",
    )
    assert res_bad_phone.status_code == 422
    assert "Celular/Telefone inválido" in str(res_bad_phone.json())
