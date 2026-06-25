# OWL Ontology Migration Plan

## Goal

Move repository entries from YAML-first records to an OWL/RDF knowledge graph while preserving the current UI and simulation behavior during the transition.

The main design change is that relationship semantics become ontology facts. For example, an entry only needs to assert `hasParent`; `hasOffspring` is declared as the inverse and can be inferred or materialized for views.

## Target Architecture

1. YAML compatibility loader
   - Existing `entries/*.yaml` files remain readable during migration.
   - Current `loader.datasets` and `loader.entities` dictionary projections continue to exist so UI and simulations do not have to move all at once.

2. Ontology repository
   - Owlready2 becomes the Python-facing ontology layer.
   - Entries are OWL individuals.
   - Datasets and schema/entity types are RDF classes.
   - Relation fields become object properties.
   - Scalar fields become datatype properties.

3. Query/materialization layer
   - UI code asks for entries through repository methods.
   - Recursive and inverse relationships are inferred or materialized centrally.
   - Views such as `offspring` are projections, not independently edited source fields.

4. Write path
   - Editing a relation asserts or retracts one canonical fact.
   - Inverse and recursive views are recomputed.
   - Later phases can replace YAML writes with RDF serialization.

## Migration Phases

### Phase 1: OWL Export and Projection

- Add an ontology repository module.
- Export current YAML entries to `ontology/index0.owl` with Owlready2.
- Declare core object properties:
  - `hasParent.inverse_property = hasOffspring`
  - `relatedTo`
- Materialize `offspring` from `parents` in one repository projection.

### Phase 2: Schema-to-Ontology Mapping

- Convert schema YAML fields into OWL property declarations.
- Treat fields with `type: entity` or `type: entity_list` as object properties.
- Treat scalar fields as datatype properties.
- Preserve UI metadata such as sections and optionality as annotations.

### Phase 3: Read Path Refactor

- Keep `WorldModel.get_entity`, `get_dataset`, and `get_entities_by_dataset` stable.
- Internally source those projections from the ontology repository.
- Move relationship graph construction onto ontology relations.
- Current bridge: `EntityLoader(..., ontology_path=..., use_ontology=True)` can load an Owlready2-saved ontology and project it back to `datasets` / `entities`.

### Phase 4: Write Path Refactor

- Replace ad hoc YAML relation mutations with repository assertions.
- Add high-level APIs such as:
  - `set_relation(source_id, property_name, target_id)`
  - `remove_relation(source_id, property_name, target_id)`
  - `set_literal(entity_id, field_name, value)`
- Stop persisting derived inverse fields such as `offspring`.

### Phase 5: RDF-First Storage

- Switch canonical saves to Owlready2-managed OWL serialization.
- Keep YAML export as a compatibility/export format if useful.
- Use Owlready2 for ontology loading, saving, entity access, and reasoning.

### Phase 6: Validation

- Use OWL for inference.
- Use SHACL or custom validators for closed-world editor rules.
- Add tests for:
  - migration fidelity
  - inverse relations
  - recursive descendants/ancestors
  - relation editing
  - UI creation flows

## Important Design Decision

`offspring` should not be independently editable source truth. It should be inferred from `parents` through `idx:hasParent owl:inverseOf idx:hasOffspring`, then projected into the existing card views until the UI can query the graph directly.
