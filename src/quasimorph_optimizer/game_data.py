from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import AFFINITIES, JACKPOT_UPGRADE_CAP, TIER_RULES, TierRules
from .models import Item
from .settings import user_data_dir

SECTION_NAMES = ("pactcomponents", "pacttiers", "essences", "essenceaffinity")


@dataclass(frozen=True, slots=True)
class GameRules:
    tier_rules: dict[int, TierRules]
    affinities: dict[str, dict[str, tuple[float, float]]]
    jackpot_cap: float


@dataclass(frozen=True, slots=True)
class GameDatabase:
    items: tuple[Item, ...]
    rules: GameRules
    source: str


def _extract_section(data: bytes, name: str) -> str:
    marker = ("#" + name).encode("utf-8")
    start = data.find(marker)
    if start < 0:
        raise ValueError(f"Section #{name} was not found in resources.assets")
    end = data.find(b"#end", start + len(marker))
    if end < 0:
        raise ValueError(f"Section #{name} has no #end marker")
    return (
        data[start:end + 4]
        .decode("utf-8", errors="ignore")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )


def _parse_table(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.strip("\x00\t ")]
    if lines and lines[0].lstrip("\x00").startswith("#"):
        lines = lines[1:]
    if lines and lines[-1].lstrip("\x00").startswith("#end"):
        lines = lines[:-1]
    if not lines:
        return []

    header = lines[0].strip("\x00").split("\t")
    useful = [(i, name.strip()) for i, name in enumerate(header) if name.strip()]
    records: list[dict[str, str]] = []

    for line in lines[1:]:
        line = line.strip("\x00")
        if not line or line.lstrip().startswith("//"):
            continue
        cells = line.split("\t")
        record = {
            name: (cells[i].strip() if i < len(cells) else "")
            for i, name in useful
        }
        if any(record.values()):
            records.append(record)
    return records


# Verified names are now only a fallback. The installed game's localization
# TextAsset has priority over this entire dictionary.
VERIFIED_NAME_FALLBACKS = {
    "precious_metals": "Load of Gold Bars",
    "quasi_medical_kit_1": "Gavvakh",
    "quasi_repair_kit": "Shard",
    "ron_blood": "Shavva",
    "quasi_energy_ammo": "Elerium",
    "quasi_basic_ammo": "Igvas",
    "quasi_darts_ammo": "Angerlings",
    "quasi_bolts_ammo": "Nails of Pain",
    "quasi_ron_medicine_1": "Soma",
    "venus_weapon_parts": "Mechanism Parts",
    "venus_armor_plates": "Quasibronze",
    "moon_weapon_parts": "Lunar Bone",
    "moon_armor_plates": "Quasiplumbum",
    "impaler": "Ossuary",
    "mars_gear": "Horde Cog",
    "jupiter_grass": "Nightreed",
    "mars_skin": "Hellcrab Chitin",
    "cattaram_geode": "Meta-Gem",
    "jupiter_guts": "Jupiterian Innards",
    "mars_gas_ammo": "Eannis Redfire",
    "cattaram_mine": "Rebis",
    "ron_mask_1": "Aeschylith",
    "cattaram_stone": "Meta-Matter",
    "human_poop": "Feces",
    "human_rib": "Rib",
    "human_skull": "Skull",
    "human_ear": "Ear",
    "human_eye": "Eye",
    "throwable_heart": "Heart",
    "human_meat": "Piece of Flesh",
    "rotten_human_meat": "Rotten Meat",
    "roasted_human_meat": "Fried Meat",
    "roasted_human_skin": "Smoked Lard",
    "human_skin": "Skin",
    "rotten_human_skin": "Rotten Skin",
    "syringe_bloodbag": "Sang-B",
    "soup_can_1": "Spider Soup",
    "rotten_soup_can_1": "Overdue Soup",
    "spider_chitin": "Chitin",
    "rotten_spider_meat": "Rotten Spider Flesh",
    "roasted_spider_meat": "Fried Spider",
    "spider_meat": "Spider Flesh",
    "dog_teeth": "Dog Teeth",
    "venus_guts": "Venusian Innards",
    "mercury_guts": "Mercurian Innards",
    "mercury_scales": "Scales",
    "quasi_venus_rags": "Gannix Rags",
    "quasi_venus_feather": "Blue Feather",
    "venus_melee_parts": "Acatl Parts",
    "human_organ_1": "Furuncle",
    "quasi_grenade": "Eye of Wrath",
}


