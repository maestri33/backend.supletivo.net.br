from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.django_db


def _promoter_token():
    from hub.models import Hub
    from users.address.models import Address
    from users.auth.jwt import service as jwt_service
    from users.auth.models import User
    from users.profiles.models import Profile
    from users.roles import service as roles
    from users.roles.promoter.models import Promoter

    coordinator = User.objects.create_user(external_id=uuid.uuid4())
    address = Address.objects.create(city="São Paulo", state="SP")
    hub = Hub.objects.create(
        address=address,
        brand="invite-test",
        coordinator=coordinator,
        is_default=True,
    )
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=user, phone="5511999990001")
    roles.assign(user, "candidate")
    roles.promote(user, "promoter")
    promoter = Promoter.objects.create(
        user=user,
        hub=hub,
        status=Promoter.Status.ACTIVE,
    )
    token = jwt_service.issue(str(user.external_id), ["promoter"])["access_token"]
    return promoter, token


def _post(client, token: str, *, phone="43999999999", cpf="52998224725"):
    return client.post(
        "/api/v1/collaborators/promoter/me/leads/invite",
        {"phone": phone, "cpf": cpf},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def test_promoter_invite_encaminha_link_sem_criar_usuario_ou_lead(client, monkeypatch):
    from users.auth.models import User
    from users.roles.lead.models import Lead
    from users.roles.promoter import service as promoter_iface

    _promoter, token = _promoter_token()
    sent = []
    monkeypatch.setattr(
        promoter_iface,
        "_send_lead_invite",
        lambda user, phone: sent.append((user, phone)) or "notification-id",
    )
    users_before = User.objects.count()

    response = _post(client, token)

    assert response.status_code == 200
    assert response.json() == {"sent": True, "phone_last4": "9999"}
    assert User.objects.count() == users_before
    assert Lead.objects.count() == 0
    assert sent[0][1] == "5543999999999"


def test_promoter_invite_recusa_cpf_existente_sem_notificar(client, monkeypatch):
    from users.auth.models import User
    from users.profiles.models import Profile
    from users.roles.promoter import service as promoter_iface

    _promoter, token = _promoter_token()
    owner = User.objects.create_user()
    Profile.objects.create(user=owner, cpf="52998224725", phone="5511999990002")
    monkeypatch.setattr(
        promoter_iface,
        "_send_lead_invite",
        lambda *_args, **_kwargs: pytest.fail("não deve notificar"),
    )

    response = _post(client, token)

    assert response.status_code == 409
    assert response.json()["code"] == "CPF_EXISTS"


def test_promoter_invite_recusa_cpf_invalido(client):
    _promoter, token = _promoter_token()

    response = _post(client, token, cpf="12345678900")

    assert response.status_code == 422
    assert response.json()["code"] == "CPF_INVALID"


def test_promoter_invite_envia_com_idempotencia(monkeypatch):
    from notify.interface import send as notify_send
    from users.roles.promoter import service as promoter_iface

    promoter, _token = _promoter_token()
    calls = []
    monkeypatch.setattr(
        notify_send, "send", lambda **kwargs: calls.append(kwargs) or "notification-id"
    )

    assert promoter_iface._send_lead_invite(promoter.user, "5543999999999") == "notification-id"
    assert calls[0]["caller"] == "promoter.lead_invite"
    assert calls[0]["phone"] == "5543999999999"
    assert calls[0]["idempotency_key"]
