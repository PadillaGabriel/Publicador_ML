"""Internal operator authentication; independent of Mercado Libre OAuth."""

import hashlib
import hmac
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request, status
from app.identity_policy import Role, permitted
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.identity import OperatorSession, OperatorUser

COOKIE_NAME = "ml_operator_session"
SESSION_LIFETIME = timedelta(hours=8)
PASSWORD_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 1024:
        raise ValueError("Password must contain between 12 and 1024 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def check_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_str, salt_str, expected_str = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        if not 100_000 <= iterations <= 2_000_000:
            return False
        salt = bytes.fromhex(salt_str)
        expected = bytes.fromhex(expected_str)
        if len(salt) != 16 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError):
        return False


def normalize_username(username: str) -> str:
    return username.strip().lower()


def authenticate(db: Session, username: str, password: str) -> OperatorUser | None:
    user = db.scalar(select(OperatorUser).where(OperatorUser.username == normalize_username(username)))
    # Always derive a hash to minimize timing differences for unknown users.
    if user is None:
        hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes(16), PASSWORD_ITERATIONS)
        return None
    return user if user.active and check_password(password, user.password_hash) else None


def create_session(db: Session, user: OperatorUser) -> tuple[str, OperatorSession]:
    token = secrets.token_urlsafe(48)
    session = OperatorSession(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
        expires_at=utcnow() + SESSION_LIFETIME,
    )
    db.add(session)
    db.flush()
    return token, session


def resolve_session(db: Session, raw_token: str | None) -> tuple[OperatorUser, OperatorSession] | None:
    if not raw_token:
        return None
    digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    session = db.scalar(select(OperatorSession).where(OperatorSession.token_hash == digest))
    if session is None or session.revoked_at is not None or session.expires_at <= utcnow():
        return None
    user = db.get(OperatorUser, session.user_id)
    if user is None or not user.active:
        return None
    return user, session


def request_identity(db: Session, request: Request) -> tuple[OperatorUser, OperatorSession]:
    identity = resolve_session(db, request.cookies.get(COOKIE_NAME))
    if identity is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión no válida o caducada")
    return identity


def require_permission(role: str, action: str) -> None:
    """Deny unknown roles and unknown operations, even for administrators."""
    try:
        allowed = permitted(Role(role), action)
    except ValueError:
        allowed = False
    if not allowed:
        raise HTTPException(status_code=403, detail="No tenés permiso para esta operación")
