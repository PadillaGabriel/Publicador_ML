import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.audit.service import audit
from app.core.security import SecretCipher
from app.core.time import utcnow
from app.integrations.mercadolibre.client import MercadoLibreError, MercadoLibreOAuthClient
from app.persistence import MercadoLibreAccount


def refresh_account_token(db: Session, account: MercadoLibreAccount) -> str:
    cipher = SecretCipher()
    try:
        refresh_token = cipher.decrypt(account.encrypted_refresh_token or "")
        token_data = MercadoLibreOAuthClient().refresh(refresh_token)
    except (MercadoLibreError, HTTPException) as exc:
        account.auth_status = "AUTH_ERROR"
        audit(
            db,
            "ACCOUNT_TOKEN_REFRESH_FAILED",
            "MercadoLibreAccount",
            str(account.id),
            {"error": str(exc)},
        )
        db.flush()
        raise HTTPException(status_code=401, detail=f"No se pudo renovar Mercado Libre: {exc}") from exc

    access_token = token_data["access_token"]
    new_refresh = token_data.get("refresh_token")
    now = utcnow()
    expires_in = int(token_data.get("expires_in") or 0)

    account.encrypted_access_token = cipher.encrypt(access_token)
    if new_refresh:
        account.encrypted_refresh_token = cipher.encrypt(new_refresh)
    account.token_expires_at = now + timedelta(seconds=expires_in) if expires_in > 0 else None
    account.last_refresh_at = now
    account.auth_status = "CONNECTED"
    audit(db, "ACCOUNT_TOKEN_REFRESHED", "MercadoLibreAccount", str(account.id))
    db.flush()
    return access_token


def load_access_token(db: Session, account_id: uuid.UUID) -> str:
    account = db.get(MercadoLibreAccount, account_id)
    if not account or not account.active:
        raise HTTPException(status_code=404, detail="Cuenta de Mercado Libre no encontrada.")

    if (
        account.token_expires_at
        and account.encrypted_refresh_token
        and account.token_expires_at <= utcnow() + timedelta(minutes=5)
    ):
        return refresh_account_token(db, account)

    return SecretCipher().decrypt(account.encrypted_access_token)
