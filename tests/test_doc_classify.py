"""IA de classificação RÁPIDA de documento (síncrona, front→backend→OmniRoute): reconhece tipo,
lado e legibilidade sem validar autenticidade. A validação minuciosa continua assíncrona.
"""

import json

import pytest

pytestmark = pytest.mark.django_db


def _patch_vision(monkeypatch, raw: str):
    """Mocka o describe_image (multimodal OmniRoute) devolvendo `raw` (o que o LLM 'veria')."""
    from integrations.ai import service as ai

    monkeypatch.setattr(ai, "describe_image", lambda *a, **k: raw)
    return ai


def test_classifica_rg_frente(monkeypatch):
    ai = _patch_vision(
        monkeypatch,
        json.dumps(
            {
                "is_document": True,
                "doc_type": "rg",
                "completeness": "front",
                "is_legible": True,
                "reason": "Frente do RG inteira e nítida.",
                "confidence": 0.9,
            }
        ),
    )
    out = ai.classify_document(b"fake", caller="test")
    assert out["is_document"] is True
    assert out["doc_type"] == "rg"
    assert out["completeness"] == "front"
    assert out["is_legible"] is True
    assert out["reason"] == "Frente do RG inteira e nítida."


def test_classifica_documento_ilegivel(monkeypatch):
    ai = _patch_vision(
        monkeypatch,
        json.dumps(
            {
                "is_document": True,
                "doc_type": "rg",
                "completeness": "back",
                "is_legible": False,
                "reason": "O verso está desfocado.",
                "confidence": 0.92,
            }
        ),
    )
    out = ai.classify_document(b"fake", caller="test")
    assert out["is_legible"] is False
    assert out["reason"] == "O verso está desfocado."


def test_classifica_cnh_inteiro(monkeypatch):
    ai = _patch_vision(
        monkeypatch,
        json.dumps(
            {
                "is_document": True,
                "doc_type": "cnh",
                "completeness": "full",
                "confidence": 0.8,
            }
        ),
    )
    out = ai.classify_document(b"fake", caller="test")
    assert out["doc_type"] == "cnh"
    assert out["completeness"] == "full"


def test_nao_e_documento(monkeypatch):
    ai = _patch_vision(
        monkeypatch,
        json.dumps(
            {
                "is_document": False,
                "doc_type": None,
                "completeness": None,
                "confidence": 0.95,
            }
        ),
    )
    out = ai.classify_document(b"fake", caller="test")
    assert out["is_document"] is False


def test_resposta_suja_com_texto_extra_ainda_parseia(monkeypatch):
    """O LLM às vezes embrulha o JSON em prosa/```json — o classificador tem que extrair mesmo assim."""
    ai = _patch_vision(
        monkeypatch,
        'Claro! Aqui está:\n```json\n{"is_document": true, "doc_type": "rg", '
        '"completeness": "back", "confidence": 0.7}\n```\nEspero ter ajudado.',
    )
    out = ai.classify_document(b"fake", caller="test")
    assert out["doc_type"] == "rg" and out["completeness"] == "back"


def test_lixo_total_cai_em_indefinido_sem_quebrar(monkeypatch):
    """Se o LLM devolver algo impossível de parsear, NÃO explode — devolve indefinido (o front
    então pede a confirmação manual da pessoa)."""
    ai = _patch_vision(monkeypatch, "desculpe, não consegui ver a imagem")
    out = ai.classify_document(b"fake", caller="test")
    assert (
        out["is_document"] is None
    )  # indefinido → front cai no fluxo de confirmação manual


def test_pdf_e_convertido_para_imagem_antes_da_classificacao(monkeypatch):
    from integrations.ai import service as ai

    captured = {}
    monkeypatch.setattr("core.pdf.render_pdf_to_jpeg", lambda data: b"jpeg-renderizado")

    def fake_describe(image_bytes, **kwargs):
        captured["image_bytes"] = image_bytes
        captured.update(kwargs)
        return json.dumps(
            {
                "is_document": False,
                "doc_type": None,
                "completeness": None,
                "confidence": 0.99,
            }
        )

    monkeypatch.setattr(ai, "describe_image", fake_describe)
    ai.classify_document(b"pdf-original", caller="test", mime_type="application/pdf")

    assert captured["image_bytes"] == b"jpeg-renderizado"
    assert captured["mime_type"] == "image/jpeg"
    assert captured["timeout"] == 8.0


def test_endpoint_classify_exige_auth(client):
    """O endpoint de classificação é gated (só cliente do funil) — sem token dá 401, não vaza a IA."""
    import io

    r = client.post(
        "/api/v1/clients/enrollment/documents/classify",
        {"file": io.BytesIO(b"fake-image")},
    )
    assert r.status_code == 401
