"""Read entity IDs from scalar or collection-valued relationship fields."""


def entity_reference_ids(value):
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    if isinstance(value, dict):
        return entity_reference_ids(value.get("id"))
    if isinstance(value, (list, tuple)):
        ids = []
        for item in value:
            for entity_id in entity_reference_ids(item):
                if entity_id not in ids:
                    ids.append(entity_id)
        return ids
    return []


def first_entity_reference(value):
    """Select the first target for consumers that need a single parent/root."""
    return next(iter(entity_reference_ids(value)), None)
