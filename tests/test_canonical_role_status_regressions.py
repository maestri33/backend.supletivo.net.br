"""Current database state must drive canonical role journeys and session refresh."""

import pytest
from django.db.models import F

from hub.models import Hub
from users.address.models import Address
from users.auth.jwt import service as jwt
from users.auth.models import User
from users.roles import interface as roles
from users.roles.models import UserRole
from users.roles.promoter.models import Promoter
from users.roles.service import resolve_user_roles_and_statuses

pytestmark = pytest.mark.django_db


@pytest.fixture
def promoter():
    coordinator = User.objects.create_user()
    address = Address.objects.create(
        street="Rua Teste", number="10", neighborhood="Centro",
        city="Londrina", state="PR", zipcode="86000000",
    )
    hub = Hub.objects.create(address=address, brand="standard", coordinator=coordinator)
    user = User.objects.create_user()
    UserRole.objects.create(user=user, role="promoter")
    return Promoter.objects.create(user=user, hub=hub)


def test_whoami_drops_revoked_training_from_existing_token(client, promoter):
    user = promoter.user
    roles.grant(user, "training")
    tokens = jwt.issue(str(user.external_id), roles.active_roles(user))
    roles.revoke(user, "training")

    response = client.get(
        "/api/v1/collaborators/whoami",
        HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}",
    )

    assert response.status_code == 200
    assert response.json()["roles"] == ["promoter"]
    assert response.json()["role_statuses"] == {"promoter": "active"}


def test_whoami_reads_new_training_without_requiring_new_token(client, promoter, settings):
    settings.TRAINING_ENABLED = True  # Legacy overlay semantics when LMS is enabled.
    user = promoter.user
    tokens = jwt.issue(str(user.external_id), ["promoter"])
    roles.grant(user, "training")

    response = client.get(
        "/api/v1/collaborators/whoami",
        HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}",
    )

    assert response.status_code == 200
    assert response.json()["role_statuses"] == {"promoter": "training"}


@pytest.mark.parametrize("training", [False, True])
def test_suspension_takes_precedence_over_training(promoter, training):
    if training:
        roles.grant(promoter.user, "training")
    promoter.status = Promoter.Status.SUSPENDED
    promoter.save(update_fields=["status"])

    canonical_roles, statuses = resolve_user_roles_and_statuses(
        promoter.user, roles.active_roles(promoter.user)
    )

    assert canonical_roles == ["promoter"]
    assert statuses == {"promoter": "suspended"}


def test_existing_user_does_not_inherit_removed_admin_from_token(client):
    user = User.objects.create_user()
    assert resolve_user_roles_and_statuses(user, ["admin", "staff"]) == ([], {})
    tokens = jwt.issue(str(user.external_id), ["admin", "staff"])
    response = client.get(
        "/api/v1/clients/whoami",
        HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}",
    )
    assert response.status_code == 200
    assert response.json()["roles"] == []
    assert response.json()["role_statuses"] == {}


def test_revoked_promoter_history_does_not_override_new_student_journey(client, promoter):
    user = promoter.user
    promoter.status = Promoter.Status.SUSPENDED
    promoter.save()
    roles.revoke(user, "promoter")
    roles.grant(user, "lead")
    tokens = jwt.issue(str(user.external_id), ["lead", "promoter"])
    response = client.get("/api/v1/clients/whoami", HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    assert response.status_code == 200
    assert response.json()["roles"] == ["student"]
    assert response.json()["role_statuses"] == {"student": "lead"}
    assert Promoter.objects.filter(pk=promoter.pk).exists()


@pytest.mark.parametrize(
    ("previous", "current", "expected_status"),
    [("lead", "enrollment", "enrollment"), ("enrollment", "student", "active")],
)
def test_student_promotion_refreshes_session_and_preserves_other_role(
    client, previous, current, expected_status
):
    user = User.objects.create_user()
    UserRole.objects.create(user=user, role=previous)
    UserRole.objects.create(user=user, role="promoter")
    tokens = jwt.issue(str(user.external_id), [previous, "promoter"])
    roles.promote(user, current)

    stale = client.get(
        "/api/v1/clients/whoami",
        HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}",
    )
    assert stale.status_code == 401
    response = client.post(
        "/api/v1/clients/auth/refresh",
        {"refresh_token": tokens["refresh_token"]},
        content_type="application/json",
    )
    assert response.status_code == 200
    claims = jwt.decode(response.json()["access_token"])
    assert set(claims["roles"]) == {current, "promoter"}
    identity = client.get(
        "/api/v1/clients/whoami",
        HTTP_AUTHORIZATION=f"Bearer {response.json()['access_token']}",
    )
    assert identity.status_code == 200
    assert identity.json()["role_statuses"]["student"] == expected_status


@pytest.mark.parametrize("extra_change", ["revocation", "new_role", "ban"])
def test_student_promotion_does_not_bypass_session_revocation(extra_change):
    user = User.objects.create_user()
    UserRole.objects.create(user=user, role="lead")
    tokens = jwt.issue(str(user.external_id), ["lead"])
    roles.promote(user, "enrollment")
    if extra_change == "revocation":
        User.objects.filter(pk=user.pk).update(token_version=F("token_version") + 1)
    elif extra_change == "new_role":
        UserRole.objects.create(user=user, role="coordinator")
    else:
        User.objects.filter(pk=user.pk).update(is_active=False)

    with pytest.raises(jwt.TokenError):
        jwt.refresh(tokens["refresh_token"])
