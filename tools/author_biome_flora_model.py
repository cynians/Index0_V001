"""Author the biome-flora fields, the example plant collections, and a biome's assignment.

One-way ontology authoring utility for the flora of a planet's biomes
(``simulations/biosphere/flora.py``, docs/biosphere_worldgen_hookup_v001.md
section 3.7).

Without a subcommand, as one ``apply_changes`` transaction it

* extends ``schema_biosphere`` with the fields a biome's flora and a plant
  collection carry: ``collection_role``, the ``biome_*`` fields,
  ``plant_records`` and ``plant_collection``;
* writes the example plant collections (``COLLECTIONS``): species with a
  rarity each, to set a biome's flora by.

``assign`` sets the flora of the biomes found on a refined region by a
collection, for every biome of its planet that the region's ground shows:

    python tools/author_biome_flora_model.py --dry-run
    python tools/author_biome_flora_model.py
    python tools/author_biome_flora_model.py assign --region refined_lod4_e7fa59b8b3 \\
        --collection biosphere_collection_european_temperate_woodland \\
        --water-collection biosphere_collection_european_temperate_wetland

Entities are merged from their full current dict -- the store replaces whole
entities.  Re-runnable.  The application must be closed for a run that writes.
The ``.owl`` checkpoint is only exported with ``--export-checkpoint``.
"""

from __future__ import annotations

import argparse
import copy
import shutil
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore

ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"
BACKUP_ROOT = PROJECT_ROOT / "artifacts" / "biome_flora_model"

SECTION = "Biome Flora"

BIOSPHERE_FIELDS = {
    "collection_role": {
        "type": "string", "section": SECTION, "optional": True,
        "description": "'biome_flora': the extant plants of one biome of the planet in overlay_location. "
                       "'plant_collection': a named list of species with rarities, to set a biome's flora by. "
                       "Empty for any other biosphere.",
    },
    "biome_key": {
        "type": "string", "section": SECTION, "optional": True,
        "description": "The biome of a flora: its climate zone, with a water or height word where one exists "
                       "('Cfb', 'Cfb/wetland', 'Cfb/montane'). See simulations/biosphere/biomes.py.",
    },
    "biome_label": {
        "type": "string", "section": SECTION, "optional": True,
        "description": "The biome's name as shown ('Montane Temperate Oceanic wetland').",
    },
    "biome_climate": {
        "type": "string", "section": SECTION, "optional": True,
        "description": "The biome's Koppen class.",
    },
    "biome_climate_label": {
        "type": "string", "section": SECTION, "optional": True,
        "description": "The name of the biome's Koppen class.",
    },
    "biome_water": {
        "type": "string", "section": SECTION, "optional": True,
        "description": "The biome's water word: open_water, wetland or riverside; empty for ordinary ground.",
    },
    "biome_height": {
        "type": "string", "section": SECTION, "optional": True,
        "description": "The biome's height word: montane or alpine; empty below that.",
    },
    "plant_records": {
        "type": "object_list", "section": SECTION, "optional": True,
        "description": "One record per plant: species, rarity (dominant, common, occasional, rare), rarity_source "
                       "(gameplay: read off a Biosphere run; collection: set by a plant collection), and for a flora "
                       "the year it was established, the share of the living area it held and the site that was on.",
    },
    "plant_collection": {
        "type": "entity", "target": "biospheres", "section": SECTION, "optional": True,
        "description": "The plant collection a flora is set by. Its species are present at its rarities, sown or not; "
                       "the flora follows the collection when that is edited. Empty: the flora is what play established.",
    },
    "koppen_zone": {
        "type": "string", "section": SECTION, "optional": True,
        "description": "For a plant collection made for one climate zone (tools/author_zone_collections.py): its "
                       "Koppen class, such as Cfb or BSk. Empty for any other collection and for a flora.",
    },
}

