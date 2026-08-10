from __future__ import annotations

import json
import re
from pathlib import Path

from .confirmed_sprites import (
    USER_CONFIRMED_SPRITE_ALIASES,
    USER_CONFIRMED_SPRITE_OBJECTS,
)
from .models import Item
from .settings import user_data_dir

# Explicit internal-ID -> Unity inventory-art aliases. This should mirror only
# mappings that have been confirmed, not exploratory/fuzzy guesses.
EXACT_SPRITE_ALIASES: dict[str, tuple[str, ...]] = dict(USER_CONFIRMED_SPRITE_ALIASES)


def sprite_cache_dir() -> Path:
    return user_data_dir() / "sprites"


def sprite_report_path() -> Path:
    return user_data_dir() / "sprite_extraction_report.json"


def _alias_object_is_allowed(
    item_id: str,
    asset_name: str,
    object_type: str,
    path_id,
) -> bool:
    reference = USER_CONFIRMED_SPRITE_OBJECTS.get(item_id)
    if not reference:
        return True
    asset_names = reference.get("asset_names", ())
    if asset_name not in asset_names:
        return True
    key = "texture_path_ids" if object_type == "Texture2D" else "sprite_path_ids"
    allowed_ids = reference.get(key, ())
    if not allowed_ids:
        return True
    try:
        return int(path_id) in allowed_ids
    except (TypeError, ValueError):
        return False


def _norm(value: str) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    token_aliases = {
        "aye": "eye",
        "gavaah": "gavvakh",
    }
    return "_".join(token_aliases.get(t, t) for t in value.split("_"))


def _base(value: str) -> str:
    n = _norm(value)
    for suffix in (
        "_inv",
        "_icon",
        "_inventory",
        "_floor",
        "_shadow",
        "_sprite",
        "_texture",
    ):
        if n.endswith(suffix):
            n = n[:-len(suffix)]
    return n


def _strip_version(value: str) -> str:
    return re.sub(r"_\d+$", "", value)


def _candidate_score(item: Item, asset_name: str, asset_type: str = "") -> int:
    normalized = _norm(asset_name)

    aliases = {_norm(x) for x in EXACT_SPRITE_ALIASES.get(item.internal_id, ())}
    if normalized in aliases:
        return 10000

    iid = _base(item.internal_id)
    display = _base(item.name)
    candidate = _base(asset_name)
    if not candidate:
        return 0

    score = 0
    if iid and candidate == iid:
        score = max(score, 240)
    if iid and _strip_version(candidate) == _strip_version(iid):
        score = max(score, 220)
    if display and candidate == display:
        score = max(score, 215)

    for source, base_score in ((iid, 165), (display, 155)):
        tokens = [t for t in source.split("_") if len(t) > 1]
        cand_tokens = set(candidate.split("_"))
        if tokens and all(t in cand_tokens for t in tokens):
            score = max(score, base_score)

    if normalized.endswith("_inv"):
        score += 18
    elif normalized.endswith("_icon"):
        score += 12

    return score


def _resolve_asset_names(items: list[Item], available_names: set[str]) -> dict[str, tuple[str, int]]:
    """Resolve each item ID to a confirmed asset name without fuzzy fallback."""
    result: dict[str, tuple[str, int]] = {}

    for item in items:
        if not item.internal_id:
            continue

        for alias in EXACT_SPRITE_ALIASES.get(item.internal_id, ()):
            if alias in available_names:
                result[item.internal_id] = (alias, 10000)
                break

    return result


def extract_exact_sprite_aliases(
    game_path: Path,
    item_ids: set[str],
) -> dict[str, str]:
    """
    Extract only explicitly curated item-id -> asset-name aliases.

    This is intentionally narrower than the legacy fuzzy extractor. It is used
    for known exceptions such as Quasiplumbum, where the game descriptor has a
    null _icon but the exact Texture2D name is known.
    """
    try:
        import UnityPy
    except ImportError as exc:
        raise RuntimeError("Exact sprite alias export requires UnityPy.") from exc

    wanted = {
        item_id: EXACT_SPRITE_ALIASES[item_id]
        for item_id in item_ids
        if item_id in EXACT_SPRITE_ALIASES
    }
    if not wanted:
        return {}

    alias_to_items: dict[str, list[str]] = {}
    for item_id, aliases in wanted.items():
        for alias in aliases:
            alias_to_items.setdefault(alias, []).append(item_id)

    data_dir = game_path / "Quasimorph_Data"
    asset_files = [data_dir / "resources.assets"] + sorted(
        data_dir.glob("sharedassets*.assets")
    )
    asset_files = [p for p in asset_files if p.exists()]
    if not asset_files:
        raise RuntimeError("No Unity .assets files were found in Quasimorph_Data.")

    cache = sprite_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    mapped: dict[str, str] = {}

    for asset_file in asset_files:
        env = UnityPy.load(str(asset_file))
        for obj in env.objects:
            if obj.type.name not in {"Texture2D", "Sprite"}:
                continue

            try:
                asset = obj.read()
                name = str(getattr(asset, "m_Name", ""))
            except Exception:
                continue

            matching_items = alias_to_items.get(name)
            if not matching_items:
                continue
            matching_items = [
                item_id for item_id in matching_items
                if _alias_object_is_allowed(
                    item_id,
                    name,
                    obj.type.name,
                    getattr(obj, "path_id", None),
                )
            ]
            if not matching_items:
                continue

            try:
                image = asset.image
            except Exception:
                continue

            for item_id in matching_items:
                if item_id in mapped:
                    continue
                target = cache / f"{item_id}.png"
                image.save(target)
                mapped[item_id] = str(target)

        if len(mapped) == len(wanted):
            break

    return mapped


