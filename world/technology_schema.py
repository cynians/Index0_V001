"""Load-time augmentation of the technology schema.

The ``schema_technology`` entity is only defined in the ontology. Succession
(``predecessor`` / ``successor``) and being forgotten (``forgotten_year``) are
new concerns for the timeline, so the extra fields are merged in here at load
time -- the same idiom as :mod:`world.component_host`.
"""

TECHNOLOGY_SCHEMA_ID = "schema_technology"

TECHNOLOGY_SCHEMA_FIELDS = {
    "predecessor": {
        "type": "entity_list",
        "target": "technologies",
        "section": "Succession",
        "optional": True,
    },
    "successor": {
        "type": "entity_list",
        "target": "technologies",
        "section": "Succession",
        "optional": True,
    },
    "forgotten_year": {
        "type": "number",
        "section": "Temporal",
        "optional": True,
    },
}

_FALLBACK_SCHEMA_ENTITY = {
    "id": TECHNOLOGY_SCHEMA_ID,
    "_dataset": "schemas",
    "type": "schema",
    "name": "technology",
    "pretty_name": "Technology",
    "schema": "technology",
    "extends": "entity_core",
}


def apply_technology_schema(loader):
    """Merge succession / forgotten fields into ``schema_technology``.

    Idempotent: existing field specs are never overwritten.
    """
    entities = getattr(loader, "entities", None)
    datasets = getattr(loader, "datasets", None)
    if not isinstance(entities, dict) or not isinstance(datasets, dict):
        return False

    schemas = datasets.setdefault("schemas", [])
    schema = entities.get(TECHNOLOGY_SCHEMA_ID)
    changed = False

    if not isinstance(schema, dict):
        schema = dict(_FALLBACK_SCHEMA_ENTITY)
        schema["fields"] = {}
        entities[TECHNOLOGY_SCHEMA_ID] = schema
        changed = True
    else:
        schema.setdefault("schema", "technology")
        schema.setdefault("extends", "entity_core")

    fields = schema.setdefault("fields", {})
    for field_name, spec in TECHNOLOGY_SCHEMA_FIELDS.items():
        if field_name not in fields:
            fields[field_name] = dict(spec)
            changed = True

    if not any(
        isinstance(candidate, dict) and candidate.get("id") == TECHNOLOGY_SCHEMA_ID
        for candidate in schemas
    ):
        schemas.append(schema)
        changed = True

    return changed