# Example collections, from the plants authored so far.  Rarity is how much of
# the ground that suits a species it is met on: dominant all of it, common
# six tenths, occasional two tenths, rare a twentieth.
COLLECTIONS = {
    "biosphere_collection_european_temperate_woodland": {
        "name": "European Temperate Woodland and Meadow",
        "wiki_entry": (
            "A plant collection: oak and birch woods with bracken under them, and ryegrass meadow with its herbs "
            "between the woods. For a temperate biome on ordinary ground. Assign it to a biome's flora to have its "
            "species present there at these rarities."
        ),
        "rarities": {
            "spec_quercus_robur": "common",
            "spec_betula_pendula": "occasional",
            "spec_quercus_petraea": "occasional",
            "spec_pinus_sylvestris": "rare",
            "spec_aesculus_hippocastanum": "rare",
            "spec_pteridium_aquilinum": "common",
            "spec_philadelphus_coronarius": "occasional",
            "spec_lolium_perenne": "dominant",
            "spec_plantago_major": "common",
            "spec_cichorium_intybus": "occasional",
            "spec_cirsium_arvense": "occasional",
            "spec_lysimachia_arvensis": "occasional",
            "spec_torilis_arvensis": "rare",
        },
    },
    "biosphere_collection_european_temperate_wetland": {
        "name": "European Temperate Wetland",
        "wiki_entry": (
            "A plant collection: club-rush on soaked ground, white water lily on still water, a birch here and "
            "there. For the wetland, riverside and open-water biomes of a temperate climate."
        ),
        "rarities": {
            "spec_scirpus_sylvaticus": "dominant",
            "spec_nymphaea_alba": "common",
            "spec_betula_pendula": "occasional",
            "spec_empetrum_nigrum": "rare",
        },
    },
}


def _plain(entity):
    """Complete plain-dict copy (hydrates lazy projection wrappers first)."""

    materialize = getattr(entity, "materialize", None)
    if callable(materialize):
        entity = materialize()
    return copy.deepcopy(dict(entity))


def _by_id(datasets, dataset):
    return {entity.get("id"): entity for entity in datasets.get(dataset, []) if isinstance(entity, dict)}


def _biosphere_schema(datasets):
    for entity in datasets.get("schemas", []):
        if isinstance(entity, dict) and str(entity.get("schema") or entity.get("name") or "") == "biosphere":
            return entity
    raise RuntimeError("schema_biosphere is missing from the ontology")


def build_transaction(datasets):
    """The schema and the collections as upserts, without touching disk."""

    from simulations.biosphere.flora import plant_collection

    schema = _plain(_biosphere_schema(datasets))
    schema["fields"] = {**dict(schema.get("fields") or {}), **copy.deepcopy(BIOSPHERE_FIELDS)}
    upserts = [schema]
    species, stored = _by_id(datasets, "species"), _by_id(datasets, "biospheres")
    for collection_id, spec in COLLECTIONS.items():
        missing = sorted(set(spec["rarities"]) - set(species))
        if missing:
            raise RuntimeError(f"{collection_id}: species not in the ontology: {missing}")
        entity = _plain(stored[collection_id]) if collection_id in stored else {}
        entity.update(plant_collection(collection_id, spec["name"], spec["rarities"], spec["wiki_entry"]))
        entity.setdefault("entry_status", "draft")
        upserts.append(entity)
    return upserts


def region_biomes(region):
    """``[(biome, share of the region's ground)]``, the largest first."""

    import numpy as np

    from simulations.biosphere.biomes import biome_grid
    from simulations.city.city_site import city_bounds_m
    from simulations.map.worldgen_substrate import WorldgenSubstrate

    bounds = city_bounds_m(region)
    substrate = WorldgenSubstrate(region, bounds)
    columns = 160
    rows = max(2, round(columns * bounds["max_y"] / bounds["max_x"]))
    x, y = np.meshgrid((np.arange(columns) + 0.5) * bounds["max_x"] / columns,
                       (np.arange(rows) + 0.5) * bounds["max_y"] / rows)
    index, biomes = biome_grid(substrate, x, y)
    counts = Counter(index.ravel().tolist())
    return sorted(((biome, counts[number] / index.size) for number, biome in enumerate(biomes)),
                  key=lambda item: -item[1])


