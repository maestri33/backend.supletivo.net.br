"""Address extraction must only settle the upload that actually started it."""
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.utils import timezone

from users.auth.models import User
from users.address.models import Address
from users.documents import service as documents
from users.profiles.models import Profile
from users.roles import _address_proof as proof_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def proof_user():
    user = User.objects.create_user()
    Profile.objects.create(user=user, name="Maria Silva", address=Address.objects.create())
    documents.create_empty(user)
    proof = documents.get_address_proof(str(user.external_id))
    source = "documents/address-original.png"
    path = Path(settings.MEDIA_ROOT) / source
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"original source")
    proof.photo = source
    proof.validation_result = {"analysis_started_at": timezone.now().isoformat()}
    proof.save()
    return user, proof


@pytest.mark.parametrize("change", ["source", "generation", "decision"])
def test_late_ocr_cannot_replace_new_upload_or_coordinator_decision(proof_user, monkeypatch, change):
    user, proof = proof_user

    def extraction(*args, **kwargs):
        proof.refresh_from_db()
        if change == "source":
            proof.photo = "documents/replacement.png"
        elif change == "generation":
            proof.validation_result = {"analysis_started_at": timezone.now().isoformat()}
        else:
            proof.validation_status = "rejected"
            proof.validation_result = {"needs_new_proof": True}
        proof.save()
        return "approved", {"extracted": {"street": "Old street"}, "reason": "ok"}

    monkeypatch.setattr(proof_service, "run_validation", extraction)
    proof_service.validate_and_store(str(user.external_id), caller="enrollment.address_proof")
    proof.refresh_from_db()
    assert proof.validation_status != "approved"
    assert Profile.objects.get(user=user).address.street is None


def test_finished_proof_is_not_analysed_again(proof_user, monkeypatch):
    user, proof = proof_user
    proof.validation_status = "approved"
    proof.save()
    monkeypatch.setattr(proof_service, "run_validation", lambda *a, **k: pytest.fail("Finished verdict must be preserved"))
    assert proof_service.validate_and_store(str(user.external_id), caller="candidate.address_proof") == "approved"


def test_expired_address_analysis_becomes_review(proof_user, settings):
    settings.ANALYSIS_TTL_SECONDS = 120
    user, proof = proof_user
    proof.validation_result = {"analysis_started_at": (timezone.now() - timedelta(seconds=121)).isoformat()}
    proof.save()
    section = proof_service.section_dict(str(user.external_id))
    assert section["status"] == "review"
    proof.refresh_from_db()
    assert proof.validation_status == "review"


def test_live_address_analysis_exposes_poll_contract(proof_user):
    user, proof = proof_user
    section = proof_service.section_dict(str(user.external_id))
    assert section["status"] == "pending"
    assert section["poll_after_ms"] > 0
    assert section["expires_at"]


def test_kinship_for_old_upload_cannot_approve_replacement(proof_user, monkeypatch):
    from integrations.ai import service as ai
    user, proof = proof_user
    proof.validation_status = "needs_kinship"
    proof.save()

    def explanation(*args, **kwargs):
        proof.photo = "documents/new.png"
        proof.validation_status = "pending"
        proof.validation_result = {"analysis_started_at": timezone.now().isoformat()}
        proof.save()
        return {"has_merit": True, "corrected": "Cônjuge"}

    monkeypatch.setattr(ai, "evaluate_kinship", explanation)
    assert proof_service.submit_kinship(str(user.external_id), "Cônjuge") == "pending"
    proof.refresh_from_db()
    assert proof.kinship_relation is None


def test_complete_address_changed_during_ocr_is_checked_again(proof_user, monkeypatch):
    user, proof = proof_user

    def extraction(*args, **kwargs):
        address = Profile.objects.get(user=user).address
        address.zipcode = "01001000"
        address.street = "Updated street"
        address.number = "10"
        address.city = "São Paulo"
        address.state = "SP"
        address.save()
        return "approved", {"extracted": {"zip": "86000000", "city": "Londrina"}}

    monkeypatch.setattr(proof_service, "run_validation", extraction)
    monkeypatch.setattr("notify.interface.events.send_event", lambda *a, **k: None)
    assert proof_service.validate_and_store(str(user.external_id), caller="enrollment.address_proof") == "rejected"
    proof.refresh_from_db()
    assert proof.validation_status == "rejected"


def test_address_pipeline_reserves_time_for_json_and_bounds_ocr(monkeypatch):
    from users.roles.student import _document_ai as doc_ai
    import time
    calls = {}
    def vision(*args, **kwargs):
        calls["vision"] = kwargs["timeout"]
        return "approved", "ok"
    def ocr(*args, **kwargs):
        calls["ocr_remaining"] = kwargs["deadline"] - time.monotonic()
        return "text"
    def extract(*args, **kwargs):
        calls["json"] = kwargs["timeout"]
        return {"name_match": "sim"}
    monkeypatch.setattr(doc_ai, "check_student_document_photo", vision)
    monkeypatch.setattr(doc_ai, "ocr_image", ocr)
    monkeypatch.setattr(doc_ai, "extract_student_document", extract)
    proof_service.run_validation(b"test", address=None, holder_name="Maria Silva", caller="test")
    assert 0 < calls["vision"] <= 30
    assert 0 < calls["ocr_remaining"] <= 160
    assert 0 < calls["json"] <= 20
