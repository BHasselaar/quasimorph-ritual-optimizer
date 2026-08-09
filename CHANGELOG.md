## 0.7.0

- NumPy batch evaluator for distinct-component searches.
- Distinct components are the default; repeats are opt-in.
- Imported ritual price and per-result material cost.
- Broader safe sprite matching using Sprite + Texture2D.
- Includes v0.6.1/v0.6.2 startup/sync fixes.

# Changelog

## 0.6.0

- Added read-only game database import from `resources.assets`.
- Added save-file quantity synchronization and automatic Morph Analysis ritual bonuses.
- Added exact quantity-aware repeated-component brute force.
- Added local UnityPy sprite extraction/cache and graphical ritual preview.
- Added internal game IDs and quantities to inventory records.
- Added dynamic tier/affinity/Jackpot-cap rules from the installed game.
- Added integration regression tests.

## 0.5.0

- Added component-name search.
- Added case-insensitive duplicate-name protection for manual entry, CSV import, and saving.
- Added click-to-sort inventory headings for availability, name, essence, power, and stability.
- Added click-to-sort result headings for every displayed metric and clockwise order.
- Changed default objective to Balanced and reduced objectives to Jackpot, Balanced, Sidegrade, and Minimum Disenchant.
- Increased default retained results to 10,000.
- Reworked the brute-force hot path: pairwise affinity contributions are precomputed, candidates use compact numeric scoring, multiprocessing work is partitioned into low-overhead ranges, and full breakdown objects are created only for final retained results.
- Preserved exact rankings against the reference evaluator across all supported objectives.

## 0.4.0

- Updated bundled inventory to the repository's current 38-item list/order.
- Added persistent ship bonus and worker settings; ship bonuses default to zero.
- Added checkbox-style availability controls with green/red row states.
- Added drag-and-drop inventory reordering with automatic save.
- Added horizontal and vertical scrolling to inventory, results, and details.
- Added multi-process brute-force execution with auto CPU detection and deterministic ranking.
- Added an explicit Load bundled inventory action; no automatic inventory migration.
- Added settings and parallel-equivalence tests.

All notable changes to this project will be documented here.

The project follows [Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-08-06

### Fixed

- Corrected Spider Joint essence from Shavva to Agga.
- Added automatic migration for the known legacy Spider Joint inventory row.
- Correctly exposes ship Power and Stability as flat bonuses applied after affinity contributions.

### Changed

- Removed the provisional empirical calibration model and observation CSV workflow.
- Set the desktop default to +100 Power and +0 Stability for the currently reported ship upgrades.
- Added regression tests for four Tier 1 Gavvakh rituals and the corrected Tier 3 Siaira ritual.

## [0.2.0] - 2026-08-05

### Added

- Observation CSV import, export, and automatic per-tier/per-essence calibration.
- Empirical and community probability-model selection in the desktop interface.
- Calibration metadata and adjusted targets in result details and CSV exports.
- Regression tests for the reported Tier 3 Siaira ritual.

### Changed

- Tier 3 Siaira empirical targets now reproduce the reported 45% Upgrade, 3% Sidegrade, 41% Downgrade, and 11% Disenchant display after rounding.
- The four displayed outcomes are calculated separately from the still-experimental Jackpot split.
- Jackpot labels and documentation now explicitly identify the estimate as unverified.

## [0.1.0] - 2026-08-05

### Added

- Tkinter desktop inventory editor.
- Exhaustive five-item directed circular-ring optimizer.
- Jackpot, Upgrade, Upgrade+Jackpot, Sidegrade, Disenchant, balanced, Power, and Stability objectives.
- Full affinity matrix and tier targets supplied by the community model.
- Per-component calculation breakdowns and CSV result export.
- Unit tests, continuous integration, Windows executable builds, and tagged GitHub releases.
