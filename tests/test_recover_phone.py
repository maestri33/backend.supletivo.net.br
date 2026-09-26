import datetime
import pytest
from django.conf import settings
from django.test import Client

from users.auth.models import User
from users.auth.otp.models import OtpCode
from users.profiles import interface as profiles
from users.profiles.models import Profile


@pytest.mark.django_db
def test_recover_phone_birth_date_success(monkeypatch):
    """Recuperação de telefone via data de nascimento válida atualiza o telefone e incrementa token_version."""
    notified_messages = []
    monkeypatch.setattr(
        "notify.interface.send.send",
        lambda **kwargs: notified_messages.append(kwargs) or "00000000-0000-0000-0000-000000000001",
    )

    user = User.objects.create(token_version=0)
    profile = profiles.create(
        user=user,
        phone="5543996648750",
        cpf="11144477735",
        email="titular@exemplo.com",
    )
    profile.birth_date = datetime.date(1995, 8, 22)
    profile.save(update_fields=["birth_date"])

    client = Client()
    payload = {
        "cpf": "11144477735",
        "new_phone": "43988889999",
        "birth_date": "22/08/1995",
        "method": "birth_date",
    }

    res = client.post(
        "/api/v1/clients/auth/recover-phone",
        data=payload,
        content_type="application/json",
    )

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["status"] == "COMPLETED"
    assert data["requires_challenge"] is False
    assert data["protocol"].startswith("SEC-REC-")
    assert "9999" in data["masked_new_phone"]

    # Verifica atualização no banco
    profile.refresh_from_db()
    assert profile.phone == "5543988889999"

    # Verifica que o token_version foi incrementado para invalidar sessões ativas
    user.refresh_from_db()
    assert user.token_version == 1

    # Verifica notificações de segurança disparadas
    assert len(notified_messages) >= 1
    assert any(m.get("phone") == "5543996648750" for m in notified_messages)


@pytest.mark.django_db
def test_recover_phone_email_challenge_flow(monkeypatch):
    """Fluxo em 2 etapas: primeiro despacha desafio de e-mail, depois valida com OTP e conclui a troca."""
    notified_messages = []
    monkeypatch.setattr(
        "notify.interface.send.send",
        lambda **kwargs: notified_messages.append(kwargs) or "11111111-1111-1111-1111-111111111111",
    )

    user = User.objects.create(token_version=0)
    profile = profiles.create(
        user=user,
        phone="5543996648750",
        cpf="11144477735",
        email="seguranca@exemplo.com",
    )

    client = Client()

    # Etapa 1: Solicitação inicial sem OTP ou data de nascimento -> CHALLENGE_REQUIRED
    res1 = client.post(
        "/api/v1/clients/auth/recover-phone",
        data={
            "cpf": "111.444.777-35",
            "new_phone": "43977776666",
            "method": "email",
        },
        content_type="application/json",
    )

    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["success"] is True
    assert data1["status"] == "CHALLENGE_REQUIRED"
    assert data1["requires_challenge"] is True
    assert data1["masked_email"] is not None
    assert "seguranca@exemplo.com" not in data1["masked_email"]  # deve ser mascarado

    # Telefone AINDA não deve ter mudado
    profile.refresh_from_db()
    assert profile.phone == "5543996648750"

    # Código OTP gerado para teste
    test_otp = getattr(settings, "TEST_MODE_OTP_CODE", "123456")

    # Etapa 2: Submissão com o OTP correto -> COMPLETED
    res2 = client.post(
        "/api/v1/clients/auth/recover-phone",
        data={
            "cpf": "111.444.777-35",
            "new_phone": "43977776666",
            "otp": test_otp,
            "method": "email",
        },
        content_type="application/json",
    )

    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["success"] is True
    assert data2["status"] == "COMPLETED"
    assert data2["requires_challenge"] is False

    # Agora sim o telefone foi atualizado
    profile.refresh_from_db()
    assert profile.phone == "5543977776666"


@pytest.mark.django_db
def test_recover_phone_birth_date_mismatch_fails():
    """Data de nascimento incorreta rejeita com 403 IDENTITY_VERIFICATION_FAILED."""
    user = User.objects.create()
    profile = profiles.create(
        user=user,
        phone="5543996648750",
        cpf="11144477735",
        email="titular@exemplo.com",
    )
    profile.birth_date = datetime.date(1990, 1, 1)
    profile.save(update_fields=["birth_date"])

    client = Client()
    res = client.post(
        "/api/v1/clients/auth/recover-phone",
        data={
            "cpf": "11144477735",
            "new_phone": "43988889999",
            "birth_date": "15/12/1995",
        },
        content_type="application/json",
    )

    assert res.status_code == 403
    assert res.json()["code"] == "IDENTITY_VERIFICATION_FAILED"


@pytest.mark.django_db
def test_recover_phone_cpf_not_found():
    """CPF inexistente retorna 404 CPF_NOT_FOUND."""
    client = Client()
    res = client.post(
        "/api/v1/clients/auth/recover-phone",
        data={
            "cpf": "11144477735",
            "new_phone": "43988889999",
        },
        content_type="application/json",
    )

    assert res.status_code == 404
    assert res.json()["code"] == "CPF_NOT_FOUND"


@pytest.mark.django_db
def test_recover_phone_conflict_with_another_user():
    """Novo telefone já utilizado por outro usuário retorna 409 PHONE_CONFLICT."""
    user1 = User.objects.create()
    profiles.create(user=user1, phone="5543996648750", cpf="11144477735")

    user2 = User.objects.create()
    profiles.create(user=user2, phone="5543988889999", cpf="52998224725")

    client = Client()
    res = client.post(
        "/api/v1/clients/auth/recover-phone",
        data={
            "cpf": "11144477735",
            "new_phone": "43988889999",  # colide com user2
            "birth_date": "01/01/1990",
        },
        content_type="application/json",
    )

    assert res.status_code == 409
    assert res.json()["code"] == "PHONE_CONFLICT"


@pytest.mark.django_db
def test_collaborator_recover_phone_endpoint():
    """Rota em /api/v1/collaborators/auth/recover-phone funciona perfeitamente para promotores."""
    user = User.objects.create()
    profile = profiles.create(
        user=user,
        phone="5543996648750",
        cpf="11144477735",
    )
    profile.birth_date = datetime.date(1988, 3, 10)
    profile.save(update_fields=["birth_date"])

    client = Client()
    res = client.post(
        "/api/v1/collaborators/auth/recover-phone",
        data={
            "cpf": "11144477735",
            "new_phone": "43991112222",
            "birth_date": "1988-03-10",
        },
        content_type="application/json",
    )

    assert res.status_code == 200
    assert res.json()["success"] is True
    profile.refresh_from_db()
    assert profile.phone == "5543991112222"
