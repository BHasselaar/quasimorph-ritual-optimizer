# Quasimorph Ritual Optimizer v1.0.0

v1.0 keeps component matching tied to confirmed in-game sprite names, uses NumPy batch evaluation, and reads only the selected save when the user asks it to. Repeated components remain available as an advanced option.

# Quasimorph Ritual Optimizer

A Windows desktop application for exhaustive pact-ritual optimization in **Quasimorph**.

Version 1.0 operates as a read-only companion to an installed copy of the game: it imports the current ritual database from Unity assets, reads component quantities from the selected save, detects Morph Analysis ritual bonuses, and can locally extract the matching inventory sprites.

## v1.0 highlights

- Exact brute-force optimization for Jackpot, Balanced, Sidegrade, or Minimum Disenchant.
- Multi-process CPU search; `Workers = 0` uses all logical CPUs.
- Quantity-aware rituals. Five copies of one component can now legitimately produce a five-copy ritual if the save contains at least five.
- Game database import from `Quasimorph_Data/resources.assets`:
  - `#pactcomponents`
  - `#pacttiers`
  - `#essenceaffinity`
  - `SkullRitualUpgradeChanceCap`
- Manual selected-save refresh from `slot_*_session.dat`:
  - ship cargo
  - fridge storage
  - recycling storage
  - Morph Analysis Power/Stability upgrades
- Local sprite extraction with UnityPy.
- Setup status for game folder, selected save, sprite readiness, and available components.
- Lightweight post-ritual refresh that reads only the selected save.
- Graphical five-component ritual preview.
- Searchable, sortable, draggable inventory with availability toggles, quantities, and a hide-unavailable filter.
- Sortable result columns and 10,000 Top Results default.
- Copy selected ritual order to the clipboard.

## Read-only game integration

The application never modifies Quasimorph files. It only reads the installation and save, then writes its own cache to:

```text
%APPDATA%\QuasimorphRitualOptimizer\
```

Typical cached files include:

```text
game_database.json
inventory.csv
settings.json
sprites\
```

The extracted sprites remain on the local PC. They are not part of this repository or its releases.

## Using game synchronization

1. Launch the optimizer.
2. Click **Locate game folder** if the game was not detected automatically.
3. Click **Choose save** and select the current `slot_*_session.dat`.
4. Click **Sync game data** to parse `resources.assets` and load the ritual database.
5. Click **Extract sprites** once to create the local icon cache.
6. After doing a ritual in-game, click **Refresh save after ritual** to update quantities from the selected save.
7. Ritual components not present in the save are shown unavailable; present components show their exact quantity.
8. Morph Analysis ritual bonuses are filled automatically.

If automatic path detection fails, use **Choose game folder** or **Choose save**.

## Exact quantity-aware search

A component definition and a physical inventory quantity are separate concepts. If a save contains:

```text
Load of Gold Bars ×5
Spider Joint ×2
```

the optimizer may use up to five Gold Bars and two Spider Joints in a ritual. Circular rotations are collapsed so each directed ritual ring is evaluated once.

## Ritual calculation

For each component:

```text
Power contribution = base Power × predecessor→component Power multiplier × component→center Power multiplier
Stability contribution = base Stability × predecessor→component Stability multiplier × component→center Stability multiplier
```

Ship bonuses are applied after component contributions are summed. Power and Stability are divided by the current tier targets and capped at 100%. The result probabilities and 70% Upgrade-to-Jackpot split follow the game records/code model verified during development.

When game synchronization is active, tier targets, affinity multipliers, and the Jackpot cap are taken from the installed game data rather than only from bundled constants.

## Run from source

Requires Python 3.11+.

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
quasimorph-ritual-optimizer
```

`UnityPy` is installed as a dependency for local sprite extraction.

## Build Windows executable

```powershell
build_windows.bat
```

The executable is written to:

```text
dist\QuasimorphRitualOptimizer.exe
```

## Development

```powershell
python -m pip install -e . -r requirements-dev.txt
pytest
```

## Copyright note

Quasimorph artwork is not distributed with this project. Sprite extraction operates locally against a user's installed game and stores the resulting cache locally.

## License

MIT — see [LICENSE](LICENSE).
