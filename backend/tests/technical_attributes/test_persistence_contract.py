from app.persistence import ProductTechnicalAttribute


def test_product_technical_attribute_contract():
    table = ProductTechnicalAttribute.__table__
    assert table.name == "product_technical_attributes"
    assert {column.name for column in table.columns} == {
        "id",
        "product_master_id",
        "attribute_id",
        "value",
        "source_category_id",
        "source_kind",
        "source_reference",
        "created_at",
        "updated_at",
    }
    assert any(
        constraint.name == "uq_product_technical_attribute"
        for constraint in table.constraints
    )
