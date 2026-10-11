"""Database-backed release rule tests; provider, queue and notification I/O stays offline.

These tests exercise the actual domain helpers. Fixture clock changes are unit scenarios,
never evidence that a new production canary has completed the two-month waiting period.
"""
import io
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from PIL import Image
from django.utils import timezone

from finance.models import Commission, PaymentRequest
from hub.models import Hub
from users.address.models import Address
from users.auth.models import User
from users.documents.models import Document, RG
from users.profiles import interface as profiles
from users.roles.enrollment import service as enrollment_service
from users.roles.enrollment.models import Enrollment
from users.roles.lead import service as lead_service
from users.roles.lead.models import Checkout, Lead
from users.roles.models import UserRole
from users.roles.promoter.models import Promoter
from users.roles.student import service as student_service
from users.roles.student.models import Student, StudentDiploma, StudentExam, StudentDocument
from users.exceptions import Conflict

pytestmark = pytest.mark.django_db
SP = ZoneInfo("America/Sao_Paulo")


@pytest.fixture(autouse=True)
def offline_boundaries(monkeypatch):
    import core.tasks
    import integrations.cloudflare.r2
    import integrations.tools.biometric.service
    import notify.interface.events

    monkeypatch.setattr(core.tasks, "async_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(integrations.cloudflare.r2, "is_r2_configured", lambda: False)
    monkeypatch.setattr(integrations.tools.biometric.service, "try_enroll_document", lambda **kwargs: False)
    monkeypatch.setattr(notify.interface.events, "send_event", lambda *args, **kwargs: None)


@pytest.fixture
def process():
    coordinator = User.objects.create_user()
    profiles.create(user=coordinator, cpf=None, phone="5543990000001", name="Unit coordinator")
    hub = Hub.objects.create(coordinator=coordinator, address=Address.objects.create(), brand="unit")
    Promoter.objects.create(user=coordinator, hub=hub)
    UserRole.objects.create(user=coordinator, role="promoter")
    user = User.objects.create_user()
    profiles.create(user=user, cpf=None, phone="5542990000002", name="Unit student")
    UserRole.objects.create(user=user, role="student")
    enrollment = Enrollment.objects.create(user=user, hub=hub, promoter=coordinator)
    student = Student.objects.create(user=user, hub=hub, status=Student.Status.EXAM_RELEASED)
    lead = Lead.objects.create(user=user, promoter=coordinator, status=Lead.Status.PAID)
    checkout = Checkout.objects.create(
        lead=lead, provider="asaas", provider_payment_id=str(uuid.uuid4()),
        payment_method="pix", amount="1.01", is_paid=True,
        paid_at=datetime(2026, 8, 10, 12, tzinfo=SP),
    )
    return student, enrollment, checkout


@pytest.mark.parametrize("paid, eligible", [
    (datetime(2026, 12, 31, 18, tzinfo=SP), datetime(2027, 2, 28, 18, tzinfo=SP)),
    (datetime(2023, 12, 31, 18, tzinfo=SP), datetime(2024, 2, 29, 18, tzinfo=SP)),
    (datetime(2026, 7, 31, 18, tzinfo=SP), datetime(2026, 9, 30, 18, tzinfo=SP)),
    (datetime(2026, 8, 10, 12, tzinfo=SP), datetime(2026, 10, 10, 12, tzinfo=SP)),
])
def test_waiting_period_is_two_local_calendar_months(process, paid, eligible):
    student, _, checkout = process
    Checkout.objects.filter(pk=checkout.pk).update(paid_at=paid)
    assert student_service.exam_available_at(student) == eligible


def test_cannot_book_before_wait_even_for_a_later_exam(process, monkeypatch):
    student, _, _ = process
    now = datetime(2026, 10, 10, 11, 59, 59, tzinfo=SP)
    monkeypatch.setattr(student_service.timezone, "now", lambda: now)
    with pytest.raises(student_service.StudentError) as error:
        student_service.schedule_exam(user_external_id=str(student.user.external_id), subject="Final", scheduled_at=now + timedelta(days=5))
    assert error.value.code == "EXAM_WAITING_PERIOD"
    assert error.value.extra["exam_available_at"] == "2026-10-10T12:00:00-03:00"
    assert not StudentExam.objects.exists()
    student.refresh_from_db()
    assert student.status == Student.Status.EXAM_RELEASED


def test_can_book_at_wait_boundary_and_persists_real_exam(process, monkeypatch):
    student, _, _ = process
    now = datetime(2026, 10, 10, 12, tzinfo=SP)
    monkeypatch.setattr(student_service.timezone, "now", lambda: now)
    exam = student_service.schedule_exam(user_external_id=str(student.user.external_id), subject="Final", scheduled_at=now + timedelta(days=1))
    student.refresh_from_db()
    assert StudentExam.objects.get(pk=exam.pk).scheduled_at == now + timedelta(days=1)
    assert student.status == Student.Status.EXAM_SCHEDULED


def test_past_exam_date_is_rejected(process, monkeypatch):
    student, _, _ = process
    now = datetime(2026, 10, 11, 12, tzinfo=SP)
    monkeypatch.setattr(student_service.timezone, "now", lambda: now)
    with pytest.raises(student_service.StudentError) as error:
        student_service.schedule_exam(user_external_id=str(student.user.external_id), subject="Final", scheduled_at=now - timedelta(days=1))
    assert error.value.code == "INVALID_SCHEDULED_AT"
    assert not StudentExam.objects.exists()


def test_legacy_paid_checkout_uses_immutable_enrollment_not_updated_at(process):
    student, enrollment, checkout = process
    observed = datetime(2026, 8, 10, 12, tzinfo=SP)
    Checkout.objects.filter(pk=checkout.pk).update(paid_at=None, updated_at=datetime(2026, 10, 11, 12, tzinfo=SP))
    Enrollment.objects.filter(pk=enrollment.pk).update(created_at=observed)
    assert student_service.exam_available_at(student) == datetime(2026, 10, 10, 12, tzinfo=SP)


def test_missing_confirmed_payment_never_grants_exam_booking(process):
    student, _, checkout = process
    Checkout.objects.filter(pk=checkout.pk).update(is_paid=False)
    with pytest.raises(student_service.StudentError) as error:
        student_service.exam_available_at(student)
    assert error.value.code == "PAYMENT_CONFIRMATION_REQUIRED"


def test_issue_requires_new_transcript_before_saving_any_diploma(process):
    student, _, _ = process
    Student.objects.filter(pk=student.pk).update(status=Student.Status.AWAITING_DIPLOMA_ISSUANCE)
    with pytest.raises(student_service.StudentError) as error:
        student_service.issue_diploma(student_external_id=str(student.external_id), coordinator=student.hub.coordinator, diploma_bytes=b"unit diploma", diploma_content_type="application/pdf")
    assert error.value.code == "TRANSCRIPT_FILE_REQUIRED"
    assert not StudentDiploma.objects.exists()


def test_legacy_diploma_without_transcript_cannot_promote_or_credit(process):
    student, _, _ = process
    Student.objects.filter(pk=student.pk).update(status=Student.Status.AWAITING_PICKUP)
    StudentDiploma.objects.create(student=student, diploma_file="diploma/unit.pdf")
    with pytest.raises(student_service.StudentError) as error:
        student_service.register_pickup(student_external_id=str(student.external_id), coordinator=student.hub.coordinator, image_bytes=b"unit photo", content_type="image/png")
    assert error.value.code == "COMPLETION_DOCUMENTS_REQUIRED"
    student.refresh_from_db()
    assert student.status == Student.Status.AWAITING_PICKUP
    assert not Commission.objects.filter(source_type=Commission.Source.VETERAN).exists()


def test_diploma_history_photo_promote_and_credit_once(process, settings):
    student, _, _ = process
    settings.COMMISSION_COORDINATOR = "0.05"
    Student.objects.filter(pk=student.pk).update(status=Student.Status.AWAITING_DIPLOMA_ISSUANCE)
    diploma = student_service.issue_diploma(
        student_external_id=str(student.external_id), coordinator=student.hub.coordinator,
        diploma_bytes=b"%PDF-unit diploma", diploma_content_type="application/pdf",
        transcript_bytes=b"%PDF-unit history", transcript_content_type="application/pdf",
    )
    buffer = io.BytesIO(); Image.new("RGB", (8, 8), "white").save(buffer, "PNG")
    student_service.register_pickup(student_external_id=str(student.external_id), coordinator=student.hub.coordinator, image_bytes=buffer.getvalue(), content_type="image/png")
    student.refresh_from_db(); diploma.refresh_from_db()
    assert student.status == Student.Status.VETERAN
    assert diploma.diploma_file and diploma.transcript_file and diploma.pickup_photo and diploma.picked_up_at
    commission = Commission.objects.get(source_type=Commission.Source.VETERAN, source_external_id=student.external_id)
    assert commission.amount == Decimal("0.05")
    assert UserRole.objects.filter(user=student.user, role="veteran", revoked_at=None).exists()
    with pytest.raises(Conflict):
        student_service.register_pickup(student_external_id=str(student.external_id), coordinator=student.hub.coordinator, image_bytes=buffer.getvalue(), content_type="image/png")
    assert Commission.objects.filter(source_type=Commission.Source.VETERAN).count() == 1


def test_fee_schedule_calls_real_state_helper_and_queues_once(process, monkeypatch):
    student, enrollment, _ = process
    Enrollment.objects.filter(pk=enrollment.pk).update(status=Enrollment.Status.AWAITING_RELEASE)
    due = timezone.now() + timedelta(days=10)
    monkeypatch.setattr(enrollment_service, "_plan_fee_qr", lambda *args: {"due_date": due.date(), "amount": Decimal("1.01"), "scheduled_for": due})
    result = enrollment_service.schedule_fee(enrollment_external_id=str(enrollment.external_id), coordinator=student.hub.coordinator, qr_code="unit-only-qr")
    enrollment.refresh_from_db()
    assert result["status"] == enrollment.status == Enrollment.Status.FEE_SCHEDULED
    assert PaymentRequest.objects.get().scheduled_for == due
    with pytest.raises(Conflict):
        enrollment_service.schedule_fee(enrollment_external_id=str(enrollment.external_id), coordinator=student.hub.coordinator, qr_code="unit-only-qr")
    assert PaymentRequest.objects.count() == 1


def test_fee_paid_hook_uses_actual_runtime_state_helper(process):
    _, enrollment, _ = process
    Enrollment.objects.filter(pk=enrollment.pk).update(status=Enrollment.Status.AWAITING_RELEASE)
    enrollment.refresh_from_db()
    assert enrollment_service.apply_fee_paid(enrollment, external_reference=enrollment_service._fee_now_ref(enrollment), amount="1.01")
    enrollment.refresh_from_db()
    assert enrollment.status == Enrollment.Status.FEE_PAID


@pytest.mark.parametrize("approve, verdict", [(False, "rejected"), (True, "approved")])
def test_rg_human_decision_uses_actual_helpers(process, approve, verdict):
    student, enrollment, _ = process
    document = Document.objects.create(user=student.user)
    rg = RG.objects.create(document=document, full_photo="documents/unit.png", validation_status="review", validation_result={"extracted": {"number": "UNIT123"}})
    result = enrollment_service.decide_rg(enrollment_external_id=str(enrollment.external_id), coordinator=student.hub.coordinator, approve=approve, reason="Unit review")
    rg.refresh_from_db(); enrollment.refresh_from_db()
    assert result["rg_validation_status"] == rg.validation_status == verdict
    if approve:
        assert rg.number == "UNIT123"
        assert enrollment.status == Enrollment.Status.ADDRESS


@pytest.mark.parametrize("approve, status", [(False, Enrollment.Status.SELFIE), (True, Enrollment.Status.AWAITING_RELEASE)])
def test_selfie_human_decision_uses_actual_coordinator_gate(process, approve, status):
    student, enrollment, _ = process
    Enrollment.objects.filter(pk=enrollment.pk).update(status=Enrollment.Status.SELFIE, selfie_status="review")
    enrollment_service.decide_selfie(enrollment_external_id=str(enrollment.external_id), coordinator=student.hub.coordinator, approve=approve, reason="Unit review")
    enrollment.refresh_from_db()
    assert enrollment.status == status
    assert enrollment.selfie_verified is approve


def test_mark_paid_captures_observed_confirmation_once(process, monkeypatch):
    _, enrollment, checkout = process
    Enrollment.objects.filter(pk=enrollment.pk).delete()
    UserRole.objects.filter(user=checkout.lead.user).delete()
    UserRole.objects.create(user=checkout.lead.user, role="lead")
    Lead.objects.filter(pk=checkout.lead.pk).update(status=Lead.Status.PENDING)
    Checkout.objects.filter(pk=checkout.pk).update(is_paid=False, paid_at=None)
    observed = datetime(2026, 10, 11, 12, tzinfo=SP)
    monkeypatch.setattr(timezone, "now", lambda: observed)
    assert lead_service.mark_paid(provider=checkout.provider, provider_payment_id=checkout.provider_payment_id)
    checkout.refresh_from_db()
    assert checkout.paid_at == observed
    monkeypatch.setattr(timezone, "now", lambda: observed + timedelta(days=1))
    assert lead_service.mark_paid(provider=checkout.provider, provider_payment_id=checkout.provider_payment_id)
    checkout.refresh_from_db()
    assert checkout.paid_at == observed
    assert Commission.objects.filter(source_type=Commission.Source.LEAD, source_external_id=checkout.lead.external_id).count() == 1


def test_stale_document_verdict_cannot_approve_replacement_file(process):
    student, _, _ = process
    doc = StudentDocument.objects.create(student=student, doc_type="transcript", photo="new-upload.png", validation_status="pending")
    student_service.apply_validation(doc.id, status="approved", payload={"reason": "old verdict"}, expected_photo="old-upload.png")
    doc.refresh_from_db()
    assert doc.validation_status == "pending"
    assert doc.validation_result is None
    student_service.apply_validation(doc.id, status="rejected", payload={"reason": "new verdict"}, expected_photo="new-upload.png")
    doc.refresh_from_db()
    assert doc.validation_status == "rejected"
    assert doc.validation_result["reason"] == "new verdict"


def test_legacy_missing_transcript_can_be_repaired_without_graduating(process):
    student, _, _ = process
    student.status = Student.Status.AWAITING_PICKUP
    student.save(update_fields=["status"])
    StudentDiploma.objects.create(student=student, issued_by=student.hub.coordinator, diploma_file="old-diploma.pdf")
    diploma = student_service.issue_diploma(student_external_id=str(student.external_id), coordinator=student.hub.coordinator, diploma_bytes=b"%PDF-unit", diploma_content_type="application/pdf", transcript_bytes=b"%PDF-unit-new-history", transcript_content_type="application/pdf")
    student.refresh_from_db()
    assert student.status == Student.Status.AWAITING_PICKUP
    assert diploma.transcript_file
    assert diploma.picked_up_at is None
    assert not Commission.objects.exists()


def test_student_and_hub_schema_keep_exam_gate_media_and_results(process):
    from api.clients.schemas import StudentMeOut, VeteranMeOut
    from api.leadership.schemas import HubStudentDetailOut
    student, _, _ = process
    doc = StudentDocument.objects.create(student=student, doc_type="transcript", photo="real-upload.png", validation_status="approved")
    exam = StudentExam.objects.create(student=student, subject="Final", scheduled_at=timezone.now(), attempt_number=1, result="passed", notes="Resultado presencial registrado")
    data = student_service.to_dict(student)
    output = StudentMeOut(**data).model_dump()
    assert output["exam_available_at"] == "2026-10-10T12:00:00-03:00"
    assert output["documents"][0]["photo"] == doc.photo
    assert output["exams"][0]["external_id"] == str(exam.external_id)
    hub = HubStudentDetailOut(**{**data, "self_study": student.self_study, "user": {"external_id": str(student.user.external_id)}}).model_dump()
    assert hub["exams"][0]["notes"] == "Resultado presencial registrado"


def test_optional_blood_type_update_rechecks_approved_history(process):
    student, _, _ = process
    student.status = Student.Status.DOCUMENTS_UNDER_REVIEW
    student.save(update_fields=["status"])
    for doc_type in student_service._required_doc_types_for(student):
        StudentDocument.objects.create(student=student, doc_type=doc_type, photo="existing-document.png", validation_status="approved")
    saved = student_service.set_blood_type(user_external_id=str(student.user.external_id), blood_type="O+")
    assert saved.status == Student.Status.EXAM_RELEASED
    student.refresh_from_db()
    assert student.status == Student.Status.EXAM_RELEASED


def test_previous_history_alone_releases_documents_gate(process):
    student, _, _ = process
    student.status = Student.Status.DOCUMENTS_UNDER_REVIEW
    student.save(update_fields=["status"])
    assert student_service._required_doc_types_for(student) == {"transcript"}
    StudentDocument.objects.create(student=student, doc_type="transcript", photo="history.png", validation_status="approved")
    student_service._maybe_release_exam(student)
    student.refresh_from_db()
    assert student.status == Student.Status.EXAM_RELEASED
    assert student.blood_type is None


def test_optional_certificate_does_not_replace_previous_history(process):
    student, _, _ = process
    student.status = Student.Status.DOCUMENTS_UNDER_REVIEW
    student.save(update_fields=["status"])
    StudentDocument.objects.create(student=student, doc_type="certificate", photo="certificate.png", validation_status="approved")
    student_service._maybe_release_exam(student)
    student.refresh_from_db()
    assert student.status == Student.Status.DOCUMENTS_UNDER_REVIEW


def test_hub_review_queue_resolves_stale_document_helpers(process):
    student, _, _ = process
    reviews = enrollment_service.list_reviews_for_hub(hub=student.hub)
    assert reviews == {"rg": [], "selfie": [], "address_proof": []}


@pytest.mark.parametrize("state", ["failed", "cancelled", "awaiting_balance", "awaiting_pix"])
def test_failed_or_unfunded_second_fee_does_not_allow_conclusion(process, state):
    from users.roles.enrollment.fees_events import fee_facts, batch_fee_facts
    student, enrollment, _ = process
    PaymentRequest.objects.create(kind="fee", method="pix_qr", amount="1.01", status="paid", external_reference=enrollment_service._fee_now_ref(enrollment))
    PaymentRequest.objects.create(kind="fee", method="pix_qr", amount="1.01", status=state, external_reference=enrollment_service._fee_due_ref(enrollment))
    enrollment.status = Enrollment.Status.FEE_SCHEDULED
    enrollment.save(update_fields=["status"])
    assert fee_facts(enrollment)["second_scheduled"] is False
    assert batch_fee_facts([enrollment])[str(enrollment.external_id)]["second_scheduled"] is False
    with pytest.raises(Conflict) as error:
        enrollment_service.conclude(enrollment_external_id=str(enrollment.external_id), coordinator=student.hub.coordinator, platform_login="unit", platform_password="unit")
    assert error.value.code == "FEES_INCOMPLETE"
    assert error.value.extra["missing"] == ["second_fee_scheduled"]
    assert not student_service.get_for_user_external_id(str(student.user.external_id)).platform_login


def test_failed_second_fee_can_queue_a_fresh_attempt(process, monkeypatch):
    student, enrollment, _ = process
    enrollment.status = Enrollment.Status.FEE_SCHEDULED
    enrollment.save(update_fields=["status"])
    old = PaymentRequest.objects.create(kind="fee", method="pix_qr", amount="1.01", status="failed", external_reference=enrollment_service._fee_due_ref(enrollment), source_external_id=enrollment.external_id)
    due = timezone.now() + timedelta(days=10)
    monkeypatch.setattr(enrollment_service, "_plan_fee_qr", lambda *args: {"due_date": due.date(), "amount": Decimal("1.01"), "scheduled_for": due})
    result = enrollment_service.schedule_fee(enrollment_external_id=str(enrollment.external_id), coordinator=student.hub.coordinator, qr_code="unit-only-qr")
    assert result["fees"]["second_scheduled"] is True
    old.refresh_from_db()
    assert old.status == "failed"
    assert PaymentRequest.objects.filter(status="queued").count() == 1
    assert PaymentRequest.objects.count() == 2
