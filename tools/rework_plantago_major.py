"""Rework spec_plantago_major from the legacy worldgen-suitability schema to
the active Species Sim functional plant-trait schema (world/plant_traits.py).

The stub carried an older field set (plant_growth_form="perennial_forb_rosette",
worldgen_suitability_profile, biosphere_growth_profile, light_tolerance,
moisture_tolerance, soil_texture_tolerance, soil_drainage_tolerance,
soil_ph_tolerance, temperature_tolerance_c, frost_tolerance_c,
disturbance_tolerance, trampling_tolerance, altitude_tolerance_m,
establishment_requirements, rooting_profile, reproductive_strategy,
dispersal_vectors, succession_roles, pollination_vectors,
biotic_interactions, simulation_notes, plant_life_cycle, reproduction_type,
origin_type, morphological_traits, ecological_roles,
simulation_tier_default). All of those keys are either in
world.plant_traits.PLANT_LEGACY_FIELDS or otherwise absent from
PLANT_TRAIT_SCHEMA_FIELDS, so ui/card.py already hides them and
world/schema_loader.py already excludes them from the resolved species
schema; they were simply inert. worldgen_suitability_profile was the one
live consumer (simulations/bioregion/bioregion_simulation.py), but every
other authored species (oak, birch, ryegrass, water lily, rose) already
omits it, so dropping it just brings this entity in line with its siblings
rather than removing working behaviour.

This script replaces the entity outright (not a partial merge) so the
legacy keys are actually removed rather than shadowed.
"""

from __future__ import annotations

import json
from pathlib import Path

from simulations.species.plant_assets import PlantAssetStore, PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation
from world.entity_loader import EntityLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECIES_ID = "spec_plantago_major"
GENUS_ID = "cladis_plantains_plantago"


def main():
    loader = EntityLoader(
        entries_directory=PROJECT_ROOT / "entries",
        ontology_path=PROJECT_ROOT / "ontology" / "index0.owl",
        use_ontology=True,
    )
    current = loader.entities.get(SPECIES_ID)
    if not isinstance(current, dict):
        raise RuntimeError(f"Missing existing plant card: {SPECIES_ID}")

    species = {
        "id": SPECIES_ID,
        "_dataset": "species",
        "type": "species",
        "common_name": "Broadleaf Plantain - Plantago major",
        "pretty_name": "Broadleaf Plantain - Plantago major",
        "binomial_name": "Plantago major",
        "species_class": "natural_plant",
        "parents": [GENUS_ID],
        # Cosmetic fields carried over unchanged from the original stub.
        "card_color": current.get("card_color", "#4f7d3a"),
        "card_header_color": current.get("card_header_color", "#263f28"),
        "wiki_field_colors": current.get("wiki_field_colors", {"default": "#b9d69c"}),
        "plant_growth_form": "forb",
        "plant_growth_behaviour": "rosette_short_internode",
        "plant_lifespan": "perennial",
        "plant_life_form": "hemicryptophyte",
        "plant_woodiness": "herbaceous",
        "mature_height": {"min_m": 0.05, "max_m": 0.40},
        "mature_height_class": "low",
        "growth_rate": "fast",
        "maturity_rate": "fast",
        "longevity_class": "moderate",
        "leaf_phenology": "deciduous",
        "leaf_size_class": "medium",
        "leaf_structure": "simple",
        "leaf_arrangement": "basal",
        "leaf_attachment_pattern": "basal_rosette",
        "leaf_clustering": "rosette",
        "plant_shoot_dimorphism": "single_shoot_system",
        "plant_leaf_distribution": "basal_rosette",
        "photosynthesis_pathway": "c3",
        "root_architecture": "fibrous",
        "root_depth_class": "shallow",
        "reproductive_mode": "sexual",
        "seed_size_class": "tiny",
        "clonal_spread": "low",
        "regeneration_strategy": "disturbance_colonization",
        "nitrogen_fixation": "none",
        "nutrition_mode": "autotrophic",
        "mycorrhizal_type": "arbuscular",
        "shade_tolerance": "medium",
        "moisture_preference": "mesic",
        "waterlogging_tolerance": "low",
        "frost_tolerance": {"min_c": -39},
        "salinity_tolerance": "medium",
        "wiki_entry": (
            "# Broadleaf plantain\n\n"
            "*Plantago major* is a herbaceous perennial forb: broad ovate "
            "leaves sit in a basal rosette above a fibrous root system, and "
            "narrow, leafless flowering spikes rise above the rosette and are "
            "wind-pollinated. It is a classic pioneer of disturbed, compacted "
            "ground - lawns, roadsides, pastures, and footpaths - where its "
            "low rosette tolerates trampling and mowing that taller "
            "competitors cannot. Seeds are tiny and persist in the soil seed "
            "bank; they also disperse by adhering to feet, fur, and tires, "
            "which suits a species that specializes in human- and "
            "animal-tracked ground. It tolerates a broad range of soils and "
            "moisture but is intolerant of prolonged waterlogging and is "
            "overtopped once shade or dense tall vegetation develops."
        ),
    }

    if not loader.persist_entity(species):
        raise RuntimeError(f"Could not persist {SPECIES_ID}")
    loader.export_ontology_checkpoint()

    asset_store = PlantAssetStore(PROJECT_ROOT / "assets" / "plants")
    blueprint = PlantBlueprint.from_species_entity(species, SPECIES_ID)
    simulation = SpeciesSimulation(species_entity=species, species_id=SPECIES_ID, seed=707, asset_store=asset_store, blueprint=blueprint)
    simulation.set_age(simulation.mature_age_days)
    telemetry = simulation.simulate_days(5, environment={"light": 0.75, "water_available": 0.55}, sample_every_days=1)
    blueprint_path = simulation.bake_snapshot(asset_store)
    telemetry_path = PROJECT_ROOT / "assets" / "plants" / "telemetry" / f"{SPECIES_ID}_5day.json"
    telemetry_path.parent.mkdir(parents=True, exist_ok=True)
    telemetry_path.write_text(json.dumps({
        "species_id": SPECIES_ID,
        "simulation": "species",
        "seed": simulation.seed,
        "blueprint": blueprint.to_dict(),
        "telemetry": telemetry,
        "snapshot": simulation.render_snapshot.to_dict(),
        "blueprint_path": str(blueprint_path),
    }, indent=2), encoding="utf-8")

    dropped_keys = sorted(set(current.keys()) - set(species.keys()))
    print(json.dumps({
        "species_id": SPECIES_ID,
        "ontology_entity": species["pretty_name"],
        "dropped_legacy_keys": dropped_keys,
        "blueprint": str(blueprint_path),
        "mature_stats": simulation.get_growth_summary(),
    }, indent=2))


if __name__ == "__main__":
    main()
