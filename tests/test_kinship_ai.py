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
@pytest.fixture
def kinship_proof():
    from users.auth.models import User
    from users.profiles.models import Profile
    from users.documents import service as documents
    user = User.objects.create_user()
    Profile.objects.create(user=user, name="Titular Teste")
    documents.create_empty(user)
    proof = documents.get_address_proof(str(user.external_id))
    proof.photo = "documents/test.png"
    proof.validation_status = "needs_kinship"
    proof.save()
    return user, proof


def test_submit_kinship_sem_fundamento_nao_aprova(monkeypatch, kinship_proof):
    from users.roles import _address_proof as ap_mod
    from integrations.ai import service as ai

    monkeypatch.setattr(
        ai,
        "evaluate_kinship",
        lambda relation, **k: {"has_merit": False, "corrected": "", "reason": "lixo"},
    )

    user, proof = kinship_proof
    status = ap_mod.submit_kinship(str(user.external_id), "asdfgh")
    proof.refresh_from_db()
    assert status == ap_mod.NEEDS_KINSHIP, "sem fundamento não deveria aprovar"
    assert proof.validation_status == ap_mod.NEEDS_KINSHIP
    assert proof.kinship_relation is None


def test_submit_kinship_com_fundamento_salva_texto_corrigido(monkeypatch, kinship_proof):
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

    user, proof = kinship_proof
    status = ap_mod.submit_kinship(str(user.external_id), "eh minha mae maria")
    proof.refresh_from_db()
    assert status == ap_mod.APPROVED
    assert proof.kinship_relation == "É minha mãe, Maria.", (
        "deveria salvar o texto corrigido pela IA"
    )
