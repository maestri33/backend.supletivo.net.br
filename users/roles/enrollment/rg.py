from __future__ import annotations

import datetime
from django.utils import timezone

from users.documents import service as documents_iface
from users.exceptions import Conflict, DomainError
from users.blocks import service as blocks
from users.profiles import interface as profiles
from users.roles import _analysis, _document_ai
from users.roles.enrollment.models import Enrollment
from users.roles.enrollment.common import (
    EnrollmentError,
    _S,
    _require,
    _advance_to,
    _RG_DOC_FIELDS,
    _RG_PROFILE_FIELDS,
    _RG_SLOT_FIELD,
    _RG_SLOT_SIDE,
    _MIME_BY_EXT,
    logger,
)
from users.roles.enrollment.serializers import me_dict
from users.roles.enrollment import service

def _rg_started_at(rg):
    """Quando a análise do RG (re)começou — do JSON do reset (proposta #2). None = sem referência."""
    from users.roles import _analysis

    raw = (rg.validation_result or {}).get("analysis_started_at") if rg else None
    return _analysis.started_at_from(raw, coerce_tz=False)


def _reconcile_stale_analyses(enr: Enrollment) -> None:
    """TTL guard do RG (proposta #2): `pending` do DOCUMENTO que estourou o prazo vira `review` — o
    aluno nunca fica preso em "analisando…" se a task da IA morreu. Idempotente; roda nas LEITURAS.

    A selfie SAIU daqui: seu envelhecimento (pending→review+notify) roda no job agendado
    `tasks.age_stale_selfies` (Django-Q), nunca numa leitura — um GET não pode mutar/notificar
    (idempotência HTTP)."""
    from users.roles import _analysis

    rg = documents_iface.get_rg(str(enr.user.external_id))
    if rg is not None and _analysis.is_stale(rg.validation_status, _rg_started_at(rg)):
        logger.info(
            "enrollment.analysis_stale_flip",
            enrollment=str(getattr(enr, "external_id", None)),
            kind="rg",
        )
        _finish_rg(
            enr,
            rg,
            _analysis.REVIEW,
            _analysis.stale_reason(),
            rg.validation_result or {},
        )



def _public_rg_reason(status: str | None) -> str | None:
    """O que o ALUNO lê. O motivo real (lado trocado, nome divergente, rasura suspeita) fica no
    `validation_result` e só o hub/staff enxerga — regra do Victor (2026-07-28).

    Dois motivos: expor o critério ensina a burlar, e "o nome não confere com o cadastro" na tela
    de quem está tentando se matricular é acusação sem contraditório. O aluno recebe o que
    consegue AGIR: mandar de novo, direito. O porquê fica com quem decide."""
    from users.roles import _document_ai as doc_ai

    if status == doc_ai.REJECTED:
        return (
            "Não deu pra validar esse documento. Manda de novo: foto nítida, sem reflexo, "
            "com as quatro bordas aparecendo e o documento preenchendo a tela."
        )
    if status == doc_ai.REVIEW:
        return "Seu documento foi pra conferência da coordenação — a gente te avisa assim que sair."
    return None


