from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Item
from .settings import user_data_dir

# Explicit internal-ID -> Unity inventory-art aliases verified against the
# user's resources.assets manifest.  These are deliberately separate from the
# player-facing display names because Quasimorph uses years of legacy names,
# puns, misspellings, and renamed content internally.
EXACT_SPRITE_ALIASES: dict[str, tuple[str, ...]] = {
    "spider_joint": ("spiderJoint_icon",),
    "spider_brain": ("spiderBrain_icon",),
    "spider_chitin": ("spiderChitin_icon",),
    "spider_eye": ("spiderAye_icon",),
    "human_ear": ("humanEar_icon",),
    "human_eye": ("human_aye_icon",),
    "human_poop": ("poopIcon",),
    "human_skull": ("humanSkull_icon",),
    "human_rib": ("humanRig_icon",),
    "demonic_eye": ("demonicAye_inv",),

    "quasi_medical_kit_1": ("gavaah_injector_inv",),
    "quasi_repair_kit": ("demonicShards_inv",),
    "human_meat": ("meat1_inv",),
    "roasted_human_meat": ("roastedMeat1_inv",),
    "roasted_human_skin": ("slanina_inv",),
    "syringe_bloodbag": ("bloodBag_inv",),
    "soup_can_1": ("spider_soup_inv",),
    "rotten_soup_can_1": ("rotten_soup_inv",),

    "venus_guts": ("aztec_guts_inv",),
    "quasi_venus_rags": ("aztec_rags_inv",),
    "quasi_venus_feather": ("venus_feather_inv",),
    "venus_armor_plates": ("venus_shard_inv",),
    "venus_melee_parts": ("venus_melee_inv",),
    # venus_weapon_parts / Mechanism Parts intentionally left unresolved:
    # mechanism_1 was confirmed by the user to be the wrong artwork.
    "quasi_darts_ammo": ("darts_inv",),
    "quasi_basic_ammo": ("uasi_ammo_inv",),

    "mercury_scales": ("mercury_scale_inv",),

    # Corrected by direct in-game comparison.
    "moon_weapon_parts": ("moon_shards_inv",),

    "quasi_bolts_ammo": ("quasiBolts_inv",),
    "quasi_ron_medicine_1": ("ron_med_inv",),
    "mars_gas_ammo": ("mars_gas_inv",),
    "impaler": ("impaler_inv",),
    "venus_weapon_parts": ("aztKey_inv",),
}


def sprite_cache_dir() -> Path:
    return user_data_dir() / "sprites"


def sprite_report_path() -> Path:
    return user_data_dir() / "sprite_extraction_report.json"


def candidate_sheet_dir() -> Path:
    return user_data_dir() / "sprite_candidates"


def _candidate_nearness(item: Item, asset_name: str) -> int:
    """
    Broader ranking used only for manual candidate sheets.
    Unlike extraction matching, this may return weak candidates because the
    user is visually reviewing the sheet rather than trusting an automatic map.
    """
    iid = _base(item.internal_id)
    display = _base(item.name)
    cand = _base(asset_name)
    if not cand:
        return 0

    score = _candidate_score(item, asset_name)

    iid_tokens = set(t for t in iid.split("_") if len(t) > 1)
    display_tokens = set(t for t in display.split("_") if len(t) > 1)
    cand_tokens = set(t for t in cand.split("_") if len(t) > 1)

    score += 25 * len(iid_tokens & cand_tokens)
    score += 20 * len(display_tokens & cand_tokens)

    # Inventory-looking assets are much more useful than maps/effects/etc.
    n = _norm(asset_name)
    if n.endswith("_inv"):
        score += 50
    elif n.endswith("_icon"):
        score += 35

    # Quasimorph content families.
    family_tokens = {
        "moon_armor_plates": {"moon", "lunar", "armor", "plate", "shard", "quasi"},
        "venus_weapon_parts": {"venus", "aztec", "weapon", "mechanism", "part", "quasi"},
    }
    for token in family_tokens.get(item.internal_id, set()):
        if token in cand_tokens:
            score += 18

    return score


