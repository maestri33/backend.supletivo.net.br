"""Router de Candidatos aguardando aprovação (Coordenador de Polo)."""

from __future__ import annotations

from ninja import Router

from api.leadership.base import get_coordinator, get_coordinator_hub
from api.leadership.schemas import (
    CandidateActionOut,
    CandidateAwaitingOut,
    CandidateDetailOut,
    RejectIn,
)
from users.roles.candidate import service as candidate_iface

router = Router(tags=["candidate"])


@router.get("/candidates", response=list[CandidateAwaitingOut], summary="Candidatos aguardando aprovação")
def list_candidates_awaiting(request):
    """Fila de candidatos que concluíram coleta e aguardam aprovação."""
    coordinator = get_coordinator(request)
    hub = get_coordinator_hub(coordinator)
    return candidate_iface.list_awaiting_approval_for_hub(hub=hub)


@router.get("/candidates/{external_id}", response=CandidateDetailOut, summary="Detalhe de candidato para decisão")
def get_candidate_for_coordinator(request, external_id: str):
    """Detalhe do candidato para aprovação ou rejeição."""
    coordinator = get_coordinator(request)
    return candidate_iface.candidate_detail_for_coordinator(
        candidate_external_id=external_id, coordinator=coordinator
    )


@router.post("/candidates/{external_id}/approve", response=CandidateActionOut, summary="Aprovar candidato (vira promotor)")
def approve_candidate(request, external_id: str):
    """Aprova candidato e promove a promotor."""
    coordinator = get_coordinator(request)
    cand = candidate_iface.approve_candidate(
        candidate_external_id=external_id, coordinator=coordinator
    )
    return {"external_id": str(cand.external_id), "status": cand.status}


@router.post("/candidates/{external_id}/reject", response=CandidateActionOut, summary="Rejeitar candidato")
def reject_candidate(request, external_id: str, payload: RejectIn):
    """Rejeita candidato com motivo."""
    coordinator = get_coordinator(request)
    cand = candidate_iface.reject_candidate(
        candidate_external_id=external_id,
        coordinator=coordinator,
        reason=payload.reason,
    )
    return {"external_id": str(cand.external_id), "status": cand.status}
