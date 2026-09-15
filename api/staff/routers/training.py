from __future__ import annotations

from decimal import Decimal
from ninja import Query, Router
from ninja.errors import HttpError

from api.auth import require_superuser
from api.staff.schemas import (
    TrainingOverrideOut,
    TrainingSubmissionFilterSchema,
    TrainingSubmissionOut,
    TrainingUnlockOut,
)
from users.auth.models import User
from users.exceptions import NotFound, ValidationError
from users.profiles import interface as profiles
from users.roles import interface as roles
from users.roles.training.models import MaterialAssignment, Submission

router = Router(tags=["staff"])


@router.get("/training/submissions", response=list[TrainingSubmissionOut], summary="Listagem de submissões de treino com áudios e notas")
def list_training_submissions(
    request,
    filters: TrainingSubmissionFilterSchema = Query(default=None),
):
    """Retorna submissões com URLs de áudio gravado, transcrição e justificativa da IA."""
    require_superuser(request.auth)
    f = filters if isinstance(filters, TrainingSubmissionFilterSchema) else TrainingSubmissionFilterSchema()

    qs = Submission.objects.select_related("user", "material").order_by("-created_at")
    if f.status:
        qs = qs.filter(status=f.status)
    if f.material_id:
        qs = qs.filter(material__external_id=f.material_id)

    results = []
    for sub in qs[:100]:
        p = profiles.get(sub.user)
        results.append({
            "external_id": str(sub.external_id),
            "user_external_id": str(sub.user.external_id),
            "user_name": p.name if p else "Promotor",
            "user_phone": p.phone if p else None,
            "material_title": sub.material.title,
            "material_question": sub.material.question,
            "material_expected": sub.material.expected_answer,
            "answer": sub.answer,
            "audio_url": f"/media/{sub.audio}" if sub.audio else None,
            "grade": str(sub.grade) if sub.grade is not None else None,
            "justification": sub.justification,
            "status": sub.status,
            "created_at": sub.created_at.isoformat(),
        })

    return results


@router.post("/training/submissions/{external_id}/override", response=TrainingOverrideOut, summary="Aprovar/reprovar submissão manualmente")
def override_submission_grade(request, external_id: str, grade: str, approve: bool, justification: str | None = None):
    """Staff substitui a nota/decisão da IA."""
    require_superuser(request.auth)

    sub = Submission.objects.select_related("user", "material").filter(external_id=external_id).first()
    if sub is None:
        raise NotFound("Submissão não encontrada.", code="SUBMISSION_NOT_FOUND")

    sub.grade = Decimal(grade)
    sub.status = Submission.Status.APPROVED if approve else Submission.Status.REJECTED
    sub.justification = justification or ("Aprovado manualmente pelo Staff" if approve else "Reprovado manualmente pelo Staff")
    sub.save(update_fields=["grade", "status", "justification", "updated_at"])

    if approve:
        assignment = MaterialAssignment.objects.filter(user=sub.user, material=sub.material).first()
        if assignment:
            assignment.status = MaterialAssignment.Status.APPROVED
            assignment.decided_by = request.auth
            assignment.save(update_fields=["status", "decided_by", "updated_at"])

    return {"detail": "Submissão atualizada com sucesso.", "status": sub.status}


@router.post("/training/promoters/{promoter_external_id}/unlock", response=TrainingUnlockOut, summary="Desbloquear promotor travado no treino")
def unlock_promoter_training(request, promoter_external_id: str):
    """Aprova todas as matérias obrigatórias pendentes do promotor e remove o overlay training."""
    require_superuser(request.auth)

    user = User.objects.filter(external_id=promoter_external_id).first()
    if user is None:
        raise NotFound("Promotor não encontrado.", code="PROMOTER_NOT_FOUND")

    # Marca todas as assignments pendentes como aprovadas
    MaterialAssignment.objects.filter(user=user, status=MaterialAssignment.Status.PENDING).update(
        status=MaterialAssignment.Status.APPROVED, decided_by=request.auth
    )

    # Revoga role training se estiver ativa
    if "training" in roles.active_roles(user):
        roles.revoke(user, "training")

    return {"detail": "Promotor desbloqueado com sucesso. Todas as matérias foram aprovadas."}
