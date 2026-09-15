from __future__ import annotations

import datetime
from django.utils import timezone

from users.address import interface as address_iface
from users.documents import service as documents_iface
from users.exceptions import Conflict, DomainError
from users.profiles import interface as profiles
from users.roles import _address_proof, _analysis, _document_ai
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import (
    CandidateError,
    _S,
    _require,
    _set_status,
    logger,
)
from users.roles.candidate.serializers import me_dict

def set_documents(*, user_external_id, doc_type: str, **fields) -> dict:
    """RG ou CNH (candidato aceita os dois). `doc_type` = 'rg'|'cnh'; `fields` = number/issuing_agency/..."""
    cand = _require(user_external_id, _S.ADDRESS, _S.DOCUMENTS)
    doc_type = doc_type.strip().lower()
    if doc_type not in ("rg", "cnh"):
        raise CandidateError(
            "Tipo de documento inválido (use 'rg' ou 'cnh').", code="INVALID_DOC_TYPE"
        )
    payload = {doc_type: {k: v for k, v in fields.items() if v is not None}}
    documents_iface.update(user_external_id, payload)
    # plan/15 B3: o tipo escolhido é persistido no Candidate (espelha o RG do aluno ser 1-1
    # com User — aqui o candidato escolhe RG OU CNH). Imutável após a 1ª foto: re-upload de
    # outro tipo exigiria reset (não implementado; tratamos como erro no orquestrador).
    if cand.doc_type in (None, "", doc_type):
        cand.doc_type = doc_type
        cand.save(update_fields=["doc_type", "updated_at"])
    if cand.status == _S.ADDRESS:
        _set_status(cand, _S.DOCUMENTS)
    return me_dict(cand)


def get_document_section(*, user_external_id) -> dict:
    """GET da seção documento do candidato (plan/15 B3) — fotos + validação IA + TODOS os campos
    extraídos (ou digitados) + `missing_fields` (o que ainda precisa completar). Espelha o
    `enrollment.get_rg_section` (plan/13). Tipo do documento = `cand.doc_type`."""
    cand = _require(user_external_id)
    _reconcile_stale_analyses(cand)
    return _doc_section_dict(cand)


def patch_document_section(*, user_external_id, **fields) -> dict:
    """PATCH da seção documento (plan/15 B3): completa/corrige o que a extração não trouxe.
    Aceito em qualquer etapa da coleta (a foto segue sendo a fonte de verdade pra auditoria)."""
    cand = _require(user_external_id, _S.DOCUMENTS, _S.PIX, _S.SELFIE)
    doc_type = cand.doc_type
    if not doc_type:
        raise CandidateError(
            "Tipo de documento ainda não definido. Envie a primeira foto do RG ou CNH.",
            code="DOC_TYPE_NOT_SET",
        )
    doc_payload = {k: fields[k] for k in _DOC_DOC_FIELDS if fields.get(k) is not None}
    if doc_payload:
        documents_iface.update(user_external_id, {doc_type: doc_payload})
    profile_payload = {
        k: fields[k] for k in _DOC_PROFILE_FIELDS if fields.get(k) is not None
    }
    if profile_payload:
        profiles.update_identity(
            cand.user, **profile_payload
        )  # identidade → Profile (correção)
    _advance_documents(cand, user_external_id)
    return me_dict(cand)  # resposta canônica


