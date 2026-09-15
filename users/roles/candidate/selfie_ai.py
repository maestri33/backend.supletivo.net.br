from __future__ import annotations

import datetime
from django.conf import settings
from django.utils import timezone

from users.profiles import interface as profiles
from users.roles import _selfie
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import (
    _S,
    _SELFIE_EXT,
    _MIME_BY_EXT,
    _set_status,
    logger,
)
from users.roles.candidate import service

def age_stale_selfies() -> int:
    from users.roles import _analysis

    from users.roles.candidate import service
    return _analysis.age_stale_selfies(Candidate, service._notify_selfie_review)


def run_selfie_validation(candidate_id: int) -> None:
    """Pipeline async da selfie do CANDIDATO (plan/15 C, espelha `enrollment.run_selfie_validation`).

    a) liveness (é selfie real? vale ir pra biometria?)
    b) face-match biométrico selfie × documento (do candidato — RG ou CNH aprovada)
    c) reprovou? a visão gera INSTRUÇÕES práticas de como ser aprovada
    d) 3 estados: aprovada→promove training; reprovada→avisa candidato; review→avisa coord.

    Idempotente: só age com `selfie_status` PENDING (re-upload no meio tempo descarta o veredito)."""
    from pathlib import Path

    from users.roles import _selfie

    cand = (
        Candidate.objects.select_related("user", "hub", "hub__coordinator")
        .filter(id=candidate_id)
        .first()
    )
    if cand is None or not cand.selfie_image or cand.status != _S.SELFIE:
        return
    if cand.selfie_status != _selfie.SelfieStatus.PENDING:
        return
    # G11: discriminador da foto desta task (status não detecta re-upload — ele re-arma PENDING).
    started_taken_at = cand.selfie_taken_at
    fp = Path(settings.MEDIA_ROOT) / cand.selfie_image
    if not fp.exists():
        return
    image_bytes = fp.read_bytes()
    # G21/#13: mime derivado da extensão (como o enrollment) — antes era "image/jpeg" hardcoded, e
    # uma selfie PNG/WebP ia pra visão/biometria rotulada como JPEG.
    content_type = _MIME_BY_EXT.get(fp.suffix.lstrip(".").lower(), "image/jpeg")
    status, desc = _selfie.verify(image_bytes, content_type, caller="candidate.selfie")
    # SOMAR (Victor 2026-06-05): face-match biométrico selfie × documento.
    status, desc = _selfie.add_face_match(
        user=cand.user,
        selfie_image_path=str(fp),
        caller="candidate.selfie",
        liveness_status=status,
        liveness_desc=desc,
    )
    if status == _selfie.REJECTED:
        tips = _selfie.instructions(
            image_bytes, content_type, reason=desc, caller="candidate.selfie"
        )
        if tips:
            desc = f"{desc}\n\nComo resolver: {tips}"
    cand.refresh_from_db(
        fields=["selfie_status", "selfie_reject_count", "selfie_taken_at"]
    )
    # G11: descarta se saiu de PENDING OU se a foto trocou (taken_at != o do início). Sem o check de
    # taken_at, um re-upload que re-armou PENDING passava e o veredito da foto velha gravava sobre a
    # nova (mesma classe do enrollment; o candidate estava com o mesmo bug).
    if (
        cand.selfie_status != _selfie.SelfieStatus.PENDING
        or cand.selfie_taken_at != started_taken_at
    ):
        return
    cand.selfie_status = status
    cand.selfie_verified = status == _selfie.APPROVED
    update_fields = [
        "selfie_status",
        "selfie_verified",
        "selfie_description",
        "updated_at",
    ]
    if status == _selfie.REJECTED:
        # F2: acumula os comentários da IA (não sobrescreve) e conta a reprovação — 5× sobe a flag.
        cand.selfie_reject_count += 1
        cand.selfie_description = _selfie.append_reason(
            cand.selfie_description, cand.selfie_reject_count, desc
        )
        update_fields.append("selfie_reject_count")
    else:
        cand.selfie_description = desc
    cand.save(update_fields=update_fields)
    logger.info(
        "candidate.selfie_validated", candidate=str(cand.external_id), status=status
    )
    service._resolve_selfie(cand)


def _save_selfie(cand: Candidate, image_bytes: bytes, content_type: str) -> str:
    from pathlib import Path

    ext = _SELFIE_EXT.get(content_type, "jpg")
    rel = f"candidate/{cand.external_id}/selfie.{ext}"
    fp = Path(settings.MEDIA_ROOT) / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(image_bytes)
    return rel


def _resolve_selfie(cand: Candidate) -> None:
    """Reage ao veredito da selfie: aprovada→notifica+promove; reprovada→avisa candidato; revisão→avisa coordenador."""
    from users.roles import _selfie

    if cand.selfie_status == _selfie.APPROVED:
        service._notify_selfie_approved(cand)
        service._complete_candidate(cand)
    elif cand.selfie_status == _selfie.REJECTED:
        service._notify_selfie_rejected(cand)
        # F2: 5ª reprovação → sobe a flag nível-pessoa (não bloqueia) e SEGUE promovendo — o encontro
        # presencial fica pro fim do curso (gate em `student._maybe_release_exam`).
        if cand.selfie_reject_count >= _selfie.MAX_REJECTS_BEFORE_MEETING:
            profiles.set_selfie_needs_meeting(cand.user)
            service._complete_candidate(cand)
    elif cand.selfie_status == _selfie.REVIEW:
        service._notify_selfie_review(cand)


