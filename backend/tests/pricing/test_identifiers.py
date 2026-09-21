import pytest

from app.pricing.identifiers import normalize_mla_item_id
from app.pricing.schemas import ExistingListingPricingRequest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MLA123456789", "MLA123456789"),
        ("mla123456789", "MLA123456789"),
        ("123456789", "MLA123456789"),
        (
            "https://articulo.mercadolibre.com.ar/MLA-123456789-producto-_JM",
            "MLA123456789",
        ),
    ],
)
def test_normalize_mla_item_id_accepts_supported_operator_inputs(raw, expected):
    assert normalize_mla_item_id(raw) == expected


def test_existing_listing_request_normalizes_item_id_before_length_validation():
    request = ExistingListingPricingRequest(
        item_id="https://articulo.mercadolibre.com.ar/MLA-123456789-producto-_JM"
    )
    assert request.item_id == "MLA123456789"


def test_normalize_mla_item_id_rejects_unrelated_text():
    with pytest.raises(ValueError, match="MLA válido"):
        normalize_mla_item_id("producto cualquiera")
