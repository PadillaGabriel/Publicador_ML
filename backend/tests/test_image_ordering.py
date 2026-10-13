import uuid
from app.drafts.image_ordering import generate_image_orders


def test_image_orders_preserve_explicit_product_order_for_every_draft():
    ids = [uuid.uuid4() for _ in range(4)]
    result = generate_image_orders(ids, 6, "batch-1")
    expected = [str(value) for value in ids]
    assert result == [expected] * 6
