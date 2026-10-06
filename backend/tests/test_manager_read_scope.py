"""Fast, isolated DB-level integration tests of manager visibility.

SQLite is used only to test relational scoping and pagination. PostgreSQL QA
and live Mercado Libre tests are separate release gates.
"""

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app import manager_router
from app.core.db import Base
from app.identity import OperatorAccountGrant, OperatorUser
from app.persistence import (
    AuditEvent, DraftBatch, Job, JobItem, MercadoLibreAccount,
    ProductMaster, ProductVersion, Publication, PublicationDraft,
)


@compiles(JSONB, "sqlite")
def jsonb_sqlite(element, compiler, **kwargs):
    return "JSON"


@pytest.fixture
def example(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = OperatorUser(username="qaadmin", password_hash="x", display_name="Admin", role="ADMIN")
        first = OperatorUser(username="qaone", password_hash="x", display_name="Primero", role="OPERATOR")
        second = OperatorUser(username="qatwo", password_hash="x", display_name="Segundo", role="OPERATOR")
        db.add_all([admin, first, second])
        db.flush()
        account = MercadoLibreAccount(nickname="Cuenta A", encrypted_access_token="cipher-A", site_id="MLA")
        db.add(account)
        db.flush()
        db.add_all([OperatorAccountGrant(user_id=first.id, account_id=account.id),
                    OperatorAccountGrant(user_id=second.id, account_id=account.id)])
        rows = []
        for idx, owner in enumerate([first, second]):
            master = ProductMaster(internal_sku=f"QA-PRODUCT-{idx}", internal_name="Test", created_by_user_id=owner.id)
            db.add(master)
            db.flush()
            version = ProductVersion(product_master_id=master.id, version_number=1,
                                     category_id="MLA000", title_reference="Test", price=Decimal("100"),
                                     quantity=1)
            db.add(version)
            db.flush()
            batch = DraftBatch(product_version_id=version.id, account_id=account.id, requested_count=1)
            db.add(batch)
            db.flush()
            draft = PublicationDraft(batch_id=batch.id, sequence_number=1, title=f"Producto {idx}",
                                     idempotency_key=str(uuid.uuid4()))
            db.add(draft)
            db.flush()
            pub = Publication(draft_id=draft.id, account_id=account.id, item_id=f"MLA900{idx}", status="PUBLISHED")
            job = Job(total=1, status="COMPLETED", requested_by_user_id=owner.id)
            db.add_all([pub, job])
            db.flush()
            db.add(JobItem(job_id=job.id, draft_id=draft.id, status="COMPLETED"))
            rows.append((master, job, account))
        db.add(AuditEvent(event_type="TEST_EVENT", entity_type="Test", entity_id="test",
                          actor_user_id=first.id))
        db.commit()
        actor = first
        monkeypatch.setattr(manager_router, "request_identity", lambda db, req: (actor, None))
        yield db, admin, first, second, rows
    engine.dispose()


def _pub(db):
    return manager_router.list_publications(request=None, q="", account_id=None, status="",
                                            limit=25, offset=0, db=db)


def _jobs(db):
    return manager_router.list_jobs(request=None, status="", limit=25, offset=0, db=db)


def test_operator_sees_only_own_publications_and_jobs(example, monkeypatch):
    db, admin, first, second, rows = example
    assert [item["sku"] for item in _pub(db)["items"]] == [rows[0][0].internal_sku]
    assert [item["id"] for item in _jobs(db)["items"]] == [str(rows[0][1].id)]
    monkeypatch.setattr(manager_router, "request_identity", lambda db, req: (second, None))
    assert [item["sku"] for item in _pub(db)["items"]] == [rows[1][0].internal_sku]
    assert [item["id"] for item in _jobs(db)["items"]] == [str(rows[1][1].id)]
    monkeypatch.setattr(manager_router, "request_identity", lambda db, req: (admin, None))
    assert _pub(db)["total"] == 2
    assert _jobs(db)["total"] == 2


def test_grant_removed_denies_listing_and_jobs(example):
    db, admin, first, second, rows = example
    db.query(OperatorAccountGrant).filter(OperatorAccountGrant.user_id == first.id).delete()
    db.flush()
    assert _pub(db)["items"] == []
    assert _jobs(db)["items"] == []


def test_mixed_job_not_visible_by_partial_ownership(example):
    db, admin, first, second, rows = example
    mixed = Job(total=2, status="COMPLETED", requested_by_user_id=first.id)
    db.add(mixed)
    db.flush()
    drafts = db.query(PublicationDraft).order_by(PublicationDraft.title).all()
    db.add_all([JobItem(job_id=mixed.id, draft_id=draft.id, status="COMPLETED") for draft in drafts])
    db.flush()
    visible = _jobs(db)
    assert visible["total"] == 1
    assert str(mixed.id) not in [item["id"] for item in visible["items"]]


def test_publication_exact_search_and_pagination(example, monkeypatch):
    db, admin, first, second, rows = example
    monkeypatch.setattr(manager_router, "request_identity", lambda db, req: (admin, None))
    result = manager_router.list_publications(request=None, q="MLA9001", account_id=None,
                                               status="", limit=25, offset=0, db=db)
    assert result["total"] == 1
    assert result["items"][0]["sku"] == "QA-PRODUCT-1"
    assert manager_router.list_publications(request=None, q="", account_id=None,
                                             status="", limit=1, offset=1, db=db)["total"] == 2


def test_audit_restricted_to_management_roles(example, monkeypatch):
    db, admin, first, second, rows = example
    with pytest.raises(HTTPException) as error:
        manager_router.list_audit_events(request=None, event_type="", limit=25, offset=0, db=db)
    assert error.value.status_code == 403
    monkeypatch.setattr(manager_router, "request_identity", lambda db, req: (admin, None))
    result = manager_router.list_audit_events(request=None, event_type="", limit=25, offset=0, db=db)
    assert result["total"] == 1
    assert result["items"][0]["actor_name"] == "Primero"
    assert "payload" not in result["items"][0]
