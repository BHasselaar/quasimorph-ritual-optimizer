# Update v0.7.15 - cross-asset runtime fallback

The v0.7.14 report resolved `MGSC.ItemFactory` in `sharedassets0.assets` and
found the runtime placeholder sprites:

- `_iconOneSlotPlaceholder` -> `item_placeholder_one_inv`;
- `_iconTwoSlotPlaceholder` -> `item_placeholder_two_inv`;
- `_smallIconPlaceholder` -> `item_placeholder_floor`;
- `_shadowPlaceholder` -> `item_placeholder_shadow`.

The target descriptor lives in `resources.assets`, while the `ItemFactory`
fallbacks live in `sharedassets0.assets`. v0.7.15 applies runtime icon fallbacks
after all asset files have been scanned, so cross-asset data can be combined.

The managed DLL also shows `ItemRecord::.ctor` initializes
`InventoryWidthSize = 1`. Blank `config_items` cells now preserve that default,
so `moon_armor_plates` resolves to the one-slot runtime placeholder
`item_placeholder_one_inv`.
