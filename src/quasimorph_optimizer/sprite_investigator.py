from __future__ import annotations

import html
import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from .settings import user_data_dir
from .sprites import EXACT_SPRITE_ALIASES, extract_exact_sprite_aliases


TARGET_ITEM_ID = "moon_armor_plates"
ITEM_FACTORY_PLACEHOLDERS = (
    "_iconOneSlotPlaceholder",
    "_iconTwoSlotPlaceholder",
    "_smallIconPlaceholder",
    "_shadowPlaceholder",
)

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
        displayed = value if len(value) <= 500 else value[:500] + "..."
        if value.casefold().strip("*") == n.strip("*"):
            hits.append({
                "field": field,
                "value": displayed,
                "value_length": len(value),
                "kind": "exact",
            })
        elif n in value.casefold():
            hits.append({
                "field": field,
                "value": displayed,
                "value_length": len(value),
                "kind": "contains",
            })
    hits.sort(key=lambda x: (0 if x["kind"] == "exact" else 1, x["field"]))
    return hits


def _safe_tree(obj):
    try:
        return obj.read_typetree()
    except Exception:
        return {}


def _mono_identity(obj) -> tuple[dict, str]:
    """Read MonoBehaviour's fixed header and dereference its MonoScript."""
    try:
        head = obj.parse_monobehaviour_head()
        script = head.m_Script.deref_parse_as_object()
        namespace = str(getattr(script, "m_Namespace", "") or "")
        class_name = str(getattr(script, "m_ClassName", "") or "")
        assembly = str(getattr(script, "m_AssemblyName", "") or "")
        fullname = ".".join(x for x in (namespace, class_name) if x)
        return {
            "name": str(getattr(head, "m_Name", "") or ""),
            "fullname": fullname,
            "assembly": assembly,
        }, ""
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"


def _find_typetree_node(root, name: str):
    for node in root.traverse():
        if node.m_Name == name:
            return node
    raise KeyError(name)


def _clone_typetree_node(node):
    from UnityPy.helpers.TypeTreeNode import TypeTreeNode

    return TypeTreeNode(
        m_Level=node.m_Level,
        m_Type=node.m_Type,
        m_Name=node.m_Name,
        m_ByteSize=node.m_ByteSize,
        m_Version=node.m_Version,
        m_Children=[_clone_typetree_node(child) for child in node.m_Children],
        m_TypeFlags=node.m_TypeFlags,
        m_VariableCount=node.m_VariableCount,
        m_Index=node.m_Index,
        m_MetaFlag=node.m_MetaFlag,
        m_RefTypeHash=node.m_RefTypeHash,
    )


def _promote_typetree_node(node, name: str, level: int = 1):
    node = _clone_typetree_node(node)
    delta = level - node.m_Level
    for child in node.traverse():
        child.m_Level += delta
    node.m_Name = name
    return node


def _manual_managed_node(obj, kind: str):
    """Build the two small game typetrees directly from Unity's own nodes."""
    from UnityPy.enums import ClassIDType
    from UnityPy.helpers.Tpk import get_typetree_node

    base = _clone_typetree_node(
        get_typetree_node(ClassIDType.MonoBehaviour, obj.version)
    )
    asset_bundle = get_typetree_node(ClassIDType.AssetBundle, obj.version)
    sprite_atlas = get_typetree_node(ClassIDType.SpriteAtlas, obj.version)

    if kind == "DescriptorsCollection":
        descriptors = _promote_typetree_node(
            _find_typetree_node(asset_bundle, "m_PreloadTable"),
            "_descriptors",
        )
        ids = _promote_typetree_node(
            _find_typetree_node(sprite_atlas, "m_PackedSpriteNamesToIndex"),
            "_ids",
        )
        base.m_Type = "DescriptorsCollection"
        base.m_Children.extend((descriptors, ids))
        return base

    if kind == "ItemContentDescriptor":
        render_id = _promote_typetree_node(
            _find_typetree_node(sprite_atlas, "m_Tag"),
            "_overridenRenderId",
        )
        packed_sprites = _find_typetree_node(sprite_atlas, "m_PackedSprites")
        sprite_ptr = next(
            node for node in packed_sprites.traverse()
            if node.m_Name == "data" and node.m_Type == "PPtr<Sprite>"
        )
        base.m_Type = "ItemContentDescriptor"
        base.m_Children.append(render_id)
        for field_name in ("_icon", "_smallIcon", "_shadow"):
            base.m_Children.append(
                _promote_typetree_node(sprite_ptr, field_name)
            )
        return base

    if kind == "ItemFactory":
        packed_sprites = _find_typetree_node(sprite_atlas, "m_PackedSprites")
        sprite_ptr = next(
            node for node in packed_sprites.traverse()
            if node.m_Name == "data" and node.m_Type == "PPtr<Sprite>"
        )
        base.m_Type = "ItemFactory"
        for field_name in ITEM_FACTORY_PLACEHOLDERS:
            base.m_Children.append(
                _promote_typetree_node(sprite_ptr, field_name)
            )
        return base

    raise ValueError(f"Unsupported manual managed typetree: {kind}")


