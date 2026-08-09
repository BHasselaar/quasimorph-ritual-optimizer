# Updating to v0.4.0

Replace the application files with the v0.4.0 files and rebuild the executable if you run a local build.

v0.4.0 intentionally performs **no automatic inventory migration**. Existing `%APPDATA%\QuasimorphRitualOptimizer\inventory.csv` files remain untouched. To adopt the bundled 38-component v0.4 inventory, click **Load bundled** in the Inventory toolbar.

Ship bonuses now default to `0 / 0` on a fresh install and save to `settings.json` whenever valid values are changed.
