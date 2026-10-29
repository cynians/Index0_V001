"""Author reduced mechanical-rock properties onto ontology materials.

This is an ontology migration. Runtime world generation reads these facts
through its startup cache and contains no parallel material-class table.

Every natural material gets the profile of its mechanical class.  Rocks
also get their own strength (``ROCK_PROPERTIES``): two rocks of one class
differ as much as two classes do (pumice and welded ignimbrite, shale and
massive sandstone), and it is that difference which makes a cliff stand
over a slope.  The indices world generation reads are derived from three
figures per rock (``rock_profile``).

    python tools/author_mechanical_lithology.py --dry-run   # print the table, write nothing
    python tools/author_mechanical_lithology.py             # write (the application must be closed)
"""

import math
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


# --- rock-specific strength -----------------------------------------------------
#
# Per rock: uniaxial compressive strength of the intact rock (MPa), typical
# spacing of its bedding planes or joints (m), durability (0 slakes or
# dissolves in the weather .. 1 lasts), bulk density (kg/m3) and a 0..1
# permeability index of the rock mass.
#
# Typical values chosen inside the wide ranges of the engineering-geology
# literature (strength grades and example rocks of Hoek & Brown 1997; the
# property tables of Goodman 1989 and Bell 2007).  Entered from memory;
# unverified against the primary tables, and no single value stands for a
# particular formation.
ROCK_PROPERTIES = {
    # Lavas and shallow intrusions.
    "mat_basalt": (200, 0.5, 1.0, 2900, 0.40),
    "mat_diabase": (230, 1.2, 1.0, 2950, 0.15),
    "mat_andesite": (150, 0.5, 1.0, 2650, 0.35),
    "mat_dacite": (130, 0.5, 1.0, 2550, 0.30),
    "mat_rhyolite": (120, 0.4, 0.95, 2450, 0.30),
    "mat_trachyte": (120, 0.5, 0.95, 2550, 0.30),
    "mat_phonolite": (150, 0.3, 1.0, 2550, 0.25),
    "mat_latite": (130, 0.5, 1.0, 2600, 0.30),
    "mat_obsidian": (150, 0.2, 0.8, 2400, 0.10),
    # Pyroclastic rocks: welding decides everything.
    "mat_welded_ignimbrite": (80, 1.0, 0.95, 2300, 0.30),
    "mat_ignimbrite": (25, 1.5, 0.7, 1900, 0.50),
    "mat_tuff": (12, 0.8, 0.6, 1700, 0.55),
    "mat_pumice": (3, 0.1, 0.3, 800, 0.85),
    "mat_scoria": (6, 0.1, 0.45, 1400, 0.85),
    # Clastic sedimentary rocks.
    "mat_sandstone": (60, 1.0, 0.85, 2350, 0.60),
    "mat_red_bed_sandstone": (35, 0.6, 0.7, 2300, 0.50),
    "mat_calcareous_sandstone": (70, 0.6, 0.75, 2450, 0.40),
    "mat_arkose": (55, 0.8, 0.8, 2400, 0.45),
    "mat_greywacke": (130, 0.4, 0.95, 2650, 0.10),
    "mat_conglomerate": (70, 2.0, 0.85, 2500, 0.45),
    "mat_sedimentary_breccia": (60, 1.5, 0.8, 2500, 0.40),
    "mat_siltstone": (40, 0.2, 0.6, 2500, 0.25),
    "mat_mudstone": (18, 0.1, 0.3, 2400, 0.08),
    "mat_claystone": (8, 0.05, 0.15, 2300, 0.04),
    "mat_shale": (20, 0.02, 0.25, 2450, 0.05),
    "mat_oil_shale": (30, 0.03, 0.4, 2100, 0.03),
    "mat_ironstone": (90, 0.3, 0.9, 3200, 0.20),
    "mat_lignite": (5, 0.1, 0.2, 1250, 0.30),
    "mat_anthracite": (30, 0.05, 0.5, 1500, 0.15),
    "mat_diatomite": (4, 0.3, 0.3, 900, 0.60),
    "mat_phosphorite": (45, 0.3, 0.75, 2800, 0.30),
    # Carbonates and siliceous sediments.
    "mat_limestone": (90, 0.6, 0.85, 2600, 0.50),
    "mat_dolostone": (120, 0.7, 0.95, 2800, 0.40),
    "mat_oolitic_limestone": (60, 0.8, 0.8, 2400, 0.50),
    "mat_chalk": (12, 0.5, 0.6, 1900, 0.50),
    "mat_coquina": (6, 0.8, 0.6, 1800, 0.80),
    "mat_travertine": (40, 0.5, 0.75, 2400, 0.60),
    "mat_marble": (100, 1.5, 0.9, 2700, 0.10),
    "mat_lapis_lazuli_marble": (100, 1.5, 0.9, 2750, 0.10),
    "mat_carbonatite": (90, 1.0, 0.85, 2900, 0.15),
    "mat_chert": (250, 0.08, 1.0, 2600, 0.05),
    "mat_radiolarite": (200, 0.06, 1.0, 2550, 0.05),
    "mat_banded_iron_formation": (220, 0.1, 1.0, 3400, 0.05),
    # Evaporites: strong enough in the hand, gone in the rain.
    "mat_gypsum_rock": (25, 0.5, 0.2, 2300, 0.15),
    "mat_anhydrite_rock": (90, 0.5, 0.4, 2900, 0.05),
    "mat_rock_salt": (25, 0.3, 0.0, 2170, 0.01),
    # Plutonic rocks.
    "mat_granite": (160, 2.0, 1.0, 2650, 0.08),
    "mat_granodiorite": (170, 2.0, 1.0, 2700, 0.08),
    "mat_tonalite": (170, 1.8, 1.0, 2750, 0.08),
    "mat_diorite": (180, 1.5, 1.0, 2850, 0.06),
    "mat_monzonite": (170, 1.8, 1.0, 2700, 0.08),
    "mat_syenite": (160, 1.8, 1.0, 2650, 0.08),
    "mat_nepheline_syenite": (150, 1.5, 0.9, 2600, 0.08),
    "mat_gabbro": (200, 1.5, 1.0, 2950, 0.05),
    "mat_anorthosite": (180, 2.0, 1.0, 2750, 0.05),
    "mat_peridotite": (150, 1.0, 0.7, 3250, 0.05),
    "mat_dunite": (150, 1.0, 0.65, 3300, 0.05),
    "mat_komatiite": (180, 0.5, 0.8, 3000, 0.10),
    "mat_kimberlite": (60, 0.5, 0.35, 2700, 0.20),
    "mat_pegmatite": (130, 1.5, 0.95, 2650, 0.08),
    "mat_skarn": (150, 0.8, 0.9, 3200, 0.08),
    # Metamorphic rocks: foliation is the weakness.
    "mat_quartzite": (250, 1.0, 1.0, 2650, 0.04),
    "mat_hornfels": (220, 0.4, 1.0, 2750, 0.04),
    "mat_granulite": (200, 1.0, 1.0, 2850, 0.04),
    "mat_eclogite": (220, 1.0, 1.0, 3400, 0.03),
    "mat_gneiss": (150, 1.0, 1.0, 2750, 0.06),
    "mat_migmatite": (150, 1.2, 1.0, 2750, 0.06),
    "mat_amphibolite": (180, 0.6, 1.0, 3000, 0.05),
    "mat_metabasalt": (160, 0.4, 0.95, 2950, 0.08),
    "mat_metaconglomerate": (120, 1.0, 0.95, 2700, 0.06),
    "mat_blueschist": (120, 0.15, 0.9, 3100, 0.05),
    "mat_slate": (110, 0.03, 0.85, 2750, 0.04),
    "mat_schist": (60, 0.08, 0.75, 2800, 0.08),
    "mat_greenschist": (70, 0.08, 0.75, 2900, 0.06),
    "mat_phyllite": (50, 0.04, 0.6, 2750, 0.06),
    "mat_mylonite": (120, 0.05, 0.9, 2750, 0.04),
    "mat_serpentinite": (60, 0.1, 0.5, 2600, 0.10),
    "mat_soapstone": (25, 0.3, 0.5, 2800, 0.05),
    "mat_cataclasite": (40, 0.05, 0.4, 2600, 0.25),
}