def build_assignment(datasets, region_id, collection_id, water_collection_id=None):
    """The floras of a region's biomes set by a collection, as upserts; and what was found, for the report."""

    from simulations.biosphere.flora import COLLECTION_ROLE, BiomeFlora

    locations, stored = _by_id(datasets, "locations"), _by_id(datasets, "biospheres")
    if region_id not in locations:
        raise RuntimeError(f"no location {region_id}")
    region = _plain(locations[region_id])
    planet_id = region.get("refinement_root_planet_id") or region.get("terrain_root_planet_id")
    if not planet_id or planet_id not in locations:
        raise RuntimeError(f"{region_id} is not a refined region of a planet")
    planet = locations[planet_id]
    collections = {}
    for given in {collection_id, water_collection_id or collection_id}:
        if given not in stored or stored[given].get("collection_role") != COLLECTION_ROLE:
            raise RuntimeError(f"{given} is not a plant collection in the ontology (run this tool without a subcommand first)")
        collections[given] = _plain(stored[given])
    upserts, report = [], []
    for biome, share in region_biomes(region):
        chosen = collections[(water_collection_id or collection_id) if biome.water else collection_id]
        flora = BiomeFlora(str(planet_id), biome)
        existing = _plain(stored[flora.entity_id]) if flora.entity_id in stored else None
        if existing is not None:
            flora = BiomeFlora.from_entity(existing)
        flora.assign_collection(chosen)
        entity = flora.to_entity(existing, planet.get("pretty_name") or planet.get("name"))
        entity.setdefault("entry_status", "draft")
        upserts.append(entity)
        report.append((biome, share, chosen["id"], flora))
    return upserts, report


def _backup(store, upserts, remove_entity_ids=()):
    """Keep what this run replaces or removes, not a copy of the whole store (``tools/ontology_backup.py``)."""
    from tools.ontology_backup import backup_entities

    return backup_entities(store, BACKUP_ROOT, upserts, remove_entity_ids)


def _write(store, upserts, export_checkpoint):
    backup_dir = _backup(store, upserts)
    print(f"backup: {backup_dir}")
    started = time.perf_counter()
    result = store.apply_changes(entities=upserts)
    print(f"applied in {time.perf_counter() - started:.2f}s: {result}")
    stored = _by_id(store.load_datasets(), "biospheres")
    for entity in upserts:
        if entity.get("_dataset") == "biospheres":
            kept = _plain(stored[entity["id"]])
            assert kept.get("plant_records") == entity["plant_records"], f"{entity['id']} was not stored whole"
    # The datasets above are read through the store's cache, which is patched on every write.  A write made while
    # another process has the store open has been seen to reach that cache and not the database: look there too.
    connection = sqlite3.connect(f"file:{store.database_path}?mode=ro", uri=True)
    try:
        for entity in upserts:
            found = connection.execute("SELECT 1 FROM resources WHERE iri LIKE ?", (f"%/{entity['id']}",)).fetchone()
            assert found, (f"{entity['id']} is not in the database although the write was reported done; "
                           "close every other program that has the ontology open and run this again")
    finally:
        connection.close()
    fields = _biosphere_schema(store.load_datasets()).get("fields", {})
    assert all(name in fields for name in BIOSPHERE_FIELDS), "schema_biosphere lacks the biome-flora fields"
    print("validated")
    if export_checkpoint:
        store.export_rdfxml(ONTOLOGY_PATH)
        print("checkpoint exported")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report the transaction without writing")
    parser.add_argument("--export-checkpoint", action="store_true",
                        help="also export ontology/index0.owl (slow; captures every session's pending edits)")
    commands = parser.add_subparsers(dest="command")
    assign = commands.add_parser("assign", help="set the flora of a region's biomes by a plant collection")
    assign.add_argument("--region", required=True, help="id of a refined region; its ground shows which biomes there are")
    assign.add_argument("--collection", required=True, help="the plant collection for ordinary ground")
    assign.add_argument("--water-collection", help="the collection for wetland, riverside and open water (default: the same)")
    assign.add_argument("--dry-run", action="store_true", dest="assign_dry_run", help="report without writing")
    args = parser.parse_args(argv)
    dry_run = args.dry_run or getattr(args, "assign_dry_run", False)

    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    if args.command == "assign":
        upserts, report = build_assignment(datasets, args.region, args.collection, args.water_collection)
        for biome, share, collection_id, flora in report:
            print(f"  {share:6.1%}  {biome.key:26s} {biome.label:42s} <- {collection_id}  ({len(flora.records)} plants)")
    else:
        before = set(_biosphere_schema(datasets).get("fields") or {})
        upserts = build_transaction(datasets)
        print(f"schema_biosphere: {len(before)} -> {len(upserts[0]['fields'])} fields; adds {sorted(set(upserts[0]['fields']) - before)}")
        for entity in upserts[1:]:
            print(f"collection {entity['id']}: {len(entity['plant_records'])} plants")
            for record in entity["plant_records"]:
                print(f"    {record['rarity']:10s} {record['species']}")
    if dry_run:
        return
    _write(store, upserts, args.export_checkpoint)


if __name__ == "__main__":
    main()
