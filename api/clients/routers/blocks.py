"""Router de bloqueios ativos e polling de validações (Funil do Aluno)."""

from __future__ import annotations

from ninja import Router

from api.clients.schemas import BlockOut
from users.auth.models import User
from users.blocks import service as blocks_svc
from users.exceptions import NotFound

router = Router(tags=["blocks"])


@router.get("/me/blocks", response=list[BlockOut], summary="Listagem de bloqueios ativos")
def my_blocks(request):
    """Bloqueios ativos: validações que rejeitaram e o aluno precisa resolver."""
    user = User.objects.filter(external_id=request.auth.external_id).first()
    if user is None:
        return []
    return [blocks_svc.to_dict(b) for b in blocks_svc.get_active_blocks(user)]


@router.get("/me/blocks/{block_id}", response=BlockOut, summary="Consulta de bloco individual")
def my_block(request, block_id: int):
    """Busca 1 bloco por ID para deep-link."""
    user = User.objects.filter(external_id=request.auth.external_id).first()
    block = blocks_svc.get_by_id(user=user, block_id=block_id) if user else None
    if block is None:
        raise NotFound("Bloco não encontrado.", code="BLOCK_NOT_FOUND")
    return blocks_svc.to_dict(block)


@router.post("/me/blocks/{block_id}/resolve", response=BlockOut, summary="Resolução de bloco")
def resolve_block(request, block_id: int):
    """Resolve manualmente um bloco bloqueante."""
    user = User.objects.filter(external_id=request.auth.external_id).first()
    block = blocks_svc.resolve_by_id(user=user, block_id=block_id) if user else None
    if block is None:
        raise NotFound("Bloco não encontrado.", code="BLOCK_NOT_FOUND")
    return blocks_svc.to_dict(block)
