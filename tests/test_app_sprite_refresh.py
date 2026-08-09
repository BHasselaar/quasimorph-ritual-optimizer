import sys
import types
from pathlib import Path

tkinter_stub = types.ModuleType("tkinter")
tkinter_stub.Tk = type("Tk", (), {})
tkinter_stub.filedialog = types.ModuleType("tkinter.filedialog")
tkinter_stub.messagebox = types.ModuleType("tkinter.messagebox")
tkinter_stub.ttk = types.ModuleType("tkinter.ttk")
sys.modules["tkinter"] = tkinter_stub
sys.modules["tkinter.filedialog"] = tkinter_stub.filedialog
sys.modules["tkinter.messagebox"] = tkinter_stub.messagebox
sys.modules["tkinter.ttk"] = tkinter_stub.ttk

from quasimorph_optimizer import app
from quasimorph_optimizer.models import Item
from quasimorph_optimizer.sprites import (
    USER_CONFIRMED_SPRITE_ALIASES,
    _alias_object_is_allowed,
    _resolve_asset_names,
)


class _FakePhoto:
    def __init__(self, width: int, height: int, opaque: set[tuple[int, int]]):
        self._width = width
        self._height = height
        self._opaque = opaque

    def width(self) -> int:
        return self._width

    def height(self) -> int:
        return self._height

    def transparency_get(self, x: int, y: int) -> bool:
        return (x, y) not in self._opaque


def _component(internal_id: str, sprite_path: str = "") -> Item:
    return Item(
        "Component",
        "eon",
        1,
        1,
        True,
        internal_id,
        1,
        1,
        sprite_path,
    )


def test_component_sprite_mapping_overrides_existing_path():
    item = _component("moon_armor_plates", "old.png")

    sprite_path = app._sprite_path_after_component_refresh(
        item,
        {"moon_armor_plates": "authoritative_icons/moon_armor_plates.png"},
    )

    assert sprite_path == "authoritative_icons/moon_armor_plates.png"


def test_runtime_placeholder_path_falls_back_to_old_cache(monkeypatch, tmp_path: Path):
    cache = tmp_path / "sprites"
    cache.mkdir()
    cached = cache / "spider_joint.png"
    cached.write_bytes(b"png")
    monkeypatch.setattr(app, "sprite_cache_dir", lambda: cache)
    item = _component(
        "spider_joint",
        "sprite_mapping_investigation/runtime_fallback_icons/iconOneSlotPlaceholder.png",
    )

    sprite_path = app._sprite_path_after_component_refresh(item, {})

    assert sprite_path == str(cached)


def test_runtime_placeholder_path_is_cleared_without_cache(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(app, "sprite_cache_dir", lambda: tmp_path)
    item = _component("spider_joint", "runtime_fallback_icons/iconTwoSlotPlaceholder.png")

    sprite_path = app._sprite_path_after_component_refresh(item, {})

    assert sprite_path == ""


def test_valid_existing_sprite_path_is_preserved(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(app, "sprite_cache_dir", lambda: tmp_path)
    previous = tmp_path / "previous.png"
    previous.write_bytes(b"png")
    item = _component("spider_joint", str(previous))

    sprite_path = app._sprite_path_after_component_refresh(item, {})

    assert sprite_path == str(previous)


def test_missing_preserved_sprite_path_falls_back_to_cache(monkeypatch, tmp_path: Path):
    cache = tmp_path / "sprites"
    cache.mkdir()
    cached = cache / "spider_joint.png"
    cached.write_bytes(b"png")
    monkeypatch.setattr(app, "sprite_cache_dir", lambda: cache)
    item = _component("spider_joint", str(tmp_path / "deleted.png"))

    sprite_path = app._sprite_path_after_component_refresh(item, {})

    assert sprite_path == str(cached)


def test_sprite_content_size_fits_large_and_medium_icons_to_same_box():
    assert app._fit_sprite_content_size(64, 64) == (44, 44)
    assert app._fit_sprite_content_size(32, 32) == (44, 44)


def test_sprite_content_size_preserves_aspect_ratio_and_caps_tiny_icons():
    assert app._fit_sprite_content_size(96, 48) == (44, 22)
    assert app._fit_sprite_content_size(8, 8) == (24, 24)


def test_sprite_visible_bbox_ignores_transparent_padding():
    image = _FakePhoto(
        10,
        10,
        {
            (3, 2),
            (4, 2),
            (3, 3),
            (4, 3),
            (5, 4),
        },
    )

    assert app._photo_visible_bbox(image) == (3, 2, 6, 5)


def test_quasiplumbum_resolves_to_exact_moon_armor_alias():
    item = _component("moon_armor_plates")

    resolved = _resolve_asset_names([item], {"moon_armor_inv"})

    assert resolved["moon_armor_plates"] == ("moon_armor_inv", 10000)


def test_mars_gear_resolves_to_exact_mars_gear_inv_alias():
    item = _component("mars_gear")

    resolved = _resolve_asset_names([item], {"mars_gear_inv"})

    assert resolved["mars_gear"] == ("mars_gear_inv", 10000)


def test_unconfirmed_fuzzy_sprite_name_is_not_accepted():
    item = _component("unknown_component")

    resolved = _resolve_asset_names([item], {"unknown_component_inv"})

    assert resolved == {}


def test_quasiplumbum_duplicate_name_requires_confirmed_path_id():
    assert _alias_object_is_allowed(
        "moon_armor_plates",
        "moon_armor_inv",
        "Texture2D",
        6786,
    )
    assert not _alias_object_is_allowed(
        "moon_armor_plates",
        "moon_armor_inv",
        "Texture2D",
        12345,
    )
    assert _alias_object_is_allowed(
        "moon_armor_plates",
        "moon_armor_inv",
        "Sprite",
        20834,
    )
    assert _alias_object_is_allowed(
        "moon_armor_plates",
        "moon_armor_inv",
        "Sprite",
        6791,
    )
    assert not _alias_object_is_allowed(
        "moon_armor_plates",
        "moon_armor_inv",
        "Sprite",
        12345,
    )


def test_latest_user_confirmed_alias_batch_is_preserved():
    assert len(USER_CONFIRMED_SPRITE_ALIASES) == 74

    expected = {
        "quasi_venus_rags": "aztec_rags_inv",
        "venus_weapon_parts": "aztKey_inv",
        "venus_guts": "aztec_guts_inv",
        "syringe_bloodbag": "bloodBag_inv",
        "quasi_medical_kit_1": "demonicMeds_inv",
        "rotten_human_meat": "rottenMeat1_inv",
        "rotten_dog_meat": "rotten_dog_meat_inv",
        "moon_guts": "moon_guts_inv",
        "precious_metals": "precious_metals_inv",
        "quasi_energy_ammo": "quasi_energy_ammo_inv",
        "ron_blood": "ron_blood_inv",
        "venus_armor_plates": "venus_shard_inv",
        "quasi_repair_kit": "demonicShards_inv",
    }

    for item_id, asset_name in expected.items():
        assert USER_CONFIRMED_SPRITE_ALIASES[item_id] == (asset_name,)


def test_component_sprite_missing_checks_deleted_files(tmp_path: Path):
    existing = tmp_path / "sprite.png"
    existing.write_bytes(b"png")

    assert not app._component_sprite_missing(_component("spider_joint", str(existing)))
    assert app._component_sprite_missing(_component("spider_joint", str(tmp_path / "deleted.png")))
    assert app._component_sprite_missing(_component("spider_joint", ""))
