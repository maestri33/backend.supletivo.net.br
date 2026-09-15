from __future__ import annotations

import datetime
from django.conf import settings
from django.utils import timezone

from hub.models import Hub
from users.documents import service as documents_iface
from users.exceptions import Conflict, Forbidden
from users.profiles import interface as profiles
from users.roles import _address_proof, _document_ai, _selfie
from users.roles._selfie import SelfieStatus
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import (
    CandidateError,
    _S,
    logger,
)
from users.roles.candidate import service

def _candidate_document_dict(cand) -> dict | None:
    """Bloco do DOCUMENTO (RG/CNH) do candidato pro coordenador decidir VENDO — fotos + status IA +
    motivo. Espelha `enrollment._rg_section_dict`. None se não há doc_type/sub-doc ainda."""
    if not cand.doc_type:
        return None
    sub = documents_iface.get_doc_sub(str(cand.user.external_id), cand.doc_type)
    if sub is None:
        return None
    result = (getattr(sub, "validation_result", None) or {}) if sub else {}
    has_photo = bool(sub.front_photo or sub.back_photo or sub.full_photo)
    return {
        "doc_type": cand.doc_type,
        "front_photo": sub.front_photo,
        "back_photo": sub.back_photo,
        "full_photo": sub.full_photo,
        # canônico (proposta #4): sem foto → sem análise em voo (não mostra "extraindo…")
        "analysis_status": sub.validation_status if has_photo else None,
        "analysis_reason": result.get("reason") if isinstance(result, dict) else None,
    }


def candidate_detail_for_coordinator(
    *, candidate_external_id: str, coordinator
) -> dict:
    """Detalhe do candidato aguardando aprovação — pro coordenador decidir VENDO (perfil + coleta).
    Gate: ser o coordenador do polo do candidato."""
    cand = (
        Candidate.objects.filter(external_id=candidate_external_id)
        .select_related("hub", "user")
        .first()
    )
    if cand is None:
        raise CandidateError("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if cand.hub.coordinator_id != coordinator.id:
        raise Forbidden(
            "Você não coordena o polo deste candidato.", code="NOT_HUB_COORDINATOR"
        )
    p = profiles.get(cand.user)
    return {
        "document": _candidate_document_dict(cand),
        "external_id": str(cand.external_id),
        "status": cand.status,
        "user": {
            "external_id": str(cand.user.external_id),
            "name": p.name if p else None,
            "cpf": p.cpf if p else None,
            "phone": p.phone if p else None,
            "email": p.email if p else None,
        },
        "doc_type": cand.doc_type,
        "mother_name": p.mother_name if p else None,
        "father_name": p.father_name if p else None,
        "marital_status": p.marital_status if p else None,
        "birthplace": p.birthplace if p else None,
        "nationality": p.nationality if p else None,
        "pix_key": p.pix_key if p else None,
        "pix_key_type": p.pix_key_type if p else None,
        "pix_validated": cand.pix_validated,
        "selfie_status": cand.selfie_status,
        "selfie_image": cand.selfie_image,
        "selfie_description": cand.selfie_description,
    }


def list_awaiting_approval_for_hub(*, hub) -> list[dict]:
    """Candidatos do polo aguardando a APROVAÇÃO do coordenador. Pro inbox/fila.

    Inclui COMPLETED **e REJECTED** (Victor 2026-06-17: rejeição é SOFT — "aguarda ser aprovado";
    o rejeitado não some, fica na fila e pode ser aprovado depois). `rejected: true` marca quem o
    coordenador já tinha rejeitado, pro front mostrar diferente."""
    out = []
    # G10: inclui SELFIE-em-review (o estado real de "aguardando decisão do coordenador"), além de
    # COMPLETED/REJECTED. Antes só COMPLETED/REJECTED, e como COMPLETED é inatingível, o inbox ficava
    # vazio — o coordenador nunca via os candidatos que precisavam da decisão dele.
    from django.db.models import Q

    from users.roles._selfie import SelfieStatus

    qs = (
        Candidate.objects.filter(hub=hub)
        .filter(
            Q(status__in=[_S.COMPLETED, _S.REJECTED])
            | Q(status=_S.SELFIE, selfie_status=SelfieStatus.REVIEW)
        )
        .select_related("user")
        .order_by("updated_at")
    )
    rows = list(qs)
    pmap = profiles.get_map([cand.user for cand in rows])
    for cand in rows:
        p = pmap.get(cand.user_id)
        out.append(
            {
                "external_id": str(cand.external_id),
                "name": p.name if p else None,
                "since": cand.updated_at.isoformat() if cand.updated_at else None,
                "rejected": cand.status == _S.REJECTED,
            }
        )
    return out


def list_selfie_reviews_for_hub(*, hub) -> list[dict]:
    """Candidatos do polo com a selfie parada em REVISÃO (decisão do coordenador — plan/14).

    Cada item aponta pro POST de decisão que já existe (`/candidates/{ext}/selfie/decide`).
    Antes, varre PENDING órfão (worker morto) → review (`_sweep_stale_reviews`)."""
    from users.roles._selfie import SelfieStatus

    _sweep_stale_reviews(hub)
    out = []
    qs = (
        Candidate.objects.filter(hub=hub, selfie_status=SelfieStatus.REVIEW)
        .select_related("user")
        .order_by("updated_at")
    )
    rows = list(qs)
    pmap = profiles.get_map([cand.user for cand in rows])
    for cand in rows:
        p = pmap.get(cand.user_id)
        out.append(
            {
                "external_id": str(cand.external_id),
                "name": p.name if p else None,
                "since": cand.updated_at.isoformat(),
            }
        )
    return out


def candidate_selfie_for_coordinator(
    *, candidate_external_id: str, coordinator
) -> dict:
    """Tela de DETALHE da selfie do candidato em REVISÃO pro coordenador decidir (plan/15 D2).

    Devolve a foto + `analysis_status`/`analysis_reason` (motivo da IA — útil pra aprovar/
    reprovar com contexto). O coordenador decide VENDO, não às cegas (antes decidia só com o
    nome na fila). Gate: o coord precisa ser o do polo do candidato (mesma régua do decide)."""
    from users.roles import _selfie

    cand = (
        Candidate.objects.filter(external_id=candidate_external_id)
        .select_related("hub", "user")
        .first()
    )
    if cand is None:
        raise CandidateError("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if cand.hub.coordinator_id != coordinator.id:
        raise CandidateError(
            "Você não coordena o polo deste candidato.", code="NOT_HUB_COORDINATOR"
        )
    p = profiles.get(cand.user)
    return {
        "external_id": str(cand.external_id),
        "user": {
            "external_id": str(cand.user.external_id),
            "name": p.name if p else None,
            "cpf": p.cpf if p else None,
        },
        "selfie": _selfie_dict(cand),
        # "em revisão" = o que a IA mandou pra fila (TTL ou dúvida). Se NÃO está em REVIEW,
        # o detalhe existe mas o coordenador não tem o que decidir (front avisa).
        "in_review": cand.selfie_status == _selfie.REVIEW,
    }
