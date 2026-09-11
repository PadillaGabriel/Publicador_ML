from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.integrations.mercadolibre.client import MercadoLibreError

_SENSITIVE_KEYS = {
    "access_token",
    "refresh_token",
    "client_secret",
    "authorization",
    "api_key",
    "openai_api_key",
    "oauth_token",
}
_MAX_STRING_LENGTH = 2000
_MAX_LIST_ITEMS = 100


def sanitize_external_payload(value: Any) -> Any:
    """Return an audit-safe copy of a provider payload.

    Mercado Libre validation responses are valuable for debugging, but provider
    payloads must never be trusted to be free of secrets. This sanitizer keeps
    useful validation fields such as ``code``, ``message`` and ``cause`` while
    redacting credential-like keys and bounding unexpectedly large values.
    """
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key.casefold() in _SENSITIVE_KEYS:
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_external_payload(raw_value)
        return sanitized

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize_external_payload(item) for item in list(value)[:_MAX_LIST_ITEMS]]

    if isinstance(value, str):
        return value[:_MAX_STRING_LENGTH]

    return value


def _normalize_causes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_causes = payload.get("cause")
    if raw_causes is None:
        raw_causes = payload.get("causes")
    if not isinstance(raw_causes, list):
        return []

    causes: list[dict[str, Any]] = []
    for raw in raw_causes:
        if isinstance(raw, Mapping):
            item = dict(raw)
            causes.append(
                {
                    "code": item.get("code"),
                    "message": item.get("message") or item.get("description"),
                    "field": item.get("field") or item.get("attribute") or item.get("path"),
                    "type": item.get("type"),
                    "department": item.get("department"),
                }
            )
        else:
            causes.append({"code": None, "message": str(raw), "field": None, "type": None, "department": None})
    return causes


def classify_mercadolibre_error(status_code: int | None) -> str:
    if status_code is None:
        return "MERCADO_LIBRE_EXTERNAL_STATE_UNKNOWN"
    if status_code in {400, 422}:
        return "MERCADO_LIBRE_VALIDATION_ERROR"
    if status_code in {401, 403}:
        return "MERCADO_LIBRE_AUTHORIZATION_ERROR"
    if status_code == 429:
        return "MERCADO_LIBRE_RATE_LIMIT_ERROR"
    if status_code >= 500:
        return "MERCADO_LIBRE_PROVIDER_ERROR"
    return "MERCADO_LIBRE_ERROR"


def build_mercadolibre_error(exc: MercadoLibreError, *, retryable: bool) -> dict[str, Any]:
    payload = sanitize_external_payload(exc.payload or {})
    if not isinstance(payload, dict):
        payload = {"value": payload}

    provider_message = payload.get("message")
    if not isinstance(provider_message, str) or not provider_message.strip():
        provider_message = str(exc)

    return {
        "code": classify_mercadolibre_error(exc.status_code),
        "message": provider_message,
        "http_status": exc.status_code,
        "retryable": retryable,
        "provider_error": payload.get("error"),
        "causes": _normalize_causes(payload),
        "provider_payload": payload,
    }


def format_publication_error(value: dict | None) -> str:
    """Format a persisted publication error for operator-facing exports."""
    if not value:
        return ""

    message = value.get("message")
    code = value.get("code")
    headline = f"{code}: {message}" if code and message else str(message or code or "")

    cause_parts: list[str] = []
    for cause in value.get("causes") or []:
        if not isinstance(cause, dict):
            continue
        cause_code = cause.get("code")
        cause_field = cause.get("field")
        cause_message = cause.get("message")
        prefix = " / ".join(str(part) for part in (cause_code, cause_field) if part)
        if prefix and cause_message:
            cause_parts.append(f"{prefix}: {cause_message}")
        elif cause_message:
            cause_parts.append(str(cause_message))
        elif prefix:
            cause_parts.append(prefix)

    if cause_parts:
        return " | ".join([headline, *cause_parts]) if headline else " | ".join(cause_parts)
    return headline or str(value)


def provider_validation_issues(payload: dict, normalized_schema: dict) -> list[dict]:
    """Translate Mercado Libre validation causes without hardcoding category rules."""

    raw_causes = payload.get("cause") or payload.get("causes") or []
    causes = raw_causes if isinstance(raw_causes, list) else []
    fields = normalized_schema.get("fields") or []
    fields_by_id = {
        str(field.get("id")): field
        for field in fields
        if isinstance(field, dict) and field.get("id")
    }

    issues: list[dict] = []
    for cause in causes:
        if not isinstance(cause, dict):
            continue
        cause_type = str(cause.get("type") or "").strip().casefold()
        if cause_type == "warning":
            continue

        code = str(cause.get("code") or payload.get("error") or "MERCADOLIBRE_VALIDATION_ERROR")
        provider_message = str(cause.get("message") or payload.get("message") or "Validation error").strip()
        provider_field = cause.get("field")

        matched_attribute_id = next(
            (
                attribute_id
                for attribute_id in fields_by_id
                if f"[{attribute_id}]" in provider_message
            ),
            None,
        )
        field = str(provider_field) if provider_field else None
        message = provider_message
        if matched_attribute_id:
            metadata = fields_by_id[matched_attribute_id]
            label = str(metadata.get("label") or matched_attribute_id)
            field = f"attributes.{matched_attribute_id}"
            if code == "item.attribute.missing_conditional_required":
                message = f"Mercado Libre requiere completar {label} para esta publicación."

        issues.append(
            {
                "code": code,
                "field": field,
                "message": message,
                "provider_message": provider_message,
            }
        )

    if issues:
        return issues
    if causes:
        return []

    message = str(payload.get("message") or "Mercado Libre rechazó la validación previa de la publicación.")
    return [
        {
            "code": str(payload.get("error") or "MERCADOLIBRE_VALIDATION_ERROR"),
            "field": None,
            "message": message,
            "provider_message": message,
        }
    ]
