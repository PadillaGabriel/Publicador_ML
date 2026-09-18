import logging

from app.core.config import Settings
from app.keywords.semantic import LocalSemanticRanker, SemanticModelError

logger = logging.getLogger("ml-keyword-intelligence")


def semantic_prerank(
    *,
    settings: Settings,
    product_version_id: object,
    product_text: str,
    trends: list[str],
) -> tuple[list[float | None], str, str | None]:
    """Return optional local similarities without making the local model mandatory."""
    if not settings.keyword_local_embeddings_enabled:
        logger.info(
            "semantic_prerank_skipped product_version=%s reason=MEMORY_GUARD candidates=%d",
            product_version_id,
            len(trends),
        )
        return [None] * len(trends), "DISABLED_MEMORY_GUARD", None

    logger.info(
        "semantic_prerank_started product_version=%s model=%s candidates=%d",
        product_version_id,
        settings.keyword_embedding_model,
        len(trends),
    )
    try:
        similarities = LocalSemanticRanker(settings.keyword_embedding_model).similarities(
            product_text,
            trends,
        )
    except SemanticModelError as exc:
        logger.warning(
            "semantic_prerank_unavailable product_version=%s model=%s error=%s",
            product_version_id,
            settings.keyword_embedding_model,
            exc,
        )
        return [None] * len(trends), "UNAVAILABLE", settings.keyword_embedding_model

    return similarities, "AVAILABLE", settings.keyword_embedding_model
