"""Schemathesis Spec-Driven Property-Based Fuzzing Test Suite."""
from pathlib import Path
import json
import pytest
import schemathesis
from django.conf import settings
from django.core.wsgi import get_wsgi_application
from hypothesis import settings as hypo_settings, Phase

# Garante hosts permitidos para execução do runner WSGI do Schemathesis
if "localhost" not in settings.ALLOWED_HOSTS:
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["localhost", "testserver", "127.0.0.1", "*"]

# Carrega a aplicação WSGI do Django
app = get_wsgi_application()

# Carrega o schema OpenAPI exportado
schema_file = Path(__file__).resolve().parents[2].parent / "packages" / "api-client" / "scripts" / "openapi.json"

with open(schema_file, "r", encoding="utf-8") as f:
    raw_schema = json.load(f)

schema = schemathesis.openapi.from_dict(raw_schema)


# Fuzzing de endpoints públicos e de saúde
@pytest.mark.django_db
@schema.include(path="/api/v1/health/healthz").parametrize()
@hypo_settings(max_examples=10, phases=[Phase.generate, Phase.shrink], deadline=None)
def test_health_api_fuzzing(case):
    """Testa robustez do endpoint /api/v1/health/healthz."""
    response = case.call(app=app)
    case.validate_response(response)


# Fuzzing de endpoints públicos de clientes
@pytest.mark.django_db
@schema.include(path="/api/v1/clients/pricing").parametrize()
@hypo_settings(max_examples=10, phases=[Phase.generate, Phase.shrink], deadline=None)
def test_pricing_api_fuzzing(case):
    """Testa robustez do endpoint /api/v1/clients/pricing."""
    response = case.call(app=app)
    case.validate_response(response)
