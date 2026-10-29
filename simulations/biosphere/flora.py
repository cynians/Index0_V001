"""The plants a planet's biomes hold, and how common each is.

A planet's flora is kept biome by biome (``biomes``).  A species enters a
biome's flora when a Biosphere run establishes it there, with a rarity read
off that run: how much of the ground of its own layer it came to hold.  From
then on any map of that biome on that planet can show it: a city founded
there finds it growing, as often as it is common.

A *plant collection* is a named list of species with a rarity for each.  A
biome can be assigned one; its rarities then stand in place of the ones play
produced, and its species are present whether or not they were ever sown.
The assignment is the flora's ``plant_collection`` field: set on its card, or
by ``tools/author_biome_flora_model.py assign``, it takes hold the next time
the flora is looked at, and follows the collection when that is edited.

Both are Biosphere entities (dataset ``biospheres``), the ontology's record of
an ecological assemblage: a flora overlays its planet and names its biome, a
collection carries ``collection_role``.  ``tools/author_biome_flora_model.py``
puts their fields into the schema.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import re

from simulations.biosphere.biomes import Biome


# From most to least: a dominant makes up its layer, a rare plant is met here and there.
RARITIES = ("dominant", "common", "occasional", "rare")
# The share of the ground of its layer a species holds, from which it counts as each.
RARITY_FROM_SHARE = (("dominant", 0.50), ("common", 0.15), ("occasional", 0.03), ("rare", 0.0))
# The share of the ground that suits it on which a species of each rarity is met at all.
RARITY_GROUND_SHARE = {"dominant": 1.0, "common": 0.6, "occasional": 0.2, "rare": 0.05}

COLLECTION_ROLE = "plant_collection"
FLORA_ROLE = "biome_flora"


def ground_share_of(cover_share):
    """The share of the ground that suits it on which a species is met, from the share a played run measured.

    ``cover_share`` is the share of its layer's ground a run found the
    species holding.  The four rarities are steps on this line (a plant
    holding half its layer's ground is met everywhere that suits it, one
    holding three in a hundred on a fifth of it); a measured share is read
    off the line between them, so two plants a run left unequally common
    stay unequally common on every map made from it.
    """
    points = sorted((least, RARITY_GROUND_SHARE[rarity]) for rarity, least in RARITY_FROM_SHARE)
    share = max(0.0, float(cover_share))
    for (low, met_low), (high, met_high) in zip(points, points[1:]):
        if share <= high:
            return met_low + (met_high - met_low) * (share - low) / (high - low)
    return points[-1][1]


def rarity_from_share(share):
    """The rarity of a species that holds ``share`` of the ground of its layer."""
    share = float(share)
    return next(rarity for rarity, least in RARITY_FROM_SHARE if share >= least)


@dataclass
class PlantRecord:
    species_id: str
    rarity: str
    # "gameplay" for a rarity a Biosphere run produced, "collection" for one a collection set.
    rarity_source: str = "gameplay"
    established_year: int | None = None
    # The share of its layer's ground it held when last recorded, and the site that was on.
    cover_share: float | None = None
    site_id: str | None = None

    def to_dict(self):
        return {key: value for key, value in (
            ("species", self.species_id), ("rarity", self.rarity), ("rarity_source", self.rarity_source),
            ("established_year", self.established_year),
            ("cover_share", None if self.cover_share is None else round(float(self.cover_share), 4)),
            ("site", self.site_id),
        ) if value is not None}

    @classmethod
    def from_dict(cls, data):
        rarity = str(data.get("rarity") or "rare")
        return cls(
            species_id=str(data.get("species") or data.get("species_id")),
            rarity=rarity if rarity in RARITIES else "rare",
            rarity_source=str(data.get("rarity_source") or "gameplay"),
            established_year=data.get("established_year"), cover_share=data.get("cover_share"), site_id=data.get("site"),
        )


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


@dataclass
class BiomeFlora:
    """The extant plants of one biome of one planet."""

    planet_id: str
    biome: Biome
    records: dict[str, PlantRecord] = field(default_factory=dict)
    collection_id: str | None = None
    # The collection last applied, with what it held then: one set or edited since is applied again.
    applied: tuple | None = field(default=None, compare=False, repr=False)

    @property
    def entity_id(self):
        planet = _slug(re.sub(r"^(planet|loc)_", "", str(self.planet_id)))
        return f"biosphere_flora_{planet}_{_slug(self.biome.key)}"

    def rarity(self, species_id):
        record = self.records.get(species_id)
        return record.rarity if record is not None else None

    def ground_share(self, species_id):
        """The share of the ground that suits it on which a species is met here, or ``None`` for one not in the flora.

        What a played run measured of it (``ground_share_of``); for a
        species a collection set, or one entered without a measure, what
        its rarity stands for.
        """
        record = self.records.get(species_id)
        if record is None:
            return None
        if record.rarity_source != "collection" and record.cover_share is not None:
            return ground_share_of(record.cover_share)
        return RARITY_GROUND_SHARE[record.rarity]

    def species(self):
        """Its species, the commonest first."""
        return sorted(self.records, key=lambda species_id: (RARITIES.index(self.records[species_id].rarity),
                                                            -self.ground_share(species_id), species_id))

    def record(self, species_id, rarity, *, year=None, cover_share=None, site_id=None):
        """Enter a species as play established it, or bring its entry up to date.

        A rarity set by a collection is kept; only what play measured changes.
        Returns ``"entered"``, ``"changed"`` (its rarity moved) or ``None``.
        """
        if rarity not in RARITIES:
            raise ValueError(f"Unknown rarity: {rarity}")
        existing = self.records.get(species_id)
        if existing is None:
            self.records[species_id] = PlantRecord(species_id, rarity, "gameplay", year, cover_share, site_id)
            return "entered"
        existing.cover_share, existing.site_id = cover_share, site_id or existing.site_id
        if existing.established_year is None:
            existing.established_year = year
        if existing.rarity_source != "collection" and existing.rarity != rarity:
            existing.rarity = rarity
            return "changed"
        return None

    def assign_collection(self, collection):
        """Set the flora by a plant collection: its species are present, at its rarities.

        ``None`` takes the collection away.  What an earlier collection set
        and this one does not name goes with it, unless play established it
        meanwhile: that stays, as common as play left it.
        """
        self.collection_id = collection.get("id") if collection is not None else None
        self.applied = collection_signature(collection)
        given = [PlantRecord.from_dict(data) for data in (collection.get("plant_records") or [] if collection is not None else [])
                 if isinstance(data, dict)]
        named = {record.species_id for record in given}
        for species_id, record in list(self.records.items()):
            if record.rarity_source == "collection" and species_id not in named:
                if record.cover_share is None:
                    del self.records[species_id]
                else:
                    record.rarity, record.rarity_source = rarity_from_share(record.cover_share), "gameplay"
        for record in given:
            existing = self.records.get(record.species_id)
            self.records[record.species_id] = PlantRecord(
                record.species_id, record.rarity, "collection",
                existing.established_year if existing else None,
                existing.cover_share if existing else None, existing.site_id if existing else None,
            )

    def to_entity(self, stored=None, planet_name=None):
        """The flora as a Biosphere entity, on top of what is stored of it: the store replaces whole entities."""
        entity = copy.deepcopy(dict(stored or {}))
        name = f"{self.biome.label} flora of {planet_name or self.planet_id}"
        entity.update({
            "id": self.entity_id, "_dataset": "biospheres", "type": "biosphere",
            "name": name, "pretty_name": name,
            "collection_role": FLORA_ROLE, "overlay_location": self.planet_id,
            "biome_key": self.biome.key, "biome_label": self.biome.label,
            "biome_climate": self.biome.climate, "biome_climate_label": self.biome.climate_label,
            "biome_water": self.biome.water, "biome_height": self.biome.height,
            "establishment_status": "establishing" if self.records else "draft",
            "sessile_life_species": self.species(),
            "plant_records": [self.records[species_id].to_dict() for species_id in self.species()],
            "plant_collection": self.collection_id,
        })
        entity.setdefault("wiki_entry", (
            f"The plants established in the {self.biome.label} biome of [[{self.planet_id}]], "
            "each with how common it is there. Entered by Biosphere runs; a plant collection may set it instead."
        ))
        return entity

    @classmethod
    def from_entity(cls, entity):
        biome = Biome(str(entity.get("biome_climate") or ""), str(entity.get("biome_climate_label") or ""),
                      str(entity.get("biome_water") or ""), str(entity.get("biome_height") or ""))
        records = [PlantRecord.from_dict(data) for data in entity.get("plant_records") or [] if isinstance(data, dict)]
        return cls(str(entity.get("overlay_location")), biome, {record.species_id: record for record in records},
                   entity.get("plant_collection") or None)


def collection_signature(collection):
    """What a collection holds, to tell whether it changed; ``None`` for no collection."""
    if collection is None:
        return None
    return (collection.get("id"), tuple((data.get("species") or data.get("species_id"), data.get("rarity"))
                                        for data in collection.get("plant_records") or [] if isinstance(data, dict)))


def plant_collection(collection_id, name, rarities, wiki_entry=None):
    """A plant collection as a Biosphere entity: ``rarities`` maps species ids to rarities."""
    unknown = {rarity for rarity in rarities.values() if rarity not in RARITIES}
    if unknown:
        raise ValueError(f"Unknown rarity: {sorted(unknown)}")
    species = sorted(rarities, key=lambda species_id: (RARITIES.index(rarities[species_id]), species_id))
    return {
        "id": collection_id, "_dataset": "biospheres", "type": "biosphere",
        "name": name, "pretty_name": name, "collection_role": COLLECTION_ROLE,
        "establishment_status": "stable", "sessile_life_species": species,
        "plant_records": [{"species": species_id, "rarity": rarities[species_id], "rarity_source": "collection"}
                          for species_id in species],
        "wiki_entry": wiki_entry or "A plant collection: species with a rarity each, to set the flora of a biome by.",
    }


# ----------------------------------------------------------------------
# A planet's floras, read from the repository once and kept for the session
# ----------------------------------------------------------------------
def _holder(world_model):
    return getattr(world_model, "base_world", None) or world_model


def planet_floras(world_model, planet_id):
    """The floras of a planet by biome key; entered into as play goes on."""
    holder = _holder(world_model)
    try:
        planets = holder.__dict__.setdefault("_planet_floras", {})
    except AttributeError:
        return {}
    if planet_id not in planets:
        floras = {}
        dataset = getattr(holder, "get_dataset", lambda _name: [])("biospheres") or []
        for entity in dataset:
            if (isinstance(entity, dict) and entity.get("collection_role") == FLORA_ROLE
                    and entity.get("overlay_location") == planet_id):
                flora = BiomeFlora.from_entity(entity)
                floras[flora.biome.key] = flora
        planets[planet_id] = floras
    for flora in planets[planet_id].values():
        _follow_collection(holder, flora)
    return planets[planet_id]


def _follow_collection(holder, flora):
    """Hold a flora to the collection its entity names; where it is not stored yet, to the one it was given."""
    get_entity = getattr(holder, "get_entity", None)
    if not callable(get_entity):
        return
    stored = get_entity(flora.entity_id)
    named = stored.get("plant_collection") if stored is not None else flora.collection_id
    collection = get_entity(named) if named else None
    if collection_signature(collection) != flora.applied:
        flora.assign_collection(collection)
        save_flora(holder, flora)


def biome_flora(world_model, planet_id, biome):
    """The flora of one biome of a planet, begun empty the first time it is asked for."""
    floras = planet_floras(world_model, planet_id)
    if biome.key not in floras:
        floras[biome.key] = BiomeFlora(str(planet_id), biome)
    return floras[biome.key]


def save_flora(world_model, flora):
    """Write a flora to the repository where the session may; ``False`` where it lives in memory only."""
    holder = _holder(world_model)
    loader = getattr(holder, "loader", None)
    persist = getattr(loader, "persist_entity", None)
    if not callable(persist):
        return False
    get_entity = getattr(holder, "get_entity", lambda _id: None)
    stored = get_entity(flora.entity_id)
    materialize = getattr(stored, "materialize", None)
    stored = materialize() if callable(materialize) else stored
    planet = get_entity(flora.planet_id) or {}
    return bool(persist(flora.to_entity(stored, planet.get("pretty_name") or planet.get("name"))))
