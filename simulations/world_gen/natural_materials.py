import math

from simulations.world_gen.crust import crust_composition_from_seed
from simulations.world_gen.material_affinities import material_affinity_profile
from simulations.world_gen.material_catalog import ELEMENT_MATERIAL_CATALOG


NATURAL_MATERIAL_CATALOG_VERSION = "natural-materials-v3"


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
    {
        "id": "mat_limestone",
        "name": "Limestone",
        "scientific_name": "calcite-rich carbonate rock",
        "chemical_formula": "CaCO3-dominant sedimentary rock",
        "material_subclass": "rock",
        "scientific_classification": "sedimentary rock; carbonate; limestone",
        "display_color": [202, 198, 174],
        "required_element_thresholds": {"O": 12.0, "Ca": 1.0, "C": 0.02},
        "favorable_planet_tags": ["carbonate_favorable", "active_hydrology", "co2_bearing_atmosphere"],
    },
    {
        "id": "mat_dolomite",
        "name": "Dolomite",
        "scientific_name": "dolostone-forming dolomite",
        "chemical_formula": "CaMg(CO3)2",
        "material_subclass": "mineral",
        "scientific_classification": "carbonate mineral; dolomite group",
        "display_color": [196, 188, 166],
        "required_element_thresholds": {"O": 12.0, "Ca": 0.8, "Mg": 0.4, "C": 0.02},
        "favorable_planet_tags": ["carbonate_favorable", "active_hydrology", "co2_bearing_atmosphere"],
    },
    {
        "id": "mat_shale",
        "name": "Shale",
        "scientific_name": "fissile mudstone",
        "chemical_formula": "clay- and silt-rich sedimentary rock",
        "material_subclass": "rock",
        "scientific_classification": "sedimentary rock; clastic; mudrock",
        "display_color": [92, 84, 72],
        "required_element_thresholds": {"O": 18.0, "Si": 7.0, "Al": 2.0},
        "favorable_planet_tags": ["weathered_surface", "active_hydrology", "hydrated_crust"],
    },
    {
        "id": "mat_siltstone",
        "name": "Siltstone",
        "scientific_name": "silt-grade clastic sedimentary rock",
        "chemical_formula": "siliciclastic sedimentary rock",
        "material_subclass": "rock",
        "scientific_classification": "sedimentary rock; clastic; siltstone",
        "display_color": [140, 126, 102],
        "required_element_thresholds": {"O": 18.0, "Si": 7.0},
        "favorable_planet_tags": ["weathered_surface", "active_hydrology", "aeolian_surface"],
    },
    {
        "id": "mat_conglomerate",
        "name": "Conglomerate",
        "scientific_name": "rounded-clast conglomerate",
        "chemical_formula": "mixed lithic clastic rock",
        "material_subclass": "rock",
        "scientific_classification": "sedimentary rock; coarse clastic; rudite",
        "display_color": [136, 122, 100],
        "required_element_thresholds": {"O": 14.0, "Si": 5.0},
        "favorable_planet_tags": ["active_hydrology", "weathered_surface", "impact_gardening"],
    },
    {
        "id": "mat_rhyolite",
        "name": "Rhyolite",
        "scientific_name": "rhyolite",
        "chemical_formula": "felsic volcanic silicate rock",
        "material_subclass": "rock",
        "scientific_classification": "igneous rock; volcanic; felsic",
        "display_color": [184, 168, 150],
        "required_element_thresholds": {"O": 22.0, "Si": 10.0, "Al": 2.5, "K": 0.4},
        "favorable_planet_tags": ["felsic_crust", "silica_rich_crust", "volcanic_surface"],
    },
    {
        "id": "mat_andesite",
        "name": "Andesite",
        "scientific_name": "andesite",
        "chemical_formula": "intermediate volcanic silicate rock",
        "material_subclass": "rock",
        "scientific_classification": "igneous rock; volcanic; intermediate",
        "display_color": [116, 112, 104],
        "required_element_thresholds": {"O": 20.0, "Si": 8.0, "Al": 2.0, "Ca": 0.7},
        "favorable_planet_tags": ["intermediate_silicate_crust", "volcanic_surface", "plate_tectonic_surface"],
    },
    {
        "id": "mat_gabbro",
        "name": "Gabbro",
        "scientific_name": "gabbro",
        "chemical_formula": "mafic intrusive silicate rock",
        "material_subclass": "rock",
        "scientific_classification": "igneous rock; plutonic; mafic",
        "display_color": [58, 66, 60],
        "required_element_thresholds": {"O": 18.0, "Si": 7.0, "Fe": 1.5, "Mg": 0.8},
        "favorable_planet_tags": ["mafic_crust", "basaltic_surface", "plate_tectonic_surface"],
    },
    {
        "id": "mat_peridotite",
        "name": "Peridotite",
        "scientific_name": "peridotite",
        "chemical_formula": "ultramafic silicate rock",
        "material_subclass": "rock",
        "scientific_classification": "igneous rock; ultramafic; mantle-derived",
        "display_color": [88, 104, 70],
        "required_element_thresholds": {"O": 16.0, "Si": 5.0, "Mg": 3.0, "Fe": 1.2},
        "favorable_planet_tags": ["ultramafic_tendency", "mafic_crust", "volcanic_surface"],
    },
    {
        "id": "mat_serpentine",
        "name": "Serpentine",
        "scientific_name": "serpentine group",
        "chemical_formula": "(Mg,Fe)3Si2O5(OH)4",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; phyllosilicate; serpentine group",
        "display_color": [94, 126, 88],
        "required_element_thresholds": {"O": 18.0, "Si": 5.0, "Mg": 1.5},
        "favorable_planet_tags": ["hydrated_crust", "active_hydrology", "ultramafic_tendency"],
    },
    {
        "id": "mat_talc",
        "name": "Talc",
        "scientific_name": "talc",
        "chemical_formula": "Mg3Si4O10(OH)2",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; phyllosilicate; talc group",
        "display_color": [184, 196, 176],
        "required_element_thresholds": {"O": 18.0, "Si": 6.0, "Mg": 1.2},
        "favorable_planet_tags": ["hydrated_crust", "active_hydrology", "plate_tectonic_surface"],
    },
    {
        "id": "mat_chlorite",
        "name": "Chlorite",
        "scientific_name": "chlorite group",
        "chemical_formula": "(Mg,Fe,Al)6(Si,Al)4O10(OH)8",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; phyllosilicate; chlorite group",
        "display_color": [72, 110, 74],
        "required_element_thresholds": {"O": 18.0, "Si": 5.0, "Al": 1.0},
        "required_element_groups": [{"elements": ["Mg", "Fe"], "threshold": 1.0}],
        "favorable_planet_tags": ["hydrated_crust", "weathered_surface", "active_hydrology"],
    },
    {
        "id": "mat_kaolinite",
        "name": "Kaolinite",
        "scientific_name": "kaolinite",
        "chemical_formula": "Al2Si2O5(OH)4",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; phyllosilicate; kaolin group",
        "display_color": [210, 202, 184],
        "required_element_thresholds": {"O": 18.0, "Si": 5.0, "Al": 2.0},
        "favorable_planet_tags": ["weathered_surface", "active_hydrology", "hydrated_crust"],
    },
    {
        "id": "mat_montmorillonite",
        "name": "Montmorillonite",
        "scientific_name": "montmorillonite smectite",
        "chemical_formula": "(Na,Ca)0.33(Al,Mg)2Si4O10(OH)2*nH2O",
        "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; phyllosilicate; smectite group",
        "display_color": [166, 148, 118],
        "required_element_thresholds": {"O": 18.0, "Si": 6.0, "Al": 1.2},
        "required_element_groups": [{"elements": ["Na", "Ca"], "threshold": 0.4}],
        "favorable_planet_tags": ["weathered_surface", "active_hydrology", "hydrated_crust"],
    },
    {
        "id": "mat_halite",
        "name": "Halite",
        "scientific_name": "halite",
        "chemical_formula": "NaCl",
        "material_subclass": "mineral",
        "scientific_classification": "halide mineral; evaporite",
        "display_color": [220, 214, 198],
        "required_element_thresholds": {"Na": 0.8, "Cl": 0.01},
        "favorable_planet_tags": ["evaporite_favorable", "arid_surface", "active_hydrology"],
    },
    {
        "id": "mat_sylvite",
        "name": "Sylvite",
        "scientific_name": "sylvite",
        "chemical_formula": "KCl",
        "material_subclass": "mineral",
        "scientific_classification": "halide mineral; potash evaporite",
        "display_color": [218, 184, 172],
        "required_element_thresholds": {"K": 0.4, "Cl": 0.01},
        "favorable_planet_tags": ["evaporite_favorable", "arid_surface"],
    },
    {
        "id": "mat_anhydrite",
        "name": "Anhydrite",
        "scientific_name": "anhydrite",
        "chemical_formula": "CaSO4",
        "material_subclass": "mineral",
        "scientific_classification": "sulfate mineral; evaporite",
        "display_color": [194, 190, 174],
        "required_element_thresholds": {"O": 10.0, "Ca": 0.8, "S": 0.02},
        "favorable_planet_tags": ["evaporite_favorable", "arid_surface", "sulfur_bearing_crust"],
    },
    {
        "id": "mat_pyrite",
        "name": "Pyrite",
        "scientific_name": "pyrite",
        "chemical_formula": "FeS2",
        "material_subclass": "mineral",
        "scientific_classification": "sulfide mineral; pyrite group",
        "display_color": [170, 132, 58],
        "required_element_thresholds": {"Fe": 1.0, "S": 0.02},
        "favorable_planet_tags": ["sulfur_bearing_crust", "volcanic_surface", "hydrated_crust"],
    },
    {
        "id": "mat_chalcopyrite",
        "name": "Chalcopyrite",
        "scientific_name": "chalcopyrite",
        "chemical_formula": "CuFeS2",
        "material_subclass": "mineral",
        "scientific_classification": "sulfide mineral; copper iron sulfide",
        "display_color": [184, 116, 52],
        "required_element_thresholds": {"Cu": 0.01, "Fe": 1.0, "S": 0.02},
        "favorable_planet_tags": ["sulfur_bearing_crust", "volcanic_surface", "plate_tectonic_surface"],
    },
    {
        "id": "mat_sphalerite",
        "name": "Sphalerite",
        "scientific_name": "sphalerite",
        "chemical_formula": "ZnS",
        "material_subclass": "mineral",
        "scientific_classification": "sulfide mineral; zinc sulfide",
        "display_color": [116, 92, 58],
        "required_element_thresholds": {"Zn": 0.01, "S": 0.02},
        "favorable_planet_tags": ["sulfur_bearing_crust", "volcanic_surface"],
    },
    {
        "id": "mat_galena",
        "name": "Galena",
        "scientific_name": "galena",
        "chemical_formula": "PbS",
        "material_subclass": "mineral",
        "scientific_classification": "sulfide mineral; lead sulfide",
        "display_color": [94, 94, 92],
        "required_element_thresholds": {"Pb": 0.005, "S": 0.02},
        "favorable_planet_tags": ["sulfur_bearing_crust", "volcanic_surface"],
    },
    {
        "id": "mat_chromite",
        "name": "Chromite",
        "scientific_name": "chromite",
        "chemical_formula": "FeCr2O4",
        "material_subclass": "mineral",
        "scientific_classification": "oxide mineral; spinel group",
        "display_color": [42, 48, 44],
        "required_element_thresholds": {"O": 10.0, "Fe": 1.0, "Cr": 0.01},
        "favorable_planet_tags": ["mafic_crust", "ultramafic_tendency", "basaltic_surface"],
    },
    {
        "id": "mat_cassiterite",
        "name": "Cassiterite",
        "scientific_name": "cassiterite",
        "chemical_formula": "SnO2",
        "material_subclass": "mineral",
        "scientific_classification": "oxide mineral; tin oxide",
        "display_color": [98, 86, 74],
        "required_element_thresholds": {"O": 10.0, "Sn": 0.01},
        "favorable_planet_tags": ["oxidizing_surface", "weathered_surface", "felsic_crust"],
    },
    {
        "id": "mat_bauxite",
        "name": "Bauxite",
        "scientific_name": "bauxite lateritic ore",
        "chemical_formula": "hydrated aluminium oxide mixture",
        "material_subclass": "regolith",
        "scientific_classification": "weathering residue; aluminium ore",
        "display_color": [172, 92, 64],
        "required_element_thresholds": {"O": 16.0, "Al": 3.0},
        "favorable_planet_tags": ["weathered_surface", "active_hydrology", "oxidizing_surface"],
    },
    {
        "id": "mat_laterite",
        "name": "Laterite",
        "scientific_name": "iron-aluminium lateritic regolith",
        "chemical_formula": "Fe/Al oxide-rich weathering mantle",
        "material_subclass": "regolith",
        "scientific_classification": "weathering residue; ferruginous regolith",
        "display_color": [150, 74, 46],
        "required_element_thresholds": {"O": 16.0, "Al": 1.5, "Fe": 1.0},
        "favorable_planet_tags": ["weathered_surface", "active_hydrology", "oxidizing_surface"],
    },
    {
        "id": "mat_graphite",
        "name": "Graphite",
        "scientific_name": "graphite",
        "chemical_formula": "C",
        "material_subclass": "mineral",
        "scientific_classification": "native element mineral; carbon polymorph",
        "display_color": [48, 48, 44],
        "required_element_thresholds": {"C": 0.03},
        "favorable_planet_tags": ["carbon_bearing_crust", "plate_tectonic_surface"],
    },
    {
        "id": "mat_diamond",
        "name": "Diamond",
        "scientific_name": "diamond",
        "chemical_formula": "C",
        "material_subclass": "mineral",
        "scientific_classification": "native element mineral; carbon polymorph",
        "display_color": [210, 222, 226],
        "required_element_thresholds": {"C": 0.08},
        "favorable_planet_tags": ["carbon_bearing_crust", "plate_tectonic_surface"],
    },
    {
        "id": "mat_water_ice",
        "name": "Water Ice",
        "scientific_name": "hexagonal water ice",
        "chemical_formula": "H2O",
        "material_subclass": "ice",
        "scientific_classification": "volatile ice; molecular solid",
        "display_color": [196, 220, 232],
        "required_element_thresholds": {"H": 0.02, "O": 10.0},
        "favorable_planet_tags": ["water_rich_surface", "airless_regolith", "active_hydrology"],
    },
    {
        "id": "mat_carbon_dioxide_ice",
        "name": "Carbon Dioxide Ice",
        "scientific_name": "dry ice",
        "chemical_formula": "CO2",
        "material_subclass": "ice",
        "scientific_classification": "volatile ice; carbon oxide molecular solid",
        "display_color": [190, 196, 196],
        "required_element_thresholds": {"C": 0.02, "O": 10.0},
        "favorable_planet_tags": ["co2_bearing_atmosphere", "airless_regolith", "cratered_regolith"],
    },
    {
        "id": "mat_sulfur_ice",
        "name": "Sulfur Ice",
        "scientific_name": "solid elemental sulfur",
        "chemical_formula": "S8",
        "material_subclass": "ice",
        "scientific_classification": "volatile-rich molecular solid; sulfur allotrope",
        "display_color": [216, 188, 62],
        "required_element_thresholds": {"S": 0.02},
        "favorable_planet_tags": ["sulfur_bearing_crust", "volcanic_surface", "airless_regolith"],
    },
]

