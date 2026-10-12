"""Persist renewed CNH credentials only after source and identity checks."""
from datetime import date
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from hub.models import Hub
from users.address.models import Address
from users.auth.models import User
from users.documents import service as documents
from users.profiles.models import Profile
from users.roles.candidate import service, tasks
from users.roles.candidate.models import Candidate
from users.roles.models import UserRole

pytestmark = pytest.mark.django_db


def extracted(**changes):
    return {
        "name": "Offline Candidate", "cpf": "52998224725", "cpf_present": True,
        "birth_date": "1990-01-01", "number": "00123456789", "category": "AB",
        "national_register": None, "expires_on": "2035-02-03",
        "mother_name": "New OCR Mother", "father_name": "New OCR Father",
        "birthplace": "New OCR City", **changes,
    }


@pytest.fixture
def candidate(monkeypatch):
    monkeypatch.setattr("core.tasks.async_task", lambda *args, **kwargs: None)
    monkeypatch.setattr("notify.interface.events.send_event", lambda *args, **kwargs: "offline-event")
    monkeypatch.setattr("integrations.tools.biometric.service.try_enroll_document", lambda **kwargs: None)
    monkeypatch.setattr("users.roles._document_ai.fix_orientation", lambda *args, **kwargs: None)
    monkeypatch.setattr("users.roles._document_ai.check_photo", lambda *args, **kwargs: ("approved", "Offline readable document"))
    monkeypatch.setattr("users.roles._document_ai.read_identity_images", lambda *args, **kwargs: extracted())
    coordinator = User.objects.create_user()
    address = Address.objects.create(street="Rua Teste", number="10", neighborhood="Centro", city="Londrina", state="PR", zipcode="86000000")
    hub = Hub.objects.create(address=address, coordinator=coordinator, brand="standard")
    user = User.objects.create_user()
    Profile.objects.create(user=user, cpf="52998224725", phone="5543999999999", name="Offline Candidate", birth_date=date(1990, 1, 1), mother_name="Original Mother", father_name="Original Father", birthplace="Original City")
    documents.create_empty(user)
    UserRole.objects.create(user=user, role="candidate")
    cand = Candidate.objects.create(user=user, hub=hub, status=Candidate.Status.DOCUMENTS, doc_type="cnh")
    sub = documents.get_doc_sub(str(user.external_id), "cnh")
    sub.number = "1234567 SESP/PR"
    sub.category = "E"
    sub.national_register = "00123456789"
    sub.expires_on = date(2030, 2, 3)
    sub.date_of_birth = date(1990, 1, 1)
    sub.validation_status = "approved"
    sub.full_photo = "documents/previous.png"
    sub.save()
    return cand


def profile_values(candidate):
    return Profile.objects.filter(user=candidate.user).values().get()


def reupload(candidate):
    output = BytesIO()
    Image.new("RGB", (32, 32), (80, 120, 160)).save(output, "PNG")
    slot = f"{candidate.doc_type}_full"
    service.upload_document_photo(user_external_id=str(candidate.user.external_id), slot=slot, upload=SimpleUploadedFile("document.png", output.getvalue(), content_type="image/png"))
    tasks.validate_document(candidate.pk, slot)
    return service.get_document_section(user_external_id=str(candidate.user.external_id))


def test_cnh_reupload_replaces_old_credentials_without_changing_profile(candidate):
    before = profile_values(candidate)

    section = reupload(candidate)

    assert section["analysis_status"] == "approved"
    assert section["number"] == "00123456789"
    assert section["category"] == "AB"
    assert section["national_register"] is None
    assert section["extracted"]["number"] == section["number"]
    assert section["extracted"]["category"] == section["category"]
    assert section["expires_on"] == "2030-02-03"
    assert profile_values(candidate) == before


@pytest.mark.parametrize("changes", [
    {"name": "Different Holder"}, {"cpf": "11144477735"}, {"birth_date": "1991-01-01"},
])
def test_cnh_identity_mismatch_cannot_replace_credentials_or_profile(candidate, monkeypatch, changes):
    before = profile_values(candidate)
    monkeypatch.setattr("users.roles._document_ai.read_identity_images", lambda *args, **kwargs: extracted(**changes))

    section = reupload(candidate)

    assert section["analysis_status"] == "rejected"
    assert (section["number"], section["category"], section["national_register"]) == ("1234567 SESP/PR", "E", "00123456789")
    assert profile_values(candidate) == before


@pytest.mark.parametrize("old_register,expected", [
    ("00123456789", None), ("INVALID", None), ("PR123456789", "PR123456789"), (None, None),
])
def test_uncertain_new_renach_clears_only_invalid_previous_values(candidate, old_register, expected):
    sub = documents.get_doc_sub(str(candidate.user.external_id), "cnh")
    sub.national_register = old_register
    sub.save(update_fields=["national_register"])

    section = reupload(candidate)

    assert section["number"] == "00123456789"
    assert section["national_register"] == expected


def test_valid_new_renach_replaces_previous_read(candidate, monkeypatch):
    sub = documents.get_doc_sub(str(candidate.user.external_id), "cnh")
    sub.national_register = "PR123456789"
    sub.save(update_fields=["national_register"])
    monkeypatch.setattr("users.roles._document_ai.read_identity_images", lambda *args, **kwargs: extracted(national_register="SP123456789"))

    assert reupload(candidate)["national_register"] == "SP123456789"


@pytest.mark.parametrize("stage", ["decision", "fill"])
@pytest.mark.parametrize("changes", [
    {"number": "1234567 SESP/PR"}, {"number": "123456"},
    {"category": "ZZ"}, {"category": None}, {"name": "Different Holder"},
])
def test_human_approval_cannot_auto_fill_unverified_historical_cnh(candidate, stage, changes):
    profile = Profile.objects.get(user=candidate.user)
    profile.mother_name = None
    profile.save(update_fields=["mother_name"])
    before = profile_values(candidate)
    sub = documents.get_doc_sub(str(candidate.user.external_id), "cnh")
    sub.number = None
    sub.category = None
    sub.validation_status = "review" if stage == "decision" else "approved"
    sub.validation_result = {"extracted": extracted(**changes)}
    sub.save()

    if stage == "decision":
        service.decide_document(candidate_external_id=str(candidate.external_id), coordinator=candidate.hub.coordinator, approve=True)
    else:
        tasks.fill_document_data(candidate.pk)

    sub.refresh_from_db()
    assert sub.validation_status == "approved"
    assert sub.number is None
    assert sub.category is None
    assert sub.national_register == "00123456789"
    assert profile_values(candidate) == before


def test_rg_reupload_retains_existing_document_fields(candidate):
    candidate.doc_type = "rg"
    candidate.save(update_fields=["doc_type"])
    sub = documents.get_doc_sub(str(candidate.user.external_id), "rg")
    sub.number = "Original RG Number"
    sub.issuing_agency = "Original Agency"
    sub.issue_date = date(2000, 1, 1)
    sub.save()
    before = profile_values(candidate)

    section = reupload(candidate)

    assert section["analysis_status"] == "approved"
    assert section["number"] == "Original RG Number"
    assert section["issuing_agency"] == "Original Agency"
    assert section["issue_date"] == "2000-01-01"
    assert profile_values(candidate) == before
