"""Lógica do candidate (funil do colaborador): captação → coleta → vira treino.

Espelho do lead+enrollment: `create_candidate` reusa o `register` (role `candidate`) + cria o `Candidate`
ligado a um HUB. Funil autenticado: perfil → endereço(ViaCEP) → RG/CNH → **Pix (validada no Asaas/DICT)** →
selfie(IA) → `COMPLETED` (aguarda o coordenador aprovar → vira PROMOTOR). ⚠️ o passo Pix MEXE DINHEIRO REAL.
"""

from __future__ import annotations

import structlog
from django.conf import settings
from django.db import transaction

from hub import interface as hub_iface
from users.address import interface as address_iface
from users.auth import service as auth_iface
from users.auth.models import User
from users.blocks import service as blocks
from users.documents import service as documents_iface
from users.exceptions import Conflict, DomainError, Forbidden, NotFound
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.candidate.models import Candidate

logger = structlog.get_logger()

_S = Candidate.Status
_SELFIE_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_COLLABORATOR_ROLES = ("coordinator", "promoter", "training", "candidate")


class CandidateError(DomainError):
    """Erro de borda do candidate (não encontrado, etapa fora de ordem, Pix inválida).

    É `DomainError` (422): o handler central da API converte em JSON `{detail, code, …extra}`."""

    status = 422


# ── nascimento (público) ────────────────────────────────────────────────────


def _resolve_capture_hub(hub):
    hub_obj, ref_reason = hub_iface.resolve_capture_hub(hub)
    if hub_obj is None:
        raise CandidateError(
            "Nenhum polo disponível para o cadastro.", code="NO_HUB"
        )  # nem o polo padrão existe (seed_defaults não rodou)
    if ref_reason.endswith("_default") and ref_reason != "no_ref_default":
        # veio um ref mas não resolveu pro polo dele (inválido / promotor sem hub / polo sem coord)
        # → caiu no padrão. Loga pro staff monitorar links de captação ruins.
        logger.warning(
            "candidate.ref_fallback",
            ref=hub,
            reason=ref_reason,
            hub=str(hub_obj.external_id),
        )
    return hub_obj, ref_reason


def check_or_capture(
    *,
    cpf: str | None = None,
    phone: str | None = None,
    external_id: str | None = None,
    send_otp: bool = True,
    service_authed: bool = False,
    hub: str | None = None,
) -> dict:
    """`POST collaborators/auth/check`: check normal E captura automática de promotor (candidato).

    - Usuário EXISTE → comporta igual ao `auth.check` (OTP + found + roles honestos).
    - NÃO existe, veio `phone` e o WhatsApp CONFIRMOU o número → **cria a conta na hora**
      (User + Profile(phone) + role candidate + Candidate(STARTED) ligado ao polo/hub) e dispara o OTP —
      resposta ganha `created: true` + `external_id` (o front segue direto pro OTP).
    - NÃO existe e WhatsApp negou (`whatsapp:false`) ou está fora (`whatsapp:null`) → NÃO cria;
      o front avisa número inválido / não confirmado.
    """
    result = auth_iface.check(
        cpf=cpf,
        phone=phone,
        external_id=external_id,
        send_otp=send_otp,
        service_authed=service_authed,
    )
    if result["found"] or not phone or not send_otp:
        return {**result, "created": False}
    if result.get("whatsapp") is not True:
        return {**result, "created": False}

    try:
        hub_obj, ref_reason = _resolve_capture_hub(hub)
        reg = auth_iface.register(
            role="candidate", phone=phone
        )
        user = User.objects.get(external_id=reg["external_id"])
        candidate = Candidate.objects.create(
            user=user, hub=hub_obj, status=_S.STARTED
        )
    except DomainError as exc:
        logger.warning("candidate.capture_on_check_failed", code=exc.code, error=exc.detail)
        return {**result, "created": False}

    logger.info(
        "candidate.captured_on_check",
        external_id=str(candidate.external_id),
        hub=str(hub_obj.external_id),
        ref_reason=ref_reason,
    )
    return {
        "found": False,
        "created": True,
        "external_id": reg["external_id"],
        "otp_sent": reg["otp_sent"],
        "otp_wait": None,
        "whatsapp": True,
        "roles": ["candidate"],
        "token": None,
    }


def create_candidate(*, cpf: str, phone: str, email: str, hub=None) -> dict:
    """Cria o candidato: register(role candidate) + Candidate(STARTED) ligado a um hub.

    `hub` = external_id do polo (landing `?ref=` do coordenador); sem hub → hub padrão (regra dura:
    candidato↔hub).
    """
    hub_obj, ref_reason = _resolve_capture_hub(hub)

    reg = auth_iface.register(role="candidate", phone=phone, cpf=cpf, email=email)
    user = User.objects.get(external_id=reg["external_id"])
    candidate = Candidate.objects.create(user=user, hub=hub_obj, status=_S.STARTED)
    logger.info(
        "candidate.created",
        external_id=str(candidate.external_id),
        hub=str(hub_obj.external_id),
        ref_reason=ref_reason,
    )
    return {
        "external_id": str(candidate.external_id),
        # external_id do USER — é o que o /auth/login consome (plan/15 A4).
        "user_external_id": reg["external_id"],
        "status": candidate.status,
    }


def check_or_capture_candidate(
    *,
    cpf: str | None = None,
    phone: str | None = None,
    external_id: str | None = None,
    send_otp: bool = True,
    service_authed: bool = False,
    hub=None,
) -> dict:
    """Check de telefone/CPF para o funil do colaborador (/group).

    - Se usuário já existe: retorna check padrão (OTP disparado se send_otp=True).
    - Se NÃO existe e veio phone com whatsapp válido: registra usuário com role 'candidate',
      cria Candidate(STARTED) ligado ao polo (hub) e dispara OTP.
    """
    result = auth_iface.check(
        cpf=cpf,
        phone=phone,
        external_id=external_id,
        send_otp=send_otp,
        service_authed=service_authed,
    )
    if result["found"] or not phone or not send_otp:
        return {**result, "created": False}
    if result.get("whatsapp") is not True:
        return {**result, "created": False}

    try:
        hub_obj, ref_reason = _resolve_capture_hub(hub)
        reg = auth_iface.register(role="candidate", phone=phone, cpf=cpf)
        user = User.objects.get(external_id=reg["external_id"])
        candidate = Candidate.objects.create(user=user, hub=hub_obj, status=_S.STARTED)
        logger.info(
            "candidate.capture_on_check",
            external_id=str(candidate.external_id),
            hub=str(hub_obj.external_id),
            ref_reason=ref_reason,
        )
        return {
            **result,
            "found": True,
            "created": True,
            "external_id": str(user.external_id),
            "otp_sent": reg.get("otp_sent", True),
            "roles": ["candidate"],
        }
    except DomainError as exc:
        logger.warning("candidate.capture_on_check_failed", code=exc.code, error=exc.detail)
        return {**result, "created": False}
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.capture_on_check_failed", error=str(exc))
        return {**result, "created": False}


def _ensure_candidate_inner(user, hub) -> None:
    """Regra compartilhada (join/web): garante role `candidate` + linha `Candidate` pro user.

    O CHAMADOR já provou posse (OTP no `join_candidate`; sessão web autenticada no
    `ensure_candidate`) e já segura a transação/lock. Preserva roles existentes."""
    active = roles.active_roles(user)

    if not any(role in active for role in _COLLABORATOR_ROLES):
        profile = profiles.get(user)
        required = {
            "cpf": getattr(profile, "cpf", None),
            "email": getattr(profile, "email", None),
            "name": getattr(profile, "name", None),
            "birth_date": getattr(profile, "birth_date", None),
        }
        missing_fields = [name for name, value in required.items() if not value]
        if missing_fields:
            raise CandidateError(
                "Seu cadastro anterior precisa ser completado antes de entrar no programa de promotores.",
                code="JOIN_PROFILE_INCOMPLETE",
                extra={"missing_fields": missing_fields},
            )

        hub_obj, ref_reason = _resolve_capture_hub(hub)
        candidate = Candidate.objects.filter(user=user).first()
        if candidate is None:
            candidate = Candidate.objects.create(
                user=user, hub=hub_obj, status=_S.STARTED
            )
        roles.assign(user, "candidate")
        logger.info(
            "candidate.joined_existing_user",
            external_id=str(candidate.external_id),
            hub=str(hub_obj.external_id),
            ref_reason=ref_reason,
            previous_roles=active,
        )
    elif "candidate" in active and not Candidate.objects.filter(user=user).exists():
        hub_obj, ref_reason = _resolve_capture_hub(hub)
        candidate = Candidate.objects.create(user=user, hub=hub_obj, status=_S.STARTED)
        logger.warning(
            "candidate.repaired_missing_row",
            external_id=str(candidate.external_id),
            hub=str(hub_obj.external_id),
            ref_reason=ref_reason,
        )


