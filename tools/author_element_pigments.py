"""Author the ontology data behind element pigments in true colour (copper first).

A planet's trace elements reach its colour through two mechanisms owned by
``simulations/world_gen/element_pigments.py``: the minerals that carry the
element in fresh rock, and the coloured minerals its weathering leaves at the
surface.  This tool writes the facts those mechanisms read, on the live
ontology store (no ``.owl`` export unless ``--export``):

1. rocks, sediments and regolith: ``trace_element_ppm`` -- the element's
   typical content in that material on Earth.  A planet scales it by its own
   enrichment over the reference crust (an unlisted material keeps the crust
   reference, as an unlisted element does);
2. element entities: ``supergene_behaviour`` -- the primary host minerals in
   order of preference (sulfides need the planet's sulfur, the rest takes
   what sulfur cannot hold), the secondary minerals weathering can leave, and
   the element's sorption (log Kd against pH) that sets how fast water
   carries it away;
3. secondary minerals: ``supergene_stability`` -- the conditions each one
   forms under (trapezoids over aridity, temperature, the rock's carbonate
   and silica, chloride, acid from sulfide oxidation and the air's CO2) and
   a relative stability;
4. new copper minerals (malachite, azurite, chrysocolla, atacamite,
   brochantite, tenorite, native copper) and visible reflectances for the
   copper sulfides and cuprite, which shared one grey placeholder;
5. element entities: ``metallogeny`` -- ore districts and, per district
   type, the ore style (grade, pyrite, geometry) of its deposits;
6. leached caps: the iron oxides the sulfides' iron leaves (goethite,
   hematite, with ``supergene_stability`` niches), and the malachite-azurite
   gossan filed as the weathering product it is (it was a hydrothermal
   sulfide);
7. the new fields on ``schema_materials``.

Sources (values entered from memory, unverified against the primary
tables, like the rest of the material chemistry): copper in rocks after
Turekian & Wedepohl (1961), Rudnick & Gao (2003) and Kabata-Pendias (2011);
supergene copper mineralogy after Anderson (1982), Chavez (2000, SEG
Newsletter 41) and Reich & Vasconcelos (2015, Elements 11); iron oxides
after Schwertmann & Taylor (1989) and Cornell & Schwertmann (2003); ore
grades after Singer, Berger & Moring (2008, porphyry), Cox et al. (2007,
sediment-hosted), Mosier, Singer & Salem (1983, massive sulfide) and
Naldrett (2004, magmatic), pyrite with them after Sillitoe (2010) and
Franklin et al. (2005); the
malachite-azurite boundary at log pCO2 ~ -3.45 bar (Vink 1986, Mineral.
Mag. 50); copper sorption against pH after Sauve, Hendershot & Allen
(2000); copper solubility over tenorite and malachite after Stumm & Morgan
(1996) and Langmuir (1997), matching copper-roof runoff (1-5 mg/L,
Odnevall Wallinder & Leygraf); patinas after Graedel (1987) and FitzGerald
et al. (1998); copper metal reflectance after Johnson & Christy (1972).  Reflectances are approximate powder colours (RRUFF / USGS
spectral library shapes), linear 650 / 550 / 450 nm.

Existing entities are merged from their full current dict (the store
replaces whole entities).  Re-runnable.
"""

from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulations.world_gen import material_chemistry as chem  # noqa: E402
from simulations.world_gen.material_affinities import material_affinity_profile  # noqa: E402
from simulations.world_gen.material_formation import formation_contract  # noqa: E402
from simulations.world_gen.material_optics import material_optical_surface_profile  # noqa: E402
from tools.author_material_chemistry import derived_thresholds, earth_distribution  # noqa: E402
from world.persistent_ontology_store import PersistentOntologyStore  # noqa: E402

ONTOLOGY_PATH = ROOT / "ontology" / "index0.owl"

