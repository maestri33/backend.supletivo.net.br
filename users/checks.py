"""System checks do app ``users``."""

from django.core.checks import Error


def check_users(app_configs, **kwargs):
    errors = []

    from users.roles import catalog

    if not any(r.from_role is None for r in catalog.all_rules()):
        errors.append(
            Error(
                "ROLE_RULES não tem nenhuma role de entrada (from_role=None) — o register não "
                "consegue atribuir papel inicial.",
                hint="Inclua ao menos uma regra com from_role null no ROLE_RULES do .env.",
                id="users.E001",
            )
        )

    return errors