def _rg_section_dict(enr: Enrollment) -> dict:
    from users.roles import _analysis

    user_ext = str(enr.user.external_id)
    rg = documents_iface.get_rg(user_ext)
    p = profiles.get(enr.user)
    fields = {
        "number": rg.number if rg else None,
        "issuing_agency": rg.issuing_agency if rg else None,
        "issue_date": rg.issue_date.isoformat() if (rg and rg.issue_date) else None,
        "mother_name": p.mother_name if p else None,
        "father_name": p.father_name if p else None,
        "birthplace": p.birthplace if p else None,
        "marital_status": p.marital_status if p else None,
        "nationality": p.nationality if p else None,
    }
    result = (rg.validation_result or {}) if rg else {}
    # MESMA régua da selfie (_selfie_dict: `enr.selfie_status if enr.selfie_image else None`):
    # sem foto não há análise em voo, então `analysis_status` é None (front mostra o upload, não
    # "extraindo…"). O RG nasce com validation_status="pending" por default — surfá-lo cru travava
    # o passo RG num spinner eterno mesmo sem nenhuma foto enviada.
    has_photo = bool(rg and (rg.front_photo or rg.back_photo or rg.full_photo))
    photos = (result.get("photos") or {}) if isinstance(result, dict) else {}
    return {
        **fields,
        "name": p.name if p else None,
        "birth_date": p.birth_date.isoformat() if (p and p.birth_date) else None,
        "front_photo": rg.front_photo if rg else None,
        "back_photo": rg.back_photo if rg else None,
        "full_photo": rg.full_photo if rg else None,
        # canônico unificado (proposta #4) + alias `validation_*` (compat) até o front migrar.
        "analysis_status": rg.validation_status if has_photo else None,
        # PÚBLICO: orientação, nunca o critério (ver `_public_rg_reason`). O motivo real segue
        # em `validation_result["reason"]`, que só o hub/staff lê (api/leadership.py monta o RG
        # do coordenador por outro caminho — `documents_iface.get_by_external_id`).
        "analysis_reason": _public_rg_reason(
            rg.validation_status if has_photo else None
        ),
        "validation_status": rg.validation_status if has_photo else None,
        "validation_reason": _public_rg_reason(
            rg.validation_status if has_photo else None
        ),
        # Flag da regra do Victor: reprovado = o aluno volta pro RG assim que entrar, e só sai
        # de lá quando mandar de novo (o upload re-arma `pending` e derruba a flag; se a IA
        # reprovar outra vez, ela sobe de novo).
        "blocked": (rg.validation_status if has_photo else None) == "rejected",
        "missing_fields": [
            k for k in (*_RG_DOC_FIELDS, *_RG_PROFILE_FIELDS) if not fields[k]
        ],
        # next_slot: qual foto o front deve pedir AGORA (sequencial: frente→verso)
        "next_slot": _analysis.next_document_slot("rg", photos),
        # photos por slot individual (front precisa saber o status de cada foto)
        # Por slot, o cliente recebe SÓ o status — o `reason` de cada foto é o critério cru da
        # visão ("mostra os dois lados", "lado trocado") e vaza a régua do mesmo jeito que o
        # motivo da seção (achado do E2E real 2026-07-28: a UI não mostrava, mas a API entregava).
        "photos": {
            slot: {"status": (p or {}).get("status")} for slot, p in photos.items()
        },
    }


def get_rg_section(*, user_external_id: str) -> dict:
    """GET da seção documento (plan/13): fotos + validação + TODOS os campos (extraídos pela IA
    ou digitados) + `missing_fields` (o que o aluno ainda precisa completar)."""
    enr = _require(user_external_id)
    _reconcile_stale_analyses(enr)  # TTL guard (proposta #2)
    return _rg_section_dict(enr)


def patch_rg_section(*, user_external_id: str, **fields) -> dict:
    """PATCH da seção documento (plan/13): completa/CORRIGE o que a extração não trouxe — campos
    do doc e do perfil. Aceito em qualquer etapa da coleta (é dado do aluno, não progressão);
    a foto do documento segue sendo a fonte de verdade pra auditoria do coordenador."""
    enr = _require(user_external_id, _S.RG, _S.ADDRESS, _S.EDUCATION, _S.SELFIE)
    doc_payload = {k: fields[k] for k in _RG_DOC_FIELDS if fields.get(k) is not None}
    if doc_payload:
        documents_iface.update(user_external_id, {"rg": doc_payload})
    profile_payload = {
        k: fields[k] for k in _RG_PROFILE_FIELDS if fields.get(k) is not None
    }
    if profile_payload:
        profiles.update_identity(
            enr.user, **profile_payload
        )  # identidade → Profile (correção)
    _advance_rg(enr, user_external_id)
    # destrave do gate #10: selfie já aprovada que só esperava os campos → fecha a coleta agora
    from users.roles import _selfie

    if enr.status == _S.SELFIE and enr.selfie_status == _selfie.APPROVED:
        _advance_to_release(enr)
    return me_dict(
        enr
    )  # resposta canônica (proposta #3): o rg detalhado segue no GET da seção


