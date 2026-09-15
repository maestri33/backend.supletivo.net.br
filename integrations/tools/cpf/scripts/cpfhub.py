"""Integração CPFHub.io — lookup de identidade por CPF (porte do micro legado).

CPFHub exige api-key (header x-api-key) — server-side only (§8). Distingue (Portão 1 Q3):
- CPF não encontrado / formato inválido  -> retorna None (o chamador decide).
- CPFHub com erro real (rede, 401 key, 429 limite, 5xx após retry) -> levanta CpfHubError.

Zero regra de negócio aqui: só a chamada externa, retry em transitório e a normalização dos
campos. A validação de dígito verificador de CPF é regra de domínio (profiles) — não é daqui.
Config (api_key, base_url, timeout) vem do .env via settings (CONVENTION §8/§10).
Não loga CPF nem nome (PII) — só status/erro agregado (CONVENTION §12).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()

# Status HTTP transientes -> justificam retry (porte do legado).
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Backoff (s) entre tentativas; len = nº de retries -> 3 tentativas no total.
_RETRY_DELAYS = (0.2, 0.8)


class CpfHubError(Exception):
    """CPFHub com erro real (rede, 401, 429, 5xx). Quem chama decide o que fazer."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(message or f"CPFHub erro (status {status_code})")


@dataclass(frozen=True)
class CpfIdentity:
    """Identidade retornada pela CPFHub (campos opcionais — a API pode omitir)."""

    cpf: str
    name: str | None = None
    name_upper: str | None = None
    gender: str | None = None
    birth_date: date | None = None

    def as_dict(self) -> dict:
        """Serializa pro JSON (birth_date em ISO YYYY-MM-DD)."""
        return {
            "cpf": self.cpf,
            "name": self.name,
            "name_upper": self.name_upper,
            "gender": self.gender,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
        }


async def lookup(cpf: str) -> CpfIdentity | None:
    """Consulta a CPFHub e devolve a identidade normalizada.

    Retorna None se o CPF tiver formato inválido (≠ 11 dígitos) ou não for encontrado (404).
    Levanta CpfHubError se a CPFHub falhar de verdade (rede, 401 key, 429 limite, 5xx após retry).
    """
    from core.system_config import get_setting

    api_key = get_setting("CPFHUB_API_KEY", getattr(settings, "CPFHUB_API_KEY", ""))
    base_url = get_setting("CPFHUB_BASE_URL", getattr(settings, "CPFHUB_BASE_URL", "https://api.cpfhub.io"))

    if not api_key:
        raise CpfHubError(0, "CPFHUB_API_KEY ausente no .env")

    digits = re.sub(r"\D", "", cpf or "")
    if len(digits) != 11:
        logger.warning("cpfhub.invalid_format", digits_len=len(digits))
        return None

    url = f"{base_url.rstrip('/')}/cpf/{digits}"
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    resp: httpx.Response | None = None
    max_attempts = len(_RETRY_DELAYS) + 1

    async with httpx.AsyncClient(
        timeout=settings.CPFHUB_TIMEOUT, headers=headers
    ) as client:
        for attempt in range(max_attempts):
            try:
                resp = await client.get(url)
            except httpx.RequestError as exc:
                logger.warning(
                    "cpfhub.request_error", attempt=attempt, error=type(exc).__name__
                )
                if attempt + 1 < max_attempts:
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
                    continue
                raise CpfHubError(0, "CPFHub indisponível (rede)") from exc
            if resp.status_code in _RETRY_STATUSES and attempt + 1 < max_attempts:
                logger.warning(
                    "cpfhub.transient", attempt=attempt, status=resp.status_code
                )
                await asyncio.sleep(_RETRY_DELAYS[attempt])
                continue
            break

    if (
        resp is None
    ):  # nunca deveria ocorrer (o loop retorna ou levanta) — guarda defensiva
        raise CpfHubError(0, "CPFHub sem resposta")
    if resp.status_code == 404:
        logger.info("cpfhub.not_found")
        return None
    if resp.status_code != 200:
        # 401 (key inválida), 429 (limite), 5xx (após esgotar retry) -> erro real
        logger.warning("cpfhub.error_status", status=resp.status_code)
        raise CpfHubError(resp.status_code)

    body = _json_or_none(resp)
    if not isinstance(body, dict) or not body.get("success"):
        logger.info("cpfhub.unsuccessful")
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        return None
    return _parse_identity(digits, data)


def _parse_identity(cpf: str, data: dict) -> CpfIdentity:
    """Extrai os campos úteis do `data` da CPFHub (tolerante a ausência / tipo errado)."""
    name = data.get("name")
    name = name.strip() or None if isinstance(name, str) else None

    name_upper = data.get("nameUpper")
    name_upper = name_upper.strip() or None if isinstance(name_upper, str) else None

    gender = data.get("gender")
    gender = gender if gender in ("M", "F") else None

    birth_date: date | None = None
    day, month, year = data.get("day"), data.get("month"), data.get("year")
    if isinstance(day, int) and isinstance(month, int) and isinstance(year, int):
        try:
            birth_date = date(year, month, day)
        except ValueError:
            birth_date = None

    return CpfIdentity(
        cpf=cpf, name=name, name_upper=name_upper, gender=gender, birth_date=birth_date
    )


def _json_or_none(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None