# Rock-mass strength rating of Selby (1980), reduced to what a lithology
# decides.  Intact strength 5..20 by compressive strength (his Schmidt-hammer
# classes: under 25 MPa, 25-50, 50-100, 100-200, over 200) and joint spacing
# 8..30 (under 50 mm, 50-300 mm, 0.3-1 m, 1-3 m, over 3 m), both read between
# the class middles; the remaining terms (weathering 3..10, joint orientation
# 5..20, width 2..7, continuity 1..7, groundwater 1..6) are set for flat
# beds and a rock that lasts (38) and fall to 14 for one that slakes or
# dissolves.  ``slope_resistance_index`` is this rating over 100.
INTACT_STRENGTH_RATING = ((12.5, 5.0), (35.0, 10.0), (70.0, 14.0), (140.0, 18.0), (250.0, 20.0))
JOINT_SPACING_RATING = ((0.03, 8.0), (0.12, 15.0), (0.55, 21.0), (1.7, 28.0), (3.5, 30.0))
CONDITION_RATING = (14.0, 38.0)
# Tensile strength of intact rock is about a tenth of its compressive strength.
TENSILE_SHARE_OF_COMPRESSIVE = 0.1
# Rivers wear rock at a rate that falls with the square of its tensile
# strength (Sklar & Dietrich 2001); closely jointed rock is plucked rather
# than worn and rock that slakes is half gone already, so both lower the
# strength that counts.  The index spans 4.4 decades of erodibility (Stock &
# Montgomery 1999 found five), with granite at the class value it had.
ERODIBILITY_REFERENCE_STRENGTH_MPA = 4.49
ERODIBILITY_INDEX_PER_STRENGTH_DECADE = 0.455