# Typical copper content on Earth (ppm by mass).  Mafic rocks carry the most
# (sulfide droplets in basaltic melts), granites and quartz-rich sediments
# little, carbonates almost none; black and pelagic muds gather it.
COPPER_PPM = {
    # igneous, mafic to ultramafic
    "mat_basalt": 90, "mat_diabase": 90, "mat_gabbro": 80, "mat_scoria": 90, "mat_komatiite": 70,
    "mat_kimberlite": 80, "mat_peridotite": 20, "mat_dunite": 10, "mat_serpentinite": 15,
    "mat_soapstone": 15, "mat_anorthosite": 15,
    # igneous, intermediate to felsic
    "mat_andesite": 50, "mat_diorite": 40, "mat_latite": 30, "mat_monzonite": 25, "mat_tonalite": 25,
    "mat_granodiorite": 25, "mat_dacite": 30, "mat_trachyte": 10, "mat_phonolite": 10, "mat_syenite": 5,
    "mat_nepheline_syenite": 5, "mat_granite": 10, "mat_rhyolite": 8, "mat_obsidian": 8, "mat_pumice": 10,
    "mat_pegmatite": 5, "mat_carbonatite": 20, "mat_tuff": 30, "mat_ignimbrite": 15,
    "mat_welded_ignimbrite": 15,
    # metamorphic
    "mat_metabasalt": 80, "mat_amphibolite": 70, "mat_greenschist": 60, "mat_blueschist": 60,
    "mat_eclogite": 60, "mat_granulite": 30, "mat_gneiss": 25, "mat_migmatite": 20, "mat_schist": 45,
    "mat_phyllite": 45, "mat_slate": 45, "mat_hornfels": 40, "mat_quartzite": 5, "mat_marble": 5,
    "mat_lapis_lazuli_marble": 10, "mat_metaconglomerate": 15, "mat_mylonite": 25, "mat_cataclasite": 25,
    "mat_skarn": 150,
    # sedimentary rocks
    "mat_shale": 45, "mat_mudstone": 45, "mat_claystone": 50, "mat_siltstone": 30, "mat_sandstone": 10,
    "mat_arkose": 10, "mat_greywacke": 25, "mat_calcareous_sandstone": 8, "mat_red_bed_sandstone": 15,
    "mat_conglomerate": 15, "mat_sedimentary_breccia": 20, "mat_limestone": 4, "mat_oolitic_limestone": 4,
    "mat_chalk": 4, "mat_coquina": 4, "mat_dolostone": 4, "mat_travertine": 3, "mat_chert": 10,
    "mat_radiolarite": 50, "mat_diatomite": 20, "mat_phosphorite": 30, "mat_ironstone": 20,
    "mat_banded_iron_formation": 10, "mat_oil_shale": 70, "mat_anthracite": 15, "mat_lignite": 15,
    "mat_rock_salt": 1, "mat_gypsum_rock": 2, "mat_anhydrite_rock": 2,
    # sediments
    "mat_alluvium": 25, "mat_colluvium": 25, "mat_talus": 30, "mat_gravel": 15, "mat_silt": 25,
    "mat_clay": 50, "mat_marl": 20, "mat_lacustrine_mud": 40, "mat_marine_mud": 50, "mat_loess": 20,
    "mat_glacial_till": 25, "mat_beach_sand": 5, "mat_dune_sand": 4, "mat_silica_sand": 3, "mat_tephra": 40,
    "mat_evaporite_salt_crust": 2,
    # regolith
    "mat_saprolite": 35, "mat_clay_rich_regolith": 40, "mat_laterite": 50, "mat_ferricrete": 40,
    "mat_bauxite": 30, "mat_nickel_laterite": 30, "mat_limonite": 30, "mat_calcrete": 10,
    "mat_evaporite_crust": 2, "mat_rock_varnish": 100, "mat_impact_breccia": 30,
    "mat_solfataric_sulfur_crust": 10,
}
TRACE_ELEMENT_PPM = {"Cu": COPPER_PPM}


def _reflectance(red, green, blue):
    return {"red_650nm": red, "green_550nm": green, "blue_450nm": blue}


def _optics(red, green, blue, *, mixing_mode, coloring_power, weathered=None):
    profile = {
        "visible_reflectance": _reflectance(red, green, blue),
        "weathered_visible_reflectance": _reflectance(*(weathered or (red, green, blue))),
        "broadband_albedo": round(0.3 * red + 0.45 * green + 0.25 * blue, 3),
        "mixing_mode": mixing_mode,
        "optical_coloring_power": coloring_power,
        "calibration_state": "approximate_powder_colour_unverified",
    }
    return profile


