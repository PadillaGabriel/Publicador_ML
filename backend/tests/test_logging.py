import logging

from app.core.logging import UvicornAccessSanitizer


def test_uvicorn_access_log_redacts_oauth_query_secrets():
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:1234",
            "GET",
            "/api/accounts/oauth/callback?code=secret-code&state=secret-state&foo=ok",
            "1.1",
            302,
        ),
        exc_info=None,
    )
    assert UvicornAccessSanitizer().filter(record) is True
    path = record.args[2]
    assert "secret-code" not in path
    assert "secret-state" not in path
    assert "foo=ok" in path
    assert "%5BREDACTED%5D" in path
