from uuid import UUID


def generate_image_orders(image_ids: list[UUID], count: int, seed_material: str) -> list[list[str]]:
    """Return the canonical user-defined image order for every draft.

    ``ProductImage.position`` is the single source of truth. Older versions of the
    publisher rotated/shuffled images to diversify listings, which could publish a
    different principal image than the operator selected. ``seed_material`` is kept
    in the signature for backward compatibility with callers/tests but is no longer
    used.
    """
    del seed_material
    ids = [str(image_id) for image_id in image_ids]
    return [ids[:] for _ in range(max(count, 0))]
