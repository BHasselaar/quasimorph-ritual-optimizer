from __future__ import annotations

from dataclasses import dataclass

ESSENCES = ("eon", "gavvakh", "shavva", "siaira", "agga")


@dataclass(frozen=True, slots=True)
class TierRules:
    power_target: float
    stability_target: float
    sidegrade_coef: float


TIER_RULES: dict[int, TierRules] = {
    1: TierRules(650.0, 100.0, 3.50),
    2: TierRules(800.0, 125.0, 3.10),
    3: TierRules(1000.0, 150.0, 2.70),
    4: TierRules(1300.0, 175.0, 2.30),
    5: TierRules(1600.0, 200.0, 1.25),
}

# source -> target -> (power multiplier, stability multiplier)
AFFINITIES: dict[str, dict[str, tuple[float, float]]] = {
    "eon": {
        "eon": (1.0, 1.0),
        "gavvakh": (0.8, 1.2),
        "shavva": (2.2, 0.2),
        "siaira": (0.5, 1.4),
        "agga": (1.8, 0.75),
    },
    "gavvakh": {
        "eon": (2.2, 0.2),
        "gavvakh": (1.0, 1.0),
        "shavva": (1.8, 0.75),
        "siaira": (0.8, 1.2),
        "agga": (0.5, 1.4),
    },
    "shavva": {
        "eon": (0.8, 1.2),
        "gavvakh": (0.5, 1.4),
        "shavva": (1.0, 1.0),
        "siaira": (1.8, 0.75),
        "agga": (2.2, 0.2),
    },
    "siaira": {
        "eon": (1.8, 0.75),
        "gavvakh": (2.2, 0.2),
        "shavva": (0.5, 1.4),
        "siaira": (1.0, 1.0),
        "agga": (0.8, 1.2),
    },
    "agga": {
        "eon": (0.5, 1.4),
        "gavvakh": (1.8, 0.75),
        "shavva": (0.8, 1.2),
        "siaira": (2.2, 0.2),
        "agga": (1.0, 1.0),
    },
}

JACKPOT_UPGRADE_CAP = 0.70
