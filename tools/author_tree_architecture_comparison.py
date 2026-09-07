"""Author the intrinsic architecture fields for the three-tree comparison."""

import copy
import json
from pathlib import Path

from world.entity_loader import EntityLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONTINUOUS_ARCHITECTURE_FIELDS = (
    "plant_apical_control",
    "plant_leaf_spacing_bias",
    "plant_branch_droop",
    "plant_branch_angle_gradient",
    "plant_crown_openness",
    "plant_leaf_depth_gradient",
    "plant_fine_twig_density",
    "plant_leaf_cluster_density",
)


def calibration(minimum, typical, maximum, source="literature_guided_visual_calibration"):
    return {
        "min": minimum,
        "typical": typical,
        "max": maximum,
        "status": "provisional_visual_calibration",
        "source": source,
    }


def upgrade_legacy_points(entity):
    """Turn old point controls into honest, editable calibration envelopes."""
    for field_name in CONTINUOUS_ARCHITECTURE_FIELDS:
        value = entity.get(field_name)
        if value in (None, "") or isinstance(value, dict):
            continue
        typical = max(0.0, min(1.0, float(value)))
        entity[field_name] = calibration(
            round(max(0.0, typical - 0.10), 2),
            typical,
            round(min(1.0, typical + 0.10), 2),
            source="legacy_point_expanded_for_editor",
        )
    return entity


ARCHITECTURE_FIELDS = {
    "spec_betula_pendula": {
        "plant_axis_continuity": "sympodial",
        "plant_branching_rhythm": "diffuse",
        "plant_branching_timing": "mixed",
        "plant_lateral_axis_orientation": "plagiotropic",
        "plant_flowering_position": "mixed",
        "plant_apical_control": calibration(0.74, 0.82, 0.90),
        "plant_leaf_spacing_bias": calibration(0.62, 0.72, 0.82),
        "plant_branch_droop": calibration(0.66, 0.78, 0.90),
        "plant_branch_angle_gradient": calibration(0.56, 0.66, 0.76),
        "plant_crown_openness": calibration(0.70, 0.80, 0.90),
        "plant_leaf_depth_gradient": calibration(0.46, 0.56, 0.66),
        "plant_fine_twig_density": calibration(0.72, 0.82, 0.90),
        "plant_leaf_cluster_density": calibration(0.58, 0.68, 0.78),
    },
    "spec_quercus_robur": {
        "plant_axis_continuity": "monopodial",
        "plant_branching_rhythm": "continuous",
        "plant_branching_timing": "delayed",
        "plant_lateral_axis_orientation": "plagiotropic",
        "plant_flowering_position": "lateral",
        "plant_apical_control": calibration(0.32, 0.42, 0.54),
        "plant_leaf_spacing_bias": calibration(0.42, 0.52, 0.62),
        "plant_branch_droop": calibration(0.20, 0.30, 0.42),
        "plant_branch_angle_gradient": calibration(0.24, 0.34, 0.44),
        "plant_crown_openness": calibration(0.33, 0.43, 0.54),
        "plant_leaf_depth_gradient": calibration(0.58, 0.68, 0.78),
        "plant_fine_twig_density": calibration(0.82, 0.92, 0.98),
        "plant_leaf_cluster_density": calibration(0.74, 0.84, 0.92),
    },
    "spec_quercus_petraea": {
        "plant_axis_continuity": "monopodial",
        "plant_branching_rhythm": "continuous",
        "plant_branching_timing": "delayed",
        "plant_lateral_axis_orientation": "plagiotropic",
        "plant_flowering_position": "lateral",
        "plant_apical_control": calibration(0.36, 0.46, 0.58),
    },
}


