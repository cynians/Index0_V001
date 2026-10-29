# Entity Field Overview — Vehicle Unit (v002 addendum)

Version: v002
Date: 2026-09-15
Supersedes: nothing in v001 — this is an additive/corrective delta. See
`entity_field_overview_vehicle_unit_v001.md` for the full as-built schema.

## Purpose

Refining the Vehicle Registry UI surfaced three schema changes:

- **Prototype status becomes a versioning label.** `is_prototype` (boolean)
  didn't generalize — a unit isn't just "prototype or not," it's a specific
  mark/version ("Prototype", "Mk I", "Mk II", ...). `version_label` (freeform
  string) replaces it and becomes the registry's primary (outer) grouping
  level, with production batch (`production_line_id`) as the inner grouping.
- **`assigned_faction`'s `target` metadata is corrected** from the singular
  `"faction"` to the actual dataset key, `"factions"` — a pre-existing
  cosmetic mismatch (also present on `schema_item`'s `produced_by`) that had
  no runtime effect but is worth fixing while touching this schema, since the
  registry's new relation picker uses `target` to know which dataset to
  search.
- **A lighter-weight tier below `vehicle_units` itself.** `schema_vehicle`
  (dataset `vehicles`) gains `unit_placeholders` — a unit known to exist by
  name but not yet catalogued as a full `vehicle_units` entity. This is not a
  duplicate of `vehicle_units`; it's intentionally too small to query or
  relate to anything (just `{name}`), living on the design entity until
  promoted.

- **Shipped by:** `tools/author_vehicle_unit_registry_v2_model.py` (ontology
  migration, backup in `artifacts/vehicle_unit_registry_v2/`).
- **Consumer:** `simulations/vehicle/vehicle_registry_simulation.py`/
  `vehicle_registry_renderer.py`.

## Schema changes

### `schema_vehicle_unit`

| Field | Change |
| --- | --- |
| `is_prototype` | Removed. |
| `version_label` | New — string, section Identity, optional. Freeform ("Prototype", "Mk I", "Mk II", ...); sorted in the registry by a small natural-order heuristic (Prototype first, then Mk I/II/III/... by roman numeral, then insertion order for anything else) rather than a manually-authored ordering field. |
| `assigned_faction.target` | `"faction"` → `"factions"` (matches the real dataset key; see `simulations/formation/formation_simulation.py::get_dataset("factions")` and others). |

Existing `vehicle_units` entities with `is_prototype: True` were backfilled to
`version_label: "Prototype"`; `is_prototype` was dropped from every real
entity that had it (no back-compat shim — the project's stated rule for
worldgen/ontology data).

### `schema_vehicle` — one new field

| Field | Type | Section | Notes |
| --- | --- | --- | --- |
| `unit_placeholders` | object_list | Registry | Units known to exist by name but not yet catalogued. Each entry: `{name}`. Promoted one at a time into a real `vehicle_units` entity via `VehicleRegistrySimulation.promote_placeholder`, which removes the entry here and creates the entity there. |

This mirrors `tools/author_formation_vehicle_placeholders.py`, which already
extends this same schema entity's `fields` dict via `PersistentOntologyStore`
for an unrelated Formation Sim need — same mechanism, different fields.

## Relation fields become searchable, with an "unfinished link" escape hatch

`produced_by`, `assigned_faction`, and (once a producer is resolved)
`production_line_id` are no longer edited as plain typed-id text in the
Vehicle Registry — v1's stated scope cut. They're now backed by a small
self-contained search picker (`VehicleRegistrySimulation.open_picker`/
`_picker_matches`/`_commit_picker_selection`) scoped to this screen, not the
floating-card relation-picker system (`ui/card.py`/`ui/knowledge_browser_ui.py`),
which is built around rich-text wiki-links embedded in a card's text field —
a mismatch for this screen's flat per-cell model.

Committing a typed name that doesn't match any candidate stores the raw
string in the field anyway rather than requiring a resolved entity id. No
schema change was needed for this — these fields were always loosely-typed
`entity` fields at the ontology level; an "unfinished link" is just a value
that hasn't been resolved to a real id yet. The renderer flags such values
(`VehicleRegistryRenderer._cell_is_unresolved`) with a distinct color and a
trailing `?` so it's visually obvious which links are still open, and the
same picker interaction lets you replace one with a real pick later —
overwriting the field, not a separate resolution step.

## v2 scope notes

- No manually-authored version ordering field — natural-sort heuristics
  (`VehicleRegistrySimulation._version_sort_key`) keep this freeform to name
  per the ask ("hierarchy visually intuitive and easy to control" without
  forcing an enum).
- The STATUS column shown in the registry (`Destroyed`/`Active`/
  `Assigned: <faction>`/`Unknown`) is derived at render time from existing
  fields, not stored — kept intentionally lean rather than adding an
  event-log structure.
- The producer-side view (browsing units by producer instead of by design)
  remains a fast-follow, unchanged from v1.