def export_unresolved_candidate_sheets(
    game_path: Path,
    items: list[Item],
    *,
    unresolved_ids: tuple[str, ...] = ("moon_armor_plates", "venus_weapon_parts"),
    top_n: int = 36,
) -> dict[str, str]:
    """
    Export visually reviewable contact sheets for unresolved ritual sprites.

    This never writes to Quasimorph. It extracts candidate inventory textures
    into AppData and builds one PNG contact sheet per unresolved item.
    """
    try:
        import UnityPy
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError(
            "Candidate sheets require UnityPy and Pillow."
        ) from exc

    wanted = {x.internal_id: x for x in items if x.internal_id in unresolved_ids}
    if not wanted:
        return {}

    data_dir = game_path / "Quasimorph_Data"
    asset_files = [data_dir / "resources.assets"] + sorted(data_dir.glob("sharedassets*.assets"))
    asset_files = [p for p in asset_files if p.exists()]

    # First enumerate Texture2D names only.
    name_sources: dict[str, list[str]] = {}
    for asset_file in asset_files:
        env = UnityPy.load(str(asset_file))
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue
            try:
                tex = obj.read()
                name = str(getattr(tex, "m_Name", ""))
            except Exception:
                continue
            if not name:
                continue
            name_sources.setdefault(name, []).append(asset_file.name)

    ranked: dict[str, list[tuple[int, str]]] = {}
    for item_id, item in wanted.items():
        rows = []
        for name in name_sources:
            score = _candidate_nearness(item, name)
            if score > 0:
                rows.append((score, name))
        rows.sort(key=lambda x: (-x[0], x[1].casefold()))
        ranked[item_id] = rows[:top_n]

    needed_names = {name for rows in ranked.values() for _, name in rows}
    decoded: dict[str, Image.Image] = {}

    # Decode only the shortlisted textures.
    for asset_file in asset_files:
        env = UnityPy.load(str(asset_file))
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue
            try:
                tex = obj.read()
                name = str(getattr(tex, "m_Name", ""))
            except Exception:
                continue
            if name not in needed_names or name in decoded:
                continue
            try:
                decoded[name] = tex.image.convert("RGBA")
            except Exception:
                continue

    out_dir = candidate_sheet_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {}

    # 6 columns x 6 rows, each tile 180x150.
    cols = 6
    tile_w, tile_h = 180, 150
    thumb_w, thumb_h = 96, 92

    for item_id, rows in ranked.items():
        rows = [row for row in rows if row[1] in decoded]
        if not rows:
            continue

        count = len(rows)
        sheet_rows = (count + cols - 1) // cols
        sheet = Image.new("RGBA", (cols * tile_w, sheet_rows * tile_h), "white")
        draw = ImageDraw.Draw(sheet)

        for idx, (score, name) in enumerate(rows):
            x0 = (idx % cols) * tile_w
            y0 = (idx // cols) * tile_h

            img = decoded[name].copy()
            img.thumbnail((thumb_w, thumb_h), Image.Resampling.NEAREST)
            ix = x0 + (tile_w - img.width) // 2
            iy = y0 + 6 + (thumb_h - img.height) // 2
            sheet.alpha_composite(img, (ix, iy))

            # labels
            label_y = y0 + 104
            display_name = name if len(name) <= 24 else name[:21] + "..."
            draw.text((x0 + 6, label_y), display_name, fill="black")
            draw.text((x0 + 6, label_y + 18), f"score {score}", fill="black")

            # tile boundary
            draw.rectangle([x0, y0, x0 + tile_w - 1, y0 + tile_h - 1], outline="gray")

        target = out_dir / f"{item_id}_candidates.png"
        sheet.convert("RGB").save(target)
        outputs[item_id] = str(target)

        # Also write ranked manifest for exact asset-name reporting.
        manifest = {
            "item_id": item_id,
            "display_name": wanted[item_id].name,
            "candidates": [
                {"score": score, "asset_name": name, "source_files": name_sources.get(name, [])}
                for score, name in rows
            ],
        }
        (out_dir / f"{item_id}_candidates.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return outputs


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


def _candidate_score(item: Item, asset_name: str) -> int:
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
    """Resolve each item ID to one asset name without holding Unity objects."""
    names = sorted(available_names)
    result: dict[str, tuple[str, int]] = {}

    for item in items:
        if not item.internal_id:
            continue

        best_name = ""
        best_score = 0

        # Exact aliases first; this avoids thousands of fuzzy comparisons.
        for alias in EXACT_SPRITE_ALIASES.get(item.internal_id, ()):
            if alias in available_names:
                best_name = alias
                best_score = 10000
                break

        if not best_name:
            for name in names:
                score = _candidate_score(item, name)
                if score > best_score:
                    best_name = name
                    best_score = score

        if best_score >= 150:
            result[item.internal_id] = (best_name, best_score)

    return result



def inv_atlas_dir() -> Path:
    return user_data_dir() / "inv_sprite_atlas"



def quasiplumbum_trace_dir() -> Path:
    return user_data_dir() / "quasiplumbum_trace"


def _walk_pptrs(value, path=""):
    out = []
    if isinstance(value, dict):
        if "m_PathID" in value or "m_FileID" in value:
            try:
                out.append({
                    "field": path,
                    "file_id": int(value.get("m_FileID", 0) or 0),
                    "path_id": int(value.get("m_PathID", 0) or 0),
                })
            except Exception:
                pass
        for key, child in value.items():
            sub = f"{path}.{key}" if path else str(key)
            out.extend(_walk_pptrs(child, sub))
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            out.extend(_walk_pptrs(child, f"{path}[{idx}]"))
    return out


def _tree_contains_text(tree, needle: str) -> bool:
    target = needle.casefold()

    def walk(v):
        if isinstance(v, str):
            return target in v.casefold()
        if isinstance(v, dict):
            return any(walk(k) or walk(val) for k, val in v.items())
        if isinstance(v, list):
            return any(walk(x) for x in v)
        return False

    return walk(tree)


def trace_quasiplumbum_references(game_path: Path) -> dict:
    """
    Trace serialized Unity object references for moon_armor_plates (Quasiplumbum).

    This does not use sprite-name guessing. It:
      1. scans serialized objects for the exact internal ID text;
      2. records PPtr fields on matching objects;
      3. resolves local references in the same serialized file;
      4. follows one additional PPtr hop;
      5. exports any resolved Sprite/Texture2D images for visual inspection.

    Game files are opened read-only.
    """
    try:
        import UnityPy
    except ImportError as exc:
        raise RuntimeError("Quasiplumbum tracing requires UnityPy.") from exc

    needle = "moon_armor_plates"
    data_dir = game_path / "Quasimorph_Data"
    asset_files = [data_dir / "resources.assets"] + sorted(
        data_dir.glob("sharedassets*.assets")
    )
    asset_files = [p for p in asset_files if p.exists()]
    if not asset_files:
        raise RuntimeError("No Unity asset files found.")

    out_dir = quasiplumbum_trace_dir()
    image_dir = out_dir / "resolved_images"
    image_dir.mkdir(parents=True, exist_ok=True)

    matches = []
    all_resolved_visuals = []

    for asset_file in asset_files:
        env = UnityPy.load(str(asset_file))

        # Local path-id index for this serialized environment.
        by_path_id = {}
        for obj in env.objects:
            try:
                by_path_id[int(obj.path_id)] = obj
            except Exception:
                continue

        for obj in env.objects:
            tree = {}
            try:
                tree = obj.read_typetree()
            except Exception:
                continue

            if not _tree_contains_text(tree, needle):
                continue

            record = {
                "source_file": asset_file.name,
                "path_id": int(obj.path_id),
                "type": obj.type.name,
                "name": str(tree.get("m_Name", "") or ""),
                "pptrs": _walk_pptrs(tree),
                "resolved_first_hop": [],
            }

            for ref in record["pptrs"]:
                pid = ref.get("path_id", 0)
                fid = ref.get("file_id", 0)

                # First version intentionally resolves only same-file refs.
                if not pid or fid not in (0,):
                    record["resolved_first_hop"].append({
                        **ref,
                        "resolved": False,
                        "reason": "external-file-reference-or-null",
                    })
                    continue

                target_obj = by_path_id.get(pid)
                if target_obj is None:
                    record["resolved_first_hop"].append({
                        **ref,
                        "resolved": False,
                        "reason": "path-id-not-found",
                    })
                    continue

                target_tree = {}
                try:
                    target_tree = target_obj.read_typetree()
                except Exception:
                    pass

                target_name = ""
                try:
                    target_name = str(target_tree.get("m_Name", "") or "")
                except Exception:
                    pass
                if not target_name:
                    try:
                        target_name = str(getattr(target_obj.read(), "m_Name", "") or "")
                    except Exception:
                        target_name = ""

                resolved = {
                    **ref,
                    "resolved": True,
                    "target_path_id": int(target_obj.path_id),
                    "target_type": target_obj.type.name,
                    "target_name": target_name,
                    "second_hop_pptrs": _walk_pptrs(target_tree) if target_tree else [],
                }

                # Export immediately if target is visual.
                if target_obj.type.name in {"Sprite", "Texture2D"}:
                    try:
                        asset = target_obj.read()
                        image = asset.image
                        safe = re.sub(r'[<>:"/\\\\|?*]+', "_", target_name or f"path_{pid}")
                        target = image_dir / f"{target_obj.type.name}_{safe}_{pid}.png"
                        image.save(target)
                        resolved["image"] = str(target)
                        all_resolved_visuals.append(str(target))
                    except Exception as exc:
                        resolved["image_error"] = f"{type(exc).__name__}: {exc}"

                # Resolve one more local hop.
                second_resolved = []
                for ref2 in resolved["second_hop_pptrs"]:
                    pid2 = ref2.get("path_id", 0)
                    fid2 = ref2.get("file_id", 0)
                    if not pid2 or fid2 not in (0,):
                        continue
                    obj2 = by_path_id.get(pid2)
                    if obj2 is None:
                        continue

                    name2 = ""
                    tree2 = {}
                    try:
                        tree2 = obj2.read_typetree()
                        name2 = str(tree2.get("m_Name", "") or "")
                    except Exception:
                        pass
                    if not name2:
                        try:
                            name2 = str(getattr(obj2.read(), "m_Name", "") or "")
                        except Exception:
                            pass

                    rr = {
                        "field": ref2.get("field", ""),
                        "path_id": pid2,
                        "type": obj2.type.name,
                        "name": name2,
                    }

                    if obj2.type.name in {"Sprite", "Texture2D"}:
                        try:
                            asset2 = obj2.read()
                            image2 = asset2.image
                            safe2 = re.sub(r'[<>:"/\\\\|?*]+', "_", name2 or f"path_{pid2}")
                            target2 = image_dir / f"{obj2.type.name}_{safe2}_{pid2}.png"
                            image2.save(target2)
                            rr["image"] = str(target2)
                            all_resolved_visuals.append(str(target2))
                        except Exception as exc:
                            rr["image_error"] = f"{type(exc).__name__}: {exc}"

                    second_resolved.append(rr)

                resolved["resolved_second_hop"] = second_resolved
                record["resolved_first_hop"].append(resolved)

            matches.append(record)

    report = {
        "target_internal_id": needle,
        "game_path": str(game_path),
        "asset_files_scanned": [str(p) for p in asset_files],
        "matching_serialized_objects": matches,
        "resolved_visual_files": sorted(set(all_resolved_visuals)),
        "match_count": len(matches),
        "resolved_visual_count": len(set(all_resolved_visuals)),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "quasiplumbum_reference_trace.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Simple readable HTML summary.
    rows = []
    for m in matches:
        rows.append(
            f"<h2>{m['source_file']} · {m['type']} · PathID {m['path_id']}</h2>"
        )
        rows.append("<ul>")
        for r in m["resolved_first_hop"]:
            if not r.get("resolved"):
                rows.append(
                    f"<li>{r.get('field','')} → unresolved "
                    f"(file {r.get('file_id')}, path {r.get('path_id')})</li>"
                )
                continue

            rows.append(
                f"<li><b>{r.get('field','')}</b> → "
                f"{r.get('target_type')} "
                f"{r.get('target_name') or '(unnamed)'} "
                f"(PathID {r.get('target_path_id')})"
            )
            if r.get("image"):
                rel = Path(r["image"]).relative_to(out_dir).as_posix()
                rows.append(f'<br><img src="{rel}" style="max-width:160px;max-height:160px;image-rendering:pixelated">')
            if r.get("resolved_second_hop"):
                rows.append("<ul>")
                for r2 in r["resolved_second_hop"]:
                    rows.append(
                        f"<li>{r2.get('field','')} → {r2.get('type')} "
                        f"{r2.get('name') or '(unnamed)'} "
                        f"(PathID {r2.get('path_id')})"
                    )
                    if r2.get("image"):
                        rel2 = Path(r2["image"]).relative_to(out_dir).as_posix()
                        rows.append(f'<br><img src="{rel2}" style="max-width:160px;max-height:160px;image-rendering:pixelated">')
                    rows.append("</li>")
                rows.append("</ul>")
            rows.append("</li>")
        rows.append("</ul>")

    html_doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Quasiplumbum Reference Trace</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; }}
code {{ background:#eee; padding:2px 4px; }}
img {{ border:1px solid #999; margin:6px; background:#222; }}
</style>
</head>
<body>
<h1>Quasiplumbum / moon_armor_plates reference trace</h1>
<p>Matches: {len(matches)} · resolved visual objects: {len(set(all_resolved_visuals))}</p>
{''.join(rows)}
</body>
</html>"""
    html_path = out_dir / "index.html"
    html_path.write_text(html_doc, encoding="utf-8")

    report["report_json"] = str(report_path)
    report["index_html"] = str(html_path)
    return report


def export_all_inv_sprite_atlas(game_path: Path, progress=None) -> dict:
    """
    Export every Texture2D whose Unity asset name ends in `_inv`.

    This is intentionally exhaustive and makes no semantic assumptions about
    English display names, internal IDs, Russian/Slavic legacy names, puns,
    abbreviations, typos, or renamed content.

    Output:
      %APPDATA%/QuasimorphRitualOptimizer/inv_sprite_atlas/
        images/<asset_name>.png
        index.html
        manifest.json

    The HTML gallery is searchable with Ctrl+F by exact Unity asset name.
    """
    try:
        import UnityPy
    except ImportError as exc:
        raise RuntimeError("Full _inv atlas export requires UnityPy.") from exc

    data_dir = game_path / "Quasimorph_Data"
    asset_files = [data_dir / "resources.assets"] + sorted(
        data_dir.glob("sharedassets*.assets")
    )
    asset_files = [p for p in asset_files if p.exists()]
    if not asset_files:
        raise RuntimeError("No Unity .assets files found in Quasimorph_Data.")

    out = inv_atlas_dir()
    images_dir = out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    seen_names = set()
    scanned = 0
    extracted = 0
    failures = []

    for asset_file in asset_files:
        env = UnityPy.load(str(asset_file))
        for obj in env.objects:
            if obj.type.name != "Texture2D":
                continue
            scanned += 1
            if progress and scanned % 500 == 0:
                progress(scanned)

            try:
                tex = obj.read()
                name = str(getattr(tex, "m_Name", ""))
            except Exception as exc:
                continue

            if not name or not name.casefold().endswith("_inv"):
                continue

            # Preserve duplicate asset names in the manifest but only write one
            # PNG per exact name, preferring the first successfully decoded one.
            entry = {
                "name": name,
                "source_file": asset_file.name,
                "path_id": getattr(obj, "path_id", None),
                "width": int(getattr(tex, "m_Width", 0) or 0),
                "height": int(getattr(tex, "m_Height", 0) or 0),
            }

            safe = re.sub(r'[<>:"/\\\\|?*]+', "_", name)
            target = images_dir / f"{safe}.png"
            entry["png"] = f"images/{target.name}"

            if name not in seen_names:
                try:
                    tex.image.save(target)
                    seen_names.add(name)
                    extracted += 1
                    entry["decoded"] = True
                except Exception as exc:
                    entry["decoded"] = False
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                    failures.append(entry.copy())
            else:
                entry["decoded"] = target.exists()

            entries.append(entry)

    # One logical gallery card per unique decoded name.
    unique = {}
    for entry in entries:
        name = entry["name"]
        if name not in unique or (entry.get("decoded") and not unique[name].get("decoded")):
            unique[name] = entry
    cards = [unique[name] for name in sorted(unique, key=str.casefold)]

    manifest = {
        "game_path": str(game_path),
        "asset_files": [str(p) for p in asset_files],
        "texture2d_objects_scanned": scanned,
        "inv_objects_found": len(entries),
        "unique_inv_names": len(cards),
        "unique_inv_pngs_extracted": sum(1 for x in cards if x.get("decoded")),
        "decode_failures": failures,
        "entries": cards,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    css = """
    body { font-family: Segoe UI, Arial, sans-serif; margin: 18px; background:#181818; color:#eee; }
    h1 { margin-bottom: 4px; }
    .meta { color:#bbb; margin-bottom:16px; }
    #q { width:420px; max-width:90vw; padding:8px; font-size:16px; margin-bottom:16px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr)); gap:10px; }
    .card { background:#282828; border:1px solid #444; border-radius:6px; padding:8px; min-height:150px; }
    .imagebox { height:96px; display:flex; align-items:center; justify-content:center; background:#111; border-radius:4px; overflow:hidden; }
    .imagebox img { max-width:92px; max-height:92px; image-rendering:pixelated; object-fit:contain; }
    .name { margin-top:7px; font-family:Consolas,monospace; font-size:12px; overflow-wrap:anywhere; }
    .details { color:#aaa; font-size:11px; margin-top:3px; }
    """
    js = """
    function filterCards() {
      const q = document.getElementById('q').value.toLowerCase();
      document.querySelectorAll('.card').forEach(c => {
        c.style.display = c.dataset.name.includes(q) ? '' : 'none';
      });
    }
    """

    html_cards = []
    for x in cards:
        name = x["name"]
        img = x["png"] if x.get("decoded") else ""
        img_html = f'<img src="{html.escape(img)}" alt="">' if img else "<span>decode failed</span>"
        html_cards.append(
            f'<div class="card" data-name="{html.escape(name.casefold())}">'
            f'<div class="imagebox">{img_html}</div>'
            f'<div class="name">{html.escape(name)}</div>'
            f'<div class="details">{html.escape(x["source_file"])} · '
            f'{x.get("width",0)}×{x.get("height",0)} · PathID {x.get("path_id","")}</div>'
            '</div>'
        )

    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Quasimorph _inv Sprite Atlas</title>
<style>{css}</style></head>
<body>
<h1>Quasimorph `_inv` Sprite Atlas</h1>
<div class="meta">{len(cards)} unique `_inv` Texture2D names. No semantic matching applied.</div>
<input id="q" type="search" placeholder="Filter exact Unity asset names..." oninput="filterCards()" autofocus>
<div class="grid">{''.join(html_cards)}</div>
<script>{js}</script>
</body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")

    return {
        "directory": str(out),
        "index_html": str(out / "index.html"),
        "manifest": str(out / "manifest.json"),
        "unique_inv_names": len(cards),
        "pngs_extracted": sum(1 for x in cards if x.get("decoded")),
    }


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

            try:
                image = texture.image
                # Unity textures are already correctly oriented by UnityPy's
                # Texture2D.image helper.
                for item_id in wanted_names[name]:
                    target = cache / f"{item_id}.png"
                    image.save(target)
                    mapped[item_id] = str(target)
                extracted_asset_names.add(name)
            except Exception as exc:
                for item_id in wanted_names[name]:
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
                ]
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
