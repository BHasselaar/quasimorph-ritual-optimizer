# v0.7.0 — Practical search + NumPy + ritual cost

## Search behavior
- Default search uses each component type at most once.
- Repeated components are opt-in through **Allow repeated components (advanced)**.
- The default exact search uses NumPy batches for the heavy probability math.
- Multiprocessing remains available; low-thread-count machines benefit from the
  vectorized batch evaluator even with 1–4 workers.

## Price
- `Price` is imported from Quasimorph's `#pactcomponents` table.
- Inventory shows Price.
- Every result shows total material Cost.
- Cost is sortable and included in CSV exports and ritual details.
- Price does not change the probability ranking yet; it is informational/sortable.

## Sprites
v0.6 extracted only high-confidence `Sprite` matches. v0.7:
- scans both `Sprite` and `Texture2D`;
- matches against internal IDs and display names;
- handles `_inv`, `_icon`, camelCase, `eye/aye`, and known game aliases;
- keeps a conservative acceptance threshold to avoid attaching the wrong icon.

## Important
Sprite files remain local and are not bundled into the repository.
Game files and saves remain read-only.
