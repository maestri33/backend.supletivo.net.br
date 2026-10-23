"""Real persistence, task orchestration and HTTP shape; external services run offline."""
from datetime import date
from io import BytesIO
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from hub.models import Hub
from users.address.models import Address
from users.auth.jwt import service as jwt
from users.auth.models import User
from users.documents import service as documents
from users.profiles.models import Profile
from users.roles.candidate import service, tasks
from users.roles.candidate.models import Candidate
from users.roles.models import UserRole
from users.roles.promoter.models import Promoter

pytestmark = pytest.mark.django_db


@pytest.fixture
def candidate(monkeypatch, settings):
    settings.TRAINING_ENABLED = False
    monkeypatch.setattr("core.tasks.async_task", lambda *args, **kwargs: None)
    monkeypatch.setattr("notify.interface.events.send_event", lambda *args, **kwargs: "offline-event")
    monkeypatch.setattr("integrations.tools.biometric.service.try_enroll_document", lambda **kwargs: None)
    coordinator = User.objects.create_user()
    address = Address.objects.create(street="Rua Teste", number="10", neighborhood="Centro", city="Londrina", state="PR", zipcode="86000000")
    hub = Hub.objects.create(address=address, coordinator=coordinator, brand="standard")
    user = User.objects.create_user()
    Profile.objects.create(user=user, cpf="52998224725", phone=str(uuid.uuid4().int)[:13], name="Offline Candidate", birth_date=date(1990, 1, 1), address=address, education_level="medio", education_completed=True, pix_key="offline@example.test")
    documents.create_empty(user)
    UserRole.objects.create(user=user, role="candidate")
    return Candidate.objects.create(user=user, hub=hub, status=Candidate.Status.DOCUMENTS, doc_type="rg")


