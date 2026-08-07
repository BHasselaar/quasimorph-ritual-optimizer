from __future__ import annotations

import csv
from importlib import resources
from pathlib import Path

from .models import Item
from .settings import user_data_dir

CSV_FIELDS = ("enabled", "name", "essence", "power", "stability")


def _parse_enabled(value: str) -> bool:
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def load_inventory(path: Path) -> list[Item]:
    items: list[Item] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"name", "essence", "power", "stability"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"Inventory CSV is missing columns: {', '.join(sorted(missing))}")
        for line_number, row in enumerate(reader, start=2):
            try:
                items.append(
                    Item(
                        name=row["name"],
                        essence=row["essence"],
                        power=float(row["power"]),
                        stability=float(row["stability"]),
                        enabled=_parse_enabled(row.get("enabled", "true")),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid inventory row {line_number}: {exc}") from exc
    return items


def save_inventory(path: Path, items: list[Item]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "enabled": "true" if item.enabled else "false",
                    "name": item.name,
                    "essence": item.essence,
                    "power": f"{item.power:g}",
                    "stability": f"{item.stability:g}",
                }
            )


def user_inventory_path() -> Path:
    return user_data_dir() / "inventory.csv"


def reset_user_inventory_to_default() -> Path:
    target = user_inventory_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    default_resource = resources.files("quasimorph_optimizer.data").joinpath("default_inventory.csv")
    target.write_bytes(default_resource.read_bytes())
    return target


def ensure_user_inventory() -> Path:
    target = user_inventory_path()
    if not target.exists():
        reset_user_inventory_to_default()
    return target
