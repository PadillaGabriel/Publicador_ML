from app.operator_auth import check_password, hash_password, normalize_username


def test_hash_is_salted_and_verifiable():
    a = hash_password("CorrectHorseBattery1")
    b = hash_password("CorrectHorseBattery1")
    assert a != b
    assert check_password("CorrectHorseBattery1", a)
    assert not check_password("otherPassword11111", a)


def test_invalid_hash_and_username():
    assert not check_password("anything", "broken")
    assert normalize_username("  Gabriel  ") == "gabriel"
