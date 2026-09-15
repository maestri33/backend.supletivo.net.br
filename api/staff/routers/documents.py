"""Router de Auditoria de Documentos, Biometria e Dossiê Staff."""

from __future__ import annotations

from ninja import Query, Router
from ninja.errors import HttpError

from api.auth import require_superuser
from api.staff.schemas import (
    DocumentDecideIn,
    DocumentDecideOut,
    DocumentReprocessIn,
    DocumentReviewFilterSchema,
    DocumentReviewOut,
    UserDossierOut,
)
from users.auth.models import User
from users.documents.models import AddressProof, CNH, RG
from users.exceptions import NotFound, ValidationError
from users.profiles import interface as profiles
from users.roles.candidate.models import Candidate
from users.roles.enrollment.models import Enrollment
from users.roles.student.models import StudentDocument

router = Router(tags=["staff"])


@router.get("/documents/reviews", response=list[DocumentReviewOut], summary="Fila global unificada de documentos em revisão")
def list_global_document_reviews(
    request,
    filters: DocumentReviewFilterSchema = Query(default=None),
):
    """Retorna todas as análises pendentes de matrícula, candidato e aluno de todos os polos."""
    require_superuser(request.auth)
    f = filters if isinstance(filters, DocumentReviewFilterSchema) else DocumentReviewFilterSchema()
    hub = f.hub
    doc_type = f.doc_type

    reviews = []

    # 1. Matrículas com RG ou Selfie em revisão
    enrollment_qs = Enrollment.objects.select_related("user", "hub", "promoter").filter(
        status__in=[
            Enrollment.Status.RG,
            Enrollment.Status.SELFIE,
            Enrollment.Status.ADDRESS,
            Enrollment.Status.AWAITING_RELEASE,
        ]
    ).order_by("-updated_at")

    if hub:
        enrollment_qs = enrollment_qs.filter(hub__external_id=hub)

    enrollments = list(enrollment_qs[:100])
    enr_users = [enr.user for enr in enrollments if enr.user]
    enr_profiles = profiles.get_map(enr_users)
    enr_rgs = {
        rg.document.user_id: rg
        for rg in RG.objects.filter(document__user__in=enr_users).select_related("document")
    }
    enr_cnhs = {
        cnh.document.user_id: cnh
        for cnh in CNH.objects.filter(document__user__in=enr_users).select_related("document")
    }

    for enr in enrollments:
        p = enr_profiles.get(enr.user_id)
        rg = enr_rgs.get(enr.user_id)
        cnh = enr_cnhs.get(enr.user_id)
        doc = rg or cnh

        doc_status = getattr(doc, "validation_status", None)
        selfie_status = getattr(enr, "selfie_status", None)

        if doc_status == "review" or enr.status == Enrollment.Status.RG:
            res_dict = getattr(doc, "validation_result", None) or {}
            reason_text = res_dict.get("reason") or "Aguardando conferência de documento"
            reviews.append({
                "external_id": str(enr.external_id),
                "user_external_id": str(enr.user.external_id),
                "name": p.name if p else "Aluno",
                "phone": p.phone if p else None,
                "cpf": p.cpf if p else None,
                "hub_name": enr.hub.brand if enr.hub else None,
                "type": "enrollment",
                "kind": "rg",
                "reason": reason_text,
                "created_at": enr.created_at.isoformat(),
            })

        if selfie_status == "review" or getattr(p, "selfie_needs_meeting", False):
            reviews.append({
                "external_id": str(enr.external_id),
                "user_external_id": str(enr.user.external_id),
                "name": p.name if p else "Aluno",
                "phone": p.phone if p else None,
                "cpf": p.cpf if p else None,
                "hub_name": enr.hub.brand if enr.hub else None,
                "type": "enrollment",
                "kind": "selfie",
                "reason": getattr(enr, "selfie_reason", None) or "Score biométrico para revisão",
                "created_at": enr.created_at.isoformat(),
            })

    # 2. Candidatos a promotor
    candidate_qs = Candidate.objects.select_related("user", "hub").filter(
        status__in=[Candidate.Status.STARTED, Candidate.Status.APPROVED]
    ).order_by("-updated_at")

    if hub:
        candidate_qs = candidate_qs.filter(hub__external_id=hub)

    candidates = list(candidate_qs[:100])
    cand_users = [cand.user for cand in candidates if cand.user]
    cand_profiles = profiles.get_map(cand_users)

    for cand in candidates:
        p = cand_profiles.get(cand.user_id)
        if getattr(cand, "selfie_status", None) == "review":
            reviews.append({
                "external_id": str(cand.external_id),
                "user_external_id": str(cand.user.external_id),
                "name": p.name if p else "Candidato",
                "phone": p.phone if p else None,
                "cpf": p.cpf if p else None,
                "hub_name": cand.hub.brand if cand.hub else None,
                "type": "candidate",
                "kind": "selfie",
                "reason": getattr(cand, "selfie_reason", None) or "Revisão biométrica de promotor",
                "created_at": cand.created_at.isoformat(),
            })

    # 3. Documentos de alunos
    student_doc_qs = StudentDocument.objects.select_related("student", "student__user", "student__hub").filter(
        validation_status="review"
    ).order_by("-updated_at")

    if hub:
        student_doc_qs = student_doc_qs.filter(student__hub__external_id=hub)

    student_docs = list(student_doc_qs[:100])
    sdoc_users = [sdoc.student.user for sdoc in student_docs if sdoc.student and sdoc.student.user]
    sdoc_profiles = profiles.get_map(sdoc_users)

    for sdoc in student_docs:
        p = sdoc_profiles.get(sdoc.student.user_id) if sdoc.student and sdoc.student.user else None
        reviews.append({
            "external_id": str(sdoc.external_id),
            "user_external_id": str(sdoc.student.user.external_id) if sdoc.student and sdoc.student.user else None,
            "name": p.name if p else "Aluno",
            "phone": p.phone if p else None,
            "cpf": p.cpf if p else None,
            "hub_name": sdoc.student.hub.brand if sdoc.student and sdoc.student.hub else None,
            "type": "student",
            "kind": sdoc.doc_type,
            "reason": sdoc.validation_reason or "Documento complementar em revisão",
            "created_at": sdoc.created_at.isoformat(),
        })

    if doc_type:
        reviews = [r for r in reviews if r["kind"] == doc_type or r["type"] == doc_type]

    return reviews