# Fresh-rock hosts: dark, brassy, tarnished.  Chalcopyrite's powder is
# greenish black; bornite tarnishes purple; covellite is indigo.
PRIMARY_OPTICS = {
    "mat_chalcopyrite": _optics(0.20, 0.17, 0.07, mixing_mode="intimate", coloring_power=1.2),
    "mat_bornite": _optics(0.14, 0.08, 0.10, mixing_mode="intimate", coloring_power=1.2),
    "mat_chalcocite": _optics(0.07, 0.07, 0.07, mixing_mode="intimate", coloring_power=1.0),
    "mat_covellite": _optics(0.05, 0.06, 0.14, mixing_mode="intimate", coloring_power=1.2),
    "mat_cuprite": _optics(0.24, 0.04, 0.03, mixing_mode="coating", coloring_power=2.0),
}

# New minerals: (name, display formula, computational formula or None,
# display colour sRGB, optics, formation category, stability niche).
# Niche fields: aridity (0 humid .. 1 hyper-arid, surface_exposure's
# 1 / (1 + (P/PET / 0.3)^2)), temperature_k, carbonate (rock CO2 / 44),
# silica (rock SiO2 / 45), chloride (aridity^2 x planet Cl / Earth Cl),
# acid (sulfide oxidation load), log_pco2_bar (the air's CO2).
SUPERGENE = "supergene_oxidation"
NEW_MINERALS = {
    "mat_malachite": {
        "name": "Malachite", "formula": "Cu2CO3(OH)2", "computational": None, "color": [70, 150, 96],
        "optics": _optics(0.07, 0.30, 0.14, mixing_mode="coating", coloring_power=2.2),
        "category": SUPERGENE,
        "stability": {
            "niche": {"acid": [-0.01, 0.0, 0.25, 0.6], "log_pco2_bar": [-6.0, -5.0, -3.45, -2.6]},
            "relative_stability": 1.0,
            "basis": "Forms wherever the water stays near neutral with the air's CO2: carbonate-buffered oxidation zones, humid to arid (Katanga Copperbelt on dolomitic shale; Arizona), native copper on basalt (Keweenaw), the green patina of copper in clean air (Graedel 1987). Acid water from sulfides keeps it away. Stable below the azurite boundary at log pCO2 ~ -3.45 bar (Vink 1986).",
        },
    },
    "mat_azurite": {
        "name": "Azurite", "formula": "Cu3(CO3)2(OH)2", "computational": None, "color": [46, 86, 168],
        "optics": _optics(0.04, 0.12, 0.42, mixing_mode="coating", coloring_power=2.4),
        "category": SUPERGENE,
        "stability": {
            "niche": {"carbonate": [0.02, 0.15, 1.0, 1.01], "log_pco2_bar": [-4.2, -3.45, 0.0, 1.0], "aridity": [0.1, 0.35, 1.0, 1.01]},
            "relative_stability": 0.6,
            "basis": "Needs more CO2 than malachite (above log pCO2 ~ -3.45 bar, Vink 1986); at Earth's air it is metastable and survives mainly in dry oxidation zones (Bisbee, Tsumeb).",
        },
    },
    "mat_chrysocolla": {
        "name": "Chrysocolla", "formula": "(Cu,Al)2H2Si2O5(OH)4.nH2O", "computational": "CuSiO3(H2O)2",
        "color": [74, 160, 160], "optics": _optics(0.10, 0.36, 0.38, mixing_mode="coating", coloring_power=2.0),
        "category": SUPERGENE,
        "stability": {
            "niche": {"silica": [0.3, 0.6, 1.0, 1.01], "carbonate": [-0.01, 0.0, 0.15, 0.4], "aridity": [0.15, 0.3, 1.0, 1.01]},
            "relative_stability": 1.0,
            "basis": "Commonest copper oxide in silicate-hosted oxidation zones of semi-arid to arid porphyry districts (Chile, Arizona); silica comes from the host's own weathering (Chavez 2000).",
        },
    },
    "mat_atacamite": {
        "name": "Atacamite", "formula": "Cu2Cl(OH)3", "computational": None, "color": [54, 118, 70],
        "optics": _optics(0.05, 0.20, 0.07, mixing_mode="coating", coloring_power=2.2),
        "category": SUPERGENE,
        "stability": {
            "niche": {"aridity": [0.85, 0.95, 1.0, 1.01], "chloride": [0.3, 0.6, 1.0, 1.01]},
            "relative_stability": 1.2,
            "basis": "Hyper-arid, chloride-rich oxidation zones (Atacama Desert): dissolves in fresh water, so it marks lasting aridity (Reich & Vasconcelos 2015).",
        },
    },
    "mat_brochantite": {
        "name": "Brochantite", "formula": "Cu4SO4(OH)6", "computational": None, "color": [70, 140, 90],
        "optics": _optics(0.09, 0.32, 0.12, mixing_mode="coating", coloring_power=2.0),
        "category": SUPERGENE,
        "stability": {
            "niche": {"aridity": [0.5, 0.7, 1.0, 1.01], "carbonate": [-0.01, 0.0, 0.05, 0.2], "acid": [0.05, 0.3, 1.0, 1.01]},
            "relative_stability": 0.7,
            "basis": "Acid-sulfate oxidation of sulfide ore without carbonate buffer, arid (Chuquicamata); needs sulfide-derived sulfate.",
        },
    },
    "mat_tenorite": {
        "name": "Tenorite", "formula": "CuO", "computational": None, "color": [40, 40, 40],
        "optics": _optics(0.04, 0.04, 0.04, mixing_mode="coating", coloring_power=1.6),
        "category": SUPERGENE,
        "stability": {
            "niche": {"aridity": [0.6, 0.8, 1.0, 1.01], "temperature_k": [285.0, 298.0, 340.0, 360.0]},
            "relative_stability": 0.3,
            "basis": "Black copper oxide ('copper pitch') of warm, dry oxidation zones.",
        },
    },
    "mat_native_copper": {
        "name": "Native Copper", "formula": "Cu", "computational": None, "color": [184, 115, 51],
        # Copper metal reflects red well and blue poorly (an absorption edge
        # near 590 nm; Johnson & Christy 1972), as a rough grain surface
        # rather than a mirror; a cuprite film tarnishes it dull red-brown.
        "optics": {
            **_optics(0.42, 0.22, 0.13, mixing_mode="intimate", coloring_power=1.2, weathered=(0.18, 0.09, 0.06)),
            "weathering_color_response": 0.5,
            "color_driver": "oxidation",
        },
        "category": "hydrothermal_vein",
        "stability": None,
        "basis_primary": "Takes the copper sulfur cannot hold: sulfur-poor basalts carry native copper (Keweenaw); tarnished brown.",
    },
}

