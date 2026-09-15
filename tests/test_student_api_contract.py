"""Testes de Contrato de API e Validação de Schema do Funil do Aluno e Matrícula.

Cobertura:
1.  POST /api/v1/clients/auth/check -> CheckOut
2.  POST /api/v1/clients/auth/login -> TokenOut
3.  POST /api/v1/clients/lead/identity -> IdentityOut
4.  POST /api/v1/clients/lead/email -> EmailOut
5.  POST /api/v1/clients/lead/checkout -> CheckoutOut
6.  GET  /api/v1/clients/lead/me -> LeadMeOut
7.  GET  /api/v1/clients/pricing -> PricingOut
8.  GET  /api/v1/clients/contract/current -> ContractOut
9.  GET  /api/v1/clients/enrollment/me -> EnrollmentMeOut
10. GET  /api/v1/clients/enrollment/documents/rg -> RgSectionOut
11. GET  /api/v1/clients/enrollment/address -> PublicAddressOut
12. GET  /api/v1/clients/enrollment/education -> EducationOut
13. GET  /api/v1/clients/enrollment/selfie -> SelfieOut
14. GET  /api/v1/clients/student/me -> StudentMeOut
15. GET  /api/v1/clients/veteran/me -> VeteranMeOut
"""

from __future__ import annotations

import json
import uuid
import pytest
from django.core.files.storage import FileSystemStorage
from django.test import Client

from hub.models import Hub
from users.address.models import Address
from users.auth.jwt.service import issue
from users.auth.models import User
from users.documents import service as documents
from users.roles import interface as roles
from users.roles.enrollment.models import EducationalData, Enrollment
from users.roles.student.models import Student


BASE = "/api/v1/clients"


def _valid_cpf(seed9: str) -> str:
    assert len(seed9) == 9 and seed9.isdigit()

    def dv(digits: str) -> str:
        weights = range(len(digits) + 1, 1, -1)
        total = sum(int(d) * w for d, w in zip(digits, weights))
        rest = (total * 10) % 11
        return "0" if rest == 10 else str(rest)

    d1 = dv(seed9)
    return seed9 + d1 + dv(seed9 + d1)


@pytest.fixture
def default_hub(db):
    """Hub padrão com coordenador para captação e matrícula."""
    coord = User.objects.create_user(external_id=uuid.uuid4())
    address = Address.objects.create(
        city="Curitiba",
        state="PR",
        street="Rua Marechal Deodoro",
        number="100",
        neighborhood="Centro",
        zipcode="80010010",
    )
    return Hub.objects.create(
        address=address,
        brand="standard",
        coordinator=coord,
        is_default=True,
    )


@pytest.fixture
def temp_media_storage(monkeypatch, tmp_path):
    from core import media

    storage = FileSystemStorage(location=tmp_path)
    monkeypatch.setattr(documents, "default_storage", storage)
    monkeypatch.setattr(media, "default_storage", storage)
    return storage


# ---------------------------------------------------------------------------
# 1. POST /auth/check -> CheckOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_client_check(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "41999991111"}),
        content_type="application/json",
    )
    assert res.status_code == 200
    data = res.json()

    assert isinstance(data["found"], bool)
    assert isinstance(data["registered"], bool)
    assert isinstance(data["otp_sent"], bool)
    assert isinstance(data["created"], bool)
    assert isinstance(data["external_id"], str)
    assert isinstance(data["roles"], list)


# ---------------------------------------------------------------------------
# 2. POST /auth/login -> TokenOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_client_login(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "41999992222"}),
        content_type="application/json",
    )
    ext_id = check_res.json()["external_id"]

    res = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": ext_id, "otp": "000000"}),
        content_type="application/json",
    )
    assert res.status_code == 200
    data = res.json()

    assert "access_token" in data and isinstance(data["access_token"], str)
    assert "refresh_token" in data and isinstance(data["refresh_token"], str)
    assert data["token_type"] == "bearer"


