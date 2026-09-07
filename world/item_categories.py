"""Helpers for the item/component ``categories`` relation.

Categories are ordinary ontology entities (dataset ``categories``) that nest
through the standard ``parents`` relation. An item or component links several of
them through its own ``categories`` field; the reverse ``members`` list is a
derived projection (see ``EntityLoader.populate_category_members``), never
authored.

``item_class`` / ``component_class`` (single free-text strings) were replaced by
this relation -- see ``docs/entity_field_overview_item_component_v001.md``.
"""

from __future__ import annotations


def _relation_ids(value):
    """Normalise a relation field (str / dict / list of either) to id strings."""
    if not value:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        entity_id = str(value.get("id") or value.get("entity_id") or "").strip()
        return [entity_id] if entity_id else []
    if isinstance(value, (list, tuple)):
        ids = []
        for item in value:
            for entity_id in _relation_ids(item):
                if entity_id not in ids:
                    ids.append(entity_id)
        return ids
    return []


def category_ids(entity):
    """The category ids linked by an item/component entity."""
    return _relation_ids((entity or {}).get("categories"))


def resolve_category_labels(world_model, entity, *, fallback=None):
    """Return a human-readable ``", "``-joined list of an entity's category names.

    Falls back to ``fallback`` (or the entity ``type``, or ``"item"``) when the
    entity links no categories -- so display code can drop the old
    ``str(entity.get("item_class") or "item")`` idiom without a special case.
    """
    getter = getattr(world_model, "get_entity", None)
    labels = []
    for category_id in category_ids(entity):
        category = getter(category_id) if callable(getter) else None
        label = None
        if isinstance(category, dict):
            label = category.get("pretty_name") or category.get("name")
        labels.append(str(label or category_id))
    if labels:
        return ", ".join(labels)
    return str(fallback or (entity or {}).get("type") or "item")
