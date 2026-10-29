# Collection simulation (concept v001)

Status: concept, 2026-10-28. Nothing implemented. Answers the layer
overview's open question 5 (`docs/conceptual_layer_overview_v007.txt`):
"Should collections have formal membership fields, prose-only references,
generated query membership, or all three?"

## 1. Owner's direction (2026-10-28)

Use collections to build dynamic collections of what is available in a
context. For this debug session: a debug collection of test spacecraft,
which the transfer windows check. In play the same mechanism answers
questions such as "independent of faction, what craft could you expect to
meet along this route?" or "which craft does the player own that can make
this journey?". Work on the collection simulation as a whole, so it can be
used.

## 2. What exists

- **`collections` dataset** (schema `schema_collections`, parent
  `entity_core`): encyclopedic hubs with explicit references (`includes`,
  `featured_entries`, `family_members`, `related`), a `collection_class`
  with suggestions (`family`, `biosphere_species_roster`,
  `localized_biosphere_species_roster`), and species-roster buckets. Eight
  entries, among them `coll_armed_combat_tugs_of_the_planetary_period`.
  No launch mode, no workspace.
- **Plant collections** (dataset `biospheres`, `collection_role:
  plant_collection`, 33 entries incl. the 31 Koppen-zone collections): a
  named list of species, each with a rarity (dominant, common, occasional,
  rare) and its source. A biome flora (`collection_role: biome_flora`, 8)
  is assigned one through `plant_collection` and follows it when it is
  edited (`simulations/biosphere/flora.py`). This is already a weighted,
  assignable collection that a simulation reads.
- **Logistics** (`docs/logistics_simulation_concept_v001.md`): links with
  requirements, design profiles, and the transfer panel, which today checks
  every spacecraft design in the ontology (24, of which 23 have no figures).

## 3. The model: one collection, three ways in, a context to read it in

A collection is a set of members, each with an optional commonness:

- **Listed members**: `includes`, as now, plus a commonness per member on
  the plant collections' scale (dominant, common, occasional, rare).
- **Generated members**: a `membership_rule`, a small structured filter
  over the ontology: which dataset or type, which class values, which tags,
  which fields must be present. Evaluated when read, never stored as
  members: the members a rule yields are a cache (rule 1), so a new test
  craft tagged right joins without anyone editing the collection.
- **Nested collections**: a collection listed in `includes` contributes its
  members (union), so "test craft" and "player fleet" can be combined.

Reading a collection always happens **in a context** supplied by the
asking simulation: year (availability by `start_year`/`end_year`), faction
or none, owner, location, and a link with requirements. The context is not
stored on the collection; it narrows and annotates the members:

| question | collection | context |
|---|---|---|
| debug: which test craft can fly this window? | debug test craft (rule: spacecraft tagged "test craft") | the window's link |
| what craft could you meet on this route, any faction? | spacecraft designs in service (rule) | year, the route's links |
| which of the player's craft can make this journey? | player fleet (owner rule) | the journey's links |
| what grows here? | a Koppen-zone plant collection | the biome |

The result is a **collection view**: members, each with its commonness, how
it got in (listed, rule, nested), and the context's verdict on it (for
logistics: eligible, or the shortfalls from `capabilities.shortfalls`).

## 4. The collection simulation

A workspace launched from a collection card (a new "Collection" launch
affordance), and an API the other simulations call.

- **Members list**: each member with commonness and source; nested
  collections fold open.
- **Context bar**: year, faction, owner, and a link to check against (for
  spacecraft: pick a transfer window from a body).
- **Check column**: the context's verdict per member, so the debug
  collection shows at a glance which test craft fly which window and why the
  others do not.
- **Editing**: add or remove listed members, set commonness, edit the rule
  (class, tags, required fields). Changes are staged and become durable when
  the user saves the ontology (rule 2).
- **API**: `view(collection, context)` for the transfer panel now, for the
  traffic sampler later (it draws from a collection by commonness), and for
  floras once plant collections go through it.

