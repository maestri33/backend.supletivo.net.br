import httpx
import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    from users.models import Profile, User
    row = User.objects.create_user()
    Profile.objects.create(user=row, phone="5511999990011")
    return row


def test_otp_waits_for_provider_before_marking_sent(monkeypatch, user):
    from django.conf import settings
    from notify.sdk import client
    from users.auth.otp import service
    from users.auth.otp.models import OtpCode

    def provider(method, path, **kwargs):
        assert OtpCode.objects.get(user=user).status == "generated"
        assert kwargs["json"]["run_sync"] is True
        assert kwargs["timeout"] == settings.NOTIFY_SYNC_TIMEOUT
        return httpx.Response(200, json={"external_id": kwargs["json"]["external_id"]})

    monkeypatch.setattr(client, "_request", provider)
    assert service.generate_and_send(user).status == "sent"


@pytest.mark.parametrize("failure", ["http_503", "timeout"])
def test_provider_failure_is_recorded_and_login_returns_503(monkeypatch, user, client, failure):
    from notify.sdk import client as notify_client
    from users.auth.otp.models import OtpCode

    def provider(*args, **kwargs):
        if failure == "timeout":
            raise httpx.ReadTimeout("mocked provider timeout")
        return httpx.Response(503, json={"detail": "provider rejected send"})

    monkeypatch.setattr(notify_client, "_request", provider)
    response = client.post(
        "/api/v1/clients/auth/check",
        {"external_id": str(user.external_id), "send_otp": True},
        content_type="application/json",
    )
    assert response.status_code == 503, response.content
    assert response.json()["code"] == "OTP_NOT_SENT"
    otp = OtpCode.objects.get(user=user)
    assert otp.status == "failed"
    assert otp.failure_reason == "provider_unavailable"
    assert not otp.notification_external_id
