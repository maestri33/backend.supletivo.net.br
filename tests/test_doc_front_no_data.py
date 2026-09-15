"""Bug (esposa do Victor, 2026-07-11): mandou SÓ a frente do RG antigo → check_photo REPROVOU por
"dados do titular ausentes/ilegíveis". Mas a FRENTE do RG antigo NÃO TEM dados textuais (foto +
digital + assinatura); os dados moram no VERSO. A frente só pode ser reprovada se NÃO for um RG —
nunca por "faltam dados". Os dados só são exigidos na extração (full ou frente+verso juntos).
"""

import pytest

pytestmark = pytest.mark.django_db


def _patch_vision(monkeypatch, resposta: str):
    from users.roles import _document_ai as doc_ai
    from integrations.ai import service as ai

    monkeypatch.setattr(ai, "describe_image", lambda *a, **k: resposta)
    return doc_ai


def test_frente_rg_sem_dados_nao_reprova(monkeypatch):
    """A IA reconhece a frente do RG mas nota que 'não há dados textuais' — NÃO é motivo de reprovar."""
    doc_ai = _patch_vision(
        monkeypatch,
        "APROVADO. É a frente de uma Carteira de Identidade brasileira (modelo antigo): foto do "
        "titular, impressão digital e assinatura. Os dados textuais ficam no verso.",
    )
    status, _reason = doc_ai.check_photo(
        b"fake", side="front", doc_type=doc_ai.DOC_RG, caller="test"
    )
    assert status == doc_ai.APPROVED, "frente de RG legítima não pode reprovar"


def test_frente_rg_nao_e_documento_reprova(monkeypatch):
    """A frente AINDA reprova se não for um RG (foto de outra coisa) — o critério (a) continua."""
    doc_ai = _patch_vision(
        monkeypatch,
        "REPROVADO. Isto é uma selfie/foto de rosto, não a frente de uma carteira de identidade.",
    )
    status, _reason = doc_ai.check_photo(
        b"fake", side="front", doc_type=doc_ai.DOC_RG, caller="test"
    )
    assert status == doc_ai.REJECTED, "foto que não é RG deve reprovar"


def test_verso_ilegivel_de_verdade_reprova(monkeypatch):
    """O verso (que TEM os dados) ainda reprova se estiver borrado/ilegível de verdade."""
    doc_ai = _patch_vision(
        monkeypatch,
        "REPROVADO. É o verso do RG mas está muito desfocado — os dados estão ilegíveis.",
    )
    status, _reason = doc_ai.check_photo(
        b"fake", side="back", doc_type=doc_ai.DOC_RG, caller="test"
    )
    assert status == doc_ai.REJECTED


def test_prompt_da_frente_proibe_reprovar_por_falta_de_dados(monkeypatch):
    """O bug estava no PROMPT: pra front/back, ele TEM que instruir a IA a não reprovar por 'faltam
    dados' (a frente do RG não tem dados). Captura o prompt enviado e verifica a instrução."""
    from users.roles import _document_ai as doc_ai
    from integrations.ai import service as ai

    captured = {}

    def fake_describe(image_bytes, *, caller, mime_type=None, prompt=None):
        captured["prompt"] = prompt
        return "APROVADO. frente ok."

    monkeypatch.setattr(ai, "describe_image", fake_describe)
    doc_ai.check_photo(b"fake", side="front", doc_type=doc_ai.DOC_RG, caller="test")
    p = captured["prompt"].lower()
    assert "não reprove porque" in p and "faltam os dados" in p, (
        "o prompt da frente precisa proibir reprovar por falta de dados (bug da esposa do Victor)"
    )


def test_prompt_exige_o_lado_solicitado(monkeypatch):
    from users.roles import _document_ai as doc_ai
    from integrations.ai import service as ai

    captured = {}
    monkeypatch.setattr(
        ai,
        "describe_image",
        lambda *a, **k: (captured.__setitem__("prompt", k.get("prompt")), "APROVADO.")[
            1
        ],
    )
    doc_ai.check_photo(b"fake", side="back", doc_type=doc_ai.DOC_RG, caller="test")
    prompt = captured["prompt"].lower()
    assert "lado esperado é obrigatório" in prompt
    assert "imagem mostrar claramente o outro lado" in prompt


def test_prompt_do_full_ainda_exige_legibilidade(monkeypatch):
    """No full (que tem tudo), a regra de legibilidade dos dados CONTINUA — não afrouxou geral."""
    from users.roles import _document_ai as doc_ai
    from integrations.ai import service as ai

    captured = {}
    monkeypatch.setattr(
        ai,
        "describe_image",
        lambda *a, **k: (captured.__setitem__("prompt", k.get("prompt")), "APROVADO.")[
            1
        ],
    )
    doc_ai.check_photo(b"fake", side="full", doc_type=doc_ai.DOC_RG, caller="test")
    assert "genuinamente ilegíveis" in captured["prompt"]
