from simulations.world_gen.crust import crust_composition_from_seed
from simulations.world_gen.material_catalog import ELEMENT_MATERIAL_CATALOG


NATURAL_MATERIAL_CATALOG_VERSION = "natural-materials-v1"


NATURAL_MATERIAL_CATALOG = [
    {
        "id": "mat_quartz",
        "name": "Quartz",
        "scientific_name": "alpha-quartz",
        "chemical_formula": "SiO2",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; tectosilicate; silica group",
        "display_color": [190, 189, 185],
        "required_element_thresholds": {"O": 20.0, "Si": 8.0},
        "favorable_planet_tags": ["silica_rich_crust", "felsic_crust", "intermediate_silicate_crust", "weathered_surface"],
    },
    {
        "id": "mat_plagioclase_feldspar",
        "name": "Plagioclase Feldspar",
        "scientific_name": "plagioclase feldspar solid-solution series",
        "chemical_formula": "(Na,Ca)(Al,Si)4O8",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; tectosilicate; feldspar group",
        "display_color": [176, 166, 148],
        "required_element_thresholds": {"O": 25.0, "Si": 8.0, "Al": 3.0},
        "required_element_groups": [{"elements": ["Na", "Ca"], "threshold": 1.0}],
        "favorable_planet_tags": ["silicate_crust", "felsic_crust", "intermediate_silicate_crust", "mafic_crust"],
    },
    {
        "id": "mat_alkali_feldspar",
        "name": "Alkali Feldspar",
        "scientific_name": "potassium feldspar group",
        "chemical_formula": "KAlSi3O8",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; tectosilicate; feldspar group",
        "display_color": [196, 178, 150],
        "required_element_thresholds": {"O": 20.0, "Si": 8.0, "Al": 2.0, "K": 0.8},
        "favorable_planet_tags": ["felsic_crust", "silica_rich_crust"],
    },
    {
        "id": "mat_olivine",
        "name": "Olivine",
        "scientific_name": "olivine group",
        "chemical_formula": "(Mg,Fe)2SiO4",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; nesosilicate; olivine group",
        "display_color": [122, 136, 82],
        "required_element_thresholds": {"O": 18.0, "Si": 6.0},
        "required_element_groups": [{"elements": ["Mg", "Fe"], "threshold": 3.0}],
        "favorable_planet_tags": ["mafic_crust", "ultramafic_tendency", "volcanic_surface"],
    },
    {
        "id": "mat_pyroxene",
        "name": "Pyroxene",
        "scientific_name": "pyroxene group",
        "chemical_formula": "XY(Si,Al)2O6",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; single-chain inosilicate; pyroxene group",
        "display_color": [88, 104, 82],
        "required_element_thresholds": {"O": 18.0, "Si": 6.0},
        "required_element_groups": [{"elements": ["Mg", "Fe", "Ca"], "threshold": 3.0}],
        "favorable_planet_tags": ["mafic_crust", "volcanic_surface", "basaltic_surface"],
    },
    {
        "id": "mat_amphibole",
        "name": "Amphibole",
        "scientific_name": "amphibole group",
        "chemical_formula": "A0-1B2C5T8O22(OH,F,Cl)2",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; double-chain inosilicate; amphibole group",
        "display_color": [76, 92, 74],
        "required_element_thresholds": {"O": 18.0, "Si": 6.0, "Ca": 0.8},
        "required_element_groups": [{"elements": ["Mg", "Fe"], "threshold": 2.0}],
        "favorable_planet_tags": ["hydrated_crust", "active_hydrology", "plate_tectonic_surface"],
    },
    {
        "id": "mat_biotite",
        "name": "Biotite",
        "scientific_name": "biotite mica group",
        "chemical_formula": "K(Mg,Fe)3AlSi3O10(OH)2",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; phyllosilicate; mica group",
        "display_color": [78, 64, 50],
        "required_element_thresholds": {"O": 18.0, "Si": 6.0, "Al": 2.0, "K": 0.6},
        "required_element_groups": [{"elements": ["Mg", "Fe"], "threshold": 2.0}],
        "favorable_planet_tags": ["hydrated_crust", "felsic_crust", "intermediate_silicate_crust"],
    },
    {
        "id": "mat_calcite",
        "name": "Calcite",
        "scientific_name": "calcite",
        "chemical_formula": "CaCO3",
        "material_subclass": "mineral",
        "scientific_classification": "carbonate mineral; calcite group",
        "display_color": [210, 207, 190],
        "required_element_thresholds": {"O": 12.0, "Ca": 1.0, "C": 0.02},
        "favorable_planet_tags": ["carbonate_favorable", "active_hydrology", "co2_bearing_atmosphere"],
    },
    {
        "id": "mat_gypsum",
        "name": "Gypsum",
        "scientific_name": "gypsum",
        "chemical_formula": "CaSO4*2H2O",
        "material_subclass": "mineral",
        "scientific_classification": "sulfate mineral; gypsum group",
        "display_color": [218, 213, 194],
        "required_element_thresholds": {"O": 12.0, "Ca": 1.0, "S": 0.02},
        "favorable_planet_tags": ["evaporite_favorable", "active_hydrology", "arid_surface"],
    },
    {
        "id": "mat_hematite",
        "name": "Hematite",
        "scientific_name": "hematite",
        "chemical_formula": "Fe2O3",
        "material_subclass": "mineral",
        "scientific_classification": "oxide mineral; hematite group",
        "display_color": [150, 68, 50],
        "required_element_thresholds": {"O": 12.0, "Fe": 2.0},
        "favorable_planet_tags": ["oxidizing_surface", "iron_rich_crust", "weathered_surface"],
    },
    {
        "id": "mat_magnetite",
        "name": "Magnetite",
        "scientific_name": "magnetite",
        "chemical_formula": "Fe3O4",
        "material_subclass": "mineral",
        "scientific_classification": "oxide mineral; spinel group",
        "display_color": [52, 50, 48],
        "required_element_thresholds": {"O": 12.0, "Fe": 2.5},
        "favorable_planet_tags": ["iron_rich_crust", "mafic_crust", "basaltic_surface"],
    },
    {
        "id": "mat_ilmenite",
        "name": "Ilmenite",
        "scientific_name": "ilmenite",
        "chemical_formula": "FeTiO3",
        "material_subclass": "mineral",
        "scientific_classification": "oxide mineral; ilmenite group",
        "display_color": [62, 58, 56],
        "required_element_thresholds": {"O": 12.0, "Fe": 1.0, "Ti": 0.05},
        "favorable_planet_tags": ["titanium_bearing_crust", "mafic_crust", "basaltic_surface"],
    },
    {
        "id": "mat_basalt",
        "name": "Basalt",
        "scientific_name": "basalt",
        "chemical_formula": "mafic silicate rock",
        "material_subclass": "rock",
        "scientific_classification": "igneous rock; volcanic; mafic",
        "display_color": [72, 76, 70],
        "required_element_thresholds": {"O": 20.0, "Si": 8.0, "Fe": 1.5, "Mg": 0.8},
        "favorable_planet_tags": ["mafic_crust", "volcanic_surface", "basaltic_surface"],
    },
    {
        "id": "mat_granite",
        "name": "Granite",
        "scientific_name": "granite",
        "chemical_formula": "felsic intrusive silicate rock",
        "material_subclass": "rock",
        "scientific_classification": "igneous rock; plutonic; felsic",
        "display_color": [174, 162, 146],
        "required_element_thresholds": {"O": 22.0, "Si": 10.0, "Al": 3.0, "K": 0.5},
        "favorable_planet_tags": ["felsic_crust", "silica_rich_crust", "plate_tectonic_surface"],
    },
    {
        "id": "mat_sandstone",
        "name": "Sandstone",
        "scientific_name": "quartz arenite to lithic sandstone",
        "chemical_formula": "siliciclastic sedimentary rock",
        "material_subclass": "rock",
        "scientific_classification": "sedimentary rock; clastic; arenite/wacke spectrum",
        "display_color": [178, 150, 116],
        "required_element_thresholds": {"O": 20.0, "Si": 8.0},
        "favorable_planet_tags": ["active_hydrology", "aeolian_surface", "weathered_surface"],
    },
    {
        "id": "mat_silica_sand",
        "name": "Silica Sand",
        "scientific_name": "quartz sand",
        "chemical_formula": "SiO2-dominant granular sediment",
        "material_subclass": "sediment",
        "scientific_classification": "unconsolidated sediment; siliciclastic; quartz-rich sand",
        "display_color": [188, 174, 140],
        "required_element_thresholds": {"O": 20.0, "Si": 8.0},
        "favorable_planet_tags": ["aeolian_surface", "active_hydrology", "weathered_surface", "silica_rich_crust"],
    },
    {
        "id": "mat_clay_rich_regolith",
        "name": "Clay-Rich Regolith",
        "scientific_name": "phyllosilicate-rich regolith",
        "chemical_formula": "hydrated aluminosilicate regolith",
        "material_subclass": "regolith",
        "scientific_classification": "unconsolidated regolith; secondary phyllosilicate assemblage",
        "display_color": [132, 118, 92],
        "required_element_thresholds": {"O": 20.0, "Si": 8.0, "Al": 2.0},
        "favorable_planet_tags": ["weathered_surface", "active_hydrology", "hydrated_crust"],
    },
    {
        "id": "mat_impact_breccia",
        "name": "Impact Breccia",
        "scientific_name": "polymict impact breccia",
        "chemical_formula": "fragmental host-rock mixture",
        "material_subclass": "regolith",
        "scientific_classification": "impactite; breccia; clastic rock/regolith",
        "display_color": [118, 112, 104],
        "required_element_thresholds": {"O": 12.0, "Si": 4.0},
        "favorable_planet_tags": ["cratered_regolith", "airless_regolith", "impact_gardening"],
    },
]


