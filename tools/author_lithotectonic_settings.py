"""Author lithotectonic setting weights onto ontology rock materials.

World generation classifies every map cell into fuzzy lithotectonic settings
(arc, collisional core, shield, platform, rift, ocean floor, ...).  Which rock
forms in which setting, and roughly what share of that setting's surface
bedrock it occupies, is a geological fact about the material.  This one-time
migration writes it to each material as ``lithotectonic_setting_weights``;
runtime world generation rebuilds setting recipes from the material catalog
cache and keeps no parallel table.

Weights are relative within a setting (they are renormalised over the
materials a planet's chemistry actually supports).

The live SQLite quadstore is updated.  Pass ``--export`` to also rewrite the
``ontology/index0.owl`` checkpoint (slow; it captures every pending mutation
in the shared local store).
"""

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from world.persistent_ontology_store import PersistentOntologyStore


ONTOLOGY_PATH = ROOT / "ontology" / "index0.owl"

# setting id -> {material id: typical relative share of exposed bedrock}
SETTING_RECIPES = {
    "oceanic_ridge": {
        "mat_basalt": 0.70, "mat_diabase": 0.12, "mat_gabbro": 0.10,
        "mat_peridotite": 0.03, "mat_serpentinite": 0.03, "mat_metabasalt": 0.02,
    },
    "abyssal_ocean_floor": {
        "mat_basalt": 0.45, "mat_chalk": 0.12, "mat_chert": 0.10,
        "mat_claystone": 0.10, "mat_radiolarite": 0.08, "mat_diatomite": 0.05,
        "mat_mudstone": 0.05, "mat_gabbro": 0.05,
    },
    "oceanic_plateau": {
        "mat_basalt": 0.75, "mat_diabase": 0.08, "mat_gabbro": 0.07,
        "mat_limestone": 0.04, "mat_tuff": 0.04, "mat_dunite": 0.02,
    },
    "island_arc": {
        "mat_andesite": 0.30, "mat_basalt": 0.25, "mat_tuff": 0.10,
        "mat_dacite": 0.08, "mat_diorite": 0.07, "mat_tonalite": 0.06,
        "mat_greywacke": 0.06, "mat_limestone": 0.04, "mat_ignimbrite": 0.04,
    },
    "continental_arc": {
        "mat_andesite": 0.22, "mat_granodiorite": 0.16, "mat_dacite": 0.10,
        "mat_ignimbrite": 0.08, "mat_tonalite": 0.08, "mat_granite": 0.08,
        "mat_rhyolite": 0.07, "mat_diorite": 0.07, "mat_welded_ignimbrite": 0.04,
        "mat_basalt": 0.04, "mat_monzonite": 0.03, "mat_hornfels": 0.03,
        "mat_latite": 0.02,
    },
    "forearc_accretionary": {
        "mat_greywacke": 0.30, "mat_mudstone": 0.14, "mat_shale": 0.12,
        "mat_chert": 0.08, "mat_phyllite": 0.08, "mat_blueschist": 0.06,
        "mat_serpentinite": 0.06, "mat_basalt": 0.06, "mat_slate": 0.06,
        "mat_sandstone": 0.04, "mat_radiolarite": 0.02, "mat_eclogite": 0.02,
    },
    "collisional_orogen_core": {
        "mat_gneiss": 0.26, "mat_schist": 0.18, "mat_granite": 0.14,
        "mat_migmatite": 0.10, "mat_amphibolite": 0.08, "mat_granulite": 0.06,
        "mat_marble": 0.05, "mat_quartzite": 0.05, "mat_pegmatite": 0.03,
        "mat_mylonite": 0.03, "mat_eclogite": 0.02,
    },
    "fold_thrust_belt": {
        "mat_limestone": 0.18, "mat_shale": 0.16, "mat_sandstone": 0.16,
        "mat_dolostone": 0.08, "mat_slate": 0.08, "mat_siltstone": 0.08,
        "mat_phyllite": 0.06, "mat_quartzite": 0.05, "mat_conglomerate": 0.04,
        "mat_marble": 0.03, "mat_cataclasite": 0.03, "mat_greywacke": 0.03,
        "mat_mylonite": 0.02, "mat_anthracite": 0.01,
    },
    "foreland_basin": {
        "mat_sandstone": 0.24, "mat_conglomerate": 0.14, "mat_shale": 0.14,
        "mat_siltstone": 0.12, "mat_mudstone": 0.10, "mat_red_bed_sandstone": 0.10,
        "mat_arkose": 0.06, "mat_claystone": 0.04, "mat_lignite": 0.03,
        "mat_calcareous_sandstone": 0.03,
    },
    "exposed_shield": {
        "mat_gneiss": 0.26, "mat_granite": 0.18, "mat_tonalite": 0.10,
        "mat_granodiorite": 0.08, "mat_migmatite": 0.07, "mat_granulite": 0.06,
        "mat_amphibolite": 0.05, "mat_greenschist": 0.04, "mat_metabasalt": 0.04,
        "mat_quartzite": 0.03, "mat_schist": 0.03, "mat_komatiite": 0.02,
        "mat_banded_iron_formation": 0.02, "mat_anorthosite": 0.02,
        "mat_pegmatite": 0.01, "mat_metaconglomerate": 0.01, "mat_soapstone": 0.01,
    },
    "continental_platform": {
        "mat_sandstone": 0.18, "mat_limestone": 0.18, "mat_shale": 0.18,
        "mat_dolostone": 0.08, "mat_siltstone": 0.08, "mat_mudstone": 0.06,
        "mat_claystone": 0.04, "mat_chalk": 0.04, "mat_red_bed_sandstone": 0.04,
        "mat_granite": 0.04, "mat_oolitic_limestone": 0.03, "mat_gneiss": 0.03,
        "mat_arkose": 0.02, "mat_ironstone": 0.01,
    },
    "intracratonic_basin": {
        "mat_shale": 0.20, "mat_sandstone": 0.16, "mat_limestone": 0.14,
        "mat_siltstone": 0.10, "mat_mudstone": 0.08, "mat_dolostone": 0.06,
        "mat_red_bed_sandstone": 0.05, "mat_claystone": 0.05, "mat_rock_salt": 0.03,
        "mat_gypsum_rock": 0.03, "mat_oil_shale": 0.03, "mat_chalk": 0.03,
        "mat_anhydrite_rock": 0.02, "mat_lignite": 0.02,
    },
    "continental_rift": {
        "mat_basalt": 0.22, "mat_arkose": 0.12, "mat_red_bed_sandstone": 0.10,
        "mat_conglomerate": 0.10, "mat_sandstone": 0.07, "mat_rhyolite": 0.06,
        "mat_mudstone": 0.06, "mat_trachyte": 0.05, "mat_diabase": 0.05,
        "mat_phonolite": 0.04, "mat_syenite": 0.03, "mat_rock_salt": 0.03,
        "mat_nepheline_syenite": 0.02, "mat_gypsum_rock": 0.02, "mat_claystone": 0.02,
        "mat_monzonite": 0.02, "mat_carbonatite": 0.01,
    },
    "passive_margin_shelf": {
        "mat_limestone": 0.20, "mat_sandstone": 0.16, "mat_shale": 0.16,
        "mat_mudstone": 0.08, "mat_dolostone": 0.07, "mat_chalk": 0.06,
        "mat_siltstone": 0.06, "mat_oolitic_limestone": 0.05,
        "mat_calcareous_sandstone": 0.05, "mat_coquina": 0.04, "mat_rock_salt": 0.02,
        "mat_phosphorite": 0.01,
    },
    "continental_hotspot": {
        "mat_basalt": 0.55, "mat_diabase": 0.10, "mat_trachyte": 0.07,
        "mat_rhyolite": 0.07, "mat_gabbro": 0.05, "mat_sandstone": 0.05,
        "mat_phonolite": 0.04, "mat_ignimbrite": 0.04, "mat_latite": 0.03,
    },
    "volcanic_plains": {
        "mat_basalt": 0.65, "mat_diabase": 0.08, "mat_andesite": 0.05,
        "mat_tuff": 0.05, "mat_gabbro": 0.05, "mat_komatiite": 0.04,
        "mat_dunite": 0.02, "mat_anorthosite": 0.02,
    },
    "ancient_highland_crust": {
        "mat_anorthosite": 0.35, "mat_gabbro": 0.15, "mat_basalt": 0.12,
        "mat_impact_breccia": 0.10, "mat_granulite": 0.08, "mat_gneiss": 0.06,
        "mat_dunite": 0.04, "mat_peridotite": 0.04, "mat_granite": 0.03,
    },
    "impact_basin": {
        "mat_impact_breccia": 0.45, "mat_basalt": 0.25, "mat_anorthosite": 0.08,
        "mat_gabbro": 0.06, "mat_cataclasite": 0.06, "mat_hornfels": 0.04,
        "mat_dunite": 0.03,
    },
}


