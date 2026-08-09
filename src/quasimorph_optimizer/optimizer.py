from __future__ import annotations

import heapq
import itertools
import math
import multiprocessing
import os
import threading
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass

import numpy as np

from .constants import AFFINITIES, JACKPOT_UPGRADE_CAP, TIER_RULES, TierRules
from .game_data import GameRules
from .models import ComponentContribution, Item, RitualResult
from .probabilities import calculate_probabilities

ProgressCallback = callable


@dataclass(frozen=True, slots=True)
class OptimizationSummary:
    results: tuple[RitualResult, ...]
    evaluated: int
    total_candidates: int
    cancelled: bool
    workers_used: int = 1
    backend: str = "python"


OBJECTIVES = {
    "jackpot": "Jackpot",
    "balanced": "Balanced",
    "sidegrade": "Sidegrade",
    "min_disenchant": "Minimum Disenchant",
}


def unique_ring_order_count(item_count: int) -> int:
    if item_count < 5:
        return 0
    return math.comb(item_count, 5) * 24


def quantity_ring_order_count(items: list[Item]) -> int:
    active = [i for i in items if i.enabled and i.quantity > 0]
    n = len(active)
    if n == 0:
        return 0
    q = [min(5, i.quantity) for i in active]
    total = math.comb(n, 5) * 24 if n >= 5 else 0
    e2 = [i for i, x in enumerate(q) if x >= 2]
    e3 = [i for i, x in enumerate(q) if x >= 3]
    e4 = [i for i, x in enumerate(q) if x >= 4]
    e5 = [i for i, x in enumerate(q) if x >= 5]
    if n >= 4:
        total += len(e2) * math.comb(n - 1, 3) * 12
    if len(e2) >= 2 and n >= 3:
        total += math.comb(len(e2), 2) * (n - 2) * 6
    if n >= 3:
        total += len(e3) * math.comb(n - 1, 2) * 4
    total += sum(1 for a in e3 for b in e2 if a != b) * 2
    if n >= 2:
        total += len(e4) * (n - 1)
    total += len(e5)
    return total


def ritual_order_count(items: list[Item], allow_repeats: bool = False) -> int:
    active = [i for i in items if i.enabled and i.quantity > 0]
    return quantity_ring_order_count(active) if allow_repeats else unique_ring_order_count(len(active))


def _resolved_rules(game_rules: GameRules | None):
    return (
        game_rules.tier_rules if game_rules else TIER_RULES,
        game_rules.affinities if game_rules else AFFINITIES,
        game_rules.jackpot_cap if game_rules else JACKPOT_UPGRADE_CAP,
    )


def evaluate_ritual(
    order: tuple[Item, ...],
    *,
    center_essence: str,
    tier: int,
    flat_power_bonus: float = 0.0,
    flat_stability_bonus: float = 0.0,
    game_rules: GameRules | None = None,
) -> RitualResult:
    if len(order) != 5:
        raise ValueError("A ritual must contain exactly five component items")
    tier_rules, affinities, cap = _resolved_rules(game_rules)
    if center_essence not in affinities:
        raise ValueError(f"Unknown center essence: {center_essence}")
    if tier not in tier_rules:
        raise ValueError(f"Unknown tier: {tier}")

    contributions = []
    total_power = float(flat_power_bonus)
    total_stability = float(flat_stability_bonus)
    for index, item in enumerate(order):
        predecessor = order[index - 1]
        pp, ps = affinities[predecessor.essence][item.essence]
        cp, cs = affinities[item.essence][center_essence]
        power = item.power * pp * cp
        stability = item.stability * ps * cs
        total_power += power
        total_stability += stability
        contributions.append(
            ComponentContribution(item, predecessor, pp, ps, cp, cs, power, stability)
        )

    targets = tier_rules[tier]
    p = min(1.0, max(0.0, total_power / targets.power_target))
    s = min(1.0, max(0.0, total_stability / targets.stability_target))
    probs = calculate_probabilities(
        p, s, tier, jackpot_cap=cap, tier_rules=tier_rules
    )
    return RitualResult(
        order,
        total_power,
        total_stability,
        p,
        s,
        targets.power_target,
        targets.stability_target,
        float(flat_power_bonus),
        float(flat_stability_bonus),
        probs,
        tuple(contributions),
    )