ATMOSPHERIC_MATERIAL_CATALOG = [
    {
        "id": "mat_molecular_hydrogen_gas",
        "name": "Molecular Hydrogen Gas",
        "scientific_name": "dihydrogen",
        "chemical_formula": "H2",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "elemental molecular gas; homonuclear diatomic molecule",
        "atmosphere_molecule": "H2",
        "band_color": [218, 207, 178],
    },
    {
        "id": "mat_helium_gas",
        "name": "Helium Gas",
        "scientific_name": "helium",
        "chemical_formula": "He",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "noble gas; monoatomic gas",
        "atmosphere_molecule": "He",
        "band_color": [224, 216, 195],
    },
    {
        "id": "mat_methane_gas",
        "name": "Methane Gas",
        "scientific_name": "methane",
        "chemical_formula": "CH4",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "alkane; volatile molecular gas",
        "atmosphere_molecule": "CH4",
        "band_color": [95, 148, 176],
    },
    {
        "id": "mat_ammonia_gas",
        "name": "Ammonia Gas",
        "scientific_name": "azane",
        "chemical_formula": "NH3",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "pnictogen hydride; volatile molecular gas",
        "atmosphere_molecule": "NH3",
        "band_color": [222, 210, 154],
    },
    {
        "id": "mat_water_vapor",
        "name": "Water Vapor",
        "scientific_name": "oxidane",
        "chemical_formula": "H2O",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "volatile molecular gas; oxide hydride",
        "atmosphere_molecule": "H2O",
        "band_color": [214, 226, 228],
    },
    {
        "id": "mat_carbon_monoxide_gas",
        "name": "Carbon Monoxide Gas",
        "scientific_name": "carbon monoxide",
        "chemical_formula": "CO",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "carbon oxide; molecular gas",
        "atmosphere_molecule": "CO",
        "band_color": [176, 172, 164],
    },
    {
        "id": "mat_carbon_dioxide_gas",
        "name": "Carbon Dioxide Gas",
        "scientific_name": "carbon dioxide",
        "chemical_formula": "CO2",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "carbon oxide; molecular gas",
        "atmosphere_molecule": "CO2",
        "band_color": [172, 150, 126],
    },
    {
        "id": "mat_dinitrogen_gas",
        "name": "Dinitrogen Gas",
        "scientific_name": "dinitrogen",
        "chemical_formula": "N2",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "elemental molecular gas; homonuclear diatomic molecule",
        "atmosphere_molecule": "N2",
        "band_color": [156, 172, 194],
    },
    {
        "id": "mat_dioxygen_gas",
        "name": "Dioxygen Gas",
        "scientific_name": "dioxygen",
        "chemical_formula": "O2",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "elemental molecular gas; homonuclear diatomic molecule",
        "atmosphere_molecule": "O2",
        "band_color": [150, 176, 204],
    },
    {
        "id": "mat_argon_gas",
        "name": "Argon Gas",
        "scientific_name": "argon",
        "chemical_formula": "Ar",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "noble gas; monoatomic gas",
        "atmosphere_molecule": "Ar",
        "band_color": [160, 156, 170],
    },
    {
        "id": "mat_neon_gas",
        "name": "Neon Gas",
        "scientific_name": "neon",
        "chemical_formula": "Ne",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "noble gas; monoatomic gas",
        "atmosphere_molecule": "Ne",
        "band_color": [190, 160, 178],
    },
    {
        "id": "mat_hydrogen_sulfide_gas",
        "name": "Hydrogen Sulfide Gas",
        "scientific_name": "sulfane",
        "chemical_formula": "H2S",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "chalcogen hydride; volatile molecular gas",
        "atmosphere_molecule": "H2S",
        "band_color": [154, 142, 82],
    },
    {
        "id": "mat_sulfur_dioxide_gas",
        "name": "Sulfur Dioxide Gas",
        "scientific_name": "sulfur dioxide",
        "chemical_formula": "SO2",
        "material_subclass": "atmospheric_gas",
        "scientific_classification": "sulfur oxide; molecular gas",
        "atmosphere_molecule": "SO2",
        "band_color": [170, 160, 124],
    },
]