# Cover materials that share a formation category but occupy distinct climate
# niches.  Merged into each card's ``surface_affinity_profile`` as
# (outer_low, ideal_low, ideal_high, outer_high) trapezoids.
COVER_CLIMATE_NICHES = {
    # Pedogenic carbonate: semi-arid, seasonally dry.
    "mat_calcrete": {"precipitation_mm": [80.0, 200.0, 550.0, 850.0], "temperature_k": [270.0, 283.0, 318.0, 335.0]},
    # Iron crust from seasonal tropical laterite weathering.
    "mat_ferricrete": {"precipitation_mm": [450.0, 800.0, 1700.0, 2600.0], "temperature_k": [283.0, 293.0, 320.0, 340.0]},
    # Mn-Fe varnish on stable hyper-arid pavements.
    "mat_rock_varnish": {"precipitation_mm": [0.0, 0.0, 220.0, 450.0], "temperature_k": [255.0, 275.0, 330.0, 350.0]},
}


# Where unconsolidated sediments accumulate.  Merged into each card's
# ``surface_affinity_profile.depositional_environments``.  Material LOD cover
# classes that are defined by landscape position (channel bed, floodplain,
# wet hollow, talus apron) select their catalogue materials by environment,
# because several of these cards share one formation category and profile.
DEPOSITIONAL_ENVIRONMENTS = {
    "mat_alluvium": ["channel_bed", "floodplain"],
    "mat_gravel": ["channel_bed", "alluvial_fan"],
    "mat_silt": ["floodplain", "wet_hollow"],
    "mat_lacustrine_mud": ["lake_floor", "wet_hollow"],
    "mat_marine_mud": ["marine_shelf"],
    "mat_clay": ["weathering_mantle", "wet_hollow"],
    "mat_beach_sand": ["shoreline"],
    "mat_dune_sand": ["dune_field"],
    "mat_loess": ["loess_mantle"],
    "mat_talus": ["talus_apron"],
    "mat_colluvium": ["footslope"],
    "mat_glacial_till": ["glacial_margin"],
}


