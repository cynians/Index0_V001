# Vehicle Designer specification fields v0.1

## Intent

The Specification stage is a sparse design brief that precedes shape authoring. A designer can supply only the facts currently known and continue with blank values. The stage separates three kinds of knowledge:

- Identity metadata (`name`, `vehicle_class`, `manufacturer_name`, `description`) remains directly searchable on the vehicle entity.
- `vehicle_specifications` stores arbitrary characteristic rows with `label`, `value`, `unit`, and `category`.
- `design_requirements` stores arbitrary requirement rows with `label`, `target`, `unit`, `priority`, and `notes`.

Rows carry stable IDs, so later ontology tools can refine, relate, or replace individual facts without depending on display order.

## Mechanical linkage

Load-bearing forms belong in `structural_features`, not `installed_components`. A structural feature can declare `satisfies_categories` and therefore satisfy class requirements such as `structure` or `flight_surfaces` without appearing in the component catalog. Components remain discrete installed systems with a physical x/y/z footprint.

Component centers are now clamped using half of their catalog dimensions on each axis. This keeps the entire component envelope inside the current vehicle dimensions when placing, dragging, or shrinking the hull.

## Persistence

Finishing the Specification stage—or navigating to another design stage—writes identity metadata, characteristic rows, design requirements, and structural features through the world model into the authoritative ontology store. Empty lists and empty values are valid and remain sparse rather than being replaced with guessed defaults.

## Verification

`tests/test_vehicle_designer.py` covers sparse row editing and removal, structural requirement satisfaction without a component, and footprint-aware coordinate clamping. The MiG-21 verification entity exercises all three specification sections and is reproducible with `tools/create_mig21_vehicle_design.py`.

## Current limits

Characteristic values and units are stored as authored text in this first slice. This preserves uncertainty and uncommon units, but numeric comparisons and unit conversion require a later typed-value layer. Characteristics and requirements page independently when their panels fill. Typed unit conversion and ontology relationship pickers are future refinements.