GAS_MATERIAL_BY_MOLECULE = {
    material["atmosphere_molecule"]: material
    for material in ATMOSPHERIC_MATERIAL_CATALOG
}

MATERIAL_BY_ID = {
    material["id"]: material
    for material in [*ELEMENT_MATERIAL_CATALOG, *NATURAL_MATERIAL_CATALOG, *ATMOSPHERIC_MATERIAL_CATALOG]
}


def _coerce_color(value, fallback=None):
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return [max(0, min(255, int(value[index]))) for index in range(3)]
        except (TypeError, ValueError):
            return fallback
    return fallback


def material_display_color(material_id, fallback=None):
    material = MATERIAL_BY_ID.get(str(material_id or ""))
    if not isinstance(material, dict):
        return _coerce_color(fallback, [142, 142, 136])
    return _coerce_color(material.get("display_color"), _coerce_color(material.get("band_color"), _coerce_color(fallback, [142, 142, 136])))


def _blend_colors(weighted_colors, fallback=(132, 126, 116)):
    total = sum(max(0.0, float(weight or 0.0)) for _color, weight in weighted_colors)
    if total <= 0.0:
        return list(fallback)
    channels = [0.0, 0.0, 0.0]
    for color, weight in weighted_colors:
        color = _coerce_color(color)
        if color is None:
            continue
        weight = max(0.0, float(weight or 0.0))
        for index in range(3):
            channels[index] += color[index] * weight
    return [max(24, min(238, int(round(value / total)))) for value in channels]


