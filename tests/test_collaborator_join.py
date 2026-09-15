import json
import uuid

import pytest

from users.auth import service as auth_service
from users.auth.jwt import service as jwt_service
from users.auth.models import User
from users.roles import interface as roles
from users.roles.candidate.models import Candidate


OTP = "000000"
BASE = "/api/v1/collaborators/auth"


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


def _post(client, path: str, body: dict):
    return client.post(
        f"{BASE}{path}", data=json.dumps(body), content_type="application/json"
    )


def _existing_lead(*, phone: str, cpf: str, email: str) -> User:
    registered = auth_service.register(role="lead", phone=phone, cpf=cpf, email=email)
    return User.objects.get(external_id=registered["external_id"])


@pytest.mark.django_db
def test_existing_supletivo_user_can_join_after_otp(client, default_hub):
    user = _existing_lead(
        phone="11987650011", cpf="52998224725", email="join-1@v7m.test"
    )

    denied = _post(
        client,
        "/login",
        {"external_id": str(user.external_id), "otp": OTP},
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "NOT_IN_FUNNEL"

    joined = _post(
        client,
        "/join",
        {"external_id": str(user.external_id), "otp": OTP},
    )
    assert joined.status_code == 200, joined.content
    assert joined.json()["access_token"]
    assert set(roles.active_roles(user)) == {"candidate", "lead"}
    assert (
        Candidate.objects.filter(user=user, status=Candidate.Status.STARTED).count()
        == 1
    )


@pytest.mark.django_db
def test_join_wrong_otp_does_not_provision_anything(client, default_hub):
    user = _existing_lead(
        phone="11987650012", cpf="16899535009", email="join-2@v7m.test"
    )

    response = _post(
        client,
        "/join",
        {"external_id": str(user.external_id), "otp": "999999"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "OTP_INVALID"
    assert roles.active_roles(user) == ["lead"]
    assert not Candidate.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_join_replay_does_not_duplicate_candidate(client, default_hub):
    user = _existing_lead(
        phone="11987650013", cpf="11144477735", email="join-3@v7m.test"
    )
    body = {"external_id": str(user.external_id), "otp": OTP}

    assert _post(client, "/join", body).status_code == 200
    replay = _post(client, "/join", body)

    assert replay.status_code == 401
    # OTP_EXPIRED, não OTP_INVALID: o código foi CONSUMIDO no primeiro join. Desde o funil v2
    # (tela 2) o 401 separa "errou o código, tenta de novo" de "não há código utilizável, peça
    # outro" — replay é o segundo caso.
    assert replay.json()["code"] == "OTP_EXPIRED"
    assert Candidate.objects.filter(user=user).count() == 1
    assert roles.active_roles(user).count("candidate") == 1


@pytest.mark.django_db
def test_join_incomplete_shared_profile_rolls_back_otp_and_role(client, default_hub):
    registered = auth_service.register(
        role="lead", phone="11987650014", cpf=None, email=None
    )
    user = User.objects.get(external_id=registered["external_id"])
    body = {"external_id": str(user.external_id), "otp": OTP}

    blocked = _post(client, "/join", body)
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "JOIN_PROFILE_INCOMPLETE"
    assert set(blocked.json()["missing_fields"]) == {
        "cpf",
        "email",
        "name",
        "birth_date",
    }
    assert roles.active_roles(user) == ["lead"]
    assert not Candidate.objects.filter(user=user).exists()

    retried = _post(client, "/join", body)
    assert retried.status_code == 422
    assert retried.json()["code"] == "JOIN_PROFILE_INCOMPLETE"


@pytest.mark.django_db
def test_join_repairs_candidate_role_without_candidate_row(client, default_hub):
    registered = auth_service.register(
        role="candidate",
        phone="11987650015",
        cpf="12345678909",
        email="join-5@v7m.test",
    )
    user = User.objects.get(external_id=registered["external_id"])
    assert not Candidate.objects.filter(user=user).exists()

    response = _post(
        client,
        "/join",
        {"external_id": str(user.external_id), "otp": OTP},
    )
    assert response.status_code == 200, response.content
    assert Candidate.objects.filter(user=user, hub=default_hub).count() == 1


@pytest.mark.django_db
def test_join_without_available_hub_does_not_consume_otp(client):
    user = _existing_lead(
        phone="11987650016", cpf="39053344705", email="join-6@v7m.test"
    )
    body = {"external_id": str(user.external_id), "otp": OTP}

    first = _post(client, "/join", body)
    second = _post(client, "/join", body)

    assert first.status_code == 422 and first.json()["code"] == "NO_HUB"
    assert second.status_code == 422 and second.json()["code"] == "NO_HUB"
    assert roles.active_roles(user) == ["lead"]
    assert not Candidate.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_refresh_acompanha_promocao_candidate_para_promoter():
    registered = auth_service.register(
        role="candidate",
        phone="11987650017",
        cpf="98765432100",
        email="transition-1@v7m.test",
    )
    user = User.objects.get(external_id=registered["external_id"])
    tokens = auth_service.login(
        external_id=str(user.external_id), role="candidate", otp=OTP
    )

    roles.promote(user, "promoter")
    roles.grant(user, "training")
    refreshed = jwt_service.refresh(tokens["refresh_token"])
    claims = jwt_service.decode(refreshed["access_token"])

    assert set(claims["roles"]) == {"promoter", "training"}
    assert jwt_service.version_matches(user.external_id, claims["token_version"])


@pytest.mark.django_db
def test_refresh_nao_aceita_outra_troca_de_role():
    registered = auth_service.register(
        role="candidate",
        phone="11987650018",
        cpf="01234567890",
        email="transition-2@v7m.test",
    )
    user = User.objects.get(external_id=registered["external_id"])
    tokens = auth_service.login(
        external_id=str(user.external_id), role="candidate", otp=OTP
    )

    roles.assign(user, "lead")

    with pytest.raises(jwt_service.TokenError):
        jwt_service.refresh(tokens["refresh_token"])


@pytest.mark.django_db
def test_refresh_sincroniza_overlay_de_treinamento_sem_novo_otp():
    registered = auth_service.register(
        role="candidate",
        phone="11977776666",
        cpf="12345678901",
        email="transition-overlay@v7m.test",
    )
    user = User.objects.get(external_id=registered["external_id"])
    roles.promote(user, "promoter")
    roles.grant(user, "training")
    locked_tokens = jwt_service.issue(str(user.external_id), ["promoter", "training"])

    roles.revoke(user, "training")
    unlocked = jwt_service.refresh(locked_tokens["refresh_token"])
    unlocked_claims = jwt_service.decode(unlocked["access_token"])
    assert unlocked_claims["roles"] == ["promoter"]

    roles.grant(user, "training")
    relocked = jwt_service.refresh(unlocked["refresh_token"])
    relocked_claims = jwt_service.decode(relocked["access_token"])
    assert set(relocked_claims["roles"]) == {"promoter", "training"}


@pytest.mark.django_db
def test_new_phone_registers_candidate_on_check(client, default_hub):
    """Quando um telefone novo faz check no endpoint de colaboradores, cria candidato e dispara OTP."""
    phone = "11988887777"
    resp = _post(client, "/check", {"phone": phone, "send_otp": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["found"] is False
    assert data["created"] is True
    assert data["otp_sent"] is True
    assert "candidate" in data["roles"]
    assert data["external_id"] is not None

    user = User.objects.get(external_id=data["external_id"])
    assert user.candidate is not None
    assert user.candidate.status == Candidate.Status.STARTED
    assert user.candidate.hub == default_hub

    # Login subsequente com OTP autentica o novo candidato
    login_resp = _post(client, "/login", {"external_id": data["external_id"], "otp": OTP})
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert "access_token" in login_data
    claims = jwt_service.decode(login_data["access_token"])
    assert "candidate" in claims["roles"]

