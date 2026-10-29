"""Author the first growth-form coverage set on existing plant cards.

The cards are already present in the live ontology.  This pass only writes the
canonical ``plant_growth_form`` field for the selected test representatives;
it does not migrate or preserve the old artefact vocabulary.  It also bakes a
small 3D-model-space preview product for each representative so the dropdown
values can be tested through the same Species Sim path.
"""

from __future__ import annotations

import json
from pathlib import Path

from simulations.species.plant_assets import PlantAssetStore, PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation
from world.entity_loader import EntityLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]

GROWTH_FORM_TEST_SET = {
    "spec_betula_pendula": "tree",
    "spec_rosa_woodsii": "shrub",
    "spec_praxelis_clematidea": "subshrub",
    "spec_erigeron_annuus": "forb",
    "spec_lolium_perenne": "graminoid",
    "spec_pteridium_aquilinum": "fern",
    "spec_agave_americana": "succulent",
    "spec_nymphaea_alba": "aquatic",
}

GROWTH_BEHAVIOUR_TEST_SET = {
    "spec_betula_pendula": "branched_woody",
    "spec_rosa_woodsii": "branched_woody",
    "spec_praxelis_clematidea": "iterative_indeterminate",
    "spec_erigeron_annuus": "iterative_indeterminate",
    "spec_lolium_perenne": "unbranched_single_axis",
    "spec_pteridium_aquilinum": "fern_fronding",
    "spec_agave_americana": "basal_succulent_rosette",
    "spec_nymphaea_alba": "determinate_sympodial",
}

# Broad mature-height envelopes make the human reference meaningful while
# leaving room for later species-specific refinement.
MATURE_HEIGHTS = {
    "spec_rosa_woodsii": ({"min_m": 0.6, "max_m": 2.5}, "medium"),
    "spec_praxelis_clematidea": ({"min_m": 0.4, "max_m": 1.0}, "medium"),
    "spec_erigeron_annuus": ({"min_m": 0.3, "max_m": 1.5}, "medium"),
    "spec_pteridium_aquilinum": ({"min_m": 0.6, "max_m": 2.0}, "medium"),
    "spec_agave_americana": ({"min_m": 1.0, "max_m": 2.0}, "medium"),
}


def main():
    loader = EntityLoader(
        entries_directory=PROJECT_ROOT / "entries",
        ontology_path=PROJECT_ROOT / "ontology" / "index0.owl",
        use_ontology=True,
    )
    asset_store = PlantAssetStore(PROJECT_ROOT / "assets" / "plants")
    results = []

    for species_id, growth_form in GROWTH_FORM_TEST_SET.items():
        species = loader.entities.get(species_id)
        if not isinstance(species, dict):
            raise RuntimeError(f"Missing existing plant card: {species_id}")
        species["plant_growth_form"] = growth_form
        species["plant_growth_behaviour"] = GROWTH_BEHAVIOUR_TEST_SET[species_id]
        if species_id in MATURE_HEIGHTS and not species.get("mature_height"):
            species["mature_height"], species["mature_height_class"] = MATURE_HEIGHTS[species_id]
        if not loader.persist_entity(species):
            raise RuntimeError(f"Could not persist growth form for {species_id}")

        blueprint = PlantBlueprint.from_species_entity(species, species_id)
        blueprint_path = asset_store.save_blueprint(blueprint)
        simulation = SpeciesSimulation(
            species_entity=species,
            species_id=species_id,
            seed=17,
            blueprint=blueprint,
            asset_store=asset_store,
        )
        simulation.set_age(simulation.mature_age_days)
        snapshot_path = asset_store.save_snapshot(simulation.render_snapshot)
        results.append({
            "species_id": species_id,
            "growth_form": growth_form,
            "shape": blueprint.growth.get("shape"),
            "growth_behaviour": blueprint.growth.get("growth_behaviour"),
            "model_space": blueprint.model_space,
            "placement_count": simulation.render_snapshot.stats.get("placement_count", 0),
            "blueprint": blueprint_path,
            "snapshot": snapshot_path,
        })

    print(json.dumps({"growth_form_test_set": results}, indent=2))


if __name__ == "__main__":
    main()
