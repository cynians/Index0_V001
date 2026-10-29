# Claude Code Handoff — 2026-08-15

## Repository state

- Workspace: `C:\Users\logol\PycharmProjects\Index0_V001`
- Branch: `codex`. Starting commit for this session: `6666a29 version 0.1.51`.
- Nothing from this session (or the one before it) is committed. Preserve the dirty worktree — do not reset or discard.
- The venv Python is not on PATH: `C:\Users\logol\Index\.venv\Scripts\python.exe`.
- Never run the full test suite (`unittest discover`) — worldgen tests are slow. Run targeted modules (list below). `tools/run_person_sim_lab.py` is the live-code checkpoint for anything touching `simulations/person/`, `simulations/map/map_simulation.py`, `world/ownership_resolver.py`, or `ui/ui_manager.py` — run it plain to regenerate, `--check-current` to verify without regenerating.
- The prior handoff, `docs/CLAUDE_CODE_HANDOFF_2026-08-14.md`, is still accurate background for the person/site-simulation vertical slice this session built on top of. Read it first if the person/site material below is unfamiliar.
- **Rule established this session, apply it going forward:** any change that touches entity data (new/renamed fields, restructured relationships) must also update the relevant `tools/author_*.py` schema declarations and be re-applied to the live ontology — not just the Python consumers. (Saved to memory as `feedback-check-ontology-schema-sync`.)

## What actually shipped this session (implemented, tested, verified against the live ontology)

### 1. Ownership resolver bug fix
`world/ownership_resolver.py` `_entities()` used to return early on an overlay's own (often empty) `.entities` dict and never reach the real ontology data in `.loader.entities` — meaning every ownership check inside `SiteSimulation` silently saw zero entities. Fixed to merge base + overlay (overlay wins on id collision). New test file: `tests/test_ownership_resolver.py`.

### 2. Outbound logistics, stock-bounded
`simulations/person/site_simulation.py` now actuates outbound routes too (new `lumber_pickup` point), bounded by what's actually been unloaded into storage (`_lumber_stock`/`_consume_lumber_stock`, reusing the existing `container_inventories` tally rather than a new ledger). `tools/author_lumber_logistics_model.py`'s outbound route flipped from `status: "placeholder"` to `"active"`.

### 3. Wish/goal registry (replaced free-text wishes/goals/dreams)
Wishes are no longer plain strings — they're structured entities in a new `wishes` ontology dataset (`tools/author_wish_registry.py`): `task_type`, `qualifier`, `target` (real entity link), `wish_type` (the tag used for matching), `note` (free text, display-only). Person's `wishes`/`goals`/`dreams` fields are now `entity_list` references into that dataset.
- `_goal_tags()`/`_authored_motive_boost()` in `simulations/person/person_simulation.py` resolve wish entities and match `wish_type` exactly — no more keyword guessing.
- **Wish vs. job-task distinction is structural, not just documented:** `lumber_dropoff`/`lumber_pickup` carry no `tags` at all — wishes can never drive job-assigned duty points, only a person's own internally-formed tasks. Job duties arrive exclusively through `assign_external_task`. Documented in `docs/conceptual_layer_overview_v006.txt` section 22 (Persons and Pops), Is-State.
- Elda Marr's old free-text goal → `wish_obtain_lumber_for_repairs` (correctly matches nothing yet — no personal "home improvement" point exists at the site). Mara Voss got a new demonstrative wish, `wish_relax_after_shift` (wish_type "Social Place"), verified to boost her `target` point's decision score by +18 with reason `"Wish: Relax With Colleagues After A Shift"`.
- `PersonSimulation.habits = []` — a deliberately inert stub (habit formation from repeated task performance), nothing reads/writes it yet.

