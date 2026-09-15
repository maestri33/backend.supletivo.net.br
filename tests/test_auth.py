"""Testes de auth: OTP + /auth/check com e sem BOT_SERVICE_SECRET."""

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def existing_user():
    """Cria um usuário de teste com Profile (phone normalizado) para os testes de auth."""
    from users.auth.models import User
    from users.profiles.models import Profile

    user = User.objects.create_user()
    # validate_phone normaliza 11999990001 → 5511999990001
    Profile.objects.create(user=user, phone="5511999990001")
    return user


def test_check_send_otp_false_sem_segredo_recusa(client, existing_user):
    """/auth/check com send_otp=false SEM header de segredo → 401 (usuário existe, sem segredo)."""
    resp = client.post(
        "/api/v1/clients/auth/check",
        {"phone": "11999990001", "send_otp": False},
        content_type="application/json",
    )
    assert resp.status_code == 401
    data = resp.json()
    assert data["code"] == "SERVICE_SECRET_REQUIRED"


def test_check_send_otp_false_com_segredo_ok(client, bot_headers, existing_user):
    """/auth/check com send_otp=false COM header de segredo → 200 + token."""
    resp = client.post(
        "/api/v1/clients/auth/check",
        {"phone": "11999990001", "send_otp": False},
        content_type="application/json",
        **bot_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("found") is True
    assert data.get("token") is not None


def test_check_send_otp_true_sem_segredo_ok(client):
    """/auth/check NORMAL (send_otp=true) SEM segredo → 200 (não exige segredo)."""
    resp = client.post(
        "/api/v1/clients/auth/check",
        {"phone": "11999990000", "send_otp": True},
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "found" in data
    assert "otp_sent" in data


def test_admin_login_form_maxlength_supports_uuid():
    """Form do admin deve permitir UUID (36 chars) no username sem truncar."""
    from users.auth.forms import AdminAuthenticationForm

    form = AdminAuthenticationForm()
    assert form.fields["username"].widget.attrs["maxlength"] == 64


def test_otp_hash_nao_e_plaintext():
    """OTP nunca é armazenado em plaintext — só SHA256."""
    from users.auth.otp.service import _hash_code

    code = "123456"
    hashed = _hash_code(code)
    assert hashed != code
    assert len(hashed) == 64  # hex de sha256


def test_otp_compare_digest_timing_safe():
    """Validação do hash (HMAC compare_digest)."""
    import hmac
    from users.auth.otp.service import _hash_code

    code = "123456"
    hashed = _hash_code(code)
    assert hmac.compare_digest(_hash_code(code), hashed) is True
    assert hmac.compare_digest(_hash_code("000000"), hashed) is False
