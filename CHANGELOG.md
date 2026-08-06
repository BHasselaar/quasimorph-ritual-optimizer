# Changelog

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