COPPER_BEHAVIOUR = {
    "primary_hosts": ["mat_chalcopyrite", "mat_bornite", "mat_chalcocite", "mat_native_copper"],
    "secondary_phases": [
        "mat_malachite", "mat_azurite", "mat_chrysocolla", "mat_atacamite", "mat_brochantite", "mat_tenorite",
    ],
    # The iron of oxidizing sulfides (the host's and the ore's pyrite) stays
    # as the leached cap's iron oxides.
    "leached_cap_phases": ["mat_goethite", "mat_hematite"],
    # (pH, log10 Kd in L/kg): copper binds ever more tightly to mineral
    # surfaces as the water turns neutral to alkaline (Sauve et al. 2000).
    "sorption_log_kd_l_per_kg": [[3.0, 0.5], [4.0, 1.0], [6.0, 2.6], [8.0, 3.6]],
    # (pH, log10 dissolved Cu in mol/L) over tenorite and malachite: Cu2+
    # falls a hundredfold per pH unit (CuO + 2H+ = Cu2+ + H2O, log K ~ 7.6)
    # down to the carbonate and hydroxo complexes (~1e-6 M).  Water cannot
    # carry more off: a copper roof loses ~1-2 g/m2 a year and keeps its
    # patina; acid water is not limited.
    "solubility_log_molar": [[3.0, 0.0], [4.0, -0.4], [5.0, -2.4], [6.0, -4.4], [7.0, -5.9], [8.0, -6.2], [9.0, -6.0]],
    "basis": "Chalcophile: copper takes sulfur before iron does; what sulfur cannot hold stays native. Oxidation releases Cu2+, mobile in acid water and leached from humid ground (iron-oxide leached caps), fixed as carbonates, silicates, chlorides and sulfates where water is scarce or buffered.",
}
# Where ore-forming processes gather copper (``metallogeny``): the share of
# the crust's copper in district rocks, and how it splits between district
# types (porphyry ~60 % of mined copper, plus iron-oxide copper-gold in the
# same arcs; sediment-hosted ~20 %; massive sulfides ~6 %; magmatic Ni-Cu
# and native copper ~4 %: Kesler & Wilkinson 2008, Singer 1995).
COPPER_METALLOGENY = {
    "district_share": 0.3,
    "districts": {"arc_magmatism": 0.68, "rift_basin": 0.22, "spreading_ridge": 0.06, "mantle_plume": 0.04},
    # The ore each district type makes (Earth grades, wt% Cu; a planet scales
    # them like rock contents): porphyry stockworks (median ~0.4-0.5 %),
    # sediment-hosted beds (~2 %), massive sulfide lenses (~1-2 %, mostly
    # pyrite), magmatic sulfides at the base of plume intrusions (pyrrhotite,
    # pyrite stands in).  pyrite_to_host: pyrite mass per mass of the copper
    # host, where the planet's sulfur allows it.
    "styles": {
        "arc_magmatism": {"style": "porphyry_copper", "grade_wt_percent": [0.3, 1.0], "pyrite_to_host": 2.0, "geometry": "stockwork_and_lenses"},
        "rift_basin": {"style": "sediment_hosted_copper", "grade_wt_percent": [1.0, 3.5], "pyrite_to_host": 0.3, "geometry": "stratiform_basin_layer"},
        "spreading_ridge": {"style": "volcanogenic_massive_sulfide", "grade_wt_percent": [0.8, 3.0], "pyrite_to_host": 10.0, "geometry": "massive_sulfide_lens"},
        "mantle_plume": {"style": "magmatic_copper_nickel_sulfide", "grade_wt_percent": [0.4, 1.5], "pyrite_to_host": 3.0, "geometry": "basal_sheet_and_veins"},
    },
    "basis": "Shares of the copper in porphyry/IOCG (arcs), sediment-hosted (rift and intracontinental basins), volcanogenic massive sulfide (spreading ridges, rifts) and magmatic Ni-Cu/native copper (plume flood basalts) deposits (Kesler & Wilkinson 2008; Singer 1995; Sillitoe 2010). district_share is a calibration: the richest belts carry several times the background (deposits themselves hold ~0.1 % of crustal copper; their districts' rocks far more). Unverified.",
}
ELEMENT_METALLOGENY = {"Cu": COPPER_METALLOGENY}
ELEMENT_BEHAVIOUR = {"Cu": COPPER_BEHAVIOUR}

