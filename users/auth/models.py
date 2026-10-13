"""User — a identidade da plataforma (custom AUTH_USER_MODEL).

Decisão do Victor (2026-06-01, sobrepõe a CONVENTION §4 "User padrão"): o User custom carrega o
`external_id` (UUID) — a identidade exposta na borda da API (§4). O login é **passwordless por
OTP**, então o User normal nasce com senha inutilizável; só superuser/staff tem senha real (admin).
Por isso o `USERNAME_FIELD` é o próprio `external_id` (admin loga pelo UUID — confirmado no Portão 2).

Dados pessoais/contato (cpf, phone, email, gender) NÃO moram aqui — moram no `Profile` 1-1
(`users/profiles/models.py`), "contato em profiles" (§4). Este model é a âncora pura: identidade +
flags de admin. As FKs de roles/otp apontam pro PK interno (`id`); a borda usa `external_id`.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.utils import timezone

from core.models import ExternalIdModel


class UserManager(BaseUserManager):
    """Manager do User custom. Login é por `external_id` (passwordless por OTP)."""

    use_in_migrations = True

    def get_by_natural_key(self, username):
        # Usado pelo ModelBackend (admin) — chaveia pelo USERNAME_FIELD (external_id).
        return self.get(**{self.model.USERNAME_FIELD: username})

    def create_user(self, external_id=None, password=None, **extra):
        """Cria um User. Sem senha => senha inutilizável (o caminho normal: login por OTP)."""
        user = self.model(external_id=external_id or uuid.uuid4(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, external_id=None, password=None, **extra):
        """Superuser (admin) — precisa de senha real; loga no /admin pelo external_id."""
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if extra.get("is_staff") is not True or extra.get("is_superuser") is not True:
            raise ValueError("Superuser precisa de is_staff=True e is_superuser=True.")
        if not password:
            raise ValueError("Superuser precisa de senha (login do admin).")
        return self.create_user(external_id=external_id, password=password, **extra)


class User(ExternalIdModel, AbstractBaseUser, PermissionsMixin):
    """Identidade da plataforma. `external_id` (UUID, imutável) = o id exposto na borda (§4)."""

    is_staff = models.BooleanField("equipe", default=False)
    is_active = models.BooleanField("ativo", default=True)
    date_joined = models.DateTimeField("criado em", default=timezone.now)
    # versão do token: o JWT carrega esta versão; trocar de role (roles.promote/assign) incrementa, o que
    # **invalida todo JWT antigo** (gate confere) → força re-login/refresh com a role nova (Victor 2026-06-05).
    token_version = models.PositiveIntegerField(default=0)
    is_test = models.BooleanField(
        "dado sintético de teste", default=False, db_index=True
    )
    test_expires_at = models.DateTimeField(
        "expira em", null=True, blank=True, db_index=True
    )

    objects = UserManager()

    USERNAME_FIELD = "external_id"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        app_label = "users"
        db_table = "users_user"
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def __str__(self) -> str:
        return str(self.external_id)


class CpfHubLookup(ExternalIdModel):
    """Fila persistente de consultas CPFHub executada pelo worker."""

    class Status(models.TextChoices):
        PENDING = "pending", "aguardando CPFHub"
        SUCCESS = "success", "identidade confirmada"
        NOT_FOUND = "not_found", "CPF não encontrado"

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name="cpfhub_lookups")
    cpf = models.CharField("CPF", max_length=11, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=255, blank=True, default="")
    last_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    identity_name = models.CharField(max_length=200, null=True, blank=True)
    identity_gender = models.CharField(max_length=1, null=True, blank=True)
    identity_birth_date = models.DateField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    alert_pending = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "users"
        db_table = "users_cpfhublookup"

    def __str__(self) -> str:
        return f"cpfhub<{self.external_id}:{self.status}>"