HORSE_CHESTNUT = {
    "id": "spec_aesculus_hippocastanum",
    "_dataset": "species",
    "type": "species",
    "common_name": "Horse Chestnut - Aesculus hippocastanum",
    "pretty_name": "Horse Chestnut - Aesculus hippocastanum",
    "binomial_name": "Aesculus hippocastanum",
    "species_class": "natural_plant",
    "parents": ["cladis_soapberry_family_sapindaceae"],
    "plant_growth_form": "tree",
    "plant_growth_behaviour": "branched_woody",
    "plant_lifespan": "perennial",
    "plant_life_form": "phanerophyte",
    "plant_woodiness": "woody",
    "mature_height": {"min_m": 16.0, "max_m": 39.0},
    "mature_height_class": "canopy",
    "growth_rate": "moderate",
    "maturity_rate": "slow",
    "longevity_class": "long",
    "leaf_phenology": "deciduous",
    "leaf_size_class": "very_large",
    "leaf_structure": "palmately_compound",
    "leaf_arrangement": "opposite",
    "leaf_attachment_pattern": "terminal_cluster",
    "leaf_clustering": "tufted",
    "plant_shoot_dimorphism": "single_shoot_system",
    "plant_leaf_distribution": "terminal_cluster",
    "plant_axis_continuity": "monopodial_to_sympodial",
    "plant_branching_rhythm": "rhythmic",
    "plant_branching_timing": "delayed",
    "plant_lateral_axis_orientation": "mixed",
    "plant_flowering_position": "terminal",
    "plant_apical_control": calibration(0.50, 0.60, 0.70),
    # Normalised visual expressions of the categorical architecture above.
    "plant_leaf_spacing_bias": calibration(0.18, 0.28, 0.38),
    "plant_branch_droop": calibration(0.08, 0.16, 0.26),
    "plant_branch_angle_gradient": calibration(0.32, 0.42, 0.52),
    "plant_crown_openness": calibration(0.36, 0.46, 0.56),
    "plant_leaf_depth_gradient": calibration(0.62, 0.72, 0.82),
    "plant_fine_twig_density": calibration(0.24, 0.34, 0.44),
    "plant_leaf_cluster_density": calibration(0.66, 0.76, 0.86),
    "photosynthesis_pathway": "c3",
    "reproductive_mode": "sexual",
    "seed_size_class": "very_large",
    "clonal_spread": "none",
    "nutrition_mode": "autotrophic",
    "wiki_entry": (
        "# Horse chestnut\n\n"
        "*Aesculus hippocastanum* is a large deciduous tree with opposite, "
        "palmately compound leaves. Juvenile shoots extend monopodially; after "
        "sexual maturity, terminal inflorescences stop an axis and lateral buds "
        "continue it sympodially. Species Sim uses that transition to produce "
        "paired rhythmic scaffold branches, recurrent upper-crown forks, and "
        "large terminal leaf cohorts.\n\n"
        "Sources: https://besjournals.onlinelibrary.wiley.com/doi/10.1111/1365-2745.13116 ; "
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC3828942/"
    ),
}


def main():
    loader = EntityLoader(
        entries_directory=PROJECT_ROOT / "entries",
        ontology_path=PROJECT_ROOT / "ontology" / "index0.owl",
        use_ontology=True,
    )
    output = PROJECT_ROOT / "artifacts" / "tree_architecture_v001"
    output.mkdir(parents=True, exist_ok=True)
    target_ids = tuple(ARCHITECTURE_FIELDS) + (HORSE_CHESTNUT["id"],)
    before = {entity_id: copy.deepcopy(loader.entities.get(entity_id)) for entity_id in target_ids}
    backup = output / "ontology_fields_before.json"
    if not backup.exists():
        backup.write_text(json.dumps(before, indent=2), encoding="utf-8")

    authored = []
    for entity_id, fields in ARCHITECTURE_FIELDS.items():
        entity = loader.entities.get(entity_id)
        if not isinstance(entity, dict):
            if entity_id == "spec_quercus_petraea":
                continue
            raise RuntimeError(f"Missing live species: {entity_id}")
        entity.update(fields)
        upgrade_legacy_points(entity)
        if not loader.persist_entity(entity):
            raise RuntimeError(f"Could not persist {entity_id}")
        authored.append(entity_id)

    chestnut = loader.entities.get(HORSE_CHESTNUT["id"])
    chestnut = copy.deepcopy(chestnut) if isinstance(chestnut, dict) else {}
    chestnut.update(HORSE_CHESTNUT)
    upgrade_legacy_points(chestnut)
    if not loader.persist_entity(chestnut):
        raise RuntimeError("Could not persist horse chestnut")
    authored.append(chestnut["id"])
    print(json.dumps({"authored": authored}, indent=2))


if __name__ == "__main__":
    main()
