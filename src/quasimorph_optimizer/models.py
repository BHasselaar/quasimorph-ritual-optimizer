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
    internal_id: str = ""
    quantity: int = 1
    max_stack: int = 1
    sprite_path: str = ""
    price: float = 0.0

    def __post_init__(self) -> None:
        normalized = self.essence.strip().lower()
        if normalized not in ESSENCES:
            raise ValueError(f"Unknown essence: {self.essence!r}")
        if not self.name.strip():
            raise ValueError("Item name cannot be empty")
        if self.power < 0 or self.stability < 0 or self.price < 0:
            raise ValueError("Power, stability, and price must be non-negative")
        if int(self.quantity) < 0:
            raise ValueError("Quantity must be non-negative")
        object.__setattr__(self, "essence", normalized)
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "internal_id", self.internal_id.strip())
        object.__setattr__(self, "quantity", int(self.quantity))
        object.__setattr__(self, "max_stack", max(1, int(self.max_stack)))
        object.__setattr__(self, "price", float(self.price))


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

    @property
    def total_price(self) -> float:
        return sum(item.price for item in self.order)