def _shift_color(color, offset):
    color = _coerce_color(color, [132, 126, 116])
    return [max(20, min(245, int(channel + offset))) for channel in color]


def natural_material_entries():
    entries = []
    for material in [*ELEMENT_MATERIAL_CATALOG, *NATURAL_MATERIAL_CATALOG, *ATMOSPHERIC_MATERIAL_CATALOG]:
        is_gas = material["material_subclass"] == "atmospheric_gas"
        is_element = material["material_subclass"] == "element"
        entry = {
            "id": material["id"],
            "_dataset": "materials",
            "type": "material",
            "name": material["name"],
            "pretty_name": material["name"],
            "material_class": material.get("material_class", "natural_material"),
            "material_subclass": material["material_subclass"],
            "natural_material_subclass": material["material_subclass"],
            "material_form": "element" if is_element else ("atmospheric_gas" if is_gas else "natural_occurrence"),
            "scientific_name": material["scientific_name"],
            "chemical_formula": material["chemical_formula"],
            "scientific_classification": material["scientific_classification"],
            "atomic_number": material.get("atomic_number"),
            "element_symbol": material.get("element_symbol"),
            "element_group": material.get("element_group"),
            "standard_phase": material.get("standard_phase"),
            "rarity": material.get("rarity"),
            "required_element_thresholds": dict(material.get("required_element_thresholds") or {}),
            "required_element_groups": list(material.get("required_element_groups") or []),
            "favorable_planet_tags": list(material.get("favorable_planet_tags") or []),
            "atmosphere_molecule": material.get("atmosphere_molecule"),
            "molar_mass_kg_mol": material.get("molar_mass_kg_mol"),
            "display_color": material_display_color(material["id"]),
            "tags": [
                material.get("material_class", "natural_material"),
                material["material_subclass"],
                *list(material.get("favorable_planet_tags") or [])[:4],
            ],
            "wiki_entry": (
                f"{material['scientific_name']} ({material['chemical_formula']}), classified as "
                f"{material['scientific_classification']}. World generation treats this as a natural "
                + (
                    "elemental material; this is the chemical base layer for molecules, minerals, alloys, and composites."
                    if is_element else
                    "atmospheric material inferred from gas composition and retention."
                    if is_gas else
                    "material candidate inferred from crust element abundance and planet surface tags."
                )
            ),
        }
        entries.append(entry)
    return entries