def upload_rg_photo(*, user_external_id: str, slot: str, upload) -> dict:
    """Foto do RG (slot `rg_front`/`rg_back`/`rg_full`), dentro da seção `rg` — plan/12.

    Salva (PDF vira JPEG no `documents`), re-zera a validação e ENFILEIRA o pipeline de IA
    (visão → OCR → extração → biometria). O upload responde na hora; o veredito (e o motivo,
    se reprovar) sai pelo `/enrollment/me`. Aluno: RG é obrigatório (Victor)."""
    from users.roles import _analysis

    # accept-first: RG aceito em qualquer etapa pré-completion (re-upload após rejeição funciona
    # mesmo depois de avançar pro endereço/escolaridade).
    enr = _require(user_external_id, _S.RG, _S.ADDRESS, _S.EDUCATION, _S.SELFIE)
    path = documents_iface.upload_photo(user_external_id, slot, upload)
    _reset_rg_validation(user_external_id, slot)
    from core.tasks import async_task

    async_task("users.roles.enrollment.tasks.validate_rg", enr.id, slot)
    # ack de polling (proposta #2): a análise acabou de (re)começar → started_at = agora.
    rg = documents_iface.get_rg(user_external_id)
    return {"stored": path, **_analysis.ack(_analysis.PENDING, _rg_started_at(rg))}


def selfie_ack(enr: Enrollment) -> dict:
    """Ack de polling da selfie (proposta #2) — pro POST devolver junto com o estado."""
    from users.roles import _analysis

    return _analysis.ack(enr.selfie_status, enr.selfie_taken_at)


def _advance_rg(enr: Enrollment, user_external_id: str) -> None:
    """Avança RG→ADDRESS quando `number` preenchido + foto presente. A validação da IA roda em
    background e rejeições viram ValidationBlock — o usuário NÃO fica parado esperando."""
    if enr.status != _S.RG:
        return
    rg = documents_iface.get_rg(user_external_id)
    # ponytail: sem gate de validação — usuário avança na hora. Block na rejeição.
    if rg is not None and rg.number and (rg.front_photo or rg.full_photo):
        _advance_to(enr, _S.ADDRESS)


# ── validação do RG por IA (plan/12): visão → OCR → extração → biometria ────
# Roda na task Django-Q (`tasks.validate_rg`); aqui é a orquestração (status no RG, notifies,
# avanço do wizard). As chamadas de IA moram em `users/roles/_document_ai.py` (compartilhável).

_RG_SLOT_FIELD = {
    "rg_front": "front_photo",
    "rg_back": "back_photo",
    "rg_full": "full_photo",
}
_RG_SLOT_SIDE = {"rg_front": "front", "rg_back": "back", "rg_full": "full"}
_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _reset_rg_validation(user_external_id: str, slot: str) -> None:
    """Re-upload de um slot re-zera o veredito daquela foto + a extração (re-analisa tudo)."""
    from users.roles import _document_ai as doc_ai

    rg = documents_iface.get_rg(user_external_id)
    if rg is None:
        return
    from django.utils import timezone

    result = rg.validation_result or {}
    photos = dict(result.get("photos") or {})
    photos.pop(slot, None)
    for key in ("extracted", "name_match", "reason", "human"):
        result.pop(key, None)
    result["photos"] = photos
    # marca o INÍCIO da análise (proposta #2): o re-upload reinicia o relógio do TTL. Guardado no
    # JSON (sem migração); só vale enquanto `pending` (o `_finish_rg` reescreve o result ao concluir).
    result["analysis_started_at"] = timezone.now().isoformat()
    rg.validation_status = doc_ai.PENDING
    rg.validation_result = result
    rg.validated_at = None
    rg.save(update_fields=["validation_status", "validation_result", "validated_at"])
    # ponytail: re-upload resolve o bloco imediatamente — nova análise roda em background
    blocks.resolve_for_source(user=rg.document.user, source_type="rg_photo")