# ---------------------------------------------------------------------------
# 3. POST /lead/identity -> IdentityOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_lead_identity(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "41999993333"}),
        content_type="application/json",
    )
    ext_id = check_res.json()["external_id"]
    token = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": ext_id, "otp": "000000"}),
        content_type="application/json",
    ).json()["access_token"]

    cpf = _valid_cpf("111222333")
    res = client.post(
        f"{BASE}/lead/identity",
        data=json.dumps({"cpf": cpf}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200
    data = res.json()

    assert data["cpf"] == cpf
    assert "name" in data
    assert "birth_date" in data
    assert "sex" in data
    assert "photo" in data


# ---------------------------------------------------------------------------
# 4. POST /lead/email -> EmailOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_lead_email(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "41999994444"}),
        content_type="application/json",
    )
    ext_id = check_res.json()["external_id"]
    token = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": ext_id, "otp": "000000"}),
        content_type="application/json",
    ).json()["access_token"]

    res = client.post(
        f"{BASE}/lead/email",
        data=json.dumps({"email": "aluno.teste@gmail.com"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200
    data = res.json()

    assert data["email"] == "aluno.teste@gmail.com"
    assert isinstance(data["already_yours"], bool)


# ---------------------------------------------------------------------------
# 5. POST /lead/checkout -> CheckoutOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_lead_checkout(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "41999995555"}),
        content_type="application/json",
    )
    ext_id = check_res.json()["external_id"]
    token = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": ext_id, "otp": "000000"}),
        content_type="application/json",
    ).json()["access_token"]

    client.post(
        f"{BASE}/lead/identity",
        data=json.dumps({"cpf": _valid_cpf("222333444")}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    client.post(
        f"{BASE}/lead/email",
        data=json.dumps({"email": "aluno5@gmail.com"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    res = client.post(
        f"{BASE}/lead/checkout",
        data=json.dumps({"payment_method": "pix"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200
    data = res.json()

    assert data["payment_method"] == "pix"
    assert isinstance(data["amount"], str)
    assert isinstance(data["is_paid"], bool)
    assert "provider" in data


# ---------------------------------------------------------------------------
# 6. GET /lead/me -> LeadMeOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_lead_me(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "41999996666"}),
        content_type="application/json",
    )
    ext_id = check_res.json()["external_id"]
    token = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": ext_id, "otp": "000000"}),
        content_type="application/json",
    ).json()["access_token"]

    res = client.get(
        f"{BASE}/lead/me",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200
    data = res.json()

    assert isinstance(data["external_id"], str)
    assert data["status"] in ("pending", "paid", "failed")
    assert "customer" in data
    assert "promoter" in data


# ---------------------------------------------------------------------------
# 7. GET /pricing -> PricingOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_pricing(client: Client):
    res = client.get(f"{BASE}/pricing")
    assert res.status_code == 200
    data = res.json()

    assert "pix" in data and isinstance(data["pix"], str)
    assert "card" in data and isinstance(data["card"], dict)
    assert "installment" in data["card"]
    assert "total" in data["card"]
    assert isinstance(data["has_discount"], bool)


# ---------------------------------------------------------------------------
# 8. GET /contract/current -> ContractOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_current(client: Client, default_hub: Hub):
    user = User.objects.create_user()
    roles.assign(user, "lead")
    roles.promote(user, "enrollment")
    token = issue(str(user.external_id), roles.active_roles(user))["access_token"]

    res = client.get(
        f"{BASE}/contract/current",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200
    data = res.json()

    assert "version" in data and isinstance(data["version"], str)
    assert "hash" in data and isinstance(data["hash"], str)
    assert "text" in data and isinstance(data["text"], str)


# ---------------------------------------------------------------------------
# 9. GET /enrollment/me -> EnrollmentMeOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_enrollment_me(client: Client, default_hub: Hub):
    user = User.objects.create_user()
    documents.create_empty(user)
    roles.assign(user, "lead")
    roles.promote(user, "enrollment")
    enr = Enrollment.objects.create(
        user=user,
        promoter=default_hub.coordinator,
        hub=default_hub,
        status=Enrollment.Status.RG,
    )
    token = issue(str(user.external_id), roles.active_roles(user))["access_token"]

    res = client.get(
        f"{BASE}/enrollment/me",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200
    data = res.json()

    assert data["external_id"] == str(enr.external_id)
    assert data["status"] == "rg"
    assert data["hub_external_id"] == str(default_hub.external_id)
    assert isinstance(data["selfie_verified"], bool)
    assert "address_complete" in data


# ---------------------------------------------------------------------------
# 10. GET /enrollment/documents/rg -> RgSectionOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_enrollment_rg_section(client: Client, default_hub: Hub):
    user = User.objects.create_user()
    documents.create_empty(user)
    roles.assign(user, "lead")
    roles.promote(user, "enrollment")
    Enrollment.objects.create(
        user=user,
        promoter=default_hub.coordinator,
        hub=default_hub,
        status=Enrollment.Status.RG,
    )
    token = issue(str(user.external_id), roles.active_roles(user))["access_token"]

    res = client.get(
        f"{BASE}/enrollment/documents/rg",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200
    data = res.json()

    assert "number" in data
    assert "issuing_agency" in data
    assert "front_photo" in data
    assert "back_photo" in data
    assert "analysis_status" in data
    assert isinstance(data["missing_fields"], list)
    assert isinstance(data["photos"], dict)


# ---------------------------------------------------------------------------
# 11. GET /enrollment/address -> PublicAddressOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_enrollment_address(client: Client, default_hub: Hub):
    user = User.objects.create_user()
    documents.create_empty(user)
    roles.assign(user, "lead")
    roles.promote(user, "enrollment")
    Enrollment.objects.create(
        user=user,
        promoter=default_hub.coordinator,
        hub=default_hub,
        status=Enrollment.Status.ADDRESS,
    )
    token = issue(str(user.external_id), roles.active_roles(user))["access_token"]

    res = client.get(
        f"{BASE}/enrollment/address",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200
    data = res.json()

    assert "zipcode" in data
    assert "street" in data
    assert "city" in data
    assert "state" in data
    assert isinstance(data["missing_fields"], list)


# ---------------------------------------------------------------------------
# 12. GET /enrollment/education -> EducationOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_enrollment_education(client: Client, default_hub: Hub):
    user = User.objects.create_user()
    documents.create_empty(user)
    roles.assign(user, "lead")
    roles.promote(user, "enrollment")
    Enrollment.objects.create(
        user=user,
        promoter=default_hub.coordinator,
        hub=default_hub,
        status=Enrollment.Status.EDUCATION,
    )
    token = issue(str(user.external_id), roles.active_roles(user))["access_token"]

    res = client.get(
        f"{BASE}/enrollment/education",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200
    data = res.json()

    assert "level" in data
    assert "grade" in data
    assert "completed" in data
    assert "last_school" in data


# ---------------------------------------------------------------------------
# 13. GET /enrollment/selfie -> SelfieOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_enrollment_selfie(client: Client, default_hub: Hub):
    user = User.objects.create_user()
    documents.create_empty(user)
    roles.assign(user, "lead")
    roles.promote(user, "enrollment")
    Enrollment.objects.create(
        user=user,
        promoter=default_hub.coordinator,
        hub=default_hub,
        status=Enrollment.Status.SELFIE,
    )
    token = issue(str(user.external_id), roles.active_roles(user))["access_token"]

    res = client.get(
        f"{BASE}/enrollment/selfie",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200
    data = res.json()

    assert isinstance(data["exists"], bool)
    assert isinstance(data["verified"], bool)
    assert "analysis_status" in data


# ---------------------------------------------------------------------------
# 14. GET /student/me -> StudentMeOut
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_contract_student_me(client: Client, default_hub: Hub):
    user = User.objects.create_user()
    documents.create_empty(user)
    roles.assign(user, "lead")
    roles.promote(user, "enrollment")
    roles.promote(user, "student")
    student = Student.objects.create(
        user=user,
        hub=default_hub,
        status=Student.Status.PENDING,
    )
    token = issue(str(user.external_id), roles.active_roles(user))["access_token"]

    res = client.get(
        f"{BASE}/student/me",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 200
    data = res.json()

    assert data["external_id"] == str(student.external_id)
    assert data["status"] == "pending"
    assert data["hub_external_id"] == str(default_hub.external_id)
    assert isinstance(data["documents"], list)
    assert isinstance(data["pendencies"], list)
    assert "platform" in data
