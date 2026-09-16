"""Camada unificada de despacho assíncrono e agendamentos (facade).

Desacopla os serviços de negócio da dependência direta de broker específico (django-q2).
Permite chavear entre backends via `settings.TASK_BACKEND`:
- "django_q": despacho padrão via django_q.tasks.async_task
- "sync": execução síncrona imediata (ideal para testes locais e pipelines determinísticos)
- "threads": execução assíncrona em ThreadPool (leve, zero-dependency, sem necessidade de qcluster 24/7)

Também define o `CRON_REGISTRY` e `run_cron_job`, permitindo que Cloudflare Cron Triggers
(ou chamadas HTTP autenticadas de cron) substituam os processos de scheduler 24/7 do Django-Q.
"""

from __future__ import annotations

import importlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import structlog
from django.conf import settings

logger = structlog.get_logger()

_thread_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ThreadPoolExecutor:
    global _thread_pool
    if _thread_pool is not None:
        return _thread_pool
    with _pool_lock:
        if _thread_pool is not None:
            return _thread_pool
        max_workers = int(getattr(settings, "TASK_POOL_WORKERS", 4))
        _thread_pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="bg-task-"
        )
        return _thread_pool


def resolve_callable(func: str | Callable) -> Callable:
    """Resolve uma função ou caminho string 'pacote.modulo.funcao' em callable executável."""
    if callable(func):
        return func
    if isinstance(func, str):
        if "." not in func:
            raise ValueError(f"Caminho de função inválido: {func}")
        mod_name, fn_name = func.rsplit(".", 1)
        mod = importlib.import_module(mod_name)
        return getattr(mod, fn_name)
    raise TypeError(f"Esperado str ou callable, recebido: {type(func)}")


def async_task(func: str | Callable, *args: Any, **kwargs: Any) -> Any:
    """Despacha uma tarefa assíncrona respeitando settings.TASK_BACKEND."""
    backend = getattr(settings, "TASK_BACKEND", "django_q")

    # Extrai hook se fornecido
    q_hook = kwargs.pop("hook", None)
    q_options = kwargs.pop("q_options", None)

    if backend == "sync":
        fn = resolve_callable(func)
        try:
            res = fn(*args, **kwargs)
            if q_hook:
                resolve_callable(q_hook)(res)
            return res
        except Exception as exc:
            logger.exception("task.sync_failed", func=str(func), error=str(exc))
            raise

    elif backend == "threads":
        pool = _get_pool()
        fn = resolve_callable(func)

        def _run():
            from django.db import close_old_connections

            close_old_connections()
            try:
                res = fn(*args, **kwargs)
                if q_hook:
                    resolve_callable(q_hook)(res)
                return res
            except Exception as exc:
                logger.exception("task.thread_failed", func=str(func), error=str(exc))
                raise
            finally:
                close_old_connections()

        return pool.submit(_run)

    else:
        # Padrão: django_q
        try:
            from django_q.tasks import async_task as dq_async_task

            if q_hook:
                kwargs["hook"] = q_hook
            if q_options:
                kwargs["q_options"] = q_options
            return dq_async_task(func, *args, **kwargs)
        except (ImportError, Exception) as exc:
            logger.warning(
                "task.django_q_fallback_to_sync",
                func=str(func),
                error=str(exc),
            )
            fn = resolve_callable(func)
            return fn(*args, **kwargs)


def schedule(name_or_func: str | Callable, *args: Any, **kwargs: Any) -> Any:
    """Agenda execução de tarefa respeitando settings.TASK_BACKEND.

    Se TASK_BACKEND == 'django_q', delega para django_q.tasks.schedule.
    Em outros backends ('threads' / 'sync'), executa após delay se especificado,
    ou delega para async_task.
    """
    backend = getattr(settings, "TASK_BACKEND", "django_q")
    if backend == "django_q":
        try:
            from django_q.tasks import schedule as dq_schedule

            return dq_schedule(name_or_func, *args, **kwargs)
        except ImportError:
            pass

    next_run = kwargs.get("next_run")
    delay_s = 0.0
    if next_run:
        from django.utils import timezone

        diff = (next_run - timezone.now()).total_seconds()
        if diff > 0:
            delay_s = diff

    if backend == "threads" and delay_s > 0:
        def _delayed():
            time.sleep(delay_s)
            async_task(name_or_func, *args)

        t = threading.Thread(target=_delayed, daemon=True)
        t.start()
        return t

    return async_task(name_or_func, *args)


# Registro de tarefas permitidas para execução via Cron Trigger (Cloudflare-first)
CRON_REGISTRY: dict[str, dict[str, Any]] = {
    "finance_weekly_closing": {
        "func": "finance.tasks.weekly_closing",
        "description": "Fechamento semanal financeiro e criação de solicitações de pagamento",
    },
    "finance_payouts": {
        "func": "finance.tasks.process_payouts",
        "description": "Processamento e conciliação de pagamentos Pix pendentes",
    },
    "candidate_age_stale_selfies": {
        "func": "users.roles.candidate.tasks.age_stale_selfies",
        "description": "Envelhecimento de selfies pendentes de candidatos estouradas (TTL)",
    },
    "enrollment_age_stale_selfies": {
        "func": "users.roles.enrollment.tasks.age_stale_selfies",
        "description": "Envelhecimento de selfies pendentes de matrículas estouradas (TTL)",
    },
    "all_age_stale_selfies": {
        "func": None,  # Executa ambos em sequência
        "description": "Envelhecimento de selfies pendentes em todas as roles (candidato e matrícula)",
    },
}


def run_cron_job(job_name: str) -> dict[str, Any]:
    """Executa um job agendado do CRON_REGISTRY com medição de latência e log estruturado."""
    if job_name not in CRON_REGISTRY:
        raise ValueError(
            f"Job '{job_name}' não registrado. Válidos: {list(CRON_REGISTRY.keys())}"
        )

    meta = CRON_REGISTRY[job_name]
    start_time = time.monotonic()
    logger.info("cron.job_started", job=job_name)

    try:
        if job_name == "all_age_stale_selfies":
            fn_cand = resolve_callable("users.roles.candidate.tasks.age_stale_selfies")
            fn_enr = resolve_callable("users.roles.enrollment.tasks.age_stale_selfies")
            res_cand = fn_cand()
            res_enr = fn_enr()
            result = {"candidate": res_cand, "enrollment": res_enr}
        else:
            fn = resolve_callable(meta["func"])
            result = fn()

        elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
        logger.info("cron.job_finished", job=job_name, elapsed_ms=elapsed_ms)
        return {
            "job": job_name,
            "status": "success",
            "elapsed_ms": elapsed_ms,
            "result": result,
        }
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - start_time) * 1000, 2)
        logger.exception("cron.job_failed", job=job_name, error=str(exc), elapsed_ms=elapsed_ms)
        return {
            "job": job_name,
            "status": "failure",
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
        }
