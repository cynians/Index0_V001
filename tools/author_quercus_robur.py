"""Author a compact second tree representative for Species Sim comparisons."""

from __future__ import annotations

import json
from pathlib import Path

from simulations.species.plant_assets import PlantAssetStore, PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation
from world.entity_loader import EntityLoader
from tools.author_lolium_perenne import upsert


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPECIES_ID = "spec_quercus_robur"
FAMILY_ID = "cladis_fagaceae"
GENUS_ID = "cladis_quercus"


def main():
    loader = EntityLoader(
        entries_directory=PROJECT_ROOT / "entries",
        ontology_path=PROJECT_ROOT / "ontology" / "index0.owl",
        use_ontology=True,
    )
    upsert(loader, {
        "id": FAMILY_ID,
        "_dataset": "cladistics",
        "type": "cladistics",
        "name": "Fagaceae",
        "pretty_name": "Fagaceae",
        "parents": ["cladis_fagales"],
    })
    upsert(loader, {
        "id": GENUS_ID,
        "_dataset": "cladistics",
        "type": "cladistics",
        "name": "Quercus",
        "pretty_name": "Quercus",
        "parents": [FAMILY_ID],
    })
    species = upsert(loader, {
        "id": SPECIES_ID,
        "_dataset": "species",
        "type": "species",
        "common_name": "English Oak - Quercus robur",
        "pretty_name": "English Oak - Quercus robur",
        "binomial_name": "Quercus robur",
        "species_class": "natural_plant",
        "parents": [GENUS_ID],
        "plant_growth_form": "tree",
        "plant_growth_behaviour": "branched_woody",
        "plant_lifespan": "perennial",
        "plant_life_form": "phanerophyte",
        "plant_woodiness": "woody",
        "mature_height": {"min_m": 20.0, "max_m": 40.0},
        "mature_height_class": "canopy",
        "growth_rate": "moderate",
        "maturity_rate": "slow",
        "longevity_class": "very_long",
        "leaf_phenology": "deciduous",
        "leaf_size_class": "large",
        "leaf_arrangement": "alternate",
        "leaf_attachment_pattern": "along_stem",
        "leaf_clustering": "distributed",
        "plant_shoot_dimorphism": "long_and_short_shoots",
        "plant_leaf_distribution": "mixed_long_short_shoots",
        # Deliberately contrast the open, pendulous birch calibration:
        # denser twigging, a fuller crown, and less droop.
        "plant_leaf_spacing_bias": 0.52,
        "plant_branch_droop": 0.30,
        "plant_branch_angle_gradient": 0.34,
        "plant_crown_openness": 0.43,
        "plant_leaf_depth_gradient": 0.68,
        "plant_fine_twig_density": 0.92,
        "plant_leaf_cluster_density": 0.84,
        "photosynthesis_pathway": "c3",
        "root_architecture": "taproot",
        "root_depth_class": "deep",
        "reproductive_mode": "sexual",
        "seed_size_class": "large",
        "regeneration_strategy": "gap_recruitment",
        "nutrition_mode": "autotrophic",
        "mycorrhizal_type": "ectomycorrhizal",
        "shade_tolerance": "medium",
        "moisture_preference": "mesic",
        "waterlogging_tolerance": "medium",
        "salinity_tolerance": "low",
    })

    store = PlantAssetStore(PROJECT_ROOT / "assets" / "plants")
    blueprint = PlantBlueprint.from_species_entity(species, SPECIES_ID)
    simulation = SpeciesSimulation(species_entity=species, species_id=SPECIES_ID, seed=909, asset_store=store, blueprint=blueprint)
    simulation.set_age(simulation.mature_age_days)
    telemetry = simulation.simulate_days(5, environment={"light": 0.8, "water_available": 0.7}, sample_every_days=1)
    blueprint_path = simulation.bake_snapshot(store)
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
    print({
        "species_id": SPECIES_ID,
        "ontology_entity": species["pretty_name"],
        "blueprint": str(blueprint_path),
        "mature_stats": simulation.get_growth_summary(),
    })


if __name__ == "__main__":
    main()