def upload_document_photo(*, user_external_id, slot: str, upload) -> dict:
    """Foto do documento (slots `rg_front`/`rg_back`/`rg_full`/`cnh_front`/`cnh_back`/`cnh_full`).
    Plan/15 B3: a foto entra no pipeline de IA (visão+OCR+extração assíncrono) — devolve **ack**
    (análise começou) pra o front acompanhar. A biometria do rosto roda SÓ no caminho assíncrono
    (`_doc_post_approval`): fix Marilu 2026-07-05 — o enroll síncrono aqui carregava/baixava o
    InsightFace (~326MB) DENTRO do request e pendurava o worker (CNH em PDF "travava o app")."""
    from users.roles import _analysis

    # FOTO-PRIMEIRO (Victor 2026-06-16): o upload é a ENTRADA da etapa documento — nada de digitar
    # número/tipo antes (ninguém sabe o nº da CNH; o OCR extrai). Aceito a partir de `address`.
    cand = _require(
        user_external_id,
        _S.STARTED,
        _S.PROFILE,
        _S.ADDRESS,
        _S.DOCUMENTS,
        _S.PIX,
        _S.COMPLETED,
    )
    # Define o `doc_type` do candidato a partir do 1º slot (rg_* ou cnh_*). Imutável depois.
    inferred = (
        "rg" if slot.startswith("rg_") else ("cnh" if slot.startswith("cnh_") else None)
    )
    if inferred is None:
        raise CandidateError(
            f"Slot de documento inválido: {slot}.", code="SLOT_INVALID"
        )
    if cand.doc_type in (None, ""):
        cand.doc_type = inferred
        cand.save(update_fields=["doc_type", "updated_at"])
    elif cand.doc_type != inferred:
        raise CandidateError(
            f"Você já escolheu {cand.doc_type.upper()}. Para trocar, recomece o cadastro.",
            code="DOC_TYPE_LOCKED",
        )
    if cand.status in (_S.STARTED, _S.PROFILE, _S.ADDRESS):
        _set_status(cand, _S.DOCUMENTS)
    path = documents_iface.upload_photo(user_external_id, slot, upload)
    # pipeline IA async (visão → OCR → extração → biometria) — plan/12+15 B3
    _reset_doc_validation(user_external_id, cand.doc_type, slot)
    from django_q.tasks import async_task

    async_task("users.roles.candidate.tasks.validate_document", cand.id, slot)
    sub = documents_iface.get_doc_sub(user_external_id, cand.doc_type)
    return {"stored": path, **_analysis.ack(_analysis.PENDING, _doc_started_at(sub))}



# ── validação do documento por IA (plan/12+15 B3) ───────────────────────────
# Espelha `enrollment.run_rg_validation` mas GENERALIZADO por `doc_type` (rg|cnh) — uma
# implementação só, alimentada pela `_document_ai` que já é polimórfica (B1). Roda na task
# Django-Q (`tasks.validate_document`); aqui é a orquestração (status no sub-doc, notifies,
# avanço do wizard).

_DOC_SLOT_FIELD = {
    "rg_front": "front_photo",
    "rg_back": "back_photo",
    "rg_full": "full_photo",
    "cnh_front": "front_photo",
    "cnh_back": "back_photo",
    "cnh_full": "full_photo",
}
_DOC_SLOT_SIDE = {
    "rg_front": "front",
    "rg_back": "back",
    "rg_full": "full",
    "cnh_front": "front",
    "cnh_back": "back",
    "cnh_full": "full",
}
_MIME_BY_EXT = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}
# Campos textuais que o PATCH do doc aceita (pro candidate = os do RG + os da CNH; o `update` da
# documents service filtra pelo sub-doc). O front manda o que tem; o resto fica null.
_DOC_DOC_FIELDS = (
    "number",
    "issuing_agency",
    "issue_date",
    "category",
    "national_register",
    "date_of_birth",
    "expires_on",
)
# Campos do PERFIL do candidato que a extração do documento pode preencher (Portão 2 do plan/15).
_DOC_PROFILE_FIELDS = (
    "mother_name",
    "father_name",
    "birthplace",
    "marital_status",
    "nationality",
)


def _doc_started_at(sub):
    """Datetime do início da análise (pro TTL do ack). `validation_result` guarda como string
    ISO; aqui parseia de volta. `_analysis.ack` precisa de datetime pra somar com timedelta."""
    from users.roles import _analysis

    if sub is None:
        return None
    raw = (sub.validation_result or {}).get("analysis_started_at")
    return _analysis.started_at_from(raw, coerce_tz=True)


def _reconcile_stale_analyses(cand: Candidate) -> None:
    """TTL guard (proposta #2): `pending` estourado → `review` na próxima leitura (espelha o
    enrollment; só aplica se o doc já tem uma análise rolando)."""
    from users.roles import _analysis

    if not cand.doc_type:
        return
    sub = documents_iface.get_doc_sub(str(cand.user.external_id), cand.doc_type)
    if sub is None:
        return
    if _analysis.is_stale(sub.validation_status, _doc_started_at(sub)):
        sub.validation_status = _analysis.REVIEW
        sub.save(update_fields=["validation_status"])


