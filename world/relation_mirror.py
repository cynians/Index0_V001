def _as_list(value):
    if isinstance(value, list):
        return list(value)
    if value in (None, "", []):
        return []
    return [value]


def _add_unique(values, value):
    value = str(value or "").strip()
    if value and value not in values:
        values.append(value)


def mirror_location_sim_relations(entity):
    if not isinstance(entity, dict):
        return entity

    parents = _as_list(entity.get("parents"))
    for field in ("star_system", "parent_location"):
        _add_unique(parents, entity.get(field))
    if parents or "parents" in entity:
        entity["parents"] = parents

    related = _as_list(entity.get("related"))
    for field in ("parent_body", "derived_from_system_body", "legacy_system_entity_id"):
        target_id = entity.get(field)
        if target_id not in parents:
            _add_unique(related, target_id)
    if related or "related" in entity:
        entity["related"] = related

    natural_materials = [
        material_id
        for material_id in _as_list(entity.get("natural_materials"))
        if str(material_id or "").strip()
    ]
    if natural_materials:
        entity["primary_material"] = natural_materials[0]
        entity["secondary_materials"] = natural_materials[1:]

    atmospheric_materials = [
        material_id
        for material_id in _as_list(entity.get("atmospheric_materials"))
        if str(material_id or "").strip()
    ]
    if atmospheric_materials:
        entity["primary_atmospheric_material"] = atmospheric_materials[0]
        entity["secondary_atmospheric_materials"] = atmospheric_materials[1:]
        if not natural_materials:
            entity["primary_material"] = atmospheric_materials[0]
            entity["secondary_materials"] = atmospheric_materials[1:]

    return entity
