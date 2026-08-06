from __future__ import annotations

from dataclasses import dataclass

from .constants import ESSENCES


@dataclass(frozen=True, slots=True)
class Item:
    name: str
    essence: str
    power: float
    stability: float
    enabled: bool = True

    def __post_init__(self) -> None:
        normalized = self.essence.strip().lower()
        if normalized not in ESSENCES:
            raise ValueError(f"Unknown essence: {self.essence!r}")
        if not self.name.strip():
            raise ValueError("Item name cannot be empty")
        if self.power < 0 or self.stability < 0:
            raise ValueError("Power and stability must be non-negative")
        object.__setattr__(self, "essence", normalized)
        object.__setattr__(self, "name", self.name.strip())


@dataclass(frozen=True, slots=True)
class Probabilities:
    jackpot: float
    upgrade: float
    sidegrade: float
    downgrade: float
    disenchant: float

    @property
    def improvement(self) -> float:
        return self.jackpot + self.upgrade


@dataclass(frozen=True, slots=True)
class ComponentContribution:
    item: Item
    predecessor: Item
    predecessor_power_multiplier: float
    predecessor_stability_multiplier: float
    center_power_multiplier: float
    center_stability_multiplier: float
    power: float
    stability: float


@dataclass(frozen=True, slots=True)
class RitualResult:
    order: tuple[Item, ...]
    total_power: float
    total_stability: float
    power_percent: float
    stability_percent: float
    power_target: float
    stability_target: float
    flat_power_bonus: float
    flat_stability_bonus: float
    probabilities: Probabilities
    contributions: tuple[ComponentContribution, ...]

    @property
    def order_text(self) -> str:
        return " → ".join(item.name for item in self.order)