### 4. Employment as relationships (not a mediating entity)
Replaced the standalone `employment_*` entities with plain fields on the person: `is_employed_by` (entity_list → producer/institution/faction), `is_employed_as` (entity → job), `is_employed_at` (entity → location). A producer/institution's `employed_people` roster is **derived**, never hand-authored — `EntityLoader.populate_employment_rosters()` (`world/entity_loader.py`), added to `DERIVED_FIELDS` in `world/ontology_repository.py`, mirrors the exact pattern already used for `parent_location → offspring`.
- `job_criticality` (on `job`, `tools/author_job_production_model.py`) and `employer_discipline_level` (on `producer`, and per later discussion should also be added to `institution` — **not done yet**, flagged below) combine as real inputs to the *existing* personality-weighted duty scoring in `PersonSimulation._score_task`/`assign_external_task` — see `PersonSimulation.employment_pressure()`. Wired into the one real employment-driven duty call site: `SiteSimulation._handle_vehicle_arrival`'s lumber-unload assignment.
- `OwnershipResolver._person_access_subjects` reads `is_employed_by` directly now.
- Migrated: the 4 lumber-site workers (Mara/Elias/Nia/Tomas), `tools/run_person_sim_lab.py`'s fixture stub, `tests/test_author_person_food_ownership_model.py`, `tests/test_person_simulation.py`.
- **Known loose end:** `ui/card_production.py`'s inline production-line editor (the repo browser's card-based UI for editing a producer's `production_lines`) still reads/writes the *old* `employment_ids`/`employment_assignments` fields internally (`_store_inline_production_lines`, around line 278-374). It wasn't touched — it still works for its own old-style data, just isn't wired to the new relationship fields. `tests/test_inline_production.py` still passes as-is (self-contained, doesn't touch the new fields).
- **Known loose end:** the `producer` ontology schema still declares the *stale* `employment_assignments` field (merge-only schema updates don't remove keys absent from the new dict — see the memory rule above, this is exactly the kind of thing it's meant to catch). `pop` schema's `employment_assignments` field was never migrated at all (pops don't have `is_employed_by`-equivalent fields — see the pop-system section below, this was intentionally superseded by the pop-recruitment model instead of ported 1:1).

### 5. Pop system + Pop Simulation (new)
Ten-question design round settled: pops are **overlapping statistical views on a shared population**, never additive — an employment pop doesn't add people, it labels an exact recruited count from one or more source pops (`source_allocations: [{source_pop, count}]`), and its own `population_count` is *derived* (summed), never authored, so nobody is ever implied to exist twice.
- Schema (`tools/author_pop_system_model.py`): `pop_type` (location | cultural | employment), `parent_pop` (category nesting, mirrors `job.parent_job`), `employer`, `source_allocations`, `age_distribution` (static bell-curve params: mean/stddev/min/max — no dynamics yet, `growth_rate_stub` is the inert placeholder for later), `sex_ratio`.
- Demo data: `pop_lumber_neighbor_village` (30, `pop_type: "location"`) → `pop_lumber_factory_workers` (12, derived, nested under general category `pop_factory_workers`, employer = `producer_lumber_test_factory`).
- New `simulations/pop/pop_simulation.py` — `PopSimulation`, a **launchable** view (not just a backend resolver, per explicit answer): composition breakdown, nested-children listing, static age-bucket bell curve for rendering. Wired through `LaunchAffordanceResolver` (`app/launch_affordance_resolver.py`) → `NavigationController.launch_pop_tab` (`app/navigation_controller.py`) → a real panel in `ui/ui_manager.py` (`render_mode == "pop"`, `_draw_pop_composition`).
- `PopSimulation.show_time_ui = False` — opts out of the generic time-strip assumption every other sim has (`sim.sim_clock`), since it's a static composition view with no running clock.
- 7 tests in `tests/test_pop_simulation.py`, all passing; full scoped suite (105 tests) and the production lab checkpoint both clean.

