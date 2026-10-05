"""PostgreSQL-backed, per-username login throttling across API processes.

A transaction advisory lock makes check/authenticate/update atomic for a username.
No plaintext username or client-IP address is persisted in this table.
"""

import hashlib
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.identity import OperatorLoginFailure
from app.operator_auth import normalize_username

WINDOW = timedelta(minutes=15)
MAX_FAILURES = 5


def _key(username: str) -> tuple[str, int]:
    digest = hashlib.sha256(normalize_username(username).encode("utf-8")).digest()
    return digest.hex(), int.from_bytes(digest[:8], "big", signed=True)


def locked_bucket(db: Session, username: str) -> tuple[str, OperatorLoginFailure | None, datetime]:
    """Lock this username until the caller commits/rolls back the transaction."""
    digest, lock_key = _key(username)
    db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})
    bucket = db.scalar(select(OperatorLoginFailure).where(OperatorLoginFailure.username_hash == digest))
    return digest, bucket, utcnow()


def enforce_limit(bucket: OperatorLoginFailure | None, now: datetime) -> None:
    if bucket and bucket.blocked_until and bucket.blocked_until > now:
        retry = max(1, int((bucket.blocked_until - now).total_seconds()) + 1)
        raise HTTPException(status_code=429, detail="Demasiados intentos. Intentá más tarde.",
                            headers={"Retry-After": str(retry)})


def record_failed_login(db: Session, digest: str,
                        bucket: OperatorLoginFailure | None, now: datetime) -> None:
    if bucket is None:
        db.add(OperatorLoginFailure(username_hash=digest, attempts=1,
                                    window_start=now, blocked_until=None))
        return
    if now - bucket.window_start >= WINDOW:
        bucket.window_start = now
        bucket.attempts = 1
        bucket.blocked_until = None
    else:
        bucket.attempts += 1
    if bucket.attempts >= MAX_FAILURES:
        bucket.blocked_until = now + WINDOW


def clear_failures(db: Session, bucket: OperatorLoginFailure | None) -> None:
    if bucket is not None:
        db.delete(bucket)
