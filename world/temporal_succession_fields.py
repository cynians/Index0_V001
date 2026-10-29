"""Load-time augmentation of ``schema_entity_core`` with generic succession links.

``schema_technology`` already has its own ``predecessor``/``successor``
(singular, technologies-only) pair for the tech tree. This module adds a
separate, universal ``predecessors``/``successors`` (plural) pair to the base
``entity_core`` schema so any entity -- a location, a faction, an idea, a
vehicle -- can record what directly came before/after it in its own lineage,
the same idiom already used by :mod:`world.technology_schema` and
:mod:`world.periods`.

Purely additive: existing ``start_year``/``end_year``/``temporal_periods``
data and every entity already authored keep working unchanged, since this
only adds two new optional fields nothing previously relied on.
"""

ENTITY_CORE_SCHEMA_ID = "schema_entity_core"

TEMPORAL_SUCCESSION_FIELDS = {
    "predecessors": {
        "type": "entity_list",
        "target": "entity_core",
        "section": "Temporal",
        "optional": True,
        "description": "What came directly before this in its own lineage.",
    },
    "successors": {
        "type": "entity_list",
        "target": "entity_core",
        "section": "Temporal",
        "optional": True,
        "description": "What came directly after this in its own lineage.",
    },
}


def apply_temporal_succession_schema(loader):
    """Merge predecessors/successors into schema_entity_core. Idempotent."""
    entities = getattr(loader, "entities", None)
    if not isinstance(entities, dict):
        return False

    schema = entities.get(ENTITY_CORE_SCHEMA_ID)
    if not isinstance(schema, dict):
        return False

    fields = schema.setdefault("fields", {})
    changed = False
    for field_name, spec in TEMPORAL_SUCCESSION_FIELDS.items():
        if field_name not in fields:
            fields[field_name] = dict(spec)
            changed = True
    return changed
