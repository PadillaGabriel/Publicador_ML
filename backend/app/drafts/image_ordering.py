import hashlib
import itertools
import math
import random
from uuid import UUID


def generate_image_orders(image_ids: list[UUID], count: int, seed_material: str) -> list[list[str]]:
    ids = [str(x) for x in image_ids]
    if not ids:
        return [[] for _ in range(count)]
    if len(ids) == 1:
        return [ids[:] for _ in range(count)]

    seed = int(hashlib.sha256(seed_material.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)

    # Enumerate all permutations only for small image sets. For larger sets generate
    # deterministic unique shuffles to avoid factorial memory growth.
    if len(ids) <= 7:
        all_orders = list(itertools.permutations(ids))
        rng.shuffle(all_orders)
        orders = [list(p) for p in all_orders[:count]]
    else:
        seen: set[tuple[str, ...]] = set()
        orders = []
        max_unique = math.factorial(len(ids))
        target = min(count, max_unique)
        while len(orders) < target:
            candidate = ids[:]
            rng.shuffle(candidate)
            key = tuple(candidate)
            if key not in seen:
                seen.add(key)
                orders.append(candidate)

    while len(orders) < count:
        orders.append(orders[len(orders) % max(1, len(orders))][:])
    return orders
