"""Seed IDEMPOTENTE dos padrões: a conta-mãe + o hub padrão."""

from __future__ import annotations

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core import system_config
from hub import config
from hub.models import Hub
from users.address import interface as address_iface
from users.auth import validation as auth_validation
from users.auth.models import User
from users.documents import service as documents_iface
from users.profiles import interface as profiles
from users.profiles.models import Profile
from users.roles.models import UserRole
from users.roles.promoter import service as promoter_iface

logger = structlog.get_logger()


class Command(BaseCommand):
    help = "Cria (idempotente) a conta-mãe (staff superuser + promoter + coordinator) e o hub padrão."

    def handle(self, *args, **options):
        cpf = system_config.get_setting("DEFAULT_STAFF_CPF", getattr(settings, "DEFAULT_STAFF_CPF", ""))
        phone = system_config.get_setting("DEFAULT_STAFF_PHONE", getattr(settings, "DEFAULT_STAFF_PHONE", ""))
        name = system_config.get_setting("DEFAULT_STAFF_NAME", getattr(settings, "DEFAULT_STAFF_NAME", ""))
        email = system_config.get_setting("DEFAULT_STAFF_EMAIL", getattr(settings, "DEFAULT_STAFF_EMAIL", ""))
        password = system_config.get_setting("DEFAULT_STAFF_PASSWORD") or getattr(settings, "DEFAULT_STAFF_PASSWORD", "") or "1993"
        if not (cpf and phone):
            raise CommandError(
                "Configure DEFAULT_STAFF_CPF / DEFAULT_STAFF_PHONE."
            )
        identity = None
        if not name or name in ("Victor", "Administrador Geral", "Administrador Master"):
            try:
                from asgiref.sync import async_to_sync
                from integrations.tools.cpf.scripts import cpfhub
                identity = async_to_sync(cpfhub.lookup)(cpf)
                if identity and identity.name:
                    name = identity.name
            except Exception:
                pass
        name = name or (identity.name if identity else "Administrador Master")
        email = email or "admin@v7m.org"

        # Profile.phone usa o formato canônico DDI+DDD+número. O valor de ambiente
        # pode vir no formato amigável DDD+número, como ocorre no compose local.
        try:
            phone = auth_validation.validate_phone(phone)
        except ValueError as exc:
            raise CommandError(f"DEFAULT_STAFF_PHONE inválido: {exc}") from exc

        brand = system_config.get_setting("DEFAULT_HUB_BRAND", getattr(settings, "DEFAULT_HUB_BRAND", "standard"))
        user, user_created = self._ensure_staff(
            cpf=cpf, phone=phone, name=name, email=email, password=password, identity=identity
        )
        self._ensure_roles(user)
        self._ensure_pix(user)
        hub, hub_created = self._ensure_default_hub(brand=brand, coordinator=user)
        promoter = promoter_iface.create_promoter(user=user, hub=hub)  # idempotente

        logger.info(
            "hub.seed_defaults",
            staff_external_id=str(user.external_id),
            staff_created=user_created,
            hub_external_id=str(hub.external_id),
            hub_created=hub_created,
            promoter_external_id=str(promoter.external_id),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"staff external_id={user.external_id} (novo={user_created}); "
                f"hub padrão external_id={hub.external_id} brand={hub.brand} (novo={hub_created}); "
                f"promoter external_id={promoter.external_id} (ref de captação = staff external_id)"
            )
        )

    def _ensure_staff(self, *, cpf, phone, name, email, password, identity=None):
        """Acha a conta-mãe pelo cpf (idempotente) ou cria como superuser + Profile + Address vazio + Documents."""
        existing = Profile.objects.filter(cpf=cpf).select_related("user").first()
        if existing is not None:
            user = existing.user
            changed = []
            profile_changed = []
            # Corrige seeds antigos que persistiram o mesmo número sem o DDI 55.
            try:
                same_phone = auth_validation.validate_phone(existing.phone) == phone
            except ValueError:
                same_phone = False
            if existing.phone != phone and same_phone:
                existing.phone = phone
                profile_changed.append("phone")
            if not user.is_superuser:
                user.is_superuser = True
                changed.append("is_superuser")
            if not user.is_staff:
                user.is_staff = True
                changed.append("is_staff")
            if password and not user.check_password(password):
                user.set_password(password)
                changed.append("password")
            # Email da conta-mãe: grava se veio do .env e o Profile está sem email (não sobrescreve).
            if email and not existing.email:
                existing.email = email
                profile_changed.append("email")
            if profile_changed:
                existing.save(update_fields=[*profile_changed, "updated_at"])
            if changed:
                user.save(update_fields=changed)
            return user, False

        user = User.objects.create_superuser(password=password)
        profile = profiles.create(
            user=user,
            cpf=cpf,
            phone=phone,
            name=name,
            email=email or None,
            gender=identity.gender if identity else None,
            birth_date=identity.birth_date if identity else None,
        )
        profiles.attach_address(profile, address_iface.create_empty())
        documents_iface.create_empty(user)
        return user, True

    def _ensure_roles(self, user):
        """promoter + coordinator + staff DIRETO (bypass catálogo — seed de sistema). Idempotente."""
        for role in ("promoter", "coordinator", "staff"):
            UserRole.objects.get_or_create(user=user, role=role, revoked_at=None)

    def _ensure_pix(self, user):
        """Pix da conta-mãe (destino dos payouts dela) — grava DEFAULT_STAFF_PIX se o Profile está
        sem chave ou atualiza com a chave configurada, e valida/registra no DICT Asaas (asaas_pixkey)."""
        pix = system_config.get_setting("DEFAULT_STAFF_PIX", getattr(settings, "DEFAULT_STAFF_PIX", ""))
        if not pix:
            return
        profile = Profile.objects.filter(user=user).first()
        if profile is None:
            return

        from users.roles.promoter.service import detect_pix_key_type
        key_type = detect_pix_key_type(pix)

        changed = []
        if profile.pix_key != pix:
            profile.pix_key = pix
            changed.append("pix_key")
        if getattr(profile, "pix_key_type", None) != key_type:
            profile.pix_key_type = key_type
            changed.append("pix_key_type")
        if changed:
            profile.save(update_fields=[*changed, "updated_at"])

        if profile.cpf:
            try:
                from integrations.bank.asaas import pixkey
                pixkey.validate_pix_key(
                    key=pix,
                    key_type=key_type,
                    expected_document=profile.cpf,
                )
                logger.info(
                    "hub.seed_defaults.pix_validated",
                    pix_key=pix,
                    key_type=key_type,
                    staff_cpf=profile.cpf,
                )
            except Exception as exc:
                logger.warning(
                    "hub.seed_defaults.pix_validation_skipped",
                    pix_key=pix,
                    key_type=key_type,
                    error=str(exc),
                )


    def _ensure_default_hub(self, *, brand, coordinator):
        """Garante o hub padrão (coordenador = conta-mãe). Idempotente pelo flag is_default."""
        hub = Hub.objects.filter(is_default=True).first()
        if hub is not None:
            if hub.coordinator_id != coordinator.id:
                hub.coordinator = coordinator
                hub.save(update_fields=["coordinator", "updated_at"])
            return hub, False
        address = address_iface.create_empty()
        hub = Hub.objects.create(
            address=address, brand=brand, coordinator=coordinator, is_default=True
        )
        return hub, True
