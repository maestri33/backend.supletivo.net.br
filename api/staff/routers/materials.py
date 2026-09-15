"""Router de Autoria de LMS e Treinamento (Staff)."""

from __future__ import annotations

from ninja import File, Router, Status
from ninja.files import UploadedFile

from api.auth import require_superuser
from api.schemas.training import MaterialIn, MaterialUpdateIn
from api.staff.schemas import (
    DeleteMaterialOut,
    PublishMaterialOut,
    StaffMaterialOut,
)
from users.roles.training import service as training_iface

router = Router(tags=["staff"])


@router.post("/training/materials", response={201: StaffMaterialOut}, summary="Criar matéria de treino")
def create_material(request, payload: MaterialIn):
    """Cria uma matéria do treino (conteúdo + questão + gabarito)."""
    require_superuser(request.auth)
    m = training_iface.create_material(**payload.dict())
    return Status(201, training_iface.material_to_dict(m, include_answer=True))


@router.put("/training/materials/{external_id}", response=StaffMaterialOut, summary="Atualizar matéria de treino")
def update_material(request, external_id: str, payload: MaterialUpdateIn):
    """Edita uma matéria de treino."""
    require_superuser(request.auth)
    m = training_iface.update_material(external_id, **payload.dict())
    return training_iface.material_to_dict(m, include_answer=True)


@router.get("/training/materials", response=list[StaffMaterialOut], summary="Listar matérias (com gabarito)")
def list_materials(request):
    """Lista todas as matérias com gabarito para visão de autoria."""
    require_superuser(request.auth)
    return [
        training_iface.material_to_dict(m, include_answer=True)
        for m in training_iface.list_materials(active_only=False)
    ]


@router.post("/training/materials/{external_id}/publish", response=PublishMaterialOut, summary="Publicar matéria transitória")
def publish_material(request, external_id: str):
    """Publica matéria transitória para promotores existentes."""
    require_superuser(request.auth)
    return training_iface.publish_transitory(external_id)


@router.delete("/training/materials/{external_id}", response=DeleteMaterialOut, summary="Descartar matéria efêmera")
def delete_material(request, external_id: str):
    """Descarta matéria efêmera."""
    require_superuser(request.auth)
    training_iface.delete_material(external_id)
    return {"deleted": external_id}


@router.post("/training/materials/{external_id}/video", response=StaffMaterialOut, summary="Upload de vídeo de matéria")
def upload_material_video(request, external_id: str, file: UploadedFile = File(...)):
    """Upload de vídeo da matéria de treino."""
    require_superuser(request.auth)
    m = training_iface.set_material_video(
        external_id,
        data=file.read(),
        content_type=getattr(file, "content_type", "video/mp4"),
    )
    return training_iface.material_to_dict(m, include_answer=True)
