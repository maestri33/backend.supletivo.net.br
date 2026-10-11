"""The actual coordinator hook must supply the panel URL used by its template."""
from unittest.mock import Mock

import pytest

from hub import interface as hub_iface
from hub.models import Hub
from notify.interface import events, templates
from users.address import interface as addresses
from users.auth.models import User
from users.profiles import interface as profiles
from users.roles.candidate.models import Candidate

pytestmark = pytest.mark.django_db


def test_assignment_renders_app_panel_link(monkeypatch):
    user = User.objects.create_user()
    profiles.create(user=user, cpf=None, phone="5511998887777", name="Coord Teste")
    hub = Hub.objects.create(brand="standard", coordinator=user, address=addresses.create_empty())
    send = Mock()
    monkeypatch.setattr(events, "send_event", send)
    monkeypatch.setattr(hub_iface, "get_setting", lambda key, default: "https://app.example.test/")

    hub_iface._notify_coordinator_assigned(user)

    ctx = send.call_args.kwargs["ctx"]
    assert ctx["polo_nome"] == hub.brand
    assert ctx["link_painel"] == "https://app.example.test/hub/active"
    body = templates.render("{name}: {polo_nome} {link_painel}", {"name": "Coord", **ctx})
    assert "{link_painel}" not in body
    assert "/hub/active" in body
    assert send.call_args.kwargs["idempotency_key"] == f"hub_coord_assigned_{user.external_id}"


def test_candidate_resolves_own_hub_before_default():
    user = User.objects.create_user()
    own = Hub.objects.create(brand="standard", address=addresses.create_empty())
    Hub.objects.create(brand="standard", address=addresses.create_empty(), is_default=True)
    Candidate.objects.create(user=user, hub=own)

    assert hub_iface.hub_of(user) == own
