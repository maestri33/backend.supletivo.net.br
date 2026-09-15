import pytest
from django.test import Client
from users.auth.models import User
from users.profiles import interface as profiles
from users.roles.candidate.models import Candidate
from users.roles import interface as roles
from users.address.models import Address
from hub.models import Hub


@pytest.mark.django_db
def test_collaborator_check_auto_captures_new_candidate(monkeypatch):
    """Quando o número não existe e o WhatsApp é confirmado, check cria o Candidate e envia OTP."""
    addr = Address.objects.create(zipcode="86010000", street="Rua Teste", number="100", neighborhood="Centro", city="Londrina", state="PR")
    hub = Hub.objects.create(address=addr, brand="standard", is_default=True)
    
    # Mock whatsapp confirmed
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    
    client = Client()
    phone = "43996648750"
    
    res = client.post(
        "/api/v1/collaborators/auth/check",
        data={"phone": phone, "send_otp": True},
        content_type="application/json",
    )
    
    assert res.status_code == 200
    data = res.json()
    assert data["found"] is False
    assert data["created"] is True
    assert data["roles"] == ["candidate"]
    assert data["external_id"] is not None
    assert data["otp_sent"] is True
    
    # Verifica que usuário e candidato foram criados no banco
    user = User.objects.get(external_id=data["external_id"])
    prof = profiles.get(user)
    assert prof.phone == "5543996648750"
    assert "candidate" in roles.active_roles(user)
    
    candidate = Candidate.objects.get(user=user)
    assert candidate.hub == hub
    assert candidate.status == Candidate.Status.STARTED


@pytest.mark.django_db
def test_collaborator_check_existing_user_does_not_duplicate():
    """Quando o usuário já existe, check apenas devolve dados e dispara OTP sem duplicar."""
    addr = Address.objects.create(zipcode="86010000", street="Rua Teste", number="100", neighborhood="Centro", city="Londrina", state="PR")
    hub = Hub.objects.create(address=addr, brand="standard", is_default=True)
    phone = "43996648750"
    
    user = User.objects.create()
    profiles.create(user=user, phone="5543996648750", cpf="11144477735")
    roles.assign(user, "candidate")
    
    client = Client()
    res = client.post(
        "/api/v1/collaborators/auth/check",
        data={"phone": phone, "send_otp": True},
        content_type="application/json",
    )
    
    assert res.status_code == 200
    data = res.json()
    assert data["found"] is True
    assert data["created"] is False
    assert data["external_id"] == str(user.external_id)


