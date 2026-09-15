from __future__ import annotations

import datetime
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from users.blocks import service as blocks
from users.documents import service as documents_iface
from users.profiles import interface as profiles
from users.roles import _analysis, _document_ai
from users.roles.enrollment.models import Enrollment
from users.roles.enrollment.common import (
    _S,
    _advance_to,
    _RG_SLOT_FIELD,
    _RG_SLOT_SIDE,
    _MIME_BY_EXT,
    logger,
)
from users.roles.enrollment import service

def _rg_extract_and_finish(enr: Enrollment, rg, result: dict, images: list) -> None:
    """OCR + extração (1 LLM): confere o nome (tolerância de casamento) e povoa os campos."""
    from users.roles import _document_ai as doc_ai

    p = profiles.get(enr.user)
    try:
        ocr_text = doc_ai.ocr_images(
            [fp.read_bytes() for fp in images], caller="enrollment.rg"
        )
        data = doc_ai.extract_rg(
            ocr_text, holder_name=(p.name if p else None), caller="enrollment.rg"
        )
    except Exception as exc:  # noqa: BLE001 — IA fora do ar na extração → review (humano decide)
        logger.warning(
            "enrollment.rg_extract_failed",
            enrollment=str(enr.external_id),
            error=str(exc)[:200],
        )
        _finish_rg(
            enr,
            rg,
            doc_ai.REVIEW,
            "IA indisponível na extração dos dados — enviado para revisão manual do coordenador.",
            result,
        )
        return
    # guard do worker-zumbi (Victor 2026-06-17): o OCR + extração acima levam ~15s; se NESSE meio o
    # sweep do TTL (worker que ficou lento) ou o coordenador já decidiu, NÃO sobrescrever a decisão.
    # Mesma régua que a visão já aplica nas linhas 543-545 — aqui fecha a janela do estágio de extração.
    rg.refresh_from_db()
    if rg.validation_status != doc_ai.PENDING:
        return
    result["extracted"] = data
    match = str(data.get("name_match") or "").strip().lower()
    name_reason = (data.get("name_reason") or "").strip()
    if match in ("nao", "não", "no"):
        _finish_rg(
            enr,
            rg,
            doc_ai.REJECTED,
            f"O nome no documento não confere com o do cadastro. {name_reason}".strip(),
            result,
        )
        return
    if match not in ("sim", "yes"):
        _finish_rg(
            enr,
            rg,
            doc_ai.REVIEW,
            f"Não deu pra confirmar o nome do titular. {name_reason}".strip(),
            result,
        )
        return
    _apply_rg_extracted(enr, rg, data)
    _finish_rg(enr, rg, doc_ai.APPROVED, name_reason or "Documento validado.", result)
    _notify_rg_approved(enr)  # notify também no aprovado automático (plan/13)
    _rg_post_approval(enr, rg)


def _apply_rg_extracted(enr: Enrollment, rg, data: dict) -> None:
    """Povoa SÓ campos vazios (Victor: não sobrescrever): doc RG + perfil da matrícula + nascimento."""
    from datetime import date

    def _clean(value, limit: int):
        s = str(value).strip()
        return s[:limit] if s else None

    def _date(value):
        try:
            return date.fromisoformat(str(value)) if value else None
        except ValueError:
            return None

    changed = []
    if not rg.number and data.get("number"):
        rg.number = _clean(data["number"], 30)
        changed.append("number")
    if not rg.issuing_agency and data.get("issuing_agency"):
        rg.issuing_agency = _clean(data["issuing_agency"], 50)
        changed.append("issuing_agency")
    if not rg.issue_date:
        d = _date(data.get("issue_date"))
        if d:
            rg.issue_date = d
            changed.append("issue_date")
    if changed:
        rg.save(update_fields=changed)

    # filiação/naturalidade + nascimento extraídos do documento → CENTRALIZADO no Profile (Victor
    # 2026-06-16: a identidade mora SÓ no Profile, nunca espalhada no enrollment).
    profiles.fill_identity(
        enr.user,
        mother_name=_clean(data["mother_name"], 255)
        if data.get("mother_name")
        else None,
        father_name=_clean(data["father_name"], 255)
        if data.get("father_name")
        else None,
        birthplace=_clean(data["birthplace"], 128) if data.get("birthplace") else None,
        birth_date=_date(data.get("birth_date")),
    )


