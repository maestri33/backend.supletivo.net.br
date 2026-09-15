from __future__ import annotations

import datetime
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from hub.models import Hub
from users.documents import service as documents_iface
from users.exceptions import Conflict, Forbidden
from users.profiles import interface as profiles
from users.roles import _address_proof, _document_ai, _selfie
from users.roles.candidate.models import Candidate
from users.roles._selfie import SelfieStatus
from users.roles.candidate.common import (
    CandidateError,
    _S,
    _require,
    _set_status,
    logger,
)
from users.roles.candidate import service
from users.roles.candidate.serializers import me_dict
from users.roles.candidate.promotion import _promote_to_promoter

def reset_doc_type(*, candidate_external_id: str, coordinator) -> dict:
    """Coordenador DESTRAVA o candidato que fixou o tipo de documento errado (escolheu RG, só tem
    CNH — ou vice-versa). Sem isso o `upload_document_photo` barra com `DOC_TYPE_LOCKED` e a única
    saída seria recomeçar TODO o cadastro (perdendo perfil/endereço/pix) ou um db-edit (Victor
    2026-06-17: hierarquia user→coord, sem dev em prod).

    Zera o `doc_type` e volta pra etapa `documents` — perfil/endereço/pix ficam INTACTOS; a próxima
    foto define o tipo certo. O sub-doc antigo (RG/CNH) é ignorado (a leitura chaveia por `doc_type`)."""
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
    if cand.status in (_S.COMPLETED, _S.APPROVED, _S.REJECTED):
        raise Conflict(
            "O candidato já saiu da coleta — não dá pra trocar o tipo de documento.",
            code="WRONG_STATUS",
            extra={"expected_status": cand.status},
        )
    if not cand.doc_type:
        raise CandidateError(
            "O candidato ainda não escolheu um tipo de documento.",
            code="DOC_TYPE_NOT_SET",
        )
    cand.doc_type = None
    cand.save(update_fields=["doc_type", "updated_at"])
    if cand.status != _S.DOCUMENTS:
        service._set_status(cand, _S.DOCUMENTS)
    logger.info(
        "candidate.doc_type_reset",
        external_id=str(cand.external_id),
        by=str(coordinator.external_id),
    )
    service._notify_doc_type_reset(cand)
    return me_dict(cand)


def _notify_doc_type_reset(cand: Candidate) -> None:
    """Avisa o candidato que pode reenviar o documento (o coordenador destravou o tipo).

    wave-2: send_event lê teor/canais/is_tts do Template no DB. Channels default (Template decide)."""
    from notify.interface.events import send_event

    p = profiles.get(cand.user)
    try:
        send_event(
            "candidate.doc_type_reset",
            profile=p,
            idempotency_key=f"cand_doctype_reset_{cand.external_id}_{cand.updated_at.timestamp()}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_doc_type_reset_failed", error=str(exc))


def approve_candidate(*, candidate_external_id: str, coordinator) -> Candidate:
    """Coordenador do polo APROVA o candidato manualmente → promove candidate→PROMOTOR (reusa
    `_promote_to_promoter`). Fallback do caminho de selfie em `review` (a selfie aprovada já
    auto-promove, F2). Rejeição é SOFT (Victor 2026-06-17)."""
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
    # rejeição é SOFT: um candidato REJEITADO continua aguardando e pode ser aprovado depois. Só barra
    # quem ainda está na coleta (não concluiu). `SELFIE` entra: a selfie em review deixa o candidato
    # nessa etapa e o coordenador aprova por aqui.
    if cand.status not in (_S.COMPLETED, _S.REJECTED, _S.SELFIE):
        raise Conflict(
            "O candidato ainda não concluiu a coleta.",
            code="WRONG_STATUS",
            extra={"expected_status": _S.COMPLETED},
        )
    # `_promote_to_promoter` exige status SELFIE p/ `_set_status(APPROVED)` fazer sentido; se veio de
    # COMPLETED/REJECTED, normaliza pra SELFIE (transição de coleta → promoção).
    if cand.status != _S.SELFIE:
        _set_status(cand, _S.SELFIE)
    service._promote_to_promoter(cand)
    return cand


def reject_candidate(
    *, candidate_external_id: str, coordinator, reason: str | None = None
) -> Candidate:
    """Coordenador do polo REJEITA o candidato aguardando aprovação. Não promove; avisa o candidato."""
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
    # G10: mesmo conjunto de status que `approve_candidate` aceita. Antes exigia COMPLETED — estado
    # que o fluxo atual NUNCA atinge (a selfie aprovada auto-promove; a em review deixa em SELFIE),
    # então rejeitar dava 409 sempre. O candidato aguardando decisão está em SELFIE (selfie review).
    if cand.status not in (_S.COMPLETED, _S.REJECTED, _S.SELFIE):
        raise Conflict(
            "O candidato ainda não concluiu a coleta.",
            code="WRONG_STATUS",
            extra={"expected_status": _S.SELFIE},
        )
    service._set_status(cand, _S.REJECTED)
    service._notify_candidate_rejected(cand)
    logger.info("candidate.rejected", external_id=str(cand.external_id))
    return cand




def _notify_candidate_rejected(cand: Candidate) -> None:
    # wave-2: send_event lê teor/canais/is_tts do Template no DB. WhatsApp-only (legado).
    from notify.interface.events import send_event

    p = profiles.get(cand.user)
    try:
        send_event(
            "candidate.rejected",
            profile=p,
            channels_override=("whatsapp",),
            idempotency_key=f"candidate_rejected_{cand.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_rejected_failed", error=str(exc))