def objective_key(result: RitualResult, objective: str):
    p = result.probabilities
    if objective == "jackpot":
        return (p.jackpot, p.improvement, -p.disenchant, result.stability_percent)
    if objective == "balanced":
        return (
            min(result.power_percent, result.stability_percent),
            -abs(result.power_percent - result.stability_percent),
            p.improvement,
        )
    if objective == "sidegrade":
        return (
            p.sidegrade,
            -p.disenchant,
            result.power_percent,
            -result.stability_percent,
        )
    if objective == "min_disenchant":
        return (-p.disenchant, p.improvement, p.sidegrade, result.stability_percent)
    raise ValueError(f"Unknown objective: {objective}")


def _build_edges(items, center, affinities):
    n = len(items)
    p = np.zeros((n, n), dtype=np.float64)
    s = np.zeros((n, n), dtype=np.float64)
    for prev_idx, prev in enumerate(items):
        for cur_idx, item in enumerate(items):
            pp, ps = affinities[prev.essence][item.essence]
            cp, cs = affinities[item.essence][center]
            p[prev_idx, cur_idx] = item.power * pp * cp
            s[prev_idx, cur_idx] = item.stability * ps * cs
    return p, s


def _metrics_numpy(tp, ts, pt, st, coef, tier, max_tier, cap):
    p = np.clip(tp / pt, 0.0, 1.0)
    s = np.clip(ts / st, 0.0, 1.0)
    raw = p * s
    if tier < max_tier:
        jackpot = np.maximum(0.0, raw - cap)
        upgrade = np.minimum(raw, cap)
    else:
        jackpot = np.zeros_like(raw)
        upgrade = raw

    side_factor = 1.0 / coef if coef > 0 else 1.0
    sg = p * (1.0 - s) * side_factor
    dg = (1.0 - p) * s
    dis = (1.0 - s) * (p * (1.0 - side_factor) + (1.0 - p))
    if tier == 1:
        dis = dis + dg
        dg = np.zeros_like(dg)

    total = jackpot + upgrade + sg + dg + dis
    safe = total > 0
    jackpot = np.divide(jackpot, total, out=np.zeros_like(jackpot), where=safe)
    upgrade = np.divide(upgrade, total, out=np.zeros_like(upgrade), where=safe)
    sg = np.divide(sg, total, out=np.zeros_like(sg), where=safe)
    dg = np.divide(dg, total, out=np.zeros_like(dg), where=safe)
    dis = np.divide(dis, total, out=np.ones_like(dis), where=safe)
    return p, s, jackpot, upgrade, sg, dg, dis


def _metric_arrays(metrics, objective):
    p, s, j, u, sg, dg, di = metrics
    if objective == "jackpot":
        return (j, j + u, -di, s)
    if objective == "balanced":
        return (np.minimum(p, s), -np.abs(p - s), j + u)
    if objective == "sidegrade":
        return (sg, -di, p, -s)
    if objective == "min_disenchant":
        return (-di, j + u, sg, s)
    raise ValueError(objective)


def _python_key_from_metrics(metrics, objective, order):
    p, s, j, u, sg, dg, di = metrics
    if objective == "jackpot":
        key = (j, j + u, -di, s)
    elif objective == "balanced":
        key = (min(p, s), -abs(p - s), j + u)
    elif objective == "sidegrade":
        key = (sg, -di, p, -s)
    elif objective == "min_disenchant":
        key = (-di, j + u, sg, s)
    else:
        raise ValueError(objective)
    return (*key, tuple(-int(x) for x in order))


# ---- NumPy distinct-component backend ------------------------------------

_DISTINCT_CTX = None
PERMS4 = np.asarray(list(itertools.permutations(range(4))), dtype=np.int16)


def _distinct_worker_init(items, center, tier, objective, top_n, pbonus, sbonus,
                          tier_rules, affinities, cap, combo_batch):
    global _DISTINCT_CTX
    pe, se = _build_edges(items, center, affinities)
    rules = tier_rules[tier]
    _DISTINCT_CTX = (
        len(items), pe, se, rules.power_target, rules.stability_target,
        rules.sidegrade_coef, tier, max(tier_rules), objective, top_n,
        float(pbonus), float(sbonus), float(cap), int(combo_batch),
    )


