"""Lógica do `ValidationBlock` — criar, resolver, consultar.

CONVENTION §3: interface in-process, chamada pelos services de enrollment/student nos
pontos de rejeição/resolução. O endpoint de polling (`api/clients.py`) também consome daqui.
"""

from __future__ import annotations

import structlog
from django.utils import timezone

from users.blocks.models import ValidationBlock

logger = structlog.get_logger()


def create_block(
    *,
    user,
    source_type: str,
    source_external_id: str | None = None,
    title: str,
    description: str,
    action_label: str,
    action_route: str,
) -> ValidationBlock | None:
    """Cria um bloco ativo pra (user, source_type). Idempotente: se já existir bloco ativo
    da mesma fonte, atualiza título/descrição (a rejeição pode ter motivo diferente)."""
    block, created = ValidationBlock.objects.update_or_create(
        user=user,
        source_type=source_type,
        resolved_at__isnull=True,
        defaults={
            "source_external_id": source_external_id,
            "title": title,
            "description": description,
            "action_label": action_label,
            "action_route": action_route,
        },
    )
    if created:
        logger.info(
            "block.created",
            user_id=user.id,
            source_type=source_type,
        )
    else:
        logger.info(
            "block.updated",
            user_id=user.id,
            source_type=source_type,
        )
    return block


def resolve_for_source(*, user, source_type: str) -> None:
    """Resolve TODOS os blocos ativos da fonte (idempotente — no-op se não houver)."""
    updated = ValidationBlock.objects.filter(
        user=user,
        source_type=source_type,
        resolved_at__isnull=True,
    ).update(resolved_at=timezone.now())
    if updated:
        logger.info(
            "block.resolved",
            user_id=user.id,
            source_type=source_type,
            count=updated,
        )


def get_active_blocks(user) -> list[ValidationBlock]:
    """Blocos NÃO resolvidos do usuário (ordem: mais recente primeiro)."""
    return list(
        ValidationBlock.objects.filter(user=user, resolved_at__isnull=True).order_by(
            "-created_at"
        )
    )


def get_by_id(*, user, block_id: int) -> ValidationBlock | None:
    """Busca bloco por ID validando que pertence ao user (anti-enumeração)."""
    return ValidationBlock.objects.filter(id=block_id, user=user).first()


def resolve_by_id(*, user, block_id: int) -> ValidationBlock | None:
    """Resolve 1 bloco ativo por ID. Retorna o bloco resolvido ou None se não pertence ao user / já
    resolvido. Endpoint explícito do front (modal "dispensar") — em geral o bloco resolve no upload."""
    block = ValidationBlock.objects.filter(
        id=block_id, user=user, resolved_at__isnull=True
    ).first()
    if block is None:
        return None
    from django.utils import timezone

    block.resolved_at = timezone.now()
    block.save(update_fields=["resolved_at"])
    logger.info("block.resolved_by_id", user_id=user.id, block_id=block_id)
    return block


def to_dict(block: ValidationBlock) -> dict:
    return {
        "external_id": str(
            block.id
        ),  # ponytail: pk como external_id; model não herda ExternalIdModel
        "source_type": block.source_type,
        "title": block.title,
        "description": block.description,
        "action_label": block.action_label,
        "action_route": block.action_route,
        "created_at": block.created_at.isoformat(),
    }
