from datetime import timedelta
import pytest
from django.conf import settings
from users.auth.models import User
from users.auth import service as auth_service
from users.auth.jwt import service as jwt_service
from users.auth.otp.models import OtpCode, STATUS_SENT
from users.auth.otp import service as otp_service
from users.roles import interface as roles


@pytest.fixture
def auth_user():
    user = User.objects.create(token_version=0)
    roles.assign(user, "lead")
    return user


@pytest.fixture
def staff_user():
    user = User.objects.create_superuser(
        password="TestMasterPassword123!",
        token_version=0,
    )
    return user


@pytest.mark.django_db
def test_jwt_refresh_lifetime_is_30_days():
    assert settings.NINJA_JWT["REFRESH_TOKEN_LIFETIME"] == timedelta(minutes=43200)


@pytest.mark.django_db
def test_subsequent_login_invalidates_previous_jwt_session(client, auth_user):
    # Device 1: Login
    otp_1 = "111111"
    OtpCode.objects.create(
        user=auth_user,
        code_hash=otp_service._hash_code(otp_1),
        status=STATUS_SENT,
    )
    tokens_dev1 = auth_service.login(
        external_id=str(auth_user.external_id), role="lead", otp=otp_1
    )

    # Device 1 accesses whoami -> 200 OK
    res1 = client.get(
        "/api/v1/clients/whoami",
        HTTP_AUTHORIZATION=f"Bearer {tokens_dev1['access_token']}",
    )
    assert res1.status_code == 200

    # Device 2: Login from another device/browser
    otp_2 = "222222"
    OtpCode.objects.create(
        user=auth_user,
        code_hash=otp_service._hash_code(otp_2),
        status=STATUS_SENT,
    )
    tokens_dev2 = auth_service.login(
        external_id=str(auth_user.external_id), role="lead", otp=otp_2
    )

    # Device 2 accesses whoami -> 200 OK
    res2 = client.get(
        "/api/v1/clients/whoami",
        HTTP_AUTHORIZATION=f"Bearer {tokens_dev2['access_token']}",
    )
    assert res2.status_code == 200

    # Device 1 access token is now INVALID (token_version stale) -> 401
    res1_after = client.get(
        "/api/v1/clients/whoami",
        HTTP_AUTHORIZATION=f"Bearer {tokens_dev1['access_token']}",
    )
    assert res1_after.status_code == 401

    # Device 1 refresh token is now INVALID -> raises TokenError
    with pytest.raises(jwt_service.TokenError):
        jwt_service.refresh(tokens_dev1["refresh_token"])

    # Device 2 refresh token is VALID and works
    rotated_dev2 = jwt_service.refresh(tokens_dev2["refresh_token"])
    res2_after_refresh = client.get(
        "/api/v1/clients/whoami",
        HTTP_AUTHORIZATION=f"Bearer {rotated_dev2['access_token']}",
    )
    assert res2_after_refresh.status_code == 200


@pytest.mark.django_db
def test_staff_login_otp_and_password_invalidates_previous_session(client, staff_user):
    # Staff Device 1: Login OTP
    otp_1 = "333333"
    OtpCode.objects.create(
        user=staff_user,
        code_hash=otp_service._hash_code(otp_1),
        status=STATUS_SENT,
    )
    tokens_dev1 = auth_service.login_staff(
        external_id=str(staff_user.external_id), otp=otp_1
    )

    res1 = client.get(
        "/api/v1/staff/whoami",
        HTTP_AUTHORIZATION=f"Bearer {tokens_dev1['access_token']}",
    )
    assert res1.status_code == 200

    # Staff Device 2: Login via Password
    tokens_dev2 = auth_service.login_staff_password(
        identifier=str(staff_user.external_id),
        password="TestMasterPassword123!",
    )

    res2 = client.get(
        "/api/v1/staff/whoami",
        HTTP_AUTHORIZATION=f"Bearer {tokens_dev2['access_token']}",
    )
    assert res2.status_code == 200

    # Device 1 access token is now INVALID
    res1_after = client.get(
        "/api/v1/staff/whoami",
        HTTP_AUTHORIZATION=f"Bearer {tokens_dev1['access_token']}",
    )
    assert res1_after.status_code == 401

    with pytest.raises(jwt_service.TokenError):
        jwt_service.refresh(tokens_dev1["refresh_token"])
