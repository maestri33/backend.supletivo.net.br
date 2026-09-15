"""Router do Aluno e Veterano (Funil do Aluno)."""

from __future__ import annotations

import sys
from ninja import File, Router
from ninja.files import UploadedFile

from api.auth import require_roles
from api.clients.schemas import (
    BloodTypeIn,
    ExamScheduleIn,
    PendencyOut,
    StudentDocumentUploadAck,
    StudentMeOut,
    VeteranMeOut,
)
from users.documents import service as documents_iface
from users.exceptions import NotFound
from users.roles.enrollment import service as enrollment_iface
from users.roles.student import service as student_iface

router = Router(tags=["student"])


def _student_guard(request) -> str:
    """Gate role student + devolve o external_id do aluno logado."""
    require_roles(request.auth, "student")
    return request.auth.external_id


def _student_dict(ext: str):
    s = student_iface.get_for_user_external_id(ext)
    if s is None:
        raise NotFound("Aluno não encontrado.", code="STUDENT_NOT_FOUND")
    return student_iface.to_dict(s)


def _veteran_guard(request) -> str:
    """Gate role veteran + devolve o external_id do veterano logado."""
    require_roles(request.auth, "veteran")
    return request.auth.external_id


@router.get("/student/me", response=StudentMeOut, summary="Dados e progresso do aluno")
def student_me(request):
    """Consulta do aluno ativo."""
    return _student_dict(_student_guard(request))


@router.get("/veteran/me", response=VeteranMeOut, tags=["veteran"], summary="Visão consolidada do veterano")
def veteran_me(request):
    """Visão consolidada do veterano: dados pessoais, matrícula e diploma."""
    clients_pkg = sys.modules.get("api.clients")
    guard_fn = getattr(clients_pkg, "_veteran_guard", _veteran_guard)
    student_svc = getattr(clients_pkg, "student_iface", student_iface)
    enrollment_svc = getattr(clients_pkg, "enrollment_iface", enrollment_iface)

    external_id = guard_fn(request)
    data = student_svc.veteran_detail(user_external_id=external_id)

    enr = enrollment_svc.get_for_user_external_id(external_id)
    me = enrollment_svc.me_dict(enr) if enr is not None else None
    data["enrollment"] = (
        None
        if me is None
        else {k: me.get(k) for k in ("profile", "address", "education", "rg", "selfie")}
    )
    return data


@router.post("/student/blood-type", response=StudentMeOut, summary="Definição de tipo sanguíneo")
def student_blood_type(request, payload: BloodTypeIn):
    """Registra o tipo sanguíneo do aluno."""
    ext = _student_guard(request)
    student_iface.set_blood_type(user_external_id=ext, blood_type=payload.blood_type)
    return _student_dict(ext)


@router.post(
    "/student/documents/{doc_type}",
    response=StudentDocumentUploadAck,
    summary="Upload de documento do aluno",
)
def student_document(request, doc_type: str, file: UploadedFile = File(...)):
    """Upload de documento complementar do aluno."""
    ext = _student_guard(request)
    image_bytes, content_type = documents_iface.read_image_upload(file)
    doc, ack = student_iface.upload_document(
        user_external_id=ext,
        doc_type=doc_type,
        image_bytes=image_bytes,
        content_type=content_type,
    )
    return {
        "doc_type": doc_type,
        "stored": bool(doc.photo),
        "analysis_status": ack["analysis_status"],
        "poll_after_ms": ack["poll_after_ms"],
        "expires_at": ack["expires_at"],
    }


@router.post("/student/exam/schedule", response=StudentMeOut, summary="Agendamento de prova")
def student_exam_schedule(request, payload: ExamScheduleIn):
    """Agendamento de prova presencial."""
    ext = _student_guard(request)
    student_iface.schedule_exam(
        user_external_id=ext,
        subject=payload.subject,
        scheduled_at=payload.scheduled_at,
    )
    return _student_dict(ext)


@router.get("/student/pendencies", response=list[PendencyOut], summary="Listagem de pendências")
def student_pendencies(request):
    """Lista pendências financeiras e documentais abertas."""
    ext = _student_guard(request)
    pends = student_iface.list_pendencies(ext, open_only=True)
    return [
        {
            "external_id": str(p.external_id),
            "kind": p.kind,
            "description": p.description,
            "amount_cents": p.amount_cents,
        }
        for p in pends
    ]
