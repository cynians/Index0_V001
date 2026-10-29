"""Tag rows: how a card's Tags tab groups an entity's tags.

Tags serve many purposes (need tags, personality words, worldgen status,
material roles and processes, planet conditions, topic labels) and do not
belong in one row. A row is either a field of the entity holding tag
strings (``personality_adjectives``, ``production_process_tags``) or a tag
class within the general ``tags`` field: need tags are ``tags`` whose tag
entity has ``tag_class: need``.

A schema names the rows it always shows in ``tag_rows``, a list of
``{label, field, tag_class}``. Beyond those, rows come from the entity: the
general tags, one row per tag class found among them, and every tag-like
string-list field (``*_tags`` and a few named ones) of the schema or the
entity. A tag class on a field row only steers suggestions.
"""

from __future__ import annotations

from dataclasses import dataclass


GENERAL_FIELD = "tags"
TAG_DATASET = "tags"
TAG_LIKE_FIELDS = (
    "personality_adjectives",
    "action_tags",
    "functional_roles",
    "satisfies_categories",
    "descriptive_capabilities",
)
TAG_CLASS_LABELS = {
    "need": "Needs",
    "personality": "Personality",
    "action": "Actions",
}


@dataclass(frozen=True)
class TagRow:
    # the card's edit key: "tags", "tags::<class>", or the field name
    key: str
    label: str
    field: str
    tag_class: str = ""
    read_only: bool = False


def lookup_key(value):
    """How tag strings match tag entities: case, spaces and dashes ignored, as cards match them."""
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _tag_entities(world_model):
    getter = getattr(world_model, "get_dataset", None)
    entities = getter(TAG_DATASET) if callable(getter) else None
    return [entity for entity in entities or [] if isinstance(entity, dict)]


def tag_class_index(world_model):
    """Tag class of every tag entity, under each key a tag string may use for it."""
    index = {}
    for entity in _tag_entities(world_model):
        tag_class = str(entity.get("tag_class") or "").strip().lower()
        if not tag_class:
            continue
        keys = {lookup_key(entity.get(field)) for field in ("id", "name", "pretty_name")}
        keys.update(key[4:] for key in list(keys) if key.startswith("tag_"))
        for key in keys - {""}:
            index.setdefault(key, tag_class)
    return index


def class_names(tag_class, world_model):
    """Names of the tag entities of a class, for suggestions."""
    return sorted(
        str(entity.get("pretty_name") or entity.get("name") or entity.get("id"))
        for entity in _tag_entities(world_model)
        if str(entity.get("tag_class") or "").strip().lower() == tag_class
    )


def _row_key(field, tag_class):
    return f"{GENERAL_FIELD}::{tag_class}" if field == GENERAL_FIELD and tag_class else field


def _field_label(field):
    base = field[:-5] if field.endswith("_tags") else field
    return base.replace("_", " ").capitalize()


def _is_tag_like(field):
    return field.endswith("_tags") or field in TAG_LIKE_FIELDS


def tag_rows(entity, schema=None, world_model=None, class_index=None):
    """The rows of an entity's Tags tab, the general row first."""
    entity = entity or {}
    schema = schema or {}
    class_index = tag_class_index(world_model) if class_index is None else class_index
    rows = [TagRow(GENERAL_FIELD, "General", GENERAL_FIELD)]
    seen = {GENERAL_FIELD}

    def add(row):
        if row.key not in seen:
            rows.append(row)
            seen.add(row.key)

    for spec in schema.get("tag_rows") or []:
        if not isinstance(spec, dict):
            continue
        field = str(spec.get("field") or GENERAL_FIELD)
        tag_class = str(spec.get("tag_class") or "").strip().lower()
        label = spec.get("label") or TAG_CLASS_LABELS.get(tag_class) or _field_label(field)
        add(TagRow(_row_key(field, tag_class), label, field, tag_class))
    for value in _values(entity, GENERAL_FIELD):
        tag_class = class_index.get(lookup_key(value))
        if tag_class:
            add(TagRow(_row_key(GENERAL_FIELD, tag_class), TAG_CLASS_LABELS.get(tag_class, tag_class.title()),
                       GENERAL_FIELD, tag_class))
    for field, spec in (schema.get("fields") or {}).items():
        if field != GENERAL_FIELD and _is_tag_like(field) and (spec or {}).get("type", "string_list") == "string_list":
            add(TagRow(field, _field_label(field), field))
    for field, value in entity.items():
        if field != GENERAL_FIELD and _is_tag_like(field) and isinstance(value, (list, tuple)) and value:
            add(TagRow(field, _field_label(field), field))
    return rows


def _values(entity, field):
    raw = (entity or {}).get(field) or []
    if isinstance(raw, str):
        raw = [raw]
    values = []
    for value in raw if isinstance(raw, (list, tuple, set)) else []:
        text = str(value or "").strip()
        if text and text not in values:
            values.append(text)
    return values


def row_values(row, entity, rows, class_index):
    """The strings a row shows: a field's values, or the general tags of its class (or of no claimed class)."""
    values = _values(entity, row.field)
    if row.field != GENERAL_FIELD:
        return values
    if row.tag_class:
        return [value for value in values if class_index.get(lookup_key(value)) == row.tag_class]
    claimed = {other.tag_class for other in rows if other.field == GENERAL_FIELD and other.tag_class}
    return [value for value in values if class_index.get(lookup_key(value)) not in claimed]
