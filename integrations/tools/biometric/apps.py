from django.apps import AppConfig


class BiometricConfig(AppConfig):
    name = "integrations.tools.biometric"
    label = "biometric"

    def ready(self):
        # Registra o system check (só AVISA, não trava o boot — biometria é apoio do funil).
        from django.core.checks import register

        from .checks import check_biometric

        register(check_biometric)
