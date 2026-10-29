---
name: index0-data-field-development
description: Develop Index 0 ontology data fields into observable simulation behaviour using reproducible comparisons and iterative visual refinement. Use when adding or refining a field's simulation effects, rather than for schema-only edits or ordinary ontology lookups.
---

# Develop an Index 0 data field

Work in the user's selected Index 0 workspace (currently `C:\Users\logol\PycharmProjects\Index0_V001`). Preserve unrelated changes and the user's chosen species, view and visual resolution.

## Establish what the field means

- Read existing implementation documentation and inspect the live ontology projection, its schema dropdown options, authored values, units and inheritance. `PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()` is the current decoded persistent store; a checkpoint file may lag behind it.
- Trace the field from ontology through blueprint, growth, renderer and runtime consumers. Identify where it is merely displayed, ignored or replaced by a hard-coded default.
- Use the repository's Plantae ancestry catalogue for plant membership. Do not infer membership from names, growth traits or card labels.
- Choose contrasting authored candidates when available. To isolate a mechanism, use one species with clearly labelled experimental overrides. Missing category coverage does not justify inventing authored values or changing the ontology.
- Consult primary botanical or technical references for the mechanism. Separate supported facts from chosen simulation coefficients, unresolved fields and runtime defaults.

## Implement, compare, refine

1. Capture a baseline from the actual renderer with fixed seed, age, environment and detail level. Record relevant structural/ecological metrics. Include the whole organism and a detail view when scale hides the feature.
2. Define observable acceptance criteria: which input should change which output, which properties should remain stable, and what would make the result unreasonable. Keep the mechanism bounded and deterministic.
3. Connect the field to growth or interaction, then to a useful diagnostic view. Preserve separate organ modules, physical units, explicit attachment points and the established pixel grid. Keep large generated graphs outside ontology rows.
4. Compare paired treatments with shared scale and seed. Label deliberate overrides and independently scaled close-ups. Inspect images as well as numerical summaries; do not infer visual quality from passing tests.
5. Refine based on observed failures, then regenerate the affected comparison. Continue while concrete defects remain; do not add complexity simply to manufacture another round. This process should produce a visible, reviewable result, not just a proposed plan.

## Verify and retain the result

- Test meaningful invariants: determinism, finite/bounded geometry, valid parents and sockets, expected response direction, unknown values and zero values, persistence/round-trip portability, and detail-level stability of canonical ecological quantities.
- Cache keys must include every input that changes a result. Runtime catalogue membership should refresh after taxonomy changes; simulations should not traverse ontology ancestry per frame.
- Attempt the real app flow when relevant. If the app surface cannot be inspected, use the same renderer and explicitly call the output a renderer preview. Never claim a preview verifies live navigation.
- Write a field-specific document in `docs/` with candidate values, mechanism, sources, assumptions, baseline observations, refinement decisions, comparison paths, tests and remaining limits. Link it from the existing simulation documentation.
- Deliver the implemented behaviour, a readable visual comparison, and concise verification. Distinguish a useful qualitative model from an empirically calibrated one. Do not persist experimental treatments unless the user's request includes authoring those values.

Existing examples: `docs/species_sim_root_architecture_v001.md` and `docs/species_sim_forest_shade_v001.md`. Use their reproducibility principles; do not copy their species-specific coefficients into unrelated fields.
