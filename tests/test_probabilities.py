from math import isclose

from quasimorph_optimizer.probabilities import calculate_base_probabilities, calculate_probabilities


def test_probabilities_sum_to_one() -> None:
    result = calculate_probabilities(0.83, 0.47, 3)
    assert isclose(
        result.jackpot + result.upgrade + result.sidegrade + result.downgrade + result.disenchant,
        1.0,
        abs_tol=1e-12,
    )


def test_base_probabilities_match_four_outcome_formula() -> None:
    result = calculate_base_probabilities(0.45 / 0.86, 0.86, 3)
    assert isclose(result.upgrade, 0.45, abs_tol=1e-12)
    assert isclose(result.downgrade, 0.41, abs_tol=1e-12)
    assert round(result.sidegrade * 100) == 3
    assert round(result.disenchant * 100) == 11


def test_full_power_and_stability_splits_upgrade_and_jackpot() -> None:
    result = calculate_probabilities(1.0, 1.0, 2)
    assert isclose(result.jackpot, 0.30, abs_tol=1e-12)
    assert isclose(result.upgrade, 0.70, abs_tol=1e-12)
    assert isclose(result.sidegrade, 0.0, abs_tol=1e-12)
    assert isclose(result.downgrade, 0.0, abs_tol=1e-12)
    assert isclose(result.disenchant, 0.0, abs_tol=1e-12)


def test_tier_one_moves_downgrade_to_disenchant() -> None:
    result = calculate_probabilities(0.2, 0.9, 1)
    assert isclose(result.downgrade, 0.0, abs_tol=1e-12)
    assert result.disenchant > 0.7
