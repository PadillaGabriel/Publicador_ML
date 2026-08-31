from app.drafts.intelligence import jaccard, score_title, title_target_min_length, validate_title_set


def test_jaccard_detects_reordered_duplicate():
    a = "Mate Calabaza Cuero Negro Bombilla Acero"
    b = "Bombilla Acero Mate Negro Calabaza Cuero"
    assert jaccard(a, b) == 1.0


def test_distinct_titles_are_preserved():
    titles = [
        "Mate Calabaza Cuero Con Bombilla",
        "Mate Criollo Forrado En Cuero Virola Acero",
        "Mate Con Bombilla Acero Calabaza Natural",
    ]
    assert len(validate_title_set(titles, max_similarity=0.95)) == 3


def test_score_is_bounded():
    score = score_title("Mate Calabaza Cuero Bombilla", ["mate", "calabaza", "cuero"], 60)
    assert 0 <= score <= 100


def test_score_supports_multiword_keyword_phrases():
    score_with_phrase = score_title(
        "Mate Imperial Calabaza Cuero", ["mate imperial", "mate calabaza"], 60
    )
    score_without_phrase = score_title(
        "Mate Calabaza Cuero", ["mate imperial", "mate calabaza"], 60
    )
    assert score_with_phrase > score_without_phrase


def test_title_target_uses_ninety_percent_of_capacity():
    assert title_target_min_length(60) == 54


def test_score_rewards_titles_that_use_more_safe_capacity():
    keywords = ["mate", "calabaza"]
    shorter = score_title("Mate Calabaza Cuero", keywords, 60)
    fuller = score_title("Mate Calabaza Cuero Vacuno Virola Acero Con Bombilla Lisa", keywords, 60)
    assert fuller > shorter
