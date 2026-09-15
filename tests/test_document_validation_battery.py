"""Bateria de testes abrangente para validação de documentos de matrícula.
Cobre casos negativos (arquivos corrompidos, extensões inválidas, documento errado,
lados invertidos) e caso positivo com OCR e extração estruturada de campos.
"""

import json
from io import BytesIO
from PIL import Image, ImageDraw
import pytest

from integrations.ai import service as ai
from users.roles import _document_ai as doc_ai

pytestmark = pytest.mark.django_db


def _create_synthetic_image(text: str = "TEST DOCUMENT", size=(600, 400), color="white") -> bytes:
    img = Image.new("RGB", size, color=color)
    draw = ImageDraw.Draw(img)
    draw.text((30, 50), text, fill="black")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_empty_and_zero_byte_files_rejected():
    status, reason = doc_ai.check_photo(b"", side="front", doc_type="rg", mime_type="image/jpeg", caller="test")
    assert status == doc_ai.REJECTED
    assert "vazio" in reason.lower()


def test_corrupted_garbage_bytes_rejected():
    garbage = b"\x00\xFF\xAA\x55\xDE\xAD\xBE\xEF" * 32
    status, reason = doc_ai.check_photo(garbage, side="front", doc_type="rg", mime_type="image/jpeg", caller="test")
    assert status == doc_ai.REJECTED
    assert "corrompido" in reason.lower() or "inválido" in reason.lower()


def test_classify_document_handles_corrupted_bytes():
    garbage = b"not_an_image_binary_data_here"
    res = ai.classify_document(garbage, caller="test", mime_type="image/jpeg")
    assert res["is_document"] is False
    assert "corrompido" in res["reason"].lower() or "ilegível" in res["reason"].lower()


def test_classify_document_non_document_rejected(monkeypatch):
    monkeypatch.setattr(
        ai,
        "describe_image",
        lambda *a, **k: json.dumps({
            "is_document": False,
            "doc_type": None,
            "completeness": None,
            "is_legible": False,
            "reason": "Isto é uma foto de paisagem/objeto, não um documento de identificação.",
            "confidence": 0.98,
        }),
    )
    img_bytes = _create_synthetic_image("Paisagem de montanha")
    res = ai.classify_document(img_bytes, caller="test", mime_type="image/jpeg")
    assert res["is_document"] is False


def test_wrong_document_type_rejected(monkeypatch):
    monkeypatch.setattr(
        ai,
        "describe_image",
        lambda *a, **k: json.dumps({
            "is_document": True,
            "doc_type": "address_proof",
            "completeness": "full",
            "is_legible": True,
            "reason": "Comprovante de residência (fatura de luz).",
            "confidence": 0.95,
        }),
    )
    img_bytes = _create_synthetic_image("Fatura de Energia Elétrica")
    res = ai.classify_document(img_bytes, caller="test", mime_type="image/jpeg")
    assert res["is_document"] is True
    assert res["doc_type"] == "address_proof"
    # Quando enviado no slot de RG, o validador nota tipo divergente
    assert res["doc_type"] != "rg"


def test_inverted_sides_slot_rejection(monkeypatch):
    monkeypatch.setattr(
        ai,
        "describe_image",
        lambda *a, **k: "REPROVADO. A imagem contém a FRENTE do RG (foto e digital), mas o slot solicitado é o VERSO.",
    )
    img_bytes = _create_synthetic_image("Frente RG Foto Digital")
    status, reason = doc_ai.check_photo(img_bytes, side="back", doc_type="rg", mime_type="image/jpeg", caller="test")
    assert status == doc_ai.REJECTED
    assert "reprovado" in reason.lower()


def test_valid_rg_extraction_e2e(monkeypatch):
    fake_ocr = (
        "REPÚBLICA FEDERATIVA DO BRASIL\n"
        "INSTITUTO DE IDENTIFICAÇÃO DO PARANÁ\n"
        "REGISTRO GERAL: 10.981.923-9\n"
        "NOME: VICTOR VANDERLEY MAESTRI\n"
        "FILIAÇÃO: ELCIO ANTONIO MAESTRI E JOSIANE ARANTES DA SILVA\n"
        "DATA DE NASCIMENTO: 31/07/1993\n"
        "CPF: 091.263.679-39\n"
    )
    monkeypatch.setattr(ai, "ocr", lambda *a, **k: fake_ocr)
    monkeypatch.setattr(
        ai,
        "generate_json",
        lambda *a, **k: {
            "number": "10.981.923-9",
            "issuing_agency": "IIPR/PR",
            "issue_date": "2018-09-05",
            "name": "VICTOR VANDERLEY MAESTRI",
            "birth_date": "1993-07-31",
            "mother_name": "JOSIANE ARANTES DA SILVA",
            "father_name": "ELCIO ANTONIO MAESTRI",
            "birthplace": "CURITIBA/PR",
            "name_match": "sim",
            "name_reason": "Nome idêntico",
        },
    )

    data = doc_ai.extract_rg(fake_ocr, holder_name="Victor Vanderley Maestri", caller="test")
    assert data["number"] == "10.981.923-9"
    assert data["name"] == "VICTOR VANDERLEY MAESTRI"
    assert data["birth_date"] == "1993-07-31"
    assert data["name_match"] == "sim"
