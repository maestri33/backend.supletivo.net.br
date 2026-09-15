"""Tasks Django-Q do `enrollment` — validação do RG por IA (assíncrona, plan/12).

A IA roda fora do request (regra dos ≤10s por requisição; visão+OCR+LLM levam 10–60s): o upload
responde "em análise" e o front acompanha pelo `/enrollment/me`. Degrada com graça: IA fora do
ar/inconclusiva → `review` (coordenador decide) — nunca trava o aluno em silêncio.

ponytail: cada task wrap em try/except — Django-Q silenciosamente re-tenta em loop se levantar
exceção. Capturamos o erro e logamos com contexto pra rastrear o que falhou.
"""

from __future__ import annotations

import structlog

from users.roles.enrollment import service

logger = structlog.get_logger()


def _wrap(task_name: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
        logger.info("enrollment.task_ok", task=task_name, args=str(args)[:200])
    except Exception as exc:  # noqa: BLE001 — Django-Q silenciaria
        logger.exception(
            "enrollment.task_failed",
            task=task_name,
            args=str(args)[:200],
            error=str(exc),
        )


def validate_rg(enrollment_id: int, slot: str) -> None:
    """Valida a foto recém-subida (visão) e, com a seção completa, extrai os dados."""
    _wrap("validate_rg", service.run_rg_validation, enrollment_id, slot)


def fill_rg_data(enrollment_id: int) -> None:
    """Pós-aprovação humana (decide): OCR+extração best-effort SÓ pra preencher campos — sem veto."""
    _wrap("fill_rg_data", service.run_rg_fill, enrollment_id)


def validate_selfie(enrollment_id: int) -> None:
    """Valida a selfie/assinatura (liveness → face-match vs documento → instruções se reprovar)."""
    _wrap("validate_selfie", service.run_selfie_validation, enrollment_id)


def validate_address_proof(enrollment_id: int) -> None:
    """Valida o comprovante de endereço (visão → endereço bate? → titular bate?) — F1."""
    _wrap("validate_address_proof", service.run_address_proof_validation, enrollment_id)


def age_stale_selfies() -> None:
    """Schedule (Django-Q): selfies `pending` com TTL estourado → `review` + notifica coord.

    Antes rodava DENTRO do `GET /enrollment/selfie` (mutava/notificava numa leitura — viola a
    idempotência HTTP). Registrado por `manage.py selfie_schedules`. Idempotente."""
    try:
        aged = service.age_stale_selfies()
        logger.info("enrollment.task_selfies_aged", aged=aged)
    except Exception as exc:  # noqa: BLE001 — Django-Q silenciaria
        logger.exception("enrollment.age_stale_selfies_failed", error=str(exc))
