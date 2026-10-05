"""Unit tests: policy behavior (not a substitute for a real PostgreSQL login test)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.operator_login_limiter import (_key, WINDOW, MAX_FAILURES,
                                        enforce_limit, record_failed_login)


class Recorder:
    def __init__(self):
        self.created = None

    def add(self, obj):
        self.created = obj


def test_username_hash_is_normalized_and_not_plaintext():
    a, lock_a = _key("  USER_A  ")
    b, lock_b = _key("user_a")
    assert (a, lock_a) == (b, lock_b)
    assert a != "user_a"
    assert len(a) == 64


def test_lock_after_five_failures_and_unlock_after_window():
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    rec = Recorder()
    record_failed_login(rec, "d" * 64, None, now)
    row = rec.created
    assert row.attempts == 1
    for _ in range(MAX_FAILURES - 1):
        record_failed_login(rec, "d" * 64, row, now)
    assert row.attempts == MAX_FAILURES
    with pytest.raises(HTTPException) as error:
        enforce_limit(row, now + timedelta(seconds=1))
    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) > 0
    enforce_limit(row, now + WINDOW + timedelta(seconds=1))
    record_failed_login(rec, "d" * 64, row, now + WINDOW + timedelta(seconds=1))
    assert row.attempts == 1 and row.blocked_until is None


def test_below_limit_does_not_block():
    row = SimpleNamespace(attempts=MAX_FAILURES - 1, blocked_until=None)
    enforce_limit(row, datetime.now(timezone.utc))
