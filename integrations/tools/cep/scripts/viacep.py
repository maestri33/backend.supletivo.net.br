"""Integração ViaCEP — lookup de CEP brasileiro (porte 1:1 do micro legado).

ViaCEP é API pública (sem api-key). Distingue dois casos:
- CEP inexistente / formato inválido  -> retorna None (o chamador decide).
- ViaCEP indisponível (rede / HTTP != 200) -> levanta ViaCepUnavailable.

Zero regra de negócio aqui: só a chamada externa e a normalização dos campos.
Config (base_url, timeout) vem do .env via settings (CONVENTION §8/§10).
"""

from __future__ import annotations

import re

import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()


class ViaCepUnavailable(Exception):
    """ViaCEP fora do ar (rede ou status != 200). Quem chama decide o que fazer."""


async def lookup(zipcode: str) -> dict | None:
    """Consulta a ViaCEP e devolve os campos normalizados.

    Retorna None se o CEP não existir ou tiver formato inválido. Levanta
    ViaCepUnavailable se a ViaCEP estiver indisponível (rede ou status != 200).

    Chaves de retorno (alinhadas ao futuro modelo `address`): zipcode, street,
    complement, neighborhood, city, state.
    """
    clean = re.sub(r"\D", "", zipcode or "")
    if len(clean) != 8:
        return None

    url = f"{settings.VIACEP_BASE_URL.rstrip('/')}/ws/{clean}/json/"
    try:
        async with httpx.AsyncClient(timeout=settings.VIACEP_TIMEOUT_SECONDS) as client:
            resp = await client.get(url)
    except httpx.RequestError as exc:
        logger.warning("viacep.request_failed", zipcode=clean)
        raise ViaCepUnavailable("ViaCEP indisponível no momento") from exc

    if resp.status_code != 200:
        logger.warning("viacep.bad_status", zipcode=clean, status=resp.status_code)
        raise ViaCepUnavailable(f"ViaCEP retornou status {resp.status_code}")

    data = resp.json()
    if data.get("erro"):
        return None

    return {
        "zipcode": clean,
        "street": data.get("logradouro") or None,
        "complement": data.get("complemento") or None,
        "neighborhood": data.get("bairro") or None,
        "city": data.get("localidade") or None,
        "state": data.get("uf") or None,
    }