def _safe_managed_tree(obj, manual_kind: str = "") -> tuple[dict, str, str]:
    """Force the DLL-generated node, with a deterministic schema fallback."""
    try:
        node = obj.generate_monobehaviour_node()
        tree = obj.read_typetree(nodes=node)
        return tree if isinstance(tree, dict) else {}, "", "generated"
    except Exception as generated_exc:
        generated_error = f"{type(generated_exc).__name__}: {generated_exc}"

    if manual_kind:
        try:
            node = _manual_managed_node(obj, manual_kind)
            tree = obj.read_typetree(nodes=node)
            return tree if isinstance(tree, dict) else {}, "", "manual"
        except Exception as manual_exc:
            return {}, (
                f"generated={generated_error}; manual="
                f"{type(manual_exc).__name__}: {manual_exc}"
            ), ""
    return {}, generated_error, ""


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


def _environment_unity_version(env) -> str:
    for asset in env.files.values():
        # Use the raw serialized-file string. UnityPy's UnityVersion.__str__
        # currently omits the patch/build component for modern versions (for
        # example 2022.3.62f1 can become 2022.3f1), which the native generator
        # correctly rejects as an invalid Unity version.
        version = str(getattr(asset, "unity_version", "") or "").strip()
        if version and version != "0.0.0":
            return version
    raise RuntimeError("Could not determine the Unity version from the game assets.")


def _create_typetree_generator(game_path: Path, env):
    """Build MonoBehaviour typetrees from the installed managed assemblies."""
    try:
        from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
    except (ImportError, ModuleNotFoundError) as exc:
        raise RuntimeError(
            "Managed descriptor decoding requires TypeTreeGeneratorAPI. "
            "Install/update the application dependencies and try again."
        ) from exc

    managed = game_path / "Quasimorph_Data" / "Managed"
    if not managed.exists():
        raise RuntimeError(f"Managed assembly directory was not found: {managed}")

    generator = TypeTreeGenerator(_environment_unity_version(env))
    generator.load_local_dll_folder(str(managed))
    return generator


def _pptr(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    if "m_PathID" not in value and "m_FileID" not in value:
        return None
    try:
        return {
            "file_id": int(value.get("m_FileID", 0) or 0),
            "path_id": int(value.get("m_PathID", 0) or 0),
        }
    except (TypeError, ValueError):
        return None


def _first_field(tree: Any, names: tuple[str, ...]):
    if not isinstance(tree, dict):
        return None
    for name in names:
        if name in tree:
            return tree[name]
    return None


def _safe_asset_image(obj, destination: Path) -> str:
    try:
        asset = obj.read()
        image = asset.image
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination)
        return ""
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def _textasset_text(obj, tree: Any = None) -> str:
    values = []
    if isinstance(tree, dict):
        values.append(tree.get("m_Script"))
    try:
        asset = obj.read()
        values.extend(
            getattr(asset, attr, None)
            for attr in ("m_Script", "script")
        )
    except Exception:
        pass

    for value in values:
        if isinstance(value, str):
            return value.replace("\r\n", "\n").replace("\r", "\n")
        if isinstance(value, bytes):
            return value.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        if isinstance(value, bytearray):
            return bytes(value).decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        if isinstance(value, list):
            try:
                return bytes(value).decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            except Exception:
                pass
    return ""


def _parse_config_items_records(config_text: str) -> dict[str, dict]:
    section = ""
    header: list[str] = []
    expect_header = False
    records: dict[str, dict] = {}

    for line_number, raw_line in enumerate(config_text.splitlines(), 1):
        line = raw_line.lstrip("\ufeff\x00")
        if not line.strip():
            continue
        if line.startswith("#"):
            section = line.split("\t", 1)[0].lstrip("#").strip()
            header = []
            expect_header = True
            continue

        cells = [cell.strip() for cell in line.split("\t")]
        if expect_header or (cells and cells[0] == "Id"):
            header = cells
            expect_header = False
            continue
        if not header or not cells or not cells[0]:
            continue

        row = {
            key: cells[idx]
            for idx, key in enumerate(header)
            if key and idx < len(cells)
        }
        row["_section"] = section
        row["_line_number"] = line_number
        row["_raw_line"] = line
        row["_raw_id"] = cells[0]
        records[cells[0].lstrip("*")] = row

    return records


