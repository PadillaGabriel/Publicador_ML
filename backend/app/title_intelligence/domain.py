from dataclasses import dataclass

from app.keywords.relevance import content_tokens


@dataclass(frozen=True, slots=True)
class ProductTitleContext:
    category_id: str
    product_name: str
    attributes: dict[str, str]


@dataclass(frozen=True, slots=True)
class TitleConstraints:
    max_length: int

    def __post_init__(self) -> None:
        if self.max_length < 1:
            raise ValueError("max_length must be positive")


@dataclass(frozen=True, slots=True)
class TitleRecommendation:
    recommended_title: str
    alternatives: tuple[str, ...]
    matched_trends: tuple[str, ...]
    fallback_used: bool


def _factual_phrases(context: ProductTitleContext) -> list[str]:
    phrases = [context.product_name.strip(), *[str(value).strip() for value in context.attributes.values()]]
    return [phrase for phrase in phrases if phrase]


def _deduplicated_title(phrases: list[str], max_length: int) -> str:
    seen: set[str] = set()
    words: list[str] = []
    for phrase in phrases:
        for word in phrase.split():
            key = " ".join(content_tokens(word))
            if key and key not in seen:
                seen.add(key)
                words.append(word.upper())
    title = " ".join(words)
    return title[:max_length].rstrip()


def recommend_title(
    context: ProductTitleContext,
    trends: tuple[str, ...],
    constraints: TitleConstraints,
) -> TitleRecommendation:
    if not context.category_id.strip() or not context.product_name.strip():
        raise ValueError("category_id and product_name are required")
    factual = _factual_phrases(context)
    factual_tokens = {token for phrase in factual for token in content_tokens(phrase)}
    compatible = tuple(
        trend for trend in trends
        if set(content_tokens(trend)).issubset(factual_tokens) and content_tokens(trend)
    )
    recommended = _deduplicated_title(factual, constraints.max_length)
    alternatives = tuple(
        title for title in (
            _deduplicated_title([context.product_name, trend, *factual[1:]], constraints.max_length)
            for trend in compatible[:3]
        )
        if title and title != recommended
    )
    return TitleRecommendation(recommended, alternatives, compatible, not bool(compatible))
