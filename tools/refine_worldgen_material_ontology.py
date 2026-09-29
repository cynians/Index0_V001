"""Repair audited world-gen material records in the ontology.

The ontology is the durable material source.  This focused migration updates
the physical swatch, optical weathering profile, and formation contract for
the lithologies exposed by the Test 6 planetary material map.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulations.world_gen.material_affinities import material_affinity_profile
from simulations.world_gen.material_formation import formation_contract
from simulations.world_gen.material_optics import material_optical_surface_profile
from world.persistent_ontology_store import PersistentOntologyStore


AUDITED_DISPLAY_COLORS = {
    "mat_andesite": [112, 116, 104],
    "mat_silica_sand": [214, 207, 190],
    "mat_syenite": [166, 148, 132],
    "mat_granodiorite": [158, 154, 146],
    "mat_diorite": [112, 116, 112],
    "mat_granite": [174, 162, 146],
    "mat_tonalite": [148, 148, 142],
    "mat_monzonite": [142, 132, 116],
    "mat_nepheline_syenite": [172, 166, 148],
    "mat_diabase": [62, 72, 66],
    "mat_basalt": [72, 76, 70],
}

AUDITED_GEOLOGICAL_MAP_COLORS = {
    "mat_andesite": [179, 112, 99],
    "mat_silica_sand": [213, 190, 128],
    "mat_syenite": [155, 132, 166],
    "mat_granodiorite": [102, 139, 166],
    "mat_diorite": [94, 146, 146],
    "mat_granite": [184, 132, 143],
    "mat_tonalite": [138, 168, 180],
    "mat_monzonite": [190, 147, 104],
    "mat_nepheline_syenite": [130, 116, 154],
    "mat_diabase": [83, 127, 109],
    "mat_basalt": [70, 94, 115],
}


def _audited_record(entity):
    material_id = str(entity.get("id") or "")
    record = dict(entity)
    display_color = list(AUDITED_DISPLAY_COLORS[material_id])
    profile = material_affinity_profile(material_id) or {}
    profile_id = str(profile.get("profile_id") or "")
    formation = formation_contract(
        material_id,
        record.get("material_subclass"),
        profile_id,
    )
    requirements = {
        key: formation.get(key) or ([] if key != "local_minimums" else {})
        for key in (
            "required_all_planet_tags",
            "required_any_planet_tags",
            "host_formation_categories",
            "local_minimums",
            "valid_scale_levels",
        )
    }
    affinity = dict(record.get("surface_affinity_profile") or profile)
    affinity["formation_contract"] = dict(formation)

    record.update({
        "display_color": display_color,
        "geological_map_color": list(AUDITED_GEOLOGICAL_MAP_COLORS[material_id]),
        "formation_category": formation.get("category_id"),
        "formation_process": formation.get("formation_process"),
        "formation_contract_status": formation.get("status"),
        "spatial_representation": formation.get("spatial_representation"),
        "formation_requirements": requirements,
        "surface_affinity_profile": affinity,
        "optical_surface_profile": material_optical_surface_profile(
            material_id,
            formation_category=formation.get("category_id"),
            material_subclass=record.get("material_subclass"),
            display_color=display_color,
        ),
    })
    favorable = []
    for tag in (
        list(record.get("favorable_planet_tags") or [])
        + list(formation.get("required_all_planet_tags") or [])
        + list(formation.get("required_any_planet_tags") or [])
    ):
        if tag and tag not in favorable:
            favorable.append(tag)
    record["favorable_planet_tags"] = favorable
    return record


def refine_ontology():
    ontology_path = ROOT / "ontology" / "index0.owl"
    store = PersistentOntologyStore(ontology_path)
    by_id = {
        str(material.get("id") or ""): material
        for material in (store.load_datasets().get("materials") or [])
        if isinstance(material, dict)
    }
    records = []
    for material_id in AUDITED_DISPLAY_COLORS:
        if material_id not in by_id:
            raise KeyError(f"Missing ontology material: {material_id}")
        record = _audited_record(by_id[material_id])
        record["_dataset"] = "materials"
        record["type"] = "material"
        records.append(record)
    if not store.persist_entities(records):
        raise RuntimeError("Could not persist audited materials to ontology")
    store.export_rdfxml(ontology_path)
    return list(AUDITED_DISPLAY_COLORS)


if __name__ == "__main__":
    ontology_changed = refine_ontology()
    print(f"Refined {len(ontology_changed)} world-gen material ontology records.")
