"""Self-document access uses the authenticated identity and exposes no analysis internals."""
import pytest

from hub.models import Hub
from users.address.models import Address
from users.auth.jwt import service as jwt
from users.auth.models import User
from users.documents import service as documents
from users.roles.candidate.models import Candidate
from users.roles.models import UserRole
from users.roles.promoter.models import Promoter

pytestmark = pytest.mark.django_db


def _collaborator():
    user = User.objects.create_user()
    hub = Hub.objects.create(address=Address.objects.create(city="Londrina", state="PR"), brand="standard")
    documents.create_empty(user)
    Candidate.objects.create(user=user, hub=hub, doc_type="rg", status="approved", selfie_image=f"selfies/{user.external_id}.jpg", selfie_status="approved", contract_version="offline-v1", contract_hash="offline-hash")
    UserRole.objects.create(user=user, role="promoter")
    Promoter.objects.create(user=user, hub=hub)
    rg = documents.get_rg(str(user.external_id))
    rg.full_photo = f"documents/{user.external_id}/rg.jpg"
    rg.validation_status = "approved"
    rg.validation_result = {"internal": "not-public"}
    rg.save()
    return user


def test_archive_is_authenticated(client):
    response = client.get("/api/v1/collaborators/promoter/documents")
    assert response.status_code == 401


def test_archive_ignores_another_identity_and_lists_only_self(client):
    owner = _collaborator()
    other = _collaborator()
    token = jwt.issue(str(owner.external_id), ["promoter"])["access_token"]

    response = client.get(f"/api/v1/collaborators/promoter/documents?user_external_id={other.external_id}", HTTP_AUTHORIZATION=f"Bearer {token}")

    assert response.status_code == 200
    body = response.json()
    assert len(body["documents"]) == 2
    assert str(owner.external_id) in body["documents"][0]["path"]
    assert str(other.external_id) not in str(body)
    assert body["contract_version"] == "offline-v1"
    assert "internal" not in str(body)


def test_student_cannot_read_promoter_archive(client):
    user = User.objects.create_user()
    token = jwt.issue(str(user.external_id), ["student"])["access_token"]
    response = client.get("/api/v1/collaborators/promoter/documents", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 403