def _collect_config_items_records(
    by_path: dict[int, object],
    trees: dict[int, Any],
    info: dict[int, dict],
) -> tuple[dict[str, dict], list[dict]]:
    records: dict[str, dict] = {}
    sources = []
    for pid, meta in info.items():
        if meta.get("type") != "TextAsset" or meta.get("name") != "config_items":
            continue
        text = _textasset_text(by_path[pid], trees.get(pid, {}))
        parsed = _parse_config_items_records(text)
        for item_id, row in parsed.items():
            records[item_id] = {
                "_source_path_id": pid,
                **row,
            }
        sources.append({
            "path_id": pid,
            "record_count": len(parsed),
        })
    return records, sources


def _inventory_width_size(record: dict | None) -> int | None:
    if not record:
        return None
    raw = record.get("InventoryWidthSize")
    if raw in (None, ""):
        # ItemRecord::.ctor initializes InventoryWidthSize to 1. Blank TSV
        # cells keep that constructor default.
        return 1
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _sprite_reference_entry(
    *,
    source_obj,
    ref: dict | None,
    by_path: dict[int, object],
    info: dict[int, dict],
    asset_file: Path,
    output_dir: Path,
    image_name: str,
    subdir: str,
) -> tuple[dict, str]:
    if not ref or not ref.get("path_id"):
        return {}, "Sprite reference is null or malformed."

    sprite_obj, sprite_error = _resolve_object_reference(source_obj, ref, by_path)
    sprite_pid = ref["path_id"]
    sprite_meta = info.get(sprite_pid, {})
    entry = {
        "file": _reader_file_name(sprite_obj, asset_file.name) if sprite_obj else "",
        "path_id": sprite_pid,
        "type": getattr(getattr(sprite_obj, "type", None), "name", "") or sprite_meta.get("type", ""),
        "asset_name": (
            _object_name(sprite_obj) or sprite_meta.get("name", "")
        ) if sprite_obj else sprite_meta.get("name", ""),
    }
    if sprite_obj is None:
        return entry, f"Sprite reference could not be resolved: {sprite_error}"

    target = output_dir / subdir / f"{image_name}.png"
    image_error = _safe_asset_image(sprite_obj, target)
    if image_error:
        entry["image_error"] = image_error
    else:
        entry["image"] = str(target)
    return entry, ""


def _resolve_object_reference(source_obj, ref: dict, by_path: dict[int, object]):
    """Resolve a serialized PPtr, including references to external asset files."""
    if ref["file_id"] == 0 and ref["path_id"] in by_path:
        return by_path[ref["path_id"]], ""
    try:
        from UnityPy.classes.PPtr import PPtr

        ptr = PPtr(
            m_FileID=ref["file_id"],
            m_PathID=ref["path_id"],
            assetsfile=source_obj.assets_file,
        )
        return ptr.deref(), ""
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _reader_file_name(obj, fallback: str) -> str:
    try:
        return Path(str(obj.assets_file.name)).name
    except Exception:
        return fallback


def _resolve_item_factory_placeholders(
    *,
    factory_pids: list[int],
    asset_file: Path,
    by_path: dict[int, object],
    trees: dict[int, Any],
    info: dict[int, dict],
    output_dir: Path,
) -> dict:
    result = {
        "objects": [],
        "placeholders": {},
        "errors": [],
    }
    for factory_pid in factory_pids:
        factory_obj = by_path[factory_pid]
        tree, error, decode_method = _safe_managed_tree(factory_obj, "ItemFactory")
        if tree:
            trees[factory_pid] = tree
        else:
            result["errors"].append({
                "path_id": factory_pid,
                "error": error,
            })
            continue

        result["objects"].append({
            "file": asset_file.name,
            "path_id": factory_pid,
            "name": info.get(factory_pid, {}).get("name", ""),
            "class": info.get(factory_pid, {}).get("class", ""),
            "decode_method": decode_method,
        })
        for field_name in ITEM_FACTORY_PLACEHOLDERS:
            ref = _pptr(tree.get(field_name))
            placeholder = {
                "factory_file": asset_file.name,
                "factory_path_id": factory_pid,
                "field": field_name,
                "reference": ref,
            }
            sprite, sprite_error = _sprite_reference_entry(
                source_obj=factory_obj,
                ref=ref,
                by_path=by_path,
                info=info,
                asset_file=asset_file,
                output_dir=output_dir,
                image_name=field_name.lstrip("_"),
                subdir="runtime_fallback_icons",
            )
            if sprite:
                placeholder["icon"] = sprite
                if sprite.get("image"):
                    placeholder["image"] = sprite["image"]
            if sprite_error:
                placeholder["error"] = sprite_error
            result["placeholders"].setdefault(field_name, placeholder)

    return result


def _choose_runtime_icon_placeholder(
    *,
    item_id: str,
    item_records: dict[str, dict],
    factory_fallbacks: dict,
) -> tuple[str, dict | None, int | None]:
    record = item_records.get(item_id.lstrip("*"), {})
    return _choose_runtime_icon_placeholder_for_record(
        record=record,
        factory_fallbacks=factory_fallbacks,
    )


