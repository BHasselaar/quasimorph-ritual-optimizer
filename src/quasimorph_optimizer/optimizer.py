from __future__ import annotations

import heapq
import itertools
import math
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .constants import AFFINITIES, TIER_RULES
from .models import ComponentContribution, Item, RitualResult
from .probabilities import calculate_probabilities

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class OptimizationSummary:
    results: tuple[RitualResult, ...]
    evaluated: int
    total_candidates: int
    cancelled: bool


OBJECTIVES: dict[str, str] = {
    "jackpot": "Maximum Jackpot",
    "upgrade": "Maximum normal Upgrade",
    "improvement": "Maximum Upgrade + Jackpot",
    "sidegrade": "Maximum Sidegrade",
    "min_disenchant": "Minimum Disenchant",
    "balanced": "Best balanced Power/Stability",
    "power": "Maximum effective Power",
    "stability": "Maximum effective Stability",
}


def unique_ring_order_count(item_count: int) -> int:
    """Return unique five-item circular orders, collapsing five rotations."""
    if item_count < 5:
        return 0
    return math.comb(item_count, 5) * math.factorial(4)


def iter_unique_ring_orders(items: list[Item]) -> Iterable[tuple[Item, ...]]:
    """Yield every distinct five-item circular order exactly once."""
    for combination in itertools.combinations(items, 5):
        anchor = combination[0]
        for remainder in itertools.permutations(combination[1:]):
            yield (anchor, *remainder)


def evaluate_ritual(
    order: tuple[Item, ...],
    *,
    center_essence: str,
    tier: int,
    flat_power_bonus: float = 0.0,
    flat_stability_bonus: float = 0.0,
) -> RitualResult:
    if len(order) != 5:
        raise ValueError("A ritual must contain exactly five component items")
    if center_essence not in AFFINITIES:
        raise ValueError(f"Unknown center essence: {center_essence}")
    if tier not in TIER_RULES:
        raise ValueError(f"Unknown tier: {tier}")

    contributions: list[ComponentContribution] = []
    total_power = float(flat_power_bonus)
    total_stability = float(flat_stability_bonus)

    for index, item in enumerate(order):
        predecessor = order[index - 1]
        prev_power_mult, prev_stability_mult = AFFINITIES[predecessor.essence][item.essence]
        center_power_mult, center_stability_mult = AFFINITIES[item.essence][center_essence]
        power = item.power * prev_power_mult * center_power_mult
        stability = item.stability * prev_stability_mult * center_stability_mult
        total_power += power
        total_stability += stability
        contributions.append(
            ComponentContribution(
                item=item,
                predecessor=predecessor,
                predecessor_power_multiplier=prev_power_mult,
                predecessor_stability_multiplier=prev_stability_mult,
                center_power_multiplier=center_power_mult,
                center_stability_multiplier=center_stability_mult,
                power=power,
                stability=stability,
            )
        )

    targets = TIER_RULES[tier]
    power_percent = min(1.0, max(0.0, total_power / targets.power_target))
    stability_percent = min(1.0, max(0.0, total_stability / targets.stability_target))
    probabilities = calculate_probabilities(power_percent, stability_percent, tier)

    return RitualResult(
        order=order,
        total_power=total_power,
        total_stability=total_stability,
        power_percent=power_percent,
        stability_percent=stability_percent,
        power_target=targets.power_target,
        stability_target=targets.stability_target,
        flat_power_bonus=float(flat_power_bonus),
        flat_stability_bonus=float(flat_stability_bonus),
        probabilities=probabilities,
        contributions=tuple(contributions),
    )


def objective_key(result: RitualResult, objective: str) -> tuple[float, ...]:
    p = result.probabilities
    if objective == "jackpot":
        return (p.jackpot, p.improvement, -p.disenchant, result.stability_percent)
    if objective == "upgrade":
        return (p.upgrade, p.jackpot, -p.disenchant, result.stability_percent)
    if objective == "improvement":
        return (p.improvement, p.jackpot, -p.disenchant, result.stability_percent)
    if objective == "sidegrade":
        return (p.sidegrade, -p.disenchant, result.power_percent, -result.stability_percent)
    if objective == "min_disenchant":
        return (-p.disenchant, p.improvement, p.sidegrade, result.stability_percent)
    if objective == "balanced":
        return (
            min(result.power_percent, result.stability_percent),
            -abs(result.power_percent - result.stability_percent),
            p.improvement,
        )
    if objective == "power":
        return (result.power_percent, result.total_power, result.stability_percent)
    if objective == "stability":
        return (result.stability_percent, result.total_stability, result.power_percent)
    raise ValueError(f"Unknown objective: {objective}")


def optimize(
    items: list[Item],
    *,
    center_essence: str,
    tier: int,
    objective: str,
    top_n: int = 50,
    flat_power_bonus: float = 0.0,
    flat_stability_bonus: float = 0.0,
    progress_callback: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> OptimizationSummary:
    enabled_items = [item for item in items if item.enabled]
    if len(enabled_items) < 5:
        raise ValueError("Enable at least five inventory items")
    if objective not in OBJECTIVES:
        raise ValueError(f"Unknown objective: {objective}")
    if top_n < 1:
        raise ValueError("top_n must be at least 1")

    total = unique_ring_order_count(len(enabled_items))
    heap: list[tuple[tuple[float, ...], int, RitualResult]] = []
    evaluated = 0
    sequence = 0
    cancelled = False
    report_every = max(1, total // 200)

    for order in iter_unique_ring_orders(enabled_items):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break

        result = evaluate_ritual(
            order,
            center_essence=center_essence,
            tier=tier,
            flat_power_bonus=flat_power_bonus,
            flat_stability_bonus=flat_stability_bonus,
        )
        key = objective_key(result, objective)
        entry = (key, sequence, result)
        sequence += 1
        if len(heap) < top_n:
            heapq.heappush(heap, entry)
        elif key > heap[0][0]:
            heapq.heapreplace(heap, entry)

        evaluated += 1
        if progress_callback is not None and (evaluated % report_every == 0 or evaluated == total):
            progress_callback(evaluated, total)

    ordered = sorted(heap, key=lambda entry: (entry[0], entry[1]), reverse=True)
    return OptimizationSummary(
        results=tuple(entry[2] for entry in ordered),
        evaluated=evaluated,
        total_candidates=total,
        cancelled=cancelled,
    )
