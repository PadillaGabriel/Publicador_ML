import re
from dataclasses import dataclass

from app.keywords.relevance import content_tokens, normalize_text


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
    phrases = [context.product_name.strip()]
    phrases.extend(str(value).strip() for _, value in sorted(context.attributes.items()))
    return [phrase for phrase in phrases if phrase]


def _word_keys(word: str) -> list[str]:
    return content_tokens(word) or [token for token in (normalize_text(word),) if token]


def _deduplicated_title(phrases: list[str], max_length: int) -> str:
    seen: set[str] = set()
    words: list[str] = []
    for phrase in phrases:
        for word in phrase.split():
            keys = _word_keys(word)
            if not keys or any(key in seen for key in keys):
                continue
            title = " ".join([*words, word.upper()])
            if len(title) > max_length:
                return " ".join(words)
            seen.update(keys)
            words.append(word.upper())
    return " ".join(words)


def _matched_trends(trends: tuple[str, ...], factual_tokens: set[str]) -> tuple[str, ...]:
    matched: list[str] = []
    seen: set[str] = set()
    for trend in trends:
        tokens = set(content_tokens(trend))
        supported = tokens & factual_tokens
        trend_key = normalize_text(trend)
        if len(supported) >= 2 and len(supported) * 2 >= len(tokens) and trend_key not in seen:
            seen.add(trend_key)
            matched.append(trend)
    return tuple(matched)


def _attribute_value(context: ProductTitleContext, names: set[str]) -> str:
    for key, value in sorted(context.attributes.items()):
        if normalize_text(key) in names and str(value).strip():
            return str(value).strip()
    return ""


def _compact_capacity(value: str) -> str:
    return re.sub(r"(?<=\d)\s+(?=[A-Za-z])", "", value)


def _trend_candidates(context: ProductTitleContext, max_length: int) -> tuple[str, ...]:
    name_words = context.product_name.strip().split()
    if not name_words:
        return ()
    descriptor = name_words[-1:]
    use = _attribute_value(context, {"use", "uso"})
    capacity = _compact_capacity(_attribute_value(context, {"capacity", "capacidad"}))
    use_words = use.split()
    variants = (
        [name_words[0], *descriptor, "PARA", *use_words, capacity],
        [name_words[0], *descriptor, capacity, "PARA", *use_words],
        [name_words[0], "PARA", *use_words, *descriptor, capacity],
        [name_words[0], *descriptor, *use_words, capacity],
    )
    candidates: list[str] = []
    for words in variants:
        candidate = _deduplicated_title([word for word in words if word], max_length)
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def recommend_title(
    context: ProductTitleContext,
    trends: tuple[str, ...],
    constraints: TitleConstraints,
) -> TitleRecommendation:
    if not context.category_id.strip() or not context.product_name.strip():
        raise ValueError("category_id and product_name are required")
    factual = _factual_phrases(context)
    factual_tokens = {token for phrase in factual for token in content_tokens(phrase)}
    matched_trends = _matched_trends(trends, factual_tokens)
    candidates = _trend_candidates(context, constraints.max_length) if matched_trends else ()
    if not candidates:
        candidates = (_deduplicated_title(factual, constraints.max_length),)
    candidates = tuple(candidate for candidate in candidates if candidate)
    return TitleRecommendation(
        recommended_title=candidates[0],
        alternatives=candidates[1:10],
        matched_trends=matched_trends,
        fallback_used=not bool(matched_trends),
    )
