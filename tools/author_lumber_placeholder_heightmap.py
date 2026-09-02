"""Author standalone placeholder heightmaps for the lumber site and its surrounds.

One-way ontology authoring utility, same pattern as
tools/author_person_food_ownership_model.py and
tools/author_lumber_logistics_model.py.

The lumber test site has no generated-planet ancestor to inherit a real
heightmap from (see simulations/world_gen/local_placeholder_heightmap.py for
why), so this generates deterministic standalone relief instead, for the site
itself and for a new, larger location_lumber_region_surrounds location that
also backs the road-corridor window in simulations/map/road_corridor_window.py.

apply_changes fully replaces an entity's stored properties (see
world/persistent_ontology_store.py's _replace_entity), so any change to an
existing entity here carries its current full field set forward rather than
patching in isolation.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore
from simulations.world_gen.local_placeholder_heightmap import (
    LUMBER_AREA_SEED,
    build_placeholder_heightmap,
)


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"

SITE_ID = "location_lumber_test_site"
SURROUNDS_ID = "location_lumber_region_surrounds"

# The surrounding region pads generously past the site's own ~145m x 145m
# bounds so it reads as a distinct, coarser context (and gives the
# road-corridor window in Part 6 room to slide slices around within it).
SURROUNDS_BOUNDS = {"type": "bbox", "min_x": -145.0, "max_x": 150.0, "min_y": -165.0, "max_y": 130.0}


def build_changes(datasets):
    locations_by_id = {
        entity["id"]: entity
        for entity in datasets.get("locations", [])
        if isinstance(entity, dict) and entity.get("id")
    }

    site = dict(locations_by_id.get(SITE_ID, {"id": SITE_ID, "_dataset": "locations", "type": "location"}))
    site_bounds = site.get("bounds") or {"type": "bbox", "min_x": -70.0, "max_x": 75.0, "min_y": -90.0, "max_y": 55.0}
    site["heightmap_model"] = build_placeholder_heightmap(site_bounds, LUMBER_AREA_SEED, resolution=33)

    surrounds = dict(locations_by_id.get(SURROUNDS_ID, {
        "id": SURROUNDS_ID, "_dataset": "locations", "type": "location",
        "name": "Lumber Site Surrounding Region", "pretty_name": "Lumber Site Surrounding Region",
        "location_class": "generated_region", "site_class": "regional context",
        "map_coordinate_space": "site_meters",
        "associated_locations": [SITE_ID],
        "wiki_entry": (
            "Standalone placeholder regional relief covering the lumber test site "
            "and its immediate surrounds, generated from deterministic meter-space "
            "noise rather than inherited from a generated planet. Backs the "
            "road-corridor crawling-map window used to test map interaction along "
            "the east road toward North Road Village."
        ),
    }))
    surrounds["bounds"] = SURROUNDS_BOUNDS
    surrounds["heightmap_model"] = build_placeholder_heightmap(SURROUNDS_BOUNDS, LUMBER_AREA_SEED, resolution=65)

    return [site, surrounds]


def main():
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets())
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} lumber placeholder heightmap entities")


if __name__ == "__main__":
    main()
