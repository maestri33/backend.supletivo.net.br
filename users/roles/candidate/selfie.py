from __future__ import annotations

import datetime
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from users.documents import service as documents_iface
from users.exceptions import Conflict, Forbidden
from users.profiles import interface as profiles
from users.roles import _address_proof, _document_ai, _selfie
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import (
    CandidateError,
    _S,
    _SELFIE_EXT,
    _MIME_BY_EXT,
    _require,
    _set_status,
    logger,
)
from users.roles.candidate import service
from users.roles.candidate.serializers import me_dict
from users.roles.candidate.promotion import _complete_candidate, _promote_to_promoter

def get_selfie(*, user_external_id: str) -> dict:
    """GET da selfie/ASSINATURA (plan/15 C). Espelha a seção do enrollment: foto, taken_at,
    `analysis_status` (canônico) + `status` (alias), `analysis_reason` (instruções se reprovou),
    `expires_at` (TTL do `pending`).

    LEITURA PURA (idempotência HTTP): NÃO muta status nem notifica. O envelhecimento do `pending`
    estourado → `review` + notify roda no job agendado `tasks.age_stale_selfies` (Django-Q),
    fora do caminho do GET (antes um retry/crawler/preflight disparava a transição)."""
    cand = _require(user_external_id, _S.PIX, _S.EDUCATION, _S.SELFIE, _S.COMPLETED)
    return _selfie_dict(cand)


def set_selfie(
    *,
    user_external_id,
    image_bytes: bytes,
    content_type="image/jpeg",
    consent_ip: str | None = None,
    consent_user_agent: str | None = None,
) -> dict:
    """Selfie ("assinar") — ASSÍNCRONA (plan/15 C, espelha o enrollment):

    1. salva a foto
    2. marca `selfie_status=PENDING` + `selfie_taken_at=now`
    3. ENFILEIRA `users.roles.candidate.tasks.validate_candidate_selfie` (Django-Q)
    4. devolve o **ack** `{stored, analysis_status:"pending", poll_after_ms, expires_at}`

    O front acompanha pelo `GET /candidate/selfie` até virar `approved`/`rejected`/`review`. A
    pipeline roda fora do request (liveness → face-match vs documento → instruções se reprovou);
    o veredito final decide promover / notificar o candidato / escalar pro coordenador."""
    from django.utils import timezone

    from users.consent import PROMOTER_CONTRACT
    from users.roles import _selfie

    cand = _require(user_external_id, _S.EDUCATION, _S.SELFIE)
    cand.selfie_image = _save_selfie(cand, image_bytes, content_type)
    cand.selfie_taken_at = timezone.now()
    cand.selfie_status = _selfie.SelfieStatus.PENDING
    cand.selfie_verified = False
    cand.selfie_description = None
    # consentimento LGPD (lane #6): a selfie enviada com sucesso É o aceite do contrato.
    cand.consent_accepted = True
    cand.contract_version = PROMOTER_CONTRACT.version
    cand.contract_hash = PROMOTER_CONTRACT.hash
    cand.consent_ip = consent_ip
    cand.consent_user_agent = consent_user_agent
    cand.consent_accepted_at = cand.selfie_taken_at
    # BUG-4 (M2c FE-painel, 2026-06-16): worker exige `status==SELFIE` (`run_selfie_validation`
    # linha 1120) — se não avançar, bail-out silencioso e o pending vira review via TTL reconcile.
    # Espelha o `enrollment.set_selfie` (gate em `_S.SELFIE`, advance feito no `set_education`).
    if cand.status == _S.EDUCATION:
        _set_status(cand, _S.SELFIE)
    cand.save()
    from core.tasks import async_task

    async_task("users.roles.candidate.tasks.validate_candidate_selfie", cand.id)
    return _selfie_ack(cand)


def _selfie_ack(cand: Candidate) -> dict:
    """Ack canônico (mesma régua do `enrollment.selfie_ack`) pra responder no POST."""
    from users.roles import _analysis

    return {
        "stored": True,
        "analysis_status": _analysis.PENDING,
        "poll_after_ms": _analysis.poll_after_ms(),
        "expires_at": _analysis.expires_at(cand.selfie_taken_at).isoformat()
        if cand.selfie_taken_at
        else None,
    }


def _selfie_dict(cand: Candidate) -> dict:
    """Bloco da selfie (GET /selfie e o bloco `selfie` do /me — espelha enrollment/_selfie_dict)."""
    from users.roles import _analysis

    status = cand.selfie_status if cand.selfie_image else None
    return {
        "exists": bool(cand.selfie_image),
        "photo": cand.selfie_image,
        "taken_at": cand.selfie_taken_at.isoformat() if cand.selfie_taken_at else None,
        "status": status,
        # canônico unificado (mesma régua do enrollment — proposta API #4): alias `status`/`description`
        # mantidos pra compat; `expires_at` = TTL do `pending` (proposta #2).
        "analysis_status": status,
        "analysis_reason": cand.selfie_description,
        "expires_at": (
            _analysis.expires_at(cand.selfie_taken_at).isoformat()
            if status == _analysis.PENDING and cand.selfie_taken_at
            else None
        ),
        "verified": cand.selfie_verified,
        "description": cand.selfie_description,
    }


def _notify_selfie_approved(cand: Candidate) -> None:
    """Notify do aprovado (plan/15 C — paridade com `enrollment.selfie_approved`). Sem TTS.

    wave-2: send_event lê teor/canais/is_tts do Template no DB."""
    from notify.interface.events import send_event

    p = profiles.get(cand.user)
    try:
        send_event(
            "candidate.selfie_approved",
            profile=p,
            idempotency_key=f"candidate_selfie_approved_{cand.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_selfie_approved_failed", error=str(exc))




def decide_selfie(
    *, candidate_external_id: str, coordinator, approve: bool, reason: str | None = None
) -> Candidate:
    """Coordenador do hub decide a selfie em REVISÃO (sim/não). aprova→promove; reprova→avisa refazer."""
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
    if cand.selfie_status != _selfie.REVIEW:
        raise CandidateError(
            "A selfie não está em revisão.",
            code="SELFIE_NOT_IN_REVIEW",
            extra={"selfie_status": cand.selfie_status},
        )
    note = (reason or "").strip() or (
        "aprovada pelo coordenador" if approve else "reprovada pelo coordenador"
    )
    cand.selfie_status = _selfie.APPROVED if approve else _selfie.REJECTED
    cand.selfie_verified = approve
    cand.selfie_description = note
    cand.save(
        update_fields=[
            "selfie_status",
            "selfie_verified",
            "selfie_description",
            "updated_at",
        ]
    )
    if approve:
        service._complete_candidate(cand)
    else:
        service._notify_selfie_rejected(cand)
    return cand


def _notify_selfie_rejected(cand: Candidate) -> None:
    # wave-2: send_event lê teor/canais/is_tts do Template no DB. WhatsApp-only (legado).
    from notify.interface.events import send_event

    p = profiles.get(cand.user)
    try:
        send_event(
            "candidate.selfie_rejected",
            profile=p,
            channels_override=("whatsapp",),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_selfie_rejected_failed", error=str(exc))


def _notify_selfie_review(cand: Candidate) -> None:
    # wave-2: send_event lê teor/canais/is_tts do Template no DB. WhatsApp-only (coordenador).
    from notify.interface.events import send_event

    coord = cand.hub.coordinator
    if coord is None:
        return
    cp = profiles.get(coord)
    try:
        send_event(
            "candidate.selfie_in_review",
            profile=cp,
            channels_override=("whatsapp",),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_selfie_review_failed", error=str(exc))