The space view gets an **active collection** for its transfer panel: the
debug test-craft collection while debugging, later whatever the player's
context supplies (their fleet, or the traffic of a route).

## 5. Debug collection and more test craft

- `coll_debug_test_spacecraft`: rule "vehicles of a spacecraft class tagged
  `test craft`", so every authored test craft joins by itself.
- Two more test craft beside Pathfinder, so the check has something to sort:
  an orbital tug (plenty of delta-v for its size, orbital shielding only,
  short life support: fails every interplanetary window on shielding and life
  support) and a long-range craft (high specific impulse, long life support:
  reaches the outer planets Pathfinder cannot).

## 6. Plant collections

Two ways, to be decided:

- **Read them through the same API now, move them later** (recommended):
  an adapter reads a `plant_collection` as a collection view; the Biosphere
  is untouched.
- **Move them into `collections` now** with `collection_class:
  plant_collection`: one home for all collections, but an authored-content
  migration of 33 entities and every flora's reference, done by an author
  script with care.

## 7. Slices

| slice | what | done when |
|---|---|---|
| C1 model and API | `simulations/collection/`: listed + rule + nested members, commonness, context, view; schema fields `membership_rule` and per-member commonness through an author script | tests on rules, nesting, context narrowing |
| C2 debug collection | the collection and two more test craft authored; the transfer panel reads the active collection | real-app check: the panel sorts three test craft |
| C3 collection workspace | launch from the card; members, context bar, check column; staged editing | real-app walkthrough |
| C4 plant collections | through the API (or moved) | floras unchanged in behaviour |
| C5 traffic | logistics L3 draws sampled traffic from a collection by commonness | the same stretch shows the same craft |

## 9. Progress

**2026-10-28: C1 and C2 built.**

- `simulations/collection/collections.py` (`tests/test_collections.py`):
  `members()` gives listed, nested and generated members once each with
  their weights and sources (a collection that lists itself through another
  stops); `rule_matches()` reads `datasets`, `field_values`, `tags_all`,
  `tags_any`, `fields_present`; `view()` reads a collection in a `Context`
  (year: members with no dates count as available; `check`: a verdict per
  member). Plant collections go through `members()` with rarity turned into
  the Biosphere's ground share.
- `tools/author_collection_membership.py`: `membership_rule` and
  `member_weights` on `schema_collections`, the class suggestion
  `vehicle_roster`, and `coll_debug_test_spacecraft` (rule: vehicles of a
  spacecraft class tagged `test craft`); backup in
  `artifacts/collection_membership/`, OWL exported.
- `tools/create_test_craft_fleet.py`: Shuttler (orbital tug, 6.35 km/s,
  orbital shielding, 30 days) and Longreach (system spacecraft, 13.19 km/s,
  deep-space shielding, 4 years); backup in `artifacts/test_craft_fleet/`,
  OWL exported. Both join the debug collection by its rule.
- The transfer panel reads the space view's `transfer_collection_id`
  (default the debug collection) in the view's year, and says so: "Checked:
  Debug Test Spacecraft, 3 craft". Long destination lists wrap.

Earth selected in the real app, year 2400: Mars and Venus 2 craft
(Pathfinder, Longreach), Ceres, Mercury, Vesta, Pallas and Hygiea 1 craft
(Longreach), the outer planets and far dwarf planets none (Longreach lacks
the delta-v, or the life support for flights of 16 to 174 years); Shuttler
nowhere (orbital shielding). The wrap was added after that run and is
covered by a test, not yet seen in the app.

Next: C3, the collection workspace.

## 8. Decisions (owner, 2026-10-28)

- **Rule format**: a structured filter.
- **Commonness**: numeric weights, not the four words. The plant adapter
  turns a rarity into the share of suitable ground the Biosphere already
  uses for it (dominant 1.0, common 0.6, occasional 0.2, rare 0.05).
- **Plant collections**: read through the API now, moved later.
- **Test craft**: author the orbital tug and the long-range craft.
