import uuid
from app.drafts.image_ordering import generate_image_orders


def test_image_orders_are_reproducible():
    ids = [uuid.uuid4() for _ in range(4)]
    a = generate_image_orders(ids, 6, "batch-1")
    b = generate_image_orders(ids, 6, "batch-1")
    assert a == b
    assert len({tuple(x) for x in a}) == 6