def join_candidate(*, user_external_id: str, otp: str, hub=None) -> dict:
    """Adere uma identidade existente ao funil do colaborador após provar posse via OTP.

    Preserva os papéis já usados no Supletivo e só cria `candidate` depois da prova de posse do
    WhatsApp.
    """
    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")

    # Duas fases de propósito (E2E 2026-07-29):
    # 1) CONFERE fora da transação — assim a tentativa ERRADA persiste o `attempts += 1`. Antes,
    #    a exceção dentro do atomic fazia rollback do contador e o código de 6 dígitos ficava
    #    aberto a brute-force (3 erros e o contador seguia em 0).
    # 2) CONSOME dentro da transação — se o passo seguinte falhar (ex.: NO_HUB), o código CERTO
    #    não é queimado e a pessoa tenta de novo, que é o contrato dos testes de join.
    auth_iface.verify_otp_for_user(user=user, otp=otp, consume=False)

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        auth_iface.verify_otp_for_user(user=user, otp=otp)
        _ensure_candidate_inner(user, hub)
        return auth_iface.issue_tokens_for_user(user)


def ensure_candidate(*, user_external_id: str, hub=None) -> None:
    """Funil WEB (sessão Django server-side, posse já provada no login por OTP): garante a role
    `candidate` + a linha `Candidate` sem consumir OTP — mesma regra do `join_candidate`.
    Idempotente; `JOIN_PROFILE_INCOMPLETE` se o perfil de outro funil ainda não tem identidade."""
    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        _ensure_candidate_inner(user, hub)


def get_for_user_external_id(user_external_id: str) -> Candidate | None:
    return (
        Candidate.objects.filter(user__external_id=user_external_id)
        .select_related("hub", "user")
        .first()
    )


