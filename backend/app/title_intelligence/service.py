from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.accounts import service as accounts_service
from app.keywords.service import get_category_trends
from app.persistence import MercadoLibreAccount
from app.title_intelligence.domain import ProductTitleContext, TitleConstraints, recommend_title
from app.title_intelligence.schemas import TitleRecommendationRequest, TitleRecommendationResponse


def generate_title_recommendation(
    db: Session, payload: TitleRecommendationRequest
) -> TitleRecommendationResponse:
    account = db.get(MercadoLibreAccount, payload.account_id)
    if not account or not account.active:
        raise HTTPException(status_code=404, detail="Cuenta de Mercado Libre no encontrada.")

    access_token = accounts_service.load_access_token(db, payload.account_id)
    with Session(bind=db.get_bind()) as cache_db:
        trend_lookup = get_category_trends(
            cache_db,
            site_id=account.site_id,
            category_id=payload.category_id,
            access_token=access_token,
        )
        if trend_lookup.cache_status == "MISS_FETCHED":
            cache_db.commit()
    trends = () if trend_lookup.cache_status == "UNAVAILABLE" else trend_lookup.terms
    recommendation = recommend_title(
        ProductTitleContext(
            category_id=payload.category_id,
            product_name=payload.product_name,
            attributes=dict(payload.attributes),
        ),
        trends,
        TitleConstraints(max_length=payload.max_length),
    )
    return TitleRecommendationResponse(
        recommended_title=recommendation.recommended_title,
        alternatives=list(recommendation.alternatives),
        confidence=(
            "FACTUAL_FALLBACK" if recommendation.fallback_used else "TREND_SUPPORTED"
        ),
        matched_trends=list(recommendation.matched_trends),
        fallback_used=recommendation.fallback_used,
    )
