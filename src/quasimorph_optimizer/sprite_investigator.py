from __future__ import annotations

import html
import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from .settings import user_data_dir


CONTROL_PAIRS = {
    "venus_weapon_parts": "aztKey_inv",
    "roasted_human_skin": "slanina_inv",
    "impaler": "impaler_inv",
}
TARGET_ITEM_ID = "moon_armor_plates"

ASSEMBLY_SYMBOL_HINTS = (
    "ItemContentDescriptor",
    "GetActualSprite",
    "SetItemContent",
    "get_Sprites",
    "GetSprites",
    "itemSprite",
    "GetSpriteByTag",
    "AddItemIcon",
    "TooltipItemIcon",
    "ItemPaletteIcon",
    "TradeItemIcon",
    "get_sprite",
)


def investigation_dir() -> Path:
    return user_data_dir() / "sprite_mapping_investigation"


def _walk_strings(value: Any, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, child in value.items():
            sub = f"{path}.{key}" if path else str(key)
            yield from _walk_strings(child, sub)
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _walk_strings(child, f"{path}[{idx}]")


def _walk_pptrs(value: Any, path: str = ""):
    if isinstance(value, dict):
        if "m_PathID" in value or "m_FileID" in value:
            try:
                yield {
                    "field": path,
                    "file_id": int(value.get("m_FileID", 0) or 0),
                    "path_id": int(value.get("m_PathID", 0) or 0),
                }
            except Exception:
                pass
        for key, child in value.items():
            sub = f"{path}.{key}" if path else str(key)
            yield from _walk_pptrs(child, sub)
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            yield from _walk_pptrs(child, f"{path}[{idx}]")


def _exact_text_hits(tree: Any, needle: str) -> list[dict]:
    n = needle.casefold()
    hits = []
    for field, value in _walk_strings(tree):
        if value.casefold().strip("*") == n.strip("*"):
            hits.append({"field": field, "value": value, "kind": "exact"})
        elif n in value.casefold():
            hits.append({"field": field, "value": value, "kind": "contains"})
    hits.sort(key=lambda x: (0 if x["kind"] == "exact" else 1, x["field"]))
    return hits


def _safe_tree(obj):
    try:
        return obj.read_typetree()
    except Exception:
        return {}


def _object_name(obj, tree=None) -> str:
    tree = tree or {}
    if isinstance(tree, dict):
        name = tree.get("m_Name")
        if isinstance(name, str) and name:
            return name
    try:
        data = obj.read()
        return str(getattr(data, "m_Name", "") or "")
    except Exception:
        return ""


def _mono_class_name(tree: dict, by_path: dict[int, object]) -> str:
    if not isinstance(tree, dict):
        return ""
    ptr = tree.get("m_Script")
    if not isinstance(ptr, dict):
        return ""
    try:
        if int(ptr.get("m_FileID", 0) or 0) != 0:
            return ""
        pid = int(ptr.get("m_PathID", 0) or 0)
    except Exception:
        return ""
    script_obj = by_path.get(pid)
    if script_obj is None:
        return ""
    st = _safe_tree(script_obj)
    cls = st.get("m_ClassName", "") if isinstance(st, dict) else ""
    ns = st.get("m_Namespace", "") if isinstance(st, dict) else ""
    asm = st.get("m_AssemblyName", "") if isinstance(st, dict) else ""
    if cls:
        return ".".join(x for x in (ns, cls) if x) + (f" [{asm}]" if asm else "")
    return ""


def _printable_ascii_strings(data: bytes, min_len: int = 4) -> list[tuple[int, str]]:
    pattern = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
    return [(m.start(), m.group().decode("ascii", errors="ignore")) for m in pattern.finditer(data)]


def _printable_utf16le_strings(data: bytes, min_len: int = 4) -> list[tuple[int, str]]:
    # printable ASCII encoded as UTF-16LE is sufficient for .NET symbol names.
    pattern = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % min_len)
    out = []
    for m in pattern.finditer(data):
        try:
            out.append((m.start(), m.group().decode("utf-16le")))
        except Exception:
            pass
    return out


