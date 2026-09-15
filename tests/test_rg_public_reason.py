"""O motivo técnico da IA não desce pro aluno (regra do Victor, 2026-07-28).

Reprovação de RG expõe ao CLIENTE apenas orientação (o que fazer); o critério — lado
trocado, nome divergente, suspeita de adulteração — fica no `validation_result`, que só o
hub/staff lê. E reprovado ergue `blocked`: o aluno volta pro documento ao entrar e só sai
quando reenviar.
"""

import pytest

from users.roles.enrollment.service import _public_rg_reason

pytestmark = pytest.mark.django_db


def test_reprovado_vira_orientacao_e_nao_criterio():
    reason = _public_rg_reason("rejected")
    assert "Manda de novo" in reason
    # nada do vocabulário técnico da IA
    for proibido in ("nome", "adultera", "fraude", "verso", "frente"):
        assert proibido not in reason.lower()


def test_review_avisa_que_a_coordenacao_decide():
    assert "coordenação" in _public_rg_reason("review")


def test_aprovado_e_pendente_nao_tem_motivo():
    assert _public_rg_reason("approved") is None
    assert _public_rg_reason("pending") is None
    assert _public_rg_reason(None) is None
