"""Schemas Pydantic v2 do grupo Leadership (Coordenador de Polo)."""

from __future__ import annotations

from typing import Any

from ninja import Field, Schema

from api.schemas.address import PublicAddressOut
from api.schemas.auth import CheckIn, LoginIn
from api.schemas.student import StudentPlatformFields


class HubOut(Schema):
    external_id: str
    brand: str


class CoordinatorCheckOut(Schema):
    found: bool
    external_id: str | None = Field(
        None, description="external_id do USER (é o que o /auth/login espera)"
    )
    otp_sent: bool = False
    otp_wait: int | None = None
    whatsapp: bool | None = None
    roles: list[str] | None = None
    token: str | None = None
    is_coordinator: bool = False
    hub: HubOut | None = Field(
        None, description="o polo que a pessoa coordena (se coordena)"
    )
    detail: str | None = Field(
        None,
        description="presente quando a pessoa existe mas NÃO coordena polo",
    )


class HubLeadRowOut(Schema):
    external_id: str
    status: str
    name: str | None = None
    phone: str | None = None
    promoter_external_id: str
    payment_link: str | None = None
    receipt_url: str | None = None


class LeadCustomerOut(Schema):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    cpf: str | None = None


class LeadPromoterOut(Schema):
    external_id: str
    name: str | None = None


class LeadCheckoutOut(Schema):
    payment_method: str | None = None
    provider: str | None = None
    amount: str | None = None
    is_paid: bool | None = None
    url: str | None = None
    receipt_url: str | None = None
    qrcode_payload: str | None = None
    qrcode_image: str | None = None
    due_date: str | None = None


class HubLeadDetailOut(Schema):
    external_id: str
    status: str
    failed_reason: str | None = None
    created_at: str
    customer: LeadCustomerOut
    promoter: LeadPromoterOut
    checkout: LeadCheckoutOut | None = None


class CandidateProfileOut(Schema):
    mother_name: str | None = None
    father_name: str | None = None
    birthplace: str | None = None
    marital_status: str | None = None
    nationality: str | None = None
    name: str | None = None
    birth_date: str | None = None


class CandidateDocumentSubOut(Schema):
    number: str | None = None
    issuing_agency: str | None = None
    issue_date: str | None = None
    front_photo: str | None = None
    back_photo: str | None = None
    full_photo: str | None = None
    validation_status: str | None = None
    validation_reason: str | None = None
    category: str | None = None
    date_of_birth: str | None = None
    expires_on: str | None = None
    national_register: str | None = None
    kind: str | None = None
    registry_office: str | None = None
    book: str | None = None
    page: str | None = None
    entry: str | None = None
    photo: str | None = None
    series: str | None = None
    ra: str | None = None


class CandidateDocumentsOut(Schema):
    external_id: str
    rg: CandidateDocumentSubOut | None = None
    cnh: CandidateDocumentSubOut | None = None
    certificate: CandidateDocumentSubOut | None = None
    military: CandidateDocumentSubOut | None = None


class EnrollmentSelfieOut(Schema):
    exists: bool
    photo: str | None = None
    taken_at: str | None = None
    status: str | None = None
    analysis_status: str | None = None
    analysis_reason: str | None = None
    expires_at: str | None = None
    verified: bool = False
    description: str | None = None


class CandidateMeOut(Schema):
    external_id: str
    status: str
    hub_external_id: str
    pix_validated: bool
    selfie_verified: bool
    selfie_status: str | None = None
    profile: CandidateProfileOut | None = None
    address: PublicAddressOut | None = None
    documents: CandidateDocumentsOut | None = None
    selfie: EnrollmentSelfieOut | None = None


class CandidateUserOut(Schema):
    external_id: str
    name: str | None = None
    cpf: str | None = None
    phone: str | None = None
    email: str | None = None


class CandidateSelfieDetailOut(Schema):
    external_id: str
    user: CandidateUserOut
    selfie: EnrollmentSelfieOut
    in_review: bool


class EnrollmentFeeDictOut(Schema):
    status: str
    amount: str
    scheduled_for: str | None = None
    paid: bool
    last_error: str | None = None


class EnrollmentFeesOut(Schema):
    first: EnrollmentFeeDictOut | None = None
    second: EnrollmentFeeDictOut | None = None
    first_paid: bool = False
    second_scheduled: bool = False


class EnrollmentProfileOut(Schema):
    mother_name: str | None = None
    father_name: str | None = None
    marital_status: str | None = None
    birthplace: str | None = None
    nationality: str | None = None


class EnrollmentRgOut(Schema):
    number: str | None = None
    issuing_agency: str | None = None
    issue_date: str | None = None
    front_photo: str | None = None
    back_photo: str | None = None
    full_photo: str | None = None
    analysis_status: str | None = None
    analysis_reason: str | None = None
    validation_status: str | None = None
    validation_reason: str | None = None
    missing_fields: list[str] = Field(default_factory=list)


class EnrollmentEducationOut(Schema):
    level: str | None = None
    grade: int | None = None
    completed: bool | None = None
    last_school: str | None = None
    city: str | None = None
    state: str | None = None
    last_year_when: str | None = None


class HubEnrollmentDetailOut(Schema):
    external_id: str
    status: str
    hub_external_id: str
    selfie_verified: bool
    selfie_status: str | None = None
    analysis_status: str | None = None
    profile: EnrollmentProfileOut | None = None
    address_complete: bool = False
    address: PublicAddressOut | None = None
    selfie: EnrollmentSelfieOut | None = None
    rg: EnrollmentRgOut | None = None
    education: EnrollmentEducationOut | None = None
    fees: EnrollmentFeesOut