@router.get("/documents/{user_external_id}/dossier", response=UserDossierOut, summary="Dossiê visual e biométrico completo")
def get_user_dossier(request, user_external_id: str):
    """Retorna todas as mídias, scores biométricos, OCR e dados cadastrais para conferência lado a lado."""
    require_superuser(request.auth)

    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")

    p = profiles.get(user)
    rg = RG.objects.filter(document__user=user).first()
    cnh = CNH.objects.filter(document__user=user).first()
    proof = AddressProof.objects.filter(document__user=user).first()
    enr = Enrollment.objects.filter(user=user).first()
    cand = Candidate.objects.filter(user=user).first()

    # Coleta fotos
    doc = rg or cnh
    front_photo = getattr(doc, "front_photo", None)
    back_photo = getattr(doc, "back_photo", None)
    full_photo = getattr(doc, "full_photo", None)
    selfie_photo = getattr(enr, "selfie_photo", None) or getattr(cand, "selfie_photo", None)
    face_crop = getattr(enr, "selfie_face_crop", None)
    address_photo = getattr(proof, "photo", None)

    # Document data e validação
    res_dict = getattr(doc, "validation_result", None) or {}
    validation_reason = res_dict.get("reason") or getattr(doc, "validation_reason", None)
    extracted_data = res_dict.get("extracted_data") or {}

    # Face verification history
    from integrations.tools.biometric.models import FaceVerification
    verifications = list(
        FaceVerification.objects.filter(user=user).order_by("-created_at").values(
            "score", "status", "approved", "created_at"
        )[:5]
    )

    return {
        "user_external_id": str(user.external_id),
        "profile": {
            "name": p.name if p else None,
            "cpf": p.cpf if p else None,
            "phone": p.phone if p else None,
            "email": p.email if p else None,
            "birth_date": p.birth_date.isoformat() if p and p.birth_date else None,
            "mother_name": p.mother_name if p else None,
            "father_name": p.father_name if p else None,
            "pix_key": p.pix_key if p else None,
            "selfie_needs_meeting": getattr(p, "selfie_needs_meeting", False),
        },
        "media": {
            "front_photo": f"/media/{front_photo}" if front_photo else None,
            "back_photo": f"/media/{back_photo}" if back_photo else None,
            "full_photo": f"/media/{full_photo}" if full_photo else None,
            "selfie_photo": f"/media/{selfie_photo}" if selfie_photo else None,
            "face_crop": f"/media/{face_crop}" if face_crop else None,
            "address_photo": f"/media/{address_photo}" if address_photo else None,
        },
        "document_data": {
            "doc_type": "rg" if rg else ("cnh" if cnh else None),
            "number": getattr(doc, "number", None),
            "state": getattr(doc, "state", None),
            "validation_status": getattr(doc, "validation_status", None),
            "validation_reason": getattr(doc, "validation_reason", None),
            "extracted_data": getattr(doc, "extracted_data", None) or {},
        },
        "biometrics": {
            "selfie_status": getattr(enr, "selfie_status", None) or getattr(cand, "selfie_status", None),
            "selfie_reason": getattr(enr, "selfie_reason", None) or getattr(cand, "selfie_reason", None),
            "verifications": verifications,
        },
        "address": {
            "street": p.address.street if p and p.address else None,
            "number": p.address.number if p and p.address else None,
            "complement": p.address.complement if p and p.address else None,
            "neighborhood": p.address.neighborhood if p and p.address else None,
            "city": p.address.city if p and p.address else None,
            "state": p.address.state if p and p.address else None,
            "zipcode": p.address.zipcode if p and p.address else None,
        },
    }


