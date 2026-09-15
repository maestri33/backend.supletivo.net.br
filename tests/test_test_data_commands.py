from datetime import timedelta
import json
import uuid

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from users.auth.models import User
from users.profiles.models import Profile
from users.roles.candidate.models import Candidate


@pytest.fixture
def default_hub():
    from hub.models import Hub
    from users.address.models import Address

    coordinator = User.objects.create_user(external_id=uuid.uuid4())
    address = Address.objects.create(city="São Paulo", state="SP")
    return Hub.objects.create(
        address=address,
        brand="e2e",
        coordinator=coordinator,
        is_default=True,
    )


@pytest.mark.django_db
def test_seed_test_collaborator_reseta_estado(settings, default_hub):
    settings.APP_ENV = "test"
    settings.TEST_MODE = True
    settings.TEST_COLLABORATOR_PHONE = "5511999990001"
    settings.TEST_COLLABORATOR_CPF = "52998224725"
    settings.TEST_COLLABORATOR_EMAIL = "e2e-promotor@v7m.test"
    settings.TEST_DATA_TTL_HOURS = 24

    call_command("seed_test_collaborator")
    first = Profile.objects.get(phone=settings.TEST_COLLABORATOR_PHONE).user
    Candidate.objects.filter(user=first).update(status=Candidate.Status.ADDRESS)

    call_command("seed_test_collaborator")
    seeded = Profile.objects.get(phone=settings.TEST_COLLABORATOR_PHONE).user
    assert seeded.is_test is True
    assert seeded.id != first.id
    assert Candidate.objects.get(user=seeded).status == Candidate.Status.STARTED


@pytest.mark.django_db
def test_seed_test_collaborator_entra_no_funil_com_otp_deterministico(
    settings, default_hub, client
):
    settings.APP_ENV = "test"
    settings.TEST_MODE = True
    settings.TEST_COLLABORATOR_PHONE = "5511999990001"
    settings.TEST_COLLABORATOR_CPF = "52998224725"
    settings.TEST_COLLABORATOR_EMAIL = "e2e-promotor@v7m.test"
    settings.TEST_MODE_OTP_CODE = "000000"

    call_command("seed_test_collaborator")
    check = client.post(
        "/api/v1/collaborators/auth/check",
        data=json.dumps({"phone": "11999990001"}),
        content_type="application/json",
    )
    assert check.status_code == 200, check.content
    payload = check.json()
    assert payload["found"] is True
    assert payload["otp_sent"] is True

    login = client.post(
        "/api/v1/collaborators/auth/login",
        data=json.dumps({"external_id": payload["external_id"], "otp": "000000"}),
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    assert login.json()["access_token"]


@pytest.mark.django_db
def test_cleanup_test_data_remove_apenas_expirados():
    expired = User.objects.create_user(
        is_test=True, test_expires_at=timezone.now() - timedelta(minutes=1)
    )
    active = User.objects.create_user(
        is_test=True, test_expires_at=timezone.now() + timedelta(hours=1)
    )
    call_command("cleanup_test_data")
    assert not User.objects.filter(id=expired.id).exists()
    assert User.objects.filter(id=active.id).exists()


@pytest.mark.django_db
def test_seed_test_collaborator_bloqueado_em_prod(settings, default_hub):
    settings.APP_ENV = "prod"
    settings.TEST_MODE = False
    with pytest.raises(CommandError):
        call_command("seed_test_collaborator")
