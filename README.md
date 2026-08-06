# Quasimorph Ritual Optimizer

A Windows desktop application that exhaustively searches five-component pact rituals in **Quasimorph** and ranks clockwise ring orders for Jackpot, Upgrade, Sidegrade, low Disenchant risk, or balanced Power/Stability.

## What changed in v0.3.0

Version 0.3.0 removes the provisional empirical calibration introduced in v0.2.0. The Tier 3 Siaira discrepancy was caused by an incorrect inventory entry: **Spider Joint is Agga, not Shavva**.

With Spider Joint corrected and the installed **+100 ship Power** bonus applied, the community model reproduces the game display for:

```text
Load of Gold Bars → Gavvakh → Spider Joint → Rotten Spider Flesh → Feces
```

```text
Calculated exact: Upgrade 44.505%, Sidegrade 2.683%, Downgrade 41.495%, Disenchant 11.317%
Game display:     Upgrade 45%,     Sidegrade 3%,     Downgrade 41%,     Disenchant 11%
```

Four additional Tier 1 Gavvakh tests also match the game's rounded percentages. These tests verify that ship bonuses are added **after affinity-adjusted component contributions are summed** and before division by the tier targets.

## Features

- Exact brute-force search over every five-item selection and directed circular order.
- Editable inventory with add, edit, delete, enable/disable, CSV import, and CSV export.
- Supports all five pact tiers and all five center essences.
- Explicit ship Power and Stability bonus fields.
- Default ship bonus is **+100 Power / +0 Stability**; change these to match your save.
- Top-N ranked results with complete per-component affinity breakdowns.
- Background search, progress reporting, cancellation, and result export.
- Automated tests and Windows executable builds through GitHub Actions.

## Run from source

Requires Python 3.11 or newer.

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
quasimorph-ritual-optimizer
```

On Windows, `run_app.bat` is a convenient alternative after Python is installed.

## Build the Windows executable

```powershell
build_windows.bat
```

The executable is written to `dist/QuasimorphRitualOptimizer.exe`.

## Inventory

The first launch copies the included inventory to:

```text
%APPDATA%\QuasimorphRitualOptimizer\inventory.csv
```

CSV format:

```csv
enabled,name,essence,power,stability
true,Load of Gold Bars,eon,110,25
true,Spider Joint,agga,80,25
```

On first launch after upgrading from v0.1/v0.2, the app automatically corrects the exact known legacy entry `Spider Joint,shavva,80,25` to Agga. Other custom items are not changed.

## Calculation model

For each component:

```text
Power contribution = base Power × predecessor→component Power multiplier × component→center Power multiplier
Stability contribution = base Stability × predecessor→component Stability multiplier × component→center Stability multiplier
```

Then ship bonuses are applied:

```text
Total Power = sum(component Power contributions) + ship Power bonus
Total Stability = sum(component Stability contributions) + ship Stability bonus
```

Effective percentages are capped at 100%:

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

The five outer items form a directed circular ring, so the fifth component is the predecessor of the first. Rotations are equivalent; mirror-image orders are not.

## Search size

The optimizer evaluates:

```text
C(number of enabled items, 5) × 4!
```

With 18 enabled items, this is **205,632 unique directed circular orders**.

## Development

```powershell
python -m pip install -e . -r requirements-dev.txt
pytest
```

## Disclaimer

This is an unofficial community project. Game mechanics may change. Verify valuable or rare-item rituals in game before committing them.

## License

MIT — see [LICENSE](LICENSE).
