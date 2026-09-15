"""Testes de consentimento LGPD: selfie grava aceite."""

import pytest

pytestmark = pytest.mark.django_db


def test_consent_contract_endpoint_retorna_versao_hash_texto():
    """O contrato versionado existe e tem version, hash, text."""
    from users.consent import STUDENT_CONTRACT

    data = STUDENT_CONTRACT.as_dict()
    assert "version" in data
    assert "hash" in data
    assert "text" in data
    assert len(data["hash"]) == 64  # SHA256


def test_consent_contract_hash_bate_com_texto():
    """O hash retornado confere com SHA256 do texto."""
    import hashlib
    from users.consent import STUDENT_CONTRACT

    data = STUDENT_CONTRACT.as_dict()
    computed = hashlib.sha256(data["text"].encode()).hexdigest()
    assert computed == data["hash"]
