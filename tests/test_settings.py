from pathlib import Path

from quasimorph_optimizer.settings import AppSettings, load_settings, save_settings


def test_settings_default_to_zero_bonuses(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.json")
    assert settings.ship_power_bonus == 0
    assert settings.ship_stability_bonus == 0
    assert settings.worker_count == 0
    assert settings.hide_unavailable is False


def test_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    expected = AppSettings(ship_power_bonus=100, ship_stability_bonus=40, worker_count=12, hide_unavailable=True)
    save_settings(expected, path)
    assert load_settings(path) == expected