def _assembly_symbol_report(game_path: Path) -> dict:
    dll = game_path / "Quasimorph_Data" / "Managed" / "Assembly-CSharp.dll"
    if not dll.exists():
        return {"path": str(dll), "exists": False, "symbols": {}}

    data = dll.read_bytes()
    strings = _printable_ascii_strings(data) + _printable_utf16le_strings(data)
    strings.sort(key=lambda x: x[0])

    symbols = {}
    for hint in ASSEMBLY_SYMBOL_HINTS:
        hits = []
        for idx, (offset, value) in enumerate(strings):
            if hint.casefold() in value.casefold():
                lo = max(0, idx - 5)
                hi = min(len(strings), idx + 6)
                hits.append({
                    "offset": offset,
                    "value": value,
                    "context": [x[1] for x in strings[lo:hi]],
                })
                if len(hits) >= 10:
                    break
        symbols[hint] = hits

    return {
        "path": str(dll),
        "exists": True,
        "size": len(data),
        "symbols": symbols,
    }


def _resolve_chain(
    start_pid: int,
    refs_by_source: dict[int, list[dict]],
    info_by_pid: dict[int, dict],
    *,
    max_depth: int = 3,
) -> list[dict]:
    """BFS through same-file PPtr references."""
    chains = []
    queue = deque([(start_pid, [], 0)])
    seen = {(start_pid, 0)}

    while queue:
        pid, path, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for ref in refs_by_source.get(pid, []):
            if ref.get("file_id") != 0 or not ref.get("path_id"):
                continue
            target_pid = ref["path_id"]
            info = info_by_pid.get(target_pid, {})
            step = {
                "field": ref.get("field", ""),
                "path_id": target_pid,
                "type": info.get("type", ""),
                "name": info.get("name", ""),
                "class": info.get("class", ""),
            }
            new_path = path + [step]
            if info.get("type") in {"Sprite", "Texture2D"}:
                chains.append({"depth": depth + 1, "steps": new_path})
            state = (target_pid, depth + 1)
            if state not in seen:
                seen.add(state)
                queue.append((target_pid, new_path, depth + 1))
    return chains


