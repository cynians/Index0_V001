"""General, directional inheritance for species simulation and behaviour data.

The ontology remains authoritative for authored values.  Inferred parent
values are materialized as derived convenience data with provenance, while a
species can resolve an effective fallback from its cladistic parents without
mutating itself.
"""

from copy import deepcopy

from world.plant_traits import PLANT_TRAIT_FIELDS


INFERRED_FIELDS_KEY = "inferred_field_sources"
INFERENCE_CONFLICTS_KEY = "inference_conflicts"

SPECIES_BEHAVIOUR_FIELDS = {
    "behavior_class",
    "activity_cycle",
    "social_structure",
    "movement_modes",
    "feeding_strategy",
    "habitat_use",
    "trigger_conditions",
    "response_patterns",
    "behavioural_traits",
    "behavioral_traits",
    "locomotion_types",
    "diet",
    "ecological_roles",
    "habitats",
    "reproduction_type",
    "metabolism_class",
    "simulation_tier_default",
}

SPECIES_PLANT_FIELDS = set(PLANT_TRAIT_FIELDS)

SPECIES_INHERITABLE_FIELDS = SPECIES_BEHAVIOUR_FIELDS | SPECIES_PLANT_FIELDS


def _relation_ids(value):
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        candidate = value.get("id") or value.get("entity_id") or value.get("target")
        return [str(candidate)] if candidate else []
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            for relation_id in _relation_ids(item):
                if relation_id not in result:
                    result.append(relation_id)
        return result
    return []


def _is_species(entity):
    return isinstance(entity, dict) and (
        entity.get("_dataset") == "species" or entity.get("type") == "species"
    )


def is_inheritable_species_field(field_key):
    key = str(field_key or "").strip()
    return key in SPECIES_INHERITABLE_FIELDS or (
        key.startswith("simulation_")
        and key not in {"simulation_notes"}
    )


def _is_blank(value):
    return value is None or value == "" or value == [] or value == {}


def _inference_sources(entity):
    value = entity.get(INFERRED_FIELDS_KEY) if isinstance(entity, dict) else None
    return value if isinstance(value, dict) else {}


def is_authored_field(entity, field_key):
    if not isinstance(entity, dict) or _is_blank(entity.get(field_key)):
        return False
    return field_key not in _inference_sources(entity)


def _value_key(value):
    if isinstance(value, dict):
        return ("dict", tuple(sorted((str(key), _value_key(item)) for key, item in value.items())))
    if isinstance(value, (list, tuple)):
        return ("list", tuple(_value_key(item) for item in value))
    if isinstance(value, set):
        return ("set", tuple(sorted(_value_key(item) for item in value)))
    return (type(value).__name__, value)


def _entities(loader):
    return getattr(loader, "entities", {}) or {}


def _children_by_parent(loader):
    children = {}
    for entity in _entities(loader).values():
        if not isinstance(entity, dict):
            continue
        entity_id = str(entity.get("id") or "").strip()
        if not entity_id:
            continue
        for parent_id in _relation_ids(entity.get("parents")):
            children.setdefault(parent_id, []).append(entity_id)
    return children


def _descendant_ids(loader, parent_id, children):
    result = []
    seen = set()
    stack = list(children.get(parent_id, []))
    while stack:
        entity_id = str(stack.pop() or "").strip()
        if not entity_id or entity_id in seen:
            continue
        seen.add(entity_id)
        result.append(entity_id)
        stack.extend(children.get(entity_id, []))
    return result


def _eligible_source_entities(loader, target_id, children):
    """Descendant entities that may author an inheritable field for ``target_id``.

    The descendant walk and species/parent eligibility filter only depend on
    the target, so this is computed once per target rather than once per
    (target, field) pair.
    """
    entities = _entities(loader)
    eligible = []
    for entity_id in _descendant_ids(loader, target_id, children):
        entity = entities.get(entity_id)
        if not _is_species(entity) and not children.get(entity_id):
            continue
        eligible.append((entity_id, entity))
    return eligible


def _source_values(eligible_sources, field_key):
    values = []
    source_ids = []
    seen_keys = set()
    for entity_id, entity in eligible_sources:
        if not is_authored_field(entity, field_key):
            continue
        key = _value_key(entity[field_key])
        if key not in seen_keys:
            seen_keys.add(key)
            values.append((key, deepcopy(entity[field_key])))
        source_ids.append(entity_id)
    return values, source_ids


def _persist_derived(loader, entity):
    persist = getattr(loader, "persist_entity", None)
    if callable(persist):
        return bool(persist(entity))
    return True


def _persist_derived_batch(loader, changed_ids):
    """Persist all re-derived entities in one transaction.

    Committing them one at a time opens and saves the ontology quadstore once
    per entity, which turns a species edit that re-derives a deep clade chain
    into a multi-second stall.
    """
    if not changed_ids:
        return
    save_batch = getattr(loader, "save_changed_dataset_files", None)
    if callable(save_batch):
        save_batch(set(changed_ids))
        return
    entities = _entities(loader)
    for entity_id in changed_ids:
        entity = entities.get(entity_id)
        if isinstance(entity, dict):
            _persist_derived(loader, entity)


