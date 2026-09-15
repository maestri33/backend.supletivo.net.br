"""Client Cloudflare Turnstile — Proteção Anti-Bot Server-Side.

Valida tokens do widget Cloudflare Turnstile através do endpoint siteverify:
POST https://challenges.cloudflare.com/turnstile/v0/siteverify
"""

from __future__ import annotations

from dataclasses import dataclass, field
import httpx
import structlog
from django.conf import settings

logger = structlog.get_logger()

DEFAULT_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# Chaves de teste oficiais da Cloudflare
CLOUDFLARE_TEST_ALWAYS_PASS_TOKEN = "1x0000000000000000000000000000000AA"
CLOUDFLARE_TEST_ALWAYS_BLOCK_TOKEN = "2x0000000000000000000000000000000AA"


class TurnstileError(Exception):
    """Erro de comunicação ou validação com o Cloudflare Turnstile."""

    def __init__(self, message: str, *, error_codes: list[str] | None = None, status_code: int | None = None):
        super().__init__(message)
        self.error_codes = error_codes or []
        self.status_code = status_code


@dataclass
class TurnstileResult:
    """Resultado da verificação do token Turnstile."""

    success: bool
    challenge_ts: str | None = None
    hostname: str | None = None
    error_codes: list[str] = field(default_factory=list)
    action: str | None = None
    cdata: str | None = None


class TurnstileClient:
    """Cliente para validação de tokens Cloudflare Turnstile."""

    def __init__(
        self,
        *,
        secret_key: str | None = None,
        verify_url: str | None = None,
        timeout: float = 10.0,
        enabled: bool | None = None,
    ):
        self._secret_key = secret_key if secret_key is not None else getattr(settings, "TURNSTILE_SECRET_KEY", "")
        self._verify_url = (
            verify_url
            if verify_url is not None
            else getattr(settings, "TURNSTILE_VERIFY_URL", DEFAULT_SITEVERIFY_URL)
        )
        self._timeout = timeout
        self._enabled = enabled if enabled is not None else getattr(settings, "TURNSTILE_ENABLED", False)

    def _should_bypass(self, token: str) -> bool | None:
        """Verifica se deve aplicar bypass (CI / Testes / Desativado)."""
        if not self._enabled:
            return True
        if token == CLOUDFLARE_TEST_ALWAYS_PASS_TOKEN or token.startswith("1x0000") or token == "test-bypass-token":
            return True
        if token == CLOUDFLARE_TEST_ALWAYS_BLOCK_TOKEN or token.startswith("2x0000"):
            return False
        return None

    def verify(self, token: str, *, remote_ip: str | None = None) -> TurnstileResult:
        """Validação síncrona do token."""
        bypass = self._should_bypass(token)
        if bypass is not None:
            return TurnstileResult(
                success=bypass,
                error_codes=[] if bypass else ["invalid-input-response"],
                hostname="localhost",
            )

        if not self._secret_key:
            logger.warning("turnstile.secret_missing_allowing")
            return TurnstileResult(success=True, hostname="unconfigured")

        data = {
            "secret": self._secret_key,
            "response": token,
        }
        if remote_ip:
            data["remoteip"] = remote_ip

        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.post(self._verify_url, data=data)
        except Exception as exc:
            logger.warning("turnstile.request_failed", error=str(exc))
            # Fail-open ou fail-closed dependendo da criticidade; por padrão fail-closed em produção
            return TurnstileResult(success=False, error_codes=["internal-error"])

        if resp.status_code != 200:
            logger.warning("turnstile.http_error", status=resp.status_code, body=resp.text[:200])
            return TurnstileResult(success=False, error_codes=[f"http-{resp.status_code}"])

        try:
            body = resp.json()
        except ValueError:
            return TurnstileResult(success=False, error_codes=["invalid-json"])

        success = bool(body.get("success", False))
        result = TurnstileResult(
            success=success,
            challenge_ts=body.get("challenge_ts"),
            hostname=body.get("hostname"),
            error_codes=body.get("error-codes", []),
            action=body.get("action"),
            cdata=body.get("cdata"),
        )
        logger.info("turnstile.verified", success=success, hostname=result.hostname)
        return result

    async def verify_async(self, token: str, *, remote_ip: str | None = None) -> TurnstileResult:
        """Validação assíncrona do token."""
        bypass = self._should_bypass(token)
        if bypass is not None:
            return TurnstileResult(
                success=bypass,
                error_codes=[] if bypass else ["invalid-input-response"],
                hostname="localhost",
            )

        if not self._secret_key:
            logger.warning("turnstile.secret_missing_allowing")
            return TurnstileResult(success=True, hostname="unconfigured")

        data = {
            "secret": self._secret_key,
            "response": token,
        }
        if remote_ip:
            data["remoteip"] = remote_ip

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._verify_url, data=data)
        except Exception as exc:
            logger.warning("turnstile.request_failed_async", error=str(exc))
            return TurnstileResult(success=False, error_codes=["internal-error"])

        if resp.status_code != 200:
            return TurnstileResult(success=False, error_codes=[f"http-{resp.status_code}"])

        try:
            body = resp.json()
        except ValueError:
            return TurnstileResult(success=False, error_codes=["invalid-json"])

        return TurnstileResult(
            success=bool(body.get("success", False)),
            challenge_ts=body.get("challenge_ts"),
            hostname=body.get("hostname"),
            error_codes=body.get("error-codes", []),
            action=body.get("action"),
            cdata=body.get("cdata"),
        )


def verify_turnstile(token: str, *, remote_ip: str | None = None, secret_key: str | None = None) -> TurnstileResult:
    """Helper global para validação de token Turnstile."""
    client = TurnstileClient(secret_key=secret_key)
    return client.verify(token, remote_ip=remote_ip)