def investigate_item_sprite_mapping(game_path: Path) -> dict:
    """
    Discover how Quasimorph connects item records/descriptors to inventory art.

    Controls:
      venus_weapon_parts <-> aztKey_inv
      roasted_human_skin <-> slanina_inv
      impaler <-> impaler_inv

    Target:
      moon_armor_plates

    The investigator does not guess the target sprite name. It compares the
    serialized reference topology used by known-good controls and reports visual
    objects reachable from the target through the same object graph.
    """
    try:
        import UnityPy
    except ImportError as exc:
        raise RuntimeError("Sprite mapping investigation requires UnityPy.") from exc

    data_dir = game_path / "Quasimorph_Data"
    asset_files = [data_dir / "resources.assets"] + sorted(data_dir.glob("sharedassets*.assets"))
    asset_files = [p for p in asset_files if p.exists()]
    if not asset_files:
        raise RuntimeError("No Unity .assets files found in Quasimorph_Data.")

    report = {
        "game_path": str(game_path),
        "controls": CONTROL_PAIRS,
        "target_item_id": TARGET_ITEM_ID,
        "asset_files": [],
        "assembly": _assembly_symbol_report(game_path),
        "control_analysis": {},
        "target_analysis": {},
        "discovered_signatures": [],
        "target_ranked_visual_candidates": [],
    }

    global_signatures = defaultdict(int)
    target_candidates = defaultdict(lambda: {"score": 0, "evidence": []})

    for asset_file in asset_files:
        env = UnityPy.load(str(asset_file))
        by_path = {}
        trees = {}
        info = {}
        refs_by_source = defaultdict(list)
        reverse_refs = defaultdict(list)

        for obj in env.objects:
            try:
                pid = int(obj.path_id)
            except Exception:
                continue
            by_path[pid] = obj

        # Read metadata/typetrees once.
        for pid, obj in by_path.items():
            tree = _safe_tree(obj)
            trees[pid] = tree
            name = _object_name(obj, tree)
            cls = _mono_class_name(tree, by_path) if obj.type.name == "MonoBehaviour" else ""
            info[pid] = {
                "type": obj.type.name,
                "name": name,
                "class": cls,
            }
            for ref in _walk_pptrs(tree):
                refs_by_source[pid].append(ref)
                if ref.get("file_id") == 0 and ref.get("path_id"):
                    reverse_refs[ref["path_id"]].append({
                        "source_path_id": pid,
                        "field": ref.get("field", ""),
                    })

        visual_by_name = defaultdict(list)
        for pid, meta in info.items():
            if meta["type"] in {"Sprite", "Texture2D"} and meta["name"]:
                visual_by_name[meta["name"]].append(pid)

        file_summary = {
            "file": asset_file.name,
            "object_count": len(by_path),
            "known_visual_objects": {
                sprite: visual_by_name.get(sprite, [])
                for sprite in CONTROL_PAIRS.values()
            },
        }
        report["asset_files"].append(file_summary)

        # Analyze controls.
        for item_id, known_sprite in CONTROL_PAIRS.items():
            entry = report["control_analysis"].setdefault(item_id, {
                "known_sprite": known_sprite,
                "item_text_objects": [],
                "known_sprite_objects": [],
                "reverse_referrers_of_known_sprite": [],
                "item_to_visual_chains": [],
            })

            item_roots = []
            for pid, tree in trees.items():
                hits = _exact_text_hits(tree, item_id)
                if hits:
                    item_roots.append(pid)
                    entry["item_text_objects"].append({
                        "file": asset_file.name,
                        "path_id": pid,
                        **info[pid],
                        "hits": hits[:20],
                    })

            sprite_pids = visual_by_name.get(known_sprite, [])
            for spid in sprite_pids:
                entry["known_sprite_objects"].append({
                    "file": asset_file.name,
                    "path_id": spid,
                    **info[spid],
                })
                for rev in reverse_refs.get(spid, []):
                    src = rev["source_path_id"]
                    ref_record = {
                        "file": asset_file.name,
                        "source_path_id": src,
                        "field": rev["field"],
                        **info.get(src, {}),
                    }
                    entry["reverse_referrers_of_known_sprite"].append(ref_record)
                    signature = (
                        info.get(src, {}).get("type", ""),
                        info.get(src, {}).get("class", ""),
                        rev["field"],
                    )
                    global_signatures[signature] += 1

            for root in item_roots:
                chains = _resolve_chain(root, refs_by_source, info, max_depth=3)
                for chain in chains:
                    final = chain["steps"][-1]
                    rec = {
                        "file": asset_file.name,
                        "root_path_id": root,
                        "root_type": info[root]["type"],
                        "root_name": info[root]["name"],
                        "root_class": info[root]["class"],
                        **chain,
                        "matches_known_sprite": final.get("name") == known_sprite,
                    }
                    entry["item_to_visual_chains"].append(rec)
                    if rec["matches_known_sprite"]:
                        fields = tuple(step["field"] for step in chain["steps"])
                        signature = (
                            info[root]["type"],
                            info[root]["class"],
                            fields,
                        )
                        global_signatures[signature] += 5

        # Analyze target exact-text roots and their reachable visuals.
        target_entry = report["target_analysis"].setdefault(TARGET_ITEM_ID, {
            "item_text_objects": [],
            "item_to_visual_chains": [],
            "same_type_as_control_referrers": [],
        })
        target_roots = []
        for pid, tree in trees.items():
            hits = _exact_text_hits(tree, TARGET_ITEM_ID)
            if hits:
                target_roots.append(pid)
                target_entry["item_text_objects"].append({
                    "file": asset_file.name,
                    "path_id": pid,
                    **info[pid],
                    "hits": hits[:20],
                })

        for root in target_roots:
            chains = _resolve_chain(root, refs_by_source, info, max_depth=3)
            for chain in chains:
                rec = {
                    "file": asset_file.name,
                    "root_path_id": root,
                    "root_type": info[root]["type"],
                    "root_name": info[root]["name"],
                    "root_class": info[root]["class"],
                    **chain,
                }
                target_entry["item_to_visual_chains"].append(rec)

                final = chain["steps"][-1]
                vname = final.get("name", "")
                if vname:
                    score = 10
                    fields = tuple(step["field"] for step in chain["steps"])
                    target_sig = (info[root]["type"], info[root]["class"], fields)
                    if target_sig in global_signatures:
                        score += 100 * global_signatures[target_sig]
                    target_candidates[vname]["score"] += score
                    target_candidates[vname]["evidence"].append({
                        "file": asset_file.name,
                        "root_path_id": root,
                        "fields": fields,
                        "final_type": final.get("type", ""),
                    })

    # Summarize signatures learned from controls.
    signatures = []
    for signature, count in sorted(global_signatures.items(), key=lambda x: -x[1]):
        signatures.append({
            "signature": repr(signature),
            "support": count,
        })
    report["discovered_signatures"] = signatures[:100]

    ranked = []
    for name, data in target_candidates.items():
        ranked.append({
            "asset_name": name,
            "score": data["score"],
            "evidence": data["evidence"],
        })
    ranked.sort(key=lambda x: (-x["score"], x["asset_name"].casefold()))
    report["target_ranked_visual_candidates"] = ranked[:100]

    # Explicit interpretation: did all three controls actually reveal a common
    # serialized item->visual chain?
    direct_control_matches = {}
    for iid, entry in report["control_analysis"].items():
        direct_control_matches[iid] = sum(
            1 for x in entry["item_to_visual_chains"] if x.get("matches_known_sprite")
        )
    report["control_chain_match_counts"] = direct_control_matches
    report["controls_establish_serialized_mapping"] = all(
        direct_control_matches.get(iid, 0) > 0 for iid in CONTROL_PAIRS
    )

    out = investigation_dir()
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "sprite_mapping_investigation.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Human-readable HTML.
    assembly_hits = []
    for symbol, hits in report["assembly"].get("symbols", {}).items():
        if hits:
            assembly_hits.append(
                f"<li><code>{html.escape(symbol)}</code>: {len(hits)} occurrence(s)</li>"
            )

    control_rows = []
    for iid, entry in report["control_analysis"].items():
        control_rows.append(
            "<tr>"
            f"<td><code>{html.escape(iid)}</code></td>"
            f"<td><code>{html.escape(entry['known_sprite'])}</code></td>"
            f"<td>{len(entry['item_text_objects'])}</td>"
            f"<td>{len(entry['known_sprite_objects'])}</td>"
            f"<td>{sum(1 for x in entry['item_to_visual_chains'] if x.get('matches_known_sprite'))}</td>"
            "</tr>"
        )

    candidate_rows = []
    for c in ranked[:30]:
        candidate_rows.append(
            "<tr>"
            f"<td><code>{html.escape(c['asset_name'])}</code></td>"
            f"<td>{c['score']}</td>"
            f"<td>{len(c['evidence'])}</td>"
            "</tr>"
        )
    if not candidate_rows:
        candidate_rows.append("<tr><td colspan='3'>No visual candidate was reachable through serialized PPtr chains.</td></tr>")

    target = report["target_analysis"].get(TARGET_ITEM_ID, {})
    established = report["controls_establish_serialized_mapping"]
    conclusion = (
        "The known-good controls establish a serialized item→visual reference path. "
        "Candidates below are ranked using that same topology."
        if established
        else
        "The known-good controls do NOT establish a common serialized item→visual PPtr path. "
        "This indicates the association is probably created in managed code or another runtime content table. "
        "The Assembly-CSharp symbol section identifies the likely rendering API to inspect next."
    )

    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Quasimorph Sprite Mapping Investigator</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;max-width:1200px}}
