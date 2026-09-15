"""Gravação padronizada de mídia sob o MEDIA_ROOT, via `default_storage`.

Um writer único pra TODOS os funis (documentos, selfie, aluno, auditoria): o caminho é
`"<prefix>/<token>.<ext>"` com **token aleatório** — NUNCA `external_id`/slot no path (pedido do
Victor 2026-06-21: o `external_id` vaza pro frontend, então caminho por id é enumerável; a mídia é
sempre referenciada pelo campo salvo no DB, jamais reconstruída por id). Trocar `default_storage`
um dia (S3/objeto) passa a valer pra todos os writers de uma vez.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


def is_private_media(path: str) -> bool:
    """True se o 1º segmento de `path` está em `settings.MEDIA_PRIVATE_PREFIXES` (Lane #4, gate de
    /media/ em `core/media_views.py`). O resto (ex.: `training/`, `ai/`) é público."""
    prefix = path.strip("/").split("/", 1)[0]
    return prefix in settings.MEDIA_PRIVATE_PREFIXES


def media_token() -> str:
    """Token aleatório, URL-safe e não-enumerável, pro nome do arquivo/pasta de mídia."""
    return secrets.token_urlsafe(16)


def owner_external_id_for_path(path: str) -> str | None:
    """external_id do USER dono do arquivo de mídia privada em `path`, ou None se não houver dono
    resolvível (path órfão, ou prefixo sem vínculo a usuário — ex.: `receipt`, comprovante de payout
    a terceiro livre).

    Gate de DONO do /media/ privado (`core/media_views.py`): como NÃO existe índice `token → dono`
    (o path é `"<prefix>/<token>.<ext>"`, sem external_id — `save_media`), amarramos o dono fazendo
    MATCH EXATO do path relativo nos campos que guardam esses caminhos, por prefixo. É o vínculo mais
    forte possível SEM migration. ponytail: match exato de varchar sem índice (scan), mas 1 request
    de mídia privada por vez; se virar hot-path, promova a tabela `token→dono` no `save_media`.
    """
    from django.db.models import Q

    prefix = path.strip("/").split("/", 1)[0]

    if prefix == "documents":
        from users.documents.models import RG, CNH, AddressProof, Certificate, Military

        photo_models = (
            (RG, ("front_photo", "back_photo", "full_photo")),
            (CNH, ("front_photo", "back_photo", "full_photo")),
            (Certificate, ("photo",)),
            (AddressProof, ("photo",)),
            (Military, ("photo",)),
        )
        for model, fields in photo_models:
            q = Q()
            for field in fields:
                q |= Q(**{field: path})
            row = model.objects.filter(q).select_related("document__user").first()
            if row is not None:
                return str(row.document.user.external_id)
        return None

    if prefix == "selfie":
        from users.roles.candidate.models import Candidate
        from users.roles.enrollment.models import Enrollment

        for model in (Enrollment, Candidate):
            row = model.objects.filter(selfie_image=path).select_related("user").first()
            if row is not None:
                return str(row.user.external_id)
        return None

    if prefix == "diploma":
        from users.roles.student.models import StudentDiploma

        row = (
            StudentDiploma.objects.filter(
                Q(diploma_file=path) | Q(transcript_file=path)
            )
            .select_related("student__user")
            .first()
        )
        return str(row.student.user.external_id) if row is not None else None

    if prefix == "student":
        from users.roles.student.models import StudentDiploma, StudentDocument

        doc = (
            StudentDocument.objects.filter(photo=path)
            .select_related("student__user")
            .first()
        )
        if doc is not None:
            return str(doc.student.user.external_id)
        dip = (
            StudentDiploma.objects.filter(pickup_photo=path)
            .select_related("student__user")
            .first()
        )
        return str(dip.student.user.external_id) if dip is not None else None

    return None  # receipt/ e qualquer outro prefixo: sem dono de USER resolvível.


def save_media(*, prefix: str, data: bytes, ext: str, token: str | None = None) -> str:
    """Salva `data` em `"<prefix>/<token>.<ext>"` e devolve o caminho RELATIVO (pro campo do DB)."""
    tok = token or media_token()
    path = f"{prefix.strip('/')}/{tok}.{ext.lstrip('.')}"
    if default_storage.exists(path):
        default_storage.delete(path)
    default_storage.save(path, ContentFile(data))
    return path


def replace_media(*, old: str | None, prefix: str, data: bytes, ext: str) -> str:
    """G13: salva a nova mídia e DELETA a anterior — re-upload não pode deixar PII órfã no storage.
    `old` é o path relativo antigo (ou None/'', no 1º upload). Devolve o path novo."""
    path = save_media(prefix=prefix, data=data, ext=ext)
    if old and old != path and default_storage.exists(old):
        default_storage.delete(old)
    return path


def save_media_at(*, path: str, data: bytes) -> str:
    """Salva em um caminho relativo EXPLÍCITO (ex.: os arquivos de uma pasta de auditoria por token)."""
    if default_storage.exists(path):
        default_storage.delete(path)
    default_storage.save(path, ContentFile(data))
    return path
