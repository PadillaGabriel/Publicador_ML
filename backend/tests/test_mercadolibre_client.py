import httpx
import pytest

from app.integrations.mercadolibre import client as client_module
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError


@pytest.fixture(autouse=True)
def _reset_shared_http_client():
    client_module.close_shared_http_client()
    yield
    client_module.close_shared_http_client()


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


def test_validate_item_uses_official_preflight_endpoint_and_accepts_204(monkeypatch):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(204, request=request)

    _use_transport(monkeypatch, handler)
    client = MercadoLibreClient("token")

    response = client.validate_item({"family_name": "Producto", "price": 1000})

    assert response.status_code == 204
    assert seen["method"] == "POST"
    assert seen["path"] == "/items/validate"
    assert b'"family_name":"Producto"' in seen["body"]


def test_shipping_preferences_endpoints_use_authenticated_transport(monkeypatch):
    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers.get("Authorization")))
        return httpx.Response(200, json={"logistics": []}, request=request)

    _use_transport(monkeypatch, handler)
    client = MercadoLibreClient("token")

    assert client.user_shipping_preferences("123") == {"logistics": []}
    assert client.category_shipping_preferences("MLA1") == {"logistics": []}
    assert seen == [
        ("/users/123/shipping_preferences", "Bearer token"),
        ("/categories/MLA1/shipping_preferences", "Bearer token"),
    ]


def test_upload_item_picture_uses_official_multipart_endpoint(monkeypatch, tmp_path):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(201, json={"id": "123-MLA456_092026"}, request=request)

    _use_transport(monkeypatch, handler)
    image_path = tmp_path / "product.jpg"
    image_path.write_bytes(b"fake-jpeg-content")

    result = MercadoLibreClient("token").upload_item_picture(image_path, "image/jpeg")

    assert result["id"] == "123-MLA456_092026"
    assert seen["method"] == "POST"
    assert seen["path"] == "/pictures/items/upload"
    assert seen["content_type"].startswith("multipart/form-data; boundary=")
    assert b'filename="product.jpg"' in seen["body"]
    assert b"fake-jpeg-content" in seen["body"]


def test_client_reuses_one_http_pool_for_multiple_requests(monkeypatch):
    calls = {"clients": 0, "requests": 0}
    real_client = httpx.Client
    transport = httpx.MockTransport(
        lambda request: (
            calls.__setitem__("requests", calls["requests"] + 1)
            or httpx.Response(200, json={"ok": True}, request=request)
        )
    )

    def client_factory(*args, **kwargs):
        calls["clients"] += 1
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr(client_module.httpx, "Client", client_factory)
    client = MercadoLibreClient("token")

    assert client.get("/one") == {"ok": True}
    assert client.get("/two") == {"ok": True}
    assert calls == {"clients": 1, "requests": 2}


def test_item_description_uses_official_description_endpoint(monkeypatch):
    seen = {}

    def handler(request):
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(200, json={"plain_text": "Descripción importada"}, request=request)

    _use_transport(monkeypatch, handler)

    result = MercadoLibreClient("token").item_description("MLA123")

    assert result == {"plain_text": "Descripción importada"}
    assert seen == {"method": "GET", "path": "/items/MLA123/description"}
