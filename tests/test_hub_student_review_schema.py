import pytest

pytestmark = pytest.mark.django_db


def test_student_document_review_serializes_and_preserves_decision_ids():
    from api.leadership.schemas import ReviewItemOut
    from hub.models import Hub
    from users.address.models import Address
    from users.auth.models import User
    from users.roles.student.models import Student, StudentDocument
    from users.roles.student.service import list_document_reviews_for_hub

    coordinator = User.objects.create_user()
    hub = Hub.objects.create(coordinator=coordinator, brand="test", address=Address.objects.create())
    student = Student.objects.create(user=User.objects.create_user(), hub=hub)
    doc = StudentDocument.objects.create(
        student=student, doc_type=StudentDocument.Type.TRANSCRIPT,
        validation_status=StudentDocument.Validation.REVIEW,
    )
    item = list_document_reviews_for_hub(hub=hub)[0]
    response = ReviewItemOut.model_validate({"type": "student", "kind": "document", **item})
    assert response.external_id == str(doc.external_id)
    assert response.document_external_id == str(doc.external_id)
    assert response.student_external_id == str(student.external_id)


@pytest.fixture
def enrollment_review():
    from hub.models import Hub
    from users.address.models import Address
    from users.auth.models import User
    from users.documents.models import AddressProof, Document, RG
    from users.roles.enrollment.models import Enrollment
    from users.roles.models import UserRole

    coordinator = User.objects.create_user()
    UserRole.objects.create(user=coordinator, role="coordinator")
    hub = Hub.objects.create(coordinator=coordinator, brand="test", address=Address.objects.create())
    student = User.objects.create_user()
    document = Document.objects.create(user=student)
    RG.objects.create(document=document, validation_status="review")
    AddressProof.objects.create(document=document, validation_status="review")
    return Enrollment.objects.create(user=student, promoter=coordinator, hub=hub, selfie_status="review")


@pytest.mark.parametrize("address_status", ["review", "needs_kinship"])
def test_hub_reviews_http_exposes_rg_selfie_and_address_decisions(client, enrollment_review, address_status):
    from users.auth.jwt.service import issue
    from users.documents.models import AddressProof

    enr = enrollment_review
    AddressProof.objects.filter(document__user=enr.user).update(validation_status=address_status)
    token = issue(str(enr.hub.coordinator.external_id), ["coordinator"])["access_token"]
    result = client.get("/api/v1/leadership/reviews", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert result.status_code == 200, result.content
    response = result.json()
    for key in ["enrollment_rg", "enrollment_selfie", "enrollment_address_proof"]:
        assert response[key][0]["external_id"] == str(enr.external_id)
    assert response["enrollment_address_proof"][0]["kind"] == "address_proof"


@pytest.mark.parametrize("approve, status", [(True, "approved"), (False, "rejected")])
def test_enrollment_address_decision_uses_runtime_helpers(monkeypatch, enrollment_review, approve, status):
    from users.documents.models import AddressProof
    from users.roles.enrollment import service

    enr = enrollment_review
    monkeypatch.setattr(service, "_notify_resolution", lambda *args: None)
    response = service.decide_address_proof_kinship(
        enrollment_external_id=str(enr.external_id), coordinator=enr.hub.coordinator,
        approve=approve, reason="decisão do coordenador",
    )
    assert response["status"] == status
    assert AddressProof.objects.get(document__user=enr.user).validation_status == status
