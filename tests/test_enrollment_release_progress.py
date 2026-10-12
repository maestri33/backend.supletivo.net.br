import uuid

import pytest

from users.roles.enrollment import service


@pytest.fixture
def enrollment(db):
    from hub.models import Hub
    from users.address.models import Address
    from users.auth.models import User
    from users.roles.enrollment.models import Enrollment

    coordinator = User.objects.create_user(external_id=uuid.uuid4())
    user = User.objects.create_user(external_id=uuid.uuid4())
    hub = Hub.objects.create(address=Address.objects.create(city="Curitiba", state="PR"), brand="standard", coordinator=coordinator)
    return Enrollment.objects.create(user=user, promoter=coordinator, hub=hub, status="awaiting_release", selfie_status="approved", selfie_verified=True, consent_accepted=True)


def progress(enrollment, monkeypatch, *, first=False, second=False, rg="approved", address="approved"):
    from users.roles.enrollment.release_progress import release_dict

    monkeypatch.setattr(service, "fee_facts", lambda _: {"first_paid": first, "second_scheduled": second})
    return release_dict(enrollment, rg_status=rg, address_proof_status=address)


@pytest.mark.parametrize("status", ["pending", "review", "rejected", None])
def test_unapproved_selfie_never_claims_partner_setup(enrollment, monkeypatch, status):
    enrollment.selfie_status = status
    enrollment.selfie_verified = False
    data = progress(enrollment, monkeypatch)
    assert data["stage"] == "document_review"
    assert data["action_required"] is False


@pytest.mark.parametrize("kind", ["rg", "address"])
def test_rejected_document_is_reviewed_without_broken_upload_route(enrollment, monkeypatch, kind):
    data = progress(enrollment, monkeypatch, **{kind: "rejected"})
    assert data["stage"] == "document_review"
    assert data["action_required"] is False
    assert data["action_route"] is None


@pytest.mark.parametrize("first,second,stage", [(False, False, "partner_setup"), (False, True, "partner_setup"), (True, False, "access_preparation"), (True, True, "access_preparation")])
def test_progress_uses_facts_without_exposing_internal_fees(enrollment, monkeypatch, first, second, stage):
    data = progress(enrollment, monkeypatch, first=first, second=second)
    assert data["stage"] == stage
    assert data["payment_confirmed"] is False
    assert data["hub_name"] == "Polo responsável"
    assert data["contact_url"] is None
    assert data["action_required"] is False
    assert not ({"fees", "amount", "password", "cpf", "first_paid", "second_scheduled"} & data.keys())


def test_completed_enrollment_is_ready(enrollment, monkeypatch):
    enrollment.status = "completed"
    data = progress(enrollment, monkeypatch)
    assert data["stage"] == "ready"


def test_wizard_before_release_has_no_progress(enrollment, monkeypatch):
    enrollment.status = "rg"
    assert progress(enrollment, monkeypatch) is None


def test_real_checkout_confirms_payment_without_assuming_every_enrollment_paid(enrollment, monkeypatch):
    from users.roles.lead.models import Checkout, Lead

    lead = Lead.objects.create(user=enrollment.user, promoter=enrollment.promoter, status="paid")
    Checkout.objects.create(lead=lead, payment_method="pix", amount="1.01", is_paid=True)
    assert progress(enrollment, monkeypatch)["payment_confirmed"] is True


def test_missing_coordinator_and_payment_keep_unknown_facts_unknown(enrollment, monkeypatch):
    enrollment.hub.coordinator = None
    data = progress(enrollment, monkeypatch)
    assert data["coordinator_name"] is None
    assert data["contact_url"] is None
    assert data["payment_confirmed"] is False


def test_contact_uses_manager_of_assigned_hub(enrollment, monkeypatch):
    import uuid
    from users.models import User
    from users.profiles.models import Profile

    Profile.objects.create(user=enrollment.hub.coordinator, name="Coordenadora do polo", phone="5541999990001")
    promoter = User.objects.create_user(external_id=uuid.uuid4())
    Profile.objects.create(user=promoter, name="Promotor", phone="5541999990002")
    enrollment.promoter = promoter
    data = progress(enrollment, monkeypatch)
    assert data["coordinator_name"] == "Coordenadora do polo"
    assert data["contact_url"] == "https://wa.me/5541999990001"
    assert "5541999990002" not in str(data)


def test_enrollment_me_schema_retains_public_release_progress(enrollment, monkeypatch):
    from api.clients.schemas import EnrollmentMeOut

    monkeypatch.setattr(service, "fee_facts", lambda _: {"first_paid": False, "second_scheduled": False})
    response = EnrollmentMeOut(**service.me_dict(enrollment)).model_dump()
    assert response["release"]["stage"] == "document_review"
    assert response["release"]["coordinator_name"] is None
    assert response["release"]["payment_confirmed"] is False
