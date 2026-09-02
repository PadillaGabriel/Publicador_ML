"""Bounded in-process cache for complete Mercado Libre pricing simulations."""

from collections import OrderedDict
from dataclasses import dataclass, fields
from decimal import Decimal
from threading import RLock
from time import monotonic
from uuid import UUID

from app.pricing.domain.models import MarketplaceEconomics


@dataclass(frozen=True, slots=True)
class PricingCacheKey:
    """Every input that can change a marketplace pricing simulation result."""

    account_id: UUID
    category_or_item_id: str
    listing_type_id: str
    gross_price: Decimal
    logistic_type: str
    shipping_mode: str
    billable_weight: Decimal


class PricingSimulationCache:
    """Small TTL/LRU cache that never persists marketplace economics."""

    def __init__(self, *, max_entries: int = 256, ttl_seconds: float = 300) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_entries = max_entries
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[PricingCacheKey, tuple[float, MarketplaceEconomics]] = (
            OrderedDict()
        )
        self._lock = RLock()

    def get(self, key: PricingCacheKey) -> MarketplaceEconomics | None:
        """Return a non-expired simulation result, if present."""
        with self._lock:
            cached = self._entries.get(key)
            if cached is None:
                return None
            expires_at, economics = cached
            if monotonic() >= expires_at:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return economics

    def put(self, key: PricingCacheKey, economics: MarketplaceEconomics) -> bool:
        """Cache only a complete, usable marketplace response."""
        if not self._is_complete_economics(economics):
            return False
        with self._lock:
            self._entries[key] = (monotonic() + self._ttl_seconds, economics)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return True

    @staticmethod
    def _is_complete_economics(economics: object) -> bool:
        if not isinstance(economics, MarketplaceEconomics):
            return False
        return all(
            isinstance(getattr(economics, field.name), Decimal)
            and getattr(economics, field.name).is_finite()
            for field in fields(MarketplaceEconomics)
        )