def derive_atmospheric_material_model(atmosphere):
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    composition_rows = atmosphere.get("composition") if isinstance(atmosphere.get("composition"), list) else []
    candidates = []
    for row in composition_rows:
        if not isinstance(row, dict):
            continue
        molecule = row.get("molecule")
        material = GAS_MATERIAL_BY_MOLECULE.get(molecule)
        if material is None:
            continue
        try:
            fraction = max(0.0, float(row.get("fraction", 0.0) or 0.0))
        except (TypeError, ValueError):
            fraction = 0.0
        if fraction <= 0.0005:
            continue
        candidates.append({
            "material_id": material["id"],
            "name": material["name"],
            "material_subclass": material["material_subclass"],
            "scientific_classification": material["scientific_classification"],
            "chemical_formula": material["chemical_formula"],
            "molecule": molecule,
            "fraction": round(fraction, 6),
            "percent": round(fraction * 100.0, 3),
            "band_color": list(material["band_color"]),
            "display_color": material_display_color(material["id"], material["band_color"]),
        })
    candidates.sort(key=lambda item: (-item["fraction"], item["name"]))
    return {
        "status": "inferred",
        "catalog_version": NATURAL_MATERIAL_CATALOG_VERSION,
        "likely_materials": candidates,
        "dominant_materials": [item["material_id"] for item in candidates[:5]],
    }


def atmospheric_band_palette(atmosphere):
    model = derive_atmospheric_material_model(atmosphere)
    materials = model.get("likely_materials") or []
    if not materials:
        return {
            "base_color": [150, 160, 172],
            "bands": [[130, 140, 154], [168, 176, 188], [118, 128, 142]],
        }

    total = sum(float(item.get("fraction", 0.0) or 0.0) for item in materials) or 1.0
    base = [0.0, 0.0, 0.0]
    for item in materials:
        weight = float(item.get("fraction", 0.0) or 0.0) / total
        color = item.get("band_color") or [150, 160, 172]
        for index in range(3):
            base[index] += color[index] * weight

    try:
        temperature = float(atmosphere.get("estimated_surface_temperature_k", atmosphere.get("equilibrium_temperature_k", 250.0)) or 250.0)
    except (TypeError, ValueError):
        temperature = 250.0
    if temperature >= 650.0:
        tint = [44, 20, -12]
    elif temperature <= 170.0:
        tint = [-24, 16, 36]
    else:
        tint = [0, 0, 0]

    base = [
        max(32, min(238, int(base[index] + tint[index])))
        for index in range(3)
    ]
    bands = []
    offsets = [-32, 22, -14, 36, -24, 12, -8, 28]
    for index, offset in enumerate(offsets):
        channel_shift = (index % 3) * 5
        bands.append([
            max(24, min(245, base[0] + offset + channel_shift)),
            max(24, min(245, base[1] + int(offset * 0.55))),
            max(24, min(245, base[2] - int(offset * 0.25))),
        ])
    return {"base_color": base, "bands": bands}


def _element_abundance_map(crust_composition):
    composition = crust_composition_from_seed({"crust_composition": crust_composition})
    abundances = {}
    for group_name in ("major_elements", "trace_elements"):
        for element in composition.get(group_name) or []:
            symbol = str(element.get("symbol") or "").strip()
            if not symbol:
                continue
            try:
                abundance = float(element.get("abundance_percent", 0.0) or 0.0)
            except (TypeError, ValueError):
                abundance = 0.0
            abundances[symbol] = max(abundances.get(symbol, 0.0), abundance)
    return abundances


