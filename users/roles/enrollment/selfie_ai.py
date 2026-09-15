from __future__ import annotations

import datetime
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from users.exceptions import Conflict, Forbidden
from users.profiles import interface as profiles
from users.documents import service as documents_iface
from users.roles import _analysis, _selfie
from users.roles.enrollment.rg_decision import _notify_resolution
from users.roles.enrollment.models import Enrollment
from users.roles.enrollment.common import (
    EnrollmentError,
    _S,
    _SELFIE_EXT,
    _MIME_BY_EXT,
    _advance_to,
    _set_status,
    logger,
)
from users.roles.enrollment.serializers import me_dict
from users.roles.enrollment import service

def age_stale_selfies() -> int:
    from users.roles import _analysis

    return _analysis.age_stale_selfies(Enrollment, service._notify_selfie_review)



def run_selfie_validation(enrollment_id: int) -> None:
    """Pipeline da task da selfie (plan/13). Idempotente: só age com `selfie_status` pending.

    a) liveness (é selfie real? adianta ir pra biometria?) → b) face-match vs rosto do DOCUMENTO
    (biometria do RG) → c) reprovou? a visão olha DE NOVO e gera INSTRUÇÕES práticas de como ser
    aprovada (vão no GET e no notify) → d) notifies: aprovada→aluno; reprovada→aluno; review→coord."""
    from pathlib import Path

    from users.roles import _selfie

    enr = (
        Enrollment.objects.select_related("user", "hub", "hub__coordinator")
        .filter(id=enrollment_id)
        .first()
    )
    if enr is None or not enr.selfie_image or enr.status != _S.SELFIE:
        return
    if enr.selfie_status != _selfie.SelfieStatus.PENDING:
        return
    # G11: o discriminador da FOTO desta task. `selfie_status` não serve pra detectar re-upload —
    # o novo upload re-arma PENDING, então status seguiria PENDING e o veredito da foto velha
    # gravaria sobre a nova. `selfie_taken_at` muda a cada upload; é o que identifica a foto.
    started_taken_at = enr.selfie_taken_at
    fp = Path(settings.MEDIA_ROOT) / enr.selfie_image
    if not fp.exists():
        return
    content_type = _MIME_BY_EXT.get(fp.suffix.lstrip(".").lower(), "image/jpeg")
    image_bytes = fp.read_bytes()
    status, desc = _selfie.verify(image_bytes, content_type, caller="enrollment.selfie")
    # SOMAR (Victor 2026-06-05): face-match biométrico selfie × documento. Avança só se os dois passarem.
    status, desc = _selfie.add_face_match(
        user=enr.user,
        selfie_image_path=str(fp),
        caller="enrollment.selfie",
        liveness_status=status,
        liveness_desc=desc,
    )
    if status == _selfie.REJECTED:
        tips = _selfie.instructions(
            image_bytes, content_type, reason=desc, caller="enrollment.selfie"
        )
        if tips:
            desc = f"{desc}\n\nComo resolver: {tips}"
    enr.refresh_from_db(
        fields=["selfie_status", "selfie_reject_count", "selfie_taken_at"]
    )
    # G11: descarta se o status saiu de PENDING OU se a foto trocou (taken_at != o do início) —
    # este veredito é da foto velha. Sem o check de taken_at, um re-upload que re-armou PENDING
    # passava e o veredito da foto A gravava sobre a foto B (podia liberar B nunca validada).
    if (
        enr.selfie_status != _selfie.SelfieStatus.PENDING
        or enr.selfie_taken_at != started_taken_at
    ):
        return
    enr.selfie_status = status
    enr.selfie_verified = status == _selfie.APPROVED
    update_fields = [
        "selfie_status",
        "selfie_verified",
        "selfie_description",
        "updated_at",
    ]
    if status == _selfie.REJECTED:
        # F2: acumula os comentários da IA (não sobrescreve) e conta a reprovação — 5× sobe a flag.
        enr.selfie_reject_count += 1
        enr.selfie_description = _selfie.append_reason(
            enr.selfie_description, enr.selfie_reject_count, desc
        )
        update_fields.append("selfie_reject_count")
    else:
        enr.selfie_description = desc
    enr.save(update_fields=update_fields)
    logger.info(
        "enrollment.selfie_validated", enrollment=str(enr.external_id), status=status
    )
    service._save_selfie_audit(enr, status, desc)
    service._resolve_selfie(enr)


def _resolve_selfie(enr: Enrollment) -> None:
    """Reage ao veredito: aprovada→avisa o aluno + aguarda liberação; reprovada→avisa o aluno
    (com as instruções); revisão→avisa o coordenador."""
    from users.roles import _selfie

    if enr.selfie_status == _selfie.APPROVED:
        service._notify_selfie_approved(enr)
        _advance_to_release(enr)
    elif enr.selfie_status == _selfie.REJECTED:
        _notify_selfie_rejected(enr)
        # ponytail: signal post_save da Enrollment (selfie_status) cria bloco automaticamente.
        if enr.selfie_reject_count >= _selfie.MAX_REJECTS_BEFORE_MEETING:
            from users.profiles import interface as profiles

            profiles.set_selfie_needs_meeting(enr.user)
            _advance_to_release(enr)
    elif enr.selfie_status == _selfie.REVIEW:
        _notify_selfie_review(enr)


