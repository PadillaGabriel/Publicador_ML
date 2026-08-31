import base64
import hashlib
import hmac
import json
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from app.core.config import get_settings


class SecretCipher:
    def __init__(self) -> None:
        key = get_settings().app_encryption_key
        if not key:
            raise RuntimeError(
                "APP_ENCRYPTION_KEY is required. Generate one with Fernet.generate_key()."
            )
        self._fernet = Fernet(key.encode())

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Stored credential cannot be decrypted.",
            ) from exc


def _state_key() -> bytes:
    secret = get_settings().app_secret_key
    if not secret or secret == "change-me":
        raise RuntimeError("APP_SECRET_KEY must be configured before using Mercado Libre OAuth.")
    return secret.encode("utf-8")


def create_oauth_state(ttl_seconds: int = 600) -> str:
    payload = {
        "nonce": secrets.token_urlsafe(24),
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=")
    signature = hmac.new(_state_key(), encoded, hashlib.sha256).digest()
    signed = encoded + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")
    return signed.decode("ascii")


def verify_oauth_state(value: str) -> dict:
    try:
        encoded, signature = value.encode("ascii").split(b".", 1)
        padded_sig = signature + b"=" * (-len(signature) % 4)
        actual = base64.urlsafe_b64decode(padded_sig)
        expected = hmac.new(_state_key(), encoded, hashlib.sha256).digest()
        if not hmac.compare_digest(actual, expected):
            raise ValueError("signature")
        padded = encoded + b"=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired")
        return payload
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="OAuth state inválido o vencido.") from exc
