# Person Simulation — Concept & Decoupling Roadmap

Status: living document. Cycles append a dated log entry at the bottom rather
than rewriting earlier sections; earlier sections are revised only when a
decision they describe is actually superseded.

## 1. Why this document exists

`PersonSimulation` (`simulations/person/person_simulation.py`) is expected to
become one of the most complex simulations in the project (TASK-037 and its
dependents in `text/tasks.txt`: universal task objects, habit formation,
multi-factor priority, cross-simulation task carryover, role-based child
subtabs, vehicle/person ownership nesting). Before adding more mechanics on
top of it, two structural problems need a deliberate plan rather than ad hoc
patching:

1. **The engine's vocabulary is currently fixed to one authored scenario.**
   `TEST_POINT_DEFINITIONS` / `TEST_MAP_BOUNDS` (`person_simulation.py:91-179`)
   hardcode exactly seven point ids (`bed`, `food`, `kitchen`, `job`, `target`,
   `lumber_dropoff`, `lumber_pickup`) as class constants. Every
   `PersonSimulation` instance builds `self.test_points` from these
   regardless of which person entity is loaded; an authored site's
   `simulation_points` can only override fields on these seven fixed points,
   never add, remove, or express an arbitrary layout. The "lumber test site"
   scenario (Mara Voss and the ontology-authored site around
   `location_lumber_test_site`) is genuine, durable ontology data — the
   problem isn't that test data lives in code, it's that the *engine* treats
   that one scenario's shape as universal.
2. **There is no notion of a person being under-specified.** Nothing in the
   codebase today assesses whether an authored person entity carries enough
   data (personality, knowledge, motivation, relationships) to be simulated
   credibly, and there is no character-creation flow to fill gaps when it
   doesn't. Every person, however sparse, is simulated as if it were as
   fully authored as the lab's cook, cast silently into the same fixed
   geometry.

This document is where we track the shape of the eventual fix and the
concept for character creation, and log what actually shipped, cycle by
cycle, under the iterative review process the user set up (propose →
implement → review renders/telemetry → refine up to 4 passes → log loose
ends → pick the next focus).

## 2. Architectural precedent: `simulations/species/`

The species simulation already demonstrates the separation person sim should
move toward:

- **Thin core, dedicated assets module.** `SpeciesSimulation` derives a
  `PlantBlueprint` from the ontology entity (`plant_assets.py`) instead of
  hardcoding growth points inline. Data classes and pure translation
  functions live in the assets module, independently testable without
  pygame or a live sim.
- **Explicit authored-vs-default provenance.** `plant_life_history_profile()`
  (`plant_assets.py:86-115`) falls back to a categorical default table when a
  trait isn't authored and tags the result `"source": "authored"` vs
  `"runtime_default"`. `get_personality_panel_model()`
  (`person_simulation.py:2442`) already does the analogous thing for Big
  Five axes — this is the pattern to generalize.
- **Ecology/decision logic as pure functions, decoupled from the sim
  class.** `forest_ecology.py` has no class at all; `SpeciesSimulation` is a
  thin adapter over it. Person sim's `_score_task` / `_urgency` /
  `_conviction_effects` scoring math is currently a method soup on
  `PersonSimulation` itself and would benefit from the same split
  (`person_psychology.py` or similar), but this is a larger, higher-risk
  refactor deferred past Cycle 1.
- **The bespoke scenario is optional and additive, not the default path.**
  Forest mode is opt-in (`sim.diagnostic_view == "forest"`); a bare
  `SpeciesSimulation` works standalone for any species. This is the target
  shape for the lumber scenario too: a specific, richly-authored example
  that exercises a generic engine, not the engine's only supported shape.

## 3. Target end state (multi-cycle)

Not committed to a timeline — this is the destination the cycles below are
walking toward:

- `simulations/person/person_assets.py`: a blueprint object resolved from an
  authored site's `simulation_points` / `layout_structures` / task-schema
  entities, with generic procedural defaults (and an `authored` flag per
  field) when a site is under-specified, replacing `TEST_POINT_DEFINITIONS`
  as the only vocabulary the engine understands.
- A generalized multi-step task template system (today `_task_for_point`
  special-cases `"food"` and `"lumber_dropoff"` by point id inline) driven by
  an authored recipe/task schema instead of hardcoded branches.
