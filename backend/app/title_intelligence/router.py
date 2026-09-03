from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.title_intelligence.schemas import TitleRecommendationRequest, TitleRecommendationResponse
from app.title_intelligence.service import generate_title_recommendation

router = APIRouter(prefix="/api/title-intelligence", tags=["title-intelligence"])


@router.post("/generate", response_model=TitleRecommendationResponse)
def generate_title(
    payload: TitleRecommendationRequest,
    db: Annotated[Session, Depends(get_db)],
) -> TitleRecommendationResponse:
    try:
        return generate_title_recommendation(db, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_TITLE_REQUEST", "message": str(exc)},
        ) from exc
