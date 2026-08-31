from app.integrations.mercadolibre.client import MercadoLibreError
from app.publication.errors import build_mercadolibre_error, sanitize_external_payload


def test_external_payload_sanitizer_preserves_validation_code_and_redacts_secrets():
    payload = {
        "message": "Validation error",
        "access_token": "secret-token",
        "cause": [{"code": "item.invalid", "message": "Invalid field", "field": "title"}],
    }

    sanitized = sanitize_external_payload(payload)

    assert sanitized["access_token"] == "[REDACTED]"
    assert sanitized["cause"][0]["code"] == "item.invalid"
    assert sanitized["cause"][0]["field"] == "title"


def test_mercadolibre_400_is_normalized_with_causes():
    exc = MercadoLibreError(
        "Mercado Libre HTTP 400",
        status_code=400,
        payload={
            "error": "validation_error",
            "message": "Validation error",
            "cause": [
                {"code": "item.attributes.missing", "message": "Missing attribute", "field": "BRAND"}
            ],
        },
    )

    error = build_mercadolibre_error(exc, retryable=False)

    assert error["code"] == "MERCADO_LIBRE_VALIDATION_ERROR"
    assert error["message"] == "Validation error"
    assert error["provider_error"] == "validation_error"
    assert error["http_status"] == 400
    assert error["retryable"] is False
    assert error["causes"] == [
        {
            "code": "item.attributes.missing",
            "message": "Missing attribute",
            "field": "BRAND",
            "type": None,
            "department": None,
        }
    ]


def test_export_error_text_includes_provider_causes():
    from app.publication.errors import format_publication_error

    text = format_publication_error(
        {
            "code": "MERCADO_LIBRE_VALIDATION_ERROR",
            "message": "Validation error",
            "causes": [
                {"code": "item.attributes.missing", "field": "BRAND", "message": "Missing attribute"}
            ],
        }
    )

    assert "MERCADO_LIBRE_VALIDATION_ERROR" in text
    assert "item.attributes.missing" in text
    assert "BRAND" in text
    assert "Missing attribute" in text
