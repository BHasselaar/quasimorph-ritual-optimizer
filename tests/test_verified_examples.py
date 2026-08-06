from math import isclose

from quasimorph_optimizer.models import Item
from quasimorph_optimizer.optimizer import evaluate_ritual


def gold() -> Item:
    return Item("Load of Gold Bars", "eon", 110, 25)


def angerlings() -> Item:
    return Item("Angerlings", "gavvakh", 110, 15)


def evaluate_tier1(items: tuple[Item, ...]):
    return evaluate_ritual(
        items,
        center_essence="gavvakh",
        tier=1,
        flat_power_bonus=100,
    )


def test_tier1_five_gold_bars_matches_game() -> None:
    result = evaluate_tier1((gold(), gold(), gold(), gold(), gold()))
    p = result.probabilities
    assert isclose(result.total_power, 540.0)
    assert round(p.jackpot * 100) == 13
    assert round(p.upgrade * 100) == 70
    assert round(p.disenchant * 100) == 17


def test_tier1_four_gold_one_angerlings_matches_game() -> None:
    result = evaluate_tier1((gold(), gold(), gold(), gold(), angerlings()))
    p = result.probabilities
    assert isclose(result.total_power, 645.6)
    assert round(p.jackpot * 100) == 29
    assert round(p.upgrade * 100) == 70
    assert round(p.disenchant * 100) == 1


def test_tier1_three_gold_two_angerlings_has_hidden_sidegrade() -> None:
    result = evaluate_tier1((gold(), gold(), gold(), angerlings(), angerlings()))
    p = result.probabilities
    assert p.sidegrade > 0
    assert round(p.jackpot * 100) == 29
    assert round(p.upgrade * 100) == 70
    assert round(p.sidegrade * 100) == 0
    assert round(p.disenchant * 100) == 1


def test_tier1_two_gold_three_angerlings_matches_game() -> None:
    result = evaluate_tier1((gold(), gold(), angerlings(), angerlings(), angerlings()))
    p = result.probabilities
    assert round(p.jackpot * 100) == 14
    assert round(p.upgrade * 100) == 70
    assert round(p.sidegrade * 100) == 5
    assert round(p.disenchant * 100) == 11


def test_corrected_tier3_siaira_ritual_matches_game() -> None:
    order = (
        Item("Load of Gold Bars", "eon", 110, 25),
        Item("Gavvakh", "gavvakh", 100, 25),
        Item("Spider Joint", "agga", 80, 25),
        Item("Rotten Spider Flesh", "agga", 90, 10),
        Item("Feces", "eon", 50, 25),
    )
    result = evaluate_ritual(order, center_essence="siaira", tier=3, flat_power_bonus=100)
    p = result.probabilities
    assert isclose(result.total_power, 517.5, abs_tol=1e-12)
    assert isclose(result.total_stability, 129.0, abs_tol=1e-12)
    assert round(p.jackpot * 100) == 0
    assert round(p.upgrade * 100) == 45
    assert round(p.sidegrade * 100) == 3
    assert round(p.downgrade * 100) == 41
    assert round(p.disenchant * 100) == 11
