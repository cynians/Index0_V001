# Person Simulation — Concept & Decoupling Roadmap

The first DNA-backed outward-appearance editor slice is documented in
[Person genetic DNA v001](person_genetic_dna_v001.md).

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

## 4. Character creation — concept

The player-authored strategy below is built: the stepped Person Editor
(Cycle 9). It writes on Save, so the open question at the end of this
section is settled for it: creation is durable, staged until Save. The
procedural strategy is still only the seeded birth draws.

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

## 5. Need satisfaction: need tags and personal knowledge (owner, 2026-10-28)

Replaces the fixed point vocabulary (Section 3, first two bullets) as the
way a person finds something for a need. Not built yet; slices below.

**The behaviour wanted.** A hungry person eats the chips bag they carry and
is still hungry, checks the vending machine they know and finds it empty,
gets a fish from the fishmonger, is robbed of it on the way, and walks to a
place where they know berries grow. Nothing in that chain is scripted: it
falls out of tags, knowledge and one choose-act-learn loop.

**Decisions.**

| Topic | Decision |
|---|---|
| Recognising a satisfier | A loose tag system: items, installed items and components, people, species and places can all be recognised as having to do with a need. |
| Where knowledge lives | One knowledge collection per full person. It includes shared collections (culture, job training, local lore) as nested members, so knowledge is inherited from them. |
| Beliefs learned in a run | Staged during the run, written back to the person's knowledge collection on explicit Save. |
| Money | Left out of the first loop. The machine and the fishmonger give food freely; the theft takes carried food. Money arrives with the market work. |

**Need tags.** A tag says what a thing is for, not how much it gives.

- Tag entities with `tag_class: need`, each naming the need it serves.
  Tags may have parent tags (Snack -> Food, Fish -> Food, Berries -> Food).
- A tag sits on the thing that is consumed or used, on its class (item
  category chain, species, job), and instances inherit it. Explicit `tags`
  on an instance add to that.
- A holder becomes relevant through a relation, and the relation picks the
  action:

  | Relation | Field | Example | Action |
  |---|---|---|---|
  | is | the thing's own tags, its categories' tags, `food_satiation` | chips bag | use |
  | carries | `inventory_items` | a pantry, a person's pocket | take |
  | dispenses | `dispenses_items` on an item | vending machine | operate |
  | gives | `hands_out_items` on a job, reached through `is_employed_as` | fishmonger | ask |
  | bears | `harvest_yields` on a species | crowberry shrub | harvest |
  | produces | `produced_items` on a producer, reached through a place's `operated_by` | kitchen | make (cook with a known recipe) |

- A holder class may carry a need tag itself as general knowledge
  ("vending machines have food") without anyone knowing the contents.
- Amount comes from the entity's fields (`food_satiation`) or from
  experience, never from the tag.
- Resolution stays inspectable (layer overview section 8): every resolved
  tag reports whether it is local, inherited (and from where) or inferred.
