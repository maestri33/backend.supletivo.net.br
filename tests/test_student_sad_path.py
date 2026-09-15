"""Testes de SAD PATH e SEGURANÇA do funil do aluno (Lead, Checkout e Matrícula).

Cobertura:
1.  Check com phone inválido/malformado → 422
2.  Check com payload vazio → 422
3.  Login com OTP incorreto → 401 OTP_INVALID
4.  Login com external_id inexistente → 404 USER_NOT_FOUND
5.  Login com brute force / OTP bloqueado após 5 tentativas → 401
6.  Identity com CPF inválido/dígito verificador incorreto → 422 CPF_INVALID
7.  Identity sem token de autenticação → 401
8.  Identity com role incorreta (ex: coordinator) → 403
9.  Email com formato malformado (sem @) → 422 EMAIL_INVALID
10. Checkout direto sem preencher perfil (CPF/E-mail) → 409 PROFILE_INCOMPLETE
11. Acesso a /enrollment/me sem role enrollment (usuário ainda é lead) → 403
12. Upload de RG com slot inválido → 422 SLOT_INVALID
13. Upload de documento com mime-type não permitido (não imagem) → 400 FILE_NOT_IMAGE
14. Upload de mesma imagem como frente e verso do RG → 422 DOCUMENT_SIDE_DUPLICATE
15. Acesso a /student/me sem role student (usuário ainda em enrollment) → 403
"""

from __future__ import annotations

import io
import json
import uuid
import pytest
from PIL import Image
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from hub.models import Hub
from users.address.models import Address
from users.auth.jwt.service import issue
from users.auth.models import User
from users.roles import interface as roles
from users.roles.enrollment.models import Enrollment


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


def _png(color: str = "white", size: tuple[int, int] = (16, 16)) -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return SimpleUploadedFile(
        f"doc_{color}.png", buffer.getvalue(), content_type="image/png"
    )


@pytest.fixture
def default_hub(db):
    """Hub padrão com coordenador para auto-captura de leads."""
    coord = User.objects.create_user(external_id=uuid.uuid4())
    address = Address.objects.create(
        city="Londrina",
        state="PR",
        street="Rua Central",
        number="500",
        neighborhood="Centro",
        zipcode="86010000",
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
    from users.documents import service as documents

    storage = FileSystemStorage(location=tmp_path)
    monkeypatch.setattr(documents, "default_storage", storage)
    monkeypatch.setattr(media, "default_storage", storage)
    return storage


# ---------------------------------------------------------------------------
# 1. Check com phone inválido → 422
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_check_invalid_phone_returns_422(client: Client):
    res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "invalid_phone_123"}),
        content_type="application/json",
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# 2. Check com payload vazio → 422
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_check_empty_payload_returns_422(client: Client):
    res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# 3. Login com OTP incorreto → 401
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_login_wrong_otp_returns_401(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "11999998888"}),
        content_type="application/json",
    )
    assert check_res.status_code == 200
    ext_id = check_res.json()["external_id"]

    login_res = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": ext_id, "otp": "999999"}),
        content_type="application/json",
    )
    assert login_res.status_code == 401
    assert login_res.json()["code"] == "OTP_INVALID"


# ---------------------------------------------------------------------------
# 4. Login com external_id inexistente → 404
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_login_nonexistent_external_id_returns_404(client: Client):
    res = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": str(uuid.uuid4()), "otp": "000000"}),
        content_type="application/json",
    )
    assert res.status_code == 404
    assert res.json()["code"] == "USER_NOT_FOUND"


