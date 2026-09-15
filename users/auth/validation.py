"""Validação de formato de CPF e phone — fail-fast antes de chamar serviço externo (porte do legado).

Só FORMATO aqui (regra barata, local). A veracidade ("nem falsos", spec auth) é checada no register
contra serviços REAIS: CPFHub (a identidade existe) e WhatsApp check_numbers (o número existe no zap).
"""

from __future__ import annotations

import re
import phonenumbers
from phonenumbers import NumberParseException
from validate_docbr import CPF

_cpf_validator = CPF()


def validate_cpf(cpf: str) -> str:
    """Normaliza e valida o FORMATO do CPF. Retorna 11 dígitos ou levanta ValueError."""
    clean = re.sub(r"\D", "", cpf or "")
    if len(clean) != 11:
        raise ValueError(f"CPF deve ter 11 dígitos, encontrados {len(clean)}.")
    if clean == clean[0] * 11:
        raise ValueError("CPF não pode ter todos os dígitos iguais.")
    return clean


def validate_cpf_strict(cpf: str) -> str:
    """Valida o formato e os dígitos verificadores do CPF via validate_docbr.

    Retorna 11 dígitos limpos ou levanta ValueError.
    """
    clean = validate_cpf(cpf)
    if not _cpf_validator.validate(clean):
        raise ValueError("CPF inválido (dígitos verificadores incorretos).")
    return clean


def cpf_check_digits_ok(cpf: str) -> bool:
    """Dígitos verificadores do CPF (mod-11 / validate_docbr). Usado pelo passo 3 do funil v2 (`confirm_identity`)
    ANTES do lookup no CPFHub — DV errado nem gasta chamada externa."""
    clean = re.sub(r"\D", "", cpf or "")
    if len(clean) != 11 or clean == clean[0] * 11:
        return False
    return _cpf_validator.validate(clean)


def validate_phone(phone: str) -> str:
    """Normaliza pro formato canônico DDI+DDD+número (BR). Retorna 12 ou 13 dígitos ou ValueError.

    Aceita com DDI (`55…`, 12/13 díg) ou sem (10/11 díg, DDD+número) — neste caso prefixa `55`.
    É o formato que o WhatsApp/notify (resolve_br_number) consomem.
    """
    clean = re.sub(r"\D", "", phone or "")
    if clean.startswith("55"):
        if len(clean) not in (12, 13):
            raise ValueError(
                f"Telefone BR com DDI deve ter 12 ou 13 dígitos, encontrados {len(clean)}."
            )
        return clean
    if len(clean) in (10, 11):
        return "55" + clean
    raise ValueError(
        f"Telefone deve ter 10 ou 11 dígitos (DDD+número), encontrados {len(clean)}."
    )


def validate_phone_strict(phone: str) -> str:
    """Validação rigorosa de telefone/celular brasileiro usando Google phonenumbers.

    Retorna o número canônico com DDI 55 (ex: '5511988887777') ou levanta ValueError.
    """
    clean = re.sub(r"\D", "", phone or "")
    if not clean:
        raise ValueError("Telefone não pode ser vazio.")

    raw = str(phone).strip()
    if not raw.startswith("+"):
        if clean.startswith("55"):
            raw = f"+{clean}"
        else:
            raw = f"+55{clean}"

    try:
        parsed = phonenumbers.parse(raw, "BR")
    except NumberParseException as exc:
        raise ValueError(f"Número de telefone inválido: {exc}") from exc

    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Número de telefone/celular inválido para o Brasil.")

    return f"{parsed.country_code}{parsed.national_number}"
