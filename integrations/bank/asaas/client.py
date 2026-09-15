"""Camada HTTP fina e isolada sobre a API do Asaas (porte 1:1 do micro legado).

Regras:
 - base_url vem do .env via settings (CONVENTION §10): https://api.asaas.com (prod) ou
   https://api-sandbox.asaas.com (sandbox). O cliente prefixa /v3/ em cada path.
 - Zero regra de negócio aqui. Cada função mapeia 1:1 um endpoint do Asaas.
 - Levanta AsaasError em qualquer não-2xx (quem chama decide o que fazer).
 - I/O async (httpx.AsyncClient) pra não bloquear: o validador e o worker têm prazo curto.
"""

from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings


class AsaasError(Exception):
    def __init__(self, status_code: int, body: Any, message: str = ""):
        self.status_code = status_code
        self.body = body
        super().__init__(message or f"Asaas HTTP {status_code}: {body!r}")


class AsaasClient:
    # default 10s: a charge PIX roda DENTRO do request do register — timeout alto = stall do serviço
    # inteiro (auditoria do front 2026-06-10). A API do Asaas responde em ~1-2s; o money-path (payout)
    # já trata falha incerta sem re-submeter.
    def __init__(
        self, api_key: str, *, base_url: str | None = None, timeout: float = 10.0
    ):
        if not api_key:
            raise ValueError("api_key is required")
        self._client = httpx.AsyncClient(
            base_url=base_url or settings.ASAAS_BASE_URL,
            headers={
                "access_token": api_key,
                "User-Agent": "asaas-app/1.0",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        await self.aclose()

    # ---------- low-level ----------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Any = None,
        idempotency_key: str | None = None,
    ) -> Any:
        # Idempotency-Key: o Asaas guarda a chave só em respostas de sucesso (confirmado em
        # sandbox). Um POST repetido com a mesma chave de um recurso já criado recebe HTTP 409
        # — nunca duplica; já respostas de erro (4xx) não gravam a chave, então um pagamento
        # que falhou (saldo, chave inválida) pode ser re-tentado normalmente.
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        r = await self._client.request(
            method, path, json=json, params=params, headers=headers
        )
        if r.status_code == 204 or not r.content:
            data: Any = None
        else:
            try:
                data = r.json()
            except ValueError:
                data = r.text
        if r.status_code >= 400:
            raise AsaasError(r.status_code, data)
        return data

    # ---------- account ----------
    async def get_my_account(self) -> dict:
        # /v3/myAccount retorna o perfil da carteira autenticada.
        return await self._request("GET", "/v3/myAccount")

    async def get_balance(self) -> dict:
        return await self._request("GET", "/v3/finance/balance")

    # ---------- webhooks ----------
    async def list_webhooks(self) -> dict:
        return await self._request("GET", "/v3/webhooks")

    async def create_webhook(self, payload: dict) -> dict:
        return await self._request("POST", "/v3/webhooks", json=payload)

    async def delete_webhook(self, webhook_id: str) -> Any:
        return await self._request("DELETE", f"/v3/webhooks/{webhook_id}")

    # ---------- PIX address keys & static QR Code inbound (recebimento direto) ----------
    async def list_pix_address_keys(self, params: dict | None = None) -> dict:
        """Lista as chaves PIX cadastradas na conta Asaas."""
        return await self._request("GET", "/v3/pix/addressKeys", params=params)

    async def get_pix_address_key(self, key_id: str) -> dict:
        return await self._request("GET", f"/v3/pix/addressKeys/{key_id}")

    async def create_static_qr_code(self, payload: dict) -> dict:
        """Cria um QR Code estático / direto com valor definido (baixo custo transacional)."""
        return await self._request("POST", "/v3/pix/qrCodes/static", json=payload)

    async def delete_static_qr_code(self, qr_id: str) -> Any:
        """Remove / cancela um QR Code estático."""
        return await self._request("DELETE", f"/v3/pix/qrCodes/static/{qr_id}")

    # ---------- transfers (PIX out) ----------
    async def create_transfer(
        self, payload: dict, *, idempotency_key: str | None = None
    ) -> dict:
        return await self._request(
            "POST", "/v3/transfers", json=payload, idempotency_key=idempotency_key
        )

    async def cancel_transfer(self, transfer_id: str) -> Any:
        return await self._request("POST", f"/v3/transfers/{transfer_id}/cancel")

    # ---------- PIX QR Code outbound (copia-e-cola, pagando) ----------
    async def decode_qr_code(self, payload: str) -> dict:
        # Decodifica um BR Code no Asaas (resolve o payload dinâmico de cobrança no servidor deles).
        # Campos úteis: type, value, totalValue, dueDate, canBePaid, cannotBePaidReason, receiver.
        # dueDate=None para QR estático/imediato.
        return await self._request(
            "POST", "/v3/pix/qrCodes/decode", json={"payload": payload}
        )

    async def pay_qr_code(
        self,
        payload: str,
        value: float,
        description: str | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        body: dict = {
            "qrCode": {"payload": payload},
            "value": round(float(value), 2),
        }
        if description:
            body["description"] = description
        return await self._request(
            "POST", "/v3/pix/qrCodes/pay", json=body, idempotency_key=idempotency_key
        )

    # ---------- bill payments (boleto / conta de consumo, OUTBOUND) ----------
    async def pay_bill(
        self, payload: dict, *, idempotency_key: str | None = None
    ) -> dict:
        # Paga um boleto/conta pela linha digitável (`identificationField`) ou código de barras
        # (`barCode`). Campos úteis no retorno: id, status, value, dueDate.
        return await self._request(
            "POST", "/v3/bill", json=payload, idempotency_key=idempotency_key
        )

    async def get_bill(self, bill_id: str) -> dict:
        return await self._request("GET", f"/v3/bill/{bill_id}")

    # ---------- PIX transactions (outbound) ----------
    async def get_pix_transaction(self, transaction_id: str) -> dict:
        return await self._request("GET", f"/v3/pix/transactions/{transaction_id}")

    # ---------- customers ----------
    async def create_customer(self, payload: dict) -> dict:
        return await self._request("POST", "/v3/customers", json=payload)

    async def list_customers(self, params: dict | None = None) -> dict:
        return await self._request("GET", "/v3/customers", params=params)

    # ---------- payments (cobranças inbound) ----------
    async def create_payment(self, payload: dict) -> dict:
        return await self._request("POST", "/v3/payments", json=payload)

    async def get_payment(self, payment_id: str) -> dict:
        return await self._request("GET", f"/v3/payments/{payment_id}")

    async def list_payments(self, params: dict | None = None) -> dict:
        return await self._request("GET", "/v3/payments", params=params)

    async def delete_payment(self, payment_id: str) -> Any:
        return await self._request("DELETE", f"/v3/payments/{payment_id}")

    async def refund_payment(
        self, payment_id: str, payload: dict | None = None
    ) -> dict:
        return await self._request(
            "POST", f"/v3/payments/{payment_id}/refund", json=payload or {}
        )

    async def get_payment_pix_qr_code(self, payment_id: str) -> dict:
        """BR Code (copia-e-cola) + PNG base64 da cobrança PIX."""
        return await self._request("GET", f"/v3/payments/{payment_id}/pixQrCode")

    async def get_payment_identification_field(self, payment_id: str) -> dict:
        """Linha digitável e código de barras da cobrança boleto."""
        return await self._request(
            "GET", f"/v3/payments/{payment_id}/identificationField"
        )

    # ---------- credit card (tokenização / pagamento) ----------
    async def tokenize_credit_card(self, payload: dict) -> dict:
        return await self._request("POST", "/v3/creditCard/tokenize", json=payload)

    async def pay_with_credit_card(self, payment_id: str, payload: dict) -> dict:
        return await self._request(
            "POST", f"/v3/payments/{payment_id}/payWithCreditCard", json=payload
        )

    # ---------- financial transactions / extrato ----------
    async def get_financial_transactions(self, params: dict | None = None) -> dict:
        return await self._request("GET", "/v3/financialTransactions", params=params)


def get_client() -> AsaasClient:
    """Constrói o client com a key/base_url do .env ou PlatformSetting (config via settings — CONVENTION §10)."""
    from core.system_config import get_setting

    key = get_setting("ASAAS_API_KEY", getattr(settings, "ASAAS_API_KEY", ""))
    return AsaasClient(key)

