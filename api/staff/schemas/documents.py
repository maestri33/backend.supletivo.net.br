"""Schemas Pydantic v2 do grupo Staff: Documentos e Dossiê."""

from __future__ import annotations

from typing import Any

from ninja import Field, FilterSchema, Schema
from pydantic import ConfigDict


class DocumentDecideIn(Schema):
    kind: str  # rg, selfie, address_proof, student_doc
    approve: bool
    reason: str | None = None
    doc_id: str | None = None


class DocumentReprocessIn(Schema):
    pipeline: str = "all"  # ocr, extract, biometric, all
    model: str | None = None


class DocumentReviewFilterSchema(FilterSchema):
    hub: str | None = None
    doc_type: str | None = None


class DocumentReviewOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    user_external_id: str | None = None
    name: str
    phone: str | None = None
    cpf: str | None = None
    hub_name: str | None = None
    type: str
    kind: str
    reason: str
    created_at: str


class DossierProfileOut(Schema):
    name: str | None = None
    cpf: str | None = None
    phone: str | None = None
    email: str | None = None
    birth_date: str | None = None
    mother_name: str | None = None
    father_name: str | None = None
    pix_key: str | None = None
    selfie_needs_meeting: bool = False


class DossierMediaOut(Schema):
    front_photo: str | None = None
    back_photo: str | None = None
    full_photo: str | None = None
    selfie_photo: str | None = None
    face_crop: str | None = None
    address_photo: str | None = None


class DossierDocumentDataOut(Schema):
    doc_type: str | None = None
    number: str | None = None
    state: str | None = None
    validation_status: str | None = None
    validation_reason: str | None = None
    extracted_data: dict[str, Any] = Field(default_factory=dict)


class DossierBiometricsOut(Schema):
    selfie_status: str | None = None
    selfie_reason: str | None = None
    verifications: list[dict[str, Any]] = Field(default_factory=list)


class DossierAddressOut(Schema):
    street: str | None = None
    number: str | None = None
    complement: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    state: str | None = None
    zipcode: str | None = None


class UserDossierOut(Schema):
    user_external_id: str
    profile: DossierProfileOut
    media: DossierMediaOut
    document_data: DossierDocumentDataOut
    biometrics: DossierBiometricsOut
    address: DossierAddressOut


class DocumentDecideOut(Schema):
    detail: str
    status: str
