"""Router da fase de Candidato (Funil do Promotor)."""

from __future__ import annotations

from ninja import File, Router
from ninja.files import UploadedFile

from api.auth import require_roles
from api.collaborators.schemas import (
    AddressProofSectionOut,
    AnalysisAckOut,
    CandidateDocumentSectionOut,
    CandidateMeOut,
    CandidateSelfieOut,
    ContractOut,
    DocClassifyOut,
    DocumentsIn,
    EducationIn,
    KinshipIn,
    PixIn,
    ProfileIn,
)
from api.schemas.address import AddressCepIn, AddressDataIn, PublicAddressOut
from core.net import source_ip
from users.consent import PROMOTER_CONTRACT
from users.exceptions import NotFound
from users.roles.candidate import service as candidate_iface

router = Router(tags=["candidate"])


def _guard(request, *allowed: str) -> str:
    """Gate de role por rota + devolve o external_id do USER logado."""
    require_roles(request.auth, *allowed)
    return request.auth.external_id


@router.get("/candidate/me", response=CandidateMeOut, summary="Estado completo do candidato")
def candidate_me(request):
    """Estado COMPLETO do candidato para o resume do wizard."""
    ext = _guard(request, "candidate")
    cand = candidate_iface.get_for_user_external_id(ext)
    if cand is None:
        raise NotFound("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    return candidate_iface.me_dict(cand)


@router.post("/candidate/profile", response=CandidateMeOut, summary="Dados complementares do perfil")
def candidate_profile(request, payload: ProfileIn):
    """Dados do perfil que o documento não traz."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_profile(user_external_id=ext, **payload.dict())


@router.get("/candidate/address", response=PublicAddressOut, summary="Consulta do endereço")
def candidate_get_address(request):
    """GET do endereço + missing_fields."""
    ext = _guard(request, "candidate")
    return candidate_iface.get_address(user_external_id=ext)


@router.post("/candidate/address", response=CandidateMeOut, summary="Definição de CEP")
def candidate_address(request, payload: AddressCepIn):
    """Define CEP e auto-completa via ViaCEP."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_address_cep(user_external_id=ext, cep=payload.cep)


@router.patch("/candidate/address", response=CandidateMeOut, summary="Complemento de endereço")
def candidate_address_patch(request, payload: AddressDataIn):
    """Preenche e corrige os demais campos de endereço."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_address_data(
        user_external_id=ext, **payload.dict(exclude_none=True)
    )


@router.post("/candidate/documents", response=CandidateMeOut, summary="Envio de dados do documento")
def candidate_documents(request, payload: DocumentsIn):
    """Gravação dos campos do documento (RG ou CNH)."""
    ext = _guard(request, "candidate")
    fields = payload.dict()
    doc_type = fields.pop("doc_type")
    return candidate_iface.set_documents(
        user_external_id=ext, doc_type=doc_type, **fields
    )


@router.get(
    "/candidate/document", response=CandidateDocumentSectionOut, summary="Consulta da seção de documentos"
)
def candidate_get_document(request):
    """Seção rica do documento: tipo + fotos + validação IA."""
    ext = _guard(request, "candidate")
    return candidate_iface.get_document_section(user_external_id=ext)


@router.patch("/candidate/document", response=CandidateMeOut, summary="Correção manual de documento")
def candidate_patch_document(request, payload: DocumentsIn):
    """Completa ou corrige campos que a extração OCR não trouxe."""
    ext = _guard(request, "candidate")
    fields = payload.dict(exclude_none=True)
    fields.pop("doc_type", None)
    return candidate_iface.patch_document_section(user_external_id=ext, **fields)


@router.post(
    "/candidate/documents/photo/{slot}", response=AnalysisAckOut, summary="Upload de foto de documento"
)
def candidate_document_photo(request, slot: str, file: UploadedFile = File(...)):
    """Foto do documento (RG ou CNH, frente/verso/inteiro)."""
    ext = _guard(request, "candidate")
    return candidate_iface.upload_document_photo(
        user_external_id=ext, slot=slot, upload=file
    )


@router.post("/candidate/documents/classify", response=DocClassifyOut, summary="Classificação rápida pré-upload")
def candidate_document_classify(request, file: UploadedFile = File(...)):
    """Classificação rápida da foto antes do envio."""
    _guard(request, "candidate")
    from integrations.ai import service as ai

    return ai.classify_document(
        file.read(),
        caller="candidate.classify",
        mime_type=file.content_type or "application/octet-stream",
    )


@router.post(
    "/candidate/documents/address-proof", response=CandidateMeOut, summary="Upload do comprovante de residência"
)
def candidate_address_proof(request, file: UploadedFile = File(...)):
    """Upload do comprovante de residência."""
    ext = _guard(request, "candidate")
    return candidate_iface.upload_address_proof(user_external_id=ext, upload=file)


@router.post(
    "/candidate/documents/address-proof/kinship",
    response=CandidateMeOut,
    summary="Parentesco do comprovante de residência",
)
def candidate_address_proof_kinship(request, payload: KinshipIn):
    """Parentesco quando o comprovante está em nome de terceiro."""
    ext = _guard(request, "candidate")
    return candidate_iface.submit_address_proof_kinship(
        user_external_id=ext, relation=payload.relation
    )


@router.post("/candidate/pix", response=CandidateMeOut, summary="Cadastro de chave Pix")
def candidate_pix(request, payload: PixIn):
    """Valida e cadastra chave Pix do titular."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_pix(
        user_external_id=ext, key=payload.key, key_type=payload.key_type
    )


@router.post("/candidate/education", response=CandidateMeOut, summary="Escolaridade do candidato")
def candidate_education(request, payload: EducationIn):
    """Gravação da escolaridade antes da selfie."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_education(
        user_external_id=ext,
        level=payload.level,
        completed=payload.completed,
        grade=payload.grade,
        last_completed_grade=payload.last_completed_grade,
        qualification=payload.qualification,
        last_completed_qualification=payload.last_completed_qualification,
        education_status=payload.education_status,
        year=payload.year,
        city=payload.city,
        school=payload.school,
    )


@router.post("/candidate/selfie", response=AnalysisAckOut, summary="Upload da selfie (assinatura)")
def candidate_selfie(request, file: UploadedFile = File(...)):
    """Envia a selfie de assinatura e dispara validação biométrica assíncrona."""
    ext = _guard(request, "candidate")
    return candidate_iface.set_selfie(
        user_external_id=ext,
        image_bytes=file.read(),
        content_type=getattr(file, "content_type", "image/jpeg"),
        consent_ip=source_ip(request),
        consent_user_agent=request.headers.get("user-agent"),
    )


@router.get("/contract/current", response=ContractOut, summary="Contrato vigente de adesão")
def get_current_contract(request):
    """Contrato atual de adesão de promotor."""
    return PROMOTER_CONTRACT.as_dict()


@router.get("/candidate/selfie", response=CandidateSelfieOut, summary="Consulta da selfie")
def get_candidate_selfie(request):
    """Consulta estado e análise da selfie."""
    ext = _guard(request, "candidate")
    return candidate_iface.get_selfie(user_external_id=ext)
