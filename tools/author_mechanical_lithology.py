"""Author reduced mechanical-rock properties onto ontology materials.

This is a one-time ontology migration. Runtime world generation reads these
facts through its startup cache and contains no parallel material-class table.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = ROOT / "ontology" / "index0.owl"

PROFILES = {
    "unconsolidated_sediment": dict(bulk_density_kg_m3=2050, cohesion_mpa=0.05, friction_angle_deg=31, tensile_strength_mpa=0.01, erodibility_index=0.93, permeability_index=0.78, slope_resistance_index=0.12, fracture_density_index=0.05, elastic_strength_index=0.10, fabric="granular_unconsolidated"),
    "weak_sedimentary_rock": dict(bulk_density_kg_m3=2420, cohesion_mpa=6, friction_angle_deg=30, tensile_strength_mpa=1.4, erodibility_index=0.72, permeability_index=0.55, slope_resistance_index=0.34, fracture_density_index=0.46, elastic_strength_index=0.32, fabric="bedded"),
    "strong_carbonate_rock": dict(bulk_density_kg_m3=2700, cohesion_mpa=24, friction_angle_deg=36, tensile_strength_mpa=5.5, erodibility_index=0.38, permeability_index=0.62, slope_resistance_index=0.72, fracture_density_index=0.58, elastic_strength_index=0.68, fabric="bedded_jointed"),
    "massive_crystalline_rock": dict(bulk_density_kg_m3=2720, cohesion_mpa=34, friction_angle_deg=40, tensile_strength_mpa=8.5, erodibility_index=0.23, permeability_index=0.16, slope_resistance_index=0.86, fracture_density_index=0.38, elastic_strength_index=0.82, fabric="massive_crystalline"),
    "foliated_metamorphic_rock": dict(bulk_density_kg_m3=2780, cohesion_mpa=25, friction_angle_deg=34, tensile_strength_mpa=5.2, erodibility_index=0.41, permeability_index=0.28, slope_resistance_index=0.67, fracture_density_index=0.63, elastic_strength_index=0.65, fabric="foliated_anisotropic"),
    "jointed_volcanic_rock": dict(bulk_density_kg_m3=2850, cohesion_mpa=27, friction_angle_deg=39, tensile_strength_mpa=6.2, erodibility_index=0.35, permeability_index=0.42, slope_resistance_index=0.76, fracture_density_index=0.72, elastic_strength_index=0.71, fabric="jointed_volcanic"),
    "weak_evaporite_rock": dict(bulk_density_kg_m3=2250, cohesion_mpa=5, friction_angle_deg=28, tensile_strength_mpa=1.1, erodibility_index=0.82, permeability_index=0.34, slope_resistance_index=0.25, fracture_density_index=0.44, elastic_strength_index=0.25, fabric="bedded_soluble"),
    "regolith_or_weathering_mantle": dict(bulk_density_kg_m3=1850, cohesion_mpa=0.12, friction_angle_deg=30, tensile_strength_mpa=0.02, erodibility_index=0.88, permeability_index=0.68, slope_resistance_index=0.16, fracture_density_index=0.08, elastic_strength_index=0.12, fabric="granular_weathered"),
    "massive_ice": dict(bulk_density_kg_m3=920, cohesion_mpa=1.2, friction_angle_deg=18, tensile_strength_mpa=0.8, erodibility_index=0.58, permeability_index=0.04, slope_resistance_index=0.38, fracture_density_index=0.52, elastic_strength_index=0.28, fabric="polycrystalline_ice"),
    "unresolved_geologic_material": dict(bulk_density_kg_m3=2700, cohesion_mpa=18, friction_angle_deg=34, tensile_strength_mpa=5, erodibility_index=0.50, permeability_index=0.40, slope_resistance_index=0.55, fracture_density_index=0.45, elastic_strength_index=0.55, fabric="massive_or_unresolved"),
}


# Formation categories -> mechanical class.  Substring matching on ids and
# tags classified pumice and siliceous sinter as ice ("pum-ice", "sil-ice-ous"),
# sulfides as jointed volcanic rock (their ``volcanic_surface`` tag) and
# sandstone and shale as regolith ("sand"), so classes now follow the
# material's subclass and formation category.
MINERAL_CATEGORY_CLASSES = {
    "volatile_ice": "massive_ice",
    "evaporite_basin": "weak_evaporite_rock",
    "sulfur_surface": "weak_evaporite_rock",
    "carbonate_sedimentary_basin": "strong_carbonate_rock",
    "weathering_clay": "regolith_or_weathering_mantle",
    "residual_bauxite": "regolith_or_weathering_mantle",
    "iron_weathering": "regolith_or_weathering_mantle",
    "nickel_laterite": "regolith_or_weathering_mantle",
    "hydrated_alteration": "weak_sedimentary_rock",
}
ROCK_CATEGORY_CLASSES = {
    "igneous_extrusive_mafic": "jointed_volcanic_rock",
    "igneous_extrusive_intermediate": "jointed_volcanic_rock",
    "igneous_extrusive_felsic": "jointed_volcanic_rock",
    "igneous_hypabyssal_mafic": "jointed_volcanic_rock",
    "pyroclastic_deposit": "jointed_volcanic_rock",
    "volcanic_glass": "jointed_volcanic_rock",
    "igneous_intrusive_felsic": "massive_crystalline_rock",
    "igneous_intrusive_intermediate": "massive_crystalline_rock",
    "igneous_intrusive_alkaline": "massive_crystalline_rock",
    "igneous_mafic": "massive_crystalline_rock",
    "igneous_ultramafic": "massive_crystalline_rock",
    "kimberlite_pipe": "massive_crystalline_rock",
    "magmatic_carbonatite": "strong_carbonate_rock",
    "late_stage_pegmatite": "massive_crystalline_rock",
    "regional_metamorphism": "foliated_metamorphic_rock",
    "contact_metasomatic_skarn": "massive_crystalline_rock",
    "hydrated_alteration": "foliated_metamorphic_rock",
    "carbonate_sedimentary_basin": "strong_carbonate_rock",
    "spring_carbonate": "strong_carbonate_rock",
    "clastic_sedimentary_basin": "weak_sedimentary_rock",
    "evaporite_basin": "weak_evaporite_rock",
}
# Hard chain silicates filed under hydrated alteration.
MINERAL_CLASS_OVERRIDES = {
    "mat_amphibole": "massive_crystalline_rock",
    "mat_hornblende": "massive_crystalline_rock",
    "mat_epidote": "massive_crystalline_rock",
}
# Rocks whose mechanics differ from their formation category.
ROCK_CLASS_OVERRIDES = {
    "mat_marble": "strong_carbonate_rock",
    "mat_lapis_lazuli_marble": "strong_carbonate_rock",
    "mat_quartzite": "massive_crystalline_rock",
    "mat_hornfels": "massive_crystalline_rock",
    "mat_granulite": "massive_crystalline_rock",
    "mat_eclogite": "massive_crystalline_rock",
    "mat_anthracite": "weak_sedimentary_rock",
    "mat_chert": "massive_crystalline_rock",
    "mat_radiolarite": "massive_crystalline_rock",
    "mat_banded_iron_formation": "massive_crystalline_rock",
    "mat_chalk": "weak_sedimentary_rock",
    "mat_phosphorite": "weak_sedimentary_rock",
    "mat_diatomite": "weak_sedimentary_rock",
}


def _mechanical_class(entity):
    material_id = str(entity.get("id") or "").lower()
    subclass = str(entity.get("material_subclass") or "").lower()
    category = str(entity.get("formation_category") or "").lower()
    if subclass == "ice" or category == "volatile_ice":
        return "massive_ice"
    if subclass == "sediment":
        return "unconsolidated_sediment"
    if subclass in {"regolith", "soil"}:
        return "regolith_or_weathering_mantle"
    if subclass == "mineral":
        if material_id in MINERAL_CLASS_OVERRIDES:
            return MINERAL_CLASS_OVERRIDES[material_id]
        return MINERAL_CATEGORY_CLASSES.get(category, "massive_crystalline_rock")
    if subclass == "rock":
        if material_id in ROCK_CLASS_OVERRIDES:
            return ROCK_CLASS_OVERRIDES[material_id]
        return ROCK_CATEGORY_CLASSES.get(category, "massive_crystalline_rock")
    return "unresolved_geologic_material"


def author(export=False):
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    records = []
    for entity in datasets.get("materials") or []:
        if not isinstance(entity, dict) or entity.get("material_system_role") != "natural_geologic_material":
            continue
        mechanical_class = _mechanical_class(entity)
        replacement = dict(entity)
        replacement["mechanical_class"] = mechanical_class
        replacement["mechanical_rock_profile"] = dict(PROFILES[mechanical_class])
        records.append(replacement)
    if not records:
        raise RuntimeError("No natural geological material records found")
    if not store.persist_entities(records):
        raise RuntimeError("Could not persist mechanical lithology properties")
    if export:
        store.export_rdfxml(ONTOLOGY_PATH)
    return records


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true", help="Also rewrite the ontology .owl checkpoint.")
    changed = author(export=parser.parse_args().export)
    unresolved = sum(item.get("mechanical_class") == "unresolved_geologic_material" for item in changed)
    print(f"Authored mechanical lithology for {len(changed)} ontology materials ({unresolved} unresolved).")
