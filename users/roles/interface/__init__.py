"""Superfície pública in-process do `roles` (CONVENTION §3): o que o auth e futuros apps chamam.

Fina de propósito — só reexporta a lógica do `service`/`catalog`. Quem chama (auth) passa o `User`;
a borda (views/edges) traduz `external_id` ↔ User.
"""

from users.roles.catalog import all_rules, find_rule
from users.roles.service import (
    active_roles,
    assign,
    grant,
    is_blocked,
    promote,
    purge_funnel_user,
    revoke,
    users_with_role,
)


def is_entry_role(role: str) -> bool:
    """True se `role` pode ser a primeira role (regra com from_role=None)."""
    return find_rule(to_role=role, from_role=None) is not None


__all__ = [
    "assign",
    "promote",
    "grant",
    "revoke",
    "active_roles",
    "is_blocked",
    "is_entry_role",
    "users_with_role",
    "purge_funnel_user",
    "all_rules",
]
