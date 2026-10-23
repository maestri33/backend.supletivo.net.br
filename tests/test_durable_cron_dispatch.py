from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from core import tasks

pytestmark = pytest.mark.django_db


def test_failed_queue_publish_never_executes_the_task_in_the_request(settings):
    settings.TASK_BACKEND = 'django_q'
    business_action = Mock()
    with patch('django_q.tasks.async_task', side_effect=RuntimeError('broker unavailable')):
        with pytest.raises(RuntimeError, match='broker unavailable'):
            tasks.async_task(business_action)
    business_action.assert_not_called()


def test_weekly_trigger_preserves_original_scheduled_instant(client, bot_headers):
    instant = datetime(2026, 10, 9, 21, tzinfo=timezone.utc)
    with patch('finance.tasks.weekly_closing', return_value={}) as closing:
        response = client.post('/api/v1/tools/cron/finance/weekly-closing', data={'scheduled_time': instant.isoformat()}, content_type='application/json', **bot_headers)
    assert response.status_code == 200
    closing.assert_called_once_with(reference_date=instant)


def test_weekly_closing_dispatches_due_repayments_immediately():
    from finance import tasks as financial_tasks
    with patch('finance.interface.commissions.run_weekly_closing', return_value={'payment_requests_created': 1}), patch('finance.interface.payout.process_payment_requests', return_value={'paid': 1}) as payouts:
        result = financial_tasks.weekly_closing()
    payouts.assert_called_once_with()
    assert result['payouts'] == {'paid': 1}


def test_cron_auth_reads_protected_platform_configuration(client, monkeypatch, settings):
    from core import webhook_auth, system_config
    settings.CRON_SERVICE_SECRET = ''
    settings.BOT_SERVICE_SECRET = ''
    monkeypatch.setattr(system_config, 'get_setting', lambda key, default=None: 'protected-cron-test' if key == 'CRON_SERVICE_SECRET' else default)
    with patch('finance.tasks.process_payouts', return_value={}):
        response = client.post('/api/v1/tools/cron/finance/payouts', HTTP_X_CRON_SECRET='protected-cron-test')
    assert response.status_code == 200


def test_future_or_naive_weekly_trigger_is_rejected(client, bot_headers):
    with patch('finance.tasks.weekly_closing') as closing:
        for instant in ('2999-10-09T21:00:00Z', '2026-10-09T21:00:00'):
            response = client.post('/api/v1/tools/cron/finance/weekly-closing', data={'scheduled_time': instant}, content_type='application/json', **bot_headers)
            assert response.status_code == 422
    closing.assert_not_called()
