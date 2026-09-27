import uuid
import pytest
from django.test import Client
from users.auth.models import User
from users.profiles.models import Profile
from users.auth.jwt import service as jwt_service
from users.roles.service import resolve_user_roles_and_statuses
from users.roles.models import UserRole
from users.roles.lead.models import Lead
from users.roles.enrollment.models import Enrollment
from users.roles.student.models import Student
from users.roles.promoter.models import Promoter
from users.roles.candidate.models import Candidate
from hub.models import Hub
from users.address.models import Address

pytestmark = pytest.mark.django_db


def test_canonical_roles_resolution_for_student_lead():
    """Aluno com registro de Lead deve ter role='student' e status='lead'."""
    promoter_user = User.objects.create_user(external_id=uuid.uuid4())
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=user, phone="11999990002")
    UserRole.objects.create(user=user, role="lead")
    Lead.objects.create(user=user, promoter=promoter_user)

    roles, statuses = resolve_user_roles_and_statuses(user)
    assert roles == ["student"]
    assert statuses == {"student": "lead"}


def test_canonical_roles_resolution_for_student_enrollment():
    """Aluno com Enrollment deve ter role='student' e status='enrollment'."""
    promoter_user = User.objects.create_user(external_id=uuid.uuid4())
    addr = Address.objects.create(street="Rua 1", number="10", neighborhood="Bairro", city="Cidade", state="SP", zipcode="01001000")
    hub = Hub.objects.create(brand="supletivo", address=addr, coordinator=promoter_user)
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=user, phone="11999990002")
    UserRole.objects.create(user=user, role="enrollment")
    Enrollment.objects.create(user=user, promoter=promoter_user, hub=hub)

    roles, statuses = resolve_user_roles_and_statuses(user)
    assert roles == ["student"]
    assert statuses == {"student": "enrollment"}


def test_canonical_roles_resolution_for_promoter_candidate():
    """Promotor candidato deve ter role='promoter' e status='candidate'."""
    coord_user = User.objects.create_user(external_id=uuid.uuid4())
    addr = Address.objects.create(street="Rua 1", number="10", neighborhood="Bairro", city="Cidade", state="SP", zipcode="01001000")
    hub = Hub.objects.create(brand="supletivo", address=addr, coordinator=coord_user)
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=user, phone="11999990003")
    UserRole.objects.create(user=user, role="candidate")
    Candidate.objects.create(user=user, hub=hub)

    roles, statuses = resolve_user_roles_and_statuses(user)
    assert roles == ["promoter"]
    assert statuses == {"promoter": "candidate"}


def test_canonical_roles_resolution_for_admin():
    """Superuser deve ter role='admin' e status='active'."""
    admin_user = User.objects.create_superuser(password="secret")
    roles, statuses = resolve_user_roles_and_statuses(admin_user)
    assert "admin" in roles
    assert statuses["admin"] == "active"


def test_multi_role_user_resolution():
    """Usuário com múltiplas roles (ex: student lead + promoter ativo)."""
    coord_user = User.objects.create_user(external_id=uuid.uuid4())
    addr = Address.objects.create(street="Rua 1", number="10", neighborhood="Bairro", city="Cidade", state="SP", zipcode="01001000")
    hub = Hub.objects.create(brand="supletivo", address=addr, coordinator=coord_user)

    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=user, phone="11999990004")
    UserRole.objects.create(user=user, role="lead")
    UserRole.objects.create(user=user, role="promoter")
    Promoter.objects.create(user=user, hub=hub)

    roles, statuses = resolve_user_roles_and_statuses(user)
    assert "student" in roles
    assert "promoter" in roles
    assert statuses["student"] == "lead"
    assert statuses["promoter"] == "active"


def test_whoami_endpoint_returns_canonical_roles_and_statuses(client):
    """O endpoint /whoami deve expor roles canônicas e role_statuses."""
    promoter_user = User.objects.create_user(external_id=uuid.uuid4())
    user = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=user, phone="11999990005")
    UserRole.objects.create(user=user, role="lead")
    Lead.objects.create(user=user, promoter=promoter_user)

    tokens = jwt_service.issue(str(user.external_id), ["lead"])
    headers = {"HTTP_AUTHORIZATION": f"Bearer {tokens['access_token']}"}

    resp = client.get("/api/v1/clients/whoami", **headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["roles"] == ["student"]
    assert data["role_statuses"] == {"student": "lead"}


def test_admin_and_staff_endpoint_symmetry(client):
    """Tanto /api/v1/admin/ quanto /api/v1/staff/ devem responder igualmente para o superuser."""
    admin_user = User.objects.create_superuser(password="secret")
    tokens = jwt_service.issue(str(admin_user.external_id), [])
    headers = {"HTTP_AUTHORIZATION": f"Bearer {tokens['access_token']}"}

    resp_staff = client.get("/api/v1/staff/leads", **headers)
    resp_admin = client.get("/api/v1/admin/leads", **headers)

    assert resp_staff.status_code == 200
    assert resp_admin.status_code == 200
    assert resp_staff.json() == resp_admin.json()