# Leached-cap iron oxides: which one the sulfides' iron becomes.
IRON_OXIDE_STABILITY = {
    "mat_goethite": {
        "niche": {"aridity": [-0.01, 0.0, 0.55, 0.85]},
        "relative_stability": 1.0,
        "basis": "Yellow-brown iron oxide of humid and cool ground, and of acid caps where jarosite turns to it (Schwertmann & Taylor 1989; Cornell & Schwertmann 2003).",
    },
    "mat_hematite": {
        "niche": {"aridity": [0.25, 0.55, 1.0, 1.01], "temperature_k": [278.0, 290.0, 340.0, 380.0]},
        "relative_stability": 1.0,
        "basis": "Red iron oxide: warm, dry, well-drained ground ripens ferrihydrite to hematite; red leached caps of Arizona and the Atacama (Anderson 1982; Cornell & Schwertmann 2003).",
    },
}
# A gossan is the weathered top of a sulfide body, not the sulfide itself.
RECATEGORIZED = {"mat_malachite_azurite_gossan": SUPERGENE}

SCHEMA_FIELDS = {
    "trace_element_ppm": {
        "type": "dict", "section": "Chemistry", "optional": True,
        "description": "Rocks, sediments, regolith: element -> typical content on Earth (ppm by mass) for trace elements the bulk composition does not list. A planet scales it by its own enrichment over the reference crust.",
    },
    "supergene_behaviour": {
        "type": "dict", "section": "Chemistry", "optional": True,
        "description": "Element entities: primary_hosts (host minerals in order of preference), secondary_phases (minerals weathering can leave), leached_cap_phases (iron oxides the oxidizing sulfides' iron leaves), sorption_log_kd_l_per_kg ([pH, log Kd] pairs that set how fast water carries the element away), solubility_log_molar ([pH, log10 mol/L] the most the water can hold over the element's stable phases), basis.",
    },
    "metallogeny": {
        "type": "dict", "section": "Chemistry", "optional": True,
        "description": "Element entities: district_share (share of the crust's element in ore districts), districts {arc_magmatism, rift_basin, spreading_ridge, mantle_plume: share} -- where ore-forming processes gather it (simulations/world_gen/metallogeny.py) -- and styles {district type: style, grade_wt_percent [low, high] on Earth, pyrite_to_host, geometry}: the ore system its deposits form (regional_materials), basis.",
    },
    "supergene_stability": {
        "type": "dict", "section": "Chemistry", "optional": True,
        "description": "Secondary minerals and leached-cap iron oxides: niche (trapezoids [outer_low, ideal_low, ideal_high, outer_high] over aridity, temperature_k, carbonate, silica, chloride, acid, log_pco2_bar), relative_stability, basis.",
    },
}