def derive_planet_material_tags(seed, atmosphere=None, regime=None, terrain=None, crust_type="unknown"):
    seed = seed if isinstance(seed, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    regime = regime if isinstance(regime, dict) else {}
    terrain = terrain if isinstance(terrain, dict) else {}
    surface = regime.get("surface_processes") if isinstance(regime.get("surface_processes"), dict) else {}
    interior = regime.get("interior") if isinstance(regime.get("interior"), dict) else {}
    composition = _element_abundance_map(seed.get("crust_composition"))

    tags = {"natural_material_context", "silicate_crust"}
    crust_type_key = str(crust_type or interior.get("crust_type") or "unknown").replace(" ", "_")
    if crust_type_key and crust_type_key != "unknown":
        tags.add(f"{crust_type_key}_crust")
    if composition.get("Si", 0.0) >= 27.0:
        tags.add("silica_rich_crust")
    if composition.get("Fe", 0.0) >= 6.0:
        tags.add("iron_rich_crust")
    if composition.get("Mg", 0.0) + composition.get("Fe", 0.0) >= 8.0:
        tags.add("mafic_crust")
    if composition.get("Mg", 0.0) + composition.get("Fe", 0.0) >= 13.0:
        tags.add("ultramafic_tendency")
    if composition.get("Ti", 0.0) >= 0.05:
        tags.add("titanium_bearing_crust")
    if composition.get("C", 0.0) >= 0.01:
        tags.add("carbon_bearing_crust")
    if composition.get("S", 0.0) >= 0.01:
        tags.add("sulfur_bearing_crust")

    hydrology = surface.get("hydrologic_cycle") or terrain.get("hydrology", {}).get("cycle")
    if hydrology in {"active", "limited"}:
        tags.update({"active_hydrology", "weathered_surface", "hydrated_crust"})
    if terrain.get("hydrology", {}).get("target_ocean_fraction", 0.0) or seed.get("water_fraction", 0.0):
        try:
            if float(seed.get("water_fraction", 0.0) or 0.0) >= 0.35:
                tags.add("water_rich_surface")
        except (TypeError, ValueError):
            pass
    if surface.get("aeolian_activity") in {"weak", "moderate", "strong"}:
        tags.add("aeolian_surface")
    if surface.get("crater_retention") == "high" or terrain.get("cratering", {}).get("density", 0.0) >= 0.4:
        tags.update({"cratered_regolith", "impact_gardening"})
    if atmosphere.get("surface_pressure_bar", 1.0) < 0.01:
        tags.add("airless_regolith")
    if interior.get("volcanic_activity") in {"low", "moderate", "high"}:
        tags.add("volcanic_surface")
    if interior.get("tectonic_regime") in {"plate_tectonics", "mobile_lid"}:
        tags.add("plate_tectonic_surface")
    if crust_type_key in {"mafic", "metal-rich"} or "mafic_crust" in tags:
        tags.add("basaltic_surface")

    composition_rows = atmosphere.get("composition") if isinstance(atmosphere.get("composition"), list) else []
    gases = {row.get("molecule"): float(row.get("fraction", 0.0) or 0.0) for row in composition_rows if isinstance(row, dict)}
    if gases.get("CO2", 0.0) >= 0.05:
        tags.add("co2_bearing_atmosphere")
    if gases.get("O2", 0.0) >= 0.01 or "active_hydrology" in tags:
        tags.add("oxidizing_surface")
    if "active_hydrology" in tags and "co2_bearing_atmosphere" in tags and composition.get("Ca", 0.0) >= 1.0:
        tags.add("carbonate_favorable")
    if composition.get("S", 0.0) >= 0.01 and composition.get("Ca", 0.0) >= 1.0:
        tags.add("evaporite_favorable")
    if seed.get("volatile_inventory") in {"dry", "thin"}:
        tags.add("arid_surface")
    return sorted(tags)


def _threshold_score(elements, thresholds):
    scores = []
    for symbol, threshold in (thresholds or {}).items():
        threshold = max(0.0001, float(threshold or 0.0))
        abundance = float(elements.get(symbol, 0.0) or 0.0)
        if abundance < threshold:
            return 0.0
        scores.append(min(1.0, abundance / (threshold * 2.0)))
    return sum(scores) / len(scores) if scores else 1.0


def _group_score(elements, groups):
    scores = []
    for group in groups or []:
        options = list(group.get("elements") or [])
        threshold = max(0.0001, float(group.get("threshold", 0.0) or 0.0))
        abundance = max(float(elements.get(symbol, 0.0) or 0.0) for symbol in options) if options else 0.0
        if abundance < threshold:
            return 0.0
        scores.append(min(1.0, abundance / (threshold * 2.0)))
    return sum(scores) / len(scores) if scores else 1.0


def derive_natural_material_model(crust_composition, planet_tags):
    elements = _element_abundance_map(crust_composition)
    tag_set = {str(tag) for tag in planet_tags or []}
    candidates = []
    for material in NATURAL_MATERIAL_CATALOG:
        if material.get("material_subclass") == "atmospheric_gas":
            continue
        chemistry_score = _threshold_score(elements, material.get("required_element_thresholds"))
        group_score = _group_score(elements, material.get("required_element_groups"))
        if chemistry_score <= 0.0 or group_score <= 0.0:
            continue
        favorable = [tag for tag in material.get("favorable_planet_tags", []) if tag in tag_set]
        tag_score = min(1.0, len(favorable) / max(1, min(3, len(material.get("favorable_planet_tags", [])))))
        confidence = round(min(0.98, chemistry_score * 0.68 + group_score * 0.12 + tag_score * 0.20), 3)
        if confidence < 0.28:
            continue
        if confidence >= 0.75:
            occurrence = "common"
        elif confidence >= 0.52:
            occurrence = "probable"
        else:
            occurrence = "possible"
        candidates.append({
            "material_id": material["id"],
            "name": material["name"],
            "material_subclass": material["material_subclass"],
            "scientific_classification": material["scientific_classification"],
            "chemical_formula": material["chemical_formula"],
            "display_color": material_display_color(material["id"]),
            "confidence": confidence,
            "occurrence": occurrence,
            "evidence_tags": favorable,
        })

    candidates.sort(key=lambda item: (-item["confidence"], item["name"]))
    palette = derive_planet_surface_palette({
        "likely_materials": candidates,
        "element_profile": elements,
    })
    return {
        "status": "inferred",
        "catalog_version": NATURAL_MATERIAL_CATALOG_VERSION,
        "planet_tags": sorted(tag_set),
        "element_profile": elements,
        "likely_materials": candidates,
        "dominant_materials": [item["material_id"] for item in candidates[:5]],
        "surface_palette": palette,
    }


def derive_planet_surface_palette(material_model, atmosphere=None, terrain=None):
    material_model = material_model if isinstance(material_model, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    terrain = terrain if isinstance(terrain, dict) else {}
    weighted = []
    evidence = []

    for index, item in enumerate(material_model.get("likely_materials") or []):
        if not isinstance(item, dict):
            continue
        material_id = item.get("material_id")
        color = material_display_color(material_id, item.get("display_color"))
        confidence = max(0.05, float(item.get("confidence", item.get("fraction", 0.0)) or 0.0))
        rank_weight = max(0.25, 1.0 - index * 0.11)
        weight = confidence * rank_weight
        weighted.append((color, weight))
        evidence.append({
            "material_id": material_id,
            "name": item.get("name"),
            "weight": round(weight, 4),
            "display_color": color,
        })
        if index >= 7:
            break

    element_profile = material_model.get("element_profile") if isinstance(material_model.get("element_profile"), dict) else {}
    for symbol, abundance in sorted(element_profile.items(), key=lambda row: -float(row[1] or 0.0))[:4]:
        element_id = f"mat_element_{str(symbol).lower()}"
        color = material_display_color(element_id)
        weight = max(0.0, float(abundance or 0.0)) / 100.0 * 0.35
        weighted.append((color, weight))
        evidence.append({
            "material_id": element_id,
            "name": symbol,
            "weight": round(weight, 4),
            "display_color": color,
        })

    hydrology = terrain.get("hydrology") if isinstance(terrain.get("hydrology"), dict) else {}
    try:
        ocean_fraction = float(hydrology.get("target_ocean_fraction", 0.0) or 0.0)
        ice_fraction = float(hydrology.get("target_ice_fraction", 0.0) or 0.0)
    except (TypeError, ValueError):
        ocean_fraction = 0.0
        ice_fraction = 0.0
    if ocean_fraction > 0.02:
        weighted.append(([36, 82, 128], min(0.8, ocean_fraction * 1.15)))
    if ice_fraction > 0.02:
        weighted.append(([210, 224, 232], min(0.65, ice_fraction * 1.0)))

    if not weighted and isinstance(atmosphere.get("composition"), list):
        atmosphere_palette = atmospheric_band_palette(atmosphere)
        weighted.append((atmosphere_palette.get("base_color", [150, 160, 172]), 1.0))

    surface = _blend_colors(weighted)
    return {
        "surface_color": surface,
        "palette": [
            _shift_color(surface, -28),
            surface,
            _shift_color(surface, 24),
            _shift_color(surface, -12),
        ],
        "evidence": evidence[:8],
    }
