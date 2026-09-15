from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import ImproperlyConfigured


VALID_APP_ENVS = frozenset({"prod", "staging", "preview", "test"})


@dataclass(frozen=True)
class EnvironmentConfig:
    app_env: str
    test_mode: bool


def resolve_external_fakes(*, app_env: str, requested: bool) -> bool:
    if requested and app_env == "prod":
        raise ImproperlyConfigured(
            "TEST_EXTERNAL_ADAPTERS=1 é proibido em APP_ENV=prod."
        )
    return requested


def resolve_environment(
    *,
    app_env: str,
    legacy_test_mode: bool,
    hostname: str,
    allowed_test_hosts: list[str],
) -> EnvironmentConfig:
    normalized = app_env.strip().lower()
    if normalized not in VALID_APP_ENVS:
        allowed = ", ".join(sorted(VALID_APP_ENVS))
        raise ImproperlyConfigured(
            f"APP_ENV={app_env!r} inválido; use um de: {allowed}."
        )

    test_mode = normalized != "prod"
    if legacy_test_mode and not test_mode:
        raise ImproperlyConfigured(
            "TEST_MODE=1 é incompatível com APP_ENV=prod. Use APP_ENV=test, preview ou staging."
        )
    if test_mode and "*" not in allowed_test_hosts and hostname not in allowed_test_hosts:
        raise ImproperlyConfigured(
            f"APP_ENV={normalized!r} recusado: hostname {hostname!r} não está em "
            f"TEST_MODE_ALLOWED_HOSTS={allowed_test_hosts}."
        )
    return EnvironmentConfig(app_env=normalized, test_mode=test_mode)
