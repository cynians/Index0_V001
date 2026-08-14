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


def _mechanical_class(entity):
    material_id = str(entity.get("id") or "").lower()
    subclass = str(entity.get("material_subclass") or "").lower()
    category = str(entity.get("formation_category") or "").lower()
    classification = str(entity.get("scientific_classification") or "").lower()
    tags = {str(tag).lower() for tag in (entity.get("tags") or [])}
    text = " ".join((material_id, subclass, category, classification, " ".join(tags)))
    if "ice" in text or "frost" in text:
        return "massive_ice"
    if subclass in {"sediment", "soil", "regolith"} or any(word in text for word in ("sand", "silt", "clay", "gravel", "mud", "talus", "colluv", "alluv")):
        return "unconsolidated_sediment" if subclass == "sediment" else "regolith_or_weathering_mantle"
    if any(word in text for word in ("evaporite", "halite", "gypsum", "anhydrite")):
        return "weak_evaporite_rock"
    if any(word in text for word in ("limestone", "dolostone", "carbonate_rock", "marble")):
        return "strong_carbonate_rock"
    if any(word in text for word in ("metamorphic", "gneiss", "schist", "phyllite", "slate", "quartzite", "amphibolite")):
        return "foliated_metamorphic_rock"
    if any(word in text for word in ("volcanic", "basalt", "andesite", "rhyolite", "dacite", "diabase", "gabbro", "tuff", "lava")):
        return "jointed_volcanic_rock"
    if any(word in text for word in ("sedimentary", "sandstone", "shale", "mudstone", "siltstone", "conglomerate", "breccia")):
        return "weak_sedimentary_rock"
    if subclass in {"rock", "mineral"} or any(word in text for word in ("plutonic", "igneous", "granite", "diorite", "tonalite", "syenite", "monzonite")):
        return "massive_crystalline_rock"
    return "unresolved_geologic_material"


def author():
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
    store.export_rdfxml(ONTOLOGY_PATH)
    return records


if __name__ == "__main__":
    changed = author()
    unresolved = sum(item.get("mechanical_class") == "unresolved_geologic_material" for item in changed)
    print(f"Authored mechanical lithology for {len(changed)} ontology materials ({unresolved} unresolved).")
