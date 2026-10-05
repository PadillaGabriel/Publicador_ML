"""Verify administrative account-grant URLs never fall into unclassified actions."""
from app.operator_access import required_action
from app.identity_policy import Role, permitted, can_manage_user


def test_account_grant_mutation_restricted_to_managers():
    assert required_action('/api/operator-account-grants/00000000-0000-0000-0000-000000000000', 'PUT') == 'manage_users'
    assert permitted(Role.ADMIN, 'manage_users')
    assert permitted(Role.SUPERVISOR, 'manage_users')
    assert not permitted(Role.OPERATOR, 'manage_users')


def test_supervisor_cannot_manage_admin_grants():
    assert not can_manage_user(Role.SUPERVISOR, Role.ADMIN)
    assert can_manage_user(Role.SUPERVISOR, Role.OPERATOR)
