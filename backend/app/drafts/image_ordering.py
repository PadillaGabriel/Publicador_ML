from uuid import UUID


def generate_image_orders(image_ids: list[UUID], count: int, seed_material: str) -> list[list[str]]:
    """Return the explicit product-image order for every generated publication.

    Image order is a commercial/editorial decision persisted by ProductImage.position.
    It must not be randomized per draft or inferred from filesystem/upload timing.
    ``seed_material`` is retained in the signature for backwards compatibility.
    """
    del seed_material
    ordered = [str(image_id) for image_id in image_ids]
    return [ordered[:] for _ in range(count)]