### 6. Floating entity card fixes
- **Crash fix:** `ui_manager._rebuild_floating_card` relayouts the card (populating `header_drag_rect`) then calls `scrub_floating_card_hitboxes()`, which used to null `header_drag_rect` back out as a blunt "disable drag" measure. `draw_card` (`ui/card.py`) and the schema-card equivalent (`ui/schema_card.py`) read that field unconditionally for the header's visual bounds with no relayout in between → crashed on *every* floating card open with `TypeError: rect argument is invalid`. Fixed with a computed fallback in both draw functions. New regression test in `tests/test_site_simulation.py` reproduces the exact crash against the pre-fix code before passing against the fix.
- **Instance isolation:** the floating card used to reuse `ui_manager.knowledge_ui` directly — the *same* instance the full-screen modal repository browser uses. Opening a floating card overwrote the browser's own `layout["right_rect"]`/`canvas_offset_x`/`canvas_offset_y`/`canvas_zoom` and appended into its shared `.cards` list, so exiting a sim without explicitly closing the floating card left a stale, broken card behind in the repository browser. Fixed with a dedicated `ui_manager.floating_knowledge_ui` instance, used throughout `_open_floating_card`/`_rebuild_floating_card`/`draw_floating_card`/`close_floating_card`/`scrub_floating_card_hitboxes` and in `app/input_router.py`'s `_handle_floating_card_input`.
- **Drag/resize enabled:** `scrub_floating_card_hitboxes()` now only strips edit/delete affordances in read-only inspect mode (the real data-safety concern); it no longer nulls `header_drag_rect`/resize hitboxes. `input_router.py` now also forwards `MOUSEMOTION`/`MOUSEBUTTONUP` to continue a drag/resize *only while one is actually in progress* (checked via `active_card_drag_id`/`active_card_resize_id`/`active_card_color_slider`), so the card stays non-modal otherwise.
- **⚠️ User-reported, NOT confirmed fixed:** after the above, the user reported drag still doesn't work in the live app, in both Site Sim and Person Sim. I drove the exact real event pipeline (`InputRouter.route_event`, not a shortcut) through a full mousedown→mousemotion→mouseup sequence on a freshly-opened card and it moved the card by the exact mouse delta — the mechanism is demonstrably correct in isolation, and the full scoped test suite passes. Could not reproduce the failure. Two live things to check first: (a) **is the running app process stale** (started before this fix — Python doesn't hot-reload, needs a restart), (b) **is the user grabbing the actual header strip** (only the top ~28px where the title/close button sit is draggable — clicking the tab row or body won't start a drag by design). If it still fails after a restart with a precise header-grab, this needs a fresh live debugging pass — the code-level evidence says it should work.
- **ESC/system menu z-order fix:** the system menu used to draw *inside* `ui_manager.draw()`, but `app.py` draws the floating card *after* `ui_manager.draw()` returns — so the floating card always painted over the ESC menu. New `ui_manager.draw_system_menu_overlay()`, called last in `app/app.py`, after `draw_floating_card()`. Verified fixed via the relevant test suite (105 tests pass) — **not yet visually confirmed live** by the user.
- **Person-mode side panel sizing:** the Needs/Personality/Knowledge/Tasks/Items overlay panel (a *different*, older UI element than the floating card — custom-drawn, no drag/resize) was capped at a fixed 760×610 regardless of window size, clipping longer content. Now sizes to fill the available screen (`ui/ui_manager.py`, the `panel_w`/`panel_h` block inside `rebuild_for_state`'s `"person"` render-mode branch).

## Explicitly deferred / not built

### Generalized placement + Site Simulation focus/anchor split
Discussed and scoped, not implemented. The ask: instead of a person always opening on the disconnected generic solo test map, route them into whichever simulation their **most specific currently-valid `location_history` entry** calls for (a real field already on person cards' Location tab: `{location_id, start_year, end_year, note}` — a person linked only to a star system opens Space; linked to a site opens that site's living `SiteSimulation`). Confirmed priority rule: most recent `start_year` wins, most specific location as tiebreak among near-simultaneous entries.
This requires:
1. A placement-resolution function (probably a new method on `LaunchAffordanceResolver`) that reads `location_history`, filters by current-year validity, ranks by recency-then-specificity, and reuses `options_for_entity`'s existing location-class → mode routing.
2. `SiteSimulation` needs a real **focus vs. anchor** split — today `self` (the `SiteSimulation` instance) *is* the anchor person (`resident_people[0]`), hardcoded, and every panel query (`get_needs_panel_model` etc.) and the Direct Control toggle act on `self` unconditionally. Focus needs to be a separate, settable target so panels/Direct-Control follow whichever person you actually launched from, while the anchor keeps driving `_update_site_runtime`'s tick loop regardless. **Real subtlety found and not yet resolved:** `control_mode` is read both for UI display (should follow focus) and internally inside `PersonSimulation._update_runtime` for whichever agent is *actually being ticked* (must always be that agent's own mode, never redirected) — a naive property override would break the anchor's own autonomous behavior. Needs a separate accessor for the UI-facing "what's focused" concept, not a redirect of `control_mode` itself.
3. Camera should center on the focused person, not the anchor.

This is "other people in Person Sim are stagnant" from the user's perspective — expected/known, not a regression from anything else this session.

### Site-simulation fidelity/scope (how much detail different contexts get simulated at)
User's own words: "the scope of this must be discussed later." Untouched, intentionally.

## In progress: Bioregion simulation rework

User wants `simulations/bioregion/` **wholly rebuilt**, not patched — "none of the current implementation needs to be preserved." Ten-question design round completed; results:

1. Build toward the full Should-Be vision (see `docs/conceptual_layer_overview_v006.txt` section 20, "BIOSPHERES AND BIOSIM" — bioregion-first hierarchy, scale-dependent species resolution, rivers as a bioregion subclass, behavior-module inheritance with category-override, plant/soil co-development, terraforming, person-layer ecological write-back), not just a bridge fix.
2. Make it launchable from a real location card (`LaunchAffordanceResolver`), not just the current standalone `launch_bioregion_test_tab` test harness.
3. Field audit done (see below) rather than guessed.
4. Scale driven by the real region/site being viewed, not the current fixed 10km×10km test grid.
5. **This pass = structural skeleton only** (hierarchy, scale-dependent grain, real worldgen data, soil/plant framework) — species/population/behavior-module simulation gets stubbed, same pattern as `habits`/`growth_rate_stub` elsewhere this session. Not built in this pass.
6. Rivers-as-bioregion-subclass deferred (would reuse `simulations/map/road_corridor_window.py`'s crawling-map engine, built earlier for logistics roads).
7. **Biosphere is a durable ontology entity, built from the start of this work** — the storage for all biotic/ecological data (species rosters, ecological soil profile, stability notes) *except* geology/geography, which stays on the location/worldgen entity. This is the next concrete step.
8. Validate with unit tests + a manual screenshot — no new lab-checkpoint tooling for this.
9. Share rendering primitives with `simulations/world_gen/world_gen_renderer.py` rather than keeping `bioregion_renderer.py` fully independent.
10. Worldgen field audit came first (done — see below); Biosphere schema comes next.

### Worldgen field audit results (informs the Biosphere schema — read before designing it)

`simulations/bioregion/bioregion_simulation.py`'s existing worldgen bridge (`_resolve_worldgen_context`, `_has_worldgen_context`) checks 10 field names on a location entity. Audited against the current `simulations/world_gen/world_gen_sim.py` and its ~30 helper modules:

- **9 of 10 are still correct/current**: `heightmap_model`, `hydrology_summary`, `environment_summary`, `water_cycle_model`, `koppen_climate_model`, `river_model`, `climate_summary`, `natural_material_model`, `materials_summary`.
- **1 is dead**: `climate_zone_model` — never written anywhere (`grep -rn '"climate_zone_model"\]\s*='` returns zero hits). Only appears in two `.pop(key, None)` cleanup calls (popping a key that's never set) and the bioregion bridge's own now-pointless fallback read (`bioregion_simulation.py:263-269`, safe to delete — `koppen_climate_model` is read first and always has the real data).
- **The real gap is coverage, not staleness.** Worldgen already produces several fields the bridge never asks for at all:
  - **`regolith_soil_model`** (soil depth/porosity/pH/salinity/dominant classes, from `regolith_soils.py`) — **this one self-labels `"biosphere_contribution": "excluded_pending_separate_design"` in its own generated data.** It was built explicitly waiting for this bioregion work. Strong signal for what the Biosphere's ecological soil-profile field should be derived from (distinct from this — the Should-Be text's own distinction is "area soil profile" = current local substrate, from this field, vs. "Biosphere soil profile" = what the assemblage requires/produces/stabilizes, authored separately).
  - **`material_heatmap_model`** — fine-grained per-cell material rasters. The bridge's `_has_worldgen_context` already gates on this field's presence but never actually extracts it into the resolved context dict (`bioregion_simulation.py:225` checks for it, `_resolve_worldgen_context`'s returned dict doesn't include it) — an existing bug, not a new one.
  - `ocean_circulation_model`, `cryosphere_model` (ice/seasonal-snow fraction), `surface_evolution_model` (erosion/weathering process grid), `true_color_model` (usable as an albedo proxy) — all currently invisible to the bridge, all plausibly relevant to a biosphere's climate/substrate inputs.

### Next concrete action
Draft the Biosphere ontology schema (likely a new `tools/author_biosphere_model.py`, following the same pattern as `author_pop_system_model.py`/`author_wish_registry.py`): species rosters, ecological soil profile fields (organic layer, topsoil, subsoil, parent material, moisture capacity, pH, salinity, nutrients, microbial activity, drainage, compaction, erosion risk, root-depth constraints — per the Should-Be text), stability/failure-mode notes, and a reference back to the location/worldgen entity it overlays for geology. Then design the bioregion-first hierarchy (bioregion as the main simulation object; species/populations/individuals resolved differently depending on current scale/grain) and rebuild `BioregionSimulation` against it, consuming the 9-current-plus-5-newly-surfaced worldgen fields above via a corrected bridge.

## Verification commands used this session

```powershell
# Scoped test modules actually exercised this session (fast, safe to rerun)
C:\Users\logol\Index\.venv\Scripts\python.exe -m unittest tests.test_ownership_resolver tests.test_person_simulation tests.test_site_simulation tests.test_lumber_logistics_model tests.test_person_ui_panels tests.test_author_person_food_ownership_model tests.test_navigation_building tests.test_inline_production tests.test_pop_simulation

# Live-code checkpoint (run after touching person/site/map/ownership/ui_manager)
C:\Users\logol\Index\.venv\Scripts\python.exe tools\run_person_sim_lab.py
C:\Users\logol\Index\.venv\Scripts\python.exe tools\run_person_sim_lab.py --check-current

# Re-apply ontology authoring tools after schema/data edits (module mode needed for author_job_production_model.py specifically -- it has no sys.path bootstrap)
C:\Users\logol\Index\.venv\Scripts\python.exe tools\author_wish_registry.py
C:\Users\logol\Index\.venv\Scripts\python.exe tools\author_pop_system_model.py
C:\Users\logol\Index\.venv\Scripts\python.exe tools\author_person_psychology_model.py
C:\Users\logol\Index\.venv\Scripts\python.exe tools\author_person_food_ownership_model.py
C:\Users\logol\Index\.venv\Scripts\python.exe -m tools.author_job_production_model
```

Known **pre-existing, unrelated** failure if you ever do run repository-integrity or worldgen-adjacent tests: `tests.test_repository_integrity.test_star_system_neighbourhoods_are_present_in_ontology` fails on `system_test_system_prime` contaminating `system_sol.stellar_neighbours` — flagged to the user in an earlier session, not yet cleaned up (real ontology data, needs their explicit go-ahead to touch), not caused by anything in this session. Also, `tests.test_world_gen_orbit_clicks` currently has several failures (`editor_stage`, seed-text, `parent_location` naming mismatches) — confirmed unrelated to anything touched this session (worldgen wasn't modified until the read-only audit above); likely drift from concurrent Codex work on worldgen.

## Working-tree caution

Substantial interdependent edits across ontology schemas, simulation code, UI, navigation, and tests — review the diff before restructuring anything broadly. Specifically:
- Do not delete or reset `simulations/pop/`, `tests/test_pop_simulation.py`, `tools/author_pop_system_model.py`, `tools/author_wish_registry.py`, or any of the other untracked files listed by `git status` — all are real, tested work.
- Do not re-introduce the old `employment_*` entity pattern — employment is a relationship field now (see section 4 above), and `world/entity_loader.py`'s `populate_employment_rosters()`/`ontology_repository.py`'s `DERIVED_FIELDS` depend on that.
- The `wishes` dataset and its keyword-free matching (section 3) replaced free-text wishes entirely — don't add new free-text wish/goal strings to authored people; author a `wishes`-dataset entity and reference it by id instead.
- `PopSimulation.show_time_ui = False` and the `_draw_pop_composition`/`draw_system_menu_overlay` additions in `ui/ui_manager.py` are load-bearing for the fixes above — don't revert `ui_manager.py`'s draw-order changes without understanding why the system menu moved (see section 6).
