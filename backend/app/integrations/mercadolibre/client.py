from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings


class MercadoLibreError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}

    @property
    def retryable(self) -> bool:
        return self.status_code in {429, 500, 502, 503, 504} or self.status_code is None


@dataclass(slots=True)
class PublishResponse:
    status_code: int
    payload: dict


class MercadoLibreClient:
    def __init__(self, access_token: str | None = None):
        settings = get_settings()
        self._base_url = settings.ml_api_base_url.rstrip("/")
        self._timeout = settings.ml_request_timeout_seconds
        self._access_token = access_token

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    def get(self, path: str, *, extra_headers: dict[str, str] | None = None) -> dict | list:
        try:
            with httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={**self._headers(), **(extra_headers or {})},
            ) as client:
                response = client.get(path)
        except httpx.TimeoutException as exc:
            raise MercadoLibreError("Mercado Libre request timed out.") from exc
        self._raise(response)
        return response.json()

    def post(self, path: str, payload: dict) -> PublishResponse:
        try:
            with httpx.Client(
                base_url=self._base_url,
                timeout=self._timeout,
                headers={**self._headers(), "Content-Type": "application/json"},
            ) as client:
                response = client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise MercadoLibreError("Mercado Libre publish request timed out.") from exc
        if response.is_error:
            body = self._safe_json(response)
            raise MercadoLibreError(
                f"Mercado Libre HTTP {response.status_code}",
                response.status_code,
                body,
            )
        return PublishResponse(response.status_code, self._safe_json(response))

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict:
        try:
            value = response.json()
            return value if isinstance(value, dict) else {"value": value}
        except ValueError:
            return {"raw": response.text[:4000]}

    def _raise(self, response: httpx.Response) -> None:
        if response.is_error:
            raise MercadoLibreError(
                f"Mercado Libre HTTP {response.status_code}",
                response.status_code,
                self._safe_json(response),
            )

    def me(self) -> dict:
        value = self.get("/users/me")
        assert isinstance(value, dict)
        return value

    def site_categories(self, site_id: str) -> list[dict]:
        value = self.get(f"/sites/{site_id}/categories")
        if not isinstance(value, list):
            raise MercadoLibreError("Unexpected categories response.")
        return value


    def category_suggestions(self, site_id: str, query: str, limit: int = 8) -> list[dict]:
        params = urlencode({"q": query, "limit": limit})
        value = self.get(f"/sites/{site_id}/domain_discovery/search?{params}")
        if not isinstance(value, list):
            raise MercadoLibreError("Unexpected category suggestions response.")
        return value

    def category(self, category_id: str) -> dict:
        value = self.get(f"/categories/{category_id}")
        assert isinstance(value, dict)
        return value

    def category_attributes(self, category_id: str) -> list[dict]:
        value = self.get(f"/categories/{category_id}/attributes")
        if not isinstance(value, list):
            raise MercadoLibreError("Unexpected category attributes response.")
        return value

    def available_listing_types(self, seller_id: str, category_id: str) -> dict:
        params = urlencode({"category_id": category_id})
        value = self.get(f"/users/{seller_id}/available_listing_types?{params}")
        if not isinstance(value, dict):
            raise MercadoLibreError("Unexpected available listing types response.")
        return value

    def category_trends(self, site_id: str, category_id: str) -> list[str]:
        value = self.get(f"/trends/{site_id}/{category_id}")
        if not isinstance(value, list):
            raise MercadoLibreError("Unexpected category trends response.")

        terms: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            keyword = str(item.get("keyword") or "").strip()
            normalized = keyword.casefold()
            if keyword and normalized not in seen:
                seen.add(normalized)
                terms.append(keyword)
        return terms

    def create_item(self, payload: dict) -> PublishResponse:
        return self.post("/items", payload)

    def create_item_description(self, item_id: str, plain_text: str) -> PublishResponse:
        return self.post(f"/items/{item_id}/description", {"plain_text": plain_text})

    def item(self, item_id: str) -> dict:
        value = self.get(f"/items/{item_id}")
        if not isinstance(value, dict):
            raise MercadoLibreError("Unexpected item response.")
        return value

    def listing_prices(
        self,
        *,
        site_id: str,
        category_id: str,
        listing_type_id: str,
        price: object,
        currency_id: str,
        logistic_type: str | None = None,
        shipping_mode: str | None = None,
    ) -> list[dict] | dict:
        params = {
            "category_id": category_id,
            "listing_type_id": listing_type_id,
            "price": str(price),
            "currency_id": currency_id,
        }
        if logistic_type is not None:
            params["logistic_type"] = logistic_type
        if shipping_mode is not None:
            params["shipping_mode"] = shipping_mode
        return self.get(f"/sites/{site_id}/listing_prices?{urlencode(params)}")

    def item_prices(self, item_id: str, *, show_all: bool = True) -> dict:
        value = self.get(
            f"/items/{item_id}/prices",
            extra_headers={"show-all-prices": "true"} if show_all else None,
        )
        if not isinstance(value, dict):
            raise MercadoLibreError("Unexpected item prices response.")
        return value

    def set_b2b_quantity_prices(self, item_id: str, payload: dict) -> PublishResponse:
        return self.post(f"/items/{item_id}/prices/standard/quantity", payload)


class MercadoLibreOAuthClient:
    """OAuth transport isolated from account/domain logic."""

    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self._timeout = settings.ml_request_timeout_seconds

    def ensure_configured(self) -> None:
        if not self.settings.ml_oauth_configured:
            raise MercadoLibreError(
                "Mercado Libre OAuth no está configurado: faltan ML_CLIENT_ID, "
                "ML_CLIENT_SECRET o ML_REDIRECT_URI."
            )

    def authorization_url(self, state: str) -> str:
        self.ensure_configured()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.ml_client_id,
                "redirect_uri": self.settings.ml_redirect_uri,
                "state": state,
            }
        )
        return f"{self.settings.ml_auth_base_url.rstrip('/')}/authorization?{query}"

    def exchange_code(self, code: str) -> dict:
        self.ensure_configured()
        return self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": self.settings.ml_client_id,
                "client_secret": self.settings.ml_client_secret,
                "code": code,
                "redirect_uri": self.settings.ml_redirect_uri,
            }
        )

    def refresh(self, refresh_token: str) -> dict:
        self.ensure_configured()
        return self._token_request(
            {
                "grant_type": "refresh_token",
                "client_id": self.settings.ml_client_id,
                "client_secret": self.settings.ml_client_secret,
                "refresh_token": refresh_token,
            }
        )

    def _token_request(self, data: dict[str, str]) -> dict:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self.settings.ml_api_base_url.rstrip('/')}/oauth/token",
                    data=data,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
        except httpx.TimeoutException as exc:
            raise MercadoLibreError("Mercado Libre OAuth request timed out.") from exc

        if response.is_error:
            raise MercadoLibreError(
                f"Mercado Libre OAuth HTTP {response.status_code}",
                response.status_code,
                MercadoLibreClient._safe_json(response),
            )
        payload = MercadoLibreClient._safe_json(response)
        if not payload.get("access_token"):
            raise MercadoLibreError("Mercado Libre OAuth response did not include access_token.")
        return payload
