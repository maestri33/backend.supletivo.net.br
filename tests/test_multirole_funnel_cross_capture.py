"""Testes de cruzamento multirole nos funis de entrada (aluno e promotor).

Garante que:
1. Candidato existente ao se cadastrar no funil de aluno ganha papel de lead e Lead com preço travado.
2. Aluno/lead existente ao se cadastrar no funil de promotor ganha papel de candidato e Candidate ligado ao polo.
3. Ambos resultam em usuário com papéis canônicos ['student', 'promoter'] e seus respectivos status operacionais.
"""

from __future__ import annotations

import uuid
import pytest
from unittest.mock import patch

from users.auth.models import User
from users.models import Profile
from users.roles.models import UserRole
from users.roles.lead.models import Lead
from users.roles.candidate.models import Candidate
from users.roles.service import resolve_user_roles_and_statuses
from users.roles.lead import service as lead_iface
from users.roles.candidate import capture as candidate_capture
from hub.models import Hub
from users.address.models import Address


@pytest.fixture
def coordinator_and_hub(db):
    coord = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=coord, phone="5543999990001", name="Coordenador Victor")
    UserRole.objects.create(user=coord, role="coordinator")
    addr = Address.objects.create(city="Ponta Grossa", state="PR")
    hub = Hub.objects.create(
        brand="standard",
        address=addr,
        coordinator=coord,
        is_default=True,
    )
    return coord, hub


@pytest.fixture
def promoter_user(db, coordinator_and_hub):
    coord, hub = coordinator_and_hub
    prom = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=prom, phone="5543999990002", name="Promotor Padrao")
    UserRole.objects.create(user=prom, role="promoter")
    return prom


@pytest.mark.django_db
def test_existing_candidate_captures_as_student(coordinator_and_hub, promoter_user):
    """Candidato existente entra no funil de aluno -> recebe role lead e Lead criado."""
    coord, hub = coordinator_and_hub

    # Cria usuário inicialmente apenas como candidato
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=user, phone="5543988887777", name="Diandra Candidata")
    UserRole.objects.create(user=user, role="candidate")
    Candidate.objects.create(user=user, hub=hub)

    initial_roles, initial_statuses = resolve_user_roles_and_statuses(user)
    assert initial_roles == ["promoter"]
    assert initial_statuses == {"promoter": "candidate"}
    assert not hasattr(user, "lead")

    with patch("users.auth.service._send_or_wait", return_value={"otp_sent": True, "otp_wait": None}), \
         patch("notify.interface.events.send_event"):

        result = lead_iface.check_or_capture(
            phone="43988887777",
            send_otp=True,
            service_authed=True,
        )

    assert result["found"] is True
    # Usuário agora possui Lead criado
    user.refresh_from_db()
    assert hasattr(user, "lead")
    assert user.lead.status == Lead.Status.PENDING

    # Roles canônicas agora incluem student e promoter
    roles, statuses = resolve_user_roles_and_statuses(user)
    assert "student" in roles
    assert "promoter" in roles
    assert statuses["student"] == "lead"
    assert statuses["promoter"] == "candidate"


@pytest.mark.django_db
def test_existing_student_captures_as_candidate(coordinator_and_hub, promoter_user):
    """Aluno existente entra no funil de promotor -> recebe role candidate e Candidate criado."""
    coord, hub = coordinator_and_hub

    # Cria usuário inicialmente apenas como aluno/lead
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=user, phone="5543977776666", name="Carlos Aluno")
    UserRole.objects.create(user=user, role="lead")
    Lead.objects.create(user=user, promoter=promoter_user, status=Lead.Status.PENDING)

    initial_roles, initial_statuses = resolve_user_roles_and_statuses(user)
    assert initial_roles == ["student"]
    assert initial_statuses == {"student": "lead"}
    assert not hasattr(user, "candidate")

    with patch("users.auth.service._send_or_wait", return_value={"otp_sent": True, "otp_wait": None}), \
         patch("notify.interface.events.send_event") as mock_notify:

        result = candidate_capture.check_or_capture(
            phone="43977776666",
            send_otp=True,
            service_authed=True,
            hub=str(hub.external_id),
        )

    assert result["found"] is True
    # Usuário agora possui Candidate criado
    user.refresh_from_db()
    assert hasattr(user, "candidate")
    assert user.candidate.hub == hub

    # Ambas as notificações foram disparadas
    assert mock_notify.call_count == 2

    # Roles canônicas agora incluem student e promoter
    roles, statuses = resolve_user_roles_and_statuses(user)
    assert "student" in roles
    assert "promoter" in roles
    assert statuses["student"] == "lead"
    assert statuses["promoter"] == "candidate"
