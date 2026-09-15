"""pixkey — valida chave PIX no DICT do Asaas e persiste (porte do legado, ORM síncrono).

O truque (legado `asaas/app/services/pixkey.py`): cria uma transferência de **R$0,01 AGENDADA** pra amanhã
(o Asaas resolve o DICT e devolve o titular em `bankAccount`), **CANCELA** a transferência, e confere que o
`cpfCnpj` do titular bate com o CPF esperado (o do candidato, lido do Profile — não informado pelo usuário).

⚠️ **MEXE DINHEIRO REAL:** a transferência é cancelada na hora, mas a criação é uma chamada real ao Asaas
(§8 — testar com o Victor). O client async é embrulhado com `asyncio.run()`, igual `charge`/`payout`.
"""

from __future__ import annotations

import asyncio
import secrets
import unicodedata
from datetime import timedelta

import structlog
from django.conf import settings
from django.utils import timezone

from .client import AsaasError, get_client
from .models import PixKey

logger = structlog.get_logger()

VALID_KEY_TYPES = {"CPF", "CNPJ", "EMAIL", "PHONE", "EVP"}

# Apelidos PT/EN → tipo canônico do DICT. O front manda "celular"/"aleatoria" etc.; aqui vira o
# código que o Asaas entende (e que é persistido no Profile/PixKey).
_KEY_TYPE_ALIASES = {
    "cpf": "CPF",
    "cnpj": "CNPJ",
    "email": "EMAIL",
    "e-mail": "EMAIL",
    "mail": "EMAIL",
    "phone": "PHONE",
    "celular": "PHONE",
    "telefone": "PHONE",
    "fone": "PHONE",
    "evp": "EVP",
    "aleatoria": "EVP",
    "chave aleatoria": "EVP",
    "random": "EVP",
}


def normalize_key_type(raw: str | None) -> str:
    """Apelido PT/EN → tipo canônico do DICT (CPF/CNPJ/EMAIL/PHONE/EVP). Fold de acentos: "aleatória"
    também casa. Desconhecido → upper cru (rejeitado adiante por `invalid_key_type`)."""
    folded = unicodedata.normalize("NFKD", (raw or "").strip().lower())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return _KEY_TYPE_ALIASES.get(folded, (raw or "").strip().upper())


class PixKeyError(Exception):
    """Formato inválido, titular não confere, ou DICT fora — a chave NÃO é aceita (não avança o funil)."""


def _only_digits(value: str | None) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _basic_validate(key: str, key_type: str) -> None:
    k = key.strip()
    digits = _only_digits(k)
    if key_type == "CPF":
        if not (len(digits) == 11 and digits == k):
            raise PixKeyError("invalid_cpf_format")
    elif key_type == "CNPJ":
        if not (len(digits) == 14 and digits == k):
            raise PixKeyError("invalid_cnpj_format")
    elif key_type == "EMAIL":
        if "@" not in k or "." not in k.split("@")[-1]:
            raise PixKeyError("invalid_email_format")
    elif key_type == "PHONE":
        if not (k.startswith("+") and len(digits) >= 12):
            raise PixKeyError("invalid_phone_format_expected_+55DDDNNNNNNNNN")
    elif key_type == "EVP":
        if not (len(k) == 36 and k.count("-") == 4):
            raise PixKeyError("invalid_evp_format")
    else:
        raise PixKeyError("invalid_key_type")


def _doc_matches(masked_or_full: str, expected: str) -> bool:
    """O Asaas mascara CPF como `***.XXX.XXX-**` mas devolve CNPJ sem máscara. Aceita se cada char não-`*`
    bate com o dígito esperado na mesma posição (mesmo comprimento depois de tirar pontuação)."""
    a = "".join(ch for ch in (masked_or_full or "") if ch.isdigit() or ch == "*")
    b = _only_digits(expected)
    if not a or not b or len(a) != len(b):
        return False
    return all(ca == "*" or ca == cb for ca, cb in zip(a, b))


def _dict_lookup(pix_key: str) -> dict:
    """Cria a transferência R$0,01 agendada (resolve o DICT) e cancela. Devolve a resposta bruta."""
    tomorrow = (timezone.now() + timedelta(days=1)).date().isoformat()
    payload = {
        "value": 0.01,
        "pixAddressKey": pix_key,
        "scheduleDate": tomorrow,
        "externalReference": f"dict-{secrets.token_hex(6)}",
        "description": "consulta DICT (cancelada)",
    }

    async def _coro():
        async with get_client() as c:
            created = await c.create_transfer(payload)
            transfer_id = created.get("id")
            if transfer_id:
                try:
                    await c.cancel_transfer(transfer_id)
                except AsaasError:
                    pass  # cobrança DICT já foi lida; cancelar é best-effort
            return created

    try:
        return asyncio.run(_coro())
    except AsaasError as e:
        raise PixKeyError(f"dict_lookup_failed: {e.body}") from e


def validate_pix_key(*, key: str, key_type: str, expected_document: str) -> PixKey:
    """Valida a chave no DICT e confere que o titular é o `expected_document` (CPF do candidato).

    Persiste/atualiza o registro `PixKey`. Titular diferente / formato inválido / DICT fora → `PixKeyError`.
    """
    key = key.strip()
    key_type = normalize_key_type(key_type)
    expected = _only_digits(expected_document)
    if key_type not in VALID_KEY_TYPES:
        raise PixKeyError("invalid_key_type")
    if len(expected) not in (11, 14):
        raise PixKeyError("invalid_document_length")
    _basic_validate(key, key_type)

    if settings.TEST_EXTERNAL_ADAPTERS:
        from core.test_adapters import pix_dict_lookup

        raw = pix_dict_lookup(expected_document=expected)
    else:
        raw = _dict_lookup(key)
    bank_account = raw.get("bankAccount") or {}
    got_doc = (bank_account.get("cpfCnpj") or "").strip()
    if not _doc_matches(got_doc, expected):
        raise PixKeyError(f"holder_mismatch: expected {expected} got {got_doc}")

    bank_info = bank_account.get("bank") or {}
    row, _ = PixKey.objects.update_or_create(
        key=key,
        defaults={
            "key_type": key_type,
            # got_doc vem mascarado; como bate com o esperado, guardo o CPF completo do candidato.
            "holder_document": expected,
            "holder_name": bank_account.get("ownerName")
            or bank_account.get("accountName")
            or "",
            "bank_name": bank_info.get("name") or "",
            "raw_dict": raw,
        },
    )
    logger.info("asaas.pixkey_validated", key_type=key_type, holder_document=expected)
    return row
