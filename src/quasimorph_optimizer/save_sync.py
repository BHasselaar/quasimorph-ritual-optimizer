from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SaveSnapshot:
    path: Path
    quantities: dict[str, int]
    power_bonus: float
    stability_bonus: float
    perks: tuple[str, ...]


def default_save_dir() -> Path:
    base = os.environ.get("USERPROFILE")
    if base:
        return Path(base) / "AppData" / "LocalLow" / "Magnum Scriptum Ltd" / "Quasimorph"
    return Path.home() / "AppData" / "LocalLow" / "Magnum Scriptum Ltd" / "Quasimorph"


def find_session_saves(save_dir: Path | None = None) -> list[Path]:
    save_dir = save_dir or default_save_dir()
    if not save_dir.exists():
        return []
    return sorted(save_dir.glob("slot_*_session.dat"), key=lambda p: p.stat().st_mtime, reverse=True)


def _collect_items(value, totals: Counter[str]) -> None:
    containers = value if isinstance(value, list) else [value]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for entry in container.get("Items", []):
            if not isinstance(entry, dict):
                continue
            content = entry.get("Content", {})
            if not isinstance(content, dict):
                continue
            item_id = content.get("Id")
            if not item_id:
                continue
            try:
                qty = int(content.get("StackCount", "1"))
            except (TypeError, ValueError):
                qty = 1
            totals[str(item_id)] += max(0, qty)


def read_save(path: Path) -> SaveSnapshot:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    components = {entry.get("Type"): entry.get("Content", {}) for entry in data.get("Components", [])}
    cargo = components.get("MGSC.MagnumCargo", {})
    totals: Counter[str] = Counter()
    for key in ("ShipCargo", "FridgeStorage", "RecyclingStorage"):
        _collect_items(cargo.get(key, []), totals)

    progression = components.get("MGSC.MagnumProgression", {})
    perks = tuple(str(x) for x in progression.get("_purchasedPerks", []))
    perk_set = set(perks)
    power = 0.0
    stability = 0.0
    # Values verified against the current Morph Analysis upgrades discussed/tested for this game build.
    if "moranl_upgrade_power" in perk_set:
        power += 100.0
    if "moranl_upgrade_power_2" in perk_set:
        power += 100.0
    if "moranl_upgrade_stability" in perk_set:
        stability += 40.0

    return SaveSnapshot(path, dict(totals), power, stability, perks)
