import httpx
import pytest

from app.integrations.mercadolibre import client as client_module
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError


def _use_transport(monkeypatch, handler) -> None:
    real_client = httpx.Client
    transport = httpx.MockTransport(handler)

    def client_factory(*args, **kwargs):
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(client_module.httpx, "Client", client_factory)


@pytest.mark.parametrize("method", ["get", "post"])
def test_client_converts_connection_failures_to_mercadolibre_error(monkeypatch, method):
    """Catches non-timeout request failures escaping the integration boundary."""

    def connection_failure(request):
        raise httpx.ConnectError("connection failed", request=request)

    _use_transport(monkeypatch, connection_failure)
    client = MercadoLibreClient("token")

    with pytest.raises(MercadoLibreError) as exc_info:
        if method == "get":
            client.get("/categories/MLA1")
        else:
            client.post("/items", {"title": "Producto"})

    assert exc_info.value.status_code is None
    assert exc_info.value.retryable is True
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)


@pytest.mark.parametrize(
    ("method", "status_code", "expected_retryable"),
    [("get", 400, False), ("post", 503, True)],
)
def test_client_preserves_http_error_classification(
    monkeypatch,
    method,
    status_code,
    expected_retryable,
):
    """Catches transport handling from flattening classified HTTP responses."""

    def http_error(request):
        return httpx.Response(
            status_code,
            json={"message": "provider error"},
            request=request,
        )

    _use_transport(monkeypatch, http_error)
    client = MercadoLibreClient("token")

    with pytest.raises(MercadoLibreError) as exc_info:
        if method == "get":
            client.get("/categories/MLA1")
        else:
            client.post("/items", {"title": "Producto"})

    assert exc_info.value.status_code == status_code
    assert exc_info.value.payload == {"message": "provider error"}
    assert exc_info.value.retryable is expected_retryable
