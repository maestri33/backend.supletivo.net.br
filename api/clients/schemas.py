"""Schemas Pydantic v2 do grupo Clients (Funil do Aluno)."""

from __future__ import annotations

from typing import Any, Literal

from ninja import Field, Schema

from api.schemas.address import PublicAddressOut
from api.schemas.documents import ContractOut, DocClassifyOut
from api.schemas.student import StudentPlatformFields

AnalysisStatus = Literal["pending", "approved", "rejected", "review"]
WizardStatus = Literal[
    "rg", "address", "education", "selfie", "awaiting_release", "completed"
]


class LeadCreateIn(Schema):
    cpf: str
    phone: str
    email: str
    payment_method: str | None = None
    ref: str | None = None
    turnstile_token: str | None = None  # Token emitido pelo Cloudflare Turnstile


class PixPageOut(Schema):
    """Dados da página PIX PRÓPRIA (`/pix/<token>` no front), endereçada pelo token do link curto.

    PÚBLICO por necessidade: o lead chega pelo link do WhatsApp, sem sessão. Por isso é MAGRO de
    propósito — valor + copia-e-cola + PNG + pago/não pago, zero dado pessoal."""

    amount: str
    is_paid: bool
    qrcode_payload: str | None = None
    qrcode_image: str | None = Field(
        default=None,
        description="Caminho RELATIVO do PNG (/media/...) — same-origin no front (CSP img-src 'self').",
    )
    receipt_url: str | None = None


class CheckoutOut(Schema):
    payment_method: str
    provider: str
    amount: str
    is_paid: bool
    checkout_url: str | None = None
    url: str | None = None
    short_url: str | None = None
    qrcode_payload: str | None = None
    qrcode_image: str | None = None
    due_date: str | None = None


class LeadOut(Schema):
    external_id: str = Field(
        description="external_id do LEAD (≠ do user — proposta #8)"
    )
    user_external_id: str = Field(
        description="external_id do USER — é o que o POST /auth/login espera."
    )
    status: str
    checkout: CheckoutOut | None = None


class CardPriceOut(Schema):
    installments: int
    installment: str
    total: str


class PricingOut(Schema):
    pix: str
    card: CardPriceOut
    promo_pix: str | None = None
    promo_card: CardPriceOut | None = None
    has_discount: bool = False
    promoter_name: str | None = None
    anchor_full: str | None = None


class UrlOut(Schema):
    url: str


class LeadCustomerOut(Schema):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    cpf: str | None = None


class LeadPromoterOut(Schema):
    external_id: str = Field(
        description="external_id do USER do promotor (o mesmo do `?ref=` da landing)"
    )
    name: str | None = None


class LeadSelfCheckoutOut(Schema):
    payment_method: str
    provider: str
    amount: str
    is_paid: bool
    checkout_url: str | None = None
    url: str | None = None
    receipt_url: str | None = None
    qrcode_payload: str | None = None
    qrcode_image: str | None = None
    due_date: str | None = None


class LeadMeOut(Schema):
    external_id: str = Field(
        description="external_id do LEAD (≠ do user — proposta #8)"
    )
    status: str = Field(description="pending | paid | failed")
    failed_reason: str | None = None
    created_at: str
    customer: LeadCustomerOut
    promoter: LeadPromoterOut
    checkout: LeadSelfCheckoutOut | None = None


class AddressProofSectionOut(Schema):
    """Bloco do comprovante de endereço no /me (F1): status da validação IA + parentesco."""

    exists: bool = False
    photo: str | None = None
    status: str | None = None
    reason: str | None = Field(
        None,
        description="Orientação PÚBLICA (o que fazer).",
    )
    needs_kinship: bool = False
    kinship_kind: str | None = Field(
        None,
        description="Com needs_kinship: 'confirm' = sobrenome em comum · 'justify' = sem relação.",
    )
    kinship_relation: str | None = None
    needs_new_proof: bool = Field(
        False,
        description="Coordenador rejeitou a justificativa: pede outro documento.",
    )


class StudentDocumentOut(Schema):
    doc_type: str
    validation_status: str
    has_photo: bool
    analysis_status: AnalysisStatus | None = Field(
        None,
        description="pending | approved | rejected | review",
    )
    analysis_reason: str | None = None
    expires_at: str | None = Field(
        None, description="Até quando o `pending` vale; depois vira `review` (TTL)."
    )


class PendencyOut(Schema):
    external_id: str = Field(description="external_id da PENDÊNCIA (proposta #8)")
    kind: str
    description: str | None = None
    amount_cents: int | None = None


class StudentPendencyOut(PendencyOut):
    resolved: bool


class BlockOut(Schema):
    external_id: str
    source_type: str
    title: str
    description: str
    action_label: str
    action_route: str
    created_at: str


class StudentDiplomaOut(Schema):
    issued_at: str | None = None
    picked_up: bool


class StudentMeOut(Schema):
    external_id: str = Field(
        description="external_id do STUDENT (≠ do user, ≠ da matrícula)"
    )
    status: str = Field(
        description="awaiting_documents | documents_under_review | exam_released | exam_scheduled "
        "| exam_failed | awaiting_documentation_dispatch | pending | awaiting_diploma_issuance "
        "| awaiting_pickup | veteran"
    )
    hub_external_id: str
    blood_type: str | None = None
    platform: StudentPlatformFields
    documents: list[StudentDocumentOut]
    pendencies: list[StudentPendencyOut]
    diploma: StudentDiplomaOut | None = None


class ReferralOut(Schema):
    name: str | None = Field(
        None,
        description="PRIMEIRO nome do promotor ativo, ou null se o ref não vale",
    )


class IdentityIn(Schema):
    cpf: str


