"""Which folder below ``assets/`` an entity's files belong in.

A category is the dataset of the entity an asset belongs to, and each category
packs into one ``<category>.pak`` (``tools/pack_assets.py``).  Species and
clades are ``plants`` when they descend from plants or fungi (both go through
the plant design process) and ``animals`` otherwise; locations are ``maps``.
An idea such as an illustration belongs to what it depicts, its parent.
"""

from __future__ import annotations

DATASET_CATEGORY = {"species": "plants", "cladistics": "plants", "locations": "maps"}
PLANT_ROOTS = frozenset({"cladis_archaeplastida", "cladis_fungi"})
UNSORTED = "misc"


def _parent_ids(entity):
    parents = entity.get("parents")
    if isinstance(parents, str):
        parents = [parents]
    return [str(parent) for parent in parents or [] if parent]


def _descends_from(entity, roots, get_entity):
    seen, pending = set(), [entity]
    while pending:
        current = pending.pop()
        entity_id = str(current.get("id") or "")
        if entity_id in roots:
            return True
        if entity_id in seen:
            continue
        seen.add(entity_id)
        for parent_id in _parent_ids(current):
            parent = get_entity(parent_id)
            if isinstance(parent, dict):
                pending.append(parent)
    return False


def category_of(entity, get_entity):
    """The category of ``entity``; ``get_entity(entity_id)`` looks up its parents."""
    if not isinstance(entity, dict):
        return UNSORTED
    dataset = str(entity.get("_dataset") or entity.get("type") or "").strip()
    if dataset in ("ideas", "idea"):
        for parent_id in _parent_ids(entity):
            parent = get_entity(parent_id)
            if isinstance(parent, dict):
                return category_of(parent, get_entity)
        return UNSORTED
    if dataset in ("species", "cladistics"):
        return "plants" if _descends_from(entity, PLANT_ROOTS, get_entity) else "animals"
    return DATASET_CATEGORY.get(dataset, dataset or UNSORTED)


def illustration_folder(illustration_id, get_entity):
    """``assets/<category>/illustrations`` for an illustration, by what it depicts."""
    entity = get_entity(illustration_id) if illustration_id else None
    return f"assets/{category_of(entity, get_entity)}/illustrations"