- A **person readiness / character creation system**: given a person entity,
  assess whether authored data (personality, knowledge, motivation, site,
  relationships) is sufficient for a credible simulation. When it isn't,
  offer a character-creation flow — procedurally filling gaps with
  provenance-tagged defaults, or (eventually) a player-facing creation UI —
  rather than silently running a hollow person through the full engine.
- The lumber scenario becomes one authored example location among others,
  not baked into the class.

## 4. Character creation — concept (not implemented yet)

Captured here per the user's request, as a concept to implement in a later
cycle rather than now:

- **Trigger.** A person is a character-creation candidate when its readiness
  tier is below "authored" — see Cycle 1 below for the first concrete
  tier/scoring definition (`simulations/person/person_assets.py`).
- **Shape of the gap.** Missing data falls into distinguishable categories
  that likely need different fill strategies: identity (name, sex,
  person_class), personality (Big Five), motivation (wishes/goals/dreams),
  knowledge (`knowledge_records`), social grounding (affiliations,
  residence, relations), and physical grounding (a site/position to exist
  at). A creation flow should probably address these as separate steps
  rather than one monolithic form, mirroring how the dossier/personality/
  knowledge/task panels are already separate UI surfaces.
- **Two fill strategies, not mutually exclusive:**
  - *Procedural* — deterministic, seeded generation of plausible defaults
    (`SitePresenceResolver._personality()` in `site_simulation.py:105-109`
    already does a SHA-256-seeded Big Five projection for lightweight pop
    presences; this is the closest existing precedent, though it only
    produces a name and personality numbers today, not knowledge/wishes/
    goals).
  - *Player-authored* — an explicit character-creation UI the player fills
    in when they want to intentionally define who this person is, most
    relevant when the player starts a person simulation on a deliberately
    blank/new person rather than an existing sparse NPC.
- **Provenance must survive creation.** Whatever fills the gap, the
  authored/default distinction already used for personality and plant life
  history should be preserved per-field, so a later authoring pass (or the
  player editing the dossier) can tell which values are load-bearing canon
  versus generated filler.
- **Open question, not resolved here:** whether character creation writes
  the generated values back into the ontology (durable) or keeps them as
  session-local runtime defaults (ephemeral, regenerated each load). This
  interacts with the project's staged-save/ontology-is-sole-source rules and
  needs a decision before any writeback path is built.

## 5. Cycle log

### Cycle 1 — 2026-09-05: Readiness assessment (non-destructive)

**Scope.** A thin vertical slice: introduce person data-completeness
detection without touching the existing fixed-point engine, so the lumber
test scenario and its tests keep working unchanged while every person gains
a visible signal for how sparse its authored data is.

**Shipped:**
- `simulations/person/person_assets.py` — `assess_person_readiness(person)`,
  scoring identity/personality/motivation/knowledge/social/site fields into
  a tier (`empty` / `sparse` / `authored`), with per-field authored/missing
  detail, mirroring the `plant_life_history_profile` provenance pattern.
- `PersonSimulation.character_readiness` / `.needs_character_creation`,
  computed in `__init__` alongside the existing site/inventory/task loading,
  additive only.
- `get_character_creation_panel_model()` on `PersonSimulation`, following the
  existing panel-model convention consumed by `ui_manager.py`.
- A renderer banner in `person_renderer.py` surfaced only when
  `needs_character_creation` is true, so a sparse person is visibly flagged
  during play instead of silently pretending to be as fleshed out as Mara
  Voss.
- `tests/test_person_assets.py` covering the three tiers.
- `tools/render_person_readiness_scenario.py` — a deterministic screenshot
  tool (pattern: `tools/render_forest_shade_comparison.py`) rendering a
  minimal stub person against the authored lumber-site cook side by side,
  for visual review.

**Explicitly deferred (loose ends for future cycles):**
- The fixed 7-point engine itself is untouched — `needs_character_creation`
  is currently informational only, not yet gating or altering simulation
  behavior. A sparse person still gets the full lumber-shaped point set.
- No character-creation UI or procedural gap-filling exists yet — only
  detection. Section 4 above is the concept to build from next.
- `_task_for_point`'s point-id-keyed branches, the ontology writeback
  question, and the `person_psychology.py` extraction are all untouched.

### Cycle 2 — 2026-09-05: Site-less people spawn in a void, not the lumber site

