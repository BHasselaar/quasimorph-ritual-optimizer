from math import comb, factorial, isclose

from quasimorph_optimizer.models import Item
from quasimorph_optimizer.optimizer import evaluate_ritual, optimize, unique_ring_order_count


def sample_items() -> list[Item]:
    return [
        Item("A", "eon", 100, 25),
        Item("B", "gavvakh", 100, 25),
        Item("C", "shavva", 100, 25),
        Item("D", "siaira", 100, 25),
        Item("E", "agga", 100, 25),
        Item("F", "eon", 80, 20),
    ]


def test_unique_ring_order_count_collapses_rotations() -> None:
    assert unique_ring_order_count(6) == comb(6, 5) * factorial(4)


def test_rotation_has_identical_totals() -> None:
    order = tuple(sample_items()[:5])
    rotated = order[2:] + order[:2]
    first = evaluate_ritual(order, center_essence="siaira", tier=3)
    second = evaluate_ritual(rotated, center_essence="siaira", tier=3)
    assert isclose(first.total_power, second.total_power, abs_tol=1e-12)
    assert isclose(first.total_stability, second.total_stability, abs_tol=1e-12)


def test_optimizer_returns_requested_count() -> None:
    summary = optimize(sample_items(), center_essence="siaira", tier=3, objective="sidegrade", top_n=7)
    assert len(summary.results) == 7
    assert summary.evaluated == unique_ring_order_count(6)
    assert summary.results[0].probabilities.sidegrade >= summary.results[-1].probabilities.sidegrade


def test_flat_bonuses_are_added_after_component_affinities() -> None:
    order = tuple(sample_items()[:5])
    base = evaluate_ritual(order, center_essence="siaira", tier=3)
    boosted = evaluate_ritual(order, center_essence="siaira", tier=3, flat_power_bonus=100, flat_stability_bonus=40)
    assert isclose(boosted.total_power - base.total_power, 100.0, abs_tol=1e-12)
    assert isclose(boosted.total_stability - base.total_stability, 40.0, abs_tol=1e-12)


def test_parallel_optimizer_matches_single_process() -> None:
    from quasimorph_optimizer.optimizer import optimize_parallel

    items = sample_items()
    single = optimize(items, center_essence="siaira", tier=3, objective="sidegrade", top_n=7)
    parallel = optimize_parallel(
        items,
        center_essence="siaira",
        tier=3,
        objective="sidegrade",
        top_n=7,
        workers=2,
        chunk_size=1,
    )
    assert parallel.evaluated == single.evaluated
    assert parallel.workers_used == 2
    assert [r.order_text for r in parallel.results] == [r.order_text for r in single.results]
    assert [r.probabilities.sidegrade for r in parallel.results] == [r.probabilities.sidegrade for r in single.results]


def test_v05_objective_set_is_intentionally_small() -> None:
    from quasimorph_optimizer.optimizer import OBJECTIVES

    assert tuple(OBJECTIVES) == ("jackpot", "balanced", "sidegrade", "min_disenchant")


def test_parallel_matches_reference_for_every_supported_objective() -> None:
    from quasimorph_optimizer.optimizer import OBJECTIVES, optimize_parallel

    items = sample_items()
    for objective in OBJECTIVES:
        single = optimize(items, center_essence="siaira", tier=3, objective=objective, top_n=10)
        parallel = optimize_parallel(
            items, center_essence="siaira", tier=3, objective=objective, top_n=10, workers=2
        )
        assert [r.order_text for r in parallel.results] == [r.order_text for r in single.results]