def _on_log_scale(value, anchors):
    """Piecewise-linear in log(value) through ``anchors``, clamped at both ends."""
    if value <= anchors[0][0]:
        return anchors[0][1]
    for (low, low_rating), (high, high_rating) in zip(anchors, anchors[1:]):
        if value <= high:
            share = math.log(value / low) / math.log(high / low)
            return low_rating + (high_rating - low_rating) * share
    return anchors[-1][1]


def rock_mass_strength_rating(compressive_strength_mpa, spacing_m, durability):
    """Selby's rating (25..100) of a flat-lying rock of this strength, spacing and durability."""
    condition = CONDITION_RATING[0] + (CONDITION_RATING[1] - CONDITION_RATING[0]) * min(1.0, max(0.0, durability))
    return (
        _on_log_scale(compressive_strength_mpa, INTACT_STRENGTH_RATING)
        + _on_log_scale(spacing_m, JOINT_SPACING_RATING)
        + condition
    )


def rock_profile(mechanical_class, properties):
    """The class profile with one rock's own strength and the indices derived from it."""
    compressive, spacing, durability, density, permeability = (float(value) for value in properties)
    profile = dict(PROFILES[mechanical_class])
    tensile = compressive * TENSILE_SHARE_OF_COMPRESSIVE
    friction = math.radians(profile["friction_angle_deg"])
    # Mohr-Coulomb: the cohesion of intact rock of this strength and friction angle.
    cohesion = compressive * (1.0 - math.sin(friction)) / (2.0 * math.cos(friction))
    effective = tensile * min(1.1, max(0.5, spacing ** 0.25)) * (0.5 + 0.5 * durability)
    erodibility = 0.5 + ERODIBILITY_INDEX_PER_STRENGTH_DECADE * math.log10(ERODIBILITY_REFERENCE_STRENGTH_MPA / effective)
    rating = rock_mass_strength_rating(compressive, spacing, durability)
    profile.update({
        "uniaxial_compressive_strength_mpa": compressive,
        "discontinuity_spacing_m": spacing,
        "durability_index": durability,
        "rock_mass_strength_rating": round(rating, 1),
        "bulk_density_kg_m3": density,
        "permeability_index": permeability,
        "tensile_strength_mpa": round(tensile, 2),
        "cohesion_mpa": round(cohesion, 1),
        "erodibility_index": round(min(0.97, max(0.05, erodibility)), 2),
        "slope_resistance_index": round(rating / 100.0, 3),
        "fracture_density_index": round(min(0.95, max(0.05, 0.60 - 0.28 * math.log10(spacing / 0.5))), 2),
        "elastic_strength_index": round(min(0.95, max(0.05, 0.25 + 0.48 * math.log10(compressive / 10.0))), 2),
        "profile_basis": "rock_specific_strength_v1",
    })
    return profile


