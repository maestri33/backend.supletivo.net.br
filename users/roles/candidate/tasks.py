"""Tasks Django-Q do `candidate` — validação do documento por IA (assíncrona, plan/15 B3).

Espelho do `enrollment/tasks.py` (plan/12): a IA roda fora do request (≤10s/req; visão+OCR+LLM
levam 10–60s); o upload responde ack e o front acompanha pelo `/candidate/me`. Degrada com
graça: IA fora/inconclusiva → `review` (coordenador decide).

ponytail: cada task wrap em try/except — Django-Q silenciosamente re-tenta em loop se levantar
exceção. Capturamos o erro e logamos com contexto pra rastrear o que falhou.
"""

from __future__ import annotations

import structlog

from users.roles.candidate import service

logger = structlog.get_logger()


def _wrap(task_name: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
        logger.info("candidate.task_ok", task=task_name, args=str(args)[:200])
    except Exception as exc:  # noqa: BLE001 — Django-Q silenciaria
        logger.exception(
            "candidate.task_failed",
            task=task_name,
            args=str(args)[:200],
            error=str(exc),
        )


def validate_document(candidate_id: int, slot: str) -> None:
    """Valida a foto recém-subida (visão) e, com a seção completa, extrai os dados."""
    _wrap("validate_document", service.run_document_validation, candidate_id, slot)


def fill_document_data(candidate_id: int) -> None:
    """Pós-aprovação humana (decide): OCR+extração best-effort SÓ pra preencher campos — sem veto."""
    _wrap("fill_document_data", service.run_document_fill, candidate_id)


def validate_candidate_selfie(candidate_id: int) -> None:
    """Valida a selfie/assinatura (liveness → face-match vs documento → instruções se reprovar)."""
    _wrap("validate_candidate_selfie", service.run_selfie_validation, candidate_id)


def validate_address_proof(candidate_id: int) -> None:
    """Valida o comprovante de endereço (visão → endereço bate? → titular bate?) — F1."""
    _wrap("validate_address_proof", service.run_address_proof_validation, candidate_id)


def age_stale_selfies() -> None:
    """Schedule (Django-Q): selfies `pending` com TTL estourado → `review` + notifica coord.

    Antes rodava DENTRO do `GET /candidate/selfie` (mutava/notificava numa leitura — viola a
    idempotência HTTP). Registrado por `manage.py selfie_schedules`. Idempotente."""
    try:
        aged = service.age_stale_selfies()
        logger.info("candidate.task_selfies_aged", aged=aged)
    except Exception as exc:  # noqa: BLE001 — Django-Q silenciaria
        logger.exception("candidate.age_stale_selfies_failed", error=str(exc))
