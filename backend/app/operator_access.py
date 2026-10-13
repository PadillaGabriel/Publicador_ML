"""Central authentication boundary for the existing API routes."""

from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.operator_auth import request_identity, require_permission
from app.operator_account_scope import scope_operation

PUBLIC_API_PATHS = frozenset({
    "/api/operator-auth/login",
    "/api/accounts/oauth/callback",  # Signed OAuth state, received as a cross-site redirect.
})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

def same_origin(request: Request) -> bool:
    """Compare Origin with the configured public app origin, never a client-controlled Host."""
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin:
        return False
    settings = get_settings()
    allowed = {value.rstrip("/") for value in settings.cors_origin_list}
    if settings.public_base_url:
        allowed.add(settings.public_base_url.rstrip("/"))
    # Add deployment's canonical frontend origin, if configured.
    allowed.add(settings.frontend_url.rstrip("/"))
    return origin in allowed and urlsplit(origin).scheme in {"http", "https"}

def required_action(path: str, method: str) -> str | None:
    """Conservative role protection for known mutations; additions must be classified."""
    if method in SAFE_METHODS:
        if path == "/api/accounts/oauth/start":
            return "manage_ml_accounts"
        return None
    if path.startswith("/api/product-edit-leases"):
        return "edit_own_product"
    if path.startswith("/api/operator-users") or path.startswith("/api/operator-account-grants"):
        return "manage_users"
    if path.startswith("/api/accounts"):
        return "manage_ml_accounts"
    if path == "/api/pricing/profile" and method == "PUT":
        return "configure_global"
    if path.startswith("/api/pricing/"):
        return None  # Calculation is read-only even when using POST.
    if path.startswith("/api/products"):
        return "create_product" if path == "/api/products" and method == "POST" else "edit_own_product"
    if path.startswith("/api/publication-import"):
        return "create_product"
    if path.startswith("/api/drafts") or path.startswith("/api/publication"):
        return "publish"
    if path.startswith("/api/jobs"):
        return "publish"
    if path.startswith("/api/title-intelligence"):
        return "create_product"
    if path.startswith("/api/catalog"):
        return None
    return "__unclassified__"

async def operator_access_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)
    if path.startswith("/api/") and path not in PUBLIC_API_PATHS and path not in {"/api/operator-auth/me", "/api/operator-auth/logout"}:
        try:
            with SessionLocal() as db:
                user, _ = request_identity(db, request)
                action = required_action(path, request.method)
                if action:
                    require_permission(user.role, action)
                if user.role == "OPERATOR" and path.startswith((
                    "/api/accounts", "/api/drafts", "/api/publication", "/api/jobs",
                    "/api/products", "/api/title-intelligence", "/api/publication-import",
                )):
                    # Do not interpret form or multipart bodies as account identifiers.
                    # Requests with invalid JSON fail closed in the scope service.
                    payload = None
                    if request.method not in SAFE_METHODS and path.startswith((
                        "/api/drafts", "/api/publication", "/api/publication-import",
                        "/api/title-intelligence",
                    )):
                        try:
                            payload = await request.json()
                        except (ValueError, UnicodeDecodeError):
                            payload = None
                    if payload is not None and not isinstance(payload, dict):
                        payload = None
                    scope_operation(db, user, path, request.method,
                                    dict(request.query_params), payload)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if (path.startswith("/api/") or path.startswith("/uploads/")) and request.method not in SAFE_METHODS:
        if path != "/api/accounts/oauth/callback" and not same_origin(request):
            return JSONResponse({"detail": "Origen de solicitud no permitido"}, status_code=403)
    if path.startswith("/uploads/"):
        try:
            with SessionLocal() as db:
                user, _ = request_identity(db, request)
                # Authentication is required for every upload. The /uploads/{image_id}
                # handler checks product ownership before serving the bytes.
                # Do not reject operators here: that would bypass the per-image check.
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    response = await call_next(request)
    if path.startswith("/api/") or path.startswith("/uploads/"):
        response.headers["Cache-Control"] = "no-store"
    return response