def mechanical_profile(entity):
    """``(mechanical class, profile)`` this tool gives a natural material."""
    mechanical_class = _mechanical_class(entity)
    properties = ROCK_PROPERTIES.get(str(entity.get("id") or ""))
    if properties is not None and str(entity.get("material_subclass") or "").lower() == "rock":
        return mechanical_class, rock_profile(mechanical_class, properties)
    return mechanical_class, dict(PROFILES[mechanical_class])


def author(export=False, dry_run=False):
    """Write class and profile to every natural material whose stored ones differ.

    Returns the records written (or that would be written with ``dry_run``).
    """
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    records = []
    natural = 0
    for entity in datasets.get("materials") or []:
        if not isinstance(entity, dict) or entity.get("material_system_role") != "natural_geologic_material":
            continue
        natural += 1
        mechanical_class, profile = mechanical_profile(entity)
        if entity.get("mechanical_class") == mechanical_class and entity.get("mechanical_rock_profile") == profile:
            continue
        # The store replaces an entity whole: write the full record back.
        replacement = dict(entity)
        replacement["mechanical_class"] = mechanical_class
        replacement["mechanical_rock_profile"] = profile
        records.append(replacement)
    if not natural:
        raise RuntimeError("No natural geological material records found")
    if dry_run or not records:
        return records
    if not store.persist_entities(records):
        raise RuntimeError("Could not persist mechanical lithology properties")
    if export:
        store.export_rdfxml(ONTOLOGY_PATH)
    return records


def _table(records):
    lines = ["%-28s %-28s %5s %6s %5s  %6s %6s %6s" % (
        "material", "class", "MPa", "m", "dur", "rating", "resist", "erod")]
    for record in sorted(records, key=lambda item: -float(item["mechanical_rock_profile"].get("slope_resistance_index", 0.0))):
        profile = record["mechanical_rock_profile"]
        if "rock_mass_strength_rating" not in profile:
            continue
        lines.append("%-28s %-28s %5.0f %6.2f %5.2f  %6.1f %6.3f %6.2f" % (
            record["id"], record["mechanical_class"], profile["uniaxial_compressive_strength_mpa"],
            profile["discontinuity_spacing_m"], profile["durability_index"], profile["rock_mass_strength_rating"],
            profile["slope_resistance_index"], profile["erodibility_index"]))
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--export", action="store_true", help="Also rewrite the ontology .owl checkpoint.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change; write nothing.")
    arguments = parser.parse_args()
    changed = author(export=arguments.export, dry_run=arguments.dry_run)
    if arguments.dry_run:
        print(_table(changed))
    unresolved = sum(item.get("mechanical_class") == "unresolved_geologic_material" for item in changed)
    print(f"{'Would author' if arguments.dry_run else 'Authored'} mechanical lithology for {len(changed)} ontology materials ({unresolved} unresolved).")
