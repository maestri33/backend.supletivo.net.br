import pytest
from django.test import Client
from unittest.mock import patch
import uuid

from users.auth.models import User
from users.profiles import interface as profiles
from users.roles.lead.models import Lead, LeadAttribution
from users.address.models import Address
from hub.models import Hub


@pytest.fixture
def client():
    return Client()


@pytest.fixture(autouse=True)
def default_promoter(db):
    coord = User.objects.create_user(external_id=uuid.uuid4(), is_active=True)
    addr = Address.objects.create(city="São Paulo", state="SP")
    Hub.objects.create(address=addr, brand="e2e", coordinator=coord, is_default=True)
    return coord


@pytest.mark.django_db
def test_capture_phone_only_new_lead(client):
    payload = {
        "phone": "11988887777",
    }
    resp = client.post(
        "/api/v1/clients/lead/capture",
        data=payload,
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["found"] is False
    assert data["created"] is True
    assert data["otp_sent"] is True
    assert data["external_id"] is not None
    assert "(11)" in data["masked_phone"]
    assert data["roles"] == ["lead"]
    assert data["next_route"] == "/autenticacao/otp"

    user = User.objects.get(external_id=data["external_id"])
    lead = Lead.objects.get(user=user)
    assert lead.status == Lead.Status.PENDING


@pytest.mark.django_db
def test_capture_phone_only_existing_lead(client):
    existing_user = User.objects.create_user()
    profiles.create(
        user=existing_user,
        cpf=None,
        phone="5511988887777",
        name="Existing User",
    )


    # First capture on existing user dispatches OTP cleanly
    resp1 = client.post(
        "/api/v1/clients/lead/capture",
        data={"phone": "11988887777"},
        content_type="application/json",
    )
    assert resp1.status_code == 200, resp1.json()
    data1 = resp1.json()
    assert data1["found"] is True
    assert data1["created"] is False
    assert data1["external_id"] == str(existing_user.external_id)
    assert data1["otp_sent"] is True

    # Immediate second capture triggers 429 RATE_LIMITED with Retry-After header
    resp2 = client.post(
        "/api/v1/clients/lead/capture",
        data={"phone": "11988887777"},
        content_type="application/json",
    )
    assert resp2.status_code == 429
    assert resp2.headers.get("Retry-After") is not None
    data2 = resp2.json()
    assert data2["code"] == "RATE_LIMITED"
    assert "retry_after_s" in data2



@pytest.mark.django_db
def test_capture_scenario_a_new_cpf_enriched(client):
    cpf = "58622877361"
    payload = {

        "phone": "11977776666",
        "cpf": cpf,
        "attribution": {
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "search_supletivo",
            "gclid": "gclid_test_12345",
        },
    }
    resp = client.post(
        "/api/v1/clients/lead/capture",
        data=payload,
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["found"] is False
    assert data["created"] is True
    assert data["otp_sent"] is True
    assert data["external_id"] is not None
    assert data["roles"] == ["lead"]
    assert data["next_route"] == "/autenticacao/otp"

    user = User.objects.get(external_id=data["external_id"])
    profile = profiles.get(user)
    assert profile.cpf == cpf
    assert profile.name is not None
    assert profile.birth_date is not None

    lead = Lead.objects.get(user=user)
    attr = LeadAttribution.objects.get(lead=lead)
    assert attr.utm_source == "google"
    assert attr.utm_campaign == "search_supletivo"
    assert attr.gclid == "gclid_test_12345"


@pytest.mark.django_db
def test_capture_scenario_b_existing_cpf_recovery(client):
    owner_user = User.objects.create_user()
    profiles.create(
        user=owner_user,
        cpf="11144477735",
        phone="5511999990000",
        name="Owner Original",
    )

    payload = {
        "phone": "11988881234",
        "cpf": "111.444.777-35",
    }
    resp = client.post(
        "/api/v1/clients/lead/capture",
        data=payload,
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["found"] is True
    assert data["created"] is False
    assert data["external_id"] == str(owner_user.external_id)
    assert data["otp_sent"] is True
    assert data["masked_phone"] == "(11) •••••-0000"
    assert data["next_route"] == "/autenticacao/otp"

    owner_profile = profiles.get(owner_user)
    assert owner_profile.phone == "5511999990000"


@pytest.mark.django_db
def test_capture_invalid_cpf_modulo_11(client):
    payload = {
        "phone": "11988887777",
        "cpf": "11111111111",
    }
    resp = client.post(
        "/api/v1/clients/lead/capture",
        data=payload,
        content_type="application/json",
    )
    assert resp.status_code == 422
    data = resp.json()
    assert data["code"] == "CPF_INVALID"


@pytest.mark.django_db
def test_capture_phone_not_on_whatsapp(client):
    payload = {
        "phone": "11988887777",
    }
    with patch("users.auth.service._wa_check", return_value=(False, "5511988887777")):
        resp = client.post(
            "/api/v1/clients/lead/capture",
            data=payload,
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["code"] == "PHONE_NOT_ON_WHATSAPP"


@pytest.mark.django_db
def test_auth_capture_alias(client):
    payload = {
        "phone": "11955554444",
    }
    resp = client.post(
        "/api/v1/clients/auth/capture",
        data=payload,
        content_type="application/json",
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()
    assert data["found"] is False
    assert data["created"] is True
    assert data["next_route"] == "/autenticacao/otp"
