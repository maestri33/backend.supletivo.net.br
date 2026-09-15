"""Schemas Pydantic v2 do grupo Collaborators (Funil do Promotor)."""

from __future__ import annotations

from typing import Any

from ninja import Field, Schema

from api.schemas.address import PublicAddressOut
from api.schemas.documents import ContractOut, DocClassifyOut


class CandidateCreateIn(Schema):
    cpf: str
    phone: str
    email: str
    hub: str | None = None


class CandidateJoinIn(Schema):
    external_id: str = Field(description="external_id do USER vindo do /auth/check")
    otp: str
    hub: str | None = None


class CandidateOut(Schema):
    external_id: str = Field(description="external_id do CANDIDATO (≠ do user)")
    user_external_id: str = Field(
        description="external_id do USER — é o que o /auth/login espera"
    )
    status: str


class ProfileIn(Schema):
    mother_name: str | None = None
    father_name: str | None = None
    marital_status: str | None = None
    birthplace: str | None = None
    nationality: str | None = None


class DocumentsIn(Schema):
    doc_type: str
    number: str
    issuing_agency: str | None = None
    issue_date: str | None = None
    category: str | None = None
    national_register: str | None = None
    date_of_birth: str | None = None
    expires_on: str | None = None


class PixIn(Schema):
    key: str
    key_type: str


class PromoterPixIn(Schema):
    pix_key: str | None = None
    key: str | None = None
    key_type: str | None = None


class EducationIn(Schema):
    level: str
    completed: bool
    grade: int | None = None
    last_completed_grade: int | None = None
    qualification: str | None = None
    last_completed_qualification: str | None = None
    education_status: str | None = None
    year: int | None = None
    city: str | None = None
    school: str | None = None


class KinshipIn(Schema):
    relation: str


class SubmissionIn(Schema):
    material_external_id: str
    answer: str


class CandidateProfileOut(Schema):
    mother_name: str | None = None
    father_name: str | None = None
    birthplace: str | None = None
    marital_status: str | None = None
    nationality: str | None = None
    name: str | None = None
    birth_date: str | None = None
    education_level: str | None = None
    education_completed: bool | None = None
    education_grade: int | None = None
    education_last_completed_grade: int | None = None
    education_qualification: str | None = None
    education_last_completed_qualification: str | None = None
    education_status: str | None = None
    education_year: int | None = None
    education_city: str | None = None
    education_school: str | None = None
    locked_fields: list[str] = Field(default_factory=list)


class CandidateDocumentSubOut(Schema):
    number: str | None = None
    issuing_agency: str | None = None
    issue_date: str | None = None
    category: str | None = None
    date_of_birth: str | None = None
    expires_on: str | None = None
    national_register: str | None = None
    front_photo: str | None = None
    back_photo: str | None = None
    full_photo: str | None = None
    validation_status: str | None = None
    validation_reason: str | None = None


class AddressProofOut(Schema):
    photo: str | None = None


class CandidateDocumentsOut(Schema):
    external_id: str
    rg: CandidateDocumentSubOut | None = None
    cnh: CandidateDocumentSubOut | None = None
    certificate: CandidateDocumentSubOut | None = None
    military: CandidateDocumentSubOut | None = None
    address_proof: AddressProofOut | None = None


class CandidateSelfieOut(Schema):
    exists: bool
    photo: str | None = None
    taken_at: str | None = None
    status: str | None = None
    analysis_status: str | None = None
    analysis_reason: str | None = None
    expires_at: str | None = None
    verified: bool = False
    description: str | None = None


class AddressProofSectionOut(Schema):
    exists: bool = False
    photo: str | None = None
    status: str | None = None
    reason: str | None = None
    needs_kinship: bool = False
    kinship_relation: str | None = None


class CandidateMeOut(Schema):
    external_id: str
    status: str
    hub_external_id: str
    pix_validated: bool
    selfie_verified: bool
    selfie_status: str | None = None
    profile: CandidateProfileOut | None = None
    address: PublicAddressOut | None = None
    address_proof: AddressProofSectionOut | None = None
    documents: CandidateDocumentsOut | None = None
    selfie: CandidateSelfieOut | None = None
    blocks: list[dict[str, Any]] | None = None


