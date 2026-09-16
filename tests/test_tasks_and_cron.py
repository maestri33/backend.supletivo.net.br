import pytest
from unittest.mock import patch, MagicMock
from core import tasks

pytestmark = pytest.mark.django_db


def dummy_sync_task(x, y):
    return x + y


def dummy_hook(result):
    pass


def test_tasks_facade_sync_execution(settings):
    settings.TASK_BACKEND = "sync"
    res = tasks.async_task(dummy_sync_task, 10, 20)
    assert res == 30


def test_tasks_facade_threads_execution(settings):
    settings.TASK_BACKEND = "threads"
    fut = tasks.async_task(dummy_sync_task, 5, 15)
    assert fut.result(timeout=2.0) == 20


def test_tasks_facade_django_q_fallback(settings):
    settings.TASK_BACKEND = "django_q"
    # Quando django_q.tasks.async_task funciona:
    with patch("django_q.tasks.async_task", return_value="task-uuid-123") as mock_dq:
        res = tasks.async_task("tests.test_tasks_and_cron.dummy_sync_task", 1, 2)
        assert res == "task-uuid-123"
        assert mock_dq.called


def test_cron_registry_and_run_cron_job():
    assert "finance_weekly_closing" in tasks.CRON_REGISTRY
    assert "finance_payouts" in tasks.CRON_REGISTRY
    assert "all_age_stale_selfies" in tasks.CRON_REGISTRY

    with patch("finance.tasks.weekly_closing", return_value={"closed": 5}) as mock_fn:
        res = tasks.run_cron_job("finance_weekly_closing")
        assert res["status"] == "success"
        assert res["result"] == {"closed": 5}
        assert res["elapsed_ms"] >= 0
        assert mock_fn.called


def test_cron_jobs_list_endpoint(client, bot_headers):
    # Sem auth -> 401
    resp_unauth = client.get("/api/v1/tools/cron/jobs")
    assert resp_unauth.status_code == 401

    # Com auth -> 200
    resp = client.get("/api/v1/tools/cron/jobs", **bot_headers)
    assert resp.status_code == 200
    jobs = {item["job"] for item in resp.json()}
    assert "finance_weekly_closing" in jobs
    assert "finance_payouts" in jobs
    assert "all_age_stale_selfies" in jobs


def test_cron_trigger_weekly_closing_endpoint(client, bot_headers):
    with patch("finance.tasks.weekly_closing", return_value={"batch_id": 123}):
        resp = client.post("/api/v1/tools/cron/finance/weekly-closing", **bot_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job"] == "finance_weekly_closing"
        assert data["status"] == "success"
        assert data["result"] == {"batch_id": 123}


def test_cron_trigger_payouts_endpoint(client, bot_headers):
    with patch("finance.tasks.process_payouts", return_value={"processed": 2}):
        resp = client.post("/api/v1/tools/cron/finance/payouts", **bot_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job"] == "finance_payouts"
        assert data["status"] == "success"


def test_cron_trigger_selfies_endpoint(client, bot_headers):
    with patch("users.roles.candidate.tasks.age_stale_selfies", return_value=1), \
         patch("users.roles.enrollment.tasks.age_stale_selfies", return_value=0):
        resp = client.post("/api/v1/tools/cron/selfies/age-stale", **bot_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job"] == "all_age_stale_selfies"
        assert data["status"] == "success"
        assert data["result"] == {"candidate": 1, "enrollment": 0}


def test_cron_run_job_invalid(client, bot_headers):
    resp = client.post("/api/v1/tools/cron/run/job_que_nao_existe", **bot_headers)
    assert resp.status_code == 409 or resp.status_code == 422
    assert "INVALID_JOB" in resp.text
