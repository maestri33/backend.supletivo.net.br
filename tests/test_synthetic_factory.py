"""Tests for BrazilianDataFactory."""
from validate_docbr import CPF
from tests.synthetic_fixtures import BrazilianDataFactory


def test_cpf_generation_validity():
    cpf_validator = CPF()
    for _ in range(50):
        raw_cpf = BrazilianDataFactory.generate_cpf(formatted=False, valid=True)
        assert len(raw_cpf) == 11
        assert cpf_validator.validate(raw_cpf), f"CPF {raw_cpf} should be valid"

        formatted_cpf = BrazilianDataFactory.generate_cpf(formatted=True, valid=True)
        assert len(formatted_cpf) == 14
        assert cpf_validator.validate(formatted_cpf)


def test_invalid_cpf_generation():
    cpf_validator = CPF()
    for _ in range(10):
        invalid_cpf = BrazilianDataFactory.generate_cpf(formatted=False, valid=False)
        assert not cpf_validator.validate(invalid_cpf), f"CPF {invalid_cpf} should be invalid"


def test_phone_generation():
    for _ in range(50):
        phone = BrazilianDataFactory.generate_phone()
        assert phone.startswith("55")
        assert len(phone) == 13
        assert phone[2:4] in BrazilianDataFactory.VALID_DDDS
        assert phone[4] == "9"


def test_synthetic_image_generation():
    for kind in ["rg_front", "rg_back", "selfie"]:
        img_bytes = BrazilianDataFactory.generate_synthetic_image(kind=kind)
        assert len(img_bytes) > 500
        assert img_bytes.startswith(b"\x89PNG\r\n\x1a\n")
