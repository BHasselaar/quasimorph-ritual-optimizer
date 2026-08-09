# v0.7.4 — unresolved sprite contact sheets

Corrections:
- `impaler` display name -> **Ossuary**
- `impaler` sprite -> `scrivnus_impale_inv`
- `moon_armor_plates` display name remains **Quasiplumbum**, but its forced wrong
  sprite mapping was removed.
- `venus_weapon_parts` display name remains **Mechanism Parts**, with no forced
  sprite mapping.

New UI action:
**Export unresolved sprite candidates**

It creates candidate contact sheets in:

    %APPDATA%\QuasimorphRitualOptimizer\sprite_candidates\

Expected files:
- `moon_armor_plates_candidates.png`
- `moon_armor_plates_candidates.json`
- `venus_weapon_parts_candidates.png`
- `venus_weapon_parts_candidates.json`

Each sheet contains up to 36 likely Texture2D inventory candidates with the
Unity asset name and score under each image. Once the correct two are identified,
their asset names can be locked into the extractor permanently.