class EnrollmentActionOut(Schema):
    external_id: str
    status: str


class EnrollmentRgDecideOut(Schema):
    external_id: str
    status: str
    rg_validation_status: str


class AddressProofDecideOut(Schema):
    external_id: str
    status: str


class EnrollmentSelfieDecideOut(Schema):
    external_id: str
    status: str
    selfie_status: str
    selfie_verified: bool


class HubEnrollmentRowOut(Schema):
    external_id: str
    name: str | None = None
    phone: str | None = None
    status: str
    fees: EnrollmentFeesOut
    created_at: str


class ReviewItemOut(Schema):
    external_id: str = Field(
        description="id do recurso a decidir"
    )
    type: str = Field(description="enrollment | candidate | student | promoter")
    kind: str = Field(
        description="rg | selfie | document | awaiting_approval | locked_training"
    )
    name: str | None = None
    doc_type: str | None = None
    since: str | None = None
    rejected: bool | None = None
    document_external_id: str | None = None
    student_external_id: str | None = None
    promoter_external_id: str | None = None
    pending_materials: list[dict[str, Any]] | None = None


class ReviewsOut(Schema):
    enrollment_rg: list[ReviewItemOut] = Field(default_factory=list)
    enrollment_selfie: list[ReviewItemOut] = Field(default_factory=list)
    candidate_document: list[ReviewItemOut] = Field(default_factory=list)
    candidate_selfie: list[ReviewItemOut] = Field(default_factory=list)
    student_documents: list[ReviewItemOut] = Field(default_factory=list)
    candidates_awaiting_approval: list[ReviewItemOut] = Field(default_factory=list)
    locked_promoters: list[ReviewItemOut] = Field(default_factory=list)


class HubStudentRowOut(Schema):
    external_id: str
    name: str | None = None
    phone: str | None = None
    status: str
    created_at: str


class PaginatedStudentsOut(Schema):
    items: list[HubStudentRowOut]
    total: int
    limit: int
    offset: int


class HubPromoterRowOut(Schema):
    external_id: str
    name: str | None = None
    status: str
    locked: bool


class CandidateAwaitingOut(Schema):
    external_id: str
    name: str | None = None
    since: str | None = None
    rejected: bool


class CandidateDocumentDetailOut(Schema):
    doc_type: str
    front_photo: str | None = None
    back_photo: str | None = None
    full_photo: str | None = None
    analysis_status: str | None = None
    analysis_reason: str | None = None


class CandidateDetailOut(Schema):
    external_id: str
    status: str
    user: CandidateUserOut
    doc_type: str | None = None
    document: CandidateDocumentDetailOut | None = None
    mother_name: str | None = None
    father_name: str | None = None
    marital_status: str | None = None
    birthplace: str | None = None
    nationality: str | None = None
    pix_key: str | None = None
    pix_key_type: str | None = None
    pix_validated: bool
    selfie_status: str
    selfie_image: str | None = None
    selfie_description: str | None = None


class CandidateActionOut(Schema):
    external_id: str
    status: str


class ExamOut(Schema):
    external_id: str
    result: str


class DocDecisionOut(Schema):
    external_id: str
    validation_status: str


class DiplomaIssueOut(Schema):
    external_id: str
    issued_at: str | None = None


class RgPhotoUploadOut(Schema):
    stored: str
    analysis_status: str | None = None
    poll_after_ms: int
    expires_at: str | None = None


class CandidateSelfieDecideOut(Schema):
    external_id: str
    selfie_status: str
    status: str


class StudentDocItemOut(Schema):
    external_id: str
    doc_type: str
    photo: str | None = None
    validation_status: str
    has_photo: bool
    analysis_status: str | None = None
    analysis_reason: str | None = None
    expires_at: str | None = None


class StudentPendencyOut(Schema):
    external_id: str
    kind: str
    description: str
    amount_cents: int | None = None
    resolved: bool


class StudentDiplomaOut(Schema):
    issued_at: str | None = None
    picked_up: bool


class StudentUserOut(Schema):
    external_id: str
    name: str | None = None
    cpf: str | None = None
    phone: str | None = None
    email: str | None = None


class HubStudentDetailOut(Schema):
    external_id: str
    status: str
    hub_external_id: str
    blood_type: str | None = None
    self_study: bool
    platform: StudentPlatformFields
    documents: list[StudentDocItemOut] = Field(default_factory=list)
    pendencies: list[StudentPendencyOut] = Field(default_factory=list)
    diploma: StudentDiplomaOut | None = None
    user: StudentUserOut


class FeeIn(Schema):
    qr_code: str
    amount: str | None = None


class ConcludeIn(Schema):
    platform_login: str
    platform_password: str
    platform_url: str | None = None
    platform_notes: str | None = None


class SelfieDecideIn(Schema):
    approve: bool
    reason: str | None = None


class ExamGradeIn(Schema):
    passed: bool
    notes: str | None = None


class PendencyIn(Schema):
    kind: str
    description: str
    amount_cents: int | None = None


class DocDecideIn(Schema):
    approve: bool
    reason: str | None = None


class MaterialApproveOut(Schema):
    promoter_external_id: str
    material_external_id: str
    locked: bool


class RejectIn(Schema):
    reason: str


class ProxyCepIn(Schema):
    cep: str


class CorrectIdentityIn(Schema):
    mother_name: str | None = None
    father_name: str | None = None
    marital_status: str | None = None
    nationality: str | None = None
    birthplace: str | None = None
