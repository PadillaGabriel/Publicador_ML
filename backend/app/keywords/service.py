import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import utcnow
from app.integrations.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from app.integrations.openai.semantic_trends import (
    OpenAITrendAnalysisError,
    OpenAITrendSemanticAnalyzer,
    TrendClassification,
)
from app.keywords.relevance import (
    build_product_evidence,
    rank_trends,
    select_assessed_keywords,
)
from app.keywords.prerank import semantic_prerank
from app.persistence import KeywordSnapshot, KeywordTrendSnapshot, ProductVersion

logger = logging.getLogger("ml-keyword-intelligence")


class KeywordResearchError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class CategoryTrendLookup:
    terms: tuple[str, ...]
    snapshot: KeywordTrendSnapshot | None
    cache_status: Literal["FRESH_HIT", "MISS_FETCHED", "STALE_FALLBACK", "UNAVAILABLE"]
    failure_retryable: bool | None


def _latest_trend_snapshot(db: Session, site_id: str, category_id: str) -> KeywordTrendSnapshot | None:
    return db.scalar(
        select(KeywordTrendSnapshot)
        .where(
            KeywordTrendSnapshot.site_id == site_id,
            KeywordTrendSnapshot.category_id == category_id,
        )
        .order_by(desc(KeywordTrendSnapshot.fetched_at))
        .limit(1)
    )


def get_category_trends(
    db: Session,
    *,
    site_id: str,
    category_id: str,
    access_token: str,
) -> CategoryTrendLookup:
    settings = get_settings()
    now = utcnow()
    latest = _latest_trend_snapshot(db, site_id, category_id)
    if latest and latest.expires_at > now:
        logger.info(
            "keyword_trends_cache_hit site=%s category=%s terms=%d",
            site_id,
            category_id,
            len(latest.terms),
        )
        return CategoryTrendLookup(tuple(latest.terms), latest, "FRESH_HIT", None)

    logger.info("keyword_trends_fetch_started site=%s category=%s", site_id, category_id)
    try:
        terms = MercadoLibreClient(access_token).category_trends(site_id, category_id)
    except MercadoLibreError as exc:
        if latest:
            logger.warning(
                "keyword_trends_stale_fallback site=%s category=%s terms=%d",
                site_id,
                category_id,
                len(latest.terms),
            )
            return CategoryTrendLookup(tuple(latest.terms), latest, "STALE_FALLBACK", None)
        logger.warning("keyword_trends_unavailable site=%s category=%s error=%s", site_id, category_id, exc)
        return CategoryTrendLookup((), None, "UNAVAILABLE", exc.retryable)

    terms = terms[: settings.keyword_max_trends]
    snapshot = KeywordTrendSnapshot(
        site_id=site_id,
        category_id=category_id,
        source="mercadolibre_category_trends",
        terms=terms,
        fetched_at=now,
        expires_at=now + timedelta(seconds=settings.ml_keyword_trends_ttl_seconds),
    )
    db.add(snapshot)
    db.flush()
    logger.info(
        "keyword_trends_fetch_completed site=%s category=%s terms=%d",
        site_id,
        category_id,
        len(terms),
    )
    return CategoryTrendLookup(tuple(terms), snapshot, "MISS_FETCHED", None)


def _fallback_snapshot(
    db: Session,
    *,
    version: ProductVersion,
    trend_snapshot: KeywordTrendSnapshot,
    cache_status: str,
    reason: str,
    started: float,
) -> KeywordSnapshot:
    snapshot = KeywordSnapshot(
        product_version_id=version.id,
        strategy_version="product-facts-fallback-v1",
        keywords=[],
        evidence={
            "source": "product_facts",
            "trend_snapshot_id": str(trend_snapshot.id),
            "trend_cache_status": cache_status,
            "trend_fetched_at": trend_snapshot.fetched_at.isoformat(),
            "trend_expires_at": trend_snapshot.expires_at.isoformat(),
            "selected_terms": [],
            "token_weights": [],
            "ranked_terms": [],
            "generation_mode": "PRODUCT_FACTS_FALLBACK",
            "fallback_reason": reason,
            "note": (
                "Mercado Libre category trends are optional ranking evidence. "
                "Title generation continues from factual product data when no usable trend exists."
            ),
        },
    )
    db.add(snapshot)
    db.flush()
    logger.info(
        "keyword_research_completed product_version=%s cache=%s selected_terms=0 mode=PRODUCT_FACTS_FALLBACK duration_ms=%d",
        version.id,
        cache_status,
        round((time.perf_counter() - started) * 1000),
    )
    return snapshot


