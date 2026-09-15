"""Titularidade do comprovante em camadas (Victor 2026-07-28).

O próprio → aprova; **pai/mãe** (filiação que o RG populou) → aprova direto; **sobrenome em
comum** → confirmar o grau (`kinship_kind="confirm"`); **nome sem relação** → justificar
(`kinship_kind="justify"`). E o que o aluno lê é orientação — o critério fica interno.
"""

import pytest

from users.roles import _address_proof as ap

pytestmark = pytest.mark.django_db


def _mock_ai(monkeypatch, extracted: dict):
    """Visão aprova e a extração devolve `extracted` — isola a REGRA das chamadas de IA."""
    from users.roles.student import _document_ai as doc_ai

    monkeypatch.setattr(
        doc_ai, "check_student_document_photo", lambda *a, **k: (doc_ai.APPROVED, "ok")
    )
    monkeypatch.setattr(doc_ai, "ocr_image", lambda *a, **k: "texto ocr")
    monkeypatch.setattr(doc_ai, "extract_student_document", lambda *a, **k: extracted)


def _run(monkeypatch, extracted, **kwargs):
    _mock_ai(monkeypatch, extracted)
    return ap.run_validation(
        b"img",
        address=None,  # comprovante-PRIMEIRO: nada digitado ainda
        holder_name="Victor Vanderley Maestri",
        caller="test",
        **kwargs,
    )


def test_titular_o_proprio_aprova(monkeypatch):
    status, result = _run(
        monkeypatch,
        {"name_match": "sim", "holder_name": "Victor Vanderley Maestri"},
    )
    assert status == ap.APPROVED


def test_comprovante_da_mae_aprova_direto(monkeypatch):
    status, result = _run(
        monkeypatch,
        {"name_match": "nao", "holder_name": "JOSIANE ARANTES DA SILVA"},
        mother_name="Josiane Arantes da Silva",
        father_name="Elcio Antonio Maestri",
    )
    assert status == ap.APPROVED
    assert "mãe" in result["reason"]


def test_comprovante_do_pai_aprova_direto(monkeypatch):
    status, result = _run(
        monkeypatch,
        {"name_match": "nao", "holder_name": "ELCIO ANTONIO MAESTRI"},
        mother_name="Josiane Arantes da Silva",
        father_name="Elcio Antonio Maestri",
    )
    assert status == ap.APPROVED
    assert "pai" in result["reason"]


def test_sobrenome_em_comum_pede_confirmacao_do_grau(monkeypatch):
    status, result = _run(
        monkeypatch,
        {"name_match": "nao", "holder_name": "Ana Paula Maestri"},
        mother_name="Josiane Arantes da Silva",
    )
    assert status == ap.NEEDS_KINSHIP
    assert result["kinship_kind"] == "confirm"


def test_nome_sem_relacao_pede_justificativa(monkeypatch):
    status, result = _run(
        monkeypatch,
        {"name_match": "nao", "holder_name": "João Carlos de Souza"},
    )
    assert status == ap.NEEDS_KINSHIP
    assert result["kinship_kind"] == "justify"


def test_conectivos_nao_contam_como_sobrenome():
    # "de"/"da" em comum não é família — sem isso, todo "de Souza" viraria parente.
    assert ap._surnames("Maria de Souza") & ap._surnames("Victor de Maestri") == set()


def test_reason_publico_e_orientacao_nunca_criterio():
    aluno_le = ap._public_reason(
        ap.NEEDS_KINSHIP,
        {"kinship_kind": "justify", "extracted": {"holder_name": "João"}},
    )
    assert (
        "João" in aluno_le
    )  # quem é o titular a pessoa PODE saber (o comprovante é dela)
    novo_doc = ap._public_reason(ap.REJECTED, {"needs_new_proof": True})
    assert "SEU nome" in novo_doc
    generico = ap._public_reason(ap.REJECTED, {})
    assert "titular" not in generico.lower()