def _top_indices(metrics, objective, orders, keep):
    arrays = _metric_arrays(metrics, objective)
    # np.lexsort sorts ascending using the LAST key as primary.
    # Objective metrics are negated for descending ranking; order is ascending
    # for deterministic tie-breaking (equivalent to tuple(-order) descending).
    keys = tuple(orders[:, i] for i in range(4, -1, -1))
    keys = keys + tuple(-arr for arr in arrays[::-1])
    ranked = np.lexsort(keys)
    return ranked[: min(keep, len(ranked))]


def _distinct_group(a_values):
    n, pe, se, pt, st, coef, tier, max_tier, objective, top_n, pbonus, sbonus, cap, combo_batch = _DISTINCT_CTX
    heap = []
    evaluated = 0

    for a in a_values:
        combo_iter = itertools.combinations(range(a + 1, n), 4)
        while True:
            chunk = list(itertools.islice(combo_iter, combo_batch))
            if not chunk:
                break
            combos = np.asarray(chunk, dtype=np.int32)
            k = combos.shape[0]

            # 24 clockwise orders per 5-element set with the smallest index
            # anchored at position 0. This removes rotational duplicates exactly.
            permuted = combos[:, PERMS4].reshape(-1, 4)
            orders = np.empty((k * 24, 5), dtype=np.int32)
            orders[:, 0] = a
            orders[:, 1:] = permuted

            tp = (
                pbonus
                + pe[orders[:, 4], orders[:, 0]]
                + pe[orders[:, 0], orders[:, 1]]
                + pe[orders[:, 1], orders[:, 2]]
                + pe[orders[:, 2], orders[:, 3]]
                + pe[orders[:, 3], orders[:, 4]]
            )
            ts = (
                sbonus
                + se[orders[:, 4], orders[:, 0]]
                + se[orders[:, 0], orders[:, 1]]
                + se[orders[:, 1], orders[:, 2]]
                + se[orders[:, 2], orders[:, 3]]
                + se[orders[:, 3], orders[:, 4]]
            )
            metrics = _metrics_numpy(tp, ts, pt, st, coef, tier, max_tier, cap)
            idxs = _top_indices(metrics, objective, orders, top_n)

            for idx in idxs:
                order = tuple(int(x) for x in orders[idx])
                scalar_metrics = tuple(float(arr[idx]) for arr in metrics)
                key = _python_key_from_metrics(scalar_metrics, objective, order)
                entry = (key, order)
                if len(heap) < top_n:
                    heapq.heappush(heap, entry)
                elif key > heap[0][0]:
                    heapq.heapreplace(heap, entry)
            evaluated += len(orders)

    return heap, evaluated


def _group_a_values(n, group_count):
    values = [(a, math.comb(n - a - 1, 4) * 24 if n - a - 1 >= 4 else 0)
              for a in range(max(0, n - 4))]
    groups = [[] for _ in range(max(1, min(group_count, len(values) or 1)))]
    loads = [0] * len(groups)
    for a, weight in sorted(values, key=lambda x: x[1], reverse=True):
        k = min(range(len(groups)), key=loads.__getitem__)
        groups[k].append(a)
        loads[k] += weight
    return [g for g in groups if g]


def _optimize_distinct_numpy(active, *, center_essence, tier, objective, top_n,
                             flat_power_bonus, flat_stability_bonus, workers,
                             progress_callback, cancel_event, tier_rules,
                             affinities, cap, combo_batch=5000):
    total = unique_ring_order_count(len(active))
    requested = workers if workers and workers > 0 else (os.cpu_count() or 1)
    worker_count = max(1, min(int(requested), max(1, len(active) - 4)))
    task_groups = _group_a_values(len(active), worker_count * 3)
    global_heap = []
    evaluated = 0
    cancelled = False

    initargs = (
        active, center_essence, tier, objective, top_n, flat_power_bonus,
        flat_stability_bonus, tier_rules, affinities, cap, combo_batch,
    )

    if worker_count == 1:
        _distinct_worker_init(*initargs)
        for group in task_groups:
            if cancel_event and cancel_event.is_set():
                cancelled = True
                break
            local, count = _distinct_group(group)
            evaluated += count
            for entry in local:
                if len(global_heap) < top_n:
                    heapq.heappush(global_heap, entry)
                elif entry[0] > global_heap[0][0]:
                    heapq.heapreplace(global_heap, entry)
            if progress_callback:
                progress_callback(evaluated, total)
    else:
        executor = ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_distinct_worker_init,
            initargs=initargs,
        )
        futures = {executor.submit(_distinct_group, group) for group in task_groups}
        try:
            while futures:
                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    for f in futures:
                        f.cancel()
                    break
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                for f in done:
                    local, count = f.result()
                    evaluated += count
                    for entry in local:
                        if len(global_heap) < top_n:
                            heapq.heappush(global_heap, entry)
                        elif entry[0] > global_heap[0][0]:
                            heapq.heapreplace(global_heap, entry)
                    if progress_callback:
                        progress_callback(evaluated, total)
        finally:
            executor.shutdown(wait=True, cancel_futures=cancelled)

    return global_heap, evaluated, total, cancelled, worker_count


