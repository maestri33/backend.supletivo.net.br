"""Free registration, immediate referrals and activation after approved checks."""
import uuid
from datetime import date

import pytest
from django.utils import timezone

from hub.models import Hub
from users.address.models import Address
from users.auth.models import User
from users.documents import service as documents
from users.profiles.models import Profile
from users.roles.candidate import service
from users.roles.candidate.models import Candidate
from users.roles.models import UserRole
from users.roles.promoter import service as promoters
from users.roles.promoter.models import Promoter

pytestmark = pytest.mark.django_db


@pytest.fixture
def candidate(monkeypatch, settings):
    settings.TRAINING_ENABLED = False
    from notify.interface import events
    monkeypatch.setattr(events, "send_event", lambda *args, **kwargs: "offline-event")
    coordinator = User.objects.create_user()
    address = Address.objects.create(zipcode="84050360", street="Rua de teste", number="1", neighborhood="Centro", city="Ponta Grossa", state="PR")
    hub = Hub.objects.create(address=address, coordinator=coordinator, brand="standard")
    user = User.objects.create_user()
    Profile.objects.create(user=user, cpf=str(uuid.uuid4().int)[:11], name="Offline Candidate", phone=str(uuid.uuid4().int)[:13], birth_date=date(1990, 1, 1), address=address, pix_key="offline@example.test", pix_key_type="EMAIL", education_level="medio", education_completed=True)
    UserRole.objects.create(user=user, role="candidate")
    documents.create_empty(user)
    documents.get_doc_sub(str(user.external_id), "rg").__class__.objects.filter(document__user=user).update(validation_status="approved")
    proof = documents.get_address_proof(str(user.external_id))
    proof.validation_status = "approved"
    proof.save(update_fields=["validation_status"])
    return Candidate.objects.create(user=user, hub=hub, status=Candidate.Status.SELFIE, doc_type="rg", pix_validated=True, selfie_verified=True, selfie_status="approved", consent_accepted=True, consent_accepted_at=timezone.now())


def test_candidate_can_refer_immediately_and_receive_backend_discount(candidate, client):
    candidate.status = Candidate.Status.STARTED
    candidate.save(update_fields=["status"])
    assert promoters.validate_ref(str(candidate.user.external_id)) == candidate.user
    response = client.get(f"/api/v1/clients/pricing?ref={candidate.user.external_id}")
    assert response.status_code == 200
    assert response.json()["has_discount"] is True
    assert response.json()["promo_pix"] == "999.00"
    assert not Promoter.objects.exists()


def test_approved_complete_registration_activates_without_creating_training(candidate):
    from users.roles.training.models import Material, MaterialAssignment
    Material.objects.create(title="Deferred LMS", question="Offline", expected_answer="Offline", active=True, blocking=True)
    service._complete_candidate(candidate)
    service._complete_candidate(candidate)
    candidate.refresh_from_db()
    assert candidate.status == Candidate.Status.APPROVED
    assert Promoter.objects.get(user=candidate.user).status == Promoter.Status.ACTIVE
    assert not MaterialAssignment.objects.exists()
    assert not UserRole.objects.filter(user=candidate.user, role="training", revoked_at__isnull=True).exists()


@pytest.mark.parametrize("missing", ["pix", "address", "identity", "consent", "education"])
def test_approval_does_not_skip_incomplete_registration(candidate, missing):
    if missing == "pix":
        Candidate.objects.filter(pk=candidate.pk).update(pix_validated=False)
    elif missing == "address":
        Address.objects.filter(pk=candidate.user.profile.address_id).update(number=None)
    elif missing == "identity":
        Profile.objects.filter(user=candidate.user).update(birth_date=None)
    elif missing == "consent":
        Candidate.objects.filter(pk=candidate.pk).update(consent_accepted=False)
    else:
        Profile.objects.filter(user=candidate.user).update(education_level=None)
    candidate.refresh_from_db()
    service._complete_candidate(candidate)
    assert not Promoter.objects.filter(user=candidate.user).exists()


def test_five_selfie_rejections_cannot_bypass_identity_approval(candidate):
    candidate.selfie_verified = False
    candidate.selfie_status = "rejected"
    candidate.selfie_reject_count = 5
    candidate.save(update_fields=["selfie_verified", "selfie_status", "selfie_reject_count"])
    service._complete_candidate(candidate)
    assert not Promoter.objects.exists()


def test_candidate_api_exposes_referral_link_before_identity_approval(candidate, client):
    from users.auth.jwt import service as jwt
    candidate.status = Candidate.Status.STARTED
    candidate.selfie_verified = False
    candidate.save(update_fields=["status", "selfie_verified"])
    token = jwt.issue(str(candidate.user.external_id), ["candidate"])["access_token"]
    response = client.get("/api/v1/collaborators/candidate/me", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert response.status_code == 200
    assert f"ref={candidate.user.external_id}" in response.json()["ref_url"]
    assert "selfie" in response.json()["missing_requirements"]


def test_paid_referral_uses_candidates_hub_and_retains_commission(candidate):
    from finance.interface.commissions import next_closing_at, run_weekly_closing
    from finance.models import Commission, PaymentRequest
    from users.roles.enrollment.models import Enrollment
    from users.roles.lead.models import Lead, Checkout
    from users.roles.lead.service import mark_paid
    candidate.status = Candidate.Status.STARTED
    candidate.save(update_fields=["status"])
    student = User.objects.create_user()
    Profile.objects.create(user=student, phone=str(uuid.uuid4().int)[:13], name="Offline Student")
    UserRole.objects.create(user=student, role="lead")
    documents.create_empty(student)
    lead = Lead.objects.create(user=student, promoter=candidate.user)
    checkout = Checkout.objects.create(lead=lead, provider="asaas", provider_payment_id="offline-candidate-sale", amount=999)
    assert mark_paid(provider="asaas", provider_payment_id=checkout.provider_payment_id)
    assert Enrollment.objects.get(user=student).hub == candidate.hub
    run_weekly_closing(reference_date=next_closing_at())
    assert Commission.objects.get(payee=candidate.user).status == Commission.Status.PENDING
    assert not PaymentRequest.objects.exists()


def test_fifth_selfie_rejection_enters_human_review_without_activating(candidate):
    candidate.selfie_status = "rejected"
    candidate.selfie_verified = False
    candidate.selfie_reject_count = 5
    candidate.save(update_fields=["selfie_status", "selfie_verified", "selfie_reject_count"])
    service._resolve_selfie(candidate)
    candidate.refresh_from_db()
    assert candidate.selfie_status == "review"
    assert not Promoter.objects.exists()


def test_deferred_training_overlay_does_not_hide_the_active_environment(candidate):
    from users.roles.service import resolve_user_roles_and_statuses
    Promoter.objects.create(user=candidate.user, hub=candidate.hub)
    UserRole.objects.create(user=candidate.user, role="training")
    _, statuses = resolve_user_roles_and_statuses(candidate.user)
    assert statuses["promoter"] == "active"