def _fallback_name(item_id: str) -> str:
    if item_id in VERIFIED_NAME_FALLBACKS:
        return VERIFIED_NAME_FALLBACKS[item_id]
    return " ".join(
        part.capitalize()
        for part in item_id.strip("*").split("_")
        if part
    )


def game_text_data_dir() -> Path:
    return user_data_dir() / "game_text_data"


def localization_diagnostic_path() -> Path:
    return game_text_data_dir() / "localization_resolution.json"


def _textasset_bytes(obj) -> bytes:
    asset = obj.read()
    for attr in ("m_Script", "script"):
        value = getattr(asset, attr, None)
        if value is None:
            continue
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
        if isinstance(value, str):
            return value.encode("utf-8")
    tree = obj.read_typetree()
    value = tree.get("m_Script", b"") if isinstance(tree, dict) else b""
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, list):
        try:
            return bytes(value)
        except Exception:
            return b""
    return bytes(value or b"")


def extract_game_textassets(resources_path: Path) -> dict[str, str]:
    """
    Read the installed game's authoritative TextAssets.

    Extracts raw text to AppData for inspection and returns decoded strings.
    Game files remain read-only.
    """
    try:
        import UnityPy
    except ImportError:
        return {}

    env = UnityPy.load(str(resources_path))
    wanted = {"localization", "config_items"}
    found: dict[str, str] = {}
    out_dir = game_text_data_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        try:
            asset = obj.read()
            name = str(getattr(asset, "m_Name", "") or "")
        except Exception:
            continue

        if name not in wanted:
            continue

        try:
            raw = _textasset_bytes(obj)
        except Exception:
            continue

        text = raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        found[name] = text
        (out_dir / f"{name}.txt").write_text(text, encoding="utf-8")

    return found


