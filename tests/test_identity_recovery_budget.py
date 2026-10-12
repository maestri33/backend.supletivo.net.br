import asyncio
import json
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from integrations.ai import service
from integrations.ai.client import ChatResult, LLMError
from integrations.ai.cloudflare import CloudflareWorkersAIClient
from integrations.ai.models import AiCall


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(service.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr('integrations.ai.cloudflare.connection', lambda: ('https://gateway.invalid', 'test-token'))
    return now


@pytest.mark.django_db
def test_identity_ocr_recovers_once_and_records_failed_attempt(monkeypatch, clock):
    async def chat(client, *args, **kwargs):
        clock[0] += 60 if clock[0] == 100 else 20
        if clock[0] == 160:
            raise LLMError('read_timeout', retryable=True)
        return ChatResult(content='Printed identity text', finish_reason='stop')
    monkeypatch.setattr(CloudflareWorkersAIClient, 'chat', chat)
    assert service.ocr(b'fake', caller='test.recovery', document=True, deadline=220) == 'Printed identity text'
    assert list(AiCall.objects.filter(caller='test.recovery').values_list('status', flat=True)) == ['error', 'success']


@pytest.mark.django_db
def test_ocr_attempts_stop_at_budget_without_unbounded_retry(monkeypatch, clock):
    limits = []
    async def chat(client, *args, **kwargs):
        limits.append(client._timeout)
        clock[0] += client._timeout
        raise LLMError('read_timeout', retryable=True)
    monkeypatch.setattr(CloudflareWorkersAIClient, 'chat', chat)
    with pytest.raises(LLMError):
        service.ocr(b'fake', caller='test.exhaustion', document=True, deadline=190)
    assert limits == [60, 30]
    assert clock[0] == 190
    assert AiCall.objects.filter(caller='test.exhaustion', status='error').count() == 2


@pytest.mark.django_db
def test_ocr_contract_failure_is_not_retried(monkeypatch, clock):
    chat = AsyncMock(side_effect=LLMError('HTTP 400', retryable=False))
    monkeypatch.setattr(CloudflareWorkersAIClient, 'chat', chat)
    with pytest.raises(LLMError):
        service.ocr(b'fake', caller='test.bad-input', document=True, deadline=220)
    assert chat.await_count == 1


@pytest.mark.django_db
def test_expired_identity_budget_does_not_start_inference(monkeypatch, clock):
    chat = AsyncMock()
    monkeypatch.setattr(CloudflareWorkersAIClient, 'chat', chat)
    with pytest.raises(LLMError) as caught:
        service.ocr(b'fake', caller='test.expired', document=True, deadline=99)
    assert caught.value.retryable is False
    chat.assert_not_awaited()


@pytest.mark.django_db
def test_shared_http_pool_keeps_per_request_timeout(monkeypatch):
    monkeypatch.setattr('integrations.ai.cloudflare.connection', lambda: ('https://gateway.invalid', 'test-token'))
    pool = AsyncMock()
    pool.post.return_value = httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})
    monkeypatch.setattr('integrations.ai.cloudflare.get_ai_http_client', lambda **kwargs: pool)
    client = CloudflareWorkersAIClient(timeout=3.5)
    asyncio.run(client.chat([{'role': 'user', 'content': 'test'}], model='@cf/google/gemma-4-26b-a4b-it'))
    timeout = pool.post.await_args.kwargs['timeout']
    assert timeout.read == 3.5 and timeout.connect == 3.5


@pytest.mark.django_db
@pytest.mark.parametrize('failure,kind', [(httpx.ReadTimeout('private payload'), 'read_timeout'), (httpx.ConnectTimeout('private payload'), 'connect_timeout'), (httpx.ConnectError('private payload'), 'transport_error')])
def test_transport_telemetry_identifies_kind_without_private_payload(monkeypatch, failure, kind):
    monkeypatch.setattr('integrations.ai.cloudflare.connection', lambda: ('https://gateway.invalid', 'test-token'))
    pool = AsyncMock()
    pool.post.side_effect = failure
    monkeypatch.setattr('integrations.ai.cloudflare.get_ai_http_client', lambda **kwargs: pool)
    with pytest.raises(LLMError) as caught:
        asyncio.run(CloudflareWorkersAIClient().chat([{'role': 'user', 'content': 'test'}], model='@cf/google/gemma-4-26b-a4b-it'))
    assert caught.value.error_kind == kind
    assert kind in str(caught.value) and 'private payload' not in str(caught.value)


@pytest.mark.django_db
def test_total_http_budget_cancels_request(monkeypatch):
    monkeypatch.setattr('integrations.ai.cloudflare.connection', lambda: ('https://gateway.invalid', 'test-token'))
    cancelled = []
    async def stalled(*args, **kwargs):
        try:
            await asyncio.sleep(1)
        finally:
            cancelled.append(True)
    pool = AsyncMock()
    pool.post.side_effect = stalled
    monkeypatch.setattr('integrations.ai.cloudflare.get_ai_http_client', lambda **kwargs: pool)
    with pytest.raises(LLMError) as caught:
        asyncio.run(CloudflareWorkersAIClient(timeout=0.01).chat([{'role': 'user', 'content': 'test'}], model='@cf/google/gemma-4-26b-a4b-it'))
    assert caught.value.error_kind == 'total_timeout'
    assert cancelled == [True]


def test_cnh_faces_and_json_share_one_deadline(monkeypatch, clock):
    deadlines = []
    def ocr(source, **kwargs):
        deadlines.append(kwargs['deadline'])
        clock[0] += 25
        return 'Printed text'
    structured = Mock(return_value={'name': 'Printed Holder'})
    credentials = Mock(return_value={'number': '00123456789', 'category': 'B'})
    monkeypatch.setattr(service, 'ocr', ocr)
    monkeypatch.setattr(service, 'generate_json', structured)
    monkeypatch.setattr(service, '_read_cnh_credentials', credentials)
    result = service.read_identity_document([b'front', b'back'], doc_type='cnh', schema='{}', caller='test.faces')
    assert deadlines == [220, 220]
    assert structured.call_args.kwargs['timeout'] == 20
    assert credentials.call_args.kwargs['deadline'] == 220
    assert result['number'] == '00123456789'


def test_cnh_exhaustion_cannot_start_json_or_apply_credentials(monkeypatch, clock):
    def ocr(source, **kwargs):
        clock[0] = kwargs['deadline']
        return 'Printed text'
    structured, credentials = Mock(), Mock()
    monkeypatch.setattr(service, 'ocr', ocr)
    monkeypatch.setattr(service, 'generate_json', structured)
    monkeypatch.setattr(service, '_read_cnh_credentials', credentials)
    with pytest.raises(LLMError) as caught:
        service.read_identity_document([b'file'], doc_type='cnh', schema='{}', caller='test.exhausted')
    assert caught.value.retryable is False
    structured.assert_not_called()
    credentials.assert_not_called()


@pytest.mark.django_db
def test_truncated_ocr_never_becomes_verified_identity(monkeypatch, clock):
    chat = AsyncMock(return_value=ChatResult(content='Partial printed text', finish_reason='length'))
    monkeypatch.setattr(CloudflareWorkersAIClient, 'chat', chat)
    with pytest.raises(LLMError) as caught:
        service.ocr(b'fake', caller='test.truncated', document=True, deadline=220)
    assert caught.value.retryable is False
    assert chat.await_count == 1