# Rock-specific visible reflectance for lithologies whose cards still carried
# a formation-family default.  (fresh RGB, weathered RGB) are linear
# reflectance at 650/550/450 nm; values are representative hand-sample /
# outcrop endmembers, not single-crystal spectra.
OPTICAL_ENDMEMBERS = {
    "mat_arkose": ((0.36, 0.28, 0.22), (0.40, 0.29, 0.20), 0.29, "bedded", 0.28),
    "mat_greywacke": ((0.13, 0.135, 0.12), (0.17, 0.15, 0.12), 0.13, "bedded", 0.22),
    "mat_siltstone": ((0.22, 0.20, 0.17), (0.26, 0.22, 0.17), 0.20, "bedded", 0.36),
    "mat_claystone": ((0.21, 0.185, 0.16), (0.26, 0.20, 0.15), 0.19, "bedded", 0.30),
    "mat_conglomerate": ((0.25, 0.21, 0.17), (0.29, 0.22, 0.16), 0.22, "bedded", 0.18),
    "mat_calcareous_sandstone": ((0.42, 0.37, 0.30), (0.45, 0.38, 0.29), 0.37, "bedded", 0.30),
    "mat_dolostone": ((0.44, 0.41, 0.36), (0.47, 0.41, 0.33), 0.42, "bedded", 0.30),
    "mat_oolitic_limestone": ((0.55, 0.51, 0.43), (0.56, 0.50, 0.40), 0.51, "bedded", 0.26),
    "mat_coquina": ((0.50, 0.45, 0.36), (0.52, 0.45, 0.34), 0.45, "bedded", 0.22),
    "mat_chert": ((0.30, 0.28, 0.26), (0.33, 0.29, 0.25), 0.28, "bedded", 0.34),
    "mat_radiolarite": ((0.24, 0.13, 0.10), (0.26, 0.13, 0.09), 0.15, "bedded", 0.40),
    "mat_banded_iron_formation": ((0.20, 0.10, 0.08), (0.24, 0.10, 0.07), 0.12, "bedded", 0.60),
    "mat_ironstone": ((0.26, 0.15, 0.10), (0.28, 0.14, 0.08), 0.17, "bedded", 0.30),
    "mat_phosphorite": ((0.18, 0.16, 0.14), (0.21, 0.18, 0.14), 0.16, "bedded", 0.28),
    "mat_gypsum_rock": ((0.75, 0.73, 0.68), (0.74, 0.71, 0.64), 0.72, "bedded", 0.20),
    "mat_anhydrite_rock": ((0.62, 0.61, 0.58), (0.63, 0.60, 0.55), 0.60, "bedded", 0.20),
    "mat_amphibolite": ((0.09, 0.10, 0.09), (0.14, 0.11, 0.08), 0.095, "foliated", 0.30),
    "mat_blueschist": ((0.14, 0.16, 0.19), (0.17, 0.16, 0.15), 0.16, "foliated", 0.45),
    "mat_eclogite": ((0.16, 0.15, 0.12), (0.19, 0.15, 0.11), 0.15, "massive", 0.10),
    "mat_greenschist": ((0.15, 0.19, 0.14), (0.19, 0.19, 0.14), 0.17, "foliated", 0.45),
    "mat_metabasalt": ((0.11, 0.12, 0.10), (0.15, 0.12, 0.09), 0.11, "foliated", 0.20),
    "mat_granulite": ((0.20, 0.18, 0.16), (0.23, 0.19, 0.15), 0.18, "foliated", 0.18),
    "mat_migmatite": ((0.30, 0.27, 0.24), (0.33, 0.28, 0.23), 0.27, "foliated", 0.40),
    "mat_mylonite": ((0.16, 0.15, 0.14), (0.19, 0.16, 0.13), 0.15, "foliated", 0.60),
    "mat_cataclasite": ((0.20, 0.18, 0.15), (0.24, 0.19, 0.14), 0.18, "fragmental", 0.30),
    "mat_hornfels": ((0.10, 0.10, 0.10), (0.14, 0.11, 0.09), 0.10, "massive", 0.06),
    "mat_metaconglomerate": ((0.24, 0.21, 0.18), (0.27, 0.22, 0.17), 0.21, "foliated", 0.25),
    "mat_phyllite": ((0.20, 0.21, 0.20), (0.23, 0.21, 0.18), 0.20, "foliated", 0.50),
    "mat_pegmatite": ((0.55, 0.49, 0.44), (0.57, 0.49, 0.42), 0.50, "massive", 0.05),
    "mat_serpentinite": ((0.10, 0.14, 0.10), (0.14, 0.15, 0.11), 0.12, "foliated", 0.25),
    "mat_soapstone": ((0.33, 0.36, 0.32), (0.35, 0.36, 0.31), 0.34, "massive", 0.08),
    "mat_ignimbrite": ((0.34, 0.28, 0.24), (0.37, 0.29, 0.22), 0.29, "volcanic_flow", 0.18),
    "mat_carbonatite": ((0.45, 0.42, 0.32), (0.46, 0.41, 0.29), 0.41, "massive", 0.10),
    "mat_loess": ((0.40, 0.34, 0.26), (0.42, 0.35, 0.25), 0.33, "fragmental", 0.10),
}


