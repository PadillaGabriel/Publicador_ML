"""API contracts for product master/version operations."""
from pydantic import BaseModel, Field, model_validator

from app.integrations.mercadolibre.attribute_contracts import (
    EMPTY_GTIN_REASON_ATTRIBUTE_ID,
    GTIN_ATTRIBUTE_ID,
)
from app.integrations.mercadolibre.product_identifiers import (
    attribute_has_value,
    is_valid_identifier_format,
)


class ProductCreate(BaseModel):
    internal_sku: str = Field(min_length=1, max_length=120)
    internal_name: str = Field(min_length=1, max_length=255)
    category_id: str = Field(min_length=1, max_length=40)
    title_reference: str = Field(min_length=1, max_length=255)
    description: str = ""
    price: float = Field(gt=0)
    quantity: int = Field(ge=0)
    condition: str = "new"
    currency_id: str = "ARS"
    listing_type_id: str | None = None
    attributes: dict = Field(default_factory=dict)
    commercial: dict = Field(default_factory=dict)
    logistics: dict = Field(default_factory=dict)
    discovery_context: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_product_identifier_input(self):
        gtin = self.attributes.get(GTIN_ATTRIBUTE_ID)
        empty_reason = self.attributes.get(EMPTY_GTIN_REASON_ATTRIBUTE_ID)
        has_gtin = attribute_has_value(gtin)
        has_empty_reason = attribute_has_value(empty_reason)

        if has_gtin and not is_valid_identifier_format(gtin):
            raise ValueError(
                "GTIN debe contener un código universal numérico real; no uses SKU, "
                "0, 'Otros' ni textos descriptivos."
            )
        if has_gtin and has_empty_reason:
            raise ValueError("Informá un GTIN real o un motivo de ausencia de GTIN, no ambos.")
        return self
