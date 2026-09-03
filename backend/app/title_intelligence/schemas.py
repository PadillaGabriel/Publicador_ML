from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class TitleRecommendationRequest(BaseModel):
    account_id: UUID
    category_id: str = Field(min_length=1, max_length=40)
    product_name: str = Field(min_length=1, max_length=255)
    attributes: dict[str, str] = Field(default_factory=dict, max_length=50)
    max_length: int = Field(gt=0)

    @field_validator("category_id", "product_name")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class TitleRecommendationResponse(BaseModel):
    recommended_title: str
    alternatives: list[str]
    confidence: Literal["TREND_SUPPORTED", "FACTUAL_FALLBACK"]
    matched_trends: list[str]
    fallback_used: bool
