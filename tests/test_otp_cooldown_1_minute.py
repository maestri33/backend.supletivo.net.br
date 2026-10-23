"""Teste da regra de cooldown de 1 minuto (60 segundos) para solicitação de OTP.

Garante que:
1. Primeira solicitação de OTP envia normalmente (otp_sent=True).
2. Solicitação subsequente antes de 1 minuto (60s) é bloqueada com indicação de espera (otp_wait > 0 e <= 60).
3. Após transcorrido 1 minuto (60s), a solicitação de OTP é novamente permitida.
"""

from datetime import timedelta
import pytest
from django.conf import settings
from django.utils import timezone

from users.auth import service as auth_service
from users.auth.models import User
from users.auth.otp.models import OtpRateLimit
from users.auth.otp import service as otp_service
from users.profiles.models import Profile

pytestmark = pytest.mark.django_db


def test_otp_rate_limit_cooldown_exatamente_1_minuto(monkeypatch):
    """Verifica que o cooldown configurado é de 60 segundos (1 minuto) e bloqueia reenvios imediatos."""
    assert settings.OTP_RATELIMIT_WINDOW_S == 60, "OTP_RATELIMIT_WINDOW_S deve ser 60 segundos (1 minuto)"

    user = User.objects.create_user()
    Profile.objects.create(user=user, phone="43996648750", cpf="09126367939")

    # 1. Primeiro envio: deve passar e registrar rate-limit
    res1 = auth_service._send_or_wait(user)
    assert res1["otp_sent"] is True
    assert res1["otp_wait"] is None

    # Verifica registro em OtpRateLimit
    rl = OtpRateLimit.objects.get(user=user)
    assert rl.hourly_count == 1

    # 2. Reenvio imediato (< 60s): deve ser bloqueado com otp_wait entre 1 e 60
    res2 = auth_service._send_or_wait(user)
    assert res2["otp_sent"] is False
    assert res2["otp_wait"] is not None
    assert 1 <= res2["otp_wait"] <= 60

    # 3. Simula avanço de tempo de 30 segundos: ainda deve estar bloqueado com ~30s restantes
    rl.last_created_at = timezone.now() - timedelta(seconds=30)
    rl.save(update_fields=["last_created_at"])

    res3 = auth_service._send_or_wait(user)
    assert res3["otp_sent"] is False
    assert 25 <= res3["otp_wait"] <= 31

    # 4. Simula avanço de tempo de 61 segundos (> 1 minuto): deve permitir envio novamente
    rl.last_created_at = timezone.now() - timedelta(seconds=61)
    rl.save(update_fields=["last_created_at"])

    res4 = auth_service._send_or_wait(user)
    assert res4["otp_sent"] is True
    assert res4["otp_wait"] is None


def test_api_check_reenvio_retorna_otp_wait_1_minuto(client):
    """Pela API pública /api/v1/clients/auth/check: segundo pedido dentro de 1 minuto retorna otp_wait."""
    phone = "43996648750"
    user = User.objects.create_user()
    Profile.objects.create(user=user, phone=phone, cpf="09126367939")

    # 1º request
    resp1 = client.post(
        "/api/v1/clients/auth/check",
        {"phone": phone, "auto_capture": False},
        content_type="application/json",
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["found"] is True
    assert data1["otp_sent"] is True
    assert data1["otp_wait"] is None

    # 2º request imediato
    resp2 = client.post(
        "/api/v1/clients/auth/check",
        {"phone": phone, "auto_capture": False},
        content_type="application/json",
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["found"] is True
    assert data2["otp_sent"] is False
    assert data2["otp_wait"] is not None
    assert 1 <= data2["otp_wait"] <= 60
