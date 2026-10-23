import pytest
from core import system_config
from hub.models import Hub
from hub.management.commands.seed_defaults import Command
from users.address.models import Address
from users.auth.models import User
from users.roles.models import UserRole
from users.roles.promoter.models import Promoter
from users.roles.lead.service import _resolve_promoter, LeadError
from users.exceptions import ValidationError

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    system_config.clear_settings_cache()
    yield
    system_config.clear_settings_cache()


def test_default_promoter_is_independent_of_hub_coordinator():
    coordinator, selected = User.objects.create_user(), User.objects.create_user()
    hub = Hub.objects.create(address=Address.objects.create(), coordinator=coordinator, is_default=True)
    Promoter.objects.create(user=selected, hub=hub)
    system_config.save_platform_config({"default_promoter_external_id": str(selected.external_id)})
    assert _resolve_promoter(None) == selected
    hub.refresh_from_db()
    assert hub.coordinator == coordinator
    assert system_config.get_all_platform_config()["default_promoter_external_id"] == str(selected.external_id)


def test_invalid_default_promoter_cannot_save_other_changes():
    user = User.objects.create_user()
    with pytest.raises(ValidationError):
        system_config.save_platform_config({"default_promoter_external_id": str(user.external_id), "pricing": {"price_pix": "0.01"}})
    assert system_config.get_setting("ENROLLMENT_PRICE_PIX", "1615") != "0.01"


def test_suspended_default_does_not_silently_redirect_commission():
    user = User.objects.create_user()
    hub = Hub.objects.create(address=Address.objects.create(), coordinator=user, is_default=True)
    promoter = Promoter.objects.create(user=user, hub=hub)
    system_config.set_setting("DEFAULT_PROMOTER_USER_EXTERNAL_ID", str(user.external_id))
    promoter.status = Promoter.Status.SUSPENDED
    promoter.save()
    with pytest.raises(LeadError, match="default_promoter_unavailable"):
        _resolve_promoter(None)


def test_bootstrap_preserves_assigned_coordinator_and_staff_roles():
    staff = User.objects.create_user(is_staff=True)
    coordinator = User.objects.create_user()
    hub = Hub.objects.create(address=Address.objects.create(), coordinator=coordinator, is_default=True)
    result, created = Command()._ensure_default_hub(brand="standard", coordinator=staff)
    Command()._ensure_roles(staff, operational=result.coordinator_id == staff.pk)
    hub.refresh_from_db()
    assert result.pk == hub.pk and created is False and hub.coordinator_id == coordinator.pk
    assert list(UserRole.objects.filter(user=staff).values_list("role", flat=True)) == ["staff"]
