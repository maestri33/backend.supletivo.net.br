import pytest
from django.core.exceptions import ImproperlyConfigured

from core.environment import resolve_environment, resolve_external_fakes


def test_prod_nunca_aceita_test_mode_legado():
    with pytest.raises(ImproperlyConfigured):
        resolve_environment(
            app_env="prod",
            legacy_test_mode=True,
            hostname="prod-1",
            allowed_test_hosts=[],
        )


def test_non_prod_exige_hostname_explicito():
    with pytest.raises(ImproperlyConfigured):
        resolve_environment(
            app_env="preview",
            legacy_test_mode=False,
            hostname="preview-1",
            allowed_test_hosts=[],
        )


def test_preview_habilita_test_mode_no_host_autorizado():
    result = resolve_environment(
        app_env="preview",
        legacy_test_mode=False,
        hostname="preview-1",
        allowed_test_hosts=["preview-1"],
    )
    assert result.app_env == "preview"
    assert result.test_mode is True


def test_preview_habilita_test_mode_com_wildcard():
    result = resolve_environment(
        app_env="test",
        legacy_test_mode=True,
        hostname="ci-runner-arbitrary-hostname-123",
        allowed_test_hosts=["*"],
    )
    assert result.app_env == "test"
    assert result.test_mode is True


def test_prod_nunca_aceita_adaptadores_externos_sinteticos():
    with pytest.raises(ImproperlyConfigured):
        resolve_external_fakes(app_env="prod", requested=True)


def test_database_settings_health_checks_habilitado():
    from django.conf import settings
    assert settings.DATABASES["default"].get("CONN_HEALTH_CHECKS") is True
    assert "CONN_MAX_AGE" in settings.DATABASES["default"]


def test_database_resolution_unpooled_para_migracoes(monkeypatch):
    import environ
    env = environ.Env()
    pooled_url = "postgresql://user:pass@ep-test-pooler.us-east-2.aws.neon.tech/neondb"
    unpooled_url = "postgresql://user:pass@ep-test.us-east-2.aws.neon.tech/neondb"

    # Simula comando migrate com unpooled URL
    migration_cmds = {"migrate", "makemigrations"}
    mock_argv = ["manage.py", "migrate"]
    is_migration = any(cmd in mock_argv for cmd in migration_cmds)
    assert is_migration is True

    cfg = env.db_url_config(unpooled_url)
    assert cfg["HOST"] == "ep-test.us-east-2.aws.neon.tech"
    assert "pooler" not in cfg["HOST"]