class IdentityOut(Schema):
    cpf: str
    name: str | None = None
    birth_date: str | None = Field(
        None, description="ISO YYYY-MM-DD — o front calcula a idade"
    )
    sex: str | None = Field(
        None, description='"M" | "F" — decide "matriculado/a" no pergaminho'
    )
    photo: str | None = Field(
        None,
        description="Foto de perfil do WhatsApp capturada de forma assíncrona.",
    )


class EmailIn(Schema):
    email: str


class EmailOut(Schema):
    email: str
    already_yours: bool = Field(
        False,
        description="True quando este e-mail JÁ era o desta conta.",
    )


class CheckoutSetIn(Schema):
    payment_method: str = Field(description='"pix" | "card"')


class KinshipIn(Schema):
    relation: str


class EducationIn(Schema):
    level: str
    grade: int
    completed: bool
    last_school: str = ""
    city: str
    state: str
    last_year_when: str | None = None


class EnrollmentOut(Schema):
    external_id: str = Field(
        description="external_id da MATRÍCULA (≠ do user, ≠ do promoter)"
    )
    status: WizardStatus = Field(
        description="Seção do wizard a preencher AGORA"
    )
    hub_external_id: str
    selfie_verified: bool
    analysis_status: AnalysisStatus | None = Field(
        None, description="Análise da selfie: pending | approved | rejected | review"
    )
    selfie_status: str = Field(
        description="[DEPRECATED — use analysis_status] alias de compat"
    )
    poll_after_ms: int | None = Field(
        None,
        description="Quando o front deve voltar a perguntar (ms).",
    )
    expires_at: str | None = Field(
        None,
        description="Até quando o `pending` vale (TTL).",
    )


class RgSectionOut(Schema):
    number: str | None = None
    issuing_agency: str | None = None
    issue_date: str | None = None
    mother_name: str | None = None
    father_name: str | None = None
    birthplace: str | None = None
    marital_status: str | None = None
    nationality: str | None = None
    name: str | None = None
    birth_date: str | None = None
    front_photo: str | None = None
    back_photo: str | None = None
    full_photo: str | None = None
    analysis_status: AnalysisStatus | None = Field(
        None,
        description="pending | approved | rejected | review",
    )
    analysis_reason: str | None = None
    blocked: bool = False
    validation_status: AnalysisStatus | None = None
    validation_reason: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    next_slot: str | None = None
    photos: dict[str, Any] = Field(default_factory=dict)


class RgPatchIn(Schema):
    number: str | None = None
    issuing_agency: str | None = None
    issue_date: str | None = None
    mother_name: str | None = None
    father_name: str | None = None
    birthplace: str | None = None
    marital_status: str | None = None
    nationality: str | None = None


class SelfieOut(Schema):
    exists: bool
    photo: str | None = None
    taken_at: str | None = None
    analysis_status: AnalysisStatus | None = None
    analysis_reason: str | None = None
    expires_at: str | None = None
    status: AnalysisStatus | None = None
    verified: bool = False
    description: str | None = None
    attempts: int = 0


class EnrollmentProfileOut(Schema):
    mother_name: str | None = None
    father_name: str | None = None
    marital_status: str | None = None
    birthplace: str | None = None
    nationality: str | None = None


class RgOut(Schema):
    number: str | None = None
    issuing_agency: str | None = None
    issue_date: str | None = None
    front_photo: str | None = None
    back_photo: str | None = None
    full_photo: str | None = None
    analysis_status: AnalysisStatus | None = None
    analysis_reason: str | None = None
    validation_status: AnalysisStatus | None = None
    validation_reason: str | None = None
    missing_fields: list[str] = Field(default_factory=list)


class EducationOut(Schema):
    level: str | None = None
    grade: int | None = None
    completed: bool | None = None
    last_school: str | None = None
    city: str | None = None
    state: str | None = None
    last_year_when: str | None = None


class EnrollmentMeOut(EnrollmentOut):
    profile: EnrollmentProfileOut | None = None
    address_complete: bool = False
    address: PublicAddressOut | None = None
    address_proof: AddressProofSectionOut | None = None
    rg: RgOut | None = None
    education: EducationOut | None = None
    selfie: SelfieOut | None = None
    blocks: list[dict[str, Any]] | None = None


class RgUploadAck(Schema):
    slot: Literal["front", "back", "full"]
    stored: str
    analysis_status: AnalysisStatus
    poll_after_ms: int
    expires_at: str | None = None
    analysis: str = ""


class BloodTypeIn(Schema):
    blood_type: str


class ExamScheduleIn(Schema):
    subject: str
    scheduled_at: str


class StudentDocumentUploadAck(Schema):
    doc_type: str
    stored: bool
    analysis_status: AnalysisStatus
    poll_after_ms: int
    expires_at: str | None = None


class VeteranUserOut(Schema):
    external_id: str
    name: str | None = None
    cpf: str | None = None
    phone: str | None = None
    email: str | None = None


class VeteranDiplomaOut(Schema):
    issued_at: str | None = None
    picked_up_at: str | None = None
    picked_up: bool | None = None
    diploma_file: str | None = None
    transcript_file: str | None = None
    pickup_photo: str | None = None


class VeteranDocumentItemOut(Schema):
    external_id: str | None = None
    doc_type: str
    validation_status: str
    photo: str | None = None
    validated_at: str | None = None


class VeteranMeOut(Schema):
    external_id: str | None = None
    status: str | None = None
    hub_external_id: str | None = None
    blood_type: str | None = None
    platform: StudentPlatformFields | None = None
    user: VeteranUserOut | None = None
    documents: list[VeteranDocumentItemOut] = Field(default_factory=list)
    pendencies: list[dict[str, Any]] = Field(default_factory=list)
    diploma: VeteranDiplomaOut | None = None
    enrollment: dict[str, Any] | None = None

