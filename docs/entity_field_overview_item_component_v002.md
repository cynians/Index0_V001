# Entity Field Overview — Item & Component (v002 addendum)

Version: v002
Date: 2026-09-14
Supersedes: nothing in v001 — this is an additive delta. See
`entity_field_overview_item_component_v001.md` for the full as-built schema.

## Purpose

Records the `schema_components` change shipped alongside the vehicle-designer
system-diagram feature: a component now separates its physical *slot*
(the vehicle designer's reserved rect + category) from the specific catalog
part *installed* into it, and installed parts declare typed input/output
ports so the designer can auto-wire a vehicle's systems into a flow diagram
(e.g. a fuel tank's `fuel` output feeding an engine's `fuel` input, whose
`mechanical_power`/`thrust` output in turn feeds a wheel or a flight surface).

- **Shipped by:** `tools/author_component_ports_model.py` (ontology migration,
  backup in `artifacts/component_ports_model/`).
- **Consumer:** `simulations/vehicle/vehicle_design.py` —
  `VehicleDesignController._build_catalog_entry_from_component_entity`,
  `_resolve_ports`, `compute_system_wiring`, `get_component_wiring_status`.

## Schema change

### `schema_components` — two new own fields

| Field | Type | Section | Notes |
| --- | --- | --- | --- |
| `inputs` | object_list | Systems | Resource ports consumed to operate. Each entry: `{resource_type, label}`. |
| `outputs` | object_list | Systems | Resource ports produced. Same shape. |

### Port vocabulary (`resource_type`, controlled)

`mechanical_power`, `electrical_power`, `fuel`, `coolant`, `thrust`, `lift`,
`control_signal`, `cargo_mass`, `crew_capacity`.

Purely structural component types (body, hull, frame, landing gear, ...) are
expected to carry empty `inputs`/`outputs` — they aren't part of a
resource-flow graph.

## Backfill

Real `components`-dataset entities carry a generic `type` of `"component"` or
`"assembly"` (not a fine-grained kind), so ports cannot be inferred from
`type`. The migration and the runtime fallback both infer ports from
`satisfies_categories` instead — see `CATEGORY_DEFAULT_PORTS` in
`tools/author_component_ports_model.py`, kept as a hand-synced copy of
`VehicleDesignController.CATEGORY_DEFAULT_PORTS` (the same table also keys off
the fine-grained `component_type` used by embedded-literal catalog fixtures,
via `COMPONENT_TYPE_DEFAULT_PORTS`, since those fixtures — e.g. the MiG-21
verification vehicle — do set a specific component_type).

Only entities with a matching category and no already-authored ports were
backfilled; components with neither an explicit port declaration nor a
recognized category (most legacy parts — hinges, brackets, cross-members, and
similar structural/unclassified components) were left with no ports, which is
the correct outcome for non-flow parts.

## Not covered

- Embedded-literal `component_catalog` entries on a vehicle entity (a Python
  fallback path used when a catalog id doesn't resolve to a real ontology
  entity, e.g. `tools/create_mig21_vehicle_design.py`) are not touched by this
  migration — they carry their own explicit `inputs`/`outputs` per entry.
- Legacy components with `satisfies_categories: None` and a generic label were
  not heuristically re-categorized as part of this change; that would be a
  separate categories data-quality pass.
