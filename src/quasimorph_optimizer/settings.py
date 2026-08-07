from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class AppSettings:
    ship_power_bonus: float = 0.0
    ship_stability_bonus: float = 0.0
    worker_count: int = 0  # 0 = use all logical CPUs detected by Python.


def user_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "QuasimorphRitualOptimizer"
    return Path.home() / ".quasimorph-ritual-optimizer"


def settings_path() -> Path:
    return user_data_dir() / "settings.json"


def load_settings(path: Path | None = None) -> AppSettings:
    path = path or settings_path()
    if not path.exists():
        return AppSettings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()

    try:
        return AppSettings(
            ship_power_bonus=float(payload.get("ship_power_bonus", 0.0)),
            ship_stability_bonus=float(payload.get("ship_stability_bonus", 0.0)),
            worker_count=max(0, int(payload.get("worker_count", 0))),
        )
    except (TypeError, ValueError):
        return AppSettings()


def save_settings(settings: AppSettings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
