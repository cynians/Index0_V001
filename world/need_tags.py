"""Need tags: which needs a thing has to do with, and why.

A need tag is an ordinary tag entity (dataset ``tags``) with
``tag_class: need``. It names the need it serves in ``serves_need`` or
inherits it through its ``parents`` (Snack -> Food). Entities carry tags as
plain strings in their ``tags`` field, matched to tag entities the way cards
match them: by id, name or pretty name, ignoring case, spaces and dashes.

A tag says what a thing is for, never how much it gives. Amounts come from
the thing's own fields (``food_satiation``, ``rest_quality``) or from what a
person learned. Without a tag, those fields imply the need themselves, and
any person can be company (belonging).

A thing can relate to a need itself (``is``), or hold something that does.
The relation decides what a person does to get it:

    is         the thing itself                      use
    carries    ``inventory_items``                   take
    dispenses  ``dispenses_items`` (a machine)       operate
    gives      ``hands_out_items`` on a job          ask
    bears      ``harvest_yields`` on a species       harvest
    produces   ``produced_items`` on a producer      make

See docs/person_simulation_concept_v001.md section 5.
"""

from __future__ import annotations

from dataclasses import dataclass

from world.entity_references import entity_reference_ids
from world.item_categories import category_ids


NEEDS = ("food", "rest", "safety", "belonging", "esteem", "leisure")
NEED_TAG_CLASS = "need"
TAG_DATASET = "tags"

RELATION_ACTIONS = {
    "is": "use",
    "carries": "take",
    "dispenses": "operate",
    "gives": "ask",
    "bears": "harvest",
    "produces": "make",
}

# Holder field -> relation. A job's ``hands_out_items`` is reached through a
# person's ``is_employed_as``, and a producer's ``produced_items`` through a
# place's ``operated_by``, as well as on the job or producer itself.
HOLDER_FIELDS = (
    ("inventory_items", "carries"),
    ("dispenses_items", "dispenses"),
    ("hands_out_items", "gives"),
    ("harvest_yields", "bears"),
    ("produced_items", "produces"),
)
REACHED_HOLDERS = ("is_employed_as", "operated_by")


@dataclass(frozen=True)
class NeedTag:
    tag_id: str
    label: str
    need: str
    # labels from this tag up to the one that names the need: ("Snack", "Food")
    chain: tuple


@dataclass(frozen=True)
class NeedLink:
    need: str
    # the tag label, or the field name for an inferred link
    tag: str
    # "local", "inherited" or "inferred"
    provenance: str
    # the entity the tag sits on: the thing itself or one of its categories
    source: str
    relation: str = "is"
    # ids from the asked entity to the thing that carries the tag
    path: tuple = ()
    chain: tuple = ()

    @property
    def action(self):
        return RELATION_ACTIONS[self.relation]

    @property
    def thing(self):
        return self.path[-1] if self.path else self.source


def _lookup_key(value):
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _entity(world_model, entity_id):
    getter = getattr(world_model, "get_entity", None)
    entity = getter(entity_id) if callable(getter) and entity_id else None
    return entity if isinstance(entity, dict) else None


def _label(world_model, entity_id):
    entity = _entity(world_model, entity_id) or {}
    return str(entity.get("pretty_name") or entity.get("name") or entity.get("common_name") or entity_id)


def _tag_entities(world_model):
    getter = getattr(world_model, "get_dataset", None)
    entities = getter(TAG_DATASET) if callable(getter) else None
    return [entity for entity in entities or [] if isinstance(entity, dict)]


def need_tag_index(world_model):
    """Every need tag, under each key a ``tags`` string may use for it."""
    by_id = {entity.get("id"): entity for entity in _tag_entities(world_model) if entity.get("id")}

    def resolve(tag_id):
        chain = []
        seen = set()
        current = by_id.get(tag_id)
        while current is not None and current.get("id") not in seen:
            seen.add(current.get("id"))
            chain.append(str(current.get("pretty_name") or current.get("name") or current.get("id")))
            need = str(current.get("serves_need") or "").strip().lower()
            if need in NEEDS:
                return need, tuple(chain)
            parent_ids = [parent for parent in entity_reference_ids(current.get("parents")) if parent in by_id]
            current = by_id.get(parent_ids[0]) if parent_ids else None
        return None, ()

    index = {}
    for tag_id, entity in by_id.items():
        if str(entity.get("tag_class") or "").strip().lower() != NEED_TAG_CLASS:
            continue
        need, chain = resolve(tag_id)
        if need is None:
            continue
        tag = NeedTag(tag_id, chain[0], need, chain)
        keys = {_lookup_key(entity.get(field)) for field in ("id", "name", "pretty_name")}
        keys.update(key[4:] for key in list(keys) if key.startswith("tag_"))
        for key in keys - {""}:
            index.setdefault(key, tag)
    return index


def _tag_links(entity, index, *, provenance, source):
    links = []
    for value in (entity or {}).get("tags") or []:
        tag = index.get(_lookup_key(value))
        if tag is not None:
            links.append(NeedLink(tag.need, tag.label, provenance, source, chain=tag.chain))
    return links


def _category_chain(world_model, entity):
    """The entity's categories and all their ancestors, nearest first."""
    order = []
    queue = list(category_ids(entity))
    while queue:
        category_id = queue.pop(0)
        if category_id in order:
            continue
        order.append(category_id)
        queue.extend(entity_reference_ids((_entity(world_model, category_id) or {}).get("parents")))
    return order


