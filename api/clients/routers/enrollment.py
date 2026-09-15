"""Router da fase de Matrícula (Funil do Aluno)."""

from __future__ import annotations

from ninja import File, Router
from ninja.files import UploadedFile

from api.auth import require_roles
from api.base import resolve_rg_slot
from api.clients.schemas import (
    ContractOut,
    DocClassifyOut,
    EducationIn,
    EducationOut,
    EnrollmentMeOut,
    KinshipIn,
    RgPatchIn,
    RgSectionOut,
    RgUploadAck,
    SelfieOut,
)
from api.schemas.address import AddressCepIn, AddressDataIn, PublicAddressOut
from core.net import source_ip
from users.consent import STUDENT_CONTRACT
from users.documents import service as documents_iface
from users.exceptions import NotFound
from users.roles.enrollment import service as enrollment_iface

router = Router(tags=["enrollment"])


def _enr_guard(request) -> str:
    """Gate role enrollment / student + devolve o external_id do aluno logado."""
    require_roles(request.auth, "enrollment", "student")
    return request.auth.external_id


@router.get("/enrollment/me", response=EnrollmentMeOut, summary="Estado completo da matrícula")
def enrollment_me(request):
    """Estado COMPLETO da matrícula para o resume do wizard."""
    require_roles(request.auth, "enrollment", "student")
    enr = enrollment_iface.get_for_user_external_id(request.auth.external_id)
    if enr is None:
        raise NotFound("Matrícula não encontrada.", code="ENROLLMENT_NOT_FOUND")
    return enrollment_iface.me_dict(enr)


@router.post(
    "/enrollment/documents/rg/photo/{slot}",
    response=RgUploadAck,
    summary="Upload de foto/arquivo do RG",
)
def enrollment_rg_photo(request, slot: str, file: UploadedFile = File(...)):
    """Upload de foto do RG por slot ('front', 'back', 'full')."""
    ext = _enr_guard(request)
    real_slot = resolve_rg_slot(slot)
    ack = enrollment_iface.upload_rg_photo(
        user_external_id=ext, slot=real_slot, upload=file
    )
    return {"slot": slot, "analysis": ack["analysis_status"], **ack}


@router.post(
    "/enrollment/documents/classify",
    response=DocClassifyOut,
    summary="Classificação rápida pré-upload",
)
def enrollment_document_classify(request, file: UploadedFile = File(...)):
    """Classificação rápida da foto antes do envio."""
    _enr_guard(request)
    from integrations.ai import service as ai

    return ai.classify_document(
        file.read(),
        caller="enrollment.classify",
        mime_type=file.content_type or "application/octet-stream",
    )


@router.get(
    "/enrollment/documents/rg",
    response=RgSectionOut,
    summary="Consulta da seção de RG",
)
def enrollment_rg_get(request):
    """Seção documento completa: fotos, validação e campos extraídos."""
    ext = _enr_guard(request)
    return enrollment_iface.get_rg_section(user_external_id=ext)


@router.patch(
    "/enrollment/documents/rg",
    response=EnrollmentMeOut,
    summary="Correção manual de campos do RG",
)
def enrollment_rg_patch(request, payload: RgPatchIn):
    """Completa/corrige manualmente campos do documento."""
    ext = _enr_guard(request)
    return enrollment_iface.patch_rg_section(
        user_external_id=ext, **payload.dict(exclude_none=True)
    )


@router.get("/enrollment/address", response=PublicAddressOut, summary="Consulta do endereço")
def enrollment_get_address(request):
    """GET do endereço + missing_fields."""
    ext = _enr_guard(request)
    return enrollment_iface.get_address(user_external_id=ext)


@router.post("/enrollment/address", response=EnrollmentMeOut, summary="Definição de CEP")
def enrollment_address(request, payload: AddressCepIn):
    """Define CEP e auto-completa via ViaCEP."""
    ext = _enr_guard(request)
    return enrollment_iface.set_address_cep(user_external_id=ext, cep=payload.cep)


@router.patch("/enrollment/address", response=EnrollmentMeOut, summary="Complemento de endereço")
def enrollment_address_patch(request, payload: AddressDataIn):
    """Preenche e corrige os demais campos de endereço."""
    ext = _enr_guard(request)
    return enrollment_iface.set_address_data(
        user_external_id=ext, **payload.dict(exclude_none=True)
    )


@router.post(
    "/enrollment/address/proof",
    response=EnrollmentMeOut,
    summary="Upload do comprovante de residência",
)
def enrollment_address_proof(request, file: UploadedFile = File(...)):
    """Upload do comprovante de residência."""
    ext = _enr_guard(request)
    return enrollment_iface.upload_address_proof(user_external_id=ext, upload=file)


@router.post(
    "/enrollment/address/proof/kinship",
    response=EnrollmentMeOut,
    summary="Declaração de parentesco do comprovante",
)
def enrollment_address_proof_kinship(request, payload: KinshipIn):
    """Declaração de parentesco quando o titular do comprovante é terceiro."""
    ext = _enr_guard(request)
    return enrollment_iface.submit_address_proof_kinship(
        user_external_id=ext, relation=payload.relation
    )


@router.get("/enrollment/education", response=EducationOut, summary="Consulta de escolaridade")
def enrollment_get_education(request):
    """GET dos dados educacionais da matrícula."""
    ext = _enr_guard(request)
    return enrollment_iface.get_education(user_external_id=ext)


@router.post(
    "/enrollment/education",
    response=EnrollmentMeOut,
    summary="Gravação de dados educacionais",
)
def enrollment_education(request, payload: EducationIn):
    """Grava os dados de escolaridade e avança o wizard."""
    ext = _enr_guard(request)
    enr = enrollment_iface.set_education(
        user_external_id=ext,
        level=payload.level,
        grade=payload.grade,
        completed=payload.completed,
        last_school=payload.last_school,
        city=payload.city,
        state=payload.state,
        last_year_when=payload.last_year_when,
    )
    return enrollment_iface.me_dict(enr)


@router.get("/enrollment/selfie", response=SelfieOut, summary="Consulta da selfie")
def enrollment_get_selfie(request):
    """Consulta estado e análise da selfie."""
    ext = _enr_guard(request)
    return enrollment_iface.get_selfie(user_external_id=ext)


@router.post(
    "/enrollment/selfie",
    response=EnrollmentMeOut,
    summary="Upload de selfie (assinatura)",
)
def enrollment_selfie(request, file: UploadedFile = File(...)):
    """Envia a selfie como assinatura da matrícula."""
    ext = _enr_guard(request)
    image_bytes, content_type = documents_iface.read_image_upload(file)
    enr = enrollment_iface.set_selfie(
        user_external_id=ext,
        image_bytes=image_bytes,
        content_type=content_type,
        consent_ip=source_ip(request),
        consent_user_agent=request.headers.get("user-agent"),
    )
    return {**enrollment_iface.me_dict(enr), **enrollment_iface.selfie_ack(enr)}


@router.get("/contract/current", response=ContractOut, summary="Contrato vigente de matrícula")
def get_current_contract(request):
    """Contrato atual de matrícula (texto + versão + hash)."""
    return STUDENT_CONTRACT.as_dict()
