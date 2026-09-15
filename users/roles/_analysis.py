"""Contrato unificado das análises assíncronas por IA (proposta API #2/#4/#6).

UM vocabulário só pros estados de qualquer análise que roda em 2º plano (RG, selfie e, no
futuro, docs do student): `pending | approved | rejected | review`. Os models já gravam
exatamente esses 4 valores (RG.Validation, SelfieStatus) — aqui a gente expõe sob o nome
CANÔNICO (`analysis_status`) e dá:

  • o **ack de polling** (`poll_after_ms` = quando o front volta a perguntar; `expires_at` =
    até quando o `pending` vale) pras mutações que disparam análise;
  • a régua do **TTL**: um `pending` que estourou o prazo VIRA `review` — nunca fica preso em
    "analisando…" se a task da IA morreu/sumiu (plan/9: "IA fora do ar/em dúvida → review, a
    gente resolve"; e [[feedback-qcluster-sempre-no-ar]]: sem o worker a fila represa calada).

Helpers PUROS (sem efeito no banco) — quem persiste o flip é o service do funil.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

# Estados canônicos — iguais aos dos enums dos models (RG.Validation, SelfieStatus).
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
REVIEW = "review"

# Literal pros schemas Ninja: o OpenAPI passa a mostrar o enum em vez de `"string"` (proposta #6).
STATUS_VALUES = (PENDING, APPROVED, REJECTED, REVIEW)

_STALE_REASON = "Análise automática expirou — em revisão pela equipe."


def started_at_from(raw, *, coerce_tz: bool = True) -> datetime | None:
    """Parseia o `analysis_started_at` (gravado como string ISO em `validation_result`) de volta a
    datetime — o que o `is_stale`/`ack` precisam pra somar com o TTL. Valor vazio/ilegível → None.
    `coerce_tz` força UTC quando a string vier naive (o funil do RG do enrollment guarda naive)."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            dt = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return None
    if coerce_tz and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def ttl_seconds() -> int:
    return int(getattr(settings, "ANALYSIS_TTL_SECONDS", 120))


def poll_after_ms() -> int:
    return int(getattr(settings, "ANALYSIS_POLL_MS", 2500))


def expires_at(started_at: datetime | None) -> datetime | None:
    """Quando o `pending` disparado em `started_at` deixa de valer (vira review na próxima leitura)."""
    if started_at is None:
        return None
    return started_at + timedelta(seconds=ttl_seconds())


def is_stale(status: str | None, started_at: datetime | None) -> bool:
    """`pending` cujo prazo já estourou → DEVE virar review (o caller persiste)."""
    if status != PENDING or started_at is None:
        return False
    return timezone.now() > started_at + timedelta(seconds=ttl_seconds())


def stale_reason() -> str:
    return _STALE_REASON


def age_stale_selfies(model, notify) -> int:
    """Move selfies expiradas para revisão e avisa o coordenador uma única vez."""
    cutoff = timezone.now() - timedelta(seconds=ttl_seconds())
    stale = model.objects.select_related("hub", "hub__coordinator").filter(
        selfie_status=PENDING, selfie_taken_at__lt=cutoff
    )
    aged = 0
    for obj in stale:
        if not is_stale(obj.selfie_status, obj.selfie_taken_at):
            continue
        obj.selfie_status = REVIEW
        obj.selfie_description = (obj.selfie_description or "").strip() or stale_reason()
        obj.save(update_fields=["selfie_status", "selfie_description", "updated_at"])
        notify(obj)
        aged += 1
    return aged


def sweep_stale_selfies(model, hub) -> None:
    cutoff = timezone.now() - timedelta(seconds=ttl_seconds())
    model.objects.filter(
        hub=hub, selfie_status=PENDING, selfie_taken_at__lt=cutoff
    ).update(selfie_status=REVIEW, selfie_description=stale_reason())


def sweep_stale_documents(queryset, started_at) -> None:
    for document in queryset.filter(validation_status=PENDING):
        if is_stale(document.validation_status, started_at(document)):
            document.validation_status = REVIEW
            document.save(update_fields=["validation_status"])


def next_document_slot(doc_type: str, photos: dict) -> str | None:
    """Próxima foto do documento, ou None enquanto a análise aguarda/concluiu."""
    full, front, back = (f"{doc_type}_{side}" for side in ("full", "front", "back"))

    def status(slot: str) -> str | None:
        return (photos.get(slot) or {}).get("status")

    if status(full) == APPROVED or (
        status(front) == APPROVED and status(back) == APPROVED
    ):
        return None
    if any(status(slot) in (PENDING, REVIEW) for slot in (full, front, back)):
        return None
    if status(full) == REJECTED:
        return full
    if status(front) == APPROVED:
        return back
    if status(back) == APPROVED:
        return front
    return front


def ack(status: str | None, started_at: datetime | None) -> dict:
    """Ack de uma mutação que dispara análise async (proposta #2): o front sabe QUANDO voltar a
    perguntar (`poll_after_ms`) e até QUANDO o `pending` vale (`expires_at`). Já reflete o TTL: se
    o prazo estourou, o `analysis_status` devolvido é `review`."""
    exp = expires_at(started_at)
    return {
        "analysis_status": REVIEW
        if is_stale(status, started_at)
        else (status or PENDING),
        "poll_after_ms": poll_after_ms(),
        "expires_at": exp.isoformat() if exp else None,
    }
