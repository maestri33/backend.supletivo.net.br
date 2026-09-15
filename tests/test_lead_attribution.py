import pytest
from unittest.mock import patch
from users.roles.lead.models import Lead, LeadAttribution
from integrations.analytics import tasks
from django.utils import timezone
from users.auth.models import User
from users.address.models import Address
from hub.models import Hub

pytestmark = pytest.mark.django_db

@pytest.fixture
def test_promoter():
    import uuid
    coord = User.objects.create_user(external_id=uuid.uuid4())
    addr = Address.objects.create(city='São Paulo', state='SP')
    Hub.objects.create(address=addr, brand='e2e', coordinator=coord, is_default=True)
    return coord

@pytest.fixture
def test_lead(test_promoter):
    import uuid
    from users.roles.lead.models import Checkout
    user = User.objects.create_user(external_id=uuid.uuid4())
    lead = Lead.objects.create(user=user, promoter=test_promoter, status=Lead.Status.PENDING)
    Checkout.objects.create(lead=lead, amount=100.00, payment_method='pix', provider='asaas')
    return lead

def test_lead_attribution_creation(client, test_promoter):
    import json
    payload = {
        'phone': '+5511999999999',
        'ref': test_promoter.external_id.hex,
        'attribution': {
            'gclid': 'test_gclid',
            'utm_source': 'google'
        }
    }
    response = client.post('/api/v1/clients/auth/check', data=json.dumps(payload), content_type='application/json', REMOTE_ADDR='127.0.0.1')
    assert response.status_code == 200, response.json()
    assert response.json()['created'] is True
    
    lead = Lead.objects.latest('created_at')
    assert lead.attribution.gclid == 'test_gclid'
    assert lead.attribution.utm_source == 'google'
    assert lead.attribution.client_ip == '127.0.0.1'

def test_lead_attribution_failure_does_not_block_lead(client, test_promoter):
    import json
    payload = {
        'phone': '+5511988888888',
        'ref': test_promoter.external_id.hex,
        'attribution': {
            'gclid': 'test'
        }
    }
    with patch('users.roles.lead.service.LeadAttribution.objects.update_or_create', side_effect=Exception('DB Error')):
        response = client.post('/api/v1/clients/auth/check', data=json.dumps(payload), content_type='application/json')
        
    assert response.status_code == 200
    assert response.json()['created'] is True
    
    lead = Lead.objects.latest('created_at')
    assert not hasattr(lead, 'attribution')

@patch('integrations.analytics.tasks.send_google_purchase')
@patch('integrations.analytics.tasks.send_meta_purchase')
def test_send_purchase_task(mock_meta, mock_google, test_lead):
    LeadAttribution.objects.create(lead=test_lead, gclid='teste', fbp='fbpteste', fbc='fbcteste')
    test_lead.checkout.is_paid = True
    test_lead.checkout.save()
    test_lead.status = Lead.Status.PAID
    test_lead.save()
    
    tasks.send_purchase(str(test_lead.external_id))
    
    mock_google.assert_called_once()
    mock_meta.assert_called_once()
    
    test_lead.attribution.refresh_from_db()
    assert test_lead.attribution.sent_google is not None
    assert test_lead.attribution.sent_meta is not None
    
    # Idempotency
    mock_google.reset_mock()
    mock_meta.reset_mock()
    
    tasks.send_purchase(str(test_lead.external_id))
    mock_google.assert_not_called()
    mock_meta.assert_not_called()

@patch('integrations.analytics.tasks.send_google_purchase')
@patch('integrations.analytics.tasks.send_meta_purchase')
def test_send_purchase_task_ignores_self_study(mock_meta, mock_google, test_lead):
    test_lead.self_study = True
    test_lead.status = Lead.Status.PAID
    test_lead.save()
    LeadAttribution.objects.create(lead=test_lead)
    
    tasks.send_purchase(str(test_lead.external_id))
    
    mock_google.assert_not_called()
    mock_meta.assert_not_called()
