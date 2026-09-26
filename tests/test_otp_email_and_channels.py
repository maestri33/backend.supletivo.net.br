"""Testes de envio de OTP por e-mail, multi-canal e fallback em users.auth.otp."""

import uuid
import pytest

from users.auth.models import User
from users.auth.otp import service as otp_service
from users.auth.otp.models import STATUS_FAILED, STATUS_SENT, OtpCode
from users.auth.service import check, mask_email_privacy, recover
from users.profiles.models import Profile

pytestmark = pytest.mark.django_db


def _make_user(phone="5511999990099", email="aluno.teste@supletivo.net.br", cpf="52998224725"):
    user = User.objects.create_user()
    Profile.objects.create(user=user, phone=phone, email=email, cpf=cpf, name="Aluno de Teste")
    return user


def test_mask_email_privacy():
    assert mask_email_privacy("carlos.silva@gmail.com") == "c***a@gmail.com"
    assert mask_email_privacy("ab@domain.com") == "a***@domain.com"
    assert mask_email_privacy(None) is None
    assert mask_email_privacy("invalid") is None


def test_otp_send_whatsapp_default(monkeypatch):
    """Canal padrão despacha para WhatsApp."""
    import notify.interface.send as notify_send

    captured = {}
    sentinel = str(uuid.uuid4())

    def _mock_send(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(notify_send, "send", _mock_send)

    user = _make_user(phone="5511999990001", email="user1@example.com")
    otp = otp_service.generate_and_send(user, channel="whatsapp")

    assert otp.status == STATUS_SENT
    assert captured["whatsapp"] is True
    assert captured["email_channel"] is False
    assert captured["phone"] == "5511999990001"
    assert captured["email"] is None
    assert captured["caller"] == "users.auth.otp"


def test_otp_send_email_exclusive(monkeypatch):
    """Canal 'email' despacha exclusivamente para profile.email."""
    import notify.interface.send as notify_send

    captured = {}
    sentinel = str(uuid.uuid4())

    def _mock_send(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(notify_send, "send", _mock_send)

    user = _make_user(phone="5511999990002", email="exclusivo@example.com")
    otp = otp_service.generate_and_send(user, channel="email")

    assert otp.status == STATUS_SENT
    assert captured["whatsapp"] is False
    assert captured["email_channel"] is True
    assert captured["email"] == "exclusivo@example.com"
    assert captured["phone"] is None
    assert captured["mail_template"] == "otp"
    assert "Seu código de acesso" in captured["subject"]


def test_otp_send_email_fails_if_no_email(monkeypatch):
    """Canal 'email' falha com failure_reason='no_email' se usuário não tiver e-mail."""
    user = _make_user(phone="5511999990003", email=None)
    otp = otp_service.generate_and_send(user, channel="email")

    assert otp.status == STATUS_FAILED
    assert otp.failure_reason == "no_email"


def test_otp_send_all_multi_channel(monkeypatch):
    """Canal 'all' despacha simultaneamente para WhatsApp e E-mail."""
    import notify.interface.send as notify_send

    captured = {}
    sentinel = str(uuid.uuid4())

    def _mock_send(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(notify_send, "send", _mock_send)

    user = _make_user(phone="5511999990004", email="ambos@example.com")
    otp = otp_service.generate_and_send(user, channel="all")

    assert otp.status == STATUS_SENT
    assert captured["whatsapp"] is True
    assert captured["email_channel"] is True
    assert captured["phone"] == "5511999990004"
    assert captured["email"] == "ambos@example.com"


def test_otp_fallback_to_email_when_phone_is_empty(monkeypatch):
    """Se o profile não possui telefone, a chamada padrão faz fallback transparente para e-mail."""
    import notify.interface.send as notify_send
    from users.profiles import interface as profiles_iface

    captured = {}
    sentinel = str(uuid.uuid4())

    def _mock_send(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(notify_send, "send", _mock_send)

    user = _make_user(phone="5511999990006", email="fallback@example.com")

    # Simula profile com telefone vazio
    class MockProfile:
        phone = None
        email = "fallback@example.com"

    monkeypatch.setattr(profiles_iface, "get", lambda u: MockProfile())

    otp = otp_service.generate_and_send(user)  # channel=None / "whatsapp"

    assert otp.status == STATUS_SENT
    assert captured["whatsapp"] is False
    assert captured["email_channel"] is True
    assert captured["email"] == "fallback@example.com"


def test_check_returns_masked_email_and_channels_sent(monkeypatch):
    """O endpoint de check retorna masked_email e lista channels_sent apropriada."""
    import notify.interface.send as notify_send

    monkeypatch.setattr(notify_send, "send", lambda **kw: str(uuid.uuid4()))

    user = _make_user(phone="5511999990005", email="roberto.aluno@example.com", cpf="52998224725")

    # 1. Check padrão (whatsapp) com telefone formatado ou com DDD
    res_wa = check(phone="11999990005")
    assert res_wa["found"] is True
    assert res_wa["otp_sent"] is True
    assert res_wa["masked_email"] == "r***o@example.com"
    assert res_wa["channels_sent"] == ["whatsapp"]

    # 2. Check com preferred_channel="email"
    from users.auth.otp.models import OtpRateLimit
    OtpRateLimit.objects.filter(user=user).delete()

    res_email = check(phone="11999990005", preferred_channel="email")
    assert res_email["found"] is True
    assert res_email["otp_sent"] is True
    assert res_email["channels_sent"] == ["email"]

    # 3. Check com preferred_channel="all"
    OtpRateLimit.objects.filter(user=user).delete()
    res_all = check(phone="11999990005", preferred_channel="all")
    assert res_all["channels_sent"] == ["whatsapp", "email"]

