from __future__ import annotations

import argparse
import csv
import html
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quasimorph_optimizer.game_data import (  # noqa: E402
    detect_game_path,
    load_cached_game_database,
    parse_resources_assets,
)
from quasimorph_optimizer.models import Item  # noqa: E402
from quasimorph_optimizer.sprites import (  # noqa: E402
    EXACT_SPRITE_ALIASES,
    USER_CONFIRMED_SPRITE_ALIASES,
    _base,
)


IMAGE_SUFFIXES = {".png", ".tga", ".jpg", ".jpeg", ".webp", ".bmp"}
SPRITE_SUFFIXES = ("_inv", "_icon")

@dataclass(frozen=True)
class AssetFile:
    name: str
    path: Path
    base: str


@dataclass(frozen=True)
class Candidate:
    item_id: str
    display_name: str
    asset_name: str
    asset_path: Path
    evidence: str
    confidence: str


def _is_sprite_image(path: Path) -> bool:
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        return False
    stem = path.stem
    return stem.endswith(SPRITE_SUFFIXES)


def collect_asset_files(asset_root: Path) -> list[AssetFile]:
    assets = []
    for path in sorted(asset_root.rglob("*")):
        if path.is_file() and _is_sprite_image(path):
            assets.append(AssetFile(path.stem, path, _base(path.stem)))
    return assets


def _add_candidate(
    out: list[Candidate],
    seen: set[str],
    *,
    item: Item,
    asset: AssetFile,
    evidence: str,
    confidence: str,
) -> None:
    if asset.name in seen:
        return
    seen.add(asset.name)
    out.append(
        Candidate(
            item_id=item.internal_id,
            display_name=item.name,
            asset_name=asset.name,
            asset_path=asset.path,
            evidence=evidence,
            confidence=confidence,
        )
    )


def candidate_assets_for_item(
    item: Item,
    *,
    by_name: dict[str, list[AssetFile]],
    by_base: dict[str, list[AssetFile]],
) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()

    for alias in USER_CONFIRMED_SPRITE_ALIASES.get(item.internal_id, ()):
        for asset in by_name.get(alias, ()):
            _add_candidate(
                candidates,
                seen,
                item=item,
                asset=asset,
                evidence="user-confirmed asset name",
                confidence="confirmed",
            )

    for alias in EXACT_SPRITE_ALIASES.get(item.internal_id, ()):
        for asset in by_name.get(alias, ()):
            _add_candidate(
                candidates,
                seen,
                item=item,
                asset=asset,
                evidence="curated exact alias",
                confidence="curated",
            )

    exact_id_names = (f"{item.internal_id}_inv", f"{item.internal_id}_icon")
    for exact_name in exact_id_names:
        for asset in by_name.get(exact_name, ()):
            _add_candidate(
                candidates,
                seen,
                item=item,
                asset=asset,
                evidence="internal_id + suffix exact",
                confidence="high",
            )

    for asset in by_base.get(_base(item.internal_id), ()):
        _add_candidate(
            candidates,
            seen,
            item=item,
            asset=asset,
            evidence="normalized internal_id exact",
            confidence="high",
        )

    for asset in by_base.get(_base(item.name), ()):
        _add_candidate(
            candidates,
            seen,
            item=item,
            asset=asset,
            evidence="localized display name exact",
            confidence="high",
        )

    return candidates


def _index_assets(assets: list[AssetFile]) -> tuple[dict[str, list[AssetFile]], dict[str, list[AssetFile]]]:
    by_name: dict[str, list[AssetFile]] = {}
    by_base: dict[str, list[AssetFile]] = {}
    for asset in assets:
        by_name.setdefault(asset.name, []).append(asset)
        by_base.setdefault(asset.base, []).append(asset)
    return by_name, by_base


def _load_items(game_path: Path | None) -> tuple[list[Item], str]:
    if game_path is not None:
        game = detect_game_path(str(game_path))
        if not game:
            raise RuntimeError(f"Quasimorph game folder was not found: {game_path}")
        db = parse_resources_assets(game / "Quasimorph_Data" / "resources.assets")
        return list(db.items), str(game)

    db = load_cached_game_database()
    if db is None:
        raise RuntimeError("No cached game database found. Pass --game first.")
    return list(db.items), db.source


def _copy_thumb(candidate: Candidate, out_dir: Path, copied: dict[Path, str]) -> str:
    source = candidate.asset_path.resolve()
    if source in copied:
        return copied[source]
    target_dir = out_dir / "thumbs"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in candidate.asset_name)
    target = target_dir / f"{safe_name}{candidate.asset_path.suffix.lower()}"
    counter = 2
    while target.exists() and target.resolve() != source:
        target = target_dir / f"{safe_name}_{counter}{candidate.asset_path.suffix.lower()}"
        counter += 1
    shutil.copy2(source, target)
    rel = target.relative_to(out_dir).as_posix()
    copied[source] = rel
    return rel