def _placement_fields(material_id, category, *, display_color, optics=None):
    """Formation contract, affinity profile and optics of a mineral filed under ``category``."""
    affinity = material_affinity_profile(material_id) or {}
    contract = formation_contract(material_id, "mineral", affinity.get("profile_id"), explicit_category=category)
    if contract["status"] != "resolved":
        raise KeyError(f"{material_id}: formation category {category} does not resolve")
    return {
        "formation_category": category,
        "spatial_representation": contract["spatial_representation"],
        "formation_process": contract["formation_process"],
        "formation_contract_status": "resolved",
        "formation_requirements": {
            key: copy.deepcopy(contract[key])
            for key in ("required_all_planet_tags", "required_any_planet_tags", "host_formation_categories", "local_minimums", "valid_scale_levels")
        },
        "surface_affinity_profile": copy.deepcopy(affinity),
        "minimum_map_detail_level": int(affinity.get("minimum_map_detail_level", 2) or 2),
        "distribution_scale": affinity.get("distribution_scale") or "regional_deposit",
        "optical_surface_profile": material_optical_surface_profile(
            material_id, formation_category=category, material_subclass="mineral",
            display_color=display_color, explicit=optics,
        ),
    }


def _new_mineral(template, material_id, spec, earth):
    entity = copy.deepcopy(template)
    formula = spec["computational"] or spec["formula"]
    composition = chem.formula_composition(formula)
    name = spec["name"]
    entity.update({
        "id": material_id,
        "name": name,
        "pretty_name": name,
        "scientific_name": name.lower(),
        "chemical_formula": spec["formula"],
        "chemistry_status": "computational_formula" if spec["computational"] else "formula",
        "elemental_composition_wt": chem.rounded_composition(composition),
        "display_color": list(spec["color"]),
        "geological_map_color": list(spec["color"]),
        "formation_category": spec["category"],
        "optical_surface_profile": copy.deepcopy(spec["optics"]),
        "required_element_thresholds": derived_thresholds(composition, earth),
        "production_role_tags": ["extractive_resource", "ore_feedstock"],
    })
    if spec["computational"]:
        entity["computational_formula"] = spec["computational"]
    else:
        entity.pop("computational_formula", None)
    if spec["category"] == SUPERGENE:
        entity.update({
            "scientific_classification": "secondary copper mineral; supergene oxidation product",
            "formation_process": "oxidation_of_primary_sulfides_and_supergene_precipitation",
            "spatial_representation": "constituent_abundance",
            "natural_distribution_role": "mineral_constituent",
            "favorable_planet_tags": ["oxidizing_surface", "weathered_surface"],
            "supergene_stability": copy.deepcopy(spec["stability"]),
        })
    else:
        entity.update({
            "scientific_classification": "native element mineral; hydrothermal and magmatic phase",
            "formation_process": "hydrothermal_precipitation_in_sulfur_poor_host",
            "spatial_representation": "bounded_deposit",
            "natural_distribution_role": "sparse_deposit",
            "favorable_planet_tags": ["volcanic_surface", "silicate_crust"],
            "supergene_basis": spec["basis_primary"],
        })
        entity.pop("supergene_stability", None)
    # Placement fields, as every card carries them: the formation contract of
    # its category and the affinity profile (material_affinities).
    entity.update(_placement_fields(material_id, spec["category"], display_color=spec["color"], optics=spec["optics"]))
    entity["tags"] = ["natural_material", "mineral", "material", "copper_mineral"]
    return entity


