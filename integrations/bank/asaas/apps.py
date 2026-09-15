import os
import sys
import threading
import time

from django.apps import AppConfig


class AsaasConfig(AppConfig):
    name = "integrations.bank.asaas"
    label = "asaas"

    def ready(self):
        # Registra os system checks de env no boot. Rodam em todo runserver/manage, então "ficam
        # printando" enquanto faltar env essencial (E001 = api-key trava; W001 = webhook-secret avisa).
        from django.core.checks import register

        from .checks import check_asaas_env, check_asaas_webhook_secret

        register(check_asaas_env)
        register(check_asaas_webhook_secret)

        # Bateria de testes + auto-cadastro do webhook em TODO boot (1a-v), NÃO-bloqueante.
        self._maybe_enqueue_selftest()

    def _maybe_enqueue_selftest(self):
        """Enfileira a bateria (onboarding.boot_selftest) como task do Django-Q — NÃO roda inline.

        Antes a bateria rodava direto numa thread daemon do boot; como ela faz I/O de rede via
        asyncio.run(), sob o qcluster quebrava com `RuntimeError: cannot schedule new futures after
        interpreter shutdown` (o executor padrão do asyncio recusa futures quando o processo entra em
        shutdown) e o webhook nunca era cadastrado. Agora um WORKER do Django-Q roda a bateria em
        contexto estável (mesmo padrão provado de payout/charge/qrpay) -> o auto-cadastro funciona
        sozinho, inclusive em prod (gunicorn + qcluster), onde a thread antiga nem disparava. O
        qcluster fica SEMPRE no ar junto com o app (regra do Victor), então a fila sempre tem quem rode.

        A thread aqui faz SÓ o enfileiramento (um INSERT síncrono na fila — sem asyncio), então NÃO
        repete a corrida de shutdown da thread antiga. Enfileirar fora do ready() também evita o
        warning do Django de "acessar o banco durante o app-init" (o INSERT espera o registro de apps).

        Só quando o comando é "subir o servidor" (runserver/qcluster) — pula migrate/test/shell/etc.,
        que não devem falar com o Asaas. Sob o autoreload do runserver, ready() roda 2x (launcher +
        worker): enfileira só no worker (RUN_MAIN == "true"). `setup()` é idempotente -> enfileirar 2x
        não recria o webhook.
        """
        argv = sys.argv
        if not any(cmd in argv for cmd in ("runserver", "qcluster")):
            return
        reloader_launcher = (
            "runserver" in argv
            and "--noreload" not in argv
            and os.environ.get("RUN_MAIN") != "true"
        )
        if reloader_launcher:
            return
        threading.Thread(
            target=self._enqueue_selftest, name="asaas-enqueue-selftest", daemon=True
        ).start()

    def _enqueue_selftest(self):
        """Espera o registro de apps terminar e enfileira a task do boot. Falha de enfileiramento só
        loga — nunca derruba o processo."""
        import structlog
        from django.apps import apps as django_apps

        logger = structlog.get_logger()
        # deixa o app-init terminar antes de tocar no banco (django_apps.ready == True após os ready())
        for _ in range(50):
            if django_apps.ready:
                break
            time.sleep(0.1)
        try:
            from django_q.tasks import async_task

            async_task("integrations.bank.asaas.onboarding.boot_selftest")
        except Exception as exc:  # enfileirar nunca derruba o boot
            logger.error("asaas_boot_selftest_enqueue_failed", error=str(exc))
