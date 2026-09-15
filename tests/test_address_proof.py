"""F1 — validação do comprovante de endereço por IA (Victor 2026-07-08).

Trava dois eixos que o student NÃO cobria: (a) o endereço extraído bate com o informado? (b) titular
diferente NÃO reprova → `needs_kinship`. Mocka a IA (visão + extração) e afirma a tabela de decisão.
O comparador puro `_address_matches` é coberto diretamente no fim deste arquivo.
"""

from __future__ import annotations

from unittest.mock import patch

from users.roles import _address_proof as ap


class _Addr:
    """Endereço COMPLETO (is_complete=True): o gate de divergência só roda com endereço
    completo desde o comprovante-primeiro (2026-07-28) — incompleto/vazio é populado, não
    comparado."""

    def __init__(self, zipcode="01310100", street="Avenida Paulista", city="São Paulo"):
        self.zipcode = zipcode
        self.street = street
        self.city = city
        self.number = "1000"
        self.state = "SP"


def _run(extracted, *, vision=("approved", "ok"), addr=None):
    """Roda run_validation com a IA mockada. `extracted` = o JSON que a extração devolve."""
    with (
        patch(
            "users.roles.student._document_ai.check_student_document_photo",
            return_value=vision,
        ),
        patch("users.roles.student._document_ai.ocr_image", return_value="ocr text"),
        patch(
            "users.roles.student._document_ai.extract_student_document",
            return_value=extracted,
        ),
    ):
        return ap.run_validation(
            b"fake", address=addr or _Addr(), holder_name="Maria Silva", caller="test"
        )


def test_endereco_bate_titular_bate_aprova():
    status, _ = _run(
        {
            "zip": "01310100",
            "city": "São Paulo",
            "street": "Av Paulista",
            "name_match": "sim",
        }
    )
    assert status == ap.APPROVED


def test_endereco_nao_bate_reprova_nao_needs_kinship():
    # cidade divergente → rejected (NÃO needs_kinship, mesmo com titular ok)
    status, payload = _run({"city": "Campinas", "street": "Rua X", "name_match": "sim"})
    assert status == ap.REJECTED
    assert "endereço" in payload["reason"].lower()


def test_endereco_bate_titular_outro_pede_parentesco():
    status, _ = _run(
        {
            "zip": "01310100",
            "city": "São Paulo",
            "name_match": "nao",
            "name_reason": "outro nome",
        }
    )
    assert status == ap.NEEDS_KINSHIP


def test_titular_duvida_vai_pra_review():
    status, _ = _run({"zip": "01310100", "city": "São Paulo", "name_match": "duvida"})
    assert status == ap.REVIEW


def test_visao_reprova_nem_extrai():
    status, _ = _run({"name_match": "sim"}, vision=("rejected", "não é comprovante"))
    assert status == ap.REJECTED


def test_comparador_puro():
    cases = [
        ({"zip": "01310-100", "city": "São Paulo"}, _Addr(), True),
        ({"zip": "01310100", "street": "Av. Paulista"}, _Addr(), True),
        ({"city": "Campinas"}, _Addr(), False),
        ({"zip": "99999-000"}, _Addr(), False),
        ({}, _Addr(), True),
        (
            {"street": "Rua das Flores"},
            _Addr(zipcode=None, street="Avenida Brasil", city=None),
            False,
        ),
    ]
    for extracted, address, expected in cases:
        assert ap._address_matches(extracted, address)[0] is expected
