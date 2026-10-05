"""Route classification regression tests (pure functions, no database needed)."""

from app.operator_access import required_action


def test_roles_are_required_for_changes():
    assert required_action("/api/products", "POST") == "create_product"
    assert required_action("/api/drafts/generate", "POST") == "publish"
    assert required_action("/api/pricing/profile", "PUT") == "configure_global"
    assert required_action("/api/accounts", "POST") == "manage_ml_accounts"
    assert required_action("/api/accounts/oauth/start", "GET") == "manage_ml_accounts"
    assert required_action("/api/jobs/test/cancel", "POST") == "publish"
    assert required_action("/api/pricing/simulate", "POST") is None
    assert required_action("/api/unclassified", "POST") == "__unclassified__"


def test_import_operations_are_classified():
    assert required_action("/api/publication-import/mla", "POST") == "create_product"