# ---- Quantity-aware legacy backend (optional advanced mode) --------------

_REPEAT_CTX = None


def _canonical_ring(order):
    for j in range(1, 5):
        if order[j] == order[0] and order[j:] + order[:j] < order:
            return False
    return True


def _quantities_allow(order, qty):
    a, b, c, d, e = order
    if qty[a] < 1 + (b == a) + (c == a) + (d == a) + (e == a):
        return False
    if b != a and qty[b] < 1 + (c == b) + (d == b) + (e == b):
        return False
    if c != a and c != b and qty[c] < 1 + (d == c) + (e == c):
        return False
    if d != a and d != b and d != c and qty[d] < 1 + (e == d):
        return False
    return True


def _repeat_worker_init(items, center, tier, objective, top_n, pbonus, sbonus,
                        tier_rules, affinities, cap):
    global _REPEAT_CTX
    pe, se = _build_edges(items, center, affinities)
    rules = tier_rules[tier]
    _REPEAT_CTX = (
        len(items), tuple(min(5, i.quantity) for i in items), pe, se,
        rules.power_target, rules.stability_target, rules.sidegrade_coef,
        tier, max(tier_rules), objective, top_n, float(pbonus), float(sbonus), float(cap),
    )


def _repeat_prefix(a, b):
    n, qty, pe, se, pt, st, coef, tier, max_tier, obj, top_n, pbonus, sbonus, cap = _REPEAT_CTX
    heap = []
    evaluated = 0
    for c in range(a, n):
        for d in range(a, n):
            for e in range(a, n):
                order = (a, b, c, d, e)
                if not _quantities_allow(order, qty) or not _canonical_ring(order):
                    continue
                tp = pbonus + pe[e, a] + pe[a, b] + pe[b, c] + pe[c, d] + pe[d, e]
                ts = sbonus + se[e, a] + se[a, b] + se[b, c] + se[c, d] + se[d, e]
                metrics = _metrics_numpy(
                    np.asarray([tp]), np.asarray([ts]), pt, st, coef, tier, max_tier, cap
                )
                scalar_metrics = tuple(float(x[0]) for x in metrics)
                key = _python_key_from_metrics(scalar_metrics, obj, order)
                entry = (key, order)
                if len(heap) < top_n:
                    heapq.heappush(heap, entry)
                elif key > heap[0][0]:
                    heapq.heapreplace(heap, entry)
                evaluated += 1
    return heap, evaluated


def _repeat_group(prefixes):
    merged = []
    evaluated = 0
    n, qty, pe, se, pt, st, coef, tier, max_tier, obj, top_n, pbonus, sbonus, cap = _REPEAT_CTX
    for a, b in prefixes:
        local, count = _repeat_prefix(a, b)
        evaluated += count
        for entry in local:
            if len(merged) < top_n:
                heapq.heappush(merged, entry)
            elif entry[0] > merged[0][0]:
                heapq.heapreplace(merged, entry)
    return merged, evaluated


def _repeat_groups(n, group_count):
    prefixes = [(a, b, (n - a) ** 3) for a in range(n) for b in range(a, n)]
    groups = [[] for _ in range(max(1, min(group_count, len(prefixes))))]
    loads = [0] * len(groups)
    for a, b, weight in sorted(prefixes, key=lambda x: x[2], reverse=True):
        k = min(range(len(groups)), key=loads.__getitem__)
        groups[k].append((a, b))
        loads[k] += weight
    return [g for g in groups if g]


