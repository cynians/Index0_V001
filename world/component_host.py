COMPONENT_HOST_SCHEMA_ENTITY = {
    "id": "schema_component_host",
    "_dataset": "schemas",
    "type": "schema",
    "name": "component_host",
    "pretty_name": "Component Host",
    "schema": "component_host",
    "extends": "entity_core",
    "fields": {
        "vehicle_class": {
            "type": "string",
            "section": "Engineering / Design",
            "optional": True,
        },
        "dimension_length_m": {
            "type": "number",
            "section": "Engineering / Design",
            "optional": True,
        },
        "dimension_width_m": {
            "type": "number",
            "section": "Engineering / Design",
            "optional": True,
        },
        "dimension_height_m": {
            "type": "number",
            "section": "Engineering / Design",
            "optional": True,
        },
        "component_catalog": {
            "type": "entity_list",
            "target": "components",
            "section": "Engineering / Components",
            "optional": True,
        },
        "installed_components": {
            "type": "object_list",
            "section": "Engineering / Components",
            "optional": True,
        },
        "interior_layout": {
            "type": "object_list",
            "section": "Engineering / Interior",
            "optional": True,
        },
        "operational_state": {
            "type": "dict",
            "section": "Engineering / Operations",
            "optional": True,
        },
    },
}


def apply_component_host_schema(loader):
    """Expose reusable design fields without giving an entity a second dataset identity."""
    entities = getattr(loader, "entities", None)
    datasets = getattr(loader, "datasets", None)
    if not isinstance(entities, dict) or not isinstance(datasets, dict):
        return False

    schemas = datasets.setdefault("schemas", [])
    schema_id = COMPONENT_HOST_SCHEMA_ENTITY["id"]
    schema = entities.get(schema_id)
    changed = False
    if not isinstance(schema, dict):
        schema = {
            key: value
            for key, value in COMPONENT_HOST_SCHEMA_ENTITY.items()
            if key != "fields"
        }
        schema["fields"] = {
            field_name: dict(spec)
            for field_name, spec in COMPONENT_HOST_SCHEMA_ENTITY["fields"].items()
        }
        entities[schema_id] = schema
        changed = True
    else:
        schema.setdefault("schema", "component_host")
        schema.setdefault("extends", "entity_core")
        fields = schema.setdefault("fields", {})
        for field_name, spec in COMPONENT_HOST_SCHEMA_ENTITY["fields"].items():
            if field_name not in fields:
                fields[field_name] = dict(spec)
                changed = True

    if not any(
        isinstance(candidate, dict) and candidate.get("id") == schema_id
        for candidate in schemas
    ):
        schemas.append(schema)
        changed = True
    return changed
