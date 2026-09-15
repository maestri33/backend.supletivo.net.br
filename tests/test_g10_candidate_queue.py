"""G10 — a fila de aprovação do candidate e reject_candidate exigiam status COMPLETED, que o fluxo
atual nunca atinge (a selfie aprovada auto-promove; a em review deixa em SELFIE). Resultado: inbox
do coordenador sempre vazio e rejeição sempre 409. Alinhados ao status real (SELFIE-review).
"""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db


def _reject(status):
    from users.roles.candidate import service as cs

    class _Hub:
        coordinator_id = 1

    class _User:
        external_id = "u1"

    class _Cand:
        hub = _Hub()
        user = _User()
        external_id = "c1"

    _Cand.status = status

    class _Coord:
        id = 1

    with (
        patch.object(cs.Candidate, "objects") as cobj,
        patch.object(cs, "_set_status") as setst,
        patch.object(cs, "_notify_candidate_rejected"),
    ):
        cobj.filter.return_value.select_related.return_value.first.return_value = (
            _Cand()
        )
        cs.reject_candidate(candidate_external_id="c1", coordinator=_Coord())
        return setst.called


def test_g10_reject_aceita_selfie_review():
    """Candidato em SELFIE (aguardando decisão) pode ser rejeitado — antes dava 409."""
    from users.roles.candidate import service as cs

    assert _reject(cs._S.SELFIE) is True


def test_g10_reject_barra_quem_ainda_coleta():
    """Não-regressão: quem ainda está na coleta (ex.: DOCUMENTS) não pode ser rejeitado."""
    from users.roles.candidate import service as cs

    with pytest.raises(cs.Conflict):
        _reject(cs._S.DOCUMENTS)


def test_g10_fila_inclui_selfie_review():
    """list_awaiting_approval_for_hub deve incluir SELFIE-em-review, e EXECUTAR sem NameError
    (o source-check sozinho não pegava que faltava importar SelfieStatus no escopo)."""
    import inspect

    from users.roles.candidate import service as cs

    src = inspect.getsource(cs.list_awaiting_approval_for_hub)
    assert "SelfieStatus.REVIEW" in src, (
        "a fila não inclui os candidatos em selfie-review"
    )

    # executa a função (constrói a query, itera vazio) — pega NameError de import faltando
    with patch.object(cs.Candidate, "objects") as cobj:
        chain = cobj.filter.return_value.filter.return_value
        chain.select_related.return_value.order_by.return_value = []
        assert cs.list_awaiting_approval_for_hub(hub=object()) == []
