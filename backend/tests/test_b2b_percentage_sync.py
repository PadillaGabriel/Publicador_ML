from decimal import Decimal

from app.integrations.mercadolibre.client import PublishResponse
from app.publication.quantity_pricing import sync_b2b_quantity_prices


class FakeClient:
    def __init__(self):
        self.write = None

    def item_prices(self, item_id, *, show_all=True, display_version=False):
        assert item_id == "MLA123"
        assert show_all is True
        assert display_version is True
        return {
            "version": 13,
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
