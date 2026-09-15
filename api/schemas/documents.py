"""Schemas de documentos compartilhados entre funis (CONVENTION §12)."""

from __future__ import annotations

from ninja import Schema


class DocClassifyOut(Schema):
    """Classificação preliminar de documento pela IA."""

    is_document: bool | None = None
    doc_type: str | None = None
    completeness: str | None = None
    is_legible: bool | None = None
    reason: str | None = None
    confidence: float | None = None


class ContractOut(Schema):
    """Contrato de prestação de serviços / consentimento."""

    version: str
    hash: str
    text: str