code{{background:#eee;padding:2px 4px}}
table{{border-collapse:collapse;width:100%;margin:12px 0 24px}}
td,th{{border:1px solid #bbb;padding:6px;text-align:left}}
.ok{{padding:10px;background:#eef6ee;border-left:4px solid #538653}}
</style></head><body>
<h1>Quasimorph Sprite Mapping Investigator</h1>
<p class="ok">{html.escape(conclusion)}</p>

<h2>Known-good controls</h2>
<table><tr><th>Item ID</th><th>Known sprite</th><th>Item-text objects</th>
<th>Sprite objects</th><th>Confirmed item→sprite chains</th></tr>
{''.join(control_rows)}</table>

<h2>Target: <code>{TARGET_ITEM_ID}</code></h2>
<p>Serialized objects containing target ID: {len(target.get('item_text_objects', []))}</p>
<p>Visual chains reachable from target: {len(target.get('item_to_visual_chains', []))}</p>

<h3>Ranked visual candidates</h3>
<table><tr><th>Asset</th><th>Score</th><th>Evidence chains</th></tr>
{''.join(candidate_rows)}</table>

<h2>Assembly-CSharp rendering symbols</h2>
<p>The managed assembly contains the following relevant symbols:</p>
<ul>{''.join(assembly_hits) or '<li>No requested symbols found.</li>'}</ul>
<p>Full offsets and nearby string context are in <code>sprite_mapping_investigation.json</code>.</p>
</body></html>"""
    html_path = out / "index.html"
    html_path.write_text(page, encoding="utf-8")

    return {
        "json": str(json_path),
        "index_html": str(html_path),
        "controls_establish_serialized_mapping": established,
        "candidate_count": len(ranked),
        "top_candidate": ranked[0]["asset_name"] if ranked else "",
    }