def _choose_runtime_icon_placeholder_for_record(
    *,
    record: dict | None,
    factory_fallbacks: dict,
) -> tuple[str, dict | None, int | None]:
    width = _inventory_width_size(record)
    if width is None:
        return "", None, None
    field_name = "_iconOneSlotPlaceholder" if width <= 1 else "_iconTwoSlotPlaceholder"
    placeholder = factory_fallbacks.get("placeholders", {}).get(field_name)
    return field_name, placeholder, width


def _annotate_runtime_icon_fallbacks(report: dict) -> None:
    descriptor_scan = report.get("authoritative_descriptor_resolution", {})
    factory_fallbacks = descriptor_scan.get("item_factory_fallbacks", {})
    if not factory_fallbacks.get("placeholders"):
        return

    for item_id, entry in descriptor_scan.get("items", {}).items():
        if entry.get("icon") or entry.get("image"):
            continue
        descriptor_ref = entry.get("descriptor_icon_reference") or entry.get("icon_reference")
        if isinstance(descriptor_ref, dict) and descriptor_ref.get("path_id"):
            continue

        field_name, placeholder, width = _choose_runtime_icon_placeholder_for_record(
            record=entry.get("item_record"),
            factory_fallbacks=factory_fallbacks,
        )
        if not placeholder or not placeholder.get("icon"):
            continue

        entry["runtime_placeholder_source"] = "ItemFactory.ResolveIcon"
        entry["placeholder_decision"] = {
            "InventoryWidthSize": width,
            "field": field_name,
        }
        entry["runtime_placeholder_reference"] = placeholder.get("reference")
        entry["runtime_placeholder_icon"] = placeholder["icon"]
        entry["warning"] = (
            "ItemContentDescriptor._icon is null. ItemFactory.ResolveIcon "
            "would show this placeholder at runtime, but it is not a "
            "component-specific sprite and is not applied to the optimizer."
        )


def _apply_exact_alias_sprites(
    descriptor_scan: dict,
    exact_alias_paths: dict[str, str],
) -> dict[str, dict]:
    """Promote curated exact aliases without treating placeholders as icons."""
    exact_alias_items: dict[str, dict] = {}
    items = descriptor_scan.get("items", {})

    for item_id, image_path in sorted(exact_alias_paths.items()):
        entry = items.get(item_id)
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("image")
            and entry.get("icon_source") == "ItemContentDescriptor._icon"
        ):
            continue

        aliases = EXACT_SPRITE_ALIASES.get(item_id, ())
        asset_name = aliases[0] if aliases else ""
        icon = {
            "file": "",
            "path_id": "",
            "type": "Texture2D/Sprite",
            "asset_name": asset_name,
            "image": image_path,
        }
        if entry.get("error"):
            entry["descriptor_error"] = entry["error"]
        entry["icon"] = icon
        entry["icon_source"] = "EXACT_SPRITE_ALIASES"
        entry["exact_alias_candidates"] = list(aliases)
        entry["exact_alias_icon"] = icon
        entry["image"] = image_path
        entry["error"] = ""
        exact_alias_items[item_id] = {
            "source": "EXACT_SPRITE_ALIASES",
            "asset_name": asset_name,
            "aliases": list(aliases),
            "image": image_path,
        }

    descriptor_scan["exact_alias_mapping"] = exact_alias_items
    return exact_alias_items


