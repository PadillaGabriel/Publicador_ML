import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass


STOPWORDS = {
    "a", "al", "con", "de", "del", "el", "en", "la", "las", "los", "para", "por", "un", "una", "y"
}

CLASSIFICATION_WEIGHTS = {
    "DIRECT_MATCH": 1.0,
    "SYNONYM": 0.95,
    "RELATED_INTENT": 0.78,
    "UNSUPPORTED": 0.0,
}


@dataclass(frozen=True, slots=True)
class RankedTrend:
    term: str
    popularity_rank: int
    semantic_similarity: float | None
    lexical_coverage: float
    final_score: float
    eligible: bool
    unsupported_tokens: tuple[str, ...]


def normalize_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", without_accents))


def _canonical_token(token: str) -> str:
    """Very small Spanish plural normalization, not a linguistic stemmer."""
    if len(token) > 5 and token.endswith("es"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


def content_tokens(text: str) -> list[str]:
    return [
        _canonical_token(token)
        for token in normalize_text(text).split()
        if len(token) > 1 and token not in STOPWORDS
    ]


def _attribute_value_text(value: object) -> list[str]:
    if isinstance(value, dict):
        resolved = value.get("value_name") or value.get("name") or value.get("value")
        return [str(resolved)] if resolved not in (None, "") else []
    if isinstance(value, (str, int, float)):
        return [str(value)]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_attribute_value_text(item))
        return result
    return []


def build_product_evidence(
    *,
    product_name: str,
    category_name: str,
    description: str,
    attributes: dict,
    discovery_context: dict,
) -> tuple[str, set[str]]:
    semantic_parts = [product_name, f"Categoría: {category_name}"]
    factual_parts = [product_name, category_name]

    clean_description = (description or "").strip()
    if clean_description:
        semantic_parts.append(f"Descripción: {clean_description}")
        factual_parts.append(clean_description)

    for key, value in attributes.items():
        values = _attribute_value_text(value)
        for text in values:
            semantic_parts.append(f"{key}: {text}")
            factual_parts.append(text)

    for key in ("brand", "model", "characteristics"):
        value = discovery_context.get(key)
        if value not in (None, "", [], {}):
            semantic_parts.append(f"{key}: {value}")
            factual_parts.append(str(value))

    factual_tokens = {
        token
        for part in factual_parts
        for token in content_tokens(part)
    }
    return ". ".join(semantic_parts), factual_tokens


def rank_trends(
    trends: list[str],
    semantic_scores: list[float | None],
    factual_tokens: set[str],
    *,
    min_semantic_similarity: float,
) -> list[RankedTrend]:
    if len(trends) != len(semantic_scores):
        raise ValueError("trends and semantic_scores must have the same length")

    ranked: list[RankedTrend] = []
    for popularity_rank, (term, semantic_score) in enumerate(
        zip(trends, semantic_scores, strict=True),
        start=1,
    ):
        term_tokens = content_tokens(term)
        if not term_tokens:
            continue

        supported = [token for token in term_tokens if token in factual_tokens]
        unsupported = tuple(sorted(set(term_tokens) - factual_tokens))
        lexical_coverage = len(supported) / len(term_tokens)
        factual_safe = not unsupported
        if semantic_score is None:
            semantic_relevant = True
            preliminary_score = lexical_coverage
            normalized_semantic_score = None
        else:
            normalized_semantic_score = min(max(semantic_score, 0.0), 1.0)
            semantic_relevant = normalized_semantic_score >= min_semantic_similarity
            preliminary_score = 0.75 * normalized_semantic_score + 0.25 * lexical_coverage

        ranked.append(
            RankedTrend(
                term=term,
                popularity_rank=popularity_rank,
                semantic_similarity=(
                    None
                    if normalized_semantic_score is None
                    else round(normalized_semantic_score, 6)
                ),
                lexical_coverage=round(lexical_coverage, 6),
                final_score=round(preliminary_score, 6),
                eligible=factual_safe and semantic_relevant,
                unsupported_tokens=unsupported,
            )
        )

    return sorted(
        ranked,
        key=lambda item: (item.final_score, -item.popularity_rank),
        reverse=True,
    )


def _token_weights(scored_terms: list[tuple[str, float]]) -> list[dict]:
    token_weights: dict[str, float] = defaultdict(float)
    for term, score in scored_terms:
        unique_tokens = set(content_tokens(term))
        if not unique_tokens:
            continue
        contribution = score / len(unique_tokens)
        for token in unique_tokens:
            token_weights[token] += contribution

    return [
        {"token": token, "weight": round(weight, 6)}
        for token, weight in sorted(token_weights.items(), key=lambda pair: pair[1], reverse=True)
    ]


def select_assessed_keywords(
    ranked: list[RankedTrend],
    classifications: dict[str, str],
    limit: int,
) -> tuple[list[str], list[dict], list[dict]]:
    """Rank AI-classified trends with deterministic weights owned by the application."""
    if limit < 1:
        return [], [], []

    total = max(len(ranked), 1)
    scored: list[dict] = []
    for item in ranked:
        classification = classifications.get(item.term, "UNSUPPORTED")
        classification_weight = CLASSIFICATION_WEIGHTS.get(classification, 0.0)
        if classification_weight <= 0:
            continue

        popularity_score = 1.0 if total == 1 else 1.0 - ((item.popularity_rank - 1) / (total - 1))
        weighted_signals = [
            (0.45, classification_weight),
            (0.30, popularity_score),
            (0.05, item.lexical_coverage),
        ]
        if item.semantic_similarity is not None:
            weighted_signals.append((0.20, item.semantic_similarity))
        available_weight = sum(weight for weight, _score in weighted_signals)
        final_score = sum(weight * score for weight, score in weighted_signals) / available_weight
        scored.append(
            {
                "term": item.term,
                "classification": classification,
                "popularity_rank": item.popularity_rank,
                "popularity_score": round(popularity_score, 6),
                "semantic_similarity": item.semantic_similarity,
                "lexical_coverage": item.lexical_coverage,
                "final_score": round(final_score, 6),
            }
        )

    scored.sort(
        key=lambda item: (item["final_score"], -item["popularity_rank"]),
        reverse=True,
    )
    selected = scored[:limit]
    phrases = [item["term"] for item in selected]
    token_weights = _token_weights([(item["term"], item["final_score"]) for item in selected])
    return phrases, token_weights, scored
