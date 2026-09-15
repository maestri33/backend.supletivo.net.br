"""Comprovante em nome de outra pessoa (`needs_kinship`): a pessoa escreve quem é o titular. Uma IA
avalia se a resposta tem FUNDAMENTO (não é lixo/sem sentido) e corrige/simplifica o português antes
de salvar. Sem fundamento → NÃO aprova; volta pra pessoa reescrever (human-in-the-loop).
"""

import pytest

pytestmark = pytest.mark.django_db


def _patch_ai(monkeypatch, result: dict):
    from integrations.ai import service as ai

    monkeypatch.setattr(ai, "evaluate_kinship", lambda relation, **k: result)
    return ai


def test_evaluate_kinship_parse_e_normaliza(monkeypatch):
    """evaluate_kinship devolve o contrato {has_merit, corrected, reason} a partir do JSON do LLM."""
    from integrations.ai import service as ai

    monkeypatch.setattr(
        ai,
        "generate_json",
        lambda *a, **k: {
            "has_merit": True,
            "corrected": "É minha mãe, Maria da Silva.",
            "reason": "explica o parentesco de forma plausível",
        },
    )
    out = ai.evaluate_kinship("eh minha mae maria da silva", caller="test")
    assert out["has_merit"] is True
    assert out["corrected"] == "É minha mãe, Maria da Silva."


def test_evaluate_kinship_sem_fundamento(monkeypatch):
    from integrations.ai import service as ai

    monkeypatch.setattr(
        ai,
        "generate_json",
        lambda *a, **k: {
            "has_merit": False,
            "corrected": "",
            "reason": "texto sem sentido",
        },
    )
    out = ai.evaluate_kinship("asdfgh", caller="test")
    assert out["has_merit"] is False


def test_evaluate_kinship_ia_falha_nao_bloqueia(monkeypatch):
    """Se a IA cair, NÃO trava a pessoa: assume mérito e usa o texto original (fail-open — a
    validação minuciosa do comprovante ainda roda depois)."""
    from integrations.ai import service as ai
    from integrations.ai.client import LLMError

    def boom(*a, **k):
        raise LLMError("ia fora", retryable=True)

    monkeypatch.setattr(ai, "generate_json", boom)
    out = ai.evaluate_kinship("minha mãe", caller="test")
    assert out["has_merit"] is True
    assert out["corrected"] == "minha mãe"  # cai no texto original


# ── integração com o fluxo do comprovante: sem fundamento NÃO aprova ──
def test_submit_kinship_sem_fundamento_nao_aprova(monkeypatch):
    from users.roles import _address_proof as ap_mod
    from integrations.ai import service as ai

    monkeypatch.setattr(
        ai,
        "evaluate_kinship",
        lambda relation, **k: {"has_merit": False, "corrected": "", "reason": "lixo"},
    )

    saved = {"status": None, "relation": None}

    class _AP:
        validation_status = ap_mod.NEEDS_KINSHIP
        kinship_relation = None
        kinship_provided_at = None

        def save(self, **kw):
            saved["status"] = self.validation_status
            saved["relation"] = self.kinship_relation

    from users.documents import service as documents_iface

    monkeypatch.setattr(documents_iface, "get_address_proof", lambda ext: _AP())

    status = ap_mod.submit_kinship("u1", "asdfgh")
    assert status == ap_mod.NEEDS_KINSHIP, "sem fundamento não deveria aprovar"
    assert saved["status"] is None, "não deveria ter salvado aprovação"


def test_submit_kinship_com_fundamento_salva_texto_corrigido(monkeypatch):
    from users.roles import _address_proof as ap_mod
    from integrations.ai import service as ai

    monkeypatch.setattr(
        ai,
        "evaluate_kinship",
        lambda relation, **k: {
            "has_merit": True,
            "corrected": "É minha mãe, Maria.",
            "reason": "ok",
        },
    )

    saved = {}

    class _AP:
        validation_status = ap_mod.NEEDS_KINSHIP
        kinship_relation = None
        kinship_provided_at = None

        def save(self, **kw):
            saved["status"] = self.validation_status
            saved["relation"] = self.kinship_relation

    from users.documents import service as documents_iface

    monkeypatch.setattr(documents_iface, "get_address_proof", lambda ext: _AP())

    status = ap_mod.submit_kinship("u1", "eh minha mae maria")
    assert status == ap_mod.APPROVED
    assert saved["relation"] == "É minha mãe, Maria.", (
        "deveria salvar o texto corrigido pela IA"
    )
