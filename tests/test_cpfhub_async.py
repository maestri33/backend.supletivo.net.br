from datetime import timedelta, date
from unittest.mock import AsyncMock
import pytest
from django.utils import timezone
from users.auth.models import User, CpfHubLookup
from users.profiles.models import Profile
from users.auth import tasks, service
from integrations.tools.cpf.scripts import cpfhub

pytestmark = pytest.mark.django_db


def owner():
    user = User.objects.create_user()
    Profile.objects.create(user=user, phone='5541999991234', cpf='09126367939')
    return user


def test_request_enqueues_without_calling_provider(settings, monkeypatch, django_capture_on_commit_callbacks):
    settings.TEST_MODE = False
    provider = AsyncMock(side_effect=AssertionError('HTTP caller must never reach provider'))
    monkeypatch.setattr(cpfhub, 'lookup', provider)
    queued = []
    monkeypatch.setattr('django_q.tasks.async_task', lambda *a, **k: queued.append(a))
    with django_capture_on_commit_callbacks(execute=True):
        assert service._lookup_cpf('09126367939') is None
        assert service._lookup_cpf('09126367939') is None
    assert len(queued) == 1
    assert provider.call_count == 0
    assert CpfHubLookup.objects.count() == 1


def test_unlimited_retry_then_success(settings, monkeypatch):
    settings.TEST_MODE = False
    user = owner()
    job = CpfHubLookup.objects.create(user=user, cpf='09126367939', attempts=999)
    monkeypatch.setattr(cpfhub, 'lookup', AsyncMock(side_effect=cpfhub.CpfHubError(401)))
    alerts = []
    monkeypatch.setattr(tasks, 'dispatch_alert', lambda pk: alerts.append(pk))
    assert tasks.lookup_cpfhub(job.pk) == 'retry_pending'
    job.refresh_from_db()
    assert job.status == 'pending' and job.attempts == 1000 and job.alert_pending
    assert alerts == [job.pk]
    assert tasks.lookup_cpfhub(job.pk) == 'waiting'
    job.next_attempt_at = timezone.now() - timedelta(seconds=1)
    job.save()
    monkeypatch.setattr(cpfhub, 'lookup', AsyncMock(return_value=cpfhub.CpfIdentity(cpf=job.cpf, name='Test Owner', birth_date=date(1990,1,1))))
    assert tasks.lookup_cpfhub(job.pk) == 'success'
    user.profile.refresh_from_db()
    assert user.profile.name == 'Test Owner'
    assert tasks.lookup_cpfhub(job.pk) == 'finished'


def test_worker_restart_and_queue_failure_recovered(monkeypatch):
    job = CpfHubLookup.objects.create(cpf='09126367939', lease_until=timezone.now()-timedelta(seconds=1))
    queued = []
    monkeypatch.setattr('django_q.tasks.async_task', lambda *a: queued.append(a))
    assert tasks.retry_pending_lookups() == 1
    assert queued[0][-1] == job.pk
    monkeypatch.setattr('django_q.tasks.async_task', lambda *a: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(tasks, 'dispatch_alert', lambda pk: None)
    tasks.retry_pending_lookups()
    job.refresh_from_db()
    assert job.alert_pending and job.status == 'pending'


def test_confirm_reuses_pending_job(settings, monkeypatch):
    settings.TEST_MODE = False
    user = owner()
    CpfHubLookup.objects.create(user=user, cpf='09126367939')
    result = service.confirm_identity(user_external_id=str(user.external_id), cpf='09126367939')
    assert result['pending'] and result['name'] is None
    assert service.get_identity_lookup(user_external_id=str(user.external_id))['pending']

def test_failed_alert_is_retried_without_leaking_cpf(monkeypatch):
    user = owner()
    user.is_superuser = True
    user.save()
    job = CpfHubLookup.objects.create(user=user, cpf='09126367939', alert_pending=True, attempts=1, last_status_code=401)
    monkeypatch.setattr('notify.interface.send.send', lambda **kw: (_ for _ in ()).throw(RuntimeError()))
    tasks.dispatch_alert(job.pk)
    job.refresh_from_db()
    assert job.alert_pending
    sent = []
    monkeypatch.setattr('notify.interface.send.send', lambda **kw: sent.append(kw))
    tasks.dispatch_alert(job.pk)
    job.refresh_from_db()
    assert not job.alert_pending
    assert job.cpf not in sent[0]['text']
    assert sent[0]['idempotency_key']
