"""Static regression contract: authenticated draft mutations attribute audit events."""
import ast
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "app" / "drafts"


def _functions(source: str):
    return {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}


def _calls(func, name: str):
    return [node for node in ast.walk(func) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name]


def test_all_relevant_handlers_resolve_authenticated_actor():
    functions = _functions((BASE / "router.py").read_text())
    for handler in ("generate", "update_title", "validate_batch", "validate", "approve_batch_ready", "approve", "exclude"):
        assert _calls(functions[handler], "request_identity"), handler


def test_mutation_audit_uses_actor_and_no_title_content():
    functions = _functions((BASE / "router.py").read_text())
    for handler in ("update_title", "validate_batch", "validate", "approve", "exclude"):
        events = _calls(functions[handler], "audit")
        assert events, handler
        assert all(any(k.arg == "actor_user_id" for k in event.keywords) for event in events), handler
    title_audit = _calls(functions["update_title"], "audit")[0]
    assert not any(isinstance(arg, ast.Dict) for arg in title_audit.args), "No title content in audit payload"


def test_generation_and_bulk_approval_forward_identity_to_service():
    functions = _functions((BASE / "router.py").read_text())
    for handler, service in (("generate", "generate_drafts"), ("approve_batch_ready", "approve_ready_drafts")):
        calls = _calls(functions[handler], service)
        assert len(calls) == 1
        assert any(key.arg == "actor_user_id" for key in calls[0].keywords)


def test_service_events_persist_actor_without_new_schema():
    generation = (BASE / "service.py").read_text().split("def generate_drafts(", 1)[1].split("def rebase_batch_product_version(", 1)[0]
    approval = (BASE / "validation_service.py").read_text().split("def approve_ready_drafts(", 1)[1]
    assert "actor_user_id=actor_user_id" in generation
    assert "actor_user_id=actor_user_id" in approval
