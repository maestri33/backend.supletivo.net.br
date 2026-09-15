from __future__ import annotations

from typing import Any
from ninja import Field, Schema


class MaterialIn(Schema):
    """Criação de uma matéria do treino: conteúdo (texto/blocos) + questão + gabarito.

    `kind` fixa (todo promotor novo recebe) ou transitória (staff publica p/ os existentes);
    `blocking` = obrigatória (trava o painel); `ephemeral` = descartável; `content_blocks` =
    conteúdo rico (texto/imagem/vídeo/arquivo) que o front renderiza em ordem."""

    title: str
    question: str
    expected_answer: str
    text_content: str = ""
    content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    order: int = 0
    kind: str = "fixed"
    blocking: bool = True
    ephemeral: bool = False
    video: str | None = None
    photo: str | None = None


class MaterialUpdateIn(Schema):
    """Edição de uma matéria — só os campos enviados; `active=False` desativa."""

    title: str | None = None
    text_content: str | None = None
    content_blocks: list[dict[str, Any]] | None = None
    question: str | None = None
    expected_answer: str | None = None
    order: int | None = None
    active: bool | None = None
    kind: str | None = None
    blocking: bool | None = None
    ephemeral: bool | None = None
    video: str | None = None
    photo: str | None = None
