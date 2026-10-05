"""Guard the two critical invariants without a running PostgreSQL instance."""
from pathlib import Path

from app.operator_account_scope import scope_operation


def test_reuse_is_classified_but_handler_guards_ownership():
    source = Path(__file__).parents[1] / "app" / "technical_attributes" / "router.py"
    body = source.read_text(encoding="utf-8")
    assert "visible_product(db, actor, product_id)" in body
    assert "ensure_account(db, actor, account_id)" in body
    scope_operation(None, type("User", (), {"role": "OPERATOR"})(),
                    "/api/products/00000000-0000-0000-0000-000000000001/technical-attributes/reuse",
                    "GET", {}, None)


def test_upload_handler_checks_owner_before_file_read():
    source = Path(__file__).parents[1] / "app" / "main.py"
    body = source.read_text(encoding="utf-8")
    section = body.split('def serve_upload(', 1)[1].split('mount_static_frontend(', 1)[0]
    assert section.index('request_identity(db, request)') < section.index('FileResponse(')
    assert section.index('visible_product(db, actor, version.product_master_id)') < section.index('FileResponse(')
