from __future__ import annotations

from users.blocks import service as blocks
from users.documents import service as documents_iface
from users.roles import _address_proof
from users.roles.candidate.models import Candidate
from users.roles.candidate.common import _S, _ACTIVE_COLLECTION_STATUSES, _require, logger
from users.roles.candidate.profile_address import _advance_address
from users.roles.candidate.promotion import _complete_candidate
from users.roles.candidate.serializers import me_dict


def get_address_proof(user_external_id: str) -> dict:
    """Retorna o bloco/status do comprovante de residência (para consulta isolada)."""
    return _address_proof.section_dict(user_external_id)


def upload_address_proof(*, user_external_id, upload) -> dict:
    """Comprovante de residência (foto/PDF) — OBRIGATÓRIO + validado por IA (F1). Salva a foto,
    marca `pending` e enfileira a validação (endereço + titular). Aceito já na etapa `address`."""
    cand = _require(
        user_external_id,
        _S.STARTED,
        _S.PROFILE,
        _S.ADDRESS,
        _S.DOCUMENTS,
        _S.PIX,
        _S.SELFIE,
        _S.COMPLETED,
        _S.APPROVED,
    )
    _address_proof.receive_upload(user_external_id, upload)
    blocks.resolve_for_source(user=cand.user, source_type="address_proof")
    from core.tasks import async_task

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
        _S.STARTED,
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