def build_ml_keyword_snapshot(
    db: Session,
    *,
    version: ProductVersion,
    site_id: str,
    category_name: str,
    access_token: str,
) -> KeywordSnapshot:
    started = time.perf_counter()
    settings = get_settings()
    logger.info(
        "keyword_research_started product_version=%s category=%s",
        version.id,
        version.category_id,
    )
    trend_lookup = get_category_trends(
        db,
        site_id=site_id,
        category_id=version.category_id,
        access_token=access_token,
    )
    if trend_lookup.snapshot is None:
        if trend_lookup.failure_retryable is None:
            raise AssertionError("unavailable trend lookup must include retryability")
        raise KeywordResearchError(
            "No se pudieron obtener las tendencias de Mercado Libre para esta categoría.",
            code="ML_KEYWORD_TRENDS_UNAVAILABLE",
            retryable=trend_lookup.failure_retryable,
        )
    trends = list(trend_lookup.terms)
    trend_snapshot = trend_lookup.snapshot
    cache_status = trend_lookup.cache_status
    product_text, factual_tokens = build_product_evidence(
        product_name=version.title_reference,
        category_name=category_name,
        description=version.description or "",
        attributes=version.attributes,
        discovery_context=version.discovery_context or {},
    )

    if not trends:
        return _fallback_snapshot(
            db,
            version=version,
            trend_snapshot=trend_snapshot,
            cache_status=cache_status,
            reason="ML_TRENDS_EMPTY",
            started=started,
        )

    similarities, semantic_model_status, semantic_model = semantic_prerank(
        settings=settings,
        product_version_id=version.id,
        product_text=product_text,
        trends=trends,
    )

    ranked = rank_trends(
        trends,
        similarities,
        factual_tokens,
        min_semantic_similarity=settings.keyword_min_semantic_similarity,
    )
    trend_candidates = [
        {
            "term": item.term,
            "popularity_rank": item.popularity_rank,
            "semantic_similarity": item.semantic_similarity,
            "lexical_coverage": item.lexical_coverage,
            "unsupported_tokens": list(item.unsupported_tokens),
        }
        for item in sorted(ranked, key=lambda candidate: candidate.popularity_rank)
    ]

    logger.info(
        "trend_semantic_analysis_started product_version=%s candidates=%d",
        version.id,
        len(trend_candidates),
    )
    analyzer = OpenAITrendSemanticAnalyzer()
    try:
        assessment_result, provider = analyzer.assess(
            category_name=category_name,
            product_name=version.title_reference,
            description=version.description or "",
            attributes=version.attributes,
            discovery_context=version.discovery_context or {},
            trend_candidates=trend_candidates,
        )
    except OpenAITrendAnalysisError as exc:
        raise KeywordResearchError(
            str(exc),
            code=exc.code,
            retryable=exc.retryable,
        ) from exc

    classifications = {
        item.term: item.classification.value
        for item in assessment_result.assessments
    }
    keywords, token_weights, scored_terms = select_assessed_keywords(
        ranked,
        classifications,
        settings.keyword_max_selected_terms,
    )
    assessments_by_term = {item.term: item for item in assessment_result.assessments}
    usable_count = sum(
        item.classification != TrendClassification.UNSUPPORTED
        for item in assessment_result.assessments
    )
    generation_mode = "TREND_SEMANTIC_ENRICHED" if keywords else "PRODUCT_FACTS_FALLBACK"

    snapshot = KeywordSnapshot(
        product_version_id=version.id,
        strategy_version=(
            "ml-trends-openai-semantic-v1" if keywords else "product-facts-fallback-v1"
        ),
        keywords=keywords,
        evidence={
            "source": "mercadolibre_category_trends",
            "trend_snapshot_id": str(trend_snapshot.id),
            "trend_cache_status": cache_status,
            "trend_fetched_at": trend_snapshot.fetched_at.isoformat(),
            "trend_expires_at": trend_snapshot.expires_at.isoformat(),
            "semantic_model": semantic_model,
            "semantic_model_status": semantic_model_status,
            "semantic_min_similarity": (
                settings.keyword_min_semantic_similarity if semantic_model is not None else None
            ),
            "trend_analyzer": {
                "model": provider["model"],
                "prompt_version": provider["prompt_version"],
                "request_id": provider.get("request_id"),
                "usage": provider.get("usage") or {},
            },
            "selected_terms": keywords,
            "token_weights": token_weights,
            "generation_mode": generation_mode,
            "fallback_reason": None if keywords else "NO_SEMANTICALLY_USABLE_TRENDS",
            "ranked_terms": [
                {
                    "term": item.term,
                    "popularity_rank": item.popularity_rank,
                    "semantic_similarity": item.semantic_similarity,
                    "lexical_coverage": item.lexical_coverage,
                    "preliminary_score": item.final_score,
                    "deterministic_exact_match_eligible": item.eligible,
                    "unsupported_tokens": list(item.unsupported_tokens),
                }
                for item in ranked
            ],
            "semantic_assessments": [
                {
                    "term": item.term,
                    "classification": item.classification.value,
                    "maps_to": item.maps_to,
                    "reason": item.reason,
                }
                for item in assessment_result.assessments
            ],
            "scored_usable_terms": [
                {
                    **item,
                    "maps_to": assessments_by_term[item["term"]].maps_to,
                }
                for item in scored_terms
            ],
            "note": (
                "Mercado Libre trend order remains a popularity signal. Local lexical evidence is always available; "
                "embedding similarity is an optional pre-ranking signal. OpenAI classifies low-overlap synonyms and "
                "related search intent without being allowed to invent product claims. "
                "Final keyword scores are computed deterministically by the application, not by the model."
            ),
        },
    )
    db.add(snapshot)
    db.flush()
    logger.info(
        "keyword_research_completed product_version=%s cache=%s candidates=%d usable=%d selected_terms=%d mode=%s duration_ms=%d",
        version.id,
        cache_status,
        len(ranked),
        usable_count,
        len(keywords),
        generation_mode,
        round((time.perf_counter() - started) * 1000),
    )
    return snapshot
