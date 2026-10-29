# Entity Field Overview — Item & Component (v003 addendum)

Version: v003
Date: 2026-10-28
Supersedes: nothing in v001 or v002 — this is an additive delta. See
`entity_field_overview_item_component_v001.md` for the full as-built schema
and `..._v002.md` for the ports.

## Purpose

Records the `schema_components` change for the logistics simulation's space
domain (`docs/logistics_simulation_concept_v001.md`): components state what
they contribute in space, so a vehicle design's capability profile (delta-v,
shielding, life support, docking, atmosphere entry) can be checked against
what a route requires, such as a transfer window.

- **Shipped by:** `tools/author_component_spaceflight_fields.py` (ontology
  authoring, backup in `artifacts/component_spaceflight_fields/`).
- **Consumer:** `simulations/logistics/vehicle_profiles.py` —
  `space_profile_from_design`, `design_propulsion_state` — which read the
  fields from each installed component's own entity (the vehicle designer's
  catalog entry does not carry them).

## Schema change

### `schema_components` — seven new own fields, section Spaceflight

| Field | Type | Notes |
| --- | --- | --- |
| `thrust_n` | number | Engine thrust in vacuum, newtons. |
| `specific_impulse_s` | number | Engine specific impulse in vacuum, seconds. |
| `propellant_capacity_kg` | number | Propellant a tank holds when full, kilograms. |
| `shielding_class` | string | `none`, `orbital` or `deep_space`; the craft takes the highest of its parts. Other values are ignored. |
| `life_support_s` | number | Crew life support supplied, seconds (shown in interplanetary cycles); the craft sums its parts. |
| `docking` | boolean | The part lets the craft dock. |
| `atmosphere_entry` | boolean | The part lets the craft enter an atmosphere (heat shield). |

How a design profile uses them:

- delta-v by the rocket equation with full tanks: dry mass = installed
  component masses (`mass_kg`, item schema), propellant = summed
  `propellant_capacity_kg`, engines = parts with both `thrust_n` and
  `specific_impulse_s` whose fuel input is wired;
- a vehicle's `structural_features` entries may also carry
  `shielding_class` and `atmosphere_entry` (a hull that is its own shield);
- a term no part shows stays unknown, which a route requirement reports as
  unknown rather than met.

## Backfill

None. No existing component received values: a guessed thrust or shielding
class would be an invented fact. Components gain the fields as they are
authored.

## Known gaps

- Hull and structure mass are not modelled, so dry mass is component mass
  only.
- Per-vehicle propellant load (operational state, not design) is not yet a
  field; profiles assume full tanks.