def _flatten_json_strings(value: Any, path: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            sub = f"{path}.{key}" if path else str(key)
            if isinstance(child, str):
                out.append((sub, child))
            else:
                out.extend(_flatten_json_strings(child, sub))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            out.extend(_flatten_json_strings(child, f"{path}[{i}]"))
    return out


LOCALIZATION_LANGUAGE_COLUMNS = {
    "English": 1,
    "Russian": 2,
    "German": 3,
    "French": 4,
    "Spanish": 5,
    "Polish": 6,
    "Turkish": 7,
    "BrazilianPortugal": 8,
    "Korean": 9,
    "Japanese": 10,
    "ChineseSimp": 11,
}


def parse_localization_tsv(localization_text: str) -> tuple[list[str], dict[str, list[str]]]:
    """
    Parse Quasimorph's localization TextAsset exactly as tab-separated text.

    Layout:
        key<TAB>English<TAB>Russian<TAB>German...

    No delimiter guessing or fuzzy matching is used.
    """
    header: list[str] = []
    table: dict[str, list[str]] = {}

    for raw_line in localization_text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        line = raw_line.lstrip("\ufeff\x00")
        if not line.strip():
            continue

        cells = [cell.strip() for cell in line.split("\t")]

        if not header and cells and cells[0] == "":
            header = cells
            continue

        key = cells[0] if cells else ""
        if not key:
            continue
        table[key] = cells

    return header, table


def resolve_localized_names(
    localization_text: str,
    item_ids: list[str],
    *,
    language: str = "English",
) -> tuple[dict[str, str], dict[str, Any]]:
    """
    Resolve ritual-component names from exact keys:

        item.<internal_id>.name

    The installed localization file is authoritative.
    """
    header, table = parse_localization_tsv(localization_text)

    language_index = None
    if header:
        for idx, value in enumerate(header):
            if value == language:
                language_index = idx
                break
    if language_index is None:
        language_index = LOCALIZATION_LANGUAGE_COLUMNS.get(language, 1)

    resolved: dict[str, str] = {}
    missing: list[str] = []
    diagnostics: dict[str, Any] = {
        "format": "tsv-exact",
        "language": language,
        "language_column": language_index,
        "header": header,
        "resolved_count": 0,
        "missing_count": 0,
        "missing_item_ids": [],
        "items": {},
    }

    for item_id in item_ids:
        clean_id = item_id.lstrip("*")
        key = f"item.{clean_id}.name"
        row = table.get(key)

        value = ""
        if row is not None and language_index < len(row):
            value = row[language_index].strip()

        if value:
            resolved[item_id] = value
            diagnostics["items"][item_id] = {
                "key": key,
                "value": value,
                "resolved": True,
            }
        else:
            missing.append(item_id)
            diagnostics["items"][item_id] = {
                "key": key,
                "value": "",
                "resolved": False,
            }

    diagnostics["resolved_count"] = len(resolved)
    diagnostics["missing_count"] = len(missing)
    diagnostics["missing_item_ids"] = missing
    return resolved, diagnostics



def extract_config_item_matches(config_text: str, item_ids: list[str]) -> dict[str, Any]:
    """
    Preserve raw config_items evidence for every ritual component.

    The schema may evolve, so this diagnostic intentionally records matching
    lines/rows instead of inventing fields that are not present.
    """
    lines = config_text.splitlines()
    result: dict[str, Any] = {}
    for item_id in item_ids:
        matches = []
        iid = item_id.casefold()
        for idx, line in enumerate(lines):
            if iid in line.casefold():
                lo = max(0, idx - 1)
                hi = min(len(lines), idx + 2)
                matches.append({
                    "line_number": idx + 1,
                    "line": line,
                    "context": lines[lo:hi],
                })
        result[item_id] = matches[:50]
    return result


def _write_text_data_diagnostics(
    localized: dict[str, str],
    localization_diag: dict[str, Any],
    config_matches: dict[str, Any],
) -> None:
    out_dir = game_text_data_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "resolved_names": localized,
        "localization": localization_diag,
        "config_items_matches": config_matches,
    }
    localization_diagnostic_path().write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def parse_resources_assets(path: Path) -> GameDatabase:
    data = path.read_bytes()
    components = _parse_table(_extract_section(data, "pactcomponents"))
    tiers = _parse_table(_extract_section(data, "pacttiers"))
    affinities_rows = _parse_table(_extract_section(data, "essenceaffinity"))

    # Extract authoritative text resources before constructing items.
    textassets = extract_game_textassets(path)

    component_ids = []
    for row in components:
        item_id = row.get("Id", "").strip()
        if item_id:
            component_ids.append(item_id)

    localized_names: dict[str, str] = {}
    localization_diag: dict[str, Any] = {"format": "missing", "items": {}}
    if textassets.get("localization"):
        localized_names, localization_diag = resolve_localized_names(
            textassets["localization"],
            component_ids,
        )

    config_matches = {}
    if textassets.get("config_items"):
        config_matches = extract_config_item_matches(
            textassets["config_items"],
            component_ids,
        )

    _write_text_data_diagnostics(
        localized_names,
        localization_diag,
        config_matches,
    )

    items = []
    for row in components:
        try:
            item_id = row["Id"]
            essence = row["Essence"].lower()
            power = float(row["EssencePower"])
            stability = float(row["EssenceStability"])
        except (KeyError, ValueError):
            continue

        max_stack = 1
        price = 0.0
        try:
            if row.get("MaxStack"):
                max_stack = max(1, int(float(row["MaxStack"])))
        except ValueError:
            pass
        try:
            if row.get("Price"):
                price = max(0.0, float(row["Price"]))
        except ValueError:
            pass

        # Localization is authoritative. Manual verified names and humanization
        # are only fallbacks when the installed build cannot be resolved.
        display_name = localized_names.get(item_id) or _fallback_name(item_id)

        items.append(
            Item(
                name=display_name,
                essence=essence,
                power=power,
                stability=stability,
                enabled=True,
                internal_id=item_id,
                quantity=1,
                max_stack=max_stack,
                price=price,
            )
        )

    tier_rules: dict[int, TierRules] = {}
    for row in tiers:
        try:
            tier_rules[int(row["Tier"])] = TierRules(
                float(row["EssencePower"]),
                float(row["EssenceStability"]),
                float(row["SidegradeCoef"]),
            )
        except (KeyError, ValueError):
            pass
    if not tier_rules:
        tier_rules = dict(TIER_RULES)

    affinity: dict[str, dict[str, tuple[float, float]]] = {}
    for row in affinities_rows:
        try:
            source = row["SourceEssenceId"].lower()
            target = row["TargetEssenceId"].lower()
            affinity.setdefault(source, {})[target] = (
                float(row["PowerMult"]),
                float(row["StabilityMult"]),
            )
        except (KeyError, ValueError):
            pass
    if not affinity:
        affinity = {k: dict(v) for k, v in AFFINITIES.items()}

    cap = JACKPOT_UPGRADE_CAP
    match = re.search(rb"SkullRitualUpgradeChanceCap\t([0-9.]+)", data)
    if match:
        try:
            cap = float(match.group(1))
        except ValueError:
            pass

    return GameDatabase(
        tuple(items),
        GameRules(tier_rules, affinity, cap),
        str(path),
    )