def author(export=False):
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    materials = {str(entity.get("id") or ""): entity for entity in datasets.get("materials") or [] if isinstance(entity, dict)}
    targets = {material_id for table in TRACE_ELEMENT_PPM.values() for material_id in table} | set(PRIMARY_OPTICS)
    missing = sorted(material_id for material_id in targets if material_id not in materials)
    if missing:
        raise KeyError(f"Targets missing from the ontology: {', '.join(missing)}")
    template = materials.get("mat_cuprite")
    if template is None:
        raise KeyError("mat_cuprite (template for the new copper minerals) is missing")
    earth = earth_distribution()
    replacements = {}
    for element, table in TRACE_ELEMENT_PPM.items():
        for material_id, ppm in table.items():
            entity = replacements.setdefault(material_id, dict(materials[material_id]))
            entity["trace_element_ppm"] = {**dict(entity.get("trace_element_ppm") or {}), element: float(ppm)}
    for material_id, optics in PRIMARY_OPTICS.items():
        entity = replacements.setdefault(material_id, dict(materials[material_id]))
        entity["optical_surface_profile"] = {**dict(entity.get("optical_surface_profile") or {}), **copy.deepcopy(optics)}
    # Cuprite's display colour had its channels rotated (green).
    replacements["mat_cuprite"]["display_color"] = [156, 46, 34]
    for material_id, spec in NEW_MINERALS.items():
        current = materials.get(material_id)
        base = _new_mineral(template, material_id, spec, earth)
        replacements[material_id] = {**dict(current), **base} if current else base
    for material_id, stability in IRON_OXIDE_STABILITY.items():
        if material_id not in materials:
            raise KeyError(f"{material_id} (leached-cap iron oxide) is missing")
        entity = replacements.setdefault(material_id, dict(materials[material_id]))
        entity["supergene_stability"] = copy.deepcopy(stability)
    for material_id, category in RECATEGORIZED.items():
        if material_id not in materials:
            raise KeyError(f"{material_id} is missing")
        entity = replacements.setdefault(material_id, dict(materials[material_id]))
        entity.update(_placement_fields(
            material_id, category, display_color=entity.get("display_color") or [90, 140, 110],
            optics=entity.get("optical_surface_profile"),
        ))
        entity["formation_process"] = "oxidation_of_primary_sulfides_and_supergene_precipitation"
        entity["natural_distribution_role"] = "mineral_constituent"
    elements = {str(entity.get("element_symbol") or ""): entity for entity in materials.values() if entity.get("material_subclass") == "element"}
    for symbol, behaviour in ELEMENT_BEHAVIOUR.items():
        entity = elements.get(symbol)
        if entity is None:
            raise KeyError(f"Element entity for {symbol} is missing")
        known = set(materials) | set(NEW_MINERALS)
        unknown = [item for item in behaviour["primary_hosts"] + behaviour["secondary_phases"] + behaviour.get("leached_cap_phases", []) if item not in known]
        if unknown:
            raise KeyError(f"{symbol}: unknown minerals {unknown}")
        replacement = replacements.setdefault(entity["id"], dict(entity))
        replacement["supergene_behaviour"] = copy.deepcopy(behaviour)
        if symbol in ELEMENT_METALLOGENY:
            replacement["metallogeny"] = copy.deepcopy(ELEMENT_METALLOGENY[symbol])
    schema = next((entity for entity in datasets.get("schemas") or [] if str(entity.get("id")) == "schema_materials"), None)
    if schema is None:
        raise RuntimeError("schema_materials is missing from the ontology")
    schema = dict(schema)
    schema["fields"] = {**dict(schema.get("fields") or {}), **copy.deepcopy(SCHEMA_FIELDS)}
    records = [replacements[material_id] for material_id in sorted(replacements)] + [schema]
    if not store.persist_entities(records):
        raise RuntimeError("Could not persist element pigment data")
    if export:
        store.export_rdfxml(ONTOLOGY_PATH)
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true", help="Also rewrite the ontology .owl checkpoint.")
    parser.add_argument("--dry-run", action="store_true", help="Compute and check without writing.")
    arguments = parser.parse_args()
    if arguments.dry_run:
        PersistentOntologyStore.persist_entities = lambda self, records: True  # noqa: E731
    changed = author(export=arguments.export and not arguments.dry_run)
    new = sum(1 for record in changed if record.get("id") in NEW_MINERALS)
    print(f"{'Checked' if arguments.dry_run else 'Authored'} {len(changed) - 1} materials ({new} new copper minerals) and schema_materials.")
