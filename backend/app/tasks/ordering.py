STEP = 1024.0
MIN_GAP = 1e-6


def position_between(before: float | None, after: float | None) -> float:
    """Position for a card dropped below `before` and above `after` (either may be absent)."""
    if before is None and after is None:
        return STEP
    if after is None:
        return before + STEP
    if before is None:
        return after - STEP
    return (before + after) / 2


def needs_rebalance(a: float, b: float) -> bool:
    return abs(a - b) < MIN_GAP