def _optical_record(entity, endmember):
    from simulations.world_gen.material_optics import material_optical_surface_profile

    fresh, weathered, albedo, fabric, fabric_strength = endmember
    current = dict(entity.get("optical_surface_profile") or {})
    current.update({
        "visible_reflectance": {"red_650nm": fresh[0], "green_550nm": fresh[1], "blue_450nm": fresh[2]},
        "weathered_visible_reflectance": {"red_650nm": weathered[0], "green_550nm": weathered[1], "blue_450nm": weathered[2]},
        "broadband_albedo": albedo,
        "surface_fabric": fabric,
        "surface_fabric_strength": fabric_strength,
    })
    profile = material_optical_surface_profile(
        entity.get("id"),
        formation_category=entity.get("formation_category"),
        material_subclass=entity.get("material_subclass"),
        display_color=entity.get("display_color"),
        explicit=current,
    )
    profile["source_kind"] = "material_override"
    return profile


def material_setting_weights():
    """Invert the recipe table into per-material setting weights."""
    weights = {}
    for setting_id, recipe in SETTING_RECIPES.items():
        for material_id, weight in recipe.items():
            weights.setdefault(material_id, {})[setting_id] = float(weight)
    return weights


def author(export=False):
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    materials = {
        str(entity.get("id") or ""): entity
        for entity in store.load_datasets().get("materials") or []
        if isinstance(entity, dict)
    }
    per_material = material_setting_weights()
    missing = sorted(material_id for material_id in per_material if material_id not in materials)
    if missing:
        raise KeyError(f"Recipe materials missing from the ontology: {', '.join(missing)}")
    missing_covers = sorted(material_id for material_id in COVER_CLIMATE_NICHES if material_id not in materials)
    if missing_covers:
        raise KeyError(f"Cover niche materials missing from the ontology: {', '.join(missing_covers)}")
    replacements = {}
    for material_id, weights in sorted(per_material.items()):
        replacement = replacements.setdefault(material_id, dict(materials[material_id]))
        replacement["lithotectonic_setting_weights"] = {
            setting_id: round(weight, 4) for setting_id, weight in sorted(weights.items())
        }
    for material_id, niche in sorted(COVER_CLIMATE_NICHES.items()):
        replacement = replacements.setdefault(material_id, dict(materials[material_id]))
        profile = dict(replacement.get("surface_affinity_profile") or {})
        profile.update({key: list(value) for key, value in niche.items()})
        replacement["surface_affinity_profile"] = profile
    missing_environments = sorted(material_id for material_id in DEPOSITIONAL_ENVIRONMENTS if material_id not in materials)
    if missing_environments:
        raise KeyError(f"Depositional-environment materials missing from the ontology: {', '.join(missing_environments)}")
    for material_id, environments in sorted(DEPOSITIONAL_ENVIRONMENTS.items()):
        replacement = replacements.setdefault(material_id, dict(materials[material_id]))
        profile = dict(replacement.get("surface_affinity_profile") or {})
        profile["depositional_environments"] = list(environments)
        replacement["surface_affinity_profile"] = profile
    missing_optics = sorted(material_id for material_id in OPTICAL_ENDMEMBERS if material_id not in materials)
    if missing_optics:
        raise KeyError(f"Optical endmember materials missing from the ontology: {', '.join(missing_optics)}")
    for material_id, endmember in sorted(OPTICAL_ENDMEMBERS.items()):
        replacement = replacements.setdefault(material_id, dict(materials[material_id]))
        replacement["optical_surface_profile"] = _optical_record(replacement, endmember)
    records = [replacements[material_id] for material_id in sorted(replacements)]
    if not store.persist_entities(records):
        raise RuntimeError("Could not persist lithotectonic setting weights")
    if export:
        store.export_rdfxml(ONTOLOGY_PATH)
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true", help="Also rewrite the ontology .owl checkpoint.")
    arguments = parser.parse_args()
    changed = author(export=arguments.export)
    print(f"Authored lithotectonic setting weights on {len(changed)} ontology materials.")