**Scope.** Cycle 1's renders exposed the sharpest edge directly: a person
with no authored site data was still silently placed inside
`location_lumber_test_site` (Mara Voss's kitchen, walls, and coworkers)
because `PersonSimulation` defaulted `site_entity_id` to `TEST_SITE_ID`
whenever nothing else resolved. Per direction from this cycle's review,
the fix is not yet a generic placeholder room (that still implies a kind
of world we can't author correctly yet) — a site-less person now spawns in
an open, structureless void, since world generation isn't ready to place
them meaningfully.

**Shipped:**
- `PersonSimulation.site_entity_id` defaults to `None` instead of a hidden
  fallback to the lumber site; `TEST_SITE_ID` (now dead) was removed.
- New `in_void` flag, true whenever no `simulation_site` or
  `associated_locations`-with-`simulation_points` resolves. While in void,
  `site_entity`/`site_structures`/`wall_segments`/`site_people` all stay
  empty rather than inheriting another authored site's contents.
- `VOID_MAP_BOUNDS` (a large, structureless bounding box) replaces
  `TEST_MAP_BOUNDS` as the pre-resolution default, so an unauthored person
  doesn't inherit the lumber site's cramped geometry either, even before
  bounds are looked up.
- `PersonRenderer` skips drawing the floor/walls/terrain entirely when
  `in_void` is set, and shows a small "Unbound void -- no site authored
  yet" label, so the void reads as deliberately empty rather than a
  rendering bug.
- Tests: `test_site_less_person_spawns_in_void_not_the_lumber_test_site`
  and `test_authored_site_clears_void_state` in `test_person_simulation.py`.
- Reran `tools/render_person_readiness_scenario.py`; the sparse and empty
  stub screenshots now show the person's floating task points alone in
  darkness instead of standing in Mara Voss's barracks/kitchen/factory
  yard.

**Explicitly deferred (loose ends for future cycles):**
- The 7 fixed task points (bed/food/kitchen/job/target/lumber_dropoff/
  lumber_pickup) still exist unconditionally and still float at their
  hardcoded default positions inside the void -- including the two
  lumber-specific duty points, which are meaningless outside that one
  authored site. Generalizing this vocabulary (Section 3) is still future
  work; this cycle only stopped the *wrong* site's geometry from leaking
  in, it didn't yet give a void person a *correct* one.
- No transition path exists yet for a person who starts in the void and is
  later authored/placed into a real site mid-simulation.

#### Refinement: rudimentary asset selector and placer

Per direction from this cycle's review, the void is meant to become the
general test area for human behavior, and needs a first, rudimentary asset
selector/placer -- deliberately small now, but intended to generalize later
into the placer building and engineering menus will also need.

**Shipped:**
- `simulations/person/person_assets.py:placeable_asset_catalog()` -- a pure
  function deriving the placeable catalog from `TEST_POINT_DEFINITIONS`,
  keeping the two lumber duty points (no `tags`, by the existing authoring
  convention) out of the player-facing palette rather than hand-duplicating
  a second list that could drift from the source definitions.
- `PersonSimulation.asset_palette` / `.placement_mode` /
  `.placement_selected_asset_id`, plus `select_asset_for_placement()`,
  `cancel_asset_placement()`, and `place_selected_asset()`. Placement is
  gated to `in_void` for now -- an authored site's hand-placed, wall-aware
  geometry stays untouched until placement understands walls/collision.
- Number keys 1-9 select a palette entry (via the existing
  `consumes_global_keydown` / `handle_event` duck-typed hooks
  `app/input_router.py` already dispatches through, the same mechanism
  species sim uses for its forest diagnostic key); Escape or a right-click
  cancels placement; a left-click while placing relocates (or creates) that
  point at the clicked world position and tags it `"placed": True`.
- `PersonRenderer._draw_asset_palette()` -- a small always-visible list of
  the palette (highlighting the active selection) plus a "click to place"
  hint while placement is active, shown only in the void.
- 8 new tests across `test_person_assets.py` / `test_person_simulation.py`
  (catalog filtering, void gating, keydown selection, click placement,
  cancel-by-Escape, cancel-by-right-click). All 60 scoped person/site tests
  pass.
- Reran `tools/render_person_readiness_scenario.py` with a placement
  walkthrough: selecting "Ingredients" and clicking a point far from the
  default cluster visibly relocates it there.

**Explicitly deferred (loose ends for future cycles):**
- The void's 7 points still exist by default before any placement --
  placing only repositions an already-existing point, it doesn't yet start
  the void truly blank. Making the void start empty and requiring the
  player to place everything (matching "select the assets ... and place
  them" as literally as possible) is a materially bigger change: most of
  `test_person_simulation.py`'s suite shares one fixture that relies on the
  current default population existing without an authored site, so it
  would need deliberate rework, not just an incidental side effect of this
  feature. Flagged here rather than decided unilaterally.
- No UI-manager-integrated clickable palette exists yet -- selection is
  keyboard-only (1-9) and the palette is renderer-drawn text, not a real
  panel with clickable icons. Sharing this with the eventual building and
  engineering menus will need a proper panel-model + click-handling pass
  once those menus exist to actually need it.
- Placement has no collision/validity checking (can drop a point anywhere,
  including atop another point) and only supports the 5 already-implemented
  point kinds -- there is no way yet to place something that doesn't
  already have engine behavior behind it.

### Cycle 3 — 2026-09-05: Character editor entry points

**Scope.** Section 4's character-creation concept assumed we'd need to
build field-editing UI from scratch. Investigation before writing any code
found that isn't true: the floating entity card's edit mode
(`ui/card.py`/`ui/knowledge_canvas_controller.py`) is already a full,
schema-driven editor that can edit every authored field on a person,
including personality, wishes, goals, and knowledge_records -- it's the
same generic editor the repository browser uses for every entity type, not
something built for people specifically. So this cycle is about entry
points into that existing editor, not new editing widgets.

Two entry points were requested: from within a running `PersonSimulation`,
and from the floating card's toolbelt. A design fork came up for the
toolbelt button specifically: in this codebase a card's toolbelt only
renders once the card is already in edit mode (`_uses_toolbelt`,
`ui/card.py:1178`, meant for meta-actions on an entity being actively
edited, e.g. the existing add-parent/add-child tools). Given that
constraint, the toolbelt button can't be "the thing that turns edit mode
on" without a gating change; the direction taken was to keep it as a
same-conventions, edit-mode-only convenience: jump straight to the tab
holding the character-relevant fields, skipping past Identity/
Classification.

**Shipped:**
- `PersonSimulation.open_character_editor()` -- opens the existing floating
  card in edit mode on the controlled person (`open_entity_card(...,
  mode="edit")`), distinct from `open_person_inspector()`'s narrow name/
  notes-only path. A new "Character Editor" button sits in the person-sim
  button column (`ui/ui_manager.py`, below Direct Control), dispatched via
  `app/navigation_controller.py` the same way `open_person_inspector`
  already is.
- A `person_character_editor` toolbelt tool (`ui/card.py`'s
  `match={"person","people"}` block) with a new `kind:
  "jump_to_character_tab"`, handled self-contained in
  `ui/knowledge_canvas_controller.py` (alongside the existing
  `color_picker`/`plant_asset_creator` kinds) by calling
  `card_view.set_active_subtab("simulation", "data")` -- confirmed via
  `ui/card_simulation.py` that `_has_simulation_fields()` always returns
  True for person cards and the "data" subtab is exactly the generic
  field-dump view where big_five/wishes/knowledge_records actually render,
  even for an "empty"-tier person with none of them authored yet.
  Deliberately self-contained (`kind`, not `action_id`) so it works
  identically whether the card was opened from the modal repository
  browser or as a floating card from a running simulation -- the
  `action_id` dict-action path has a known gap where the floating-card
  input handler (`app/input_router.py:_handle_floating_card_input`)
  discards dict results, which this sidesteps entirely rather than
  patching.
- 7 new tests (`tests/test_person_character_editor_toolbelt.py`,
  `tests/test_person_simulation.py`) plus a manual render confirming the
  new button doesn't overlap the panel icon column it displaced downward.
  Full scoped run (person/site/card/toolbelt suites, 171 tests) green.

**Explicitly deferred (loose ends for future cycles):**
- The editor surface is still the fully generic, un-curated schema editor
  -- every raw field on the person entity, not a purpose-built layout
  around the 6 readiness categories. Section 4's "bespoke curated panel"
  option was explicitly declined for now in favor of this smaller, reuse-
  first slice; worth revisiting once/if the generic editor proves too
  noisy for actually authoring a character.
- The toolbelt button still requires the card to already be in edit mode
  to appear at all -- there's still no single click that takes an
  inspect-mode card straight into character editing.
- Neither entry point does anything with the readiness/character-creation
  system built in Cycles 1-2 -- there's no indicator on the button, panel,
  or toolbelt tool showing *why* editing is needed (the missing-category
  list `get_character_creation_panel_model()` already computes) or
  confirming once a person has crossed into the "authored" tier.
