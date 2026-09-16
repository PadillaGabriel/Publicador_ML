from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ImportMlaRequest(BaseModel):
    account_id: uuid.UUID
    item_id: str = Field(min_length=4, max_length=40)

    @field_validator("item_id")
    @classmethod
    def normalize_item_id(cls, value: str) -> str:
        item_id = value.strip().upper()
        if not re.fullmatch(r"MLA\d+", item_id):
            raise ValueError("Ingresá un MLA válido, por ejemplo MLA123456789.")
        return item_id


class TechnicalAttributeRecord(BaseModel):
    attribute_id: str
    label: str
    value: Any = None
    source_category_id: str | None = None
    source_kind: str | None = None
    source_reference: str | None = None
    status: str


class ImportTechnicalAttributesResult(BaseModel):
    item_id: str
    category_id: str | None = None
    imported_count: int
    skipped_count: int
    imported: list[TechnicalAttributeRecord] = Field(default_factory=list)
    skipped: list[TechnicalAttributeRecord] = Field(default_factory=list)


class ReuseTechnicalAttributesResult(BaseModel):
    product_id: uuid.UUID
    category_id: str
    reusable: list[TechnicalAttributeRecord] = Field(default_factory=list)
    pending: list[TechnicalAttributeRecord] = Field(default_factory=list)
    incompatible: list[TechnicalAttributeRecord] = Field(default_factory=list)

    @property
    def reusable_count(self) -> int:
        return len(self.reusable)

    @property
    def pending_count(self) -> int:
        return len(self.pending)

    @property
    def incompatible_count(self) -> int:
        return len(self.incompatible)
