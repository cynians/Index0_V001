# Entity Field Overview — Item & Component

Version: v001
Date: 2026-09-07
Rendered reference: https://claude.ai/code/artifact/20792eba-d456-4ba1-a7ea-a04a7d52785a

> **Status — IMPLEMENTED 2026-09-07.** The four design decisions below shipped via
> `tools/author_item_component_model.py` (ontology migration, backup in
> `artifacts/item_component_model/`) plus the consumer/schema code changes. The
> "current schema" / "case in one look" / drift sections describe the **pre-merge**
> state and are kept for the record; the **As-built schema** section at the end is
> the live shape. Consolidating this into the next `conceptual_layer_overview`
> version (resolving open question #59) is still pending.

## Purpose

Part of a per-entity-class field audit series. Each document inventories what an
entity class's schema actually holds today, which fields are consumed by runtime
code versus display-only, and the inconsistencies a redesign would need to
resolve. The series exists to give a cross-class overview of how each entity
family is really used, so development can be aimed rather than speculative.

This first document covers `item` and `component`, whose schemas have drifted
into near-duplicates. The open design direction (see
`conceptual_layer_overview_v007.txt`, point 14 and §2A lines 89 & 119) is to make
`component` a special subclass of `item` rather than a parallel entity family.

- **Source:** SQLite quadstore (`.cache/ontology/*.quadstore.sqlite3`),
  cross-checked against `ontology/index0.owl`.
- **Population:** ~12 item entities, ~35 component entities.
- **Base:** both extend `entity_core`.

## What an item is

An **item** is any corporal thing that is not a building, vehicle, or human:
bottles, steel plates, mobile phones, spacecraft engines, tools, rations. It is a
discrete manufactured or natural object, distinct from `material` (the substance
layer beneath it) and from the host families (`vehicle`, `locations`/buildings,
`person`) that carry or operate items.

Items are grouped by category and may have **multiple category parents**. A mobile
phone is at once a `communication_good`, an `electronic_item`, and a
`consumer_good_tech`. The current schema does not support this — it carries a
single free-text `item_class` plus a flat `tags` list (see open questions).

A **component** is an item considered in its role as an installed functional part
of a larger system — the same object, seen from the "bolted in and doing a job"
angle rather than the "loose on a shelf" angle.

## The case in one look

Strip out the shared core and each side keeps a genuinely distinct tail. `item`
owns handling, ownership, food and inventory; `component` owns engineering
dimensions and functional-role vocabulary. The shared column is what a merged
base class would absorb wholesale.

| Item only (16) | Shared (8) | Component only (11) |
| --- | --- | --- |
| `component_equivalent` | `item_class` / `component_class` | `represented_item` |
| `produced_by` | `primary_material` | `functional_roles` |
| `uses_technology` | `secondary_materials` | `satisfies_categories` |
| `storage_modes` | `production_materials_needed` | `operational_groups` |
| `handling_notes` | `production_components_needed` | `subsystem_labels` |
| `default_state` | `production_items_needed` | `requires_technology` |
| `portable` | `descriptive_capabilities` | `maintenance_notes` |
| `placeable` | `install_contexts` | `dimension_length_m` |
| `installable` | | `dimension_height_m` |
| `install_contexts` | | `dimension_width_m` |
| `ownership_records` | | `mass_kg` |
| `consumable` | | `power_kw` |
| `food_energy_kcal` | | |
| `food_satiation` | | |
| `inventory_items` | | |
| `inventory_unit` | | |
| `stackable` | | |

`component_equivalent` and `represented_item` are a hand-maintained bidirectional
pointer between an item and "the same thing, installed" — the model already
assumes the two are facets of one object.

## Item schema

`schema_item` → dataset `items` · type `item` · id prefix `item_`

Every field is `optional`; only the three `entity_core` requireds
(`id`, `pretty_name`, `type`) must be present. Authored `item_class` values so
far: `industrial_good`, `machinery_module`, `storage_fixture`.

### Identity

| Field | Type | Notes |
| --- | --- | --- |
| `item_class` | string | Free text, no controlled vocabulary. |

### Materials

| Field | Type | Notes |
| --- | --- | --- |
| `primary_material` | entity → materials | e.g. `mat_stainless_steel` |
| `secondary_materials` | entity_list → materials | Often authored as an empty list. |

### Item ↔ component bridge

| Field | Type | Notes |
| --- | --- | --- |
| `component_equivalent` | entity → components | Points at the installed-form entity. Reciprocal of `component.represented_item`. |

### Production — section "Class Relations"

| Field | Type | Notes |
| --- | --- | --- |
| `production_materials_needed` | entity_list → materials | |
| `production_components_needed` | entity_list → components | |
| `production_items_needed` | entity_list → item | Target string is singular `item`. |
| `produced_by` | entity_list → faction | |
| `uses_technology` | entity_list → technology | Drift: vs `component.requires_technology`. |

### Handling & state

| Field | Type | Notes |
| --- | --- | --- |
| `storage_modes` | string_list | `stackable`, `palletizable`, `containerizable` |
| `handling_notes` | text | Drift: vs `component.maintenance_notes`. |
| `default_state` | string | Authored value: `loose` |
| `portable` | string | Authored as `"limited"`. Type unclear. |
| `placeable` | string | Authored as xsd:boolean. Type drift. |
| `installable` | string | Authored as xsd:boolean. Type drift. |
| `install_contexts` | string_list | `building`, `vehicle`, `site`, `station` |
| `descriptive_capabilities` | string_list | `fluid_transfer`, `structural_input`, … |

### Ownership

| Field | Type | Notes |
| --- | --- | --- |
| `ownership_records` | entity_list → ownerships | |

### Food

| Field | Type | Notes |
| --- | --- | --- |
| `consumable` | boolean | |
| `food_energy_kcal` | number | |
| `food_satiation` | number | |

### Inventory

| Field | Type | Notes |
| --- | --- | --- |
| `inventory_items` | object_list | Entries shaped `{item, quantity, unit}`. |
| `inventory_unit` | string | |
| `stackable` | boolean | Separate from `storage_modes` containing `"stackable"`. |

## entity_core (inherited base)

`schema_entity_core`. Present on every entity in the ontology, item and component
alike. `id`, `pretty_name`, `type` are required; the rest are optional.

### Identity

| Field | Type | Notes |
| --- | --- | --- |
| `id` | string | required |
| `pretty_name` | string | required |
| `type` | string | required |
| `name` | string | |
| `three_word_description` | string | |
| `wiki_entry` | text | |
| `entry_status` | string | e.g. `draft` |

### Card metadata

| Field | Type | Notes |
| --- | --- | --- |
| `card_color` | string | |
| `card_header_color` | string | |
| `wiki_field_colors` | dict | |
| `tags` | string_list | Load-bearing — see requirement resolver below. |

### Temporal

| Field | Type | Notes |
| --- | --- | --- |
| `start_year` | number | |
| `start_commentary` | text | |
| `end_year` | number | |
| `end_commentary` | text | |
| `temporal_periods` | object_list | |

### Relations

| Field | Type | Notes |
| --- | --- | --- |
| `parents` | entity_list → entity_core | |
| `related` | entity_list → entity_core | |
| `offspring` | object_list | Derived from `parents`. |

## Component schema

`schema_components` → dataset `components` · type `component` · id prefix `comp_`

Shares eight fields with `item`. What follows the shared group is what a component
adds: an engineering block and a functional-role vocabulary the item side never
grew.

### Shared with item

| Field | Type | Notes |
| --- | --- | --- |
| `component_class` | string | Mirrors `item_class`. |
| `primary_material` | entity → materials | |
| `secondary_materials` | entity_list → materials | |
| `production_materials_needed` | entity_list → materials | section "Class Relations" |
| `production_components_needed` | entity_list → components | section "Class Relations" |
| `production_items_needed` | entity_list → item | section "Class Relations" |
| `descriptive_capabilities` | string_list | |
| `install_contexts` | string_list | |

### Item ↔ component bridge

| Field | Type | Notes |
| --- | --- | --- |
| `represented_item` | entity → item | Reciprocal of `item.component_equivalent`. Hand-maintained pair. |

### Functional role vocabulary

| Field | Type | Notes |
| --- | --- | --- |
| `functional_roles` | string_list | `hinge_mount_support`, … |
| `satisfies_categories` | string_list | Feeds vehicle-design requirement matching. |
| `operational_groups` | string_list | |
| `subsystem_labels` | string_list | |
| `requires_technology` | entity_list → technology | Drift: vs `item.uses_technology`. |

### Engineering

| Field | Type | Notes |
| --- | --- | --- |
| `maintenance_notes` | text | Drift: vs `item.handling_notes`. |
| `dimension_length_m` | number | |
| `dimension_height_m` | number | |
| `dimension_width_m` | number | |
| `mass_kg` | number | |
| `power_kw` | number | |

## Component host

`schema_component_host`, injected in Python by `world/component_host.py`. Not a
dataset. A mix-in schema (extends `entity_core`) merged onto vehicles, stations,
buildings and sites so a host can carry components "without giving an entity a
second dataset identity." The same field set backs `schema_vehicle`.

| Field | Type | Section | Notes |
| --- | --- | --- | --- |
| `vehicle_class` | string | Engineering / Design | |
| `dimension_length_m` | number | Engineering / Design | |
| `dimension_width_m` | number | Engineering / Design | |
| `dimension_height_m` | number | Engineering / Design | |
| `component_catalog` | entity_list → components | Engineering / Components | The pool a host may draw from. |
| `installed_components` | object_list | Engineering / Components | Placed instances with layout data. |
| `interior_layout` | object_list | Engineering / Interior | |
| `operational_state` | dict | Engineering / Operations | |

## What the code actually reads

Most schema fields are display-only. These are the consumers that give `item` and
`component` behavioural meaning — and in every case the distinction between the
two is carried by *which slot an entity sits in*, not by any schema field.

| Consumer | Behaviour |
| --- | --- |
| `world/requirement_resolver.py` | `technology.required_item_tags` / `required_component_tags` are matched against the `tags` of whatever sits in `site.assigned_items` / `site.assigned_components`. Item vs component = which site field. |
| `simulations/person/person_simulation.py` | Reads `inventory_items` (`{item, quantity}`) on person & producer; matches a recipe's `required_components` against the producer's `assigned_components`. |
| `simulations/vehicle/vehicle_design.py` | Uses `component_class` (category hints), `component_catalog`, `installed_components`. Never touches `represented_item`. |
| `ui/card.py` | The `components` dataset gets a dedicated **Operational** tab; `items` uses the default tab order with **no** Operational tab. `_is_component_card()` also moves dimensions out of Overview. |
| `ui/card_production.py` | When building a product's requirement picklist it pulls both `component_equivalent` and `represented_item` as candidate "items" — already treating the pair as interchangeable. |

## Naming & type drift a merge must resolve

- **Technology link:** `item.uses_technology` vs `component.requires_technology` —
  same relation, two names.
- **Free-text notes:** `item.handling_notes` vs `component.maintenance_notes` —
  near-duplicates with different framing.
- **The bridge pointer:** `component_equivalent` ↔ `represented_item` — a
  bidirectional pair kept in sync by hand; collapses to nothing if the two become
  one class.
- **Boolean-ish strings:** `portable`, `placeable`, `installable` — typed
  `string` in schema; authored as a mix of `"limited"` and xsd:boolean
  `true`/`false`.
- **Target string:** `→ item` (singular) in `item` / `production` / `technology`
  / `locations`; `→ items` (plural) in `recipes` / `logistics`.
- **Dataset vs type name:** schema target `item`, dataset `items`, type `item` —
  the component side is consistently plural-dataset / singular-type; the item side
  mixes both.

## What the design already settles

Most of the "what is an item for" questions are answered across `text/tasks.txt`
and `conceptual_layer_overview_v007.txt`. The schema simply has not caught up.

| Question | Resolution | Source |
| --- | --- | --- |
| What kind of thing is an item? | A corporal thing that is not a building, vehicle, or human. Corporal (embodied) is a deliberate category, distinct from conceptual entities (designs, recipes, technologies, ideas). | user; concept §3 |
| What earns entity status? | Item *definitions* (types) are repository entities. Traded/stored *quantities* are runtime state. An *individual* becomes an entity only on player interaction or when a system needs it. | TASK-046 ("repository item definitions vs runtime traded quantities"); IM-015; concept §3, §14A.1 |
| Item vs material? | `material` is the raw material-science layer (substance, hazards, properties); `item` is the discrete stored object built from it. Material identity is explicitly "distinct from item and component identity." | TASK-208 |
| Item vs component? | `component` is the functional-installed-part layer over the same object — "functional parts for vehicles, stations, buildings, sites" — with an equivalence link back to the item. | TASK-210 |
| One base for a flint scraper and a fusion drive? | Yes — "a shared base representation for tools, goods, modules, fixtures, and similar object types." | TASK-209 |
| One item in many states, or many entities? | One item; `loose` / `placed` / `stored` / `installed` are *contexts* of the same definition, not separate entities. | TASK-209, TASK-217 |
| Does an item mean one thing across simulations? | One concept, many viewpoints. Simulation modes are "a viewpoint and scale over ontology facts," not separate data. | concept §1, §15, §27 |
| Where does an item's history live? | On the corporal entity as `activity_periods`-style episodes, promoted to standalone records only when an episode gains independent importance. | concept §3, §23 |

## Design decisions (2026-09-07) — decisions 1, 2, 4 SHIPPED; 3 deferred

The four previously-open questions, resolved. Decisions 1, 2 and 4 are
implemented (`tools/author_item_component_model.py` + code changes). Decision 3
(the actualization runtime) is a separate future project — `inventory_items`
already covers the "holding" layer.

### 1. Categories — multiple parent classes

`item_class` (one free-text string) is replaced by a multi-valued link to
**category entities**. An item may belong to several categories at once: a mobile
phone is a `communication_good`, an `electronic_item`, and a `consumer_good_tech`
simultaneously. Categories form their own shallow hierarchy (e.g.
`electronic_item` under `manufactured_good`). `tags` stays for cross-cutting,
non-taxonomic labels. (Concept §29 Q59, option "multiple ontology classes".)

### 2. Component is a subclass of item

Not a parallel family joined by a hand-maintained pointer. `component` becomes a
subclass of `item` that adds the engineering block (`dimension_*`, `mass_kg`,
`power_kw`) and the functional-role vocabulary (`functional_roles`,
`satisfies_categories`, `operational_groups`, `subsystem_labels`). Any item that
can be installed and performs a function when installed is a component.
`component_equivalent` and `represented_item` are **deleted** — there is one
entity.

### 3. Two layers of actualization: definition → holding → individual

- **Definition** — the repository entity for a *kind* of item ("Carrot", "Nokia
  3310"). Timeless; no quantity, no location.
- **Holding (cumulative)** — a quantity of a definition somewhere: a granary's
  200 carrots, 20 tons of grain in a silo, 40 phones in a crate. Stored as
  `{item, quantity, unit}` on the container/inventory (today's `inventory_items`).
  20 tons of grain never becomes 100 000 grain entities.
- **Individual (actualized)** — a specific instance split off from a holding when
  it is picked up, used, carried, installed, or otherwise becomes significant. A
  person takes 10 carrots → the granary holding drops to 190, the person gains a
  holding of 10. A phone stolen from the crate → crate holding −1, and that phone
  becomes a **singular item, ready for use**, with its own identity, condition,
  ownership and history.

Rules:

- The default on *use* is actualization into individual form.
- Actualizing decrements the source holding by exactly the amount taken; the two
  layers must always reconcile and never double-count (concept §14A.1).
- An individual with no accumulated state (a plain carrot returned to the bin)
  may dissolve back into a holding. An individual that has gained history,
  damage, ownership, or narrative weight stays an entity (concept §22 promotion
  pattern; §21 vehicle design-vs-individual).
- Bulk/fungible things (grain, ore, fuel) usually stay cumulative even in a
  person's inventory; discrete durable things (a phone, a rifle, an engine)
  actualize readily.

### 4. Schema drift — proposed normalisation

Suggested, for review.

| Now | Proposed |
| --- | --- |
| `item.uses_technology` + `component.requires_technology` | one `requires_technology` on the base = tech needed to operate/support it; production-time tech stays in the recipe / production layer |
| `item.handling_notes` + `component.maintenance_notes` | keep both, split by layer: `handling_notes` on the base (storage / transport), `maintenance_notes` on the component subclass (upkeep while installed) — no longer drift once subclassed |
| `component_equivalent` ↔ `represented_item` | **deleted** (one entity after the merge) |
| `installable` (string / bool) | **dropped** — derived from `install_contexts` being non-empty |
| `placeable` (string / bool) | boolean, or fold into `install_contexts` as placement contexts (`floor`, `surface`, `wall`) |
| `portable` (string `"limited"`) | graded enum `portability: hand \| team \| vehicle \| fixed` |
| standalone `stackable` boolean | **dropped** — `storage_modes` already carries `stackable` |
| `inventory_unit` vs per-entry `unit` | rename to `default_unit` on the definition; a holding may override |
| schema target `→ item` vs `→ items` | normalise all to `items` (plural, matching every other dataset target) |

## Still open

- **Category authoring at scale.** How categories are seeded and kept consistent
  across thousands of items — a controlled vocabulary, template-driven, or
  inferred from ideas/tags (concept §8 tag-driven setup).
- **Individual representation.** Whether an actualized individual is its own
  dataset or an `entity_core` entity with an `is_instance_of` link to the
  definition; where the reconciliation logic lives.
- **Reconciliation triggers.** The exact moments a holding splits or re-absorbs
  an individual, and how that interacts with markets (aggregate trade) and
  logistics (cargo loads).

## As-built schema (post-2026-09-07)

### `schema_category` — dataset `categories`, id prefix `cat_`, extends `entity_core`

| Field | Type | Notes |
| --- | --- | --- |
| `category_kind` | string | `functional` \| `form` \| `market` \| `regulatory` \| `material_domain` |
| `synonyms` | string_list | |
| `category_notes` | text | |
| `members` | entity_list | **derived** — `EntityLoader.populate_category_members()` inverts every item/component's `categories`; never authored |
| *(hierarchy)* | — | via `entity_core.parents` → subcategories fall out as derived `offspring` |

Starter taxonomy (16): `cat_manufactured_good` ⊃ {`industrial_good`,
`machinery_module`, `storage_fixture`, `small_arm`, `kitchen_fixture`,
`cooking_appliance`, `vehicle_part`, `communication_good`, `electronic_item`,
`consumer_good_tech`}; `cat_foodstuff` ⊃ {`food_ingredient`, `prepared_food`};
`cat_raw_material_good` ⊃ {`raw_building_material`}.

### `schema_item` — the corporal-object base (extends `entity_core`)

`categories` (→categories), `primary_material`, `secondary_materials`,
`production_materials_needed` / `production_components_needed` /
`production_items_needed`, `produced_by`, `requires_technology`,
`dimension_length_m` / `dimension_width_m` / `dimension_height_m` / `mass_kg`
(*Physical*), `storage_modes` / `handling_notes` / `default_state` / `portable`
(`hand`\|`team`\|`vehicle`\|`fixed`) / `placeable` (bool) / `install_contexts`
(*Handling*), `descriptive_capabilities`, `ownership_records`, `consumable` /
`food_energy_kcal` / `food_satiation` (*Food*), `inventory_items` / `default_unit`
(*Inventory*).

**Removed:** `item_class`, `component_equivalent`, `uses_technology`
(→`requires_technology`), `installable` (derive from `install_contexts`),
`inventory_unit` (→`default_unit`), `stackable` (use `storage_modes`).

### `schema_components` — subclass, `extends: "item"`

Own fields only: `functional_roles`, `satisfies_categories`, `operational_groups`,
`subsystem_labels`, `maintenance_notes`, `power_kw` (*Physical*). Everything else
is inherited from `item`. **Removed:** `represented_item`, `component_class`, and
all now-inherited fields.

### Migration outcome

16 categories created; 13 items + 33 components migrated; `comp_pump_module` /
`comp_storage_rack` deleted and folded onto `item_pump_module` /
`item_storage_rack`; `prod_pump_module_assembly` and `prod_steel_plate_rolling`
repointed. `_is_component_card` (dataset/type based) unchanged, so component cards
keep the Operational tab and inherit item fields; a component card suppresses
inherited empty Food/Inventory rows.

### Deferred

- `→ item` vs `→ items` schema-target normalisation on `production`,
  `technology`, `producer`, `locations`, `formation`, `vehicle` (cosmetic;
  skipped to avoid colliding with other sessions authoring those schemas).
- Decision 3, the actualization runtime (holding → individual split + reconcile).
- Consolidating this into the next `conceptual_layer_overview` version
  (resolves open question #59; `text/tasks.txt` TASK-207–219 stay the scattered
  source of record until then).

## Concept doc status

`conceptual_layer_overview_v007.txt` still has no dedicated item/component
section — the model above should land there as v008, formally resolving open
question #59 (multi-classing → multiple category entities) and folding in
TASK-207–219.
