import uuid

from app.drafts.image_ordering import generate_image_orders


def test_image_orders_preserve_canonical_user_order_for_every_draft():
    ids = [uuid.uuid4() for _ in range(4)]
    orders = generate_image_orders(ids, 6, "batch-1")
    expected = [str(value) for value in ids]

    assert len(orders) == 6
    assert all(order == expected for order in orders)
    # Each result is an independent list so a caller cannot mutate sibling drafts.
    assert len({id(order) for order in orders}) == 6
