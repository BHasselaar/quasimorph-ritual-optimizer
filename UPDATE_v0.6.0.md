# v0.6.0 — Game integration

v0.6.0 turns the optimizer into a read-only Quasimorph companion application.

## New

- Reads `Quasimorph_Data/resources.assets` directly and imports the game's `#pactcomponents`, `#pacttiers`, `#essenceaffinity`, and ritual Jackpot cap.
- Reads `slot_*_session.dat` and synchronizes component quantities from ship cargo, fridge storage, and recycling storage.
- Detects Morph Analysis ritual upgrades from the save and fills the Power/Stability bonuses automatically.
- Quantity-aware exact brute force: a component may be used repeatedly only up to the amount actually owned.
- Local sprite extraction via UnityPy. Extracted game images are cached under the user's AppData directory and are never bundled in the repository.
- Inventory icon column and a five-position graphical ritual preview.
- Manual inventory and manual bonus mode remain available.

## Safety

All Quasimorph game and save files are opened read-only. The application never writes into the game installation or save directory.
