"""Places a person can be born at or live in: the location tree without its geology.

Locations nest through ``parent_location`` (else the first of ``parents``):
a star system holds a star, the star its planets, a planet continents,
countries, cities and buildings. Geologic units, material covers, deposits
and orbital space are locations too, but nobody is born in a rock unit, so
they are left out; a place whose parent is left out hangs from the nearest
kept ancestor (Earth hangs from the Sol System, not from the Sun).

A place may say when it existed (``start_year``/``end_year``); a person's
birth there is checked against it, not refused by it.
"""

from __future__ import annotations


PLACE_DATASETS = ("locations", "cities")
SKIPPED_CLASSES = frozenset({
    "geologic_unit", "surface_material_cover", "mineral_constituent_occurrence",
    "material_deposit", "orbital_space", "star", "biosphere_patch", "internal_passage",
})
SKIPPED_ROLES = frozenset({"generated_material_body"})
# Siblings list in this order, then by name.
CLASS_ORDER = (
    "star_system", "system", "cluster", "planet", "dwarf_planet", "moon", "asteroid",
    "space_station", "continent", "ocean", "island_chain", "atoll", "region", "macro_site",
    "country", "state", "city", "village", "quarter", "site", "building",
)

_CACHE = {}


def is_place(entity):
    if not isinstance(entity, dict) or not entity.get("id"):
        return False
    return (
        str(entity.get("location_class") or "") not in SKIPPED_CLASSES
        and str(entity.get("location_role") or "") not in SKIPPED_ROLES
    )


def _year(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parent_id(entity):
    parent = entity.get("parent_location")
    if isinstance(parent, str) and parent:
        return parent
    parents = entity.get("parents")
    if isinstance(parents, (list, tuple)):
        return next((item for item in parents if isinstance(item, str) and item), None)
    return parents if isinstance(parents, str) and parents else None


class PlaceTree:
    def __init__(self, world_model):
        getter = getattr(world_model, "get_dataset", None)
        locations = {}
        for dataset in PLACE_DATASETS:
            for entity in (getter(dataset) if callable(getter) else None) or []:
                if isinstance(entity, dict) and entity.get("id"):
                    locations.setdefault(entity["id"], entity)
        self.places = {place_id: entity for place_id, entity in locations.items() if is_place(entity)}
        self._parents = {}
        for place_id, entity in self.places.items():
            parent, seen = _parent_id(entity), {place_id}
            while parent and parent not in self.places and parent in locations and parent not in seen:
                seen.add(parent)
                parent = _parent_id(locations[parent])
            self._parents[place_id] = parent if parent in self.places and parent != place_id else None
        self._children = {}
        for place_id, parent in self._parents.items():
            self._children.setdefault(parent, []).append(place_id)
        for siblings in self._children.values():
            siblings.sort(key=self._sort_key)

    def _sort_key(self, place_id):
        place_class = self.place_class(place_id)
        rank = CLASS_ORDER.index(place_class) if place_class in CLASS_ORDER else len(CLASS_ORDER)
        return rank, self.label(place_id).casefold()

    def label(self, place_id):
        entity = self.places.get(place_id) or {}
        return str(entity.get("pretty_name") or entity.get("name") or place_id or "")

    def place_class(self, place_id):
        return str((self.places.get(place_id) or {}).get("location_class") or "")

    def parent(self, place_id):
        return self._parents.get(place_id)

    def children(self, place_id=None):
        """Places directly inside a place; with None, the places inside nothing."""
        return list(self._children.get(place_id, ()))

    def has_children(self, place_id):
        return bool(self._children.get(place_id))

    def chain(self, place_id):
        """The place and everything it lies in, outermost first."""
        chain, seen = [], set()
        while place_id in self.places and place_id not in seen:
            seen.add(place_id)
            chain.append(place_id)
            place_id = self._parents.get(place_id)
        return chain[::-1]

    def search(self, query, limit=60):
        """Places whose name holds the query, names starting with it first."""
        needle = str(query or "").strip().casefold()
        if not needle:
            return []
        found = []
        for place_id in self.places:
            name = self.label(place_id).casefold()
            if needle in name or needle in place_id.casefold():
                found.append((not name.startswith(needle), len(self.chain(place_id)), name, place_id))
        return [place_id for *_rank, place_id in sorted(found)[:limit]]

    def years(self, place_id):
        entity = self.places.get(place_id) or {}
        return _year(entity.get("start_year")), _year(entity.get("end_year"))

    def existed(self, place_id, year):
        """Whether the place stood in a year: True, False, or None when it does not say."""
        start, end = self.years(place_id)
        year = _year(year)
        if year is None or (start is None and end is None):
            return None
        return (start is None or start <= year) and (end is None or year <= end)

    def existence_text(self, place_id, year):
        start, end = self.years(place_id)
        span = f"{start if start is not None else '?'}-{end if end is not None else ''}".rstrip("-")
        state = self.existed(place_id, year)
        if state is None:
            return "no founding or end year recorded"
        if state:
            return f"stood then ({span})"
        if start is not None and _year(year) < start:
            return f"not founded until {start}"
        return f"gone by then (ended {end})"


def place_tree(world_model):
    """The place tree of a world model, rebuilt when its repository changes."""
    key = id(world_model)
    revision = getattr(world_model, "repository_revision", 0)
    cached = _CACHE.get(key)
    if cached is None or cached[0] != revision or cached[1] is not world_model:
        cached = (revision, world_model, PlaceTree(world_model))
        _CACHE.clear()
        _CACHE[key] = cached
    return cached[2]
