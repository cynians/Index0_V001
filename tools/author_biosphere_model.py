"""Author the Biosphere ontology entity: a durable, reusable ecological
assemblage, distinct from the location/worldgen entity it overlays.

Per docs/conceptual_layer_overview_v006.txt section 20 ("BIOSPHERES AND
BIOSIM"), a Biosphere is the user-facing and ontology-facing term for a
reusable viable ecological assemblage -- species rosters, ecological soil
profile, stability notes -- overlaid on a location's geology/geometry rather
than replacing it. This pass builds the structural skeleton only: species
roster fields are wired to real selection/suitability code (see
simulations/bioregion/bioregion_simulation.py), soil profile fields are
generated from real worldgen data, but ecological-structure fields
(predator/prey, symbioses, behavior modules, ...) are deliberately inert
placeholders -- the same pattern as PersonSimulation.habits and
pop.growth_rate_stub -- until the species/population/behavior-module
simulation itself is built.

This is a one-way ontology authoring utility, following the same pattern as
tools/author_pop_system_model.py.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = PROJECT_ROOT / "ontology" / "index0.owl"


BIOSPHERE_SCHEMA_FIELDS = {
    "bioregion_subclass": {
        "type": "string", "section": "Classification", "optional": True,
        "description": "terrestrial (default) | river. River bioregions are reserved for the rolling-strip river corridor mode -- not implemented yet.",
    },
    "parent_biosphere": {
        "type": "entity", "target": "biospheres", "section": "Classification", "optional": True,
        "description": "Category/hierarchy nesting, mirroring pop.parent_pop and job.parent_job. A parent biosphere may summarize this one; this one may expand an abstract parent population into finer detail.",
    },
    "overlay_location": {
        "type": "entity", "target": "locations", "section": "Classification", "optional": True,
        "description": "The location (typically location_class=biosphere_patch) this Biosphere overlays for geology/geometry. Geology/geography stay on the location; biotic/ecological data stays here.",
    },
    "establishment_status": {
        "type": "string", "section": "Classification", "optional": True,
        "description": "draft | establishing | stable. A Biosphere becomes reusable as a recipe once its ecological structure is proven viable over an establishment period.",
    },
    "microfauna_species": {"type": "entity_list", "target": "species", "section": "Species Roster", "optional": True, "description": "Roster bucket -- see simulations/bioregion/bioregion_simulation.py BIOSPHERE_SPECIES_ROSTER_FIELDS."},
    "small_animal_species": {"type": "entity_list", "target": "species", "section": "Species Roster", "optional": True, "description": "Roster bucket."},
    "medium_animal_species": {"type": "entity_list", "target": "species", "section": "Species Roster", "optional": True, "description": "Roster bucket."},
    "large_animal_species": {"type": "entity_list", "target": "species", "section": "Species Roster", "optional": True, "description": "Roster bucket."},
    "megafauna_species": {"type": "entity_list", "target": "species", "section": "Species Roster", "optional": True, "description": "Roster bucket."},
    "sessile_life_species": {"type": "entity_list", "target": "species", "section": "Species Roster", "optional": True, "description": "Roster bucket -- plants, fungi, and other sessile life."},
    "area_soil_profile": {
        "type": "object", "section": "Soil Profile", "optional": True,
        "description": "The current local substrate as resolved from worldgen (regolith_soil_model): organic_layer, topsoil, subsoil, parent_material, moisture_capacity, ph, salinity, nutrients, microbial_activity, drainage, compaction, erosion_risk, root_depth_constraints. Generated once by BioregionSimulation, then user-editable.",
    },
    "biosphere_soil_profile": {
        "type": "object", "section": "Soil Profile", "optional": True,
        "description": "The soil state required, produced, or stabilized by this Biosphere's assemblage -- same shape as area_soil_profile. Defaults to a copy of area_soil_profile until the plant/soil co-development pass is built.",
    },
    "predator_prey_relations": {"type": "object_list", "section": "Ecological Structure", "optional": True, "description": "Inert placeholder -- ecological-structure simulation not built yet, same pattern as PersonSimulation.habits."},
    "symbioses": {"type": "object_list", "section": "Ecological Structure", "optional": True, "description": "Inert placeholder."},
    "competition_notes": {"type": "string", "section": "Ecological Structure", "optional": True, "description": "Inert placeholder."},
    "nest_colony_structures": {"type": "object_list", "section": "Ecological Structure", "optional": True, "description": "Inert placeholder."},
    "population_bands": {"type": "object_list", "section": "Ecological Structure", "optional": True, "description": "Inert placeholder."},
    "seasonal_pressures": {"type": "object_list", "section": "Ecological Structure", "optional": True, "description": "Inert placeholder."},
    "stability_notes": {"type": "string", "section": "Ecological Structure", "optional": True, "description": "Inert placeholder."},
    "failure_modes": {"type": "object_list", "section": "Ecological Structure", "optional": True, "description": "Inert placeholder."},
    "behavior_module_refs": {"type": "entity_list", "target": "behavior_modules", "section": "Ecological Structure", "optional": True, "description": "Inert placeholder -- full behavior-module inheritance system deferred past this pass."},
}


def _schema_name(entity):
    return str(entity.get("schema") or entity.get("name") or entity.get("id") or "").removeprefix("schema_")


def build_changes(datasets):
    schemas = {_schema_name(entity): dict(entity) for entity in datasets.get("schemas", []) if isinstance(entity, dict)}
    biospheres_by_id = {
        entity["id"]: entity
        for entity in datasets.get("biospheres", [])
        if isinstance(entity, dict) and entity.get("id")
    }
    locations_by_id = {
        entity["id"]: entity
        for entity in datasets.get("locations", [])
        if isinstance(entity, dict) and entity.get("id")
    }
    changes = []

    biosphere_schema = schemas.get("biosphere", {
        "id": "schema_biosphere", "_dataset": "schemas", "type": "schema",
        "entryId": "schema_biosphere", "datasetName": "schemas", "entityType": "schema",
        "pretty_name": "Biosphere", "schema": "biosphere", "name": "biosphere",
    })
    biosphere_schema["fields"] = {**(biosphere_schema.get("fields") or {}), **BIOSPHERE_SCHEMA_FIELDS}
    changes.append(biosphere_schema)

    changes.append({
        # apply_changes fully replaces stored properties -- carry any
        # existing authored fields forward rather than patching a bare
        # partial dict (see feedback_ontology_partial_writes memory).
        **biospheres_by_id.get("biosphere_cerrado_ecoregion", {
            "id": "biosphere_cerrado_ecoregion", "_dataset": "biospheres", "type": "biosphere",
        }),
        "name": "Cerrado Ecoregion Biosphere",
        "pretty_name": "Cerrado Ecoregion Biosphere",
        "bioregion_subclass": "terrestrial",
        "overlay_location": "loc_cerrado_ecoregion",
        "establishment_status": "draft",
        "wiki_entry": (
            "Durable Biosphere overlay for [[loc_cerrado_ecoregion]]. Structural skeleton demo entity: "
            "soil profile is generated from worldgen where available; ecological-structure fields "
            "(predator/prey, symbioses, behavior modules) remain inert placeholders pending the "
            "species/population/behavior-module simulation pass."
        ),
    })

    # Keep the reverse pointer in sync -- LaunchAffordanceResolver and
    # NavigationController.launch_biosphere_tab read biosphere_entity_id
    # directly off the location (same field the map-draft creation path in
    # MapSimulation.finish_spatial_feature_draft stamps), not a dataset scan.
    overlay_location_id = "loc_cerrado_ecoregion"
    overlay_location = locations_by_id.get(overlay_location_id)
    if overlay_location is not None and overlay_location.get("biosphere_entity_id") != "biosphere_cerrado_ecoregion":
        changes.append({
            **overlay_location,
            "biosphere_entity_id": "biosphere_cerrado_ecoregion",
        })

    return changes


def main():
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    changes = build_changes(store.load_datasets())
    result = store.apply_changes(entities=changes)
    print(f"Authored {result['upserted']} biosphere ontology entities")


if __name__ == "__main__":
    main()