def refresh_species_inheritance(loader, *, persist=False):
    """Refresh derived parent fields from authored cladistic descendants.

    A field is inherited only when all authored descendant sources agree.  A
    conflict removes a previously-derived value rather than guessing.  A
    child-derived value is never considered authored for a later parent.
    """

    entities = _entities(loader)
    children = _children_by_parent(loader)
    changed_ids = set()

    candidate_ids = set(children)
    candidate_ids.update(
        entity_id
        for entity_id, entity in entities.items()
        if isinstance(entity, dict) and entity.get(INFERRED_FIELDS_KEY)
    )

    for target_id in sorted(candidate_ids):
        target = entities.get(target_id)
        if not isinstance(target, dict):
            continue
        if not (
            _is_species(target)
            or target.get("_dataset") == "cladistics"
            or target.get("type") == "cladistics"
        ):
            continue
        inferred = _inference_sources(target)
        conflicts = {}
        target_changed = False

        eligible_sources = _eligible_source_entities(loader, target_id, children)

        for field_key in sorted(SPECIES_INHERITABLE_FIELDS):
            values, source_ids = _source_values(eligible_sources, field_key)
            currently_inferred = field_key in inferred

            if is_authored_field(target, field_key):
                if field_key in inferred:
                    inferred.pop(field_key, None)
                    target_changed = True
                continue

            if len(values) == 1:
                source_value = values[0][1]
                marker = {
                    "kind": "offspring_consensus",
                    "source_ids": sorted(set(source_ids)),
                }
                if target.get(field_key) != source_value:
                    target[field_key] = deepcopy(source_value)
                    target_changed = True
                if inferred.get(field_key) != marker:
                    inferred[field_key] = marker
                    target_changed = True
            else:
                if currently_inferred:
                    target.pop(field_key, None)
                    inferred.pop(field_key, None)
                    target_changed = True
                if len(values) > 1:
                    conflicts[field_key] = sorted(set(source_ids))

        if inferred:
            if target.get(INFERRED_FIELDS_KEY) != inferred:
                target[INFERRED_FIELDS_KEY] = inferred
                target_changed = True
        elif INFERRED_FIELDS_KEY in target:
            target.pop(INFERRED_FIELDS_KEY, None)
            target_changed = True

        if conflicts:
            if target.get(INFERENCE_CONFLICTS_KEY) != conflicts:
                target[INFERENCE_CONFLICTS_KEY] = conflicts
                target_changed = True
        elif INFERENCE_CONFLICTS_KEY in target:
            target.pop(INFERENCE_CONFLICTS_KEY, None)
            target_changed = True

        if target_changed:
            changed_ids.add(target_id)

    if persist:
        _persist_derived_batch(loader, changed_ids)

    return changed_ids


def resolve_species_field(loader, entity, field_key):
    """Resolve a species field and provenance without mutating the species."""

    if not isinstance(entity, dict) or not is_inheritable_species_field(field_key):
        return {"value": entity.get(field_key) if isinstance(entity, dict) else None, "provenance": "authored"}

    if is_authored_field(entity, field_key):
        return {"value": entity.get(field_key), "provenance": "authored", "source_ids": [entity.get("id")]}

    entities = _entities(loader)
    parent_candidates = []
    for parent_id in _relation_ids(entity.get("parents")):
        parent = entities.get(parent_id)
        if not isinstance(parent, dict) or _is_blank(parent.get(field_key)):
            continue
        parent_candidates.append((parent_id, parent.get(field_key), _inference_sources(parent).get(field_key)))

    if not parent_candidates:
        return {"value": entity.get(field_key), "provenance": "unknown"}

    grouped = {}
    for parent_id, value, marker in parent_candidates:
        grouped.setdefault(_value_key(value), []).append((parent_id, marker))
    if len(grouped) != 1:
        return {"value": entity.get(field_key), "provenance": "conflict"}

    value_key = next(iter(grouped))
    source_ids = []
    for parent_id, marker in grouped[value_key]:
        source_ids.append(parent_id)
        if isinstance(marker, dict):
            source_ids.extend(marker.get("source_ids", []))
    return {
        "value": parent_candidates[0][1],
        "provenance": "inferred",
        "source_ids": sorted(set(source_ids)),
    }


def resolved_species_entity(loader, entity):
    """Return a non-authoritative display/simulation projection of a species."""

    result = dict(entity or {})
    for field_key in SPECIES_INHERITABLE_FIELDS:
        resolution = resolve_species_field(loader, entity, field_key)
        if resolution.get("provenance") == "inferred":
            result[field_key] = deepcopy(resolution.get("value"))
    return result
