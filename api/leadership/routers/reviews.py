"""Router da Central de Análises / Reviews do Polo (Coordenador de Polo)."""

from __future__ import annotations

from ninja import Router

from api.leadership.base import get_coordinator, get_coordinator_hub
from api.leadership.schemas import (
    AddressProofDecideOut,
    CandidateDetailOut,
    CandidateMeOut,
    CandidateSelfieDecideOut,
    CandidateSelfieDetailOut,
    EnrollmentRgDecideOut,
    EnrollmentSelfieDecideOut,
    ReviewsOut,
    SelfieDecideIn,
)
from users.roles.candidate import service as candidate_iface
from users.roles.enrollment import service as enrollment_iface
from users.roles.student import service as student_iface
from users.roles.training import service as training_iface

router = Router(tags=["review"])


@router.get("/reviews", response=ReviewsOut, summary="Central unificada de revisões do polo")
def list_reviews(request):
    """TUDO que espera análise/decisão do coordenador no polo."""
    coordinator = get_coordinator(request)
    hub = get_coordinator_hub(coordinator)
    enrollment_reviews = enrollment_iface.list_reviews_for_hub(hub=hub)

    def _norm(item: dict, type_: str, kind: str) -> dict:
        return {
            "external_id": item.get("external_id"),
            "type": type_,
            "kind": kind,
            **item,
        }

    enrollment_rg = [
        _norm(item, "enrollment", "rg")
        for item in enrollment_reviews.get("rg_reviews", [])
    ]
    enrollment_selfie = [
        _norm(item, "enrollment", "selfie")
        for item in enrollment_reviews.get("selfie_reviews", [])
    ]
    candidate_document = [
        _norm(item, "candidate", "document")
        for item in candidate_iface.list_document_reviews_for_hub(hub=hub)
    ]
    candidate_selfie = [
        _norm(item, "candidate", "selfie")
        for item in candidate_iface.list_selfie_reviews_for_hub(hub=hub)
    ]
    candidates_awaiting = [
        _norm(item, "candidate", "awaiting_approval")
        for item in candidate_iface.list_awaiting_approval_for_hub(hub=hub)
    ]
    locked_promoters = [
        _norm(item, "promoter", "locked_training")
        for item in training_iface.list_locked_promoters_for_hub(hub=hub)
    ]
    student_documents = [
        _norm(item, "student", "document")
        for item in student_iface.list_document_reviews_for_hub(hub=hub)
    ]

    return {
        "enrollment_rg": enrollment_rg,
        "enrollment_selfie": enrollment_selfie,
        "candidate_document": candidate_document,
        "candidate_selfie": candidate_selfie,
        "student_documents": student_documents,
        "candidates_awaiting_approval": candidates_awaiting,
        "locked_promoters": locked_promoters,
    }


@router.post(
    "/enrollments/{external_id}/rg/decide",
    response=EnrollmentRgDecideOut,
    summary="Decisão de RG em revisão",
)
def decide_enrollment_rg(request, external_id: str, payload: SelfieDecideIn):
    """Coordenador decide o RG de uma matrícula em revisão."""
    coordinator = get_coordinator(request)
    return enrollment_iface.decide_rg(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        approve=payload.approve,
        reason=payload.reason,
    )


@router.post(
    "/enrollments/{external_id}/address-proof/decide",
    response=AddressProofDecideOut,
    summary="Decisão de comprovante de residência",
)
def decide_enrollment_address_proof(request, external_id: str, payload: SelfieDecideIn):
    """Coordenador decide a justificativa de parentesco do comprovante."""
    coordinator = get_coordinator(request)
    return enrollment_iface.decide_address_proof_kinship(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        approve=payload.approve,
        reason=payload.reason,
    )


@router.post(
    "/enrollments/{external_id}/selfie/decide",
    response=EnrollmentSelfieDecideOut,
    summary="Decisão de selfie de matrícula",
)
def decide_enrollment_selfie(request, external_id: str, payload: SelfieDecideIn):
    """Coordenador decide a selfie de matrícula em revisão."""
    coordinator = get_coordinator(request)
    enr = enrollment_iface.decide_selfie(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        approve=payload.approve,
        reason=payload.reason,
    )
    return {
        "external_id": str(enr.external_id),
        "selfie_status": enr.selfie_status,
        "selfie_verified": enr.selfie_verified,
        "status": enr.status,
    }


@router.post(
    "/candidates/{external_id}/selfie/decide",
    response=CandidateSelfieDecideOut,
    summary="Decisão de selfie de candidato",
)
def decide_candidate_selfie(request, external_id: str, payload: SelfieDecideIn):
    """Coordenador decide a selfie de candidato em revisão."""
    coordinator = get_coordinator(request)
    cand = candidate_iface.decide_selfie(
        candidate_external_id=external_id,
        coordinator=coordinator,
        approve=payload.approve,
        reason=payload.reason,
    )
    return {
        "external_id": str(cand.external_id),
        "selfie_status": cand.selfie_status,
        "status": cand.status,
    }


@router.get(
    "/candidates/{external_id}/selfie",
    response=CandidateSelfieDetailOut,
    summary="Detalhe da selfie do candidato",
)
def get_candidate_selfie_for_coordinator(request, external_id: str):
    """Detalhe da selfie em revisão para decisão humana."""
    coordinator = get_coordinator(request)
    return candidate_iface.candidate_selfie_for_coordinator(
        candidate_external_id=external_id, coordinator=coordinator
    )


@router.post(
    "/candidates/{external_id}/document/decide",
    response=CandidateMeOut,
    summary="Decisão de documento de candidato",
)
def decide_candidate_document(request, external_id: str, payload: SelfieDecideIn):
    """Coordenador decide o documento em revisão do candidato."""
    coordinator = get_coordinator(request)
    return candidate_iface.decide_document(
        candidate_external_id=external_id,
        coordinator=coordinator,
        approve=payload.approve,
        reason=payload.reason,
    )


@router.post(
    "/candidates/{external_id}/document/reset",
    response=CandidateMeOut,
    summary="Destravar tipo de documento",
)
def reset_candidate_doc_type(request, external_id: str):
    """Zera o doc_type para destravar candidato que fixou tipo errado."""
    coordinator = get_coordinator(request)
    return candidate_iface.reset_doc_type(
        candidate_external_id=external_id, coordinator=coordinator
    )