def _number(entity, field_name):
    try:
        return float(entity.get(field_name) or 0.0)
    except (TypeError, ValueError):
        return 0.0


# Needs read off a thing's own fields when no tag names them:
# (need, label, why, test).
INFERRED_NEEDS = (
    ("food", "food_satiation", "has food_satiation", lambda entity: _number(entity, "food_satiation") > 0.0),
    ("rest", "rest_quality", "has rest_quality", lambda entity: _number(entity, "rest_quality") > 0.0),
    # Anyone can be company; how much depends on who they are to the one asking.
    ("belonging", "company", "is a person",
     lambda entity: entity.get("type") == "person" or entity.get("_dataset") == "people"),
)
_INFERRED_REASONS = {label: reason for _need, label, reason, _test in INFERRED_NEEDS}


def own_need_links(entity, world_model, index=None):
    """How the entity itself relates to needs: its own tags, its categories' tags, its fields."""
    if not isinstance(entity, dict):
        return []
    index = need_tag_index(world_model) if index is None else index
    entity_id = str(entity.get("id") or "")
    links = _tag_links(entity, index, provenance="local", source=entity_id)
    for category_id in _category_chain(world_model, entity):
        links.extend(_tag_links(_entity(world_model, category_id), index, provenance="inherited", source=category_id))
    tagged_needs = {link.need for link in links}
    for need, label, _reason, test in INFERRED_NEEDS:
        if need not in tagged_needs and test(entity):
            links.append(NeedLink(need, label, "inferred", entity_id))
    return [
        NeedLink(link.need, link.tag, link.provenance, link.source, "is", (entity_id,), link.chain)
        for link in links
    ]


def _held_ids(holder, field_name):
    raw = (holder or {}).get(field_name)
    if field_name == "inventory_items":
        raw = [
            entry.get("item") or entry.get("item_id") if isinstance(entry, dict) else entry
            for entry in (raw if isinstance(raw, (list, tuple)) else [raw] if raw else [])
        ]
    return entity_reference_ids(raw)


def need_links(entity, world_model, need=None, index=None):
    """Every way the entity relates to a need: itself, or through what it holds, dispenses, gives or bears."""
    if not isinstance(entity, dict):
        return []
    index = need_tag_index(world_model) if index is None else index
    entity_id = str(entity.get("id") or "")
    links = list(own_need_links(entity, world_model, index))

    holders = [((entity_id,), entity)]
    for field_name in REACHED_HOLDERS:
        for holder_id in entity_reference_ids(entity.get(field_name)):
            holder = _entity(world_model, holder_id)
            if holder is not None:
                holders.append(((entity_id, holder_id), holder))
    for prefix, holder in holders:
        for field_name, relation in HOLDER_FIELDS:
            for held_id in _held_ids(holder, field_name):
                held = _entity(world_model, held_id)
                for link in own_need_links(held, world_model, index):
                    links.append(NeedLink(
                        link.need, link.tag, link.provenance, link.source,
                        relation, prefix + (held_id,), link.chain,
                    ))

    unique = {}
    for link in links:
        if need is None or link.need == need:
            unique.setdefault((link.need, link.relation, link.path, link.source, link.tag), link)
    return list(unique.values())


def explain(link, world_model):
    """One line saying why: 'food: dispenses Chips Bag, tagged Snack (Snack > Food)'."""
    if link.provenance == "inferred":
        reason = _INFERRED_REASONS.get(link.tag, f"has {link.tag}")
    elif link.provenance == "inherited":
        reason = f"category {_label(world_model, link.source)} tagged {link.tag}"
    else:
        reason = f"tagged {link.tag}"
    if len(link.chain) > 1:
        reason += f" ({' > '.join(link.chain)})"
    if link.relation == "is":
        return f"{link.need}: {reason}"
    via = ""
    if len(link.path) > 2:
        via = f" as {_label(world_model, link.path[-2])}"
    return f"{link.need}: {link.relation} {_label(world_model, link.thing)}{via}, {reason}"


_RELATION_ORDER = {"is": 0, "carries": 1, "dispenses": 2, "gives": 3, "bears": 4, "produces": 5}
_PROVENANCE_ORDER = {"local": 0, "inherited": 1, "inferred": 2}


def most_direct(links):
    """The link closest to the thing itself: its own tag before a held thing's, local before inherited."""
    return min(
        links,
        key=lambda link: (_RELATION_ORDER[link.relation], _PROVENANCE_ORDER.get(link.provenance, 3)),
        default=None,
    )


def brief(link, world_model):
    """A few words for a chip or a list row: 'Snack', 'via Foodstuff', 'dispenses Chips Bag'."""
    if link.relation == "is" and link.provenance == "inherited":
        return f"via {_label(world_model, link.source)}"
    if link.relation == "is":
        return link.tag
    return f"{link.relation} {_label(world_model, link.thing)}"


def need_summary(entity, world_model):
    """One short reason per need, the most direct one: [('food', 'dispenses Chips Bag'), ...]."""
    by_need = {}
    for link in need_links(entity, world_model):
        by_need.setdefault(link.need, []).append(link)
    return [(need, brief(most_direct(by_need[need]), world_model)) for need in NEEDS if need in by_need]