- The `wish_type` values already matched against point tags ("Eating
  Comfort", "Rest", "Social Place") join the same vocabulary.

**Knowledge is belief, not truth.** A member record in a person's knowledge
collection can hold:

- where the thing is: place, route or direction (the existing navigation
  knowledge fields move here);
- the state believed ("stocked", "ripe") and when it was last checked;
- the source: seen, told by a person, or inherited from a shared collection;
- confidence;
- what it did last time, per need ("chips: food +15").

The world holds the truth (machine stock, the fishmonger's stock, the
bush's fruit). A person acts on belief and corrects it on arrival.

**The loop, the same for every need.**

1. Choose: collect every known option tagged for the pressing need, or
   holding something that is. Score it by expected satisfaction x
   confidence, minus distance, risk and effort, weighed by personality.
2. Act: travel with the existing knowledge-bounded wayfinding, then do the
   relation's action.
3. Learn: compare truth with belief and update the record (empty as of
   when, how filling it was).
4. If the need is still pressing, choose again. Options that became
   impossible (empty, lost, unreachable) score down by their new belief.

Rest (bed, bench, haystack) and belonging (people) use the same loop.

**Slices.**

| # | Slice | Proves |
|---|---|---|
| N1 | Need tag vocabulary and an explaining resolver (pure module, tests). Author a chips bag, a vending machine, a fishmonger with a job that gives fish, a berry species with an edible part. | Four kinds of thing are recognised as food, and each says why |
| N2 | Knowledge collection per person: member records, nested shared collections, a reader that yields known options with believed place and state. Move the authored `knowledge_records` of the lab people into their collections. | A person knows options it was not told directly, through its culture or job |
| N3 | The loop in Person Sim, replacing the hardcoded food and kitchen branches: four actions, belief updates, staged write-back on Save, the owner's example as a lab run in the void with a scripted theft. | The example plays out unscripted |

**Agreed with the collection session (2026-10-28).** Beliefs are
`member_records` rows, `{member: id, ...}`, beside `member_weights`.
`members()` and `view()` read membership only from `includes`, nested
collections and `membership_rule`, so every believed-about member is listed
in `includes` too. The collection workspace (C3) will keep
`member_records` untouched when it stages an entity.

## 6. Cycle log

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

### Cycle 4 — 2026-10-28: N1, need tags and the explaining resolver

**Scope.** Slice N1 of section 5: four kinds of thing recognised as food,
each saying why, from ontology data alone. Person Sim's behaviour is
unchanged; the loop is N3.

**Shipped:**
- `world/need_tags.py`: the need tag index (tag entities with
  `tag_class: need`, need named by `serves_need` or inherited through
  `parents`), `own_need_links` (own tags, category-chain tags, inferred from
  `food_satiation`), `need_links` (plus what the entity carries, dispenses,
  gives through its job, or bears), `explain` and `need_summary`. Tag
  strings match tag entities the way cards match them. It lives in `world/`
  because City Sim's light residents will need the same answer.
- Entity cards draw one derived chip per need after the tags, e.g.
  "Food: dispenses Chips Bag" (`EntityCard._need_summary`, read-only, not
  editable, recorded in `need_chip_hitboxes` for a later hover with the
  full `explain` lines). Render: `artifacts/need_tags_n1/card_need_chips.png`.
- Schema fields: `serves_need` on tags, `dispenses_items` on items
  (`SCHEMA_ITEM_FIELDS`), `hands_out_items` on jobs (`JOB_FIELDS`),
  `harvest_yields` on species (stored species schema, not
  `PLANT_TRAIT_SCHEMA_FIELDS`, so it is neither inherited by relatives nor
  shown as a plant trait).
- Store content, written by `tools/author_need_tags_model.py` (dry run by
  default): tags Food, Snack, Fish, Berries; Food on the Foodstuff
  category; Chips Bag, Smoked Fish, Crowberries, Vending Machine;
  job Fishmonger held by Ivo Brann (`person_test_fishmonger`);
  `harvest_yields` on Black Crowberry (`spec_empetrum_nigrum`, a designed
  dwarf shrub; the lingonberry entity is an undesigned stub). Existing
  entities were merged over their full stored dict.
- `tests/test_need_tags.py` (12, including the card chip).

**Found on the way:** every existing item under Foodstuff (Simple Cooked
Meal, Meal Ingredients) and the lab pantry that holds them now read as food
through the one category tag, with no edits to them.

**Loose ends:**
- The `is` relation's action is the generic "use"; the need's own verb
  (eat, sleep) belongs to N3's actions.
- `serves` (a canteen) is not built; it would come from a place's
  producers' outputs.
- Only Food has tags; the other five needs have none yet.
- Seasons and ripeness are not considered: a shrub bears berries all year.

### Cycle 5 — 2026-10-28: N2, a knowledge collection per person

**Scope.** Slice N2 of section 5: knowledge moves from fields on the person
into one collection per person that nests shared collections, and Person
Sim reads everything it knows through one reader.

**Shipped:**
- `simulations/person/person_knowledge.py`: `known_entities` walks the
  person's `knowledge_collection` and every collection nested in it,
  nearest first and each once, merging `member_records` field by field
  (the person's own belief over a shared one) and keeping the collections
  each belief came from; rule-generated members come through `members()`
  from the collection package. `knowledge_records` hands Person Sim plain
  records, naming a shared collection as the source when the belief came
  from one.
- Person Sim reads knowledge, wayfinding knowledge (its own and that of
  the person it asks) and familiarity through the reader. The
  `known_entities` field is gone; relation-derived knowledge (employer,
  associated places, kin) is unchanged.
- Knowledge panel: a **Food sources** group lists what the person knows of
  that serves food, with the most direct reason, believed place and state,
  and source ("bears Crowberries at Western Wood Lot · Lumber Camp Lore");
  plant species now group under **Nature** instead of People, and species
  show their common name. Render:
  `artifacts/person_knowledge_n2/mara_knowledge_panel.png`.
- Schema: `member_records` on collections, class suggestions
  `personal_knowledge` and `shared_knowledge`; `knowledge_collection` on
  the person replaces `knowledge_records` and `known_entities`.
- Store content, written by `tools/author_person_knowledge_model.py` (dry
  run by default): shared Lumber Camp Lore (site, woodlot direction, the
  crowberry shrub believed to grow at the woodlot) and Site Cook Training
  (recipe, kitchen, pantry); one personal collection each for Mara Voss,
  Elias Kern, Nia Vale and Tomas Rhee holding their former records
  unchanged (checked equal before the write). The old fields were removed
  from the four people. `tools/author_person_food_ownership_model.py` now
  references the collections, so re-running it cannot bring the old field
  back.
- Tests: `tests/test_person_knowledge.py` (6, including the panel row);
  person, lab and tool fixtures moved to collections; a stale assertion in
  `tests/test_author_person_psychology_model.py` (`wishes` has been an
  `entity_list` since the wish registry) fixed. Lab rerun: recipe
  knowledge, woodlot wayfinding and asking Nia unchanged.

**Loose ends:**
- Shared collections are nested by hand in each person's `includes`; a
  job or culture naming its own knowledge collection, joined
  automatically, would save that.
- Beliefs are read-only so far. Writing what a person learns during a run
  (staged, on Save) is N3, with the loop that learns it.
- `checked_at` has no unit yet; it gets one when N3 first writes it.

### Cycle 6 — 2026-10-28: N3, the choose-act-learn loop for food

**Scope.** Slice N3 of section 5: hunger is met by searching what the
person knows instead of the hardcoded food and kitchen branches, with
beliefs learned on the way and staged until saved. The owner's example
plays out unscripted except for the theft.

**Shipped (`simulations/person/person_simulation.py`):**
- **Spots** are the truth of a run: every test point with an asset (its
  stock is the point's container inventory), every other resident of the
  site (their `inventory_items`), and things put into the run with
  `place_thing(entity, position, stock=...)`.
- **Options.** `_food_options` looks at food the person carries and at
  every entity they know, plus the places of their own site, and turns each
  need link into a priced plan: take, operate, ask, harvest, or cook (get
  the recipe's inputs from a known holder, cook at the place with a known
  recipe, eat). Each plan is rated by expected food per second:
  availability x food / (walking + action seconds), where availability is
  2 % for a source believed empty or not found and 50-100 % by familiarity
  otherwise, and the food is what the item did last time (`experienced`),
  else its `food_satiation`. Food in hand therefore beats a better meal far
  away, and a known-empty source drops out.
- **One food task**, `_food_task`, carries the best plan; the task panel's
  explanation says what was chosen and over what ("Chose Get Chips Bag
  from Vending Machine: food: dispenses Chips Bag, tagged Snack (Snack >
  Food); about 15 food in 6 s, 85% likely; over Ask Ivo Brann for Smoked
  Fish, ..."). Hunger pressure scoring reads `task["need"]`, not a point
  id. A click or assignment on a point whose `need` is food builds the best
  plan that uses that point, so ordering the pantry still cooks a meal.
- **Steps** are generic (take, operate, ask, harvest, cook, eat) and may
  target a point, a spot, or where the person stands. A failed step says
  why ("Vending Machine has no Chips Bag left", "no Smoked Fish held",
  "no Black Crowberry found here").
- **Learning.** Taking from a source records `believed_state` empty or
  stocked; failing records empty or not found; eating records
  `experienced: {food: n}` on the item. Each belief carries `checked_at:
  {year, second}`, the second counted from the start of the run. The
  beliefs overlay the knowledge collection while the run lasts and show in
  the Knowledge panel ("gives Smoked Fish, empty").
- **Save.** A **Save Knowledge** button in the person sim column (enabled
  while anything is unsaved) calls `save_learned_knowledge`, which merges
  the beliefs into the person's knowledge collection, creating one if the
  person has none.
- `lose_item` lets an outside event take what the person carries.
- `need_tags.py`: the **produces** relation (`produced_items`, reached
  through a place's `operated_by`), action "make". The kitchen point no
  longer names its producer and recipe; both come from the place and the
  person's knowledge.
- Placed things are drawn in the person view as labelled markers.

**Checks.** `tests/test_person_need_loop.py` plays the owner's example
(chips eaten, machine empty, fish taken by a thief, crowberries harvested
until fed) and the save. Lab checkpoints `14_need_loop_machine_empty.png`
and `15_need_loop_fed.png` play it on the authored N1 content of the active
ontology; the kitchen workflow, wayfinding and site checkpoints are
unchanged. Test and lab kitchen fixtures gained the `operated_by` and
`produced_items` links the store's kitchen already has.

**Loose ends:**
- Only food goes through the loop; rest, leisure and work still use the
  bed, target and job points. Belonging still has no satisfier.
- Places of the person's own site count as known without being in the
  knowledge collection, so the void's default pantry and kitchen are
  always seen.
- Availability never recovers with time: a machine seen empty stays at 2 %
  until checked again. A refill expectation would need a time unit, which
  `checked_at` now has.
- There is no risk or social cost yet: asking a stranger, a plant's
  ripeness, or a source on the far side of danger all price the same.
- Residents of a site run as full agents learn too, but only the controlled
  person has a Save button.

### Cycle 7 — 2026-10-28: rest and belonging through the loop

**Scope.** The choose-act-learn loop of Cycle 6 serves rest and belonging
as well as food. Leisure and work still use the target and job points.

**Shipped:**
- `need_tags.py` reads needs off a thing's fields when no tag names them:
  `food_satiation` (food), `rest_quality` (rest), and any person is
  company (belonging; "is a person"). Person cards now show
  "Belonging: company".
- `person_simulation.py`: the loop is need-generic (`_need_options`,
  `_need_task`, `_priced_option`, `LOOP_NEEDS` with each need's pressure
  label, weight, urgency exponent and Maslow tier). Rest: use a thing
  where it stands, or what a place keeps ("Rest at Worker Barracks" with
  its beds), gaining 62 x `rest_quality`; the remembered gain becomes
  `experienced: {rest: n}`. Belonging: spend time with someone the person
  knows or lives beside, gaining 40 x closeness, where closeness is the
  mean of familiarity and interest; each visit raises familiarity by 0.05,
  so the people one sees grow closer. Residents of the person's own site
  count as known ("lives here", familiarity 0.5, interest 0.4); a person
  not where they were believed to be is learned as "not found". The old
  bed branch is gone: the void's bed point is an `item_bed`, and a point's
  `need` (food or rest) builds the best plan that uses it. Belonging asks
  for company below 55.
- Knowledge panel: a **Places to rest** group beside Food sources.
- Store content (`tools/author_need_tags_model.py`): tags Rest, Bed, Seat;
  items Bed (`rest_quality` 1.0) and Bench (0.35); four beds in the lumber
  site's barracks (also in `tools/author_person_food_ownership_model.py`,
  which writes that record whole). `rest_quality` on the item schema.
- Checks: `tests/test_person_need_loop.py` (the bed 13 m away beats a
  bench 2 m away; an old friend 20 m away beats a new neighbour 3 m away);
  lab checkpoint `16_rest_and_company.png` (Mara rests in the barracks,
  then visits Nia twice).

**Loose ends:**
- Talking is one-sided: the other person's belonging and task are not
  touched, and they do not walk.
- A visit always succeeds if the person is there; mood, relationship
  strain or an unwelcome visit are not modelled.
- Rest has no sleep cycle or time of day; a bed rest is 5 seconds.
- Safety still has no satisfier of its own beyond the small boost a rest
  gives.

### Cycle 8 — 2026-10-28: the task panel as a goal tree

**Scope.** The task panel's right column ("Allocation & history", a flat
list of the last five decisions) becomes **Goals & attempts**, grouped the
way the owner sketched: a goal, what was tried, what is happening now,
what comes next.

**Shipped:**
- `PersonSimulation.goal_episodes`, kept by `_track_goal` from every
  recorded decision: one episode per pursuit of a need or duty, holding its
  attempts (done with what it gave, "food 20 to 35"; failed with why, and
  at which step). A need's episode stays open until a completed attempt
  lifts the need over its threshold (`NEED_THRESHOLDS`, now also the
  thresholds that ask for a task); a duty's closes when it ends.
- `get_task_panel_model()["goals"]`: current goals (the active one with
  its current step, progress "step 1 of 2, walking, 49 m to go", and the
  steps still to come; an open goal between tasks shows its queued plan as
  next), up next (other queued goals with their pressure), earlier
  (finished goals with their last attempt and number of tries).
- `UIManager._draw_goal_tree`: the tree, with drawn markers (done, failed,
  current, next), pressures on the right, details indented beneath.
  Lab checkpoint `14_need_loop_machine_empty.png` is now taken on the way
  to the fishmonger and shows the owner's example as a tree.
- `tests/test_person_need_loop.py`: the goal model mid-story.

**Loose ends:** the decision explanations that the old list showed are
now only on the left (current decision); the earlier ones are not shown
anywhere in the panel.

### Cycle 9 — 2026-10-28: the Person Editor

**Owner's ask.** A person editor holding what already exists for people:
make a person, choose their birth place and year, then genetics, then
personality.

**Shipped:**
- `simulations/person/person_editor.py`: the editor as steps, Person (name,
  sex) > Birth (year, place) > Genetics (the I0DNA1 string: skin tone, six
  body loci, Reroll genome; clothing worn over it) > Personality > Life
  (home, job, workplace, shared knowledge collections) > Review. Every step
  edits one draft of the person entity; `save_plan` says what Save writes:
  a new person whole (and a personal knowledge collection if they share
  any), a stored person only their changed fields (and their collection's
  shared includes, keeping everything else it includes).
- Personality step: the five axes as bars (population, birth or authored
  baseline, the combined distribution, the person's words at their measured
  positions), - and + to set a birth mean by hand (authored
  `big_five_<axis>`), "birth" to drop it, Reroll birth. The word list
  filters by axis and sorts by position on it, so the measured psychTools
  places read as a ranking; chosen words' exclusions are named.
- `birth_seed` (new person field): the birth draws come from it, else from
  the id (`world/personality.birth_seed`). A new person gets a random seed
  at creation, so typing their name does not redraw their personality.
  `birth_location` (new person field, entity -> locations); the birth
  year is `start_year`. Both in the person schema via
  `tools/author_person_genetics_model.py` (written to the store).
- `world/place_tree.py`: locations and cities as a tree of places to be
  born or live in, without geologic units, material covers, deposits,
  orbital space or stars (a planet hangs from its star system). Browsed by
  breadcrumbs or searched; a place's start/end years are checked against
  the birth year and warned about, not refused (the repository's Berlin
  ends in 2356).
- Entry points: "New person born here" on every place's card (not on star
  systems), opening a "New Person" tab
  (`NavigationController.launch_new_person_tab`); "New person" in the
  editor itself; "Person Editor" on a person's card and in Person Sim as
  before. Person Sim for a person made in the editor opens their own Person
  Sim tab, since the editor tab's runtime was loaded for nobody.
- `simulations/person/person_editor_view.py` draws it (replacing
  `PersonRenderer._draw_person_editor`'s single screen); typing goes to the
  focused field (name, year, place search, word search), the wheel scrolls
  the list under the pointer. The time strip is hidden in the editor.
- `tests/test_person_editor.py`; renders in `artifacts/person_editor_v001/`.

**Loose ends:** (parents: done in Cycle 10) sex does not reach the DNA or
the figure; wishes and goals are not in
Life; the new tab keeps the name "New Person" after Save; a job does not
bring its training collection on its own.

### Cycle 10 — 2026-10-28: parents, optional

**Owner's ask.** Parents next, but optional.

**Shipped:**
- A Parents step between Birth and Genetics: up to two people, from the
  `people` and `person` datasets, searched by name. Chosen ones are the
  people in the entity's `parents` (entity_core); anything else there (a
  family pop, a country) stays as it is. Each person in the list shows
  their years, their age at the birth, and what is odd: born after the
  child, younger than 12 at the birth, dead before it. These warn and
  never refuse.
- `person_genetics.inherit_person_dna`: each body locus lands around the
  parents' mean, scattered by `SEGREGATION_SD` 0.12 (my choice; the loci
  are hash bytes, not a measured population); skin tone the same on its
  three steps (light and deep parents give mostly medium); every reserved
  locus is copied from one parent or the other. With one parent the
  unknown one counts as the population mean. A parent without saved DNA
  gives the preview genome the editor shows for them (from their birth
  seed). The same parents and birth seed draw the same genome; Redraw
  from parents draws another.
- Choosing or dropping a parent draws the genome again from those left;
  with none left the genome stays. Skin tone and loci can be changed by
  hand afterwards. Genetics names where the genome came from.
- Tests: `InheritanceTests`, `ParentsStepTests` in
  `tests/test_person_editor.py`.

**Loose ends:** (the birth personality: done, see below) the parents' own
entities get no `offspring` entry; nothing yet stops a
loop (a person as their own grandparent).

**Then, same day: parents shape the birth personality** (owner: "Yes,
personality too"). `world/personality.personality` draws the birth mean on
each axis around the parents: each known parent pulls it by
HERITABILITY / 2 of their distance from the population mean, using their
whole personality (their words, and their own parents' pull, four
generations up, loops cut). `HERITABILITY` is 0.4, the share of Big Five
differences that runs in families in twin and family studies (Vukasovic
and Bratko 2015, meta-analysis), used as the child-on-midparent slope; it
is broad heritability standing in for the narrow one, so if anything it
pulls a little too hard. The spread narrows by what the parents explain
(two parents: 0.15 to 0.144). Effect size: two Kind parents move a child's
birth agreeableness from 0.50 to about 0.59. An authored axis ignores the
parents. The axis source reads "inherited"; the editor's bars mark each
parent's value with their initial. Applies in Person Sim too, to every
stored person whose `parents` name people (Alia and Jarem Habil now).
Tests: `InheritedBirthTests` in `tests/test_personality.py`.
