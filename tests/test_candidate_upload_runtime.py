"""Exercise actual candidate upload services behind authenticated HTTP routes."""

from io import BytesIO
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from hub.models import Hub
from users.address.models import Address
from users.auth.jwt import service as jwt
from users.auth.models import User
from users.documents import service as documents
from users.profiles.models import Profile
from users.roles.candidate import service
from users.roles.candidate.models import Candidate
from users.roles.models import UserRole

pytestmark = pytest.mark.django_db


def _png():
    output = BytesIO()
    Image.new("RGB", (32, 32), (80, 120, 160)).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def candidate():
    address = Address.objects.create(
        street="Rua Teste", number="10", neighborhood="Centro",
        city="Londrina", state="PR", zipcode="86000000",
    )
    hub = Hub.objects.create(address=address, brand="standard")
    user = User.objects.create_user()
    Profile.objects.create(user=user, phone="5511999990001", address=address)
    documents.create_empty(user)
    UserRole.objects.create(user=user, role="candidate")
    return Candidate.objects.create(user=user, hub=hub, status=Candidate.Status.PROFILE)


def _headers(candidate):
    tokens = jwt.issue(str(candidate.user.external_id), ["candidate"])
    return {"HTTP_AUTHORIZATION": f"Bearer {tokens['access_token']}"}


def test_candidate_address_proof_http_upload_persists_photo(client, candidate, monkeypatch):
    queued = []
    monkeypatch.setattr("core.tasks.async_task", lambda name, pk: queued.append((name, pk)))

    response = client.post(
        "/api/v1/collaborators/candidate/documents/address-proof",
        {"file": SimpleUploadedFile("proof.png", _png(), content_type="image/png")},
        **_headers(candidate),
    )

    assert response.status_code == 200
    proof = documents.get_address_proof(str(candidate.user.external_id))
    assert proof.validation_status == "pending"
    assert Path(settings.MEDIA_ROOT, proof.photo).is_file()
    assert queued == [("users.roles.candidate.tasks.validate_address_proof", candidate.pk)]


def test_candidate_selfie_http_upload_persists_photo_and_consent(client, candidate, monkeypatch):
    queued = []
    monkeypatch.setattr("core.tasks.async_task", lambda name, pk: queued.append((name, pk)))
    candidate.status = Candidate.Status.EDUCATION
    candidate.save(update_fields=["status"])
    photo = _png()

    response = client.post(
        "/api/v1/collaborators/candidate/selfie",
        {"file": SimpleUploadedFile("selfie.png", photo, content_type="image/png")},
        **_headers(candidate),
    )

    assert response.status_code == 200
    assert response.json()["stored"] is True
    assert response.json()["analysis_status"] == "pending"
    candidate.refresh_from_db()
    assert candidate.status == Candidate.Status.SELFIE
    assert candidate.selfie_status == "pending"
    assert candidate.consent_accepted is True
    assert candidate.contract_hash
    assert candidate.selfie_image.endswith(".png")
    assert Path(settings.MEDIA_ROOT, candidate.selfie_image).read_bytes() == photo
    assert queued == [("users.roles.candidate.tasks.validate_candidate_selfie", candidate.pk)]


def test_candidate_kinship_http_updates_proof_and_advances_address(client, candidate, monkeypatch):
    proof = documents.get_address_proof(str(candidate.user.external_id))
    proof.validation_status = "needs_kinship"
    proof.save(update_fields=["validation_status"])
    monkeypatch.setattr(
        "integrations.ai.service.evaluate_kinship",
        lambda relation, **kwargs: {"has_merit": True, "corrected": "Minha mãe"},
    )

    response = client.post(
        "/api/v1/collaborators/candidate/documents/address-proof/kinship",
        {"relation": "Minha mãe"}, content_type="application/json",
        **_headers(candidate),
    )

    assert response.status_code == 200
    proof.refresh_from_db()
    candidate.refresh_from_db()
    assert proof.validation_status == "approved"
    assert proof.kinship_relation == "Minha mãe"
    assert candidate.status == Candidate.Status.ADDRESS


def test_candidate_address_proof_task_advances_complete_address(candidate):
    # A task whose proof was removed must still resolve its existing candidate
    # and address safely; the validation layer returns without external I/O.
    service.run_address_proof_validation(candidate.pk)
    candidate.refresh_from_db()
    assert candidate.status == Candidate.Status.ADDRESS
