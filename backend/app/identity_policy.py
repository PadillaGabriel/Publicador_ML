"""Pure, independently testable RBAC rules for internal operator management."""

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "ADMIN"
    SUPERVISOR = "SUPERVISOR"
    OPERATOR = "OPERATOR"


# Explicit deny by default; authorization must also check account grants and ownership.
PERMISSIONS: dict[str, frozenset[Role]] = {
    "create_product": frozenset({Role.ADMIN, Role.OPERATOR}),
    "edit_own_product": frozenset({Role.ADMIN, Role.OPERATOR}),
    "edit_foreign_product": frozenset({Role.ADMIN}),
    "publish": frozenset({Role.ADMIN, Role.OPERATOR}),
    "update_item": frozenset({Role.ADMIN, Role.OPERATOR}),
    "bulk_update_items": frozenset({Role.ADMIN, Role.OPERATOR}),
    "set_manual_prices": frozenset({Role.ADMIN, Role.OPERATOR}),
    "configure_global": frozenset({Role.ADMIN, Role.SUPERVISOR}),
    "manage_ml_accounts": frozenset({Role.ADMIN, Role.SUPERVISOR}),
    "manage_users": frozenset({Role.ADMIN, Role.SUPERVISOR}),
    "view_team_history": frozenset(Role),
    "view_full_audit": frozenset({Role.ADMIN, Role.SUPERVISOR}),
}


def permitted(role: Role, action: str) -> bool:
    return role in PERMISSIONS.get(action, frozenset())


def can_assign_role(actor: Role, target: Role) -> bool:
    """A supervisor cannot create/promote admin accounts or grant own privileges."""
    if actor == Role.ADMIN:
        return True
    return actor == Role.SUPERVISOR and target in {Role.SUPERVISOR, Role.OPERATOR}


def can_manage_user(actor: Role, target: Role) -> bool:
    """A supervisor cannot modify or deactivate an administrator."""
    return permitted(actor, "manage_users") and (actor == Role.ADMIN or target != Role.ADMIN)
