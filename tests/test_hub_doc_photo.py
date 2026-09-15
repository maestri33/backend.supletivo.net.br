"""Hub/coordenador: o coordenador decide aprovar/reprovar o DOCUMENTO (RG/CNH) do candidato, mas
`candidate_detail_for_coordinator` não trazia a foto do documento nem o motivo da IA — só a selfie.
Aprovar às cegas. Fix: incluir um bloco `document` (fotos + status + reason) no detalhe.
"""

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.django_db


def _fake_candidate(monkeypatch, *, kind="rg"):
    from users.roles.candidate import service as cs

    class _Sub:  # instância RG/CNH (users.documents.models)
        front_photo = "documents/tok_front.jpg"
        back_photo = "documents/tok_back.jpg"
        full_photo = None
        validation_status = "review"
        validation_result = {"reason": "verso ilegível"}

    class _Cand:
        external_id = "c1"
        status = "completed"
        doc_type = kind
        pix_validated = True
        selfie_status = "approved"
        selfie_image = "selfie/s1.jpg"
        selfie_description = None
        user = type("U", (), {"external_id": "u1", "id": 1})()
        hub = type("H", (), {"coordinator_id": 99})()

    mgr = MagicMock()
    mgr.filter.return_value.select_related.return_value.first.return_value = _Cand()
    monkeypatch.setattr(cs.Candidate, "objects", mgr)
    monkeypatch.setattr(cs.profiles, "get", lambda u: None)
    monkeypatch.setattr(cs.documents_iface, "get_doc_sub", lambda ext, dt: _Sub())
    coordinator = type("C", (), {"id": 99})()
    return cs, coordinator


def test_detalhe_do_coordenador_traz_a_foto_do_documento(monkeypatch):
    """O coordenador PRECISA ver a foto do RG/CNH pra decidir — não só a selfie."""
    cs, coord = _fake_candidate(monkeypatch)
    detail = cs.candidate_detail_for_coordinator(
        candidate_external_id="c1", coordinator=coord
    )
    assert detail.get("document") is not None, (
        "detalhe sem bloco de documento — aprovaria às cegas"
    )
    doc = detail["document"]
    assert doc["front_photo"] == "documents/tok_front.jpg"
    assert doc["back_photo"] == "documents/tok_back.jpg"
    assert doc["doc_type"] == "rg"


def test_detalhe_traz_o_motivo_da_ia(monkeypatch):
    """O motivo da IA (por que caiu em review) orienta a decisão do coordenador."""
    cs, coord = _fake_candidate(monkeypatch)
    detail = cs.candidate_detail_for_coordinator(
        candidate_external_id="c1", coordinator=coord
    )
    assert detail["document"]["analysis_reason"] == "verso ilegível"
    assert detail["document"]["analysis_status"] == "review"


# ── documento do ALUNO: o detalhe do coordenador precisa da foto + do external_id do doc ──
def test_detalhe_do_aluno_traz_foto_e_id_do_documento(monkeypatch):
    """O coordenador decide o documento do aluno via `.../documents/{doc_id}/decide` — precisa da
    FOTO (pra ver) e do `external_id` do doc (pra endereçar a decisão)."""
    from users.roles.student import service as ss

    class _Doc:
        external_id = "d1"
        doc_type = "id_card"
        photo = "student/u1/id_card.jpg"
        validation_status = "review"
        validation_result = {"reason": "foto cortada"}

    class _Student:
        external_id = "s1"
        status = "documents_under_review"
        bolsista = False
        platform_login = None
        platform_password = None
        platform_notes = None
        blood_type = None
        user = type("U", (), {"external_id": "u1"})()

        class _Docs:
            @staticmethod
            def all():
                return [_Doc()]

        documents = _Docs()
        pendencies = type("P", (), {"all": staticmethod(lambda: [])})()

    monkeypatch.setattr(
        ss,
        "_document_analysis_reason",
        lambda d: (d.validation_result or {}).get("reason"),
    )
    monkeypatch.setattr(ss, "_document_expires_at", lambda d: None)
    # a montagem do dict de documento é o que testamos — chamamos o builder direto se existir,
    # senão validamos via a estrutura que detail_for_coordinator produz.
    docs = ss._student_documents_dict(_Student())
    assert docs[0]["photo"] == "student/u1/id_card.jpg", (
        "sem a foto o coordenador aprova às cegas"
    )
    assert docs[0]["external_id"] == "d1", (
        "sem o external_id não dá pra endereçar a decisão"
    )
