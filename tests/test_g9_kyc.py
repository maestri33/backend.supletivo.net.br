"""G9 — avanço de ADDRESS (accept-first, Victor 2026-07-13).

ANTES (gate): endereço completo SÓ avançava pra EDUCATION com o comprovante APROVADO por IA.
Isso deixava o aluno PRESO esperando a IA. AGORA (accept-first): endereço completo → EDUCATION na
hora. A validação do comprovante roda em background; rejeição vira ValidationBlock (modal no app),
não trava o wizard. O KYC continua garantido — só mudou de "gate síncrono" pra "flag assíncrona".
"""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db


class _Enr:
    class user:
        external_id = "u1"

    status = None
    external_id = "e1"


def _run_advance_to_address() -> str:
    from users.roles.enrollment import service as es

    captured = {}
    with (
        patch.object(es.address_iface, "is_complete", return_value=True),
        patch.object(es.address_iface, "get_by_external_id", return_value=object()),
        patch.object(es, "_has_education", return_value=False),
        patch.object(
            es, "_set_status", side_effect=lambda enr, st: captured.update(st=st)
        ),
    ):
        es._advance_to(_Enr(), es._S.ADDRESS)
    return captured["st"]


def test_g9_endereco_completo_avança_pro_comprovante_aprovado_ou_nao():
    """accept-first: endereço completo avança pra EDUCATION independentemente do comprovante.
    O comprovante é validado em background (rejeição = ValidationBlock, não gate)."""
    from users.roles.enrollment import service as es

    # is_approved não é mais consultado em _advance_to — endereço completo basta.
    assert _run_advance_to_address() == es._S.EDUCATION
