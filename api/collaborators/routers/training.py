"""Router de Treinamento (Funil do Promotor)."""

from __future__ import annotations

from ninja import File, Form, Router
from ninja.files import UploadedFile

from api.auth import require_roles
from api.collaborators.schemas import (
    SubmissionIn,
    SubmissionOut,
    TrainingMaterialOut,
    TrainingMaterialProgressOut,
)
from users.roles.training import service as training_iface

router = Router(tags=["training"])


def _guard(request, *allowed: str) -> str:
    """Gate de role por rota + devolve o external_id do USER logado."""
    require_roles(request.auth, *allowed)
    return request.auth.external_id


@router.get("/training/materials", response=list[TrainingMaterialOut], summary="Matérias atribuídas de treino")
def training_materials(request):
    """Matérias atribuídas ao promotor no treino."""
    ext = _guard(request, "promoter")
    return training_iface.assigned_materials(ext)


@router.get("/training/progress", response=list[TrainingMaterialProgressOut], summary="Progresso do treino")
def training_progress(request):
    """Resumo de progresso e notas por matéria."""
    ext = _guard(request, "promoter")
    return training_iface.progress(ext)


@router.post("/training/submissions", response=SubmissionOut, summary="Submissão de resposta em texto")
def training_submit(request, payload: SubmissionIn):
    """Submissão de resposta em texto corrigida por IA."""
    ext = _guard(request, "promoter")
    sub = training_iface.submit(
        user_external_id=ext,
        material_external_id=payload.material_external_id,
        answer=payload.answer,
    )
    return training_iface.submission_to_dict(sub)


@router.post("/training/submissions/audio", response=SubmissionOut, summary="Submissão de resposta em áudio")
def training_submit_audio(
    request,
    material_external_id: str = Form(...),
    file: UploadedFile = File(...),
):
    """Submissão de resposta em áudio transcrita e corrigida por IA."""
    ext = _guard(request, "promoter")
    sub = training_iface.submit_audio(
        user_external_id=ext,
        material_external_id=material_external_id,
        data=file.read(),
        content_type=getattr(file, "content_type", ""),
    )
    return training_iface.submission_to_dict(sub)
