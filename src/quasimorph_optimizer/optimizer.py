from __future__ import annotations

import heapq
import itertools
import math
import multiprocessing
import os
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass

from .constants import AFFINITIES, JACKPOT_UPGRADE_CAP, TIER_RULES
from .models import ComponentContribution, Item, RitualResult
from .probabilities import calculate_probabilities

ProgressCallback = Callable[[int, int], None]
PERM4 = tuple(itertools.permutations((1, 2, 3, 4)))


@dataclass(frozen=True, slots=True)
class OptimizationSummary:
    results: tuple[RitualResult, ...]
    evaluated: int
    total_candidates: int
    cancelled: bool
    workers_used: int = 1


OBJECTIVES: dict[str, str] = {
    "jackpot": "Jackpot",
    "balanced": "Balanced",
    "sidegrade": "Sidegrade",
    "min_disenchant": "Minimum Disenchant",
}


def unique_ring_order_count(item_count: int) -> int:
    if item_count < 5:
        return 0
    return math.comb(item_count, 5) * 24


def iter_unique_ring_orders(items: list[Item]) -> Iterable[tuple[Item, ...]]:
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
        contributions.append(ComponentContribution(
            item=item,
            predecessor=predecessor,
            predecessor_power_multiplier=prev_power_mult,
            predecessor_stability_multiplier=prev_stability_mult,
            center_power_multiplier=center_power_mult,
            center_stability_multiplier=center_stability_mult,
            power=power,
            stability=stability,
        ))

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
    if objective == "balanced":
        return (min(result.power_percent, result.stability_percent), -abs(result.power_percent - result.stability_percent), p.improvement)
    if objective == "sidegrade":
        return (p.sidegrade, -p.disenchant, result.power_percent, -result.stability_percent)
    if objective == "min_disenchant":
        return (-p.disenchant, p.improvement, p.sidegrade, result.stability_percent)
    raise ValueError(f"Unknown objective: {objective}")


def _push_result(heap, result: RitualResult, objective: str, top_n: int, order_key: tuple[int, ...]) -> None:
    key = (*objective_key(result, objective), order_key)
    entry = (key, result)
    if len(heap) < top_n:
        heapq.heappush(heap, entry)
    elif key > heap[0][0]:
        heapq.heapreplace(heap, entry)


