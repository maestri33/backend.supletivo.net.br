from __future__ import annotations

import datetime
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from users.documents import service as documents_iface
from users.blocks import service as blocks
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


def run_rg_validation(enrollment_id: int, slot: str) -> None:
    """Pipeline da task (plan/12). Idempotente: só age com validação `pending`.

    a) visão na foto do `slot` (é RG? lado certo? legível?) → reprovou/dúvida = para e notifica;
    b) seção completa (inteira aprovada OU frente+verso aprovadas) → OCR + extração (1 LLM);
    c) nome de outra pessoa → reprova; dúvida → review; ok → povoa campos VAZIOS →
       biometria → avança o wizard."""
    from pathlib import Path

    from users.roles import _document_ai as doc_ai

    enr = (
        Enrollment.objects.select_related("user", "hub", "hub__coordinator")
        .filter(id=enrollment_id)
        .first()
    )
    if enr is None:
        return
    user_ext = str(enr.user.external_id)
    rg = documents_iface.get_rg(user_ext)
    if rg is None or rg.validation_status != doc_ai.PENDING:
        return

    result = rg.validation_result or {}
    photos = dict(result.get("photos") or {})

    field = _RG_SLOT_FIELD.get(slot)
    path = getattr(rg, field, None) if field else None
    if path and (photos.get(slot) or {}).get("status") != doc_ai.APPROVED:
        fp = Path(settings.MEDIA_ROOT) / path
        if not fp.exists():
            return
        mime = _MIME_BY_EXT.get(fp.suffix.lstrip(".").lower(), "image/jpeg")
        # pré-tratamento (Victor 2026-06-11): endireita a foto ANTES de validar — EXIF + auto-rotação
        # por IA. Melhora visão/OCR/biometria e deixa o documento guardado reto. Best-effort.
        doc_ai.fix_orientation(str(fp), mime_type=mime, caller="enrollment.rg")
        status, reason = doc_ai.check_photo(
            fp.read_bytes(),
            side=_RG_SLOT_SIDE[slot],
            mime_type=mime,
            caller="enrollment.rg",
        )
        # merge FRESCO: a visão leva 10–60s e frente+verso viram 2 tasks em workers paralelos —
        # re-lê antes de gravar pra não perder o veredito que o outro worker salvou no meio tempo.
        rg.refresh_from_db()
        if rg.validation_status != doc_ai.PENDING:
            return  # outro worker (ou re-upload) já mudou o estado — não sobrescrever
        # G11: a foto deste slot trocou no meio tempo (re-upload) → o veredito é da foto velha,
        # descarta. `path` foi capturado no início; comparar com o atual identifica a troca (o
        # check de status sozinho não pega um re-upload que re-arma PENDING).
        if getattr(rg, field, None) != path:
            return
        result = rg.validation_result or {}
        photos = dict(result.get("photos") or {})
        photos[slot] = {"status": status, "reason": reason}
        result["photos"] = photos
        if status != doc_ai.APPROVED:
            _finish_rg(enr, rg, status, reason, result)
            return

    images = _rg_approved_images(rg, photos)
    if images is None:
        # esta foto passou, mas falta a outra — guarda o veredito e espera o resto da seção
        rg.validation_result = result
        rg.save(update_fields=["validation_result"])
        return
    _rg_extract_and_finish(enr, rg, result, images)


def _rg_approved_images(rg, photos: dict) -> list | None:
    """Imagens da seção completa e aprovada (inteira OU frente+verso), ou None se ainda falta."""
    from pathlib import Path

    from users.roles import _document_ai as doc_ai

    def ok(slot: str) -> bool:
        return (photos.get(slot) or {}).get("status") == doc_ai.APPROVED

    if rg.full_photo and ok("rg_full"):
        return [Path(settings.MEDIA_ROOT) / rg.full_photo]
    if rg.front_photo and rg.back_photo and ok("rg_front") and ok("rg_back"):
        return [
            Path(settings.MEDIA_ROOT) / rg.front_photo,
            Path(settings.MEDIA_ROOT) / rg.back_photo,
        ]
    return None