def _require(user_external_id: str, *allowed_status) -> Candidate:
    cand = get_for_user_external_id(user_external_id)
    if cand is None:
        raise NotFound("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if allowed_status and cand.status not in allowed_status:
        # 409 + expected_status = a etapa ATUAL no servidor — o front roteia o wizard com isso.
        raise Conflict(
            "Seu cadastro está em outra etapa.",
            code="WRONG_STATUS",
            extra={"expected_status": cand.status},
        )
    return cand


def _set_status(cand: Candidate, to_status: str) -> None:
    cand.status = to_status
    cand.save(update_fields=["status", "updated_at"])


def to_dict(cand: Candidate) -> dict:
    return {
        "external_id": str(cand.external_id),
        "status": cand.status,
        "hub_external_id": str(cand.hub.external_id),
        "pix_validated": cand.pix_validated,
        "selfie_verified": cand.selfie_verified,
        "selfie_status": cand.selfie_status,
    }


# campos essenciais do endereço (espelha enrollment._ADDRESS_FIELDS; complement é opcional).
# `zipcode` incluso (fix 2026-07-05): sem ele, `missing_fields` podia ficar vazio com o
# `address.is_complete` (que exige zipcode) ainda falso — wizard preso sem o front saber por quê.
_ADDRESS_FIELDS = ("zipcode", "street", "number", "neighborhood", "city", "state")
# perfil do candidato: filiação/naturalidade VÊM da extração do documento (Fatia B, plan/15);
# estado civil/nacionalidade = o que o documento não traz (Portão 2: a etapa "perfil" coleta só esses).
_PROFILE_FIELDS = (
    "mother_name",
    "father_name",
    "birthplace",
    "marital_status",
    "nationality",
)


def me_dict(cand: Candidate) -> dict:
    """GET /me RICO do candidato (espelha `enrollment.me_dict`, plan/15): `status` + cada seção já
    preenchida + `missing_fields` por seção, numa chamada só. Bloco `None`/vazio = seção ainda não
    preenchida. **Toda mutação devolve este shape** → o front roteia o wizard sem re-fetch."""
    user_ext = str(cand.user.external_id)
    p = profiles.get(cand.user)

    # SEMPRE presente quando há Profile (fix Marilu 2026-07-05): name/birth_date vêm do CPFHub no
    # cadastro — o gate antigo (só montava se filiação preenchida) escondia birth_date do /me.
    profile = None
    if p:
        profile = {
            "mother_name": p.mother_name,
            "father_name": p.father_name,
            "birthplace": p.birthplace,
            "marital_status": p.marital_status,
            "nationality": p.nationality,
            "name": p.name,
            "birth_date": p.birth_date.isoformat() if p.birth_date else None,
            # escolaridade (nível-pessoa, F3): o front usa pra renderizar/pré-marcar a etapa `education`.
            "education_level": p.education_level,
            "education_completed": p.education_completed,
            "education_grade": p.education_grade,
            "education_last_completed_grade": p.education_last_completed_grade,
            "education_qualification": p.education_qualification,
            "education_last_completed_qualification": p.education_last_completed_qualification,
            "education_status": p.education_status,
            "education_year": p.education_year,
            "education_city": p.education_city,
            "education_school": p.education_school,
            # autoritativos do CPFHub — nenhum endpoint do candidato os edita; o front usa
            # esta flag pra travar/destacar os inputs (sombra verde + ✓).
            "locked_fields": ["name", "birth_date"],
        }

    # Candidato ainda SEM endereço é o estado normal no começo do funil — não pode explodir.
    # (Estourava AttributeError dentro do próprio gate `current_step`, então a pessoa nem
    # chegava a ser redirecionada pro passo do endereço: 500 na cara.)
    addr_obj = address_iface.get_by_external_id(user_ext)
    address = (
        address_iface.as_public_dict(addr_obj)
        if addr_obj is not None
        else dict.fromkeys(_ADDRESS_FIELDS)
    )
    address["missing_fields"] = [f for f in _ADDRESS_FIELDS if not address.get(f)]

    from users.roles import _address_proof

    selfie = _selfie_dict(cand)

    try:
        docs = documents_iface.get_by_external_id(user_ext)
    except NotFound:
        docs = None

    return {
        **to_dict(cand),
        "profile": profile,
        "address": address,
        "address_proof": _address_proof.section_dict(user_ext),
        "documents": docs,
        "selfie": selfie,
        "blocks": [blocks.to_dict(b) for b in blocks.get_active_blocks(cand.user)],
    }


# ── funil de coleta (autenticado, role candidate) ───────────────────────────


def set_profile(
    *,
    user_external_id,
    mother_name=None,
    father_name=None,
    marital_status=None,
    birthplace=None,
    nationality=None,
) -> dict:
    cand = _require(user_external_id, _S.STARTED, _S.PROFILE)
    # identidade → SÓ no Profile (Victor 2026-06-16), nunca no candidate
    profiles.fill_identity(
        cand.user,
        mother_name=mother_name,
        father_name=father_name,
        marital_status=marital_status,
        birthplace=birthplace,
        nationality=nationality,
    )
    if cand.status == _S.STARTED:
        _set_status(cand, _S.PROFILE)
    return me_dict(cand)


def get_address(*, user_external_id) -> dict:
    """GET do endereço + `missing_fields` (o front renderiza input só do que falta)."""
    _require(user_external_id)
    data = address_iface.as_public_dict(
        address_iface.get_by_external_id(user_external_id)
    )
    data["missing_fields"] = [f for f in _ADDRESS_FIELDS if not data.get(f)]
    return data


def set_address_cep(*, user_external_id, cep) -> dict:
    """Busca o CEP (ViaCEP) e preenche o endereço. Em cidade de CEP único a rua fica vazia p/ digitar."""
    cand = _require(user_external_id, _S.PROFILE, _S.ADDRESS)
    address_iface.set_by_cep(external_id=user_external_id, cep=cep)
    _advance_address(cand, user_external_id)
    return me_dict(cand)


def set_address_data(*, user_external_id, **fields) -> dict:
    """Preenche/CORRIGE os demais campos do endereço — sobrescreve o que vier no payload.

    Fix Marilu 2026-07-05: o `fill_empty` antigo só escrevia em campo VAZIO — corrigir um número
    errado era descartado em silêncio ("mandei, voltou"). Agora usa `patch` (sobrescreve); valor
    vazio/None no payload é ignorado (só muda o que o front mandou de verdade)."""
    cand = _require(user_external_id, _S.PROFILE, _S.ADDRESS)
    fields = {k: v for k, v in fields.items() if v not in (None, "")}
    if fields:
        address_iface.patch(external_id=user_external_id, **fields)
    _advance_address(cand, user_external_id)
    return me_dict(cand)


def _advance_address(cand: Candidate, user_external_id) -> None:
    """Endereço completo → ADDRESS. Comprovante validado em background (rejeição = ValidationBlock)."""
    if cand.status == _S.PROFILE and address_iface.is_complete(
        address_iface.get_by_external_id(user_external_id)
    ):
        _set_status(cand, _S.ADDRESS)


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


def upload_address_proof(*, user_external_id, upload) -> dict:
    """Comprovante de residência (foto/PDF) — OBRIGATÓRIO + validado por IA (F1). Salva a foto,
    marca `pending` e enfileira a validação (endereço + titular). Aceito já na etapa `address`."""
    cand = _require(
        user_external_id,
        _S.PROFILE,
        _S.ADDRESS,
        _S.DOCUMENTS,
        _S.PIX,
        _S.SELFIE,
        _S.COMPLETED,
    )
    documents_iface.upload_photo(user_external_id, "address_proof_photo", upload)
    ap = documents_iface.get_address_proof(user_external_id)
    if ap is not None:
        ap.validation_status = "pending"
        ap.save(update_fields=["validation_status"])
    from django_q.tasks import async_task

    async_task("users.roles.candidate.tasks.validate_address_proof", cand.id)
    return me_dict(cand)


def submit_address_proof_kinship(*, user_external_id, relation: str) -> dict:
    """Titular do comprovante é outra pessoa (`needs_kinship`): a pessoa explica o parentesco → libera."""
    from users.roles import _address_proof

    # APPROVED entra na lista (2026-07-29): o comprovante é revalidado DEPOIS que a pessoa já virou
    # promotora — a IA lê e pede o parentesco. Sem isso ela caía em WRONG_STATUS e o app a mandava
    # de volta pra mesma tela, em loop, sem nunca conseguir responder.
    cand = _require(
        user_external_id,
        _S.PROFILE,
        _S.ADDRESS,
        _S.DOCUMENTS,
        _S.PIX,
        _S.SELFIE,
        _S.COMPLETED,
        _S.APPROVED,
    )
    _address_proof.submit_kinship(user_external_id, relation)
    if cand.status != _S.APPROVED:
        _advance_address(cand, user_external_id)
        _complete_candidate(cand)
    return me_dict(cand)


def run_address_proof_validation(candidate_id: int) -> None:
    """Task async: valida o comprovante (visão → endereço → titular) e, se aprovar, avança o wizard."""
    from users.roles import _address_proof

    cand = Candidate.objects.filter(id=candidate_id).select_related("user").first()
    if cand is None:
        return
    user_ext = str(cand.user.external_id)
    _address_proof.validate_and_store(user_ext, caller="candidate.address_proof")
    cand.refresh_from_db(fields=["status"])
    _advance_address(cand, user_ext)
    _complete_candidate(cand)


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


def run_document_validation(candidate_id: int, slot: str) -> None:
    """Pipeline da task (plan/15 B3). Idempotente: só age com validação `pending`. Mesma
    sequência do `run_rg_validation` do enrollment:
      a) visão na foto do `slot` (é rg/cnh? lado certo? legível?) → reprovou/dúvida = notifica;
      b) seção completa (inteira aprovada OU frente+verso aprovadas) → OCR + extração (1 LLM);
      c) nome de outra pessoa → reprova; dúvida → review; ok → povoa campos VAZIOS →
         biometria → avança o wizard."""
    from pathlib import Path

    from users.roles import _document_ai as doc_ai

    cand = (
        Candidate.objects.select_related("user", "hub", "hub__coordinator")
        .filter(id=candidate_id)
        .first()
    )
    if cand is None or not cand.doc_type:
        return
    user_ext = str(cand.user.external_id)
    sub = documents_iface.get_doc_sub(user_ext, cand.doc_type)
    if sub is None or sub.validation_status != doc_ai.PENDING:
        return

    result = sub.validation_result or {}
    photos = dict(result.get("photos") or {})

    field = _DOC_SLOT_FIELD.get(slot)
    path = getattr(sub, field, None) if field else None
    if path and (photos.get(slot) or {}).get("status") != doc_ai.APPROVED:
        fp = Path(settings.MEDIA_ROOT) / path
        if not fp.exists():
            return
        mime = _MIME_BY_EXT.get(fp.suffix.lstrip(".").lower(), "image/jpeg")
        doc_ai.fix_orientation(str(fp), mime_type=mime, caller="candidate.document")
        status, reason = doc_ai.check_photo(
            fp.read_bytes(),
            side=_DOC_SLOT_SIDE[slot],
            doc_type=cand.doc_type,
            mime_type=mime,
            caller="candidate.document",
        )
        # merge FRESCO (visão 10-60s; frente+verso em 2 workers paralelos — não perder o outro)
        sub.refresh_from_db()
        if sub.validation_status != doc_ai.PENDING:
            return
        # G11: a foto deste slot trocou no meio tempo (re-upload) → o veredito é da foto velha,
        # descarta. `path` foi capturado no início; comparar com o atual identifica a troca (o
        # check de status sozinho não pega um re-upload que re-arma PENDING).
        if getattr(sub, field, None) != path:
            return
        result = sub.validation_result or {}
        photos = dict(result.get("photos") or {})
        photos[slot] = {"status": status, "reason": reason}
        result["photos"] = photos
        if status != doc_ai.APPROVED:
            _finish_doc(cand, sub, status, reason, result)
            return

    images = _doc_approved_images(sub, photos, cand.doc_type)
    if images is None:
        sub.validation_result = result
        sub.save(update_fields=["validation_result"])
        return
    _doc_extract_and_finish(cand, sub, result, images)


def _doc_approved_images(sub, photos: dict, doc_type: str) -> list | None:
    """Imagens da seção completa e aprovada (inteira OU frente+verso), ou None se falta."""
    from pathlib import Path

    from users.roles import _document_ai as doc_ai

    prefix = f"{doc_type}_"

    def ok(slot: str) -> bool:
        return (photos.get(slot) or {}).get("status") == doc_ai.APPROVED

    full = getattr(sub, "full_photo", None)
    if full and ok(f"{prefix}full"):
        return [Path(settings.MEDIA_ROOT) / full]
    if (
        getattr(sub, "front_photo", None)
        and getattr(sub, "back_photo", None)
        and ok(f"{prefix}front")
        and ok(f"{prefix}back")
    ):
        return [
            Path(settings.MEDIA_ROOT) / sub.front_photo,
            Path(settings.MEDIA_ROOT) / sub.back_photo,
        ]
    return None


def _doc_extract_and_finish(cand: Candidate, sub, result: dict, images: list) -> None:
    """OCR + extração (1 LLM, plan/15 B3): confere o nome e povoa os campos do sub-doc + perfil."""
    from users.roles import _document_ai as doc_ai

    p = profiles.get(cand.user)
    try:
        ocr_text = doc_ai.ocr_images(
            [fp.read_bytes() for fp in images], caller="candidate.document"
        )
        data = doc_ai.extract_document(
            ocr_text,
            doc_type=cand.doc_type,
            holder_name=(p.name if p else None),
            caller="candidate.document",
        )
    except Exception as exc:  # noqa: BLE001 — IA fora do ar → review
        logger.warning(
            "candidate.doc_extract_failed",
            candidate=str(cand.external_id),
            error=str(exc)[:200],
        )
        _finish_doc(
            cand,
            sub,
            doc_ai.REVIEW,
            "IA indisponível na extração dos dados — enviado para revisão manual do coordenador.",
            result,
        )
        return
    # guard do worker-zumbi: o OCR + extração acima levam ~15s; se NESSE meio o sweep do TTL
    # (worker lento) ou o coordenador já decidiu, NÃO sobrescrever a decisão. Mesma régua que a
    # visão aplica no re-check acima — aqui fecha a janela do estágio de extração.
    sub.refresh_from_db()
    if sub.validation_status != doc_ai.PENDING:
        return
    result["extracted"] = data
    match = str(data.get("name_match") or "").strip().lower()
    name_reason = (data.get("name_reason") or "").strip()
    if match in ("nao", "não", "no"):
        _finish_doc(
            cand,
            sub,
            doc_ai.REJECTED,
            f"O nome no documento não confere com o do cadastro. {name_reason}".strip(),
            result,
        )
        return
    if match not in ("sim", "yes"):
        _finish_doc(
            cand,
            sub,
            doc_ai.REVIEW,
            f"Não deu pra confirmar o nome do titular. {name_reason}".strip(),
            result,
        )
        return
    _apply_doc_extracted(cand, sub, data)
    _finish_doc(
        cand, sub, doc_ai.APPROVED, name_reason or "Documento validado.", result
    )
    _notify_doc_event(
        cand=cand,
        event="candidate.document_approved",
        subject="Seu cadastro — documento aprovado",
    )  # notify também no aprovado automático (espelha plan/13)
    _doc_post_approval(cand, sub)


def _apply_doc_extracted(cand: Candidate, sub, data: dict) -> None:
    """Povoa SÓ campos vazios (Victor: não sobrescrever). RG/CNH compartilhados por sub-doc;
    aqui o que vale é o tipo."""
    from datetime import date

    def _clean(value, limit: int):
        s = str(value).strip()
        return s[:limit] if s else None

    def _date(value):
        try:
            return date.fromisoformat(str(value)) if value else None
        except ValueError:
            return None

    sub_changed = []
    # RG-specific
    if cand.doc_type == "rg":
        if not sub.number and data.get("number"):
            sub.number = _clean(data["number"], 30)
            sub_changed.append("number")
        if not sub.issuing_agency and data.get("issuing_agency"):
            sub.issuing_agency = _clean(data["issuing_agency"], 50)
            sub_changed.append("issuing_agency")
        if not sub.issue_date:
            d = _date(data.get("issue_date"))
            if d:
                sub.issue_date = d
                sub_changed.append("issue_date")
    # CNH-specific
    elif cand.doc_type == "cnh":
        if not sub.number and data.get("number"):
            sub.number = _clean(data["number"], 30)
            sub_changed.append("number")
        if not sub.category and data.get("category"):
            sub.category = _clean(data["category"], 5)
            sub_changed.append("category")
        if not sub.national_register and data.get("national_register"):
            sub.national_register = _clean(data["national_register"], 30)
            sub_changed.append("national_register")
        if not sub.expires_on:
            d = _date(data.get("expires_on"))
            if d:
                sub.expires_on = d
                sub_changed.append("expires_on")
        if not sub.date_of_birth:
            d = _date(data.get("birth_date"))
            if d:
                sub.date_of_birth = d
                sub_changed.append("date_of_birth")
    # OBS (fix 2026-07-12): o nascimento do RG NÃO fica no sub-doc — o modelo `RG` não tem
    # `date_of_birth` (só a `CNH` tem). A data de nascimento é CENTRALIZADA no Profile logo
    # abaixo via `profiles.fill_identity(birth_date=...)` (Victor 2026-06-16: identidade mora
    # SÓ no Profile). O bloco antigo aqui acessava `sub.date_of_birth` p/ RG e quebrava a
    # extração (AttributeError) assim que um RG passava na validação da foto.
    if sub_changed:
        sub.save(update_fields=sub_changed)

    # filiação/naturalidade + nascimento extraídos do documento → CENTRALIZADO no Profile
    # (Victor 2026-06-16: a identidade mora SÓ no Profile, nunca espalhada no candidate).
    profiles.fill_identity(
        cand.user,
        mother_name=_clean(data["mother_name"], 255)
        if data.get("mother_name")
        else None,
        father_name=_clean(data["father_name"], 255)
        if data.get("father_name")
        else None,
        birthplace=_clean(data["birthplace"], 128) if data.get("birthplace") else None,
        birth_date=_date(data.get("birth_date")),
    )
    # G8/#19: o OCR pode ter acabado de preencher o `number` que faltava — re-avalia o avanço
    # DOCUMENTS→PIX. Guarded (só avança com doc aprovado + number), idempotente nos callsites de
    # validação que já chamam _advance_documents depois. Sem isso, o candidato ficava preso em
    # DOCUMENTS após a aprovação manual quando o número só veio pelo OCR.
    _advance_documents(cand, str(cand.user.external_id))


def _finish_doc(
    cand: Candidate, sub, status: str, reason: str | None, result: dict
) -> None:
    """Grava o veredito (justificativa SEMPRE — plan/9) + dispara o notify do estado."""
    from django.utils import timezone

    from users.roles import _document_ai as doc_ai

    result["reason"] = reason
    sub.validation_status = status
    sub.validation_result = result
    sub.validated_at = timezone.now()
    sub.save(update_fields=["validation_status", "validation_result", "validated_at"])
    logger.info(
        "candidate.doc_validated",
        candidate=str(cand.external_id),
        doc_type=cand.doc_type,
        status=status,
    )
    if status == doc_ai.REJECTED:
        _notify_doc_event(cand=cand, event="candidate.document_rejected", detail=reason)
    elif status == doc_ai.REVIEW:
        _notify_doc_event(
            cand=cand, event="candidate.document_in_review", detail=reason
        )


def _doc_post_approval(cand: Candidate, sub) -> None:
    """Aprovado → AVANÇA o wizard PRIMEIRO, biometria best-effort DEPOIS: um crash da biometria
    (InsightFace/onnxruntime pode matar o worker) NÃO pode perder o avanço do wizard (Victor 2026-06-16)."""
    # o doc já está aprovado + com número → avança documents→pix ANTES de tocar na biometria.
    _advance_documents(cand, str(cand.user.external_id))
    _complete_candidate(cand)

    from pathlib import Path

    from integrations.tools.biometric import service as biometric

    from users.roles import _document_ai as doc_ai

    face_path = sub.front_photo or sub.full_photo
    face_slot = f"{cand.doc_type}_front"
    if face_path:
        full = Path(settings.MEDIA_ROOT) / face_path
        enrolled = biometric.try_enroll_document(
            user=cand.user,
            slot=face_slot,
            image_path=str(full),
            caller="candidate.document",
        )
        if enrolled is None and full.exists():
            cropped = doc_ai.crop_face(full.read_bytes(), caller="candidate.document")
            if cropped:
                crop_path = full.with_name(f"{cand.doc_type}_face_crop.jpg")
                crop_path.write_bytes(cropped)
                biometric.try_enroll_document(
                    user=cand.user,
                    slot=face_slot,
                    image_path=str(crop_path),
                    caller="candidate.document_crop",
                )


def run_document_fill(candidate_id: int) -> None:
    """Pós-aprovação do coordenador: OCR+extração best-effort SÓ pra preencher campos vazios.
    A aprovação humana é FINAL — aqui não há veto (o `name_match` fica só registrado)."""
    from users.roles import _document_ai as doc_ai

    cand = (
        Candidate.objects.select_related("user", "hub").filter(id=candidate_id).first()
    )
    if cand is None or not cand.doc_type:
        return
    user_ext = str(cand.user.external_id)
    sub = documents_iface.get_doc_sub(user_ext, cand.doc_type)
    if sub is None or sub.validation_status != doc_ai.APPROVED:
        return
    # já tem extração? só repopula o que ficou faltando
    result = sub.validation_result or {}
    if result.get("extracted"):
        _apply_doc_extracted(cand, sub, result["extracted"])
        return
    # sem extração anterior: roda OCR+extração best-effort
    images = _doc_approved_images(sub, result.get("photos") or {}, cand.doc_type)
    if not images:
        return
    p = profiles.get(cand.user)
    try:
        ocr_text = doc_ai.ocr_images(
            [fp.read_bytes() for fp in images], caller="candidate.document_fill"
        )
        data = doc_ai.extract_document(
            ocr_text,
            doc_type=cand.doc_type,
            holder_name=(p.name if p else None),
            caller="candidate.document_fill",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; falha = aluno digita
        logger.warning(
            "candidate.doc_fill_failed",
            candidate=str(cand.external_id),
            error=str(exc)[:200],
        )
        return
    result["extracted"] = data
    sub.validation_result = result
    sub.save(update_fields=["validation_result"])
    _apply_doc_extracted(cand, sub, data)


def decide_document(
    *,
    candidate_external_id: str,
    coordinator,
    approve: bool,
    reason: str | None = None,
) -> dict:
    """Coordenador do hub decide o documento do candidato em REVISÃO. Espelha `decide_rg`."""
    from users.roles import _document_ai as doc_ai

    cand = (
        Candidate.objects.filter(external_id=candidate_external_id)
        .select_related("hub", "user")
        .first()
    )
    if cand is None:
        raise CandidateError("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if cand.hub.coordinator_id != coordinator.id:
        raise CandidateError(
            "Você não coordena o polo deste candidato.", code="NOT_HUB_COORDINATOR"
        )
    if not cand.doc_type:
        raise CandidateError("Documento ainda não enviado.", code="DOC_TYPE_NOT_SET")
    sub = documents_iface.get_doc_sub(str(cand.user.external_id), cand.doc_type)
    if sub is None or sub.validation_status != doc_ai.REVIEW:
        raise CandidateError(
            "O documento não está em revisão.",
            code="DOC_NOT_IN_REVIEW",
            extra={"validation_status": sub.validation_status if sub else None},
        )
    note = (reason or "").strip() or (
        "aprovado pelo coordenador" if approve else "reprovado pelo coordenador"
    )
    result = sub.validation_result or {}
    result["human"] = {
        "approve": approve,
        "reason": note,
        "by": str(coordinator.external_id),
    }
    if not approve:
        _finish_doc(cand, sub, doc_ai.REJECTED, note, result)
        return me_dict(cand)
    # aprovação humana: as fotos presentes valem como aprovadas
    photos = dict(result.get("photos") or {})
    for slot, field in _DOC_SLOT_FIELD.items():
        if getattr(sub, field, None):
            photos[slot] = {"status": doc_ai.APPROVED, "reason": note}
    result["photos"] = photos
    _finish_doc(cand, sub, doc_ai.APPROVED, note, result)
    _notify_doc_event(
        cand=cand,
        event="candidate.document_approved",
        subject="Seu cadastro — documento aprovado",
    )
    if result.get("extracted"):
        _apply_doc_extracted(cand, sub, result["extracted"])
    else:
        from django_q.tasks import async_task

        async_task("users.roles.candidate.tasks.fill_document_data", cand.id)
    _doc_post_approval(cand, sub)
    return me_dict(cand)


def _notify_doc_event(
    *,
    cand: Candidate,
    event: str,
    detail: str | None = None,
    subject: str | None = None,
) -> None:
    """Despachante único dos notifies do documento do candidato (plan/15 B3, refator do /python-review).

    Direciona o destinatário pelo `event` configurado no notify-server:
      • `candidate.document_in_review` → coordenador do hub
      • `candidate.document_rejected` / `candidate.document_approved` → candidato

    Falha do `send` vira WARNING (a análise IA segue válida — o destinatário pode descobrir pelo
    app; o notify tem retry/canal alternativo internamente, então engolir aqui é proposital).

    wave-2: send_event lê teor/canais/is_tts do Template no DB."""
    from notify.interface.events import send_event

    if event == "candidate.document_in_review":
        coord = cand.hub.coordinator
        if coord is None:
            return
        cp = profiles.get(coord)
        target_profile = cp
        channels = ("whatsapp",)  # coordenador: WhatsApp-only (legado)
    else:
        target_profile = profiles.get(cand.user)
        channels = None  # Template decide os canais

    try:
        send_event(
            event,
            profile=target_profile,
            ctx={"detail": detail or ""},
            subject=subject,
            channels_override=channels,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "candidate.notify_doc_event_failed", doc_event=event, error=str(exc)
        )


def _sweep_stale_reviews(hub) -> None:
    from users.documents.models import CNH, RG
    from users.roles import _analysis

    _analysis.sweep_stale_selfies(Candidate, hub)
    user_ids = list(Candidate.objects.filter(hub=hub).values_list("user_id", flat=True))
    for model in (RG, CNH):
        _analysis.sweep_stale_documents(
            model.objects.filter(document__user_id__in=user_ids), _doc_started_at
        )


def list_document_reviews_for_hub(*, hub) -> list[dict]:
    """Candidatos do polo com o documento parado em REVISÃO (decisão do coordenador — plan/15 B3).
    Cada item aponta pro POST de decisão que existe. Antes, varre PENDING órfão → review."""
    from users.roles import _document_ai as doc_ai

    _sweep_stale_reviews(hub)
    out = []
    qs = (
        Candidate.objects.filter(hub=hub, doc_type__isnull=False)
        .exclude(doc_type="")
        .select_related("user")
        .order_by("updated_at")
    )
    for cand in qs:
        sub = documents_iface.get_doc_sub(str(cand.user.external_id), cand.doc_type)
        if sub is None or sub.validation_status != doc_ai.REVIEW:
            continue
        p = profiles.get(cand.user)
        out.append(
            {
                "external_id": str(cand.external_id),
                "name": p.name if p else None,
                "doc_type": cand.doc_type,
                "since": cand.updated_at.isoformat(),
            }
        )
    return out


def set_pix(*, user_external_id, key: str, key_type: str) -> dict:
    """Valida a chave Pix no Asaas/DICT (confere que é do candidato, CPF do Profile) e grava. MEXE R$0,01."""
    from integrations.bank.asaas import pixkey

    # apelidos PT do front (celular/aleatoria/…) → tipo canônico do DICT (PHONE/EVP/…); o Profile
    # guarda SEMPRE o canônico.
    key_type = pixkey.normalize_key_type(key_type)
    cand = _require(user_external_id, _S.DOCUMENTS, _S.PIX)
    profile = profiles.find_by_external_id(user_external_id)
    if profile is None or not profile.cpf:
        raise CandidateError(
            "CPF do perfil ausente — refaça o cadastro.", code="PROFILE_CPF_MISSING"
        )
    try:
        pixkey.validate_pix_key(
            key=key, key_type=key_type, expected_document=profile.cpf
        )
    except pixkey.PixKeyError as exc:
        raise CandidateError(
            "Chave Pix inválida ou não é do titular.",
            code="PIX_INVALID",
            extra={"reason": str(exc)},
        ) from exc

    # chave Pix canônica → SÓ no Profile (Victor 2026-06-16); no candidate fica só o flag de processo.
    profiles.set_pix(user_external_id, key.strip(), key_type)
    cand.pix_validated = True
    cand.save(update_fields=["pix_validated", "updated_at"])
    if cand.status == _S.DOCUMENTS:
        _set_status(cand, _S.PIX)
    logger.info("candidate.pix_validated", external_id=str(cand.external_id))
    return me_dict(cand)


# escolaridade — ÚLTIMA pergunta antes da selfie (Victor 2026-07-08). Grava no Profile (nível-pessoa),
# reusada quando/se virar aluno. Sem médio completo → o promotor nasce `pre_matriculado` (F4). Fica
# ANTES da selfie de propósito: a selfie aprovada auto-promove (F2), então a escolaridade tem que
# ser coletada antes disso. Só nível+concluiu (série/escola são riqueza do enrollment, não do funil promotor).
_EDU_LEVELS = ("fundamental", "medio", "superior")
_EDU_QUALIFICATIONS = ("graduacao", "pos_graduacao", "mestrado", "doutorado")


def set_education(
    *,
    user_external_id,
    level: str,
    completed: bool,
    grade: int | None = None,
    last_completed_grade: int | None = None,
    qualification: str | None = None,
    last_completed_qualification: str | None = None,
    education_status: str | None = None,
    year: int | None = None,
    city: str | None = None,
    school: str | None = None,
) -> dict:
    cand = _require(user_external_id, _S.PIX, _S.EDUCATION)
    if level not in _EDU_LEVELS:
        raise CandidateError(
            "Nível de ensino inválido.",
            code="EDUCATION_LEVEL_INVALID",
            extra={"level": level, "allowed": list(_EDU_LEVELS)},
        )
    allowed_grades = range(1, 10) if level == "fundamental" else range(1, 4)
    if level != "superior" and grade is not None and grade not in allowed_grades:
        raise CandidateError(
            "Série/ano incompatível com o nível de ensino.",
            code="EDUCATION_GRADE_INVALID",
            extra={"grade": grade, "level": level},
        )
    if level == "superior":
        if qualification not in _EDU_QUALIFICATIONS:
            raise CandidateError(
                "Formação superior inválida.",
                code="EDUCATION_QUALIFICATION_INVALID",
                extra={
                    "qualification": qualification,
                    "allowed": list(_EDU_QUALIFICATIONS),
                },
            )
        if grade is not None or last_completed_grade is not None:
            raise CandidateError(
                "Ensino Superior deve informar formação, não série.",
                code="EDUCATION_GRADE_INVALID",
                extra={"grade": grade, "level": level},
            )
    elif qualification is not None or last_completed_qualification is not None:
        raise CandidateError(
            "Formação superior só pode ser usada no Ensino Superior.",
            code="EDUCATION_QUALIFICATION_INVALID",
        )
    education_status = education_status or ("completed" if completed else "stopped")
    if education_status not in ("completed", "attending", "stopped"):
        raise CandidateError(
            "Situação escolar inválida.",
            code="EDUCATION_STATUS_INVALID",
            extra={"education_status": education_status},
        )
    if level == "superior" and education_status == "completed":
        if (
            last_completed_qualification is not None
            and last_completed_qualification != qualification
        ):
            raise CandidateError(
                "A última formação concluída deve coincidir com a formação informada.",
                code="EDUCATION_LAST_COMPLETED_QUALIFICATION_INVALID",
            )
        last_completed_qualification = qualification
    elif level == "superior":
        if (
            last_completed_qualification is not None
            and last_completed_qualification not in _EDU_QUALIFICATIONS
        ):
            raise CandidateError(
                "Última formação concluída inválida.",
                code="EDUCATION_LAST_COMPLETED_QUALIFICATION_INVALID",
            )
        if last_completed_qualification is not None and qualification is not None:
            if _EDU_QUALIFICATIONS.index(
                last_completed_qualification
            ) >= _EDU_QUALIFICATIONS.index(qualification):
                raise CandidateError(
                    "A última formação concluída deve ser anterior à formação frequentada.",
                    code="EDUCATION_LAST_COMPLETED_QUALIFICATION_INVALID",
                )
    elif education_status == "completed":
        if last_completed_grade is not None and last_completed_grade != grade:
            raise CandidateError(
                "A última série concluída deve coincidir com a série informada.",
                code="EDUCATION_LAST_COMPLETED_GRADE_INVALID",
                extra={"grade": grade, "last_completed_grade": last_completed_grade},
            )
        last_completed_grade = grade
    elif last_completed_grade is not None:
        max_completed = (grade - 1) if grade is not None else max(allowed_grades)
        if last_completed_grade < 0 or last_completed_grade > max_completed:
            raise CandidateError(
                "A última série concluída deve ser anterior à série frequentada.",
                code="EDUCATION_LAST_COMPLETED_GRADE_INVALID",
                extra={
                    "grade": grade,
                    "last_completed_grade": last_completed_grade,
                    "min": 0,
                    "max": max_completed,
                },
            )
    if level == "superior":
        level_completed = education_status == "completed"
    elif grade is None:
        level_completed = bool(completed)
    else:
        final_grade = 9 if level == "fundamental" else 3
        level_completed = education_status == "completed" and grade == final_grade
    if year is not None:
        from django.utils import timezone

        if year < 1950 or year > timezone.now().year + 1:
            raise CandidateError(
                "Ano da última frequência inválido.",
                code="EDUCATION_YEAR_INVALID",
                extra={"year": year},
            )
    profiles.set_education(
        cand.user,
        level=level,
        completed=level_completed,
        grade=grade,
        last_completed_grade=last_completed_grade,
        qualification=qualification,
        last_completed_qualification=last_completed_qualification,
        education_status=education_status,
        year=year,
        city=(city or "").strip() or None,
        school=(school or "").strip() or None,
    )
    if cand.status == _S.PIX:
        _set_status(cand, _S.EDUCATION)
    logger.info(
        "candidate.education_set",
        external_id=str(cand.external_id),
        level=level,
        grade=grade,
        last_completed_grade=last_completed_grade,
        qualification=qualification,
        last_completed_qualification=last_completed_qualification,
        education_status=education_status,
        completed=level_completed,
    )
    return me_dict(cand)


def get_selfie(*, user_external_id: str) -> dict:
    """GET da selfie/ASSINATURA (plan/15 C). Espelha a seção do enrollment: foto, taken_at,
    `analysis_status` (canônico) + `status` (alias), `analysis_reason` (instruções se reprovou),
    `expires_at` (TTL do `pending`).

    LEITURA PURA (idempotência HTTP): NÃO muta status nem notifica. O envelhecimento do `pending`
    estourado → `review` + notify roda no job agendado `tasks.age_stale_selfies` (Django-Q),
    fora do caminho do GET (antes um retry/crawler/preflight disparava a transição)."""
    cand = _require(user_external_id, _S.PIX, _S.EDUCATION, _S.SELFIE, _S.COMPLETED)
    return _selfie_dict(cand)


def set_selfie(
    *,
    user_external_id,
    image_bytes: bytes,
    content_type="image/jpeg",
    consent_ip: str | None = None,
    consent_user_agent: str | None = None,
) -> dict:
    """Selfie ("assinar") — ASSÍNCRONA (plan/15 C, espelha o enrollment):

    1. salva a foto
    2. marca `selfie_status=PENDING` + `selfie_taken_at=now`
    3. ENFILEIRA `users.roles.candidate.tasks.validate_candidate_selfie` (Django-Q)
    4. devolve o **ack** `{stored, analysis_status:"pending", poll_after_ms, expires_at}`

    O front acompanha pelo `GET /candidate/selfie` até virar `approved`/`rejected`/`review`. A
    pipeline roda fora do request (liveness → face-match vs documento → instruções se reprovou);
    o veredito final decide promover / notificar o candidato / escalar pro coordenador."""
    from django.utils import timezone

    from users.consent import PROMOTER_CONTRACT
    from users.roles import _selfie

    cand = _require(user_external_id, _S.EDUCATION, _S.SELFIE)
    cand.selfie_image = _save_selfie(cand, image_bytes, content_type)
    cand.selfie_taken_at = timezone.now()
    cand.selfie_status = _selfie.SelfieStatus.PENDING
    cand.selfie_verified = False
    cand.selfie_description = None
    # consentimento LGPD (lane #6): a selfie enviada com sucesso É o aceite do contrato.
    cand.consent_accepted = True
    cand.contract_version = PROMOTER_CONTRACT.version
    cand.contract_hash = PROMOTER_CONTRACT.hash
    cand.consent_ip = consent_ip
    cand.consent_user_agent = consent_user_agent
    cand.consent_accepted_at = cand.selfie_taken_at
    # BUG-4 (M2c FE-painel, 2026-06-16): worker exige `status==SELFIE` (`run_selfie_validation`
    # linha 1120) — se não avançar, bail-out silencioso e o pending vira review via TTL reconcile.
    # Espelha o `enrollment.set_selfie` (gate em `_S.SELFIE`, advance feito no `set_education`).
    if cand.status == _S.EDUCATION:
        _set_status(cand, _S.SELFIE)
    cand.save()
    from django_q.tasks import async_task

    async_task("users.roles.candidate.tasks.validate_candidate_selfie", cand.id)
    return _selfie_ack(cand)


def _selfie_ack(cand: Candidate) -> dict:
    """Ack canônico (mesma régua do `enrollment.selfie_ack`) pra responder no POST."""
    from users.roles import _analysis

    return {
        "stored": True,
        "analysis_status": _analysis.PENDING,
        "poll_after_ms": _analysis.poll_after_ms(),
        "expires_at": _analysis.expires_at(cand.selfie_taken_at).isoformat()
        if cand.selfie_taken_at
        else None,
    }


def _selfie_dict(cand: Candidate) -> dict:
    """Bloco da selfie (GET /selfie e o bloco `selfie` do /me — espelha enrollment/_selfie_dict)."""
    from users.roles import _analysis

    status = cand.selfie_status if cand.selfie_image else None
    return {
        "exists": bool(cand.selfie_image),
        "photo": cand.selfie_image,
        "taken_at": cand.selfie_taken_at.isoformat() if cand.selfie_taken_at else None,
        "status": status,
        # canônico unificado (mesma régua do enrollment — proposta API #4): alias `status`/`description`
        # mantidos pra compat; `expires_at` = TTL do `pending` (proposta #2).
        "analysis_status": status,
        "analysis_reason": cand.selfie_description,
        "expires_at": (
            _analysis.expires_at(cand.selfie_taken_at).isoformat()
            if status == _analysis.PENDING and cand.selfie_taken_at
            else None
        ),
        "verified": cand.selfie_verified,
        "description": cand.selfie_description,
    }


def age_stale_selfies() -> int:
    from users.roles import _analysis

    return _analysis.age_stale_selfies(Candidate, _notify_selfie_review)


def run_selfie_validation(candidate_id: int) -> None:
    """Pipeline async da selfie do CANDIDATO (plan/15 C, espelha `enrollment.run_selfie_validation`).

    a) liveness (é selfie real? vale ir pra biometria?)
    b) face-match biométrico selfie × documento (do candidato — RG ou CNH aprovada)
    c) reprovou? a visão gera INSTRUÇÕES práticas de como ser aprovada
    d) 3 estados: aprovada→promove training; reprovada→avisa candidato; review→avisa coord.

    Idempotente: só age com `selfie_status` PENDING (re-upload no meio tempo descarta o veredito)."""
    from pathlib import Path

    from users.roles import _selfie

    cand = (
        Candidate.objects.select_related("user", "hub", "hub__coordinator")
        .filter(id=candidate_id)
        .first()
    )
    if cand is None or not cand.selfie_image or cand.status != _S.SELFIE:
        return
    if cand.selfie_status != _selfie.SelfieStatus.PENDING:
        return
    # G11: discriminador da foto desta task (status não detecta re-upload — ele re-arma PENDING).
    started_taken_at = cand.selfie_taken_at
    fp = Path(settings.MEDIA_ROOT) / cand.selfie_image
    if not fp.exists():
        return
    image_bytes = fp.read_bytes()
    # G21/#13: mime derivado da extensão (como o enrollment) — antes era "image/jpeg" hardcoded, e
    # uma selfie PNG/WebP ia pra visão/biometria rotulada como JPEG.
    content_type = _MIME_BY_EXT.get(fp.suffix.lstrip(".").lower(), "image/jpeg")
    status, desc = _selfie.verify(image_bytes, content_type, caller="candidate.selfie")
    # SOMAR (Victor 2026-06-05): face-match biométrico selfie × documento.
    status, desc = _selfie.add_face_match(
        user=cand.user,
        selfie_image_path=str(fp),
        caller="candidate.selfie",
        liveness_status=status,
        liveness_desc=desc,
    )
    if status == _selfie.REJECTED:
        tips = _selfie.instructions(
            image_bytes, content_type, reason=desc, caller="candidate.selfie"
        )
        if tips:
            desc = f"{desc}\n\nComo resolver: {tips}"
    cand.refresh_from_db(
        fields=["selfie_status", "selfie_reject_count", "selfie_taken_at"]
    )
    # G11: descarta se saiu de PENDING OU se a foto trocou (taken_at != o do início). Sem o check de
    # taken_at, um re-upload que re-armou PENDING passava e o veredito da foto velha gravava sobre a
    # nova (mesma classe do enrollment; o candidate estava com o mesmo bug).
    if (
        cand.selfie_status != _selfie.SelfieStatus.PENDING
        or cand.selfie_taken_at != started_taken_at
    ):
        return
    cand.selfie_status = status
    cand.selfie_verified = status == _selfie.APPROVED
    update_fields = [
        "selfie_status",
        "selfie_verified",
        "selfie_description",
        "updated_at",
    ]
    if status == _selfie.REJECTED:
        # F2: acumula os comentários da IA (não sobrescreve) e conta a reprovação — 5× sobe a flag.
        cand.selfie_reject_count += 1
        cand.selfie_description = _selfie.append_reason(
            cand.selfie_description, cand.selfie_reject_count, desc
        )
        update_fields.append("selfie_reject_count")
    else:
        cand.selfie_description = desc
    cand.save(update_fields=update_fields)
    logger.info(
        "candidate.selfie_validated", candidate=str(cand.external_id), status=status
    )
    _resolve_selfie(cand)


def _save_selfie(cand: Candidate, image_bytes: bytes, content_type: str) -> str:
    from pathlib import Path

    ext = _SELFIE_EXT.get(content_type, "jpg")
    rel = f"candidate/{cand.external_id}/selfie.{ext}"
    fp = Path(settings.MEDIA_ROOT) / rel
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_bytes(image_bytes)
    return rel


def _resolve_selfie(cand: Candidate) -> None:
    """Reage ao veredito da selfie: aprovada→notifica+promove; reprovada→avisa candidato; revisão→avisa coordenador."""
    from users.roles import _selfie

    if cand.selfie_status == _selfie.APPROVED:
        _notify_selfie_approved(cand)
        _complete_candidate(cand)
    elif cand.selfie_status == _selfie.REJECTED:
        _notify_selfie_rejected(cand)
        # F2: 5ª reprovação → sobe a flag nível-pessoa (não bloqueia) e SEGUE promovendo — o encontro
        # presencial fica pro fim do curso (gate em `student._maybe_release_exam`).
        if cand.selfie_reject_count >= _selfie.MAX_REJECTS_BEFORE_MEETING:
            profiles.set_selfie_needs_meeting(cand.user)
            _complete_candidate(cand)
    elif cand.selfie_status == _selfie.REVIEW:
        _notify_selfie_review(cand)


def _notify_selfie_approved(cand: Candidate) -> None:
    """Notify do aprovado (plan/15 C — paridade com `enrollment.selfie_approved`). Sem TTS.

    wave-2: send_event lê teor/canais/is_tts do Template no DB."""
    from notify.interface.events import send_event

    p = profiles.get(cand.user)
    try:
        send_event(
            "candidate.selfie_approved",
            profile=p,
            idempotency_key=f"candidate_selfie_approved_{cand.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_selfie_approved_failed", error=str(exc))


def _promote_to_promoter(cand: Candidate) -> bool:
    """Promove candidate→PROMOTOR: cria Promoter + atribui matérias FIXAS do treino. Se houver
    matéria obrigatória pendente, o promotor nasce TRAVADO (overlay `training`, lido do /me). Devolve
    `locked`. Idempotente. Usado pela auto-promoção da selfie (F2) e pelo `approve_candidate`."""
    from users.roles.promoter import service as promoter_iface
    from users.roles.training import service as training_iface

    with transaction.atomic():
        if "promoter" not in roles.active_roles(cand.user):
            roles.promote(cand.user, "promoter")
        promoter_iface.create_promoter(user=cand.user, hub=cand.hub)
        _set_status(cand, _S.APPROVED)
        locked = training_iface.on_became_promoter(cand.user)
    _notify_became_promoter(cand, locked=locked)
    logger.info("candidate.approved", external_id=str(cand.external_id), locked=locked)
    return locked


def _complete_candidate(cand: Candidate) -> None:
    """Promove depois da selfie, sem prender as telas durante as análises assíncronas."""
    from users.roles import _address_proof, _document_ai, _selfie

    if cand.status not in (_S.SELFIE, _S.COMPLETED):
        return
    selfie_allowed = cand.selfie_verified or (
        cand.selfie_reject_count >= _selfie.MAX_REJECTS_BEFORE_MEETING
    )
    if not selfie_allowed:
        return
    user_ext = str(cand.user.external_id)
    document = (
        documents_iface.get_doc_sub(user_ext, cand.doc_type) if cand.doc_type else None
    )
    proof = documents_iface.get_address_proof(user_ext)
    checks_ready = bool(
        document
        and document.validation_status == _document_ai.APPROVED
        and proof
        and proof.validation_status == _address_proof.APPROVED
    )
    if not checks_ready:
        if cand.status == _S.SELFIE:
            _set_status(cand, _S.COMPLETED)
        return
    _promote_to_promoter(cand)


def decide_selfie(
    *, candidate_external_id: str, coordinator, approve: bool, reason: str | None = None
) -> Candidate:
    """Coordenador do hub decide a selfie em REVISÃO (sim/não). aprova→promove; reprova→avisa refazer."""
    from users.roles import _selfie

    cand = (
        Candidate.objects.filter(external_id=candidate_external_id)
        .select_related("hub", "user")
        .first()
    )
    if cand is None:
        raise CandidateError("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if cand.hub.coordinator_id != coordinator.id:
        raise CandidateError(
            "Você não coordena o polo deste candidato.", code="NOT_HUB_COORDINATOR"
        )
    if cand.selfie_status != _selfie.REVIEW:
        raise CandidateError(
            "A selfie não está em revisão.",
            code="SELFIE_NOT_IN_REVIEW",
            extra={"selfie_status": cand.selfie_status},
        )
    note = (reason or "").strip() or (
        "aprovada pelo coordenador" if approve else "reprovada pelo coordenador"
    )
    cand.selfie_status = _selfie.APPROVED if approve else _selfie.REJECTED
    cand.selfie_verified = approve
    cand.selfie_description = note
    cand.save(
        update_fields=[
            "selfie_status",
            "selfie_verified",
            "selfie_description",
            "updated_at",
        ]
    )
    if approve:
        _complete_candidate(cand)
    else:
        _notify_selfie_rejected(cand)
    return cand


def _notify_selfie_rejected(cand: Candidate) -> None:
    # wave-2: send_event lê teor/canais/is_tts do Template no DB. WhatsApp-only (legado).
    from notify.interface.events import send_event

    p = profiles.get(cand.user)
    try:
        send_event(
            "candidate.selfie_rejected",
            profile=p,
            channels_override=("whatsapp",),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_selfie_rejected_failed", error=str(exc))


def _notify_selfie_review(cand: Candidate) -> None:
    # wave-2: send_event lê teor/canais/is_tts do Template no DB. WhatsApp-only (coordenador).
    from notify.interface.events import send_event

    coord = cand.hub.coordinator
    if coord is None:
        return
    cp = profiles.get(coord)
    try:
        send_event(
            "candidate.selfie_in_review",
            profile=cp,
            channels_override=("whatsapp",),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_selfie_review_failed", error=str(exc))


# ── aprovação do candidato → PROMOTOR (coordenador, grupo leadership) ────────


def reset_doc_type(*, candidate_external_id: str, coordinator) -> dict:
    """Coordenador DESTRAVA o candidato que fixou o tipo de documento errado (escolheu RG, só tem
    CNH — ou vice-versa). Sem isso o `upload_document_photo` barra com `DOC_TYPE_LOCKED` e a única
    saída seria recomeçar TODO o cadastro (perdendo perfil/endereço/pix) ou um db-edit (Victor
    2026-06-17: hierarquia user→coord, sem dev em prod).

    Zera o `doc_type` e volta pra etapa `documents` — perfil/endereço/pix ficam INTACTOS; a próxima
    foto define o tipo certo. O sub-doc antigo (RG/CNH) é ignorado (a leitura chaveia por `doc_type`)."""
    cand = (
        Candidate.objects.filter(external_id=candidate_external_id)
        .select_related("hub", "user")
        .first()
    )
    if cand is None:
        raise CandidateError("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if cand.hub.coordinator_id != coordinator.id:
        raise Forbidden(
            "Você não coordena o polo deste candidato.", code="NOT_HUB_COORDINATOR"
        )
    if cand.status in (_S.COMPLETED, _S.APPROVED, _S.REJECTED):
        raise Conflict(
            "O candidato já saiu da coleta — não dá pra trocar o tipo de documento.",
            code="WRONG_STATUS",
            extra={"expected_status": cand.status},
        )
    if not cand.doc_type:
        raise CandidateError(
            "O candidato ainda não escolheu um tipo de documento.",
            code="DOC_TYPE_NOT_SET",
        )
    cand.doc_type = None
    cand.save(update_fields=["doc_type", "updated_at"])
    if cand.status != _S.DOCUMENTS:
        _set_status(cand, _S.DOCUMENTS)
    logger.info(
        "candidate.doc_type_reset",
        external_id=str(cand.external_id),
        by=str(coordinator.external_id),
    )
    _notify_doc_type_reset(cand)
    return me_dict(cand)


def _notify_doc_type_reset(cand: Candidate) -> None:
    """Avisa o candidato que pode reenviar o documento (o coordenador destravou o tipo).

    wave-2: send_event lê teor/canais/is_tts do Template no DB. Channels default (Template decide)."""
    from notify.interface.events import send_event

    p = profiles.get(cand.user)
    try:
        send_event(
            "candidate.doc_type_reset",
            profile=p,
            idempotency_key=f"cand_doctype_reset_{cand.external_id}_{cand.updated_at.timestamp()}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_doc_type_reset_failed", error=str(exc))


def approve_candidate(*, candidate_external_id: str, coordinator) -> Candidate:
    """Coordenador do polo APROVA o candidato manualmente → promove candidate→PROMOTOR (reusa
    `_promote_to_promoter`). Fallback do caminho de selfie em `review` (a selfie aprovada já
    auto-promove, F2). Rejeição é SOFT (Victor 2026-06-17)."""
    cand = (
        Candidate.objects.filter(external_id=candidate_external_id)
        .select_related("hub", "user")
        .first()
    )
    if cand is None:
        raise CandidateError("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if cand.hub.coordinator_id != coordinator.id:
        raise Forbidden(
            "Você não coordena o polo deste candidato.", code="NOT_HUB_COORDINATOR"
        )
    # rejeição é SOFT: um candidato REJEITADO continua aguardando e pode ser aprovado depois. Só barra
    # quem ainda está na coleta (não concluiu). `SELFIE` entra: a selfie em review deixa o candidato
    # nessa etapa e o coordenador aprova por aqui.
    if cand.status not in (_S.COMPLETED, _S.REJECTED, _S.SELFIE):
        raise Conflict(
            "O candidato ainda não concluiu a coleta.",
            code="WRONG_STATUS",
            extra={"expected_status": _S.COMPLETED},
        )
    # `_promote_to_promoter` exige status SELFIE p/ `_set_status(APPROVED)` fazer sentido; se veio de
    # COMPLETED/REJECTED, normaliza pra SELFIE (transição de coleta → promoção).
    if cand.status != _S.SELFIE:
        _set_status(cand, _S.SELFIE)
    _promote_to_promoter(cand)
    return cand


def reject_candidate(
    *, candidate_external_id: str, coordinator, reason: str | None = None
) -> Candidate:
    """Coordenador do polo REJEITA o candidato aguardando aprovação. Não promove; avisa o candidato."""
    cand = (
        Candidate.objects.filter(external_id=candidate_external_id)
        .select_related("hub", "user")
        .first()
    )
    if cand is None:
        raise CandidateError("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if cand.hub.coordinator_id != coordinator.id:
        raise Forbidden(
            "Você não coordena o polo deste candidato.", code="NOT_HUB_COORDINATOR"
        )
    # G10: mesmo conjunto de status que `approve_candidate` aceita. Antes exigia COMPLETED — estado
    # que o fluxo atual NUNCA atinge (a selfie aprovada auto-promove; a em review deixa em SELFIE),
    # então rejeitar dava 409 sempre. O candidato aguardando decisão está em SELFIE (selfie review).
    if cand.status not in (_S.COMPLETED, _S.REJECTED, _S.SELFIE):
        raise Conflict(
            "O candidato ainda não concluiu a coleta.",
            code="WRONG_STATUS",
            extra={"expected_status": _S.SELFIE},
        )
    _set_status(cand, _S.REJECTED)
    _notify_candidate_rejected(cand)
    logger.info("candidate.rejected", external_id=str(cand.external_id))
    return cand


def _notify_became_promoter(cand: Candidate, *, locked: bool) -> None:
    """Virou promotor: travado → `training.must_train` (texto); liberado → `training.approved` (TTS).

    Migração 2026-07-02: send_event lê teor/canais/is_tts do Template no DB; `{nome}` do profile."""
    from notify.interface.events import send_event

    event = "training.must_train" if locked else "training.approved"
    p = profiles.get(cand.user)
    try:
        send_event(
            event, profile=p, idempotency_key=f"candidate_promoted_{cand.external_id}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_promoted_failed", error=str(exc))


def _notify_candidate_rejected(cand: Candidate) -> None:
    # wave-2: send_event lê teor/canais/is_tts do Template no DB. WhatsApp-only (legado).
    from notify.interface.events import send_event

    p = profiles.get(cand.user)
    try:
        send_event(
            "candidate.rejected",
            profile=p,
            channels_override=("whatsapp",),
            idempotency_key=f"candidate_rejected_{cand.external_id}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("candidate.notify_rejected_failed", error=str(exc))


def _candidate_document_dict(cand) -> dict | None:
    """Bloco do DOCUMENTO (RG/CNH) do candidato pro coordenador decidir VENDO — fotos + status IA +
    motivo. Espelha `enrollment._rg_section_dict`. None se não há doc_type/sub-doc ainda."""
    if not cand.doc_type:
        return None
    sub = documents_iface.get_doc_sub(str(cand.user.external_id), cand.doc_type)
    if sub is None:
        return None
    result = (getattr(sub, "validation_result", None) or {}) if sub else {}
    has_photo = bool(sub.front_photo or sub.back_photo or sub.full_photo)
    return {
        "doc_type": cand.doc_type,
        "front_photo": sub.front_photo,
        "back_photo": sub.back_photo,
        "full_photo": sub.full_photo,
        # canônico (proposta #4): sem foto → sem análise em voo (não mostra "extraindo…")
        "analysis_status": sub.validation_status if has_photo else None,
        "analysis_reason": result.get("reason") if isinstance(result, dict) else None,
    }


def candidate_detail_for_coordinator(
    *, candidate_external_id: str, coordinator
) -> dict:
    """Detalhe do candidato aguardando aprovação — pro coordenador decidir VENDO (perfil + coleta).
    Gate: ser o coordenador do polo do candidato."""
    cand = (
        Candidate.objects.filter(external_id=candidate_external_id)
        .select_related("hub", "user")
        .first()
    )
    if cand is None:
        raise CandidateError("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if cand.hub.coordinator_id != coordinator.id:
        raise Forbidden(
            "Você não coordena o polo deste candidato.", code="NOT_HUB_COORDINATOR"
        )
    p = profiles.get(cand.user)
    return {
        "document": _candidate_document_dict(cand),
        "external_id": str(cand.external_id),
        "status": cand.status,
        "user": {
            "external_id": str(cand.user.external_id),
            "name": p.name if p else None,
            "cpf": p.cpf if p else None,
            "phone": p.phone if p else None,
            "email": p.email if p else None,
        },
        "doc_type": cand.doc_type,
        "mother_name": p.mother_name if p else None,
        "father_name": p.father_name if p else None,
        "marital_status": p.marital_status if p else None,
        "birthplace": p.birthplace if p else None,
        "nationality": p.nationality if p else None,
        "pix_key": p.pix_key if p else None,
        "pix_key_type": p.pix_key_type if p else None,
        "pix_validated": cand.pix_validated,
        "selfie_status": cand.selfie_status,
        "selfie_image": cand.selfie_image,
        "selfie_description": cand.selfie_description,
    }


def list_awaiting_approval_for_hub(*, hub) -> list[dict]:
    """Candidatos do polo aguardando a APROVAÇÃO do coordenador. Pro inbox/fila.

    Inclui COMPLETED **e REJECTED** (Victor 2026-06-17: rejeição é SOFT — "aguarda ser aprovado";
    o rejeitado não some, fica na fila e pode ser aprovado depois). `rejected: true` marca quem o
    coordenador já tinha rejeitado, pro front mostrar diferente."""
    out = []
    # G10: inclui SELFIE-em-review (o estado real de "aguardando decisão do coordenador"), além de
    # COMPLETED/REJECTED. Antes só COMPLETED/REJECTED, e como COMPLETED é inatingível, o inbox ficava
    # vazio — o coordenador nunca via os candidatos que precisavam da decisão dele.
    from django.db.models import Q

    from users.roles._selfie import SelfieStatus

    qs = (
        Candidate.objects.filter(hub=hub)
        .filter(
            Q(status__in=[_S.COMPLETED, _S.REJECTED])
            | Q(status=_S.SELFIE, selfie_status=SelfieStatus.REVIEW)
        )
        .select_related("user")
        .order_by("updated_at")
    )
    rows = list(qs)
    pmap = profiles.get_map([cand.user for cand in rows])
    for cand in rows:
        p = pmap.get(cand.user_id)
        out.append(
            {
                "external_id": str(cand.external_id),
                "name": p.name if p else None,
                "since": cand.updated_at.isoformat() if cand.updated_at else None,
                "rejected": cand.status == _S.REJECTED,
            }
        )
    return out


def list_selfie_reviews_for_hub(*, hub) -> list[dict]:
    """Candidatos do polo com a selfie parada em REVISÃO (decisão do coordenador — plan/14).

    Cada item aponta pro POST de decisão que já existe (`/candidates/{ext}/selfie/decide`).
    Antes, varre PENDING órfão (worker morto) → review (`_sweep_stale_reviews`)."""
    from users.roles._selfie import SelfieStatus

    _sweep_stale_reviews(hub)
    out = []
    qs = (
        Candidate.objects.filter(hub=hub, selfie_status=SelfieStatus.REVIEW)
        .select_related("user")
        .order_by("updated_at")
    )
    rows = list(qs)
    pmap = profiles.get_map([cand.user for cand in rows])
    for cand in rows:
        p = pmap.get(cand.user_id)
        out.append(
            {
                "external_id": str(cand.external_id),
                "name": p.name if p else None,
                "since": cand.updated_at.isoformat(),
            }
        )
    return out


def candidate_selfie_for_coordinator(
    *, candidate_external_id: str, coordinator
) -> dict:
    """Tela de DETALHE da selfie do candidato em REVISÃO pro coordenador decidir (plan/15 D2).

    Devolve a foto + `analysis_status`/`analysis_reason` (motivo da IA — útil pra aprovar/
    reprovar com contexto). O coordenador decide VENDO, não às cegas (antes decidia só com o
    nome na fila). Gate: o coord precisa ser o do polo do candidato (mesma régua do decide)."""
    from users.roles import _selfie

    cand = (
        Candidate.objects.filter(external_id=candidate_external_id)
        .select_related("hub", "user")
        .first()
    )
    if cand is None:
        raise CandidateError("Candidato não encontrado.", code="CANDIDATE_NOT_FOUND")
    if cand.hub.coordinator_id != coordinator.id:
        raise CandidateError(
            "Você não coordena o polo deste candidato.", code="NOT_HUB_COORDINATOR"
        )
    p = profiles.get(cand.user)
    return {
        "external_id": str(cand.external_id),
        "user": {
            "external_id": str(cand.user.external_id),
            "name": p.name if p else None,
            "cpf": p.cpf if p else None,
        },
        "selfie": _selfie_dict(cand),
        # "em revisão" = o que a IA mandou pra fila (TTL ou dúvida). Se NÃO está em REVIEW,
        # o detalhe existe mas o coordenador não tem o que decidir (front avisa).
        "in_review": cand.selfie_status == _selfie.REVIEW,
    }
