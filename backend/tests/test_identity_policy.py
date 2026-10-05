from app.identity_policy import Role, can_assign_role, can_manage_user, permitted


def test_supervisor_cannot_escalate_or_modify_admin():
    assert not can_assign_role(Role.SUPERVISOR, Role.ADMIN)
    assert not can_manage_user(Role.SUPERVISOR, Role.ADMIN)
    assert can_assign_role(Role.SUPERVISOR, Role.OPERATOR)
    assert can_assign_role(Role.SUPERVISOR, Role.SUPERVISOR)
    assert can_manage_user(Role.ADMIN, Role.ADMIN)


def test_permissions_follow_approved_matrix():
    assert permitted(Role.OPERATOR, "publish")
    assert permitted(Role.OPERATOR, "bulk_update_items")
    assert not permitted(Role.SUPERVISOR, "publish")
    assert permitted(Role.SUPERVISOR, "manage_users")
    assert not permitted(Role.OPERATOR, "view_full_audit")
    assert permitted(Role.OPERATOR, "view_team_history")
    assert not permitted(Role.ADMIN, "unknown_permission")
