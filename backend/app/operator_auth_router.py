"""Operator login endpoints. Route access cutover is a separate coordinated release."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.config import get_settings
from app.core.time import utcnow
from app.operator_auth import COOKIE_NAME, SESSION_LIFETIME, authenticate, create_session, request_identity
from app.operator_access import same_origin
from app.operator_login_limiter import (locked_bucket, enforce_limit,
                                        record_failed_login, clear_failures)

router = APIRouter(prefix="/api/operator-auth", tags=["operator-auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)


def public_user(user):
    return {"id": str(user.id), "username": user.username, "display_name": user.display_name, "role": user.role}


@router.post("/login")
def login(data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    # Browser-side requests use same-origin cookies; protect against login CSRF too.
    if not same_origin(request):
        raise HTTPException(status_code=403, detail="Origen no permitido")
    digest, bucket, now = locked_bucket(db, data.username)
    enforce_limit(bucket, now)
    user = authenticate(db, data.username, data.password)
    if user is None:
        record_failed_login(db, digest, bucket, now)
        db.commit()  # Persist failures even when the response is HTTP 401.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    clear_failures(db, bucket)
    token, _ = create_session(db, user)
    db.commit()
    response.set_cookie(
        COOKIE_NAME, token, secure=get_settings().public_base_url.startswith("https://"),
        httponly=True, samesite="strict", path="/",
        max_age=int(SESSION_LIFETIME.total_seconds()),
    )
    response.headers["Cache-Control"] = "no-store"
    return public_user(user)


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    user, _ = request_identity(db, request)
    return public_user(user)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    _, session = request_identity(db, request)
    session.revoked_at = utcnow()
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    response.headers["Cache-Control"] = "no-store"
