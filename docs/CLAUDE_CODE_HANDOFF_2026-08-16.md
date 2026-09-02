# Claude Code Handoff — 2026-08-16

## Repository state

- Branch: `codex`. Working tree matches session-start `git status` exactly —
  all code from this session was reverted (see below). Do not assume a clean
  tree; the usual pile of pre-existing uncommitted work (person/site sim,
  pop system, lumber logistics, floating card, etc. from prior sessions) is
  still there untouched.
- Venv: `C:\Users\logol\Index\.venv\Scripts\python.exe` (not on PATH).
- **Ontology just got dramatically smaller and faster.** `ontology/index0.owl`:
  1.84GB → **113.5MB**. Quadstore cache (`.cache/ontology/*.quadstore.sqlite3`):
  5.76GB → **221.8MB**. `WorldModel()` construction: ~15–20 min → **~5 seconds**.
  This is durable (ontology isn't git-tracked) — don't be surprised it's fast
  now, and don't assume the old "worldgen tests are slow" caveat still holds
  at the old magnitude for ontology *loading* specifically (regional
  refinement's own generation compute, ~1–4 min/level, is unchanged).

## What happened this session (in order)

1. Fixed the 7 world-gen detail levels (`regional_refinement.py`
   `generate_refined_region`) to target physically correct footprints per
   level instead of a flat 40%-of-parent crop — confirmed a real
   planetary→10m descent. **This fix was later fully reverted** (see below),
   along with everything else code-side. If you want it back, it's simple:
   `render_mountain_refinement_examples.py`'s per-level crop logic needs to
   target `sqrt(low_m * high_m) * sample_width` from each level's
   `DETAIL_LEVELS[level]["nominal_resolution"]` band instead of a constant
   0.4 crop ratio; level 7 targets `MIN_REFINED_EXTENT_M` (10m) directly.
2. Diagnosed a real ontology architecture problem: world-gen was persisting
   huge numeric grids (heightmap sample grid, climate grid, erosion process
   grid — ~30MB per disposable test region) as inline JSON-blob ontology
   literals. Built a fix (`grid_bundle.py`, a `.i0g` bundle format mirroring
   the existing `.i0r` material-raster pattern) wired into
   `regional_refinement.py`'s and `world_gen_sim.py`'s persistence/load
   boundaries. **This was also fully reverted** — see "What's reverted"
   below if you want to redo it; the design is sound, just not currently in
   the tree.
3. User authorized and I executed a real ontology cleanup: deleted 139
   legacy world-gen test/headless entities (all `planet_test*` variants,
   orbit drafts, test stars/systems including the long-flagged
   `system_test_system_prime` contamination, all disposable `refined_*`
   regions), fixed `system_sol.stellar_neighbours` (removed the
   `system_test_system_prime` reference), then `VACUUM`ed the SQLite
   quadstore and ran `export_rdfxml()` to refresh the checkpoint XML. This
   is the source of the size/speed numbers above. **This was NOT reverted**
   — it's ontology data, explicitly out of scope for the code revert.
   Deletion mechanism used: `PersistentOntologyStore(ontology_path).remove_entity(id)`
   — fast (targeted IRI lookup, no full-store materialization), unlike
   `EntityLoader`/`WorldModel()`'s bulk load path.
4. Generated a fresh "Test 1" planet on "Testing System" (technical ids
   `planet_test_1`/`system_headless_test`/`star_headless_test`, renamed for
   display) and ran the 7-level drill-down with an extended inspection tool
   that composited all 7 renderable layers (True Color, Surface Materials,
   Climate and Rivers, Coastal Geomorphology, Surface Temperature, Annual
   Precipitation, Chemical Weathering) per level.
5. **Found a real bug**, unrelated to any of the above: at least one refined
   region's `water_cycle_model.climate_grid.temperature_rows_k` came back
   100% NaN, cascading into `surface_evolution_model` (chemical weathering
   also NaN) and `material_heatmap_model` (blank Surface Materials layer;
   True Color rendered land as solid black instead of proper terrain color).
   Traced to `water_cycle.py`'s `_solve_coupled_annual_climate` (the
   function that actually produces the final `temperature_rows_k` — not the
   simpler per-cell loop earlier in `derive_water_cycle_model`, which is a
   placeholder pass). Ruled out: the region's own heightmap was clean, and
   the parent planet's own temperature grid was clean (checked both
   directly, real finite values, no NaN). A reproduction attempt with numpy
   error-trapping (`np.seterr(all="raise")`) did NOT reproduce it — but the
   repro used a different `seed_suffix` than the original failing run by
   mistake, so different terrain detail was generated and this is
   inconclusive, not a clean "it's fine." **Still open, not fixed.**