def _optimize_repeats(active, *, center_essence, tier, objective, top_n,
                      flat_power_bonus, flat_stability_bonus, workers,
                      progress_callback, cancel_event, tier_rules, affinities, cap):
    total = quantity_ring_order_count(list(active))
    requested = workers if workers and workers > 0 else (os.cpu_count() or 1)
    worker_count = max(1, min(int(requested), max(1, len(active))))
    groups = _repeat_groups(len(active), worker_count * 3)
    global_heap = []
    evaluated = 0
    cancelled = False
    initargs = (
        active, center_essence, tier, objective, top_n, flat_power_bonus,
        flat_stability_bonus, tier_rules, affinities, cap,
    )

    if worker_count == 1:
        _repeat_worker_init(*initargs)
        for group in groups:
            if cancel_event and cancel_event.is_set():
                cancelled = True
                break
            local, count = _repeat_group(group)
            evaluated += count
            for entry in local:
                if len(global_heap) < top_n:
                    heapq.heappush(global_heap, entry)
                elif entry[0] > global_heap[0][0]:
                    heapq.heapreplace(global_heap, entry)
            if progress_callback:
                progress_callback(evaluated, total)
    else:
        executor = ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_repeat_worker_init,
            initargs=initargs,
        )
        futures = {executor.submit(_repeat_group, group) for group in groups}
        try:
            while futures:
                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    for f in futures:
                        f.cancel()
                    break
                done, futures = wait(futures, return_when=FIRST_COMPLETED)
                for f in done:
                    local, count = f.result()
                    evaluated += count
                    for entry in local:
                        if len(global_heap) < top_n:
                            heapq.heappush(global_heap, entry)
                        elif entry[0] > global_heap[0][0]:
                            heapq.heapreplace(global_heap, entry)
                    if progress_callback:
                        progress_callback(evaluated, total)
        finally:
            executor.shutdown(wait=True, cancel_futures=cancelled)

    return global_heap, evaluated, total, cancelled, worker_count


def optimize_parallel(
    items: list[Item],
    *,
    center_essence: str,
    tier: int,
    objective: str,
    top_n: int = 10_000,
    flat_power_bonus: float = 0,
    flat_stability_bonus: float = 0,
    workers: int | None = None,
    progress_callback=None,
    cancel_event: threading.Event | None = None,
    game_rules: GameRules | None = None,
    allow_repeats: bool = False,
    combo_batch: int = 5000,
    chunk_size=None,
) -> OptimizationSummary:
    active = tuple(i for i in items if i.enabled and i.quantity > 0)
    if len(active) < 5 and not allow_repeats:
        if sum(i.quantity for i in active) >= 5:
            allow_repeats = True
        else:
            raise ValueError("At least five distinct available component types are required")
    if sum(i.quantity for i in active) < 5:
        raise ValueError("At least five component units are required")
    if objective not in OBJECTIVES:
        raise ValueError(f"Unknown objective: {objective}")

    tier_rules, affinities, cap = _resolved_rules(game_rules)

    if allow_repeats:
        heap, evaluated, total, cancelled, worker_count = _optimize_repeats(
            active,
            center_essence=center_essence,
            tier=tier,
            objective=objective,
            top_n=top_n,
            flat_power_bonus=flat_power_bonus,
            flat_stability_bonus=flat_stability_bonus,
            workers=workers,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            tier_rules=tier_rules,
            affinities=affinities,
            cap=cap,
        )
        backend = "quantity-aware"
    else:
        heap, evaluated, total, cancelled, worker_count = _optimize_distinct_numpy(
            active,
            center_essence=center_essence,
            tier=tier,
            objective=objective,
            top_n=top_n,
            flat_power_bonus=flat_power_bonus,
            flat_stability_bonus=flat_stability_bonus,
            workers=workers,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
            tier_rules=tier_rules,
            affinities=affinities,
            cap=cap,
            combo_batch=combo_batch,
        )
        backend = "numpy-batch"

    best = sorted(heap, key=lambda x: x[0], reverse=True)
    results = tuple(
        evaluate_ritual(
            tuple(active[i] for i in order),
            center_essence=center_essence,
            tier=tier,
            flat_power_bonus=flat_power_bonus,
            flat_stability_bonus=flat_stability_bonus,
            game_rules=game_rules,
        )
        for _, order in best
    )
    return OptimizationSummary(
        results, evaluated, total, cancelled, worker_count, backend
    )


def optimize(items: list[Item], **kwargs):
    kwargs["workers"] = 1
    return optimize_parallel(items, **kwargs)
