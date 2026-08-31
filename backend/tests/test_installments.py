from app.drafts.installments import installment_sequence, normalize_installment_distribution


def test_distribution_fills_unassigned_with_standard():
    result = normalize_installment_distribution(
        10,
        [{"installments": 3, "count": 2}, {"installments": 6, "count": 3}],
    )
    assert result == [
        {"installments": 1, "count": 5},
        {"installments": 3, "count": 2},
        {"installments": 6, "count": 3},
    ]


def test_sequence_preserves_exact_counts():
    distribution = [
        {"installments": 1, "count": 4},
        {"installments": 3, "count": 2},
        {"installments": 6, "count": 2},
    ]
    sequence = installment_sequence(8, distribution)
    assert sequence.count(1) == 4
    assert sequence.count(3) == 2
    assert sequence.count(6) == 2