# Additional common rocks, sediments, regoliths, ores, and metamorphic
# assemblages.  These remain chemistry candidates here; their actual surface
# distribution is constrained by the explicit profiles in
# ``material_affinities.py``.
NATURAL_MATERIAL_CATALOG.extend([
    {
        "id": "mat_obsidian", "name": "Obsidian", "scientific_name": "volcanic glass",
        "chemical_formula": "silica-rich amorphous volcanic glass", "material_subclass": "rock",
        "scientific_classification": "igneous rock; volcanic glass",
        "display_color": [42, 38, 42], "required_element_thresholds": {"O": 20.0, "Si": 9.0},
        "favorable_planet_tags": ["volcanic_surface", "silica_rich_crust"],
    },
    {
        "id": "mat_pumice", "name": "Pumice", "scientific_name": "vesicular felsic volcanic glass",
        "chemical_formula": "vesicular silicic glass", "material_subclass": "rock",
        "scientific_classification": "igneous rock; pyroclastic; highly vesicular",
        "display_color": [190, 184, 170], "required_element_thresholds": {"O": 20.0, "Si": 9.0},
        "favorable_planet_tags": ["volcanic_surface", "silica_rich_crust"],
    },
    {
        "id": "mat_scoria", "name": "Scoria", "scientific_name": "mafic scoria",
        "chemical_formula": "vesicular mafic volcanic rock", "material_subclass": "rock",
        "scientific_classification": "igneous rock; volcanic; vesicular mafic",
        "display_color": [92, 54, 44], "required_element_thresholds": {"O": 18.0, "Si": 6.0, "Fe": 1.5},
        "favorable_planet_tags": ["volcanic_surface", "mafic_crust"],
    },
    {
        "id": "mat_tuff", "name": "Tuff", "scientific_name": "lithified volcanic ash",
        "chemical_formula": "consolidated pyroclastic material", "material_subclass": "rock",
        "scientific_classification": "igneous rock; pyroclastic; ash deposit",
        "display_color": [154, 142, 126], "required_element_thresholds": {"O": 18.0, "Si": 7.0},
        "favorable_planet_tags": ["volcanic_surface", "weathered_surface"],
    },
    {
        "id": "mat_mudstone", "name": "Mudstone", "scientific_name": "massive mudrock",
        "chemical_formula": "clay- and silt-rich sedimentary rock", "material_subclass": "rock",
        "scientific_classification": "sedimentary rock; fine clastic; mudrock",
        "display_color": [104, 94, 80], "required_element_thresholds": {"O": 18.0, "Si": 6.0, "Al": 1.5},
        "favorable_planet_tags": ["active_hydrology", "weathered_surface"],
    },
    {
        "id": "mat_chert", "name": "Chert", "scientific_name": "microcrystalline quartz",
        "chemical_formula": "SiO2", "material_subclass": "rock",
        "scientific_classification": "sedimentary rock; chemical or biogenic silica",
        "display_color": [132, 126, 114], "required_element_thresholds": {"O": 20.0, "Si": 10.0},
        "favorable_planet_tags": ["silica_rich_crust", "active_hydrology"],
    },
    {
        "id": "mat_marl", "name": "Marl", "scientific_name": "calcareous mud",
        "chemical_formula": "carbonate-clay sediment", "material_subclass": "sediment",
        "scientific_classification": "sediment; mixed carbonate and clay",
        "display_color": [176, 174, 150], "required_element_thresholds": {"O": 14.0, "Ca": 1.0, "C": 0.02, "Al": 1.0},
        "favorable_planet_tags": ["carbonate_favorable", "active_hydrology"],
    },
    {
        "id": "mat_slate", "name": "Slate", "scientific_name": "slate",
        "chemical_formula": "fine-grained foliated aluminosilicate rock", "material_subclass": "rock",
        "scientific_classification": "metamorphic rock; low-grade; foliated",
        "display_color": [78, 84, 88], "required_element_thresholds": {"O": 18.0, "Si": 6.0, "Al": 1.5},
        "favorable_planet_tags": ["plate_tectonic_surface", "silicate_crust"],
    },
    {
        "id": "mat_quartzite", "name": "Quartzite", "scientific_name": "quartzite",
        "chemical_formula": "metamorphosed quartz sandstone", "material_subclass": "rock",
        "scientific_classification": "metamorphic rock; non-foliated; silica-rich",
        "display_color": [184, 180, 170], "required_element_thresholds": {"O": 20.0, "Si": 10.0},
        "favorable_planet_tags": ["plate_tectonic_surface", "silica_rich_crust"],
    },
    {
        "id": "mat_loess", "name": "Loess", "scientific_name": "windblown silt",
        "chemical_formula": "quartz-feldspar silt", "material_subclass": "sediment",
        "scientific_classification": "unconsolidated sediment; aeolian silt",
        "display_color": [194, 172, 128], "required_element_thresholds": {"O": 18.0, "Si": 7.0},
        "favorable_planet_tags": ["aeolian_surface", "weathered_surface"],
    },
    {
        "id": "mat_alluvium", "name": "Alluvium", "scientific_name": "fluvial alluvium",
        "chemical_formula": "mixed river-transported sediment", "material_subclass": "sediment",
        "scientific_classification": "unconsolidated sediment; fluvial deposit",
        "display_color": [158, 138, 104], "required_element_thresholds": {"O": 12.0, "Si": 5.0},
        "favorable_planet_tags": ["active_hydrology", "weathered_surface"],
    },
    {
        "id": "mat_glacial_till", "name": "Glacial Till", "scientific_name": "diamicton",
        "chemical_formula": "unsorted glacial sediment", "material_subclass": "sediment",
        "scientific_classification": "unconsolidated sediment; glacial diamicton",
        "display_color": [126, 124, 116], "required_element_thresholds": {"O": 12.0, "Si": 5.0},
        "favorable_planet_tags": ["water_rich_surface", "weathered_surface"],
    },
    {
        "id": "mat_evaporite_crust", "name": "Evaporite Crust", "scientific_name": "mixed saline duricrust",
        "chemical_formula": "mixed chloride and sulfate salts", "material_subclass": "regolith",
        "scientific_classification": "chemical sediment; evaporitic surface crust",
        "display_color": [216, 206, 178], "required_element_thresholds": {"Na": 0.8, "S": 0.01},
        "favorable_planet_tags": ["evaporite_favorable", "arid_surface"],
    },
    {
        "id": "mat_travertine", "name": "Travertine", "scientific_name": "freshwater carbonate",
        "chemical_formula": "CaCO3", "material_subclass": "rock",
        "scientific_classification": "chemical sedimentary rock; spring carbonate",
        "display_color": [204, 192, 158], "required_element_thresholds": {"O": 12.0, "Ca": 1.0, "C": 0.02},
        "favorable_planet_tags": ["carbonate_favorable", "active_hydrology", "volcanic_surface"],
    },
    {
        "id": "mat_phosphorite", "name": "Phosphorite", "scientific_name": "phosphate rock",
        "chemical_formula": "apatite-rich sedimentary rock", "material_subclass": "rock",
        "scientific_classification": "sedimentary rock; chemical; phosphate-rich",
        "display_color": [118, 112, 82], "required_element_thresholds": {"O": 12.0, "Ca": 0.8, "P": 0.01},
        "favorable_planet_tags": ["active_hydrology", "carbonate_favorable"],
    },
    {
        "id": "mat_banded_iron_formation", "name": "Banded Iron Formation", "scientific_name": "banded iron formation",
        "chemical_formula": "alternating iron oxide and silica", "material_subclass": "rock",
        "scientific_classification": "chemical sedimentary rock; iron formation",
        "display_color": [126, 70, 62], "required_element_thresholds": {"O": 14.0, "Fe": 3.0, "Si": 5.0},
        "favorable_planet_tags": ["iron_rich_crust", "active_hydrology"],
    },
    {
        "id": "mat_goethite", "name": "Goethite", "scientific_name": "goethite",
        "chemical_formula": "FeO(OH)", "material_subclass": "mineral",
        "scientific_classification": "oxide-hydroxide mineral; weathering product",
        "display_color": [138, 92, 44], "required_element_thresholds": {"O": 12.0, "Fe": 1.5},
        "favorable_planet_tags": ["oxidizing_surface", "weathered_surface", "active_hydrology"],
    },
    {
        "id": "mat_limonite", "name": "Limonite", "scientific_name": "hydrated iron oxide mixture",
        "chemical_formula": "FeO(OH)*nH2O", "material_subclass": "regolith",
        "scientific_classification": "weathering residue; hydrated iron oxides",
        "display_color": [156, 108, 46], "required_element_thresholds": {"O": 12.0, "Fe": 1.5},
        "favorable_planet_tags": ["oxidizing_surface", "weathered_surface", "active_hydrology"],
    },
    {
        "id": "mat_garnet", "name": "Garnet", "scientific_name": "garnet group",
        "chemical_formula": "X3Y2(SiO4)3", "material_subclass": "mineral",
        "scientific_classification": "metamorphic silicate mineral; nesosilicate",
        "display_color": [118, 48, 54], "required_element_thresholds": {"O": 16.0, "Si": 5.0, "Al": 1.0},
        "favorable_planet_tags": ["plate_tectonic_surface", "silicate_crust"],
    },
    {
        "id": "mat_zircon", "name": "Zircon", "scientific_name": "zircon",
        "chemical_formula": "ZrSiO4", "material_subclass": "mineral",
        "scientific_classification": "accessory silicate mineral; zircon group",
        "display_color": [150, 116, 76], "required_element_thresholds": {"O": 12.0, "Si": 5.0, "Zr": 0.005},
        "favorable_planet_tags": ["felsic_crust", "silica_rich_crust"],
    },
    {
        "id": "mat_apatite", "name": "Apatite", "scientific_name": "apatite group",
        "chemical_formula": "Ca5(PO4)3(F,Cl,OH)", "material_subclass": "mineral",
        "scientific_classification": "phosphate mineral; apatite group",
        "display_color": [116, 152, 118], "required_element_thresholds": {"O": 12.0, "Ca": 0.8, "P": 0.01},
        "favorable_planet_tags": ["silicate_crust", "volcanic_surface"],
    },
    {
        "id": "mat_fluorite", "name": "Fluorite", "scientific_name": "fluorite",
        "chemical_formula": "CaF2", "material_subclass": "mineral",
        "scientific_classification": "halide mineral; hydrothermal vein mineral",
        "display_color": [136, 116, 168], "required_element_thresholds": {"Ca": 0.8, "F": 0.005},
        "favorable_planet_tags": ["volcanic_surface", "plate_tectonic_surface"],
    },
    {
        "id": "mat_native_sulfur", "name": "Native Sulfur", "scientific_name": "alpha-sulfur",
        "chemical_formula": "S8", "material_subclass": "mineral",
        "scientific_classification": "native element; volcanic and evaporitic mineral",
        "display_color": [224, 194, 54], "required_element_thresholds": {"S": 0.02},
        "favorable_planet_tags": ["sulfur_bearing_crust", "volcanic_surface", "evaporite_favorable"],
    },
    {
        "id": "mat_nickel_laterite", "name": "Nickel Laterite", "scientific_name": "lateritic nickel ore",
        "chemical_formula": "Ni-bearing Fe/Mg oxide weathering residue", "material_subclass": "regolith",
        "scientific_classification": "weathering residue; supergene nickel ore",
        "display_color": [142, 78, 44], "required_element_thresholds": {"O": 14.0, "Fe": 1.0, "Ni": 0.005},
        "favorable_planet_tags": ["weathered_surface", "active_hydrology", "ultramafic_tendency"],
    },
    {
        "id": "mat_saprolite", "name": "Saprolite", "scientific_name": "in-situ weathered bedrock",
        "chemical_formula": "chemically decomposed silicate rock", "material_subclass": "regolith",
        "scientific_classification": "weathering profile; isovolumetric regolith",
        "display_color": [160, 132, 94], "required_element_thresholds": {"O": 16.0, "Si": 6.0, "Al": 1.0},
        "favorable_planet_tags": ["weathered_surface", "active_hydrology"],
    },
    {
        "id": "mat_calcrete", "name": "Calcrete", "scientific_name": "pedogenic carbonate duricrust",
        "chemical_formula": "CaCO3-cemented regolith", "material_subclass": "regolith",
        "scientific_classification": "duricrust; pedogenic carbonate accumulation",
        "display_color": [202, 190, 154], "required_element_thresholds": {"O": 12.0, "Ca": 1.0, "C": 0.02},
        "favorable_planet_tags": ["carbonate_favorable", "arid_surface", "weathered_surface"],
    },
    {
        "id": "mat_ferricrete", "name": "Ferricrete", "scientific_name": "iron-cemented duricrust",
        "chemical_formula": "Fe oxide-cemented regolith", "material_subclass": "regolith",
        "scientific_classification": "duricrust; ferruginous weathering profile",
        "display_color": [134, 66, 42], "required_element_thresholds": {"O": 12.0, "Fe": 1.5},
        "favorable_planet_tags": ["oxidizing_surface", "weathered_surface"],
    },
    {
        "id": "mat_zeolite", "name": "Zeolite", "scientific_name": "zeolite group",
        "chemical_formula": "hydrated aluminosilicate framework", "material_subclass": "mineral",
        "scientific_classification": "silicate mineral; low-grade alteration product",
        "display_color": [190, 202, 188], "required_element_thresholds": {"O": 18.0, "Si": 6.0, "Al": 1.5},
        "favorable_planet_tags": ["hydrated_crust", "volcanic_surface", "active_hydrology"],
    },
    {
        "id": "mat_blueschist", "name": "Blueschist", "scientific_name": "blueschist facies rock",
        "chemical_formula": "glaucophane-bearing metamorphic rock", "material_subclass": "rock",
        "scientific_classification": "metamorphic rock; high-pressure low-temperature facies",
        "display_color": [70, 88, 116], "required_element_thresholds": {"O": 18.0, "Si": 6.0, "Na": 0.8},
        "favorable_planet_tags": ["plate_tectonic_surface", "hydrated_crust"],
    },
    {
        "id": "mat_eclogite", "name": "Eclogite", "scientific_name": "eclogite",
        "chemical_formula": "garnet-clinopyroxene metamorphic rock", "material_subclass": "rock",
        "scientific_classification": "metamorphic rock; high-pressure mafic facies",
        "display_color": [78, 98, 72], "required_element_thresholds": {"O": 16.0, "Si": 5.0, "Fe": 1.0, "Mg": 0.8},
        "favorable_planet_tags": ["plate_tectonic_surface", "mafic_crust"],
    },
])


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


