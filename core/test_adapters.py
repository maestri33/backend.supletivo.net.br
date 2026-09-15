from __future__ import annotations

from django.conf import settings


def _require_enabled() -> None:
    if not settings.TEST_EXTERNAL_ADAPTERS or settings.APP_ENV == "prod":
        raise RuntimeError("Adaptador sintético indisponível neste ambiente.")


def _require_non_prod() -> None:
    if settings.APP_ENV == "prod":
        raise RuntimeError("Payout sintético é proibido em produção.")


def viacep_lookup(cep: str) -> dict | None:
    _require_enabled()
    clean = "".join(character for character in cep if character.isdigit())
    fixtures = {
        "01310100": {
            "zipcode": "01310100",
            "street": "Avenida Paulista",
            "neighborhood": "Bela Vista",
            "city": "São Paulo",
            "state": "SP",
            "complement": "",
        },
        "01001000": {
            "zipcode": "01001000",
            "street": "Praça da Sé",
            "neighborhood": "Sé",
            "city": "São Paulo",
            "state": "SP",
            "complement": "lado ímpar",
        },
    }
    return fixtures.get(clean)


def pix_dict_lookup(*, expected_document: str) -> dict:
    _require_enabled()
    return {
        "id": "test-dict-lookup",
        "status": "CANCELLED",
        "bankAccount": {
            "cpfCnpj": expected_document,
            "ownerName": "Promotor E2E V7M",
            "bank": {"name": "Banco Sintético E2E"},
        },
    }


def kyc_result() -> tuple[str, str]:
    _require_enabled()
    outcome = settings.TEST_KYC_OUTCOME
    reasons = {
        "approved": "Aprovado pelo adapter KYC sintético.",
        "rejected": "Reprovado pelo adapter KYC sintético.",
        "review": "Baixa confiança sintética; revisão manual necessária.",
    }
    return outcome, reasons[outcome]


def document_ocr() -> str:
    _require_enabled()
    return (
        "REGISTRO GERAL 12.345.678-9\nNOME PROMOTOR E2E V7M\n"
        "NASCIMENTO 01/01/1990\nSSP/SP"
    )


def document_extract(*, doc_type: str, holder_name: str | None) -> dict:
    _require_enabled()
    common = {
        "number": "123456789",
        "name": holder_name or "Promotor E2E V7M",
        "birth_date": "1990-01-01",
        "mother_name": "Maria E2E",
        "father_name": "José E2E",
        "name_match": "sim",
        "name_reason": "Titular sintético correspondente.",
    }
    if doc_type == "cnh":
        return {
            **common,
            "category": "B",
            "national_register": "12345678900",
            "expires_on": "2030-01-01",
        }
    return {
        **common,
        "issuing_agency": "SSP/SP",
        "issue_date": "2015-01-01",
        "birthplace": "São Paulo/SP",
    }


def payout_response(*, payment_id: str) -> dict:
    _require_non_prod()
    return {"id": f"test-{payment_id}", "status": "PENDING"}
