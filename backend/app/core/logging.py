import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SENSITIVE_QUERY_KEYS = {
    "code",
    "state",
    "access_token",
    "refresh_token",
    "client_secret",
}


def _sanitize_path(value: str) -> str:
    if "?" not in value:
        return value
    parts = urlsplit(value)
    sanitized_query = urlencode(
        [
            (key, "[REDACTED]" if key.lower() in _SENSITIVE_QUERY_KEYS else val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, sanitized_query, parts.fragment))


class UvicornAccessSanitizer(logging.Filter):
    """Redacts OAuth/secrets from Uvicorn access-log request paths without hiding lifecycle logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 5 and isinstance(args[2], str):
            mutable = list(args)
            mutable[2] = _sanitize_path(mutable[2])
            record.args = tuple(mutable)
        return True


def configure_logging() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, UvicornAccessSanitizer) for item in logger.filters):
        logger.addFilter(UvicornAccessSanitizer())