def optimize(
    items: list[Item], *, center_essence: str, tier: int, objective: str, top_n: int = 10_000,
    flat_power_bonus: float = 0.0, flat_stability_bonus: float = 0.0,
    progress_callback: ProgressCallback | None = None, cancel_event: threading.Event | None = None,
) -> OptimizationSummary:
    enabled_items = [item for item in items if item.enabled]
    if len(enabled_items) < 5:
        raise ValueError("Enable at least five inventory items")
    if objective not in OBJECTIVES:
        raise ValueError(f"Unknown objective: {objective}")
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    total = unique_ring_order_count(len(enabled_items))
    heap = []
    evaluated = 0
    cancelled = False
    report_every = max(1, total // 200)
    index_of = {id(item): idx for idx, item in enumerate(enabled_items)}
    for order in iter_unique_ring_orders(enabled_items):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        result = evaluate_ritual(order, center_essence=center_essence, tier=tier,
                                 flat_power_bonus=flat_power_bonus, flat_stability_bonus=flat_stability_bonus)
        _push_result(heap, result, objective, top_n, tuple(index_of[id(item)] for item in order))
        evaluated += 1
        if progress_callback is not None and (evaluated % report_every == 0 or evaluated == total):
            progress_callback(evaluated, total)
    ordered = sorted(heap, key=lambda entry: entry[0], reverse=True)
    return OptimizationSummary(tuple(entry[1] for entry in ordered), evaluated, total, cancelled, 1)


# Worker-global immutable search context. Initializing it once per process avoids
# repeatedly pickling the item list and precomputed matrices for every partition.
_WORKER_CTX = None


def _build_edge_matrices(items: tuple[Item, ...], center_essence: str) -> tuple[tuple[tuple[float, ...], ...], tuple[tuple[float, ...], ...]]:
    center_mult = {ess: AFFINITIES[ess][center_essence] for ess in AFFINITIES}
    n = len(items)
    power = [[0.0] * n for _ in range(n)]
    stability = [[0.0] * n for _ in range(n)]
    for prev_idx, predecessor in enumerate(items):
        prev_table = AFFINITIES[predecessor.essence]
        for cur_idx, item in enumerate(items):
            prev_p, prev_s = prev_table[item.essence]
            center_p, center_s = center_mult[item.essence]
            power[prev_idx][cur_idx] = item.power * prev_p * center_p
            stability[prev_idx][cur_idx] = item.stability * prev_s * center_s
    return tuple(tuple(row) for row in power), tuple(tuple(row) for row in stability)


def _worker_init(items, center_essence, tier, objective, top_n, flat_power_bonus, flat_stability_bonus):
    global _WORKER_CTX
    rules = TIER_RULES[tier]
    p_edges, s_edges = _build_edge_matrices(items, center_essence)
    _WORKER_CTX = (
        len(items), p_edges, s_edges, rules.power_target, rules.stability_target,
        rules.sidegrade_coef, tier, objective, top_n, float(flat_power_bonus), float(flat_stability_bonus),
    )


def _fast_metrics(total_power: float, total_stability: float, power_target: float, stability_target: float, coef: float, tier: int):
    p = total_power / power_target
    s = total_stability / stability_target
    if p < 0.0: p = 0.0
    elif p > 1.0: p = 1.0
    if s < 0.0: s = 0.0
    elif s > 1.0: s = 1.0
    raw_upgrade = p * s
    sidegrade = p * (1.0 - s) / coef
    downgrade = (1.0 - p) * s
    # The documented four outcomes sum to exactly one, so no normalization pass
    # is needed for valid capped p/s values.
    disenchant = 1.0 - raw_upgrade - sidegrade - downgrade
    if tier == 1:
        disenchant += downgrade
        downgrade = 0.0
    jackpot = raw_upgrade - JACKPOT_UPGRADE_CAP
    if jackpot < 0.0: jackpot = 0.0
    return p, s, raw_upgrade, sidegrade, downgrade, disenchant, jackpot


def _fast_objective_key(metrics, objective: str, order: tuple[int, ...]):
    p, s, raw_upgrade, sidegrade, _downgrade, disenchant, jackpot = metrics
    if objective == "jackpot":
        return (jackpot, raw_upgrade, -disenchant, s, order)
    if objective == "balanced":
        return (min(p, s), -abs(p - s), raw_upgrade, order)
    if objective == "sidegrade":
        return (sidegrade, -disenchant, p, -s, order)
    return (-disenchant, raw_upgrade, sidegrade, s, order)  # min_disenchant


def _optimize_range(start: int, stop: int):
    n, p_edges, s_edges, p_target, s_target, coef, tier, objective, top_n, p_bonus, s_bonus = _WORKER_CTX
    heap = []
    evaluated = 0
    combos = itertools.islice(itertools.combinations(range(n), 5), start, stop)
    for combo in combos:
        a = combo[0]
        for perm in PERM4:
            b, c, d, e = combo[perm[0]], combo[perm[1]], combo[perm[2]], combo[perm[3]]
            order = (a, b, c, d, e)
            total_p = p_bonus + p_edges[e][a] + p_edges[a][b] + p_edges[b][c] + p_edges[c][d] + p_edges[d][e]
            total_s = s_bonus + s_edges[e][a] + s_edges[a][b] + s_edges[b][c] + s_edges[c][d] + s_edges[d][e]
            metrics = _fast_metrics(total_p, total_s, p_target, s_target, coef, tier)
            key = _fast_objective_key(metrics, objective, order)
            entry = (key, order)
            if len(heap) < top_n:
                heapq.heappush(heap, entry)
            elif key > heap[0][0]:
                heapq.heapreplace(heap, entry)
            evaluated += 1
    return heap, evaluated


def _partition_ranges(total_combinations: int, task_count: int) -> list[tuple[int, int]]:
    task_count = max(1, min(task_count, total_combinations))
    base, remainder = divmod(total_combinations, task_count)
    ranges = []
    start = 0
    for i in range(task_count):
        size = base + (1 if i < remainder else 0)
        ranges.append((start, start + size))
        start += size
    return ranges


def optimize_parallel(
    items: list[Item], *, center_essence: str, tier: int, objective: str, top_n: int = 10_000,
    flat_power_bonus: float = 0.0, flat_stability_bonus: float = 0.0, workers: int | None = None,
    chunk_size: int | None = None, progress_callback: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> OptimizationSummary:
    """Exact multi-process search with a precomputed numeric inner loop.

    Unlike v0.4, workers do not construct RitualResult/ComponentContribution objects
    for every candidate. Pairwise affinity contributions are precomputed once per
    process; only compact top candidates cross process boundaries. Full result
    objects are materialized after the global top-N is known.
    """
    enabled_items = tuple(item for item in items if item.enabled)
    if len(enabled_items) < 5:
        raise ValueError("Enable at least five inventory items")
    if objective not in OBJECTIVES:
        raise ValueError(f"Unknown objective: {objective}")
    if top_n < 1:
        raise ValueError("top_n must be at least 1")

    combination_count = math.comb(len(enabled_items), 5)
    total = combination_count * 24
    requested = workers if workers is not None and workers > 0 else (os.cpu_count() or 1)
    worker_count = max(1, min(int(requested), combination_count))
    if worker_count == 1:
        return optimize(list(enabled_items), center_essence=center_essence, tier=tier, objective=objective,
                        top_n=top_n, flat_power_bonus=flat_power_bonus, flat_stability_bonus=flat_stability_bonus,
                        progress_callback=progress_callback, cancel_event=cancel_event)

    # Two partitions per worker balances unequal process speed while keeping IPC
    # low. The legacy chunk_size argument is accepted for API compatibility only.
    ranges = _partition_ranges(combination_count, worker_count * 2)
    global_heap = []
    evaluated = 0
    cancelled = False
    executor = ProcessPoolExecutor(
        max_workers=worker_count,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_worker_init,
        initargs=(enabled_items, center_essence, tier, objective, top_n, flat_power_bonus, flat_stability_bonus),
    )
    futures = {executor.submit(_optimize_range, start, stop) for start, stop in ranges}
    try:
        while futures:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                for future in futures:
                    future.cancel()
                break
            done, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                local_heap, local_evaluated = future.result()
                evaluated += local_evaluated
                for entry in local_heap:
                    if len(global_heap) < top_n:
                        heapq.heappush(global_heap, entry)
                    elif entry[0] > global_heap[0][0]:
                        heapq.heapreplace(global_heap, entry)
                if progress_callback is not None:
                    progress_callback(evaluated, total)
    finally:
        executor.shutdown(wait=True, cancel_futures=cancelled)

    best = sorted(global_heap, key=lambda entry: entry[0], reverse=True)
    results = tuple(
        evaluate_ritual(tuple(enabled_items[i] for i in order), center_essence=center_essence, tier=tier,
                        flat_power_bonus=flat_power_bonus, flat_stability_bonus=flat_stability_bonus)
        for _key, order in best
    )
    return OptimizationSummary(results, evaluated, total, cancelled, worker_count)