class CandidateDocumentSectionOut(Schema):
    doc_type: str | None = None
    number: str | None = None
    issuing_agency: str | None = None
    issue_date: str | None = None
    category: str | None = None
    date_of_birth: str | None = None
    expires_on: str | None = None
    national_register: str | None = None
    front_photo: str | None = None
    back_photo: str | None = None
    full_photo: str | None = None
    validation_status: str | None = None
    validation_reason: str | None = None
    analysis_status: str | None = None
    analysis_reason: str | None = None
    extracted: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    next_slot: str | None = None
    photos: dict[str, Any] = Field(default_factory=dict)


class AnalysisAckOut(Schema):
    stored: bool | str
    analysis_status: str | None = None
    poll_after_ms: int
    expires_at: str | None = None


class TrainingMaterialOut(Schema):
    material_external_id: str
    title: str
    blocking: bool
    kind: str
    assignment_status: str
    submission_status: str
    grade: str | None = None
    justification: str | None = None
    text_content: str = ""
    content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    question: str = ""
    video: str | None = None
    photo: str | None = None


class TrainingMaterialProgressOut(Schema):
    material_external_id: str
    title: str
    blocking: bool
    kind: str
    assignment_status: str
    submission_status: str
    grade: str | None = None
    justification: str | None = None


class SubmissionOut(Schema):
    external_id: str
    material_external_id: str
    grade: str | None = None
    justification: str | None = None
    audio: str | None = None
    status: str


class PromoterPixIn(Schema):
    pix_key: str
    key_type: str | None = None


class PromoterPixOut(Schema):
    pix_key: str
    key_type: str | None = None
    bank_name: str | None = None
    holder_name: str | None = None
    validated: bool = True


class PromoterPixTestOut(Schema):
    success: bool
    transfer_id: str | None = None
    status: str | None = None
    message: str


class PromoterMeOut(Schema):
    external_id: str
    status: str
    hub_external_id: str
    hub_brand: str | None = None
    ref_url: str
    pre_matriculado: bool = False
    locked: bool
    pending_materials: list[dict[str, Any]] = Field(default_factory=list)
    blocks: list[dict[str, Any]] | None = None
    payout_locked: bool = False
    profile_status: str = "ativo_pleno"
    missing_requirements: list[str] = Field(default_factory=list)
    name: str | None = None
    phone: str | None = None
    pix_key: str | None = None
    pix_validated: bool = False


class PromoterLeadOut(Schema):
    external_id: str
    status: str
    name: str | None = None
    phone: str | None = None
    created_at: str


class PromoterLeadInviteIn(Schema):
    phone: str
    cpf: str | None = None


class PromoterLeadInviteOut(Schema):
    sent: bool
    phone_last4: str


class PromoterCommissionOut(Schema):
    external_id: str
    amount: str
    source: str
    status: str
    created_at: str


class PromoterLifetimeOut(Schema):
    total_students: int
    goals_hit: int
    total_received: str


class PromoterSummaryOut(Schema):
    week_start: str
    week_end: str
    week_paid_leads: int
    week_goal: int
    goal_reached: bool
    week_commission_total: str
    bonus_amount: str
    next_closing_at: str
    lifetime: PromoterLifetimeOut


class StudyPricingCardOut(Schema):
    installments: int
    installment: str
    total: str


class StudyPricingOut(Schema):
    pix: str
    card: StudyPricingCardOut


class StudyCheckoutOut(Schema):
    payment_method: str | None = None
    provider: str | None = None
    amount: str | None = None
    is_paid: bool | None = None
    checkout_url: str | None = None
    short_url: str | None = None
    qrcode_payload: str | None = None
    qrcode_image: str | None = None
    due_date: str | None = None


class StudyStartOut(Schema):
    external_id: str
    user_external_id: str
    status: str
    checkout: StudyCheckoutOut | None = None


class StudyStartIn(Schema):
    payment_method: str | None = None