@router.post("/documents/{user_external_id}/decide", response=DocumentDecideOut, summary="Decisão administrativa do operador")
def decide_document_staff(request, user_external_id: str, payload: DocumentDecideIn):
    """Aprova ou rejeita manualmente documento ou selfie com justificativa."""
    require_superuser(request.auth)

    user = User.objects.filter(external_id=user_external_id).first()
    if user is None:
        raise NotFound("Usuário não encontrado.", code="USER_NOT_FOUND")

    staff_user = request.auth
    approve = payload.approve
    reason = payload.reason or ("Aprovado pelo Staff Admin" if approve else "Reprovado pelo Staff Admin")

    if payload.kind == "rg":
        rg = RG.objects.filter(user=user).first()
        cnh = CNH.objects.filter(user=user).first()
        doc = rg or cnh
        if doc:
            doc.validation_status = "approved" if approve else "rejected"
            doc.validation_reason = reason
            doc.save(update_fields=["validation_status", "validation_reason", "updated_at"])

    elif payload.kind == "selfie":
        enr = Enrollment.objects.filter(user=user).first()
        if enr:
            enr.selfie_status = "approved" if approve else "rejected"
            enr.selfie_reason = reason
            enr.save(update_fields=["selfie_status", "selfie_reason", "updated_at"])
        cand = Candidate.objects.filter(user=user).first()
        if cand:
            cand.selfie_status = "approved" if approve else "rejected"
            cand.selfie_reason = reason
            cand.save(update_fields=["selfie_status", "selfie_reason", "updated_at"])

        p = profiles.get(user)
        if p and approve:
            p.selfie_needs_meeting = False
            p.save(update_fields=["selfie_needs_meeting", "updated_at"])

    elif payload.kind == "student_doc" and payload.doc_id:
        sdoc = StudentDocument.objects.filter(external_id=payload.doc_id).first()
        if sdoc:
            sdoc.validation_status = "approved" if approve else "rejected"
            sdoc.validation_reason = reason
            sdoc.save(update_fields=["validation_status", "validation_reason", "updated_at"])

    return {"detail": "Decisão registrada com sucesso.", "status": "approved" if approve else "rejected"}