def write_outputs(
    *,
    out_dir: Path,
    asset_root: Path,
    source: str,
    items: list[Item],
    rows: dict[str, list[Candidate]],
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "sprite_candidates.csv"
    json_path = out_dir / "sprite_candidates.json"
    html_path = out_dir / "index.html"

    flat_rows = []
    for item in items:
        candidates = rows.get(item.internal_id, [])
        if candidates:
            for rank, candidate in enumerate(candidates, 1):
                flat_rows.append({
                    "item_id": item.internal_id,
                    "display_name": item.name,
                    "rank": rank,
                    "asset_name": candidate.asset_name,
                    "confidence": candidate.confidence,
                    "evidence": candidate.evidence,
                    "asset_path": str(candidate.asset_path),
                })
        else:
            flat_rows.append({
                "item_id": item.internal_id,
                "display_name": item.name,
                "rank": "",
                "asset_name": "",
                "confidence": "unresolved",
                "evidence": "no exact asset-name candidate",
                "asset_path": "",
            })

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "item_id",
                "display_name",
                "rank",
                "asset_name",
                "confidence",
                "evidence",
                "asset_path",
            ],
        )
        writer.writeheader()
        writer.writerows(flat_rows)

    json_path.write_text(
        json.dumps(flat_rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    copied: dict[Path, str] = {}
    cards = []
    for item in items:
        candidates = rows.get(item.internal_id, [])
        status = candidates[0].confidence if candidates else "unresolved"
        chips = []
        for candidate in candidates[:6]:
            rel = _copy_thumb(candidate, out_dir, copied)
            chips.append(
                "<div class='candidate'>"
                f"<img src='{html.escape(rel)}' alt=''>"
                f"<code>{html.escape(candidate.asset_name)}</code>"
                f"<span>{html.escape(candidate.confidence)} · {html.escape(candidate.evidence)}</span>"
                "</div>"
            )
        if not chips:
            chips.append("<div class='missing'>No exact candidate</div>")
        cards.append(
            "<section class='card' data-status='{status}'>"
            "<header>"
            f"<strong>{html.escape(item.name)}</strong>"
            f"<code>{html.escape(item.internal_id)}</code>"
            f"<span class='status'>{html.escape(status)}</span>"
            "</header>"
            f"<div class='candidates'>{''.join(chips)}</div>"
            "</section>"
        )

    counts = {
        "confirmed": sum(1 for x in rows.values() if x and x[0].confidence == "confirmed"),
        "curated": sum(1 for x in rows.values() if x and x[0].confidence == "curated"),
        "high": sum(1 for x in rows.values() if x and x[0].confidence == "high"),
        "unresolved": sum(1 for item in items if not rows.get(item.internal_id)),
    }
    css = """
body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#f7f7f7;color:#1b1b1b}
.meta{margin:8px 0 18px;color:#555}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:12px}
.card{background:#fff;border:1px solid #ccc;border-radius:8px;padding:10px}
header{display:grid;grid-template-columns:1fr auto;gap:4px 8px;align-items:center}
header code{grid-column:1/2;color:#555}
.status{grid-column:2/3;grid-row:1/3;border-radius:999px;padding:3px 8px;background:#eee}
.candidate{display:grid;grid-template-columns:54px 1fr;gap:2px 8px;margin-top:8px;align-items:center}
.candidate img{width:48px;height:48px;object-fit:contain;image-rendering:pixelated;background:#222;border-radius:4px}
.candidate code{font-weight:600}
.candidate span{color:#666}
.missing{margin-top:8px;color:#777}
""".strip()
    html_path.write_text(
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Quasimorph AssetRipper Sprite Audit</title>
<style>{css}</style></head><body>
<h1>Quasimorph AssetRipper Sprite Audit</h1>
<div class="meta">Game data: {html.escape(source)}<br>
AssetRipper folder: {html.escape(str(asset_root))}<br>
Items: {len(items)} · confirmed {counts['confirmed']} · curated {counts['curated']} ·
high-confidence exact {counts['high']} · unresolved {counts['unresolved']}</div>
<div class="grid">{''.join(cards)}</div>
</body></html>""",
        encoding="utf-8",
    )

    return {
        "html": str(html_path),
        "csv": str(csv_path),
        "json": str(json_path),
    }


def audit(asset_root: Path, out_dir: Path, game_path: Path | None = None) -> dict[str, str]:
    items, source = _load_items(game_path)
    assets = collect_asset_files(asset_root)
    by_name, by_base = _index_assets(assets)
    rows = {
        item.internal_id: candidate_assets_for_item(
            item,
            by_name=by_name,
            by_base=by_base,
        )
        for item in items
        if item.internal_id
    }
    return write_outputs(
        out_dir=out_dir,
        asset_root=asset_root,
        source=source,
        items=items,
        rows=rows,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit Quasimorph ritual component sprites against an AssetRipper export."
    )
    parser.add_argument("--assets", required=True, type=Path, help="AssetRipper export folder")
    parser.add_argument("--game", type=Path, help="Quasimorph installation folder")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("assetripper_sprite_audit"),
        help="Output folder for HTML/CSV/JSON audit files",
    )
    args = parser.parse_args()
    result = audit(args.assets, args.out, args.game)
    print("AssetRipper sprite audit written:")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
