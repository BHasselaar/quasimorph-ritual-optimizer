# Quasimorph Ritual Optimizer

A Windows desktop application that exhaustively searches five-component pact rituals in **Quasimorph** using the verified community affinity/probability model.

## v0.4.0

- Bundled inventory updated to the current 38-component list from the repository, preserving its order and availability state.
- Ship Power/Stability bonuses now default to **0 / 0** and are persisted immediately in the user's settings file whenever a valid value is changed.
- Inventory rows now have checkbox-style availability controls. Available rows are green; unavailable rows are red.
- Inventory rows can be rearranged by drag-and-drop; the new order is saved to the user's inventory CSV.
- Inventory, results, and ritual-detail views now have both horizontal and vertical scrollbars.
- Brute-force optimization now uses multiple **processes** rather than Python threads, allowing CPU-bound searches to use multiple cores. `Workers = 0` automatically uses all logical CPUs reported by Python.
- Added **Load bundled** so the v0.4 inventory can be adopted explicitly without automatic migration logic.
- Multiprocessing uses Windows-compatible `spawn` semantics and deterministic tie-breaking.

## Run from source

Requires Python 3.11 or newer.

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
quasimorph-ritual-optimizer
```

Or run `run_app.bat`.

## Windows executable

```powershell
build_windows.bat
```

The executable is written to `dist/QuasimorphRitualOptimizer.exe`. GitHub Actions also builds the executable for version tags.

## Local data

The app stores user files at:

```text
%APPDATA%\QuasimorphRitualOptimizer\
```

- `inventory.csv` — item order, values, and availability.
- `settings.json` — ship Power/Stability bonuses and worker count.

The bundled inventory is copied on a fresh install. Existing local inventories are not automatically migrated or overwritten. Use **Load bundled** if you want to replace your local inventory with the version shipped in the app.

CSV format:

```csv
enabled,name,essence,power,stability
true,Load of Gold Bars,eon,110,25
true,Spider Joint,agga,80,25
```

## Calculation model

For each component:

```text
Power contribution = base Power × predecessor→component Power multiplier × component→center Power multiplier
Stability contribution = base Stability × predecessor→component Stability multiplier × component→center Stability multiplier
```

After summing the five components:

```text
Total Power = component Power total + ship Power bonus
Total Stability = component Stability total + ship Stability bonus
```

Then:

```text
Power% = min(1, Total Power / tier Power target)
Stability% = min(1, Total Stability / tier Stability target)
```

Outcome formulas:

```text
Upgrade    = Power% × Stability%
Sidegrade  = Power% × (1 − Stability%) × (1 / SidegradeCoef)
Downgrade  = (1 − Power%) × Stability%
Disenchant = (1 − Stability%) × (Power% × (1 − 1/SidegradeCoef) + (1 − Power%))
```

At Tier 1, Downgrade is transferred to Disenchant. Raw Upgrade above 70% becomes Jackpot:

```text
Jackpot = max(0, raw Upgrade − 70%)
Upgrade = min(raw Upgrade, 70%)
```

The five outer items form a directed circular ring. Rotations are equivalent; mirror-image orders are not.

## Search size and parallelism

The optimizer evaluates:

```text
C(number of available items, 5) × 4!
```

The v0.4 bundled list contains 38 components, 37 of which are initially available, producing **10,461,528** unique ring orders if left unchanged. Availability checkboxes are therefore useful both for modeling your actual inventory and reducing computation.

The optimizer uses `ProcessPoolExecutor` because this search is CPU-bound and Python threads would remain constrained by the GIL. On a 12-thread CPU, leave **Workers** at `0` to use the detected 12 logical CPUs, or set the number manually.

## Future graphical ritual view

The current data model keeps item identity and clockwise order separate from the UI, so component artwork and a graphical five-slot ritual representation can be added later without changing the optimizer mathematics.

## Development

```powershell
python -m pip install -e . -r requirements-dev.txt
pytest
```

## Disclaimer

This is an unofficial community project. Game mechanics may change. Verify valuable or rare-item rituals in game before committing them.

## License

MIT — see [LICENSE](LICENSE).
