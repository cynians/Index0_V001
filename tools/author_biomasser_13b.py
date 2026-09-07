"""Author the fictional Biomasser 13B bootstrap lichen in the live ontology."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from world.entity_loader import EntityLoader


SPECIES_ID = "spec_biomasser_13b"


def build_entity(existing=None):
    entity = dict(existing or {})
    entity.update({
        "id": SPECIES_ID,
        "_dataset": "species",
        "type": "species",
        "common_name": "Biomasser 13B",
        "pretty_name": "Biomasser 13B",
        "binomial_name": "Biomasser construct 13B",
        "species_class": "engineered_lichen",
        "parents": ["cladis_rim_lichens_lecanora"],
        "base_stock_species": ["spec_lecanora_muralis"],
        "uses_technology": ["tech_telos_terraforming_envelope_and_lichen_origin_system"],
        "origin_type": "bioengineered",
        "species_simulation_enabled": True,
        "biosphere_bootstrap_species": True,
        "plant_growth_form": "lichen",
        "plant_growth_behaviour": "lichen_crust_radial",
        "plant_lifespan": "short_lived_perennial_colony",
        "plant_life_form": "surface_crust",
        "plant_woodiness": "non_woody",
        "mature_height": {"min_m": 0.002, "max_m": 0.018},
        "mature_height_class": "crust",
        "growth_rate": "very_fast_engineered",
        "maturity_rate": "very_fast",
        "longevity_class": "short",
        "reproductive_mode": "vegetative_fragments_and_spores",
        "dispersal": ["windborne_fragments", "surface_runoff", "human_placement"],
        "clonal_spread": "very_high",
        "regeneration_strategy": "rapid_surface_colonisation",
        "nutrition_mode": "lichen_symbiosis_phototrophic",
        "shade_tolerance": "medium",
        "moisture_preference": "broad_mesic_to_dry",
        "succession_roles": ["terraforming_bootstrap", "primary_pioneer", "soil_crust_builder"],
        "ecological_roles": ["primary_producer", "mineral_weathering", "biomass_accumulator", "surface_stabiliser"],
        "biosphere_growth_profile": {
            "seasonal_growth_rate": 0.58,
            "seasonal_dispersal": 0.21,
            "carrying_biomass_kg_m2": 3.2,
            "moisture_optimum": 0.38,
            "moisture_tolerance": 0.58,
            "light_minimum": 0.08,
            "calibration_status": "fictional_gameplay_design_value",
        },
        "establishment_requirements": {
            "requires_preexisting_biomass": False,
            "minimum_exposed_mineral_fraction": 0.05,
            "terraforming_role": "first_life_bootstrap",
        },
        "simulation_tier_default": "population_with_deep_representatives",
        "simulation_notes": (
            "Fictional engineered founding organism for lifeless but otherwise terraformed surfaces. "
            "BioSim coefficients are qualitative gameplay values, not empirical lichen measurements."
        ),
        "wiki_entry": (
            "# Biomasser 13B\n\n"
            "Biomasser 13B is a fictional bioengineered lichen-forming construct deployed by TELOS "
            "as a first biological foothold on terraformed, mineral-dominated surfaces. Its design "
            "prioritises broad moisture tolerance, rapid radial crust growth, mineral weathering and "
            "the accumulation of organic matter needed by later pioneer communities.\n\n"
            "In BioSim it is the only species initially unlocked in a lifeless founding patch. "
            "Its growth parameters are explicit gameplay assumptions and should not be read as "
            "measurements of a real organism."
        ),
        "card_color": "#77864b",
        "card_header_color": "#8da15b",
    })
    return entity


def main():
    loader = EntityLoader(
        entries_directory=PROJECT_ROOT / "entries",
        ontology_path=PROJECT_ROOT / "ontology" / "index0.owl",
        use_ontology=True,
    )
    entity = build_entity(loader.entities.get(SPECIES_ID))
    if not loader.persist_entity(entity):
        raise RuntimeError(f"Could not persist {SPECIES_ID}")
    print(f"Authored {SPECIES_ID} under cladis_rim_lichens_lecanora")


if __name__ == "__main__":
    main()