def _finish_rg(
    enr: Enrollment, rg, status: str, reason: str | None, result: dict
) -> None:
    """Grava o veredito (justificativa SEMPRE — plan/9) + dispara o notify do estado."""
    from django.utils import timezone

    from users.roles import _document_ai as doc_ai

    result["reason"] = reason
    rg.validation_status = status
    rg.validation_result = result
    rg.validated_at = timezone.now()
    rg.save(update_fields=["validation_status", "validation_result", "validated_at"])
    logger.info(
        "enrollment.rg_validated", enrollment=str(enr.external_id), status=status
    )
    if status == doc_ai.REJECTED:
        _notify_rg_rejected(enr, reason)
        # ponytail: signal post_save do RG cria o bloco automaticamente — não precisa criar aqui.
    elif status == doc_ai.REVIEW:
        _notify_rg_review(enr, reason)


def _rg_post_approval(enr: Enrollment, rg) -> None:
    """Aprovado → AVANÇA o wizard PRIMEIRO, biometria best-effort DEPOIS: um crash da biometria
    (InsightFace/onnxruntime pode matar o worker) NÃO pode perder o avanço (Victor 2026-06-16).

    Recorte (plan/13): InsightFace direto (já detecta/recorta); NÃO achou rosto → a visão
    localiza a região da foto do titular, o Pillow recorta e tenta de novo. Nunca trava o fluxo."""
    # o doc já está aprovado → avança rg→address ANTES de tocar na biometria.
    _advance_rg(enr, str(enr.user.external_id))

    from pathlib import Path

    from integrations.tools.biometric import service as biometric

    from users.roles import _document_ai as doc_ai

    face_path = rg.front_photo or rg.full_photo
    face_slot = "rg_front" if rg.front_photo else "rg_full"
    if face_path:
        full = Path(settings.MEDIA_ROOT) / face_path
        enrolled = biometric.try_enroll_document(
            user=enr.user,
            slot=face_slot,
            image_path=str(full),
            caller="enrollment.document",
        )
        if enrolled is None and full.exists():
            cropped = doc_ai.crop_face(full.read_bytes(), caller="enrollment.rg")
            if cropped:
                from core.media import save_media

                crop_rel = save_media(prefix="documents", data=cropped, ext="jpg")
                biometric.try_enroll_document(
                    user=enr.user,
                    slot="rg_front",
                    image_path=str(Path(settings.MEDIA_ROOT) / crop_rel),
                    caller="enrollment.document_crop",
                )


def run_rg_fill(enrollment_id: int) -> None:
    """Pós-aprovação do coordenador: OCR+extração best-effort SÓ pra preencher campos vazios.

    A aprovação humana é FINAL — aqui não há veto (o `name_match` fica só registrado). Falhou
    a IA → o aluno digita o que faltou (`missing_fields` no /me)."""
    from pathlib import Path

    from users.roles import _document_ai as doc_ai

    enr = (
        Enrollment.objects.select_related("user", "hub")
        .filter(id=enrollment_id)
        .first()
    )
    if enr is None:
        return
    user_ext = str(enr.user.external_id)
    rg = documents_iface.get_rg(user_ext)
    if rg is None or rg.validation_status != doc_ai.APPROVED:
        return
    result = rg.validation_result or {}
    if result.get("extracted"):
        return
    images = [
        Path(settings.MEDIA_ROOT) / p
        for p in ([rg.full_photo] if rg.full_photo else [rg.front_photo, rg.back_photo])
        if p
    ]
    images = [fp for fp in images if fp.exists()]
    if not images:
        return
    p = profiles.get(enr.user)
    try:
        ocr_text = doc_ai.ocr_images(
            [fp.read_bytes() for fp in images], caller="enrollment.rg_fill"
        )
        data = doc_ai.extract_rg(
            ocr_text, holder_name=(p.name if p else None), caller="enrollment.rg_fill"
        )
    except Exception as exc:  # noqa: BLE001 — best-effort: falhou → o aluno digita
        logger.warning(
            "enrollment.rg_fill_failed",
            enrollment=str(enr.external_id),
            error=str(exc)[:200],
        )
        return
    result["extracted"] = data
    rg.validation_result = result
    rg.save(update_fields=["validation_result"])
    _apply_rg_extracted(enr, rg, data)
    _advance_rg(enr, user_ext)

