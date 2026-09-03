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


def _factual_terms(context: ProductTitleContext) -> list[str]:
    terms = context.product_name.strip().split()
    terms.extend(
        str(value).strip()
        for _, value in sorted(context.attributes.items())
        if str(value).strip()
    )
    return terms


def _word_keys(word: str) -> list[str]:
    return content_tokens(word) or [token for token in (normalize_text(word),) if token]


def _complete_title(terms: list[str], max_length: int) -> str | None:
    seen: set[str] = set()
    words: list[str] = []
    for term in terms:
        for word in term.split():
            keys = _word_keys(word)
            if not keys or any(key in seen for key in keys):
                continue
            title = " ".join([*words, word.upper()])
            if len(title) > max_length:
                return None
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


def _trend_candidate(context: ProductTitleContext, max_length: int) -> str | None:
    name_words = context.product_name.strip().split()
    if not name_words:
        return None
    use = _attribute_value(context, {"use", "uso"})
    if not use:
        return None
    capacity = _compact_capacity(_attribute_value(context, {"capacity", "capacidad"}))
    terms = [name_words[0], name_words[-1], "PARA", use]
    if capacity:
        terms.append(capacity)
    return _complete_title(terms, max_length)


def _arrangements(terms: list[str]) -> tuple[tuple[str, ...], ...]:
    if len(terms) < 2:
        return (tuple(terms),)
    arrangements = [tuple(terms)]
    arrangements.extend(
        tuple(terms[offset:] + terms[:offset])
        for offset in range(1, min(len(terms), 9))
    )
    arrangements.append(tuple(reversed(terms)))
    return tuple(dict.fromkeys(arrangements))


def _fitting_title(terms: tuple[str, ...], max_length: int) -> str | None:
    selected: list[str] = []
    candidate: str | None = None
    for term in terms:
        next_candidate = _complete_title([*selected, term], max_length)
        if next_candidate is None:
            if selected:
                break
            continue
        selected.append(term)
        candidate = next_candidate
    return candidate


def _factual_candidates(terms: list[str], max_length: int) -> tuple[str, ...]:
    candidates: list[str] = []
    for arrangement in _arrangements(terms):
        candidate = _fitting_title(arrangement, max_length)
        if candidate and candidate not in candidates:
            candidates.append(candidate)
            if len(candidates) == 10:
                break
    return tuple(candidates)


def recommend_title(
    context: ProductTitleContext,
    trends: tuple[str, ...],
    constraints: TitleConstraints,
) -> TitleRecommendation:
    if not context.category_id.strip() or not context.product_name.strip():
        raise ValueError("category_id and product_name are required")
    factual_terms = _factual_terms(context)
    factual_tokens = {token for term in factual_terms for token in content_tokens(term)}
    matched_trends = _matched_trends(trends, factual_tokens)
    preferred = _trend_candidate(context, constraints.max_length) if matched_trends else None
    candidates = list(_factual_candidates(factual_terms, constraints.max_length))
    if preferred:
        candidates.insert(0, preferred)
    candidates = list(dict.fromkeys(candidates))[:10]
    if not candidates:
        raise ValueError("no factual token fits max_length")
    return TitleRecommendation(
        recommended_title=candidates[0],
        alternatives=tuple(candidates[1:]),
        matched_trends=matched_trends,
        fallback_used=preferred is None,
    )
