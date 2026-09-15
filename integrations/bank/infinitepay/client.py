"""Camada HTTP fina e isolada sobre a API de Checkout da InfinitePay (porte do micro legado).

Regras (CONVENTION §8/§10):
 - base_url vem do .env via settings: https://api.checkout.infinitepay.io (API de Checkout atual). Os
   paths são /links e /payment_check. O endpoint antigo (api.infinitepay.io/invoices/public/checkout/*)
   foi descontinuado — mesma lógica, só a URL mudou.
 - SEM auth / SEM api-key: a InfinitePay autentica só pelo `handle` (InfiniteTag) — quem recebe é o dono
   da conta, então não há segredo a proteger no envio (palavra do Victor + doc oficial).
 - Zero regra de negócio aqui. Cada função mapeia 1:1 um endpoint.
 - Levanta InfinitePayError em não-2xx ou success=false (quem chama decide o que fazer).
 - I/O async (httpx.AsyncClient) pra não bloquear — mesmo padrão do client do asaas.
"""

from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings


class InfinitePayError(Exception):
    def __init__(
        self, message: str, *, payload: Any = None, status_code: int | None = None
    ):
        super().__init__(message)
        self.payload = payload
        self.status_code = status_code


class InfinitePayClient:
    def __init__(self, *, base_url: str | None = None, timeout: float | None = None):
        self._client = httpx.AsyncClient(
            base_url=base_url or settings.INFINITEPAY_BASE_URL,
            headers={
                "User-Agent": "infinitepay-app/1.0",
                "Content-Type": "application/json",
            },
            timeout=timeout or settings.INFINITEPAY_HTTP_TIMEOUT,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        await self.aclose()

    async def _post(self, path: str, json: dict) -> Any:
        r = await self._client.post(path, json=json)
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}
        if r.status_code >= 400:
            raise InfinitePayError(
                f"HTTP {r.status_code} from InfinitePay {path}",
                payload=data,
                status_code=r.status_code,
            )
        return data

    # ---------- checkout ----------
    async def create_checkout_link(self, payload: dict) -> dict:
        """POST /links — gera o link de pagamento. Valida que veio uma URL de checkout."""
        data = await self._post("/links", payload)
        if data.get("success") is False:
            raise InfinitePayError("InfinitePay returned success=false", payload=data)
        if not (data.get("url") or data.get("checkout_url") or data.get("link")):
            raise InfinitePayError(
                "InfinitePay response missing checkout URL", payload=data
            )
        return data

    async def payment_check(
        self, *, handle: str, order_nsu: str, transaction_nsu: str, slug: str
    ) -> dict:
        """POST /payment_check — reconfirma o pagamento out-of-band (a trava real do webhook)."""
        return await self._post(
            "/payment_check",
            {
                "handle": handle,
                "order_nsu": order_nsu,
                "transaction_nsu": transaction_nsu,
                "slug": slug,
            },
        )


def get_client() -> InfinitePayClient:
    """Constrói o client com base_url/timeout do .env (config via settings — CONVENTION §10)."""
    return InfinitePayClient()
