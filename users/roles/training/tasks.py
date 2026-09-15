"""Tasks Django-Q do training: correção assíncrona da submissão pela IA (`ai.grade`).

Enfileirada por `service.submit`/`submit_audio` (após o commit). Submissão de áudio é transcrita
(`ai.transcribe`) ANTES da correção, na mesma task. Degrade gracioso: se a IA falha (transcrição ou
correção), a submissão fica `pending` (re-correção possível) — nunca derruba o fluxo do trainee.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from django.conf import settings

logger = structlog.get_logger()


def _transcribe_audio(sub) -> bool:
    """Preenche `sub.answer` com a transcrição do áudio. False = falhou (fica pending, re-run)."""
    from integrations.ai import service as ai
    from users.roles.training.service import _AUDIO_EXT

    mime_by_ext: dict[str, str] = {}
    for (
        mime,
        ext,
    ) in _AUDIO_EXT.items():  # 1º MIME de cada ext (o canônico: audio/mpeg, audio/mp4…)
        mime_by_ext.setdefault(ext, mime)
    full = Path(settings.MEDIA_ROOT) / sub.audio
    try:
        transcript = ai.transcribe(
            full.read_bytes(),
            mime_type=mime_by_ext.get(full.suffix.lstrip(".").lower(), "audio/mpeg"),
            caller="training.transcribe",
        )
    except Exception as exc:  # noqa: BLE001 — IA/arquivo fora → fica pending (degrade gracioso)
        logger.warning(
            "training.transcribe_failed", submission_id=sub.id, error=str(exc)
        )
        return False
    if not transcript.strip():
        logger.warning("training.transcript_empty", submission_id=sub.id)
        return False
    sub.answer = transcript
    sub.save(update_fields=["answer", "updated_at"])
    return True


def grade_submission(submission_id: int) -> None:
    from integrations.ai import service as ai
    from users.roles.training import service as training_service
    from users.roles.training.models import Submission

    sub = Submission.objects.select_related("material").filter(id=submission_id).first()
    if sub is None or sub.status != Submission.Status.PENDING:
        return
    if sub.audio and not sub.answer.strip():
        if not _transcribe_audio(sub):
            return
    try:
        grading = ai.grade(
            question=sub.material.question,
            expected_answer=sub.material.expected_answer,
            student_answer=sub.answer,
            caller="training.grade",
        )
    except Exception as exc:  # noqa: BLE001 — IA fora → fica pending (degrade gracioso)
        logger.warning(
            "training.grade_failed", submission_id=submission_id, error=str(exc)
        )
        return
    training_service.apply_grade(submission_id, grading.grade, grading.justification)