def _headers(candidate):
    token = jwt.issue(str(candidate.user.external_id), ["candidate"])["access_token"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _photo():
    output = BytesIO()
    Image.new("RGB", (32, 32), (80, 120, 160)).save(output, format="PNG")
    return SimpleUploadedFile("document.png", output.getvalue(), content_type="image/png")


@pytest.mark.parametrize("doc_type", ["rg", "cnh"])
def test_document_http_section_uses_stored_analysis(client, candidate, doc_type):
    candidate.doc_type = doc_type
    candidate.save(update_fields=["doc_type"])
    sub = documents.get_doc_sub(str(candidate.user.external_id), doc_type)
    sub.number = "123456"
    sub.full_photo = "documents/offline.png"
    sub.validation_status = "approved"
    sub.validation_result = {"photos": {f"{doc_type}_full": {"status": "approved"}}, "extracted": {"number": "123456", "mother_name": "Offline Mother"}}
    sub.save()

    response = client.get("/api/v1/collaborators/candidate/document", **_headers(candidate))

    assert response.status_code == 200
    section = response.json()
    assert section["photos"][f"{doc_type}_full"]["status"] == "approved"
    assert section["extracted"]["mother_name"] == "Offline Mother"
    assert section["next_slot"] is None
    assert section["missing_fields"] == []
    assert "validation_result" not in section


def test_front_task_exposes_back_as_next_upload(client, candidate, monkeypatch):
    monkeypatch.setattr("users.roles._document_ai.fix_orientation", lambda *args, **kwargs: None)
    monkeypatch.setattr("users.roles._document_ai.check_photo", lambda *args, **kwargs: ("approved", "Offline readable front"))
    service.upload_document_photo(user_external_id=str(candidate.user.external_id), slot="rg_front", upload=_photo())

    waiting = client.get("/api/v1/collaborators/candidate/document", **_headers(candidate)).json()
    assert waiting["photos"]["rg_front"]["status"] == "pending"
    assert waiting["next_slot"] == "rg_back"

    tasks.validate_document(candidate.pk, "rg_front")

    response = client.get("/api/v1/collaborators/candidate/document", **_headers(candidate))
    assert response.status_code == 200
    assert response.json()["photos"]["rg_front"]["status"] == "approved"
    assert response.json()["next_slot"] == "rg_back"


@pytest.mark.parametrize("doc_type", ["rg", "cnh"])
def test_approved_task_fills_identity_advances_and_completes_registration(candidate, monkeypatch, doc_type):
    candidate.doc_type = doc_type
    candidate.save(update_fields=["doc_type"])
    monkeypatch.setattr("users.roles._document_ai.fix_orientation", lambda *args, **kwargs: None)
    monkeypatch.setattr("users.roles._document_ai.check_photo", lambda *args, **kwargs: ("approved", "Offline readable document"))
    monkeypatch.setattr("users.roles._document_ai.ocr_images", lambda *args, **kwargs: "Offline document text")
    profile = Profile.objects.get(user=candidate.user)
    monkeypatch.setattr("users.roles._document_ai.read_identity_images", lambda *args, **kwargs: {"number": "00123456789" if doc_type == "cnh" else "123456", "category": "AB" if doc_type == "cnh" else None, "mother_name": "Offline Mother", "name": "Offline Candidate", "cpf": profile.cpf, "birth_date": "1990-01-01", "name_match": "sim"})
    service.upload_document_photo(user_external_id=str(candidate.user.external_id), slot=f"{doc_type}_full", upload=_photo())
    tasks.validate_document(candidate.pk, f"{doc_type}_full")

    candidate.refresh_from_db()
    assert candidate.status == Candidate.Status.PIX
    assert documents.get_doc_sub(str(candidate.user.external_id), doc_type).validation_status == "approved"
    assert Profile.objects.get(user=candidate.user).mother_name == "Offline Mother"

    proof = documents.get_address_proof(str(candidate.user.external_id))
    proof.validation_status = "approved"
    proof.save(update_fields=["validation_status"])
    candidate.status = Candidate.Status.COMPLETED
    candidate.pix_validated = True
    candidate.selfie_status = "approved"
    candidate.selfie_verified = True
    candidate.consent_accepted = True
    candidate.consent_accepted_at = timezone.now()
    candidate.save()
    sub = documents.get_doc_sub(str(candidate.user.external_id), doc_type)

    service._doc_post_approval(candidate, sub)

    candidate.refresh_from_db()
    assert candidate.status == Candidate.Status.APPROVED
    assert Promoter.objects.get(user=candidate.user).status == Promoter.Status.ACTIVE


@pytest.mark.parametrize("doc_type", ["rg", "cnh"])
def test_old_ocr_cannot_finish_a_new_upload_generation(candidate, monkeypatch, doc_type):
    candidate.doc_type = doc_type
    candidate.save(update_fields=["doc_type"])
    monkeypatch.setattr("users.roles._document_ai.fix_orientation", lambda *args, **kwargs: None)
    monkeypatch.setattr("users.roles._document_ai.check_photo", lambda *args, **kwargs: ("approved", "Readable"))
    monkeypatch.setattr("users.roles._document_ai.ocr_images", lambda *args, **kwargs: "Document text")
    profile = Profile.objects.get(user=candidate.user)
    def interrupted_extraction(*args, **kwargs):
        service.upload_document_photo(user_external_id=str(candidate.user.external_id), slot=f"{doc_type}_full", upload=_photo())
        return {"number": "OLD-OCR", "name": profile.name, "cpf": profile.cpf, "birth_date": "1990-01-01", "mother_name": "Must Not Be Applied"}
    monkeypatch.setattr("users.roles._document_ai.read_identity_images", interrupted_extraction)
    service.upload_document_photo(user_external_id=str(candidate.user.external_id), slot=f"{doc_type}_full", upload=_photo())
    tasks.validate_document(candidate.pk, f"{doc_type}_full")
    sub = documents.get_doc_sub(str(candidate.user.external_id), doc_type)
    assert sub.validation_status == "pending"
    assert not sub.number
    assert not Profile.objects.get(user=candidate.user).mother_name


def test_new_pair_does_not_reuse_an_old_full_approval(candidate):
    sub = documents.get_doc_sub(str(candidate.user.external_id), "rg")
    sub.full_photo = "documents/old.png"
    sub.validation_status = "rejected"
    sub.validation_result = {"photos": {"rg_full": {"status": "approved"}}}
    sub.save()
    service.upload_document_photo(user_external_id=str(candidate.user.external_id), slot="rg_front", upload=_photo())
    sub.refresh_from_db()
    assert not sub.full_photo
    assert "rg_full" not in sub.validation_result["photos"]


@pytest.mark.parametrize("doc_type", ["rg", "cnh"])
def test_old_failed_read_cannot_overwrite_new_upload(candidate, monkeypatch, doc_type):
    candidate.doc_type = doc_type
    candidate.save(update_fields=["doc_type"])
    monkeypatch.setattr("users.roles._document_ai.fix_orientation", lambda *args, **kwargs: None)
    monkeypatch.setattr("users.roles._document_ai.check_photo", lambda *args, **kwargs: ("approved", "Readable"))
    def interrupted_read(*args, **kwargs):
        service.upload_document_photo(user_external_id=str(candidate.user.external_id), slot=f"{doc_type}_full", upload=_photo())
        raise TimeoutError("Old worker")
    monkeypatch.setattr("users.roles._document_ai.read_identity_images", interrupted_read)
    service.upload_document_photo(user_external_id=str(candidate.user.external_id), slot=f"{doc_type}_full", upload=_photo())
    tasks.validate_document(candidate.pk, f"{doc_type}_full")
    sub = documents.get_doc_sub(str(candidate.user.external_id), doc_type)
    assert sub.validation_status == "pending"
    assert not sub.validation_result.get("extracted")


def test_post_review_fill_cannot_apply_previous_document(candidate, monkeypatch):
    from users.roles.candidate.documents_ai import run_document_fill
    service.upload_document_photo(user_external_id=str(candidate.user.external_id), slot="rg_full", upload=_photo())
    sub = documents.get_doc_sub(str(candidate.user.external_id), "rg")
    sub.validation_status = "approved"
    sub.validation_result["photos"] = {"rg_full": {"status": "approved"}}
    sub.save()
    def interrupted_read(*args, **kwargs):
        service.upload_document_photo(user_external_id=str(candidate.user.external_id), slot="rg_full", upload=_photo())
        return {"number": "OLD-READ", "name": "Offline Candidate", "cpf": "52998224725", "birth_date": "1990-01-01", "mother_name": "Must Not Be Applied"}
    monkeypatch.setattr("users.roles._document_ai.read_identity_images", interrupted_read)
    run_document_fill(candidate.pk)
    sub.refresh_from_db()
    assert sub.validation_status == "pending"
    assert not sub.number
    assert not sub.validation_result.get("extracted")
    assert not Profile.objects.get(user=candidate.user).mother_name


@pytest.mark.parametrize("approve", [True, False])
def test_coordinator_document_review_returns_registration(candidate, approve):
    sub = documents.get_doc_sub(str(candidate.user.external_id), "rg")
    sub.validation_status = "review"
    sub.full_photo = "documents/offline.png"
    sub.validation_result = {"extracted": {"number": "987654", "mother_name": "Offline Mother"}}
    sub.save()

    result = service.decide_document(candidate_external_id=str(candidate.external_id), coordinator=candidate.hub.coordinator, approve=approve, reason="Offline coordinator decision")

    sub.refresh_from_db()
    assert result["external_id"] == str(candidate.external_id)
    assert sub.validation_status == ("approved" if approve else "rejected")
    if approve:
        assert result["status"] == Candidate.Status.PIX
        assert sub.number == "987654"
    else:
        assert result["status"] == Candidate.Status.DOCUMENTS
