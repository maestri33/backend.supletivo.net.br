"""Erros de domínio do app `users`, com o status HTTP que a view DMZ devolve.

A lógica (auth/roles/otp) levanta estes; `users/auth/views.py` converte em JSON
`{"detail", "code"}` no status certo. Mantém a lógica sem saber de HTTP (CONVENTION §1/§3).
"""

from __future__ import annotations


class DomainError(Exception):
    """Base. `status` = HTTP a devolver; `code` = código curto pro front; `extra` = contexto."""

    status = 400

    def __init__(self, detail: str, *, code: str = "ERROR", extra: dict | None = None):
        super().__init__(detail)
        self.detail = detail
        self.code = code
        self.extra = extra or {}


class ValidationError(DomainError):
    status = 422


class Conflict(DomainError):
    status = 409


class NotFound(DomainError):
    status = 404


class Forbidden(DomainError):
    status = 403


class Unauthorized(DomainError):
    status = 401


class IntegrationError(DomainError):
    """Serviço externo (CPFHub, WhatsApp) indisponível/erro real — não é culpa do cliente."""

    status = 502


class RateLimited(DomainError):
    status = 429

    def __init__(self, detail: str, *, retry_after_s: int, code: str = "RATE_LIMITED"):
        super().__init__(detail, code=code, extra={"retry_after_s": retry_after_s})
        self.retry_after_s = retry_after_s
