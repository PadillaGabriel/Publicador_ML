"""Pure authorization contract tests, independent of a live PostgreSQL instance."""
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import product_edit_leases as leases


def _db(product):
    return SimpleNamespace(scalar=lambda _: product)


def test_legacy_product_is_admin_only():
    product = SimpleNamespace(id=uuid.uuid4(), created_by_user_id=None)
    with pytest.raises(HTTPException) as error:
        leases.visible_product(_db(product), SimpleNamespace(id=uuid.uuid4(), role="OPERATOR"), product.id)
    assert error.value.status_code == 403
    assert leases.visible_product(_db(product), SimpleNamespace(id=uuid.uuid4(), role="ADMIN"), product.id) is product


def test_operator_only_owns_own_product():
    creator = uuid.uuid4()
    product = SimpleNamespace(id=uuid.uuid4(), created_by_user_id=creator)
    assert leases.visible_product(_db(product), SimpleNamespace(id=creator, role="OPERATOR"), product.id) is product
    with pytest.raises(HTTPException) as error:
        leases.visible_product(_db(product), SimpleNamespace(id=uuid.uuid4(), role="OPERATOR"), product.id)
    assert error.value.status_code == 403


def test_lease_snapshot_excludes_expired():
    assert leases.lease_snapshot(SimpleNamespace(expires_at=leases.utcnow() - timedelta(seconds=1))) == {"locked": False, "expires_at": None}
    assert leases.lease_snapshot(None) == {"locked": False, "expires_at": None}


def test_write_requires_token_before_any_db_lookup():
    with pytest.raises(HTTPException) as exc:
        leases.require_edit_token(None, None, None, uuid.uuid4(), None)
    assert exc.value.status_code == 428


def test_write_rejects_bad_token():
    with pytest.raises(HTTPException) as exc:
        leases.require_edit_token(None, None, None, uuid.uuid4(), "not-a-uuid")
    assert exc.value.status_code == 422


def test_wrong_session_or_token_denied():
    product_id = uuid.uuid4()
    user_id = uuid.uuid4()
    token = uuid.uuid4()
    product = SimpleNamespace(id=product_id, created_by_user_id=user_id)
    lease = SimpleNamespace(session_id=uuid.uuid4(), owner_user_id=user_id,
                            fencing_token=token, expires_at=leases.utcnow() + timedelta(minutes=1))
    db = SimpleNamespace(scalar=lambda _: product, get=lambda *_: lease)
    user = SimpleNamespace(id=user_id, role="OPERATOR")
    with pytest.raises(HTTPException) as exc:
        leases.require_edit_token(db, user, SimpleNamespace(id=uuid.uuid4()), product_id, str(token))
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        leases.require_edit_token(db, user, SimpleNamespace(id=lease.session_id), product_id, str(uuid.uuid4()))
    assert exc.value.status_code == 409