def game_database_cache_path() -> Path:
    return user_data_dir() / "game_database.json"


def save_game_database(db: GameDatabase, path: Path | None = None) -> None:
    path = path or game_database_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": db.source,
        "items": [
            {
                "name": i.name,
                "id": i.internal_id,
                "essence": i.essence,
                "power": i.power,
                "stability": i.stability,
                "price": i.price,
                "max_stack": i.max_stack,
            }
            for i in db.items
        ],
        "tiers": {
            str(k): {
                "power": v.power_target,
                "stability": v.stability_target,
                "sidegrade": v.sidegrade_coef,
            }
            for k, v in db.rules.tier_rules.items()
        },
        "affinities": {
            s: {t: [p, st] for t, (p, st) in row.items()}
            for s, row in db.rules.affinities.items()
        },
        "jackpot_cap": db.rules.jackpot_cap,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_cached_game_database(path: Path | None = None) -> GameDatabase | None:
    path = path or game_database_cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = tuple(
            Item(
                name=x["name"],
                internal_id=x.get("id", ""),
                essence=x["essence"],
                power=float(x["power"]),
                stability=float(x["stability"]),
                enabled=True,
                quantity=1,
                max_stack=int(x.get("max_stack", 1)),
                price=float(x.get("price", 0)),
            )
            for x in data["items"]
        )
        tiers = {
            int(k): TierRules(
                float(v["power"]),
                float(v["stability"]),
                float(v["sidegrade"]),
            )
            for k, v in data["tiers"].items()
        }
        affinities = {
            s: {
                t: (float(v[0]), float(v[1]))
                for t, v in row.items()
            }
            for s, row in data["affinities"].items()
        }
        rules = GameRules(
            tiers,
            affinities,
            float(data.get("jackpot_cap", JACKPOT_UPGRADE_CAP)),
        )
        return GameDatabase(
            items,
            rules,
            data.get("source", str(path)),
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ):
        return None


def detect_game_path(preferred: str = "") -> Path | None:
    candidates = []
    if preferred:
        candidates.append(Path(preferred))
    for drive in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        candidates.extend(
            [
                Path(f"{drive}:/SteamLibrary/steamapps/common/Quasimorph"),
                Path(f"{drive}:/Steam/steamapps/common/Quasimorph"),
                Path(
                    f"{drive}:/Program Files (x86)/Steam/steamapps/common/Quasimorph"
                ),
            ]
        )
    for p in candidates:
        if (p / "Quasimorph_Data" / "resources.assets").is_file():
            return p
    return None
