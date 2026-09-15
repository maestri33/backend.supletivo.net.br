from django.apps import AppConfig


class CepConfig(AppConfig):
    # Tool de CEP (ViaCEP). API pública, sem api-key e sem models — por isso não há
    # system check de credencial nem migração (diferente do asaas).
    name = "integrations.tools.cep"
    label = "cep"
