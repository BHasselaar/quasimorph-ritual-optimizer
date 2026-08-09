from __future__ import annotations

from .constants import JACKPOT_UPGRADE_CAP, TIER_RULES, TierRules
from .models import Probabilities


def calculate_probabilities(
    power_percent: float, stability_percent: float, tier: int, *,
    jackpot_cap: float = JACKPOT_UPGRADE_CAP, tier_rules: dict[int, TierRules] | None = None,
) -> Probabilities:
    rules = tier_rules or TIER_RULES
    if tier not in rules:
        raise ValueError(f"Tier must be one of {tuple(rules)}")
    p = min(1.0, max(0.0, float(power_percent)))
    s = min(1.0, max(0.0, float(stability_percent)))
    coef = rules[tier].sidegrade_coef

    raw_upgrade = p * s
    jackpot = max(0.0, raw_upgrade - jackpot_cap) if tier < max(rules) else 0.0
    upgrade = min(raw_upgrade, jackpot_cap) if tier < max(rules) else raw_upgrade
    sidegrade = p * (1.0 - s) * (1.0 / coef if coef > 0 else 1.0)
    downgrade = (1.0 - p) * s
    disenchant = (1.0 - s) * (p * (1.0 - (1.0 / coef if coef > 0 else 1.0)) + (1.0 - p))
    if tier == min(rules):
        disenchant += downgrade
        downgrade = 0.0

    values = [max(0.0, jackpot), max(0.0, upgrade), max(0.0, sidegrade), max(0.0, downgrade), max(0.0, disenchant)]
    total = sum(values)
    if total <= 0.0:
        return Probabilities(0.0, 0.0, 0.0, 0.0, 1.0)
    return Probabilities(*(v / total for v in values))


def calculate_base_probabilities(power_percent: float, stability_percent: float, tier: int) -> Probabilities:
    # Compatibility helper: return outcomes before moving Upgrade excess to Jackpot.
    p = min(1.0, max(0.0, float(power_percent))); s = min(1.0, max(0.0, float(stability_percent)))
    coef = TIER_RULES[tier].sidegrade_coef
    upgrade = p * s
    sidegrade = p * (1-s) / coef
    downgrade = (1-p) * s
    disenchant = (1-s) * (p*(1-1/coef)+(1-p))
    if tier == 1: disenchant += downgrade; downgrade = 0.0
    vals=[upgrade,sidegrade,downgrade,disenchant]; total=sum(vals)
    return Probabilities(0.0, *(v/total for v in vals))
