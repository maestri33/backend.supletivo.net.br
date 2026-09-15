"""Router de Matrículas e Taxas do Polo (Coordenador de Polo)."""

from __future__ import annotations

import structlog
from ninja import File, Router
from ninja.files import UploadedFile

from api.base import resolve_rg_slot
from api.leadership.base import get_coordinator, get_coordinator_hub
from api.leadership.schemas import (
    ConcludeIn,
    CorrectIdentityIn,
    EnrollmentActionOut,
    EnrollmentFeesOut,
    FeeIn,
    HubEnrollmentDetailOut,
    HubEnrollmentRowOut,
    ProxyCepIn,
    RgPhotoUploadOut,
)
from core.net import source_ip
from users.roles.enrollment import service as enrollment_iface

router = Router(tags=["enrollment"])
logger = structlog.get_logger()


def _proxy_user(request, external_id: str):
    coordinator = get_coordinator(request)
    user_ext = enrollment_iface.coordinated_user_ext(
        enrollment_external_id=external_id, coordinator=coordinator
    )
    return coordinator, user_ext


@router.get("/enrollments", response=list[HubEnrollmentRowOut], summary="Listagem de matrículas do polo")
def list_hub_enrollments(request, status: str | None = None):
    """Matrículas do polo: status real + situação de taxas."""
    coordinator = get_coordinator(request)
    hub = get_coordinator_hub(coordinator)
    return enrollment_iface.list_for_hub(hub=hub, status=status)


@router.get("/enrollments/{external_id}", response=HubEnrollmentDetailOut, summary="Detalhe de matrícula do polo")
def get_hub_enrollment(request, external_id: str):
    """Detalhe completo de uma matrícula do polo."""
    coordinator = get_coordinator(request)
    return enrollment_iface.detail_for_hub(
        enrollment_external_id=external_id, coordinator=coordinator
    )


@router.post("/enrollments/{external_id}/fee/pay", response=EnrollmentFeesOut, summary="1ª parcela da taxa (à vista)")
def pay_enrollment_fee(request, external_id: str, payload: FeeIn):
    """1ª parcela da taxa (À VISTA): valida QR e dispara PIX."""
    coordinator = get_coordinator(request)
    return enrollment_iface.pay_fee(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        qr_code=payload.qr_code,
        amount=payload.amount,
    )


@router.post("/enrollments/{external_id}/fee/schedule", response=EnrollmentFeesOut, summary="2ª parcela da taxa (agendada)")
def schedule_enrollment_fee(request, external_id: str, payload: FeeIn):
    """2ª parcela da taxa (AGENDADA): programa pagamento no vencimento."""
    coordinator = get_coordinator(request)
    return enrollment_iface.schedule_fee(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        qr_code=payload.qr_code,
        amount=payload.amount,
    )


@router.post("/enrollments/{external_id}/conclude", response=EnrollmentActionOut, summary="Conclusão da matrícula")
def conclude_enrollment(request, external_id: str, payload: ConcludeIn):
    """Conclui a matrícula e cadastra credenciais da instituição."""
    coordinator = get_coordinator(request)
    enr = enrollment_iface.conclude(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        platform_login=payload.platform_login,
        platform_password=payload.platform_password,
        platform_url=payload.platform_url,
        platform_notes=payload.platform_notes,
    )
    return {"external_id": str(enr.external_id), "status": enr.status}


@router.post("/enrollments/{external_id}/address", response=HubEnrollmentDetailOut, summary="Gravar endereço pelo coordenador")
def coord_proxy_address(request, external_id: str, payload: ProxyCepIn):
    """Coordenador grava o endereço no lugar do aluno."""
    coordinator, user_ext = _proxy_user(request, external_id)
    logger.info(
        "leadership.acted_for",
        action="address_cep",
        enrollment=external_id,
        by=str(coordinator.external_id),
    )
    return enrollment_iface.set_address_cep(user_external_id=user_ext, cep=payload.cep)


@router.post(
    "/enrollments/{external_id}/documents/rg/photo/{slot}",
    response=RgPhotoUploadOut,
    summary="Upload de RG pelo coordenador",
)
def coord_proxy_rg_photo(
    request, external_id: str, slot: str, file: UploadedFile = File(...)
):
    """Coordenador envia foto do RG no lugar do aluno."""
    coordinator, user_ext = _proxy_user(request, external_id)
    real_slot = resolve_rg_slot(slot)
    logger.info(
        "leadership.acted_for",
        action="rg_photo",
        enrollment=external_id,
        by=str(coordinator.external_id),
    )
    return enrollment_iface.upload_rg_photo(
        user_external_id=user_ext, slot=real_slot, upload=file
    )


@router.post(
    "/enrollments/{external_id}/selfie",
    response=HubEnrollmentDetailOut,
    summary="Upload de selfie pelo coordenador",
)
def coord_proxy_selfie(request, external_id: str, file: UploadedFile = File(...)):
    """Coordenador envia selfie de assinatura no lugar do aluno."""
    coordinator, user_ext = _proxy_user(request, external_id)
    logger.info(
        "leadership.acted_for",
        action="selfie",
        enrollment=external_id,
        by=str(coordinator.external_id),
    )
    enr = enrollment_iface.set_selfie(
        user_external_id=user_ext,
        image_bytes=file.read(),
        content_type=getattr(file, "content_type", "image/jpeg"),
        consent_ip=source_ip(request),
        consent_user_agent=request.headers.get("user-agent"),
    )
    return {**enrollment_iface.me_dict(enr), **enrollment_iface.selfie_ack(enr)}


@router.patch(
    "/enrollments/{external_id}/profile",
    response=HubEnrollmentDetailOut,
    summary="Correção manual de identidade pelo coordenador",
)
def coord_correct_identity(request, external_id: str, payload: CorrectIdentityIn):
    """Coordenador corrige dados do perfil/documento do aluno."""
    coordinator = get_coordinator(request)
    return enrollment_iface.coordinator_correct_identity(
        enrollment_external_id=external_id,
        coordinator=coordinator,
        **payload.dict(exclude_none=True),
    )