def _doc_section_dict(cand: Candidate) -> dict:
    """Seção rica do doc: bloco `doc_type` (rg|cnh) com sub-bloco do tipo + fotos+validação
    + campos extraídos + `missing_fields` (o que a IA não trouxe E o candidato precisa digitar)
    + `next_slot` (qual foto o front deve pedir) + `photos` (status por slot individual)."""
    from users.roles import _analysis

    docs = documents_iface.get_by_external_id(str(cand.user.external_id))
    doc_type = cand.doc_type
    section = {"doc_type": doc_type}
    if not doc_type:
        section["missing_fields"] = ["doc_type"]
        section["next_slot"] = None
        section["photos"] = {}
        return section
    sub = docs.get(doc_type) or {}
    section.update(
        sub
    )  # number/issuing_agency/category/... + photos + validation_status/reason
    # `analysis_status`/`analysis_reason` canônicos (espelha proposal #2 do front)
    section["analysis_status"] = sub.get("validation_status") or _analysis.PENDING
    section["analysis_reason"] = sub.get("validation_reason")
    # extraídos pela IA (se houver) — fica no validation_result
    result = (
        sub.get("validation_result")
        if isinstance(sub.get("validation_result"), dict)
        else {}
    )
    extracted = (result.get("extracted") or {}) if isinstance(result, dict) else {}
    section["extracted"] = extracted
    # photos por slot individual (front precisa saber qual slot enviar)
    section["photos"] = (result.get("photos") or {}) if isinstance(result, dict) else {}
    # next_slot: qual foto o front deve pedir AGORA
    section["next_slot"] = _analysis.next_document_slot(doc_type, section["photos"])
    # missing_fields: o que a IA não trouxe (extraídos vazios) E o usuário ainda não digitou
    # (sub-doc). Considera os campos que o funil exige pra avançar.
    required = _required_doc_fields(doc_type)
    section["missing_fields"] = [f for f in required if not _doc_value_present(sub, f)]
    return section


def _required_doc_fields(doc_type: str) -> tuple[str, ...]:
    if doc_type == "cnh":
        return (
            "number",
        )  # CNH exige só o número pra avançar; resto é melhor-ter-que-não-ter
    return ("number",)  # RG idem


def _doc_value_present(sub: dict, field: str) -> bool:
    """O sub-doc tem valor não-vazio pro campo?"""
    val = sub.get(field)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    return True


def _reset_doc_validation(user_external_id: str, doc_type: str, slot: str) -> None:
    """Re-upload de um slot re-zera o veredito daquela foto + a extração (re-analisa tudo)."""
    from django.utils import timezone

    from users.roles import _document_ai as doc_ai

    sub = documents_iface.get_doc_sub(user_external_id, doc_type)
    if sub is None:
        return
    result = sub.validation_result or {}
    photos = dict(result.get("photos") or {})
    photos.pop(slot, None)
    for key in ("extracted", "name_match", "reason", "human"):
        result.pop(key, None)
    result["photos"] = photos
    result["analysis_started_at"] = timezone.now().isoformat()
    sub.validation_status = doc_ai.PENDING
    sub.validation_result = result
    sub.validated_at = None
    sub.save(update_fields=["validation_status", "validation_result", "validated_at"])


def _advance_documents(cand: Candidate, user_external_id: str) -> None:
    """Avança DOCUMENTS→PIX quando `number` presente + foto enviada. Validação roda em background."""
    if cand.status != _S.DOCUMENTS or not cand.doc_type:
        return
    sub = documents_iface.get_doc_sub(user_external_id, cand.doc_type)
    # ponytail: sem gate de validação — usuário avança na hora; rejeição = ValidationBlock
    if (
        sub is not None
        and getattr(sub, "number", None)
        and (getattr(sub, "front_photo", None) or getattr(sub, "full_photo", None))
    ):
        _set_status(cand, _S.PIX)


