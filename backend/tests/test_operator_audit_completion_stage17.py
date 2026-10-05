"""Static regression checks of identity propagation at mutation boundaries."""
import ast
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "app"

def function(module: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((BASE / module).read_text())
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)

def calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [call for call in ast.walk(node) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == name]

def has_actor(call: ast.Call, value: str) -> bool:
    return any(k.arg == "actor_user_id" and isinstance(k.value, ast.Attribute) and k.value.attr == value for k in call.keywords)

def test_upload_endpoints_forward_authenticated_actor():
    for handler, service in [("upload_images_batch", "persist_staged_product_images"), ("upload_image", "persist_product_image")]:
        f = function("products/router.py", handler)
        assert calls(f, "request_identity")
        assert any(has_actor(call, "id") for call in calls(f, service)), handler

def test_image_persistence_attaches_actor_to_audit():
    f = function("products/image_upload.py", "persist_staged_product_images")
    events = calls(f, "audit")
    assert events and any(any(k.arg == "actor_user_id" and isinstance(k.value, ast.Name) and k.value.id == "actor_user_id" for k in call.keywords) for call in events)

def test_cancel_job_audit_bound_to_identity():
    f = function("jobs.py", "cancel_job")
    assert calls(f, "request_identity")
    assert any(has_actor(call, "id") for call in calls(f, "audit"))
    assert any(call.func.attr == "commit" for call in ast.walk(f) if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute))
