from fastapi import HTTPException


def normalize_installment_distribution(count: int, distribution: list[dict] | None) -> list[dict]:
    """Return an exact distribution whose counts sum to the batch size.

    Any unassigned publications are intentionally treated as the standard 1-payment plan.
    The actual Mercado Libre financing/listing contract is resolved separately; this stores
    the operator's commercial intent without hardcoding marketplace rules.
    """
    by_plan: dict[int, int] = {}
    for raw in distribution or []:
        installments = int(raw.get("installments") or 0)
        amount = int(raw.get("count") or 0)
        if amount <= 0:
            continue
        if installments < 1 or installments > 24:
            raise HTTPException(status_code=422, detail="Las cuotas deben estar entre 1 y 24.")
        if installments in by_plan:
            raise HTTPException(status_code=422, detail=f"Plan de {installments} cuotas duplicado.")
        by_plan[installments] = amount

    assigned = sum(by_plan.values())
    if assigned > count:
        raise HTTPException(
            status_code=422,
            detail="La distribución por cuotas supera la cantidad total de publicaciones.",
        )

    remainder = count - assigned
    if remainder:
        by_plan[1] = by_plan.get(1, 0) + remainder

    return [
        {"installments": installments, "count": by_plan[installments]}
        for installments in sorted(by_plan)
        if by_plan[installments] > 0
    ]


def installment_sequence(count: int, distribution: list[dict]) -> list[int]:
    """Build a deterministic, lightly interleaved installment sequence."""
    remaining = {int(x["installments"]): int(x["count"]) for x in distribution}
    sequence: list[int] = []
    plans = sorted(remaining)
    while len(sequence) < count:
        progressed = False
        for plan in plans:
            if remaining.get(plan, 0) > 0:
                sequence.append(plan)
                remaining[plan] -= 1
                progressed = True
                if len(sequence) == count:
                    break
        if not progressed:
            break
    if len(sequence) != count:
        raise RuntimeError("Installment allocation did not match requested draft count.")
    return sequence
