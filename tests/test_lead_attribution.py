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


def test_lead_attribution_in_register(client, test_promoter):
    import json
    payload = {
        "cpf": "52998224725",
        "phone": "+5511977777777",
        "email": "lead.attr@supletivo.net.br",
        "payment_method": "pix",
        "ref": test_promoter.external_id.hex,
        "attribution": {
            "gclid": "register_gclid_123",
            "fbclid": "register_fbclid_456",
            "utm_source": "google_ads",
            "utm_campaign": "supletivo_2026",
            "landing_url": "https://supletivo.net.br/?gclid=register_gclid_123",
        },
    }
    resp = client.post(
        "/api/v1/clients/auth/register",
        data=json.dumps(payload),
        content_type="application/json",
        REMOTE_ADDR="192.168.1.50",
        HTTP_USER_AGENT="Mozilla/5.0 TestAgent",
    )
    assert resp.status_code == 201, resp.json()
    data = resp.json()
    lead = Lead.objects.get(external_id=data["external_id"])
    assert hasattr(lead, "attribution")
    assert lead.attribution.gclid == "register_gclid_123"
    assert lead.attribution.fbclid == "register_fbclid_456"
    assert lead.attribution.utm_source == "google_ads"
    assert lead.attribution.utm_campaign == "supletivo_2026"
    assert lead.attribution.client_ip == "192.168.1.50"
    assert lead.attribution.user_agent == "Mozilla/5.0 TestAgent"
    assert lead.promoter == test_promoter


def test_lead_attribution_in_checkout(client, test_lead):
    import json
    from users.auth.jwt import service as jwt_service
    from users.profiles.models import Profile

    # Guarantee profile has email and cpf to satisfy step 6
    prof, _ = Profile.objects.get_or_create(user=test_lead.user)
    prof.cpf = "52998224725"
    prof.email = "lead.checkout@supletivo.net.br"
    prof.save()

    token_data = jwt_service.issue(test_lead.user.external_id, ["lead"])
    token = token_data["access_token"]
    payload = {
        "payment_method": "card",
        "attribution": {
            "gclid": "checkout_gclid_999",
            "utm_source": "meta_ads",
            "utm_medium": "cpc",
        },
    }
    resp = client.post(
        "/api/v1/clients/lead/checkout",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        REMOTE_ADDR="10.0.0.1",
    )
    assert resp.status_code == 200, resp.json()
    test_lead.refresh_from_db()
    assert hasattr(test_lead, "attribution")
    assert test_lead.attribution.gclid == "checkout_gclid_999"
    assert test_lead.attribution.utm_source == "meta_ads"
    assert test_lead.attribution.client_ip == "10.0.0.1"
