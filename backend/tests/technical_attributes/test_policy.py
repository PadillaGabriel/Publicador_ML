from app.technical_attributes.policy import is_reusable_attribute


def test_policy_excludes_publication_identifiers():
    assert is_reusable_attribute("BRAND", source_category_id="MLA1") is True
    assert is_reusable_attribute("SELLER_SKU", source_category_id="MLA1") is False
    assert is_reusable_attribute("GTIN", source_category_id="MLA1") is False
    assert is_reusable_attribute("EMPTY_GTIN_REASON", source_category_id="MLA1") is False