6. User reported this "seems to have broken the water generation cycle...
   world gen as a whole" and asked to revert everything not "pure ontology."
   Did a careful, git-verified revert (see below) rather than blanket
   `git checkout`, since 3 of the touched files already had unrelated
   uncommitted work from before this session that had to be preserved.
7. User independently regenerated a planet ("Test 2") in the live
   interactive app post-revert and confirmed it renders correctly (Köppen
   climate map, working hydrology). I independently verified via direct
   SQLite query against the live ontology: `planet_test_2`'s
   `temperature_rows_k` is 129×257, **zero NaN**, realistic values
   (242.8–299.2K), real material heatmap present. **This confirms planetary-
   level generation is clean** — matches what was true throughout this
   whole session (the NaN was only ever found in a *refined region*, never
   at the planet level). Whether the regional-refinement NaN bug from step 5
   is actually gone, still present, or was never related to the reverted
   code in the first place is **not yet re-tested** — nobody has drilled
   into a region under a freshly-generated planet since the revert.

## What's reverted (verify with `git status` — should show nothing world-gen-related beyond pre-existing dirt)

- `simulations/world_gen/grid_bundle.py` — deleted (new file)
- `simulations/world_gen/storage_policy.py`, `headless_runner.py`,
  `world_gen_sim.py`, `surface_evolution.py`, `water_cycle.py` — restored via
  `git checkout` (were clean before this session)
- `simulations/world_gen/regional_refinement.py`, `heightmap.py` — manually
  reversed (other uncommitted work predates this session there; a blanket
  checkout would have destroyed it)
- `tools/render_mountain_refinement_examples.py` — restored via `git
  checkout` (back to the original fixed-40%-crop, `use_ontology=False`,
  True-Color/Height-only version)
- `tools/query_ontology.py` — deleted (new file; the fast direct-SQLite
  read-only ontology inspector built this session — see "Useful technique"
  below if you want to rebuild it, it's genuinely fast and handy)
- `docs/WORLDGEN_STORAGE_ARCHITECTURE.md` — deleted (new file)
- `docs/conceptual_layer_overview_v006.txt` — manually reversed just the
  principle #13/#15 amendment
- `assets/maps/terrain_grids/` — deleted (generated `.i0g` bundles, orphaned
  once the code was gone)

**Known inconsistency left in place, on purpose:** `planet_test_1` and its 7
refined regions (generated with the now-reverted grid-bundle code) still
have compact-manifest-shaped `heightmap_model`/etc. fields in the ontology.
The reverted (original) code can't read that shape — expect an error or
empty data if the live app tries to view/refine `planet_test_1` specifically.
`planet_test_2` (generated after the revert) is unaffected and clean.

## Useful technique discovered this session (not currently in the tree as a tool, but worth knowing)

Direct, fast, read-only ontology inspection without paying the
`WorldModel()`/`EntityLoader` full-materialization cost:

```python
from world.persistent_ontology_store import PersistentOntologyStore, ENTITY_IRI
store = PersistentOntologyStore("ontology/index0.owl")
world = store._open_world(read_only=True)   # ~0.1s even before the cleanup
db = world.graph.db                          # raw sqlite3.Connection
# List all entity IRIs:
db.execute("SELECT iri FROM resources WHERE iri LIKE ?", (ENTITY_IRI + "%",))
# Read one field (owlready2's storid-indexed datas/objs tables):
def storid(iri):
    row = db.execute("SELECT storid FROM resources WHERE iri=?", (iri,)).fetchone()
    return row[0] if row else None
s, p = storid(ENTITY_IRI + entity_id), storid("https://index0.local/ontology.owl#" + field_name)
db.execute("SELECT o FROM datas WHERE s=? AND p=?", (s, p)).fetchone()  # JSON string, usually
```

Deletion is equally fast and targeted:
`PersistentOntologyStore(ontology_path).remove_entity(entity_id)` — no full
load needed, ~0.1s per entity.

## Suggested next steps (not started)

1. Decide whether to redo the level-footprint fix and/or the grid-bundle
   storage architecture work. Both are described in enough detail above to
   reconstruct from scratch relatively quickly; neither is currently in the
   tree.
2. If redoing grid-bundle work: **fix the reproduction methodology first** —
   use the *exact* `seed_suffix` ("mountain-realism-example") the original
   failing run used, or better, drill into a region under the newly-clean
   `planet_test_2` with the *original* (reverted) code and see if the NaN
   reproduces there. If it does, the bug is pre-existing and unrelated to
   the storage-architecture work, clearing the way to redo that work with
   confidence. If it doesn't reproduce there either, look harder at whether
   something about the *specific* Test 1 terrain (mountain-following center
   selection, an unusual coastal configuration, etc.) triggered it.
3. `planet_test_1`'s inconsistent (manifest-shaped) ontology data is still
   sitting there. Either regenerate it fresh under the current (reverted)
   code, or delete it via the fast `remove_entity` technique above once
   confirmed unneeded.
