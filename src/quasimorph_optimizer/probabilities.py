from __future__ import annotations

from .constants import JACKPOT_UPGRADE_CAP, TIER_RULES
from .models import Probabilities


def calculate_base_probabilities(
    power_percent: float,
    stability_percent: float,
    tier: int,
) -> Probabilities:
    """Calculate the documented four in-game outcome categories.

    Jackpot is returned as zero here. The Upgrade field contains the entire raw
    improvement probability before the experimental Jackpot split.
    """
    if tier not in TIER_RULES:
        raise ValueError(f"Tier must be one of {tuple(TIER_RULES)}")

    p = min(1.0, max(0.0, float(power_percent)))
    s = min(1.0, max(0.0, float(stability_percent)))
    coef = TIER_RULES[tier].sidegrade_coef

    upgrade_raw = p * s
    sidegrade_raw = p * (1.0 - s) * (1.0 / coef)
    downgrade_raw = (1.0 - p) * s
    disenchant_raw = (1.0 - s) * (
        p * (1.0 - 1.0 / coef) + (1.0 - p)
    )

    if tier == 1:
        disenchant_raw += downgrade_raw
        downgrade_raw = 0.0

    values = [
        max(0.0, upgrade_raw),
        max(0.0, sidegrade_raw),
        max(0.0, downgrade_raw),
        max(0.0, disenchant_raw),
    ]
    total = sum(values)
    if total <= 0.0:
        return Probabilities(0.0, 0.0, 0.0, 0.0, 1.0)

    normalized = [value / total for value in values]
    return Probabilities(
        jackpot=0.0,
        upgrade=normalized[0],
        sidegrade=normalized[1],
        downgrade=normalized[2],
        disenchant=normalized[3],
    )


def calculate_probabilities(
    power_percent: float,
    stability_percent: float,
    tier: int,
    *,
    jackpot_cap: float = JACKPOT_UPGRADE_CAP,
) -> Probabilities:
    """Calculate outcomes and apply the experimental Jackpot split.

    The four-outcome calculation is supported by the supplied formulas and can
    be compared directly with the in-game display. The separate Jackpot value
    remains an unverified community assumption: raw Upgrade above
    ``jackpot_cap`` is moved to Jackpot while normal Upgrade is capped.
    """
    base = calculate_base_probabilities(power_percent, stability_percent, tier)
    jackpot = max(0.0, base.upgrade - jackpot_cap)
    upgrade = min(base.upgrade, jackpot_cap)
    return Probabilities(
        jackpot=jackpot,
        upgrade=upgrade,
        sidegrade=base.sidegrade,
        downgrade=base.downgrade,
        disenchant=base.disenchant,
    )
