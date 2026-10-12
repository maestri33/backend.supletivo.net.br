from datetime import date
from types import SimpleNamespace

import pytest

from users.roles._document_ai import compare_identity_names, validate_identity_data


@pytest.mark.parametrize(("expected", "actual"), [
    ("Maria Silva", "Maria Silva Santos"),
    ("Maria Silva Santos", "Maria Silva"),
    ("João da Silva", "Joao da Silva"),
])
def test_accepts_married_names_and_accents(expected, actual):
    assert compare_identity_names(expected, actual) is True


def test_rejects_a_different_holder():
    assert compare_identity_names("Maria Silva", "Pedro Silva") is False
    assert compare_identity_names("Maria Silva", "Maria Silveira") is False


def test_first_name_alone_does_not_confirm_identity():
    assert compare_identity_names("Maria Silva", "Maria") is None


@pytest.mark.parametrize("birth", [None, "bad-date", "2090-01-02"])
def test_missing_or_future_birth_cannot_approve_an_incomplete_profile(birth):
    profile = SimpleNamespace(name="Maria Silva", cpf="52998224725", birth_date=None)
    assert validate_identity_data({"name": "Maria Silva", "birth_date": birth}, profile)[0] == "duvida"


def test_valid_birth_is_available_to_fill_an_incomplete_profile():
    profile = SimpleNamespace(name="Maria Silva", cpf="52998224725", birth_date=None)
    status, _, checks = validate_identity_data({"name": "Maria Silva", "birth_date": "1990-01-02"}, profile)
    assert status == "sim"
    assert checks["birth_date"] == "extracted"


def test_checks_cpf_and_birth_before_approval():
    profile = SimpleNamespace(name="Maria Silva", cpf="52998224725", birth_date=date(1990, 1, 2))
    data = {"name": "Maria Silva Santos", "cpf": "529.982.247-25", "birth_date": "1990-01-02"}
    status, _, checks = validate_identity_data(data, profile)
    assert status == "sim"
    assert checks == {"name": "match", "cpf": "match", "birth_date": "match"}


@pytest.mark.parametrize(("field", "value"), [("cpf", "11144477735"), ("birth_date", "1991-01-02")])
def test_rejects_cpf_or_birth_mismatch(field, value):
    profile = SimpleNamespace(name="Maria Silva", cpf="52998224725", birth_date=date(1990, 1, 2))
    data = {"name": "Maria Silva", "cpf": "52998224725", "birth_date": "1990-01-02", field: value}
    status, _, checks = validate_identity_data(data, profile)
    assert status == "nao"
    assert checks[field] == "mismatch"


def test_missing_document_cpf_is_allowed_but_birth_must_be_confirmed():
    profile = SimpleNamespace(name="Maria Silva", cpf="52998224725", birth_date=date(1990, 1, 2))
    status, _, checks = validate_identity_data({"name": "Maria Silva", "birth_date": "1990-01-02"}, profile)
    assert status == "sim"
    assert checks["cpf"] == "absent"
    assert validate_identity_data({"name": "Maria Silva", "birth_date": "bad-date"}, profile)[0] == "duvida"


@pytest.mark.parametrize("presence", [True, None])
def test_unreadable_cpf_is_not_treated_as_absent(presence):
    profile = SimpleNamespace(name="Maria Silva", cpf="52998224725", birth_date=date(1990, 1, 2))
    status, _, checks = validate_identity_data({"name": "Maria Silva", "birth_date": "1990-01-02", "cpf_present": presence}, profile)
    assert status == "duvida"
    assert checks["cpf"] == "unverified"


def test_invalid_ocr_cpf_requires_review_instead_of_rejecting_the_holder():
    profile = SimpleNamespace(name="Maria Silva", cpf="52998224725", birth_date=date(1990, 1, 2))
    status, _, checks = validate_identity_data({"name": "Maria Silva", "birth_date": "1990-01-02", "cpf": "52998224726"}, profile)
    assert status == "duvida"
    assert checks["cpf"] == "unverified"
