import pytest
from decimal import Decimal
import uuid
import json
from users.auth.models import User
from users.address.models import Address
from hub.models import Hub
from users.roles.lead.models import Lead, Checkout
from users.roles.lead import service as lead_svc
from users.roles.promoter.models import Promoter
from users.profiles import interface as profiles

pytestmark = pytest.mark.django_db

@pytest.fixture
def default_coordinator():
    coord = User.objects.create_user(external_id=uuid.uuid4())
    addr = Address.objects.create(city="São Paulo", state="SP")
    Hub.objects.create(address=addr, brand="Hub Central", coordinator=coord, is_default=True)
    return coord

@pytest.fixture
def affiliate_promoter(default_coordinator):
    u = User.objects.create_user(external_id=uuid.uuid4())
    hub = Hub.objects.filter(is_default=True).first()
    profiles.create(user=u, cpf=None, phone="5511999990001", name="Afiliado Alpha")
    Promoter.objects.create(user=u, hub=hub, status=Promoter.Status.ACTIVE)
    return u

@pytest.fixture
def another_promoter(default_coordinator):
    u = User.objects.create_user(external_id=uuid.uuid4())
    hub = Hub.objects.filter(is_default=True).first()
    profiles.create(user=u, cpf=None, phone="5511999990002", name="Afiliado Beta")
    Promoter.objects.create(user=u, hub=hub, status=Promoter.Status.ACTIVE)
    return u

def test_lead_creation_without_ref_locks_anchor_pricing(default_coordinator):
    """Lead criado sem ref trava preço âncora cheio e has_discount=False."""
    user = User.objects.create_user(external_id=uuid.uuid4())
    lead = lead_svc._create_lead_with_locked_pricing(
        user=user,
        promoter=default_coordinator,
        ref=None,
        status=Lead.Status.PENDING,
    )
    assert lead.has_discount is False
    assert lead.promoter_name == ""
    assert lead.pix_price > 0
    assert lead.card_price > 0
    assert lead.pricing_snapshot["has_discount"] is False
    assert Decimal(lead.pricing_snapshot["pix"]) == lead.pix_price

def test_lead_creation_with_ref_locks_promotional_pricing(default_coordinator, affiliate_promoter):
    """Lead criado com ref trava preço promocional com desconto e nome do promotor."""
    user = User.objects.create_user(external_id=uuid.uuid4())
    lead = lead_svc._create_lead_with_locked_pricing(
        user=user,
        promoter=affiliate_promoter,
        ref=str(affiliate_promoter.external_id),
        status=Lead.Status.PENDING,
    )
    assert lead.has_discount is True
    assert lead.promoter_name == "Afiliado"
    assert lead.pricing_snapshot["has_discount"] is True
    assert lead.pricing_snapshot["promoter_name"] == "Afiliado"
    assert Decimal(lead.pricing_snapshot["pix"]) == lead.pix_price

def test_anti_poaching_lead_cannot_change_promoter_or_pricing(default_coordinator, affiliate_promoter, another_promoter, client):
    """Lead captado pelo Afiliado Alpha tenta se cadastrar com link do Afiliado Beta:
    - O promotor original (Alpha) é preservado
    - O ref_raw original é preservado
    - O snapshot de preço original é preservado e imutável
    """
    # 1. Primeiro cadastro com Afiliado Alpha via check
    check_payload = {
        "phone": "11988887777",
        "ref": str(affiliate_promoter.external_id),
        "attribution": {
            "ref": str(affiliate_promoter.external_id),
            "utm_source": "alpha_campaign"
        }
    }
    r1 = client.post("/api/v1/clients/auth/check", data=json.dumps(check_payload), content_type="application/json")
    assert r1.status_code == 200
    res1 = r1.json()
    assert res1["created"] is True
    lead = Lead.objects.get(user__external_id=res1["external_id"])
    assert lead.promoter == affiliate_promoter
    assert lead.has_discount is True
    assert lead.promoter_name == "Afiliado"
    locked_pix = lead.pix_price
    locked_card = lead.card_price

    # 2. Tentativa de 'roubo' de lead / troca de promoção pelo Afiliado Beta
    poach_payload = {
        "phone": "11988887777",
        "ref": str(another_promoter.external_id),
        "attribution": {
            "ref": str(another_promoter.external_id),
            "utm_source": "beta_campaign"
        }
    }
    r2 = client.post("/api/v1/clients/auth/check", data=json.dumps(poach_payload), content_type="application/json")
    assert r2.status_code == 200
    res2 = r2.json()
    assert res2["found"] is True
    assert res2["created"] is False

    lead.refresh_from_db()
    # Continua sendo do Afiliado Alpha!
    assert lead.promoter == affiliate_promoter
    assert lead.attribution.ref_raw == str(affiliate_promoter.external_id)
    assert lead.pix_price == locked_pix
    assert lead.card_price == locked_card

def test_checkout_uses_locked_price_not_global_setting(default_coordinator, affiliate_promoter):
    """Criação de checkout em PIX e Cartão usa estritamente o valor travado no lead."""
    user = User.objects.create_user(external_id=uuid.uuid4())
    lead = lead_svc._create_lead_with_locked_pricing(
        user=user,
        promoter=affiliate_promoter,
        ref=str(affiliate_promoter.external_id),
        status=Lead.Status.PENDING,
    )
    # Checkout PIX
    chk_pix = lead_svc._create_checkout_row(lead, "pix")
    assert chk_pix.amount == lead.pix_price

    # Checkout Cartão
    lead.checkout.delete()
    lead.refresh_from_db()
    chk_card = lead_svc._create_checkout_row(lead, "card")
    assert chk_card.amount == lead.card_price

def test_lead_me_and_pricing_endpoint_return_locked_pricing(default_coordinator, affiliate_promoter, client):
    """GET /lead/me e GET /pricing retornam o preço travado do lead autenticado."""
    # 1. Login e obtenção de token
    phone = "11977776666"
    r = client.post("/api/v1/clients/auth/check", data=json.dumps({
        "phone": phone,
        "ref": str(affiliate_promoter.external_id)
    }), content_type="application/json")
    ext_id = r.json()["external_id"]
    r_login = client.post("/api/v1/clients/auth/login", data=json.dumps({
        "external_id": ext_id,
        "otp": "000000"
    }), content_type="application/json")
    token = r_login.json()["access_token"]
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    # 2. GET /api/v1/clients/lead/me
    r_me = client.get("/api/v1/clients/lead/me", **headers)
    assert r_me.status_code == 200
    me_data = r_me.json()
    assert "pricing" in me_data
    assert me_data["pricing"]["has_discount"] is True
    assert me_data["pricing"]["promoter_name"] == "Afiliado"

    # 3. GET /api/v1/clients/pricing autenticado (mesmo passando ?ref=outro_afiliado)
    r_price = client.get("/api/v1/clients/pricing?ref=outro_afiliado", **headers)
    assert r_price.status_code == 200
    price_data = r_price.json()
    # Retorna o preço travado do aluno, ignorando o ?ref do query param
    assert price_data["has_discount"] is True
    assert price_data["promoter_name"] == "Afiliado"
