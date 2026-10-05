"""Structural tests only. Live PostgreSQL integration remains required."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def source(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_job_requester_and_audit_commit_together():
    section = source("app/publication/router.py").split("def create_publication_job(", 1)[1].split("def export_job(", 1)[0]
    assert "actor, _ = request_identity(db, request)" in section
    assert "requested_by_user_id=actor.id" in section
    assert "actor_user_id=actor.id" in section
    assert section.index("actor_user_id=actor.id") < section.index("db.commit()")


def test_old_jobs_remain_without_invented_owner():
    model = source("app/persistence.py").split("class Job(Base):", 1)[1].split("class JobItem(Base):", 1)[0]
    assert "requested_by_user_id" in model and "nullable=True" in model
    migration = source("migrations/versions/0012_job_requester.py")
    assert 'down_revision = "0011_product_ownership"' in migration
    assert "nullable=True" in migration


def test_upload_authorized_by_owner_not_blanket_rejected():
    section = source("app/operator_access.py").split('if path.startswith("/uploads/"):', 1)[1]
    assert "request_identity(db, request)" in section
    assert "Imágenes pendientes de control por ficha" not in section
    handler = source("app/main.py").split("def serve_upload(", 1)[1].split("mount_static_frontend(", 1)[0]
    assert handler.index("visible_product(db, actor, version.product_master_id)") < handler.index("FileResponse(")


def test_unknown_scoped_commercial_operation_denied():
    assert source("app/operator_account_scope.py").rstrip().endswith('raise HTTPException(status_code=403, detail="Ruta comercial sin clasificación de alcance")')