# These compact phase data are deliberately conservative.  They decide
# whether a material can persist as the listed surface phase; the geological
# heatmap decides where a viable material can accumulate.
SURFACE_PHASE_PROPERTIES = {
    "mat_water_ice": {
        "phase": "water_frost",
        "molecule": "H2O",
        "triple_temperature_k": 273.16,
        "triple_pressure_bar": 0.006117,
        "sublimation_enthalpy_j_mol": 51_000.0,
    },
    "mat_carbon_dioxide_ice": {
        "phase": "carbon_dioxide_frost",
        "molecule": "CO2",
        "triple_temperature_k": 216.58,
        "triple_pressure_bar": 5.185,
        "sublimation_enthalpy_j_mol": 25_200.0,
    },
    "mat_sulfur_ice": {
        "phase": "solid_elemental_sulfur",
        "solid_temperature_max_k": 388.36,
    },
}
PHASE_MODEL_VERSION = "surface-phase-v1"
GAS_CONSTANT_J_MOL_K = 8.314462618


def _atmospheric_partial_pressure_bar(atmosphere, molecule):
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    try:
        total_pressure = max(0.0, float(atmosphere.get("surface_pressure_bar", 0.0) or 0.0))
    except (TypeError, ValueError):
        total_pressure = 0.0
    fraction = 0.0
    for component in atmosphere.get("composition") or []:
        if not isinstance(component, dict) or str(component.get("molecule") or "") != str(molecule):
            continue
        try:
            fraction = max(fraction, float(component.get("fraction", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
    return total_pressure * fraction


def material_surface_phase_profile(material_id, atmosphere=None):
    """Return phase constraints for one material at the world's atmosphere."""
    material_id = str(material_id or "")
    property_model = SURFACE_PHASE_PROPERTIES.get(material_id)
    if not isinstance(property_model, dict):
        return {
            "model_version": PHASE_MODEL_VERSION,
            "material_id": material_id,
            "phase": "structural_solid",
            "stability_kind": "solid",
            "transition_temperature_k": None,
        }

    profile = dict(property_model)
    profile.update({"model_version": PHASE_MODEL_VERSION, "material_id": material_id})
    if "solid_temperature_max_k" in profile:
        profile["stability_kind"] = "solid_to_liquid"
        profile["transition_temperature_k"] = float(profile["solid_temperature_max_k"])
        return profile

    partial_pressure = max(1e-12, _atmospheric_partial_pressure_bar(atmosphere, profile["molecule"]))
    triple_pressure = max(1e-12, float(profile["triple_pressure_bar"]))
    triple_temperature = float(profile["triple_temperature_k"])
    sublimation_enthalpy = max(1.0, float(profile["sublimation_enthalpy_j_mol"]))
    # Clausius–Clapeyron, anchored at the triple point.  It is an explicit
    # approximation, suitable for a generator rather than a full EOS.
    denominator = (
        1.0 / triple_temperature
        - GAS_CONSTANT_J_MOL_K / sublimation_enthalpy * math.log(partial_pressure / triple_pressure)
    )
    transition = triple_temperature if denominator <= 0.0 else 1.0 / denominator
    profile.update({
        "stability_kind": "sublimation",
        "partial_pressure_bar": partial_pressure,
        "transition_temperature_k": max(35.0, min(triple_temperature, transition)),
    })
    return profile


def material_surface_phase_stability(material_id, temperature_k, atmosphere=None, profile=None):
    """Evaluate whether a material can persist in its named surface phase."""
    profile = profile if isinstance(profile, dict) else material_surface_phase_profile(material_id, atmosphere=atmosphere)
    try:
        temperature_k = float(temperature_k)
    except (TypeError, ValueError):
        temperature_k = 0.0
    transition = profile.get("transition_temperature_k")
    if transition is None or temperature_k <= 0.0:
        stability = 1.0
    else:
        transition = float(transition)
        softness = max(2.5, transition * 0.025)
        stability = max(0.0, min(1.0, 0.5 + (transition - temperature_k) / (softness * 2.0)))
    return {
        **profile,
        "temperature_k": round(temperature_k, 3),
        "stability": round(stability, 5),
        "stable": stability >= 0.5,
    }


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


def _mix_colors(color_a, color_b, weight_b):
    """Return a bounded RGB mix without leaking palette math into renderers."""
    color_a = _coerce_color(color_a, [132, 126, 116])
    color_b = _coerce_color(color_b, [132, 126, 116])
    weight_b = max(0.0, min(1.0, float(weight_b or 0.0)))
    return [
        max(20, min(245, int(round(color_a[index] * (1.0 - weight_b) + color_b[index] * weight_b))))
        for index in range(3)
    ]


def _surface_phase_candidates(material_model, atmosphere=None):
    """Choose materials that can control a planet's visible ground colour.

    A composition inference lists every material plausibly present in the
    crust.  Ore minerals are important for resources but should not turn a
    sulfur-coated or basaltic world into an average of every trace mineral.
    Ices, regolith and exposed rocks are therefore treated as surface phases;
    the returned weight is a visual coverage proxy, not a mass fraction.
    """
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    try:
        surface_temperature_k = float(
            atmosphere.get("estimated_surface_temperature_k", atmosphere.get("equilibrium_temperature_k", 0.0)) or 0.0
        )
    except (TypeError, ValueError):
        surface_temperature_k = 0.0
    class_weights = {
        "ice": 5.0,
        "regolith": 1.15,
        "rock": 2.20,
        "mineral": 0.42,
    }
    candidates = []
    planetary_phases = material_model.get("planetary_surface_materials")
    source_materials = (
        planetary_phases
        if isinstance(planetary_phases, list) and planetary_phases
        else material_model.get("likely_materials") or []
    )
    for index, item in enumerate(source_materials):
        if not isinstance(item, dict) or not item.get("material_id"):
            continue
        detail_level = int(item.get("minimum_map_detail_level", 0) or 0)
        if detail_level > 0:
            continue
        material_id = str(item["material_id"])
        catalog_item = MATERIAL_BY_ID.get(material_id, {})
        material_subclass = str(item.get("material_subclass") or catalog_item.get("material_subclass") or "").lower()
        class_weight = class_weights.get(material_subclass, 0.25)
        confidence = max(0.05, float(item.get("confidence", item.get("fraction", 0.0)) or 0.0))
        evidence_tags = {str(tag) for tag in (item.get("evidence_tags") or [])}
        surface_evidence = sum(
            1
            for tag in evidence_tags
            if tag.endswith("_surface") or tag in {"airless_regolith", "cratered_regolith", "impact_gardening"}
        )
        rank_weight = max(0.45, 1.0 - index * 0.06)
        visual_weight = confidence * class_weight * (1.0 + min(0.35, surface_evidence * 0.12)) * rank_weight
        # Deposits and transported regolith can dominate individual basins,
        # but they must not recolour an entire planet at global resolution.
        distribution_scale = str(item.get("distribution_scale") or "planetary_province")
        if distribution_scale != "planetary_province":
            visual_weight *= 0.18
        if material_subclass == "regolith" and not evidence_tags.intersection(
            {"airless_regolith", "cratered_regolith", "impact_gardening"}
        ):
            visual_weight *= 0.58
        phase_stability = material_surface_phase_stability(
            material_id,
            surface_temperature_k,
            atmosphere=atmosphere,
        )
        visual_weight *= float(phase_stability["stability"])
        if visual_weight <= 0.002:
            continue
        candidates.append({
            "material_id": material_id,
            "name": item.get("name") or catalog_item.get("name") or material_id,
            "material_subclass": material_subclass or "unknown",
            "display_color": material_display_color(material_id, item.get("display_color")),
            "confidence": confidence,
            "visual_weight": visual_weight,
            "evidence_tags": sorted(evidence_tags),
            "phase_stability": phase_stability,
        })

    # Volatile solids are visually dominant where they persist.  This gives a
    # cold sulfur world its own yellow, sulfur-frosted identity instead of
    # blending it into the colours of associated sulphides and ores.
    ices = [item for item in candidates if item["material_subclass"] == "ice"]
    if ices:
        return sorted(ices, key=lambda item: (-item["visual_weight"], item["name"]))[:4]

    exposed = [item for item in candidates if item["material_subclass"] in {"regolith", "rock"}]
    if exposed:
        return sorted(exposed, key=lambda item: (-item["visual_weight"], item["name"]))[:4]
    return sorted(candidates, key=lambda item: (-item["visual_weight"], item["name"]))[:5]


def natural_material_entries():
    entries = []
    for material in [*ELEMENT_MATERIAL_CATALOG, *NATURAL_MATERIAL_CATALOG, *ATMOSPHERIC_MATERIAL_CATALOG]:
        is_gas = material["material_subclass"] == "atmospheric_gas"
        is_element = material["material_subclass"] == "element"
        affinity_profile = material_affinity_profile(material["id"])
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
            "surface_affinity_profile": (
                {
                    **affinity_profile,
                    "weights": dict(affinity_profile.get("weights") or {}),
                }
                if affinity_profile is not None
                else None
            ),
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
    if interior.get("volcanic_activity") in {"moderate", "high"}:
        tags.add("active_volcanism")
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
    credible_aqueous_reservoir = (
        "active_hydrology" in tags
        or (
            float(seed.get("water_fraction", 0.0) or 0.0) >= 0.08
            and str(seed.get("volatile_inventory") or "").strip().lower()
            not in {"", "none"}
        )
    )
    if (
        composition.get("S", 0.0) >= 0.01
        and composition.get("Ca", 0.0) >= 1.0
        and credible_aqueous_reservoir
    ):
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
        affinity_profile = material_affinity_profile(material["id"])
        minimum_detail_level = int(
            (affinity_profile or {}).get("minimum_map_detail_level", 0) or 0
        )
        carbon_rich_foundation = (
            material.get("id") == "mat_graphite"
            and elements.get("C", 0.0) >= 8.0
        )
        if carbon_rich_foundation:
            minimum_detail_level = 0
        elif material.get("material_subclass") == "mineral":
            minimum_detail_level = max(1, minimum_detail_level)
        distribution_scale = {
            0: "planetary_province",
            1: "macroregional_occurrence",
            2: "regional_deposit",
            3: "local_occurrence",
            4: "site_outcrop",
        }.get(minimum_detail_level, "local_occurrence")
        candidates.append({
            "material_id": material["id"],
            "name": material["name"],
            "material_subclass": material["material_subclass"],
            "scientific_classification": material["scientific_classification"],
            "chemical_formula": material["chemical_formula"],
            "display_color": material_display_color(material["id"]),
            "confidence": confidence,
            "occurrence": occurrence,
            "minimum_map_detail_level": minimum_detail_level,
            "distribution_scale": distribution_scale,
            "evidence_tags": favorable,
            "surface_affinity_profile": affinity_profile,
            "foundational_lithology": carbon_rich_foundation,
        })

    candidates.sort(key=lambda item: (-item["confidence"], item["name"]))
    palette = derive_planet_surface_palette({
        "likely_materials": candidates,
        "element_profile": elements,
    })
    planetary_materials = [
        item for item in candidates
        if int(item.get("minimum_map_detail_level", 0) or 0) == 0
    ]
    regional_candidates = [
        item for item in candidates
        if int(item.get("minimum_map_detail_level", 0) or 0) > 0
    ]
    return {
        "status": "inferred",
        "catalog_version": NATURAL_MATERIAL_CATALOG_VERSION,
        "planet_tags": sorted(tag_set),
        "element_profile": elements,
        "likely_materials": candidates,
        "planetary_surface_materials": planetary_materials,
        "regional_material_candidates": regional_candidates,
        "dominant_materials": [
            item["material_id"] for item in planetary_materials[:5]
        ],
        "surface_palette": palette,
    }


def derive_planet_surface_palette(material_model, atmosphere=None, terrain=None):
    material_model = material_model if isinstance(material_model, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    terrain = terrain if isinstance(terrain, dict) else {}
    surface_phases = _surface_phase_candidates(material_model, atmosphere=atmosphere)
    weighted = [
        (item["display_color"], item["visual_weight"])
        for item in surface_phases
    ]
    evidence = [
        {
            "material_id": item["material_id"],
            "name": item["name"],
            "material_subclass": item["material_subclass"],
            "weight": round(item["visual_weight"], 4),
            "confidence": round(item["confidence"], 3),
            "display_color": item["display_color"],
            "phase": item["phase_stability"].get("phase"),
            "phase_transition_temperature_k": item["phase_stability"].get("transition_temperature_k"),
            "phase_stability": item["phase_stability"].get("stability"),
        }
        for item in surface_phases
    ]

    element_profile = material_model.get("element_profile") if isinstance(material_model.get("element_profile"), dict) else {}
    phase_subclasses = {item["material_subclass"] for item in surface_phases}
    # Bulk chemistry supplies a useful fallback for ordinary rock worlds, but
    # it must not wash out a physically distinct surface phase such as sulfur
    # ice.  That phase has already formed from the bulk composition.
    if not phase_subclasses.intersection({"ice", "regolith", "rock"}):
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
    # Oceans and sea ice have their own renderer layers.  Mixing their colours
    # into the land palette made every continent converge toward one muddy
    # global tint.  Only grounded ice modifies the land palette here.
    if ice_fraction > 0.02:
        weighted.append(([210, 224, 232], min(0.35, ice_fraction * 0.45)))

    if not weighted and isinstance(atmosphere.get("composition"), list):
        atmosphere_palette = atmospheric_band_palette(atmosphere)
        weighted.append((atmosphere_palette.get("base_color", [150, 160, 172]), 1.0))

    surface = _blend_colors(weighted)
    phase_palette = bool(surface_phases and phase_subclasses.intersection({"ice", "regolith", "rock"}))
    if phase_palette:
        # A phase-led palette preserves the terrain's relief while keeping the
        # material legible at a glance.  Sulfur ice consequently reads as
        # dark ochre lowlands, sulfur-yellow plains and pale sulfur frost at
        # altitude rather than a uniformly tan crater field.
        palette = [
            _mix_colors(surface, [26, 24, 20], 0.43),
            surface,
            _mix_colors(surface, [238, 232, 204], 0.30),
            _mix_colors(surface, [20, 18, 16], 0.58),
        ]
    else:
        palette = [
            _shift_color(surface, -28),
            surface,
            _shift_color(surface, 24),
            _shift_color(surface, -12),
        ]
    primary = surface_phases[0] if surface_phases else None
    return {
        "palette_version": 3,
        "selection_scope": "planetary_surface_only",
        "render_mode": "surface_phase" if phase_palette else "bulk_composition",
        "surface_color": surface,
        "palette": palette,
        "primary_surface_material": primary.get("material_id") if primary else None,
        "primary_surface_material_name": primary.get("name") if primary else None,
        "surface_materials": evidence[:4],
        "evidence": evidence[:8],
    }