def extract_component_sprites(
    game_path: Path,
    items: list[Item],
    progress=None,
) -> dict[str, str]:
    """
    Deterministic, read-only sprite extraction.

    Pass 1:
      enumerate names from Sprite and Texture2D objects and resolve item -> asset name.

    Pass 2:
      reopen each asset file and extract matching Texture2D objects immediately.

    Texture2D is intentionally preferred for writing PNGs. It avoids retaining
    Sprite objects after their Unity environment has moved on, and it avoids
    Sprite->Texture reference-resolution failures for streamed .resS textures.
    """
    try:
        import UnityPy
    except ImportError as exc:
        raise RuntimeError(
            "Sprite import requires UnityPy. Install the application dependencies first."
        ) from exc

    wanted = [x for x in items if x.internal_id]
    data_dir = game_path / "Quasimorph_Data"

    asset_files = [data_dir / "resources.assets"] + sorted(
        data_dir.glob("sharedassets*.assets")
    )
    asset_files = [p for p in asset_files if p.exists()]

    if not asset_files:
        raise RuntimeError("No Unity .assets files were found in Quasimorph_Data.")

    # ---- Pass 1: collect names only ---------------------------------------
    available_names: set[str] = set()
    source_by_name: dict[str, set[str]] = {}
    scanned_objects = 0

    for asset_file in asset_files:
        env = UnityPy.load(str(asset_file))
        for obj in env.objects:
            if obj.type.name not in {"Sprite", "Texture2D"}:
                continue
            try:
                asset = obj.read()
                name = str(getattr(asset, "m_Name", ""))
            except Exception:
                continue
            if not name:
                continue
            available_names.add(name)
            source_by_name.setdefault(name, set()).add(asset_file.name)
            scanned_objects += 1
            if progress and scanned_objects % 1000 == 0:
                progress(scanned_objects)

    resolved = _resolve_asset_names(wanted, available_names)

    # Reverse lookup: asset name -> item IDs.
    wanted_names: dict[str, list[str]] = {}
    for item_id, (asset_name, _score) in resolved.items():
        wanted_names.setdefault(asset_name, []).append(item_id)

    cache = sprite_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)

    mapped: dict[str, str] = {}
    failures: dict[str, str] = {}
    extracted_asset_names: set[str] = set()

    # ---- Pass 2: decode matching Texture2D immediately --------------------
    for asset_file in asset_files:
        env = UnityPy.load(str(asset_file))
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue

            try:
                texture = obj.read()
                name = str(getattr(texture, "m_Name", ""))
            except Exception as exc:
                continue

            if name not in wanted_names:
                continue
            matching_ids = [
                item_id for item_id in wanted_names[name]
                if _alias_object_is_allowed(
                    item_id,
                    name,
                    "Texture2D",
                    getattr(obj, "path_id", None),
                )
            ]
            if not matching_ids:
                continue

            try:
                image = texture.image
                # Unity textures are already correctly oriented by UnityPy's
                # Texture2D.image helper.
                for item_id in matching_ids:
                    target = cache / f"{item_id}.png"
                    image.save(target)
                    mapped[item_id] = str(target)
                extracted_asset_names.add(name)
            except Exception as exc:
                for item_id in matching_ids:
                    failures[item_id] = f"{type(exc).__name__}: {exc}"

    # If an exact/fuzzy name resolved only to Sprite and no same-named Texture2D
    # was found, do one small Sprite fallback pass.
    missing_after_texture = {
        item_id: asset_name
        for item_id, (asset_name, _score) in resolved.items()
        if item_id not in mapped
    }

    if missing_after_texture:
        names_needed = set(missing_after_texture.values())
        for asset_file in asset_files:
            env = UnityPy.load(str(asset_file))
            for obj in env.objects:
                if obj.type.name != "Sprite":
                    continue
                try:
                    sprite = obj.read()
                    name = str(getattr(sprite, "m_Name", ""))
                except Exception:
                    continue
                if name not in names_needed:
                    continue

                matching_ids = [
                    item_id
                    for item_id, asset_name in missing_after_texture.items()
                    if asset_name == name
                    and _alias_object_is_allowed(
                        item_id,
                        name,
                        "Sprite",
                        getattr(obj, "path_id", None),
                    )
                ]
                if not matching_ids:
                    continue
                try:
                    image = sprite.image
                    for item_id in matching_ids:
                        target = cache / f"{item_id}.png"
                        image.save(target)
                        mapped[item_id] = str(target)
                        failures.pop(item_id, None)
                except Exception as exc:
                    for item_id in matching_ids:
                        failures[item_id] = f"{type(exc).__name__}: {exc}"

    report = {
        "game_path": str(game_path),
        "asset_files": [str(p) for p in asset_files],
        "ritual_items": len(wanted),
        "unity_sprite_texture_objects_scanned": scanned_objects,
        "unique_asset_names": len(available_names),
        "resolved_asset_names": {
            item_id: {
                "asset_name": asset_name,
                "score": score,
                "source_files": sorted(source_by_name.get(asset_name, ())),
            }
            for item_id, (asset_name, score) in sorted(resolved.items())
        },
        "mapped": mapped,
        "unresolved_item_ids": sorted(
            x.internal_id for x in wanted if x.internal_id not in resolved
        ),
        "decode_failures": failures,
        "mapped_count": len(mapped),
        "unresolved_count": sum(
            1 for x in wanted if x.internal_id not in resolved
        ),
        "failure_count": len(failures),
    }

    sprite_report_path().write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return mapped