def _resolve_descriptor_collection(
    *,
    asset_file: Path,
    by_path: dict[int, object],
    trees: dict[int, Any],
    info: dict[int, dict],
    output_dir: Path,
    item_records: dict[str, dict] | None = None,
) -> dict:
    """
    Reproduce ConfigLoader's authoritative item lookup:

      DescriptorsCollections/pactcomponents_descriptors
      _ids[index] -> _descriptors[index] -> ItemContentDescriptor._icon
    """
    result = {
        "resource_path": "DescriptorsCollections/pactcomponents_descriptors",
        "collections_found": [],
        "items": {},
        "item_factory_fallbacks": {
            "objects": [],
            "placeholders": {},
            "errors": [],
        },
        "scan": {
            "mono_behaviours": 0,
            "script_identities_attempted": 0,
            "script_identities_resolved": 0,
            "descriptor_class_objects": 0,
            "item_factory_objects": 0,
            "managed_trees_attempted": 0,
            "managed_trees_decoded": 0,
            "manual_trees_decoded": 0,
        },
        "descriptor_array_candidates": [],
        "identity_error_samples": [],
        "managed_decode_error_samples": [],
    }

    mono_pids = [
        pid for pid, meta in info.items()
        if meta.get("type") == "MonoBehaviour"
    ]
    result["scan"]["mono_behaviours"] = len(mono_pids)
    item_records = item_records or {}

    # Resolve each MonoScript from the fixed MonoBehaviour header. This avoids
    # decoding tens of thousands of unrelated managed objects and also works
    # when m_Script is an external-file PPtr.
    descriptor_pids = []
    item_factory_pids = []
    unresolved_pids = []
    for pid in mono_pids:
        meta = info[pid]
        class_name = meta.get("class", "").split(" [", 1)[0]
        if class_name == "MGSC.DescriptorsCollection":
            descriptor_pids.append(pid)
            continue
        if class_name == "MGSC.ItemFactory":
            item_factory_pids.append(pid)
            continue

        result["scan"]["script_identities_attempted"] += 1
        identity, identity_error = _mono_identity(by_path[pid])
        if identity:
            result["scan"]["script_identities_resolved"] += 1
            meta["name"] = identity["name"] or meta.get("name", "")
            meta["class"] = identity["fullname"] + (
                f" [{identity['assembly']}]" if identity["assembly"] else ""
            )
            if identity["fullname"] == "MGSC.DescriptorsCollection":
                descriptor_pids.append(pid)
            elif identity["fullname"] == "MGSC.ItemFactory":
                item_factory_pids.append(pid)
        else:
            unresolved_pids.append(pid)
            if len(result["identity_error_samples"]) < 25:
                result["identity_error_samples"].append({
                    "path_id": pid,
                    "error": identity_error,
                })

    result["scan"]["descriptor_class_objects"] = len(descriptor_pids)
    result["scan"]["item_factory_objects"] = len(item_factory_pids)
    result["item_factory_fallbacks"] = _resolve_item_factory_placeholders(
        factory_pids=item_factory_pids,
        asset_file=asset_file,
        by_path=by_path,
        trees=trees,
        info=info,
        output_dir=output_dir,
    )

    # Normally only DescriptorsCollection instances need a forced managed
    # decode. If their identity could not be resolved, inspect only those
    # unresolved objects as a bounded content-based fallback.
    for collection_pid in descriptor_pids + unresolved_pids:
        meta = info[collection_pid]

        result["scan"]["managed_trees_attempted"] += 1
        tree, managed_error, decode_method = _safe_managed_tree(
            by_path[collection_pid], "DescriptorsCollection"
        )
        if tree:
            result["scan"]["managed_trees_decoded"] += 1
            if decode_method == "manual":
                result["scan"]["manual_trees_decoded"] += 1
        elif len(result["managed_decode_error_samples"]) < 25:
            result["managed_decode_error_samples"].append({
                "path_id": collection_pid,
                "class": meta.get("class", ""),
                "error": managed_error,
            })
        trees[collection_pid] = tree
        ids = _first_field(tree, ("_ids", "ids", "Ids"))
        descriptors = _first_field(tree, ("_descriptors", "descriptors", "Descriptors"))
        if not isinstance(ids, list) or not isinstance(descriptors, list):
            continue

        contains_target = TARGET_ITEM_ID in ids
        is_pactcomponents = meta.get("name", "") == "pactcomponents_descriptors"
        collection = {
            "file": asset_file.name,
            "path_id": collection_pid,
            "name": meta.get("name", ""),
            "class": meta.get("class", ""),
            "id_count": len(ids),
            "descriptor_count": len(descriptors),
            "contains_target": contains_target,
            "is_pactcomponents": is_pactcomponents,
            "decode_method": decode_method,
        }
        result["descriptor_array_candidates"].append(collection.copy())

        # DescriptorsCollection is used by several config sections. The pact
        # component collection is identified by its Resource path/name. The
        # target-id fallback preserves older report/test compatibility.
        if not is_pactcomponents and not contains_target:
            continue
        result["collections_found"].append(collection)

        if len(ids) != len(descriptors):
            collection["warning"] = "_ids and _descriptors have different lengths."

        for index, item_id in enumerate(ids):
            if not isinstance(item_id, str) or index >= len(descriptors):
                continue

            descriptor_ref = _pptr(descriptors[index])
            entry = {
                "collection_file": asset_file.name,
                "collection_path_id": collection_pid,
                "index": index,
                "descriptor_reference": descriptor_ref,
            }
            item_record = item_records.get(item_id.lstrip("*"))
            if item_record:
                entry["item_record"] = {
                    "source_path_id": item_record.get("_source_path_id"),
                    "section": item_record.get("_section", ""),
                    "line_number": item_record.get("_line_number"),
                    "InventoryWidthSize": item_record.get("InventoryWidthSize", ""),
                    "ItemClass": item_record.get("ItemClass", ""),
                    "MaxStack": item_record.get("MaxStack", ""),
                    "raw_line": item_record.get("_raw_line", ""),
                }
            result["items"][item_id] = entry
            if not descriptor_ref or not descriptor_ref["path_id"]:
                entry["error"] = "Descriptor reference is null or malformed."
                continue
            descriptor_obj, descriptor_error = _resolve_object_reference(
                by_path[collection_pid], descriptor_ref, by_path
            )
            descriptor_pid = descriptor_ref["path_id"]
            descriptor_tree, descriptor_tree_error, descriptor_decode_method = (
                _safe_managed_tree(descriptor_obj, "ItemContentDescriptor")
                if descriptor_obj is not None
                else ({}, "", "")
            )
            if descriptor_obj is not None:
                trees[descriptor_pid] = descriptor_tree
            descriptor_meta = info.get(descriptor_pid, {})
            entry["descriptor"] = {
                "file": _reader_file_name(descriptor_obj, asset_file.name) if descriptor_obj else "",
                "path_id": descriptor_pid,
                "type": getattr(getattr(descriptor_obj, "type", None), "name", "") or descriptor_meta.get("type", ""),
                "name": (
                    _object_name(descriptor_obj, descriptor_tree)
                    or descriptor_meta.get("name", "")
                ) if descriptor_obj else descriptor_meta.get("name", ""),
                "class": descriptor_meta.get("class", ""),
                "decode_method": descriptor_decode_method,
            }
            if descriptor_obj is None:
                entry["error"] = f"Descriptor reference could not be resolved: {descriptor_error}"
                continue
            if not descriptor_tree:
                entry["error"] = f"Descriptor managed typetree could not be decoded: {descriptor_tree_error}"
                continue

            icon_value = _first_field(
                descriptor_tree,
                ("_icon", "icon", "Icon", "<Icon>k__BackingField"),
            )
            icon_ref = _pptr(icon_value)
            entry["descriptor_icon_reference"] = icon_ref
            entry["icon_reference"] = icon_ref
            if not icon_ref or not icon_ref["path_id"]:
                field_name, placeholder, width = _choose_runtime_icon_placeholder(
                    item_id=item_id,
                    item_records=item_records,
                    factory_fallbacks=result["item_factory_fallbacks"],
                )
                if placeholder and placeholder.get("icon"):
                    entry["runtime_placeholder_source"] = "ItemFactory.ResolveIcon"
                    entry["placeholder_decision"] = {
                        "InventoryWidthSize": width,
                        "field": field_name,
                    }
                    entry["runtime_placeholder_reference"] = placeholder.get("reference")
                    entry["runtime_placeholder_icon"] = placeholder["icon"]
                    entry["warning"] = (
                        "ItemContentDescriptor._icon is null. ItemFactory.ResolveIcon "
                        "would show this placeholder at runtime, but it is not a "
                        "component-specific sprite and is not applied to the optimizer."
                    )
                    entry["error"] = "ItemContentDescriptor._icon is null; no component-specific icon was decoded."
                    continue
                entry["error"] = "ItemContentDescriptor._icon is null or was not decoded."
                continue

            safe_id = re.sub(r'[^A-Za-z0-9_.-]+', "_", item_id)
            icon, icon_error = _sprite_reference_entry(
                source_obj=descriptor_obj,
                ref=icon_ref,
                by_path=by_path,
                info=info,
                asset_file=asset_file,
                output_dir=output_dir,
                image_name=safe_id,
                subdir="authoritative_icons",
            )
            entry["icon"] = icon
            entry["icon_source"] = "ItemContentDescriptor._icon"
            if icon.get("image"):
                entry["image"] = icon["image"]
            if icon_error:
                entry["error"] = icon_error
                continue

        # An exact item ID should occur in only one config descriptor
        # collection. Stop before decoding thousands of unrelated behaviours.
        break

    return result


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
    Export authoritative ritual-component inventory art.

    Runtime path reproduced here:

      DescriptorsCollections/pactcomponents_descriptors
      _ids[index] -> _descriptors[index] -> ItemContentDescriptor._icon

    If _icon is null, ItemFactory.ResolveIcon can still show the one-slot or
    two-slot placeholder at runtime according to ItemRecord.InventoryWidthSize.
    Those placeholders are diagnostic only here because they are generic
    unknown-item art, not component-specific sprites. Blank InventoryWidthSize
    cells keep ItemRecord's constructor default of 1.
    """
    try:
        import UnityPy
    except ImportError as exc:
        raise RuntimeError("Component sprite export requires UnityPy.") from exc

    data_dir = game_path / "Quasimorph_Data"
    asset_files = [data_dir / "resources.assets"] + sorted(data_dir.glob("sharedassets*.assets"))
    asset_files = [p for p in asset_files if p.exists()]
    if not asset_files:
        raise RuntimeError("No Unity .assets files found in Quasimorph_Data.")

    report = {
        "game_path": str(game_path),
        "asset_files": [],
        "authoritative_descriptor_resolution": {
            "resource_path": "DescriptorsCollections/pactcomponents_descriptors",
            "collections_found": [],
            "items": {},
            "config_item_sources": [],
            "item_factory_fallbacks": {
                "objects": [],
                "placeholders": {},
                "errors": [],
            },
            "files_scanned": [],
            "descriptor_array_candidates": [],
            "identity_error_samples": [],
            "managed_decode_error_samples": [],
        },
    }

    out = investigation_dir()
    out.mkdir(parents=True, exist_ok=True)
    typetree_generator = None

    for asset_file in asset_files:
        env = UnityPy.load(str(asset_file))
        by_path = {}
        trees = {}
        info = {}

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

        file_summary = {
            "file": asset_file.name,
            "object_count": len(by_path),
        }
        report["asset_files"].append(file_summary)

        if typetree_generator is None:
            typetree_generator = _create_typetree_generator(game_path, env)
        env.typetree_generator = typetree_generator
        item_records, config_item_sources = _collect_config_items_records(
            by_path, trees, info
        )
        report["authoritative_descriptor_resolution"]["config_item_sources"].extend(
            {"file": asset_file.name, **row}
            for row in config_item_sources
        )
        authoritative = _resolve_descriptor_collection(
            asset_file=asset_file,
            by_path=by_path,
            trees=trees,
            info=info,
            output_dir=out,
            item_records=item_records,
        )
        report["authoritative_descriptor_resolution"]["files_scanned"].append({
            "file": asset_file.name,
            **authoritative["scan"],
        })
        report_fallbacks = report["authoritative_descriptor_resolution"]["item_factory_fallbacks"]
        asset_fallbacks = authoritative.get("item_factory_fallbacks", {})
        report_fallbacks["objects"].extend(asset_fallbacks.get("objects", []))
        report_fallbacks["errors"].extend(
            {"file": asset_file.name, **row}
            for row in asset_fallbacks.get("errors", [])
        )
        for field_name, placeholder in asset_fallbacks.get("placeholders", {}).items():
            report_fallbacks["placeholders"].setdefault(field_name, placeholder)
        report["authoritative_descriptor_resolution"]["descriptor_array_candidates"].extend(
            authoritative["descriptor_array_candidates"]
        )
        report["authoritative_descriptor_resolution"]["identity_error_samples"].extend(
            {"file": asset_file.name, **row}
            for row in authoritative["identity_error_samples"]
        )
        report["authoritative_descriptor_resolution"]["managed_decode_error_samples"].extend(
            {"file": asset_file.name, **row}
            for row in authoritative["managed_decode_error_samples"]
        )
        report["authoritative_descriptor_resolution"]["collections_found"].extend(
            authoritative["collections_found"]
        )
        report["authoritative_descriptor_resolution"]["items"].update(
            authoritative["items"]
        )

    _annotate_runtime_icon_fallbacks(report)

    descriptor_scan = report["authoritative_descriptor_resolution"]
    items = descriptor_scan["items"]
    descriptor_resolved_items = {
        item_id: entry
        for item_id, entry in items.items()
        if (
            entry.get("image")
            and entry.get("icon_source") == "ItemContentDescriptor._icon"
        )
    }
    direct_count = sum(
        1 for entry in descriptor_resolved_items.values()
        if entry.get("icon_source") == "ItemContentDescriptor._icon"
    )
    fallback_count = sum(
        1 for entry in items.values()
        if entry.get("runtime_placeholder_icon")
    )
    descriptor_unresolved_items = {
        item_id: entry
        for item_id, entry in items.items()
        if not entry.get("image")
    }
    exact_alias_paths = extract_exact_sprite_aliases(
        game_path,
        set(descriptor_unresolved_items),
    )
    exact_alias_items = _apply_exact_alias_sprites(
        descriptor_scan,
        exact_alias_paths,
    )
    resolved_items = {
        item_id: entry
        for item_id, entry in items.items()
        if entry.get("image")
    }
    unresolved_items = {
        item_id: entry
        for item_id, entry in items.items()
        if not entry.get("image")
    }
    descriptor_scan["summary"] = {
        "component_count": len(items),
        "resolved_count": len(resolved_items),
        "unresolved_count": len(unresolved_items),
        "descriptor_icon_count": direct_count,
        "descriptor_unresolved_count": len(descriptor_unresolved_items),
        "exact_alias_count": len(exact_alias_items),
        "runtime_placeholder_diagnostic_count": fallback_count,
    }

    json_path = out / "sprite_mapping_investigation.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # Human-readable HTML.
    summary = descriptor_scan["summary"]
    attempted_trees = sum(
        row.get("managed_trees_attempted", 0)
        for row in descriptor_scan.get("files_scanned", [])
    )
    decoded_trees = sum(
        row.get("managed_trees_decoded", 0)
        for row in descriptor_scan.get("files_scanned", [])
    )
    descriptor_classes = sum(
        row.get("descriptor_class_objects", 0)
        for row in descriptor_scan.get("files_scanned", [])
    )
    item_factory_objects = sum(
        row.get("item_factory_objects", 0)
        for row in descriptor_scan.get("files_scanned", [])
    )
    manual_trees = sum(
        row.get("manual_trees_decoded", 0)
        for row in descriptor_scan.get("files_scanned", [])
    )
    conclusion = (
        f"Resolved {summary['resolved_count']} of {summary['component_count']} "
        "ritual component icon(s) from descriptor sprites or curated exact aliases. "
        f"{summary['runtime_placeholder_diagnostic_count']} item(s) expose only "
        "the generic runtime placeholder diagnostically; placeholders are not applied."
    )

    component_rows = []
    for item_id, entry in sorted(items.items(), key=lambda x: x[1].get("index", 10**9)):
        icon = entry.get("icon", {})
        source = entry.get("icon_source", "")
        placeholder = entry.get("runtime_placeholder_icon", {})
        decision = entry.get("placeholder_decision", {})
        sprite_name = icon.get("asset_name", "")
        if not sprite_name and placeholder:
            sprite_name = f"unmapped placeholder: {placeholder.get('asset_name', '')}"
        component_rows.append(
            "<tr>"
            f"<td>{html.escape(str(entry.get('index', '')))}</td>"
            f"<td><code>{html.escape(item_id)}</code></td>"
            f"<td><code>{html.escape(sprite_name)}</code></td>"
            f"<td>{html.escape(source)}</td>"
            f"<td>{html.escape(icon.get('file', ''))}</td>"
            f"<td>{html.escape(str(icon.get('path_id', '')))}</td>"
            f"<td>{html.escape(str(decision.get('InventoryWidthSize', '')))}</td>"
            "</tr>"
        )

    unresolved_rows = []
    for item_id, entry in sorted(unresolved_items.items(), key=lambda x: x[1].get("index", 10**9)):
        unresolved_rows.append(
            "<tr>"
            f"<td>{html.escape(str(entry.get('index', '')))}</td>"
            f"<td><code>{html.escape(item_id)}</code></td>"
            f"<td>{html.escape(entry.get('error', ''))}</td>"
            "</tr>"
        )
    if not unresolved_rows:
        unresolved_rows.append("<tr><td colspan='3'>None</td></tr>")

    page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Quasimorph Component Sprite Export</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;max-width:1200px}}
code{{background:#eee;padding:2px 4px}}
table{{border-collapse:collapse;width:100%;margin:12px 0 24px}}
td,th{{border:1px solid #bbb;padding:6px;text-align:left}}
.ok{{padding:10px;background:#eef6ee;border-left:4px solid #538653}}
</style></head><body>
<h1>Quasimorph Component Sprite Export</h1>
<p class="ok">{html.escape(conclusion)}</p>

<h2>Summary</h2>
<p>Resolved icons: {summary['resolved_count']} / {summary['component_count']}</p>
<p>Descriptor icons: {summary['descriptor_icon_count']}</p>
<p>Exact aliases applied: {summary['exact_alias_count']}</p>
<p>Runtime placeholders left unmapped: {summary['runtime_placeholder_diagnostic_count']}</p>
<p>Managed descriptor scan: {attempted_trees} attempted, {decoded_trees} decoded,
{manual_trees} by deterministic fallback,
{descriptor_classes} <code>MGSC.DescriptorsCollection</code> object(s),
{item_factory_objects} <code>MGSC.ItemFactory</code> object(s),
{len(descriptor_scan.get('descriptor_array_candidates', []))} parallel-array collection(s) inspected.</p>

<h2>Component Icons</h2>
<table><tr><th>#</th><th>Item ID</th><th>Sprite</th><th>Source</th>
<th>Asset</th><th>Path ID</th><th>Width</th></tr>
{''.join(component_rows)}</table>

<h2>Unresolved</h2>
<table><tr><th>#</th><th>Item ID</th><th>Reason</th></tr>
{''.join(unresolved_rows)}</table>
</body></html>"""
    html_path = out / "index.html"
    html_path.write_text(page, encoding="utf-8")

    authoritative_mapping = {
        item_id: entry["image"]
        for item_id, entry in report["authoritative_descriptor_resolution"]["items"].items()
        if (
            entry.get("image")
            and entry.get("icon_source") == "ItemContentDescriptor._icon"
        )
    }
    manual_alias_mapping = {
        item_id: entry["image"]
        for item_id, entry in exact_alias_items.items()
        if entry.get("image")
    }
    authoritative_target = descriptor_scan["items"].get(TARGET_ITEM_ID, {})
    target_icon = authoritative_target.get("icon", {})
    return {
        "json": str(json_path),
        "index_html": str(html_path),
        "resolved_count": len(authoritative_mapping) + len(manual_alias_mapping),
        "component_count": len(items),
        "runtime_placeholder_count": fallback_count,
        "top_candidate": target_icon.get("asset_name", ""),
        "authoritative_target": authoritative_target,
        "authoritative_mapping": authoritative_mapping,
        "manual_alias_mapping": manual_alias_mapping,
    }
