"""A person's knowledge: one collection per person, nesting shared ones.

A full person names its knowledge collection in ``knowledge_collection``
(``collection_class: personal_knowledge``). The collection's ``includes``
list what the person knows; nested shared collections
(``collection_class: shared_knowledge``: a culture, a job's training, local
lore) add what everyone in them knows. Beliefs about a member are rows of
the collection's ``member_records``:

    member                 the entity the belief is about
    familiarity, interest, conviction, behavioral_rules
    navigation_knowledge, direction_hint, route_waypoints
    believed_location      where the member is thought to be
    believed_state         e.g. "stocked", "empty"
    checked_at             when that was last seen to be so
    experienced            what it did for a need last time, {need: amount}
    source                 how it was learned

A record from the nearest collection wins field by field: the person's own
belief over a shared collection's. A belief is not the truth; see
docs/person_simulation_concept_v001.md section 5.
"""

from __future__ import annotations

from dataclasses import dataclass

from simulations.collection.collections import is_collection, members
from world.entity_references import entity_reference_ids, first_entity_reference


KNOWLEDGE_FIELD = "knowledge_collection"
PERSONAL_KNOWLEDGE = "personal_knowledge"
SHARED_KNOWLEDGE = "shared_knowledge"


@dataclass(frozen=True)
class KnownEntity:
    entity_id: str
    record: dict
    # the collections that know it, nearest first
    sources: tuple


def _entity(world_model, entity_id):
    getter = getattr(world_model, "get_entity", None)
    entity = getter(entity_id) if callable(getter) and entity_id else None
    return entity if isinstance(entity, dict) else None


def knowledge_collection(person, world_model):
    collection = _entity(world_model, first_entity_reference((person or {}).get(KNOWLEDGE_FIELD)))
    return collection if is_collection(collection) else None


def _collection_tree(collection, world_model):
    """The collection and every collection nested in it, nearest first, each once."""
    order = []
    queue = [collection]
    seen = set()
    while queue:
        current = queue.pop(0)
        if current.get("id") in seen:
            continue
        seen.add(current.get("id"))
        order.append(current)
        for reference in entity_reference_ids(current.get("includes")):
            nested = _entity(world_model, reference)
            if is_collection(nested):
                queue.append(nested)
    return order


def _member_records(collection):
    records = {}
    for row in collection.get("member_records") or []:
        member_id = first_entity_reference((row or {}).get("member")) if isinstance(row, dict) else None
        if member_id:
            records[member_id] = {key: value for key, value in row.items() if key != "member"}
    return records


def known_entities(person, world_model):
    """Everything the person knows, each with its merged belief record and where the knowledge came from."""
    collection = knowledge_collection(person, world_model)
    if collection is None:
        return []
    found = {}
    for current in _collection_tree(collection, world_model):
        records = _member_records(current)
        listed = [
            reference for reference in entity_reference_ids(current.get("includes"))
            if not is_collection(_entity(world_model, reference))
        ]
        for member_id in dict.fromkeys(listed + list(records)):
            record, sources = found.setdefault(member_id, ({}, []))
            for key, value in records.get(member_id, {}).items():
                record.setdefault(key, value)
            sources.append(current["id"])
    # Members a membership rule generates carry no belief of their own.
    for member in members(collection, world_model):
        found.setdefault(member.entity_id, ({}, [member.source]))
    return [
        KnownEntity(entity_id, record, tuple(sources))
        for entity_id, (record, sources) in found.items()
    ]


def knowledge_records(person, world_model):
    """The person's beliefs as plain records, ``{"entity": id, **belief}``, as Person Sim reads them."""
    personal_id = (knowledge_collection(person, world_model) or {}).get("id")
    records = []
    for known in known_entities(person, world_model):
        record = dict(known.record)
        record["entity"] = known.entity_id
        record["knowledge_sources"] = list(known.sources)
        nearest = _entity(world_model, known.sources[0]) if known.sources else None
        if nearest is not None and nearest.get("id") != personal_id:
            record.setdefault("source", nearest.get("pretty_name") or nearest.get("name") or nearest["id"])
        records.append(record)
    return records