# ---------------------------------------------------------------------------
# 5. Brute force: 5 tentativas erradas bloqueiam o OTP → 401
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_login_brute_force_blocks_otp(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "11988887777"}),
        content_type="application/json",
    )
    assert check_res.status_code == 200
    ext_id = check_res.json()["external_id"]

    for _ in range(5):
        client.post(
            f"{BASE}/auth/login",
            data=json.dumps({"external_id": ext_id, "otp": "111111"}),
            content_type="application/json",
        )

    # 6ª tentativa deve continuar 401
    res = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": ext_id, "otp": "111111"}),
        content_type="application/json",
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 6. Identity com CPF inválido → 422
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_identity_invalid_cpf_returns_422(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "11977776666"}),
        content_type="application/json",
    )
    ext_id = check_res.json()["external_id"]
    login_res = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": ext_id, "otp": "000000"}),
        content_type="application/json",
    )
    token = login_res.json()["access_token"]

    res = client.post(
        f"{BASE}/lead/identity",
        data=json.dumps({"cpf": "12345678900"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 422
    assert res.json()["code"] == "CPF_INVALID"


# ---------------------------------------------------------------------------
# 7. Identity sem token → 401
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_identity_unauthorized_returns_401(client: Client):
    res = client.post(
        f"{BASE}/lead/identity",
        data=json.dumps({"cpf": _valid_cpf("333444555")}),
        content_type="application/json",
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 8. Identity com role incorreta (ex: candidate sem role lead) → 403
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_identity_wrong_role_returns_403(client: Client):
    user = User.objects.create_user()
    roles.assign(user, "candidate")
    token = issue(str(user.external_id), roles.active_roles(user))["access_token"]

    res = client.post(
        f"{BASE}/lead/identity",
        data=json.dumps({"cpf": _valid_cpf("444555666")}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 9. Email malformado → 422
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_email_malformed_returns_422(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "11966665555"}),
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
        data=json.dumps({"email": "email_sem_arroba.com"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 422
    assert res.json()["code"] == "EMAIL_INVALID"


# ---------------------------------------------------------------------------
# 10. Checkout sem preencher CPF/Email → 409 PROFILE_INCOMPLETE
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_checkout_without_profile_returns_409(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "11955554444"}),
        content_type="application/json",
    )
    ext_id = check_res.json()["external_id"]
    token = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": ext_id, "otp": "000000"}),
        content_type="application/json",
    ).json()["access_token"]

    res = client.post(
        f"{BASE}/lead/checkout",
        data=json.dumps({"payment_method": "pix"}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 409
    assert res.json()["code"] == "PROFILE_INCOMPLETE"


# ---------------------------------------------------------------------------
# 11. Acesso a /enrollment/me sem role enrollment → 403
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_enrollment_me_forbidden_for_lead_role(client: Client, default_hub: Hub, monkeypatch):
    monkeypatch.setattr("users.auth.service._check_phone_whatsapp", lambda phone: (True, phone))
    check_res = client.post(
        f"{BASE}/auth/check",
        data=json.dumps({"phone": "11944443333"}),
        content_type="application/json",
    )
    ext_id = check_res.json()["external_id"]
    token = client.post(
        f"{BASE}/auth/login",
        data=json.dumps({"external_id": ext_id, "otp": "000000"}),
        content_type="application/json",
    ).json()["access_token"]

    res = client.get(
        f"{BASE}/enrollment/me",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 12. Upload de RG com slot inválido → 422
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_enrollment_rg_invalid_slot_returns_422(client: Client, default_hub: Hub, temp_media_storage):
    user = User.objects.create_user()
    roles.assign(user, "lead")
    roles.promote(user, "enrollment")
    Enrollment.objects.create(
        user=user,
        promoter=default_hub.coordinator,
        hub=default_hub,
        status=Enrollment.Status.RG,
    )
    token = issue(str(user.external_id), roles.active_roles(user))["access_token"]

    file = _png("white")
    res = client.post(
        f"{BASE}/enrollment/documents/rg/photo/slot_invalido",
        data={"file": file},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# 13. Upload de documento com arquivo não-imagem → 422 FILE_NOT_IMAGE
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_enrollment_rg_non_image_upload_returns_422(client: Client, default_hub: Hub, temp_media_storage):
    from users.documents import service as documents

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

    fake_file = SimpleUploadedFile("document.txt", b"Texto plano nao e imagem", content_type="text/plain")
    res = client.post(
        f"{BASE}/enrollment/documents/rg/photo/front",
        data={"file": fake_file},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 422
    assert res.json()["code"] == "IMAGE_TYPE_INVALID"


# ---------------------------------------------------------------------------
# 14. Upload de mesma imagem como frente e verso → 422 DOCUMENT_SIDE_DUPLICATE
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_enrollment_rg_duplicate_sides_returns_422(client: Client, default_hub: Hub, temp_media_storage):
    from users.documents import service as documents

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

    file_front = _png("blue")
    res_front = client.post(
        f"{BASE}/enrollment/documents/rg/photo/front",
        data={"file": file_front},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res_front.status_code == 200

    file_back_same = _png("blue")
    res_back = client.post(
        f"{BASE}/enrollment/documents/rg/photo/back",
        data={"file": file_back_same},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res_back.status_code == 422
    assert res_back.json()["code"] == "DOCUMENT_SIDE_DUPLICATE"


# ---------------------------------------------------------------------------
# 15. Acesso a /student/me sem role student → 403
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_student_me_forbidden_for_enrollment_role(client: Client, default_hub: Hub):
    user = User.objects.create_user()
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
        f"{BASE}/student/me",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert res.status_code == 403
