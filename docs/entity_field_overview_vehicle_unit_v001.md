# Entity Field Overview — Vehicle Unit

Version: v001
Date: 2026-09-15

## Purpose

A vehicle *design* entity (dataset `vehicles`) represents a type/blueprint —
the hull, installed components, liveries. It never represented one specific,
individually constructed vehicle: a serial number, which production batch it
came from, when it was built or destroyed, who it ended up with. This
document introduces `vehicle_unit` (dataset `vehicle_units`), the first
concrete implementation of the "individual" tier that
`entity_field_overview_item_component_v001.md`'s Decision 3 ("Two layers of
actualization: definition → holding → individual") left explicitly deferred —
scoped to vehicles for now, generalizable to other entity families later.

- **Shipped by:** `tools/author_vehicle_unit_model.py` (ontology migration,
  backup in `artifacts/vehicle_unit_model/`).
- **Consumer:** `simulations/vehicle/vehicle_registry_simulation.py` — the
  Vehicle Registry screen, launched as a third option alongside Vehicle
  Designer/Vehicle Sim from any `vehicles`-dataset entity.

## Why a new dataset instead of embedding on the vehicle design

Production output today (`schema_producer.production_lines`, an inline
`dict_list` on the producer — see
`entity_field_overview_item_component_v001.md`'s "What the code actually
reads" section) is rate-based: `rate_value`/`rate_period`, no discrete count
and no per-unit identity. A vehicle unit needed to be findable from *either*
side of who-built/what-design without scanning every design a producer has
ever touched, or every producer a design has ever used — a standalone
dataset with relations both ways (`represents_design` → vehicles,
`produced_by` → producers) serves that; embedding on one side only doesn't.

## Schema

`schema_vehicle_unit` → dataset `vehicle_units` · type `vehicle_unit` ·
id prefix `unit_` · extends `entity_core`. Every field is optional, matching
the project's established schema convention (only `entity_core`'s `id`/
`pretty_name`/`type` are required).

### Identity

| Field | Type | Notes |
| --- | --- | --- |
| `represents_design` | entity → vehicles | Which design this is an instance of. |
| `serial_number` | string | e.g. `Sn-1`. |
| `is_prototype` | boolean | |

### Production

| Field | Type | Notes |
| --- | --- | --- |
| `produced_by` | entity → producers | |
| `production_line_id` | string | Matches a value in that producer's `production_lines[].line_id` — the batch-grouping key. |
| `batch_label` | string | Friendly override for the group header; derived from the production line when unset. |

### History

| Field | Type | Notes |
| --- | --- | --- |
| `year_constructed` | number | |
| `year_destroyed` | number | |
| `fate_notes` | text | e.g. "crashed during testing". |
| `assigned_faction` | entity → faction | Structured counterpart to a "went to faction X" fate. |
| `current_link_entity_id` | string | Whatever live entity currently represents this unit (a site, a formation slot, a flight instance, ...). Blank until the unit is actualized somewhere — no actualization runtime exists yet for any entity family, so this starts as a manually-set reference. |

## v1 scope notes

- `produced_by`/`production_line_id`/`assigned_faction` are edited as plain
  typed-id text fields in the Vehicle Registry UI, not through a relation
  picker widget — consistent with how `vehicle_specifications`/
  `design_requirements` are already flat text-cell tables with no picker. A
  proper picker is a fast-follow, not part of this pass.
- The producer-side view (browsing units by producer instead of by design)
  is a fast-follow too — the schema already supports it (`produced_by` is
  right there to filter on), only the UI doesn't exist yet.
- No auto-generated placeholder rows from a production line's planned
  quantity (production lines don't carry a discrete planned-count field,
  only a continuous rate) — "unknown, create" rows are just manually added
  blank units left mostly empty.
