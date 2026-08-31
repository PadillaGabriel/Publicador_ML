import re


STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "con", "para", "y", "en", "un", "una",
    "por", "a", "al"
}


def tokenize(text: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-záéíóúüñ0-9]+", text.lower())
        if len(token) > 1 and token not in STOPWORDS
    ]


def jaccard(a: str, b: str) -> float:
    sa, sb = set(tokenize(a)), set(tokenize(b))
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(1, len(sa | sb))


def validate_title_set(titles: list[str], max_similarity: float = 0.82) -> list[str]:
    unique: list[str] = []
    for title in titles:
        clean = " ".join(title.split()).strip()
        if not clean:
            continue
        if any(jaccard(clean, existing) > max_similarity for existing in unique):
            continue
        unique.append(clean)
    return unique


def _keyword_present(title_tokens: set[str], keyword: str) -> bool:
    keyword_tokens = set(tokenize(keyword))
    return bool(keyword_tokens) and keyword_tokens.issubset(title_tokens)


def title_target_min_length(max_length: int) -> int:
    """Target 90% of the contractual title capacity without making it a hard requirement."""
    return max(1, min(max_length, round(max_length * 0.90)))


def score_title(title: str, keywords: list[str], max_length: int) -> int:
    tokens = set(tokenize(title))
    coverage = sum(1 for keyword in keywords[:10] if _keyword_present(tokens, keyword))
    coverage_score = min(40, coverage * 4)
    length = len(title)
    ratio = length / max_length if max_length > 0 else 0
    if length > max_length:
        length_score = 0
    elif ratio >= 0.90:
        length_score = 25
    elif ratio >= 0.80:
        length_score = 21
    elif ratio >= 0.65:
        length_score = 16
    else:
        length_score = 10
    clarity_score = 20 if 3 <= len(tokens) <= 12 else 12
    repetition_penalty = max(0, len(tokenize(title)) - len(tokens)) * 3
    return max(0, min(100, coverage_score + length_score + clarity_score + 15 - repetition_penalty))
