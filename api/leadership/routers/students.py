"""Router de Gestão de Alunos e Diplomas (Coordenador de Polo)."""

from __future__ import annotations

from ninja import File, Router
from ninja.files import UploadedFile

from api.leadership.base import get_coordinator, get_coordinator_hub
from api.leadership.schemas import (
    DiplomaIssueOut,
    DocDecideIn,
    DocDecisionOut,
    EnrollmentActionOut,
    ExamGradeIn,
    ExamOut,
    HubStudentDetailOut,
    PaginatedStudentsOut,
    PendencyIn,
    StudentPendencyOut,
)
from users.roles.student import service as student_iface

router = Router(tags=["student"])


def _student_action(external_id: str, coordinator, fn, **kw):
    return fn(student_external_id=external_id, coordinator=coordinator, **kw)


@router.get("/students", response=PaginatedStudentsOut, summary="Listagem paginada de alunos do polo")
def list_hub_students(
    request, status: str | None = None, limit: int = 200, offset: int = 0
):
    """Alunos do polo com paginação e filtro por status."""
    coordinator = get_coordinator(request)
    hub = get_coordinator_hub(coordinator)
    items, total = student_iface.list_for_hub(
        hub=hub, status=status, limit=limit, offset=offset
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/students/{external_id}", response=HubStudentDetailOut, summary="Detalhe completo do aluno")
def get_student_for_coordinator(request, external_id: str):
    """Detalhe rico do aluno para o coordenador."""
    coordinator = get_coordinator(request)
    return student_iface.detail_for_coordinator(
        student_external_id=external_id, coordinator=coordinator
    )


@router.post("/students/{external_id}/exam/grade", response=ExamOut, summary="Correção de prova do aluno")
def grade_exam(request, external_id: str, payload: ExamGradeIn):
    """Lança nota da prova do aluno."""
    coordinator = get_coordinator(request)
    exam = _student_action(
        external_id,
        coordinator,
        student_iface.grade_exam,
        passed=payload.passed,
        notes=payload.notes,
    )
    return {"external_id": str(exam.external_id), "result": exam.result}


@router.post(
    "/students/{external_id}/documents/{document_external_id}/decide",
    response=DocDecisionOut,
    summary="Decisão de documento do aluno",
)
def decide_document(
    request, external_id: str, document_external_id: str, payload: DocDecideIn
):
    """Decide validação de documento em revisão do aluno."""
    coordinator = get_coordinator(request)
    doc = _student_action(
        external_id,
        coordinator,
        student_iface.decide_document,
        document_external_id=document_external_id,
        approve=payload.approve,
        reason=payload.reason,
    )
    return {
        "external_id": str(doc.external_id),
        "validation_status": doc.validation_status,
    }


@router.post(
    "/students/{external_id}/pendencies",
    response=StudentPendencyOut,
    summary="Abrir pendência para aluno",
)
def open_pendency(request, external_id: str, payload: PendencyIn):
    """Lança pendência para o aluno."""
    coordinator = get_coordinator(request)
    pend = _student_action(
        external_id,
        coordinator,
        student_iface.open_pendency,
        kind=payload.kind,
        description=payload.description,
        amount_cents=payload.amount_cents,
    )
    return {
        "external_id": str(pend.external_id),
        "kind": pend.kind,
        "description": pend.description,
        "amount_cents": pend.amount_cents,
        "resolved": pend.resolved_at is not None,
    }


@router.post(
    "/pendencies/{external_id}/resolve",
    response=StudentPendencyOut,
    summary="Resolver pendência do aluno",
)
def resolve_pendency(request, external_id: str):
    """Marca pendência como resolvida."""
    coordinator = get_coordinator(request)
    pend = student_iface.resolve_pendency(
        pendency_external_id=external_id, coordinator=coordinator
    )
    return {
        "external_id": str(pend.external_id),
        "kind": pend.kind,
        "description": pend.description,
        "amount_cents": pend.amount_cents,
        "resolved": pend.resolved_at is not None,
    }


@router.post(
    "/students/{external_id}/documentation/clear",
    response=EnrollmentActionOut,
    summary="Liberar emissão de diploma",
)
def clear_documentation(request, external_id: str):
    """Confirma documentação e libera emissão do diploma."""
    coordinator = get_coordinator(request)
    s = _student_action(external_id, coordinator, student_iface.clear_documentation)
    return {"external_id": str(s.external_id), "status": s.status}


@router.post(
    "/students/{external_id}/diploma/issue",
    response=DiplomaIssueOut,
    summary="Emissão de diploma",
)
def issue_diploma(
    request,
    external_id: str,
    diploma: UploadedFile = File(...),
    transcript: UploadedFile | None = File(None),
):
    """Emite o diploma e histórico do aluno."""
    coordinator = get_coordinator(request)
    issued = _student_action(
        external_id,
        coordinator,
        student_iface.issue_diploma,
        diploma_bytes=diploma.read(),
        diploma_content_type=getattr(diploma, "content_type", "application/pdf"),
        transcript_bytes=transcript.read() if transcript else None,
        transcript_content_type=(
            getattr(transcript, "content_type", None) if transcript else None
        ),
    )
    return {
        "external_id": str(issued.external_id),
        "issued_at": issued.issued_at.isoformat(),
    }


@router.post(
    "/students/{external_id}/diploma/pickup",
    response=EnrollmentActionOut,
    summary="Registro de retirada do diploma",
)
def register_diploma_pickup(request, external_id: str, file: UploadedFile = File(...)):
    """Registra entrega do diploma com foto e promove aluno a veterano."""
    coordinator = get_coordinator(request)
    s = _student_action(
        external_id,
        coordinator,
        student_iface.register_pickup,
        image_bytes=file.read(),
        content_type=getattr(file, "content_type", "image/jpeg"),
    )
    return {"external_id": str(s.external_id), "status": s.status}


@router.post(
    "/students/{external_id}/manual-selfie",
    response=EnrollmentActionOut,
    summary="Foto presencial para selfie com pendência",
)
def register_manual_selfie(request, external_id: str, file: UploadedFile = File(...)):
    """Foto tirada pelo coordenador para destravar aluno presencialmente."""
    coordinator = get_coordinator(request)
    s = _student_action(
        external_id,
        coordinator,
        student_iface.clear_manual_selfie,
        image_bytes=file.read(),
        content_type=getattr(file, "content_type", "image/jpeg"),
    )
    return {"external_id": str(s.external_id), "status": s.status}
