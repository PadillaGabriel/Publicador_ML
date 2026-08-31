import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.accounts.service import refresh_account_token
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import SecretCipher, create_oauth_state, verify_oauth_state
from app.core.time import utcnow
from app.integrations.mercadolibre.client import (
    MercadoLibreClient,
    MercadoLibreError,
    MercadoLibreOAuthClient,
)
from app.persistence import MercadoLibreAccount

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class AccountCreate(BaseModel):
    """Temporary/manual bridge while the publisher owns a dedicated OAuth callback."""

    nickname: str = Field(min_length=1, max_length=120)
    access_token: str = Field(min_length=10)
    site_id: str = Field(default="MLA", min_length=2, max_length=10)


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nickname: str
    seller_id: str | None
    site_id: str
    auth_status: str
    active: bool
    connected_at: datetime | None = None
    token_expires_at: datetime | None = None


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return db.scalars(select(MercadoLibreAccount).order_by(MercadoLibreAccount.created_at)).all()


@router.get("/oauth/status")
def oauth_status():
    settings = get_settings()
    return {
        "configured": settings.ml_oauth_configured,
        "redirect_uri": settings.ml_redirect_uri or None,
        "callback_is_local_publisher": (
            bool(settings.ml_redirect_uri)
            and settings.ml_redirect_uri.rstrip("/").endswith("/api/accounts/oauth/callback")
        ),
    }


@router.get("/oauth/start")
def oauth_start():
    try:
        client = MercadoLibreOAuthClient()
        state = create_oauth_state()
        return {"authorization_url": client.authorization_url(state)}
    except (MercadoLibreError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/oauth/callback")
def oauth_callback(
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
    db: Session = Depends(get_db),
):
    verify_oauth_state(state)
    try:
        token_data = MercadoLibreOAuthClient().exchange_code(code)
        access_token = token_data["access_token"]
        me = MercadoLibreClient(access_token).me()
    except MercadoLibreError as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo conectar Mercado Libre: {exc}") from exc

    seller_id = str(me.get("id")) if me.get("id") is not None else None
    if not seller_id:
        raise HTTPException(status_code=400, detail="Mercado Libre no devolvió seller_id.")

    cipher = SecretCipher()
    now = utcnow()
    expires_in = int(token_data.get("expires_in") or 0)
    expires_at = now + timedelta(seconds=expires_in) if expires_in > 0 else None
    refresh_token = token_data.get("refresh_token")

    account = db.scalar(select(MercadoLibreAccount).where(MercadoLibreAccount.seller_id == seller_id))
    created = account is None
    if account is None:
        account = MercadoLibreAccount(
            nickname=str(me.get("nickname") or f"ML {seller_id}"),
            seller_id=seller_id,
            site_id=str(me.get("site_id") or get_settings().ml_site_id),
            encrypted_access_token=cipher.encrypt(access_token),
            encrypted_refresh_token=cipher.encrypt(refresh_token) if refresh_token else None,
            token_expires_at=expires_at,
            connected_at=now,
            auth_status="CONNECTED",
            active=True,
        )
        db.add(account)
    else:
        account.nickname = str(me.get("nickname") or account.nickname)
        account.site_id = str(me.get("site_id") or account.site_id)
        account.encrypted_access_token = cipher.encrypt(access_token)
        if refresh_token:
            account.encrypted_refresh_token = cipher.encrypt(refresh_token)
        account.token_expires_at = expires_at
        account.connected_at = now
        account.auth_status = "CONNECTED"
        account.active = True

    db.flush()
    audit(
        db,
        "ACCOUNT_OAUTH_CONNECTED" if created else "ACCOUNT_OAUTH_RECONNECTED",
        "MercadoLibreAccount",
        str(account.id),
        {"seller_id": seller_id},
    )
    db.commit()

    frontend = get_settings().frontend_url.rstrip("/")
    return RedirectResponse(f"{frontend}/?ml_connected=1&account_id={account.id}", status_code=302)


@router.post("", response_model=AccountOut)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    """Temporary token-based connection for development/transition only."""

    cipher = SecretCipher()
    try:
        me = MercadoLibreClient(payload.access_token).me()
        seller_id = str(me.get("id")) if me.get("id") is not None else None
    except MercadoLibreError as exc:
        raise HTTPException(status_code=400, detail=f"Token Mercado Libre inválido: {exc}") from exc

    if not seller_id:
        raise HTTPException(status_code=400, detail="Mercado Libre no devolvió seller_id.")

    existing = db.scalar(select(MercadoLibreAccount).where(MercadoLibreAccount.seller_id == seller_id))
    if existing:
        existing.nickname = str(me.get("nickname") or payload.nickname)
        existing.site_id = str(me.get("site_id") or payload.site_id)
        existing.encrypted_access_token = cipher.encrypt(payload.access_token)
        existing.auth_status = "CONNECTED_MANUAL"
        existing.active = True
        existing.connected_at = utcnow()
        account = existing
        event = "ACCOUNT_MANUAL_RECONNECTED"
    else:
        account = MercadoLibreAccount(
            nickname=str(me.get("nickname") or payload.nickname),
            seller_id=seller_id,
            site_id=str(me.get("site_id") or payload.site_id),
            encrypted_access_token=cipher.encrypt(payload.access_token),
            auth_status="CONNECTED_MANUAL",
        )
        db.add(account)
        event = "ACCOUNT_MANUAL_CONNECTED"

    db.flush()
    audit(db, event, "MercadoLibreAccount", str(account.id), {"seller_id": seller_id})
    db.commit()
    db.refresh(account)
    return account


@router.post("/{account_id}/refresh", response_model=AccountOut)
def refresh_account(account_id: uuid.UUID, db: Session = Depends(get_db)):
    account = db.get(MercadoLibreAccount, account_id)
    if not account or not account.active:
        raise HTTPException(status_code=404, detail="Mercado Libre account not found.")
    if not account.encrypted_refresh_token:
        raise HTTPException(
            status_code=409,
            detail="La cuenta no tiene refresh_token. Reconectala mediante OAuth.",
        )
    refresh_account_token(db, account)
    db.commit()
    db.refresh(account)
    return account


