from decimal import Decimal

from app.integrations.mercadolibre.client import PublishResponse
from app.publication.quantity_pricing import sync_b2b_quantity_prices


class FakeClient:
    def __init__(self):
        self.write = None
        self.read_count = 0

    def item_prices(self, item_id, *, show_all=True, display_version=False):
        assert item_id == "MLA123"
        assert show_all is True
        assert display_version is True
        self.read_count += 1
        payload = {
            "version": 13 if self.read_count == 1 else 14,
            "prices": [
                {
                    "id": "1",
                    "type": "standard",
                    "amount": 1000,
                    "currency_id": "ARS",
                    "conditions": {"context_restrictions": []},
                },
                {
                    "id": "old-absolute",
                    "type": "standard",
                    "amount": 950,
                    "currency_id": "ARS",
                    "conditions": {
                        "context_restrictions": ["channel_marketplace", "user_type_business"],
                        "min_purchase_unit": 2,
                    },
                },
            ],
        }
        if self.write is not None:
            payload["price_per_quantity"] = self.write[1]["price_per_quantity"]
        return payload

    def b2b_quantity_price_recommendations(self, **kwargs):
        assert kwargs["quantities"] == [2, 3]
        assert kwargs["standard_amount"] == Decimal("1000")
        return {
            "recommendations": [
                {"quantity": 2, "amount": 960, "is_incoherent_quantity": False, "discount": {"percentage": 4}},
                {"quantity": 3, "amount": 910, "is_incoherent_quantity": False, "discount": {"percentage": 9}},
            ]
        }

    def set_b2b_quantity_discounts(self, item_id, payload, *, version, remove_absolute_pxq=False):
        self.write = (item_id, payload, version, remove_absolute_pxq)
        return PublishResponse(200, {"ok": True})


def test_sync_uses_percentage_endpoint_contract_and_version():
    client = FakeClient()
    result = sync_b2b_quantity_prices(
        client,
        item_id="MLA123",
        tiers=[
            {"min_purchase_unit": 2, "amount": Decimal("950")},
            {"min_purchase_unit": 3, "amount": Decimal("900")},
        ],
        currency_id="ARS",
        base_price=Decimal("1000"),
    )

    item_id, payload, version, remove_absolute = client.write
    assert item_id == "MLA123"
    assert version == "13"
    assert remove_absolute is True
    assert [row["percentage"] for row in payload["price_per_quantity"]] == [5.0, 10.0]
    assert result["http_status"] == 200
    assert result["verified"] == [
        {"min_purchase_unit": 2, "percentage": 5.0},
        {"min_purchase_unit": 3, "percentage": 10.0},
    ]
    assert client.read_count == 2


def test_seller_price_is_not_rejected_or_replaced_by_recommendation():
    client = FakeClient()
    def strict_recommendations(**kwargs):
        return {"recommendations": [
            {"quantity": 2, "amount": 700, "discount": {"percentage": 30}},
            {"quantity": 3, "amount": 650, "discount": {"percentage": 35}},
        ]}
    client.b2b_quantity_price_recommendations = strict_recommendations
    sync_b2b_quantity_prices(
        client, item_id="MLA123",
        tiers=[{"min_purchase_unit": 2, "amount": Decimal("950")},
               {"min_purchase_unit": 3, "amount": Decimal("900")}],
        currency_id="ARS", base_price=Decimal("1000"),
    )
    assert [r["percentage"] for r in client.write[1]["price_per_quantity"]] == [5.0, 10.0]


def test_sync_fails_when_write_is_not_visible_on_readback():
    import pytest
    from app.publication.quantity_pricing import QuantityPricingSyncError

    client = FakeClient()
    original = client.item_prices

    def never_visible(item_id, *, show_all=True, display_version=False):
        result = original(item_id, show_all=show_all, display_version=display_version)
        result.pop("price_per_quantity", None)
        return result

    client.item_prices = never_visible
    with pytest.raises(QuantityPricingSyncError):
        sync_b2b_quantity_prices(
            client,
            item_id="MLA123",
            tiers=[{"min_purchase_unit": 2, "amount": Decimal("950")},
                   {"min_purchase_unit": 3, "amount": Decimal("900")}],
            currency_id="ARS",
            base_price=Decimal("1000"),
        )
