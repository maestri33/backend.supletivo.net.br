"""Schemas Pydantic v2 do grupo Staff: Materiais de Treinamento e Submissões."""

from __future__ import annotations

from typing import Any

from ninja import Field, FilterSchema, Schema
from pydantic import ConfigDict


class StaffMaterialOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    title: str
    text_content: str
    content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    question: str
    video: str | None = None
    photo: str | None = None
    kind: str
    blocking: bool
    ephemeral: bool
    order: int
    active: bool
    expected_answer: str | None = None


class PublishMaterialOut(Schema):
    external_id: str
    assigned: int


class DeleteMaterialOut(Schema):
    deleted: str


class TrainingSubmissionFilterSchema(FilterSchema):
    status: str | None = None
    material_id: str | None = None


class TrainingSubmissionOut(Schema):
    model_config = ConfigDict(from_attributes=True)

    external_id: str
    user_external_id: str
    user_name: str
    user_phone: str | None = None
    material_title: str
    material_question: str
    material_expected: str
    answer: str
    audio_url: str | None = None
    grade: str | None = None
    justification: str | None = None
    status: str
    created_at: str


class TrainingOverrideOut(Schema):
    detail: str
    status: str


class TrainingUnlockOut(Schema):
    detail: str
