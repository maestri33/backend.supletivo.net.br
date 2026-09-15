"""Honestidade do OTP: o sistema NÃO pode fingir que mandou o código quando não mandou.

- CHECK (fluxo interativo, o usuário ESPERA o código): sem telefone → OTP_NOT_SENT, não sucesso mudo.
- REGISTER (best-effort, não pode derrubar a criação): OTP que não saiu não vira 500 — o user é
  criado e o retorno expõe `otp_sent=false` honesto.
"""

import pytest

from users.auth import service as auth_service
from users.exceptions import IntegrationError

pytestmark = pytest.mark.django_db

# CPF válido (dígitos verificadores corretos) para o register em TEST_MODE.
_VALID_CPF = "11144477735"


def _user_without_phone():
    """User + Profile com telefone vazio → generate_and_send cai em no_phone (FAILED)."""
    from users.auth.models import User
    from users.profiles.models import Profile

    user = User.objects.create_user()
    Profile.objects.create(user=user, phone="")
    return user


def test_check_sem_telefone_sinaliza_otp_not_sent():
    """CHECK interativo de user CONHECIDO sem telefone → levanta OTP_NOT_SENT (não finge sucesso)."""
    user = _user_without_phone()
    with pytest.raises(IntegrationError) as exc:
        auth_service.check(external_id=str(user.external_id), send_otp=True)
    assert exc.value.code == "OTP_NOT_SENT"


def test_check_sem_telefone_http_502(client):
    """Mesma coisa pela view: /auth/check → 502 + code OTP_NOT_SENT (não 200 mentindo otp_sent)."""
    user = _user_without_phone()
    resp = client.post(
        "/api/v1/clients/auth/check",
        {"external_id": str(user.external_id), "send_otp": True},
        content_type="application/json",
    )
    assert resp.status_code == 502
    assert resp.json()["code"] == "OTP_NOT_SENT"


def test_register_otp_nao_enviado_nao_derruba_criacao(monkeypatch):
    """REGISTER best-effort: OTP que não saiu (OTP inativo) NÃO derruba a criação — user existe,
    mas o retorno é honesto: otp_sent=False."""
    from django.conf import settings

    from users.auth.models import User

    monkeypatch.setattr(
        settings, "OTP_ACTIVE", False
    )  # força o OTP a nascer FAILED (inactive)

    reg = auth_service.register(role="lead", phone="11999990002", cpf=_VALID_CPF)

    assert reg["otp_sent"] is False  # honesto: não mente que mandou
    assert User.objects.filter(
        external_id=reg["external_id"]
    ).exists()  # criação intacta


def test_register_otp_enviado_expoe_otp_sent_true(monkeypatch):
    """Caminho feliz: com telefone válido e OTP ativo, register expõe otp_sent=True."""
    from users.auth.models import User

    reg = auth_service.register(role="lead", phone="11999990003", cpf="52998224725")

    assert reg["otp_sent"] is True
    assert User.objects.filter(external_id=reg["external_id"]).exists()