def _advance_to_release(enr: Enrollment) -> None:
    """Selfie enviada → AWAITING_RELEASE. Validação/biometria rodam em background."""
    if enr.status != _S.SELFIE:
        return
    _set_status(enr, _S.AWAITING_RELEASE)
    _notify_coordinator_awaiting(enr)


def decide_selfie(
    *,
    enrollment_external_id: str,
    coordinator,
    approve: bool,
    reason: str | None = None,
) -> Enrollment:
    """Coordenador do hub decide a selfie em REVISÃO (sim/não). aprova→aguarda liberação; reprova→refazer."""
    from users.roles import _selfie

    enr = _enrollment_for_coordinator(enrollment_external_id, coordinator)
    if enr.selfie_status != _selfie.REVIEW:
        raise EnrollmentError(
            "A selfie não está em revisão.",
            code="SELFIE_NOT_IN_REVIEW",
            extra={"selfie_status": enr.selfie_status},
        )
    note = (reason or "").strip() or (
        "aprovada pelo coordenador" if approve else "reprovada pelo coordenador"
    )
    enr.selfie_status = _selfie.APPROVED if approve else _selfie.REJECTED
    enr.selfie_verified = approve
    enr.selfie_description = note
    enr.save(
        update_fields=[
            "selfie_status",
            "selfie_verified",
            "selfie_description",
            "updated_at",
        ]
    )
    if approve:
        service._notify_selfie_approved(enr)  # notify também no aprovado (plan/13)
        _advance_to_release(enr)
    else:
        _notify_selfie_rejected(enr)
    return enr


def _notify_selfie_rejected(enr: Enrollment) -> None:
    # O comentário da IA (`selfie_description`) é INTERNO (auditoria) — NUNCA vai pro aluno; ele
    # recebe só a mensagem genérica do catálogo (Victor 2026-06-21).
    _notify_resolution(enr, "enrollment.selfie_rejected")


def _notify_selfie_approved(enr: Enrollment) -> None:
    _notify_resolution(enr, "enrollment.selfie_approved")


def _notify_selfie_review(enr: Enrollment) -> None:
    # wave-2: send_event lê teor/canais/is_tts do Template no DB. WhatsApp-only (coordenador).
    from notify.interface.events import send_event

    coord = enr.hub.coordinator
    if coord is None:
        return
    cp = profiles.get(coord)
    try:
        send_event(
            "enrollment.selfie_in_review",
            profile=cp,
            channels_override=("whatsapp",),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_selfie_review_failed", error=str(exc))


def _save_selfie_audit(enr: Enrollment, status: str, desc: str | None) -> None:
    """Auditoria da selfie (pedido do Victor 2026-06-21): por TENTATIVA, salva os recortes de rosto
    (selfie + documento) + o comentário CRU da IA num diretório com timestamp — nunca sobrescreve, pra
    o time conferir depois se a IA não está 'delirando'. Best-effort: jamais quebra o fluxo da matrícula."""
    try:
        import json
        from datetime import datetime, timezone as _tz
        from pathlib import Path

        from core.media import media_token, save_media_at
        from integrations.tools.biometric import face_match

        # pasta da tentativa por TOKEN aleatório (sem id no path — só o log liga token→enrollment).
        token = media_token()
        base = f"audit/selfie/{token}"

        if enr.selfie_image:
            sp = Path(settings.MEDIA_ROOT) / enr.selfie_image
            if sp.exists():
                crop = face_match.face_crop_bytes(str(sp))
                if crop:
                    save_media_at(path=f"{base}/rosto_selfie.jpg", data=crop)

        rg = documents_iface.get_rg(str(enr.user.external_id))
        doc_rel = (rg.full_photo or rg.front_photo) if rg else None
        if doc_rel:
            dp = Path(settings.MEDIA_ROOT) / doc_rel
            if dp.exists():
                crop = face_match.face_crop_bytes(str(dp))
                if crop:
                    save_media_at(path=f"{base}/rosto_documento.jpg", data=crop)

        save_media_at(
            path=f"{base}/veredito.json",
            data=json.dumps(
                {
                    "quando_utc": datetime.now(_tz.utc).isoformat(),
                    "status": str(status),
                    "comentario_ia": desc or "",
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )
        logger.info(
            "enrollment.selfie_audit_saved",
            enrollment=str(enr.external_id),
            user=str(enr.user.external_id),
            path=base,
        )
    except Exception as exc:  # noqa: BLE001 — auditoria nunca quebra o fluxo
        logger.warning("enrollment.selfie_audit_failed", error=str(exc))


def _save_selfie(enr: Enrollment, image_bytes: bytes, content_type: str) -> str:
    from core.media import replace_media

    ext = _SELFIE_EXT.get(content_type, "jpg")
    # G13: re-upload deleta a selfie anterior (PII não fica órfã no storage).
    return replace_media(
        old=enr.selfie_image, prefix="selfie", data=image_bytes, ext=ext
    )


def _notify_coordinator_awaiting(enr: Enrollment) -> None:
    # wave-2: send_event lê teor/canais/is_tts do Template no DB. WhatsApp-only (coordenador).
    from notify.interface.events import send_event

    coord = enr.hub.coordinator
    if coord is None:
        return
    cp = profiles.get(coord)
    try:
        send_event(
            "enrollment.awaiting_release",
            profile=cp,
            channels_override=("whatsapp",),
            idempotency_key=f"enr_awaiting_{enr.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("enrollment.notify_coord_failed", error=str(exc))


