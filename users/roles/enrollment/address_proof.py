from __future__ import annotations

from users.blocks import service as blocks
from users.documents import service as documents_iface
from users.exceptions import Conflict, Forbidden
from users.roles import _address_proof
from users.roles.enrollment.models import Enrollment
from users.roles.enrollment.common import EnrollmentError, _S, _require, logger
from users.roles.enrollment.serializers import me_dict
from users.roles.enrollment import service

def upload_address_proof(*, user_external_id: str, upload) -> dict:
    """Comprovante de residência (foto/PDF) — validado por IA em background. Aceito em qualquer
    etapa pré-completion (accept-first: o aluno pode avançar e reenviar o comprovante depois;
    rejeição vira ValidationBlock, não trava o wizard)."""
    enr = _require(
        user_external_id
    )  # sem gate de status: aceita enquanto não concluída
    documents_iface.upload_photo(user_external_id, "address_proof_photo", upload)
    # ponytail: re-upload resolve o bloco imediatamente; análise roda em background
    blocks.resolve_for_source(user=enr.user, source_type="address_proof")
    ap = documents_iface.get_address_proof(user_external_id)
    if ap is not None:
        ap.validation_status = "pending"
        # Novo upload = veredito e flags do ANTERIOR não valem mais (inclusive
        # `needs_new_proof`, que destrava a tela — Victor 2026-07-28).
        ap.validation_result = {}
        ap.save(update_fields=["validation_status", "validation_result"])
    from django_q.tasks import async_task

    async_task("users.roles.enrollment.tasks.validate_address_proof", enr.id)
    return me_dict(enr)


def submit_address_proof_kinship(*, user_external_id: str, relation: str) -> dict:
    """Titular do comprovante é outra pessoa (`needs_kinship`): explica o parentesco → libera.
    Aceito em qualquer etapa pré-completion (accept-first)."""
    from users.roles import _address_proof

    enr = _require(user_external_id)  # sem gate de status
    _address_proof.submit_kinship(user_external_id, relation)
    _advance_address(enr, user_external_id)
    return me_dict(enr)


def decide_address_proof_kinship(
    *, enrollment_external_id: str, coordinator, approve: bool, reason: str | None
) -> dict:
    """Coordenador decide a JUSTIFICATIVA de titularidade do comprovante (Victor 2026-07-28).

    Rejeitou → `needs_new_proof`: a tela do aluno trava no comprovante pedindo outro documento
    (de preferência no nome dele) até um novo upload. O motivo fica interno."""
    from users.roles import _address_proof

    enr = _enrollment_for_coordinator(enrollment_external_id, coordinator)
    status = _address_proof.decide_kinship(
        str(enr.user.external_id), approve=approve, reason=reason
    )
    if approve:
        _advance_address(enr, str(enr.user.external_id))
        _notify_resolution(enr, "enrollment.address_proof.approved")
    else:
        _notify_resolution(enr, "enrollment.address_proof.new_proof_needed")
    return {"external_id": enrollment_external_id, "status": status}


def run_address_proof_validation(enrollment_id: int) -> None:
    """Task async: valida o comprovante (visão → endereço → titular) e, se aprovar, avança o wizard."""
    from users.roles import _address_proof

    enr = Enrollment.objects.filter(id=enrollment_id).select_related("user").first()
    if enr is None:
        return
    user_ext = str(enr.user.external_id)
    _address_proof.validate_and_store(user_ext, caller="enrollment.address_proof")
    enr.refresh_from_db(fields=["status"])
    _advance_address(enr, user_ext)


# ── seção DOCUMENTO (plan/13): GET rico · PATCH completa/corrige ─────────────
