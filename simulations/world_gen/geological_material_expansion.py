"""Additional geological materials shared by the catalog and spatial model.

The compact group definitions keep chemistry, classification, and world-gen
affinity authored together.  They intentionally represent distinct geological
materials rather than grade, colour, or commercial-name variants.
"""


SPECIAL_PRODUCTION_TAGS = {
    "mat_carbonatite": ["rare_element_ore_feedstock", "carbonate_feedstock"],
    "mat_kimberlite": ["diamond_host_rock"],
    "mat_pegmatite": ["critical_mineral_host_rock", "ceramic_feedstock"],
    "mat_marble": ["dimension_stone", "carbonate_feedstock"],
    "mat_skarn": ["ore_host_rock"],
    "mat_soapstone": ["dimension_stone", "refractory_feedstock"],
    "mat_chalk": ["lime_feedstock", "cement_feedstock"],
    "mat_coquina": ["lime_feedstock", "aggregate_feedstock"],
    "mat_dolostone": ["magnesium_feedstock", "lime_feedstock"],
    "mat_rock_salt": ["chemical_feedstock", "chloride_feedstock"],
    "mat_oil_shale": ["hydrocarbon_feedstock", "fuel_feedstock"],
    "mat_anthracite": ["carbon_feedstock", "fuel_feedstock"],
    "mat_lignite": ["carbon_feedstock", "fuel_feedstock"],
    "mat_ironstone": ["iron_ore_feedstock"],
    "mat_diatomite": ["filtration_media_feedstock", "silica_feedstock"],
    "mat_gypsum_rock": ["gypsum_feedstock", "cement_feedstock"],
    "mat_anhydrite_rock": ["sulfate_feedstock", "cement_feedstock"],
    "mat_calcareous_sandstone": ["aggregate_feedstock", "dimension_stone"],
    "mat_oolitic_limestone": ["lime_feedstock", "cement_feedstock"],
    "mat_claystone": ["ceramic_feedstock", "cement_feedstock"],
    "mat_clay": ["ceramic_feedstock", "bulk_earth_material"],
    "mat_dune_sand": ["glass_feedstock", "aggregate_feedstock"],
    "mat_beach_sand": ["aggregate_feedstock", "heavy_mineral_host_sediment"],
    "mat_tephra": ["pozzolan_feedstock", "aggregate_feedstock"],
    "mat_muscovite": ["electrical_insulator_feedstock"],
    "mat_orthoclase": ["ceramic_feedstock", "glass_feedstock"],
    "mat_microcline": ["ceramic_feedstock", "glass_feedstock"],
    "mat_albite": ["ceramic_feedstock", "glass_feedstock"],
    "mat_anorthite": ["ceramic_feedstock"],
    "mat_corundum": ["abrasive_feedstock", "refractory_feedstock", "aluminium_ore_feedstock"],
    "mat_boehmite": ["aluminium_ore_feedstock"],
    "mat_gibbsite": ["aluminium_ore_feedstock"],
    "mat_periclase": ["refractory_feedstock", "magnesium_feedstock"],
}


PROFILE_PLANET_TAGS = {
    "felsic_bedrock": ["felsic_crust", "silica_rich_crust", "plate_tectonic_surface"],
    "mafic_bedrock": ["mafic_crust", "basaltic_surface", "volcanic_surface"],
    "ultramafic_bedrock": ["mafic_crust", "ultramafic_tendency", "volcanic_surface"],
    "intermediate_volcanic": ["intermediate_silicate_crust", "volcanic_surface"],
    "felsic_volcanic": ["felsic_crust", "silica_rich_crust", "volcanic_surface"],
    "fresh_pyroclastic": ["volcanic_surface", "active_volcanism"],
    "plutonic_mineral": ["silicate_crust", "felsic_crust", "plate_tectonic_surface"],
    "metamorphic_uplift": ["plate_tectonic_surface", "silicate_crust"],
    "hydrothermal": ["volcanic_surface", "plate_tectonic_surface", "active_hydrology"],
    "sulfide_ore": ["sulfur_bearing_crust", "volcanic_surface", "plate_tectonic_surface"],
    "heavy_mineral": ["silicate_crust", "weathered_surface", "active_hydrology"],
    "fluvial_sediment": ["active_hydrology", "weathered_surface"],
    "colluvial_sediment": ["weathered_surface", "plate_tectonic_surface"],
    "fine_basin_sediment": ["active_hydrology", "weathered_surface"],
    "sand": ["aeolian_surface", "active_hydrology", "weathered_surface"],
    "conglomerate": ["active_hydrology", "weathered_surface", "plate_tectonic_surface"],
    "carbonate_basin": ["carbonate_favorable", "active_hydrology", "co2_bearing_atmosphere"],
    "evaporite": ["evaporite_favorable", "arid_surface", "active_hydrology"],
    "hydrated_alteration": ["hydrated_crust", "active_hydrology", "weathered_surface"],
    "clay_weathering": ["weathered_surface", "active_hydrology", "hydrated_crust"],
    "bauxite": ["weathered_surface", "active_hydrology", "felsic_crust"],
}


# member tuple:
# (id suffix, display name, formula/description, RGB colour,
#  additional required element thresholds, affinity profile)
GEOLOGICAL_MATERIAL_GROUPS = [
    {
        "subclass": "rock",
        "classification": "igneous rock; intrusive or volcanic lithology",
        "thresholds": {"O": 18.0, "Si": 6.0},
        "members": [
            ("diorite", "Diorite", "intermediate intrusive silicate rock", [112, 116, 112], {"Al": 1.5}, "felsic_bedrock"),
            ("granodiorite", "Granodiorite", "quartz-rich intermediate intrusive rock", [158, 154, 146], {"Al": 2.0}, "felsic_bedrock"),
            ("tonalite", "Tonalite", "plagioclase-quartz intrusive rock", [148, 148, 142], {"Al": 2.0, "Ca": 0.5}, "felsic_bedrock"),
            ("syenite", "Syenite", "alkali-feldspar-rich intrusive rock", [166, 148, 132], {"Al": 2.0, "K": 0.5}, "felsic_bedrock"),
            ("monzonite", "Monzonite", "alkali-feldspar and plagioclase intrusive rock", [142, 132, 116], {"Al": 2.0, "K": 0.3}, "felsic_bedrock"),
            ("anorthosite", "Anorthosite", "plagioclase-dominant intrusive rock", [188, 190, 184], {"Al": 3.0, "Ca": 0.8}, "mafic_bedrock"),
            ("diabase", "Diabase", "medium-grained mafic hypabyssal rock", [62, 72, 66], {"Fe": 1.2, "Mg": 0.6}, "mafic_bedrock"),
            ("dunite", "Dunite", "olivine-dominant ultramafic rock", [96, 112, 72], {"Mg": 3.0}, "ultramafic_bedrock"),
            ("komatiite", "Komatiite", "high-magnesium ultramafic volcanic rock", [76, 96, 66], {"Mg": 3.5}, "ultramafic_bedrock"),
            ("dacite", "Dacite", "silica-rich intermediate volcanic rock", [154, 148, 140], {"Al": 1.5}, "felsic_volcanic"),
            ("trachyte", "Trachyte", "alkali-rich volcanic rock", [164, 146, 124], {"Al": 1.5, "K": 0.4}, "intermediate_volcanic"),
            ("phonolite", "Phonolite", "feldspathoid-bearing alkaline volcanic rock", [116, 126, 106], {"Al": 1.5, "Na": 0.5}, "intermediate_volcanic"),
            ("latite", "Latite", "potassic intermediate volcanic rock", [126, 116, 104], {"Al": 1.5, "K": 0.3}, "intermediate_volcanic"),
            ("pegmatite", "Pegmatite", "very coarse-grained granitic rock", [202, 184, 174], {"Al": 2.0, "K": 0.4}, "plutonic_mineral"),
            ("carbonatite", "Carbonatite", "carbonate-dominant igneous rock", [190, 184, 150], {"Ca": 1.0, "C": 0.02}, "hydrothermal"),
            ("kimberlite", "Kimberlite", "volatile-rich ultramafic volcanic rock", [72, 94, 76], {"Mg": 2.0}, "ultramafic_bedrock"),
            ("ignimbrite", "Ignimbrite", "welded pyroclastic-flow deposit", [164, 132, 116], {"Al": 1.0}, "fresh_pyroclastic"),
            ("nepheline_syenite", "Nepheline Syenite", "silica-undersaturated alkaline intrusive rock", [172, 166, 148], {"Al": 2.0, "Na": 0.7}, "felsic_bedrock"),
        ],
    },
    {
        "subclass": "rock",
        "classification": "metamorphic rock; recrystallized tectonic lithology",
        "thresholds": {"O": 16.0, "Si": 5.0},
        "members": [
            ("marble", "Marble", "recrystallized carbonate rock", [210, 206, 194], {"Ca": 1.0, "C": 0.02}, "metamorphic_uplift"),
            ("gneiss", "Gneiss", "banded high-grade metamorphic rock", [128, 124, 118], {"Al": 1.5}, "metamorphic_uplift"),
            ("schist", "Schist", "mica-rich foliated metamorphic rock", [104, 100, 92], {"Al": 1.5, "K": 0.3}, "metamorphic_uplift"),
            ("phyllite", "Phyllite", "fine-grained foliated metamorphic rock", [94, 100, 98], {"Al": 1.5}, "metamorphic_uplift"),
            ("amphibolite", "Amphibolite", "hornblende-plagioclase metamorphic rock", [56, 72, 62], {"Fe": 1.0, "Mg": 0.5}, "metamorphic_uplift"),
            ("hornfels", "Hornfels", "contact-metamorphosed fine-grained rock", [78, 74, 72], {"Al": 1.0}, "metamorphic_uplift"),
            ("migmatite", "Migmatite", "partially melted high-grade metamorphic rock", [142, 130, 122], {"Al": 1.5}, "metamorphic_uplift"),
            ("granulite", "Granulite", "high-temperature anhydrous metamorphic rock", [112, 102, 92], {"Al": 1.0}, "metamorphic_uplift"),
            ("serpentinite", "Serpentinite", "serpentine-rich altered ultramafic rock", [70, 110, 78], {"Mg": 2.0}, "hydrated_alteration"),
            ("metaconglomerate", "Metaconglomerate", "metamorphosed conglomerate", [132, 116, 102], {}, "metamorphic_uplift"),
            ("metabasalt", "Metabasalt", "metamorphosed basaltic rock", [62, 82, 70], {"Fe": 1.0, "Mg": 0.5}, "metamorphic_uplift"),
            ("greenschist", "Greenschist", "chlorite-actinolite low-grade metamorphic rock", [74, 104, 78], {"Fe": 0.8, "Mg": 0.5}, "hydrated_alteration"),
            ("skarn", "Skarn", "calc-silicate metasomatic rock", [124, 114, 86], {"Ca": 0.8}, "hydrothermal"),
            ("mylonite", "Mylonite", "ductile fault-zone metamorphic rock", [96, 92, 88], {}, "metamorphic_uplift"),
            ("cataclasite", "Cataclasite", "brittle fault-zone fragmental rock", [88, 82, 76], {}, "metamorphic_uplift"),
            ("soapstone", "Soapstone", "talc-rich metamorphic rock", [132, 150, 132], {"Mg": 1.0}, "hydrated_alteration"),
        ],
    },
    {
        "subclass": "rock",
        "classification": "sedimentary rock; clastic, chemical, or organic lithology",
        "thresholds": {"O": 12.0},
        "members": [
            ("arkose", "Arkose", "feldspar-rich sandstone", [174, 132, 112], {"Si": 7.0, "Al": 1.5, "K": 0.3}, "sand"),
            ("greywacke", "Greywacke", "matrix-rich immature sandstone", [94, 98, 92], {"Si": 6.0, "Al": 1.0}, "fine_basin_sediment"),
            ("sedimentary_breccia", "Sedimentary Breccia", "lithified angular clastic deposit", [132, 112, 94], {"Si": 5.0}, "conglomerate"),
            ("chalk", "Chalk", "fine-grained porous carbonate rock", [222, 218, 196], {"Ca": 1.0, "C": 0.02}, "carbonate_basin"),
            ("coquina", "Coquina", "coarse bioclastic carbonate rock", [208, 190, 154], {"Ca": 1.0, "C": 0.02}, "carbonate_basin"),
            ("dolostone", "Dolostone", "dolomite-dominant carbonate rock", [184, 174, 150], {"Ca": 0.8, "Mg": 0.4, "C": 0.02}, "carbonate_basin"),
            ("rock_salt", "Rock Salt", "halite-dominant evaporite rock", [220, 208, 196], {"Na": 0.8, "Cl": 0.01}, "evaporite"),
            ("oil_shale", "Oil Shale", "organic-rich fine sedimentary rock", [64, 62, 54], {"Si": 4.0, "C": 0.08}, "fine_basin_sediment"),
            ("anthracite", "Anthracite", "high-rank metamorphosed coal", [38, 40, 42], {"C": 0.2}, "metamorphic_uplift"),
            ("lignite", "Lignite", "low-rank brown coal", [72, 52, 38], {"C": 0.15}, "fine_basin_sediment"),
            ("ironstone", "Ironstone", "iron-rich sedimentary rock", [126, 72, 52], {"Fe": 2.0}, "fine_basin_sediment"),
            ("diatomite", "Diatomite", "porous biogenic silica rock", [216, 210, 190], {"Si": 7.0}, "fine_basin_sediment"),
            ("gypsum_rock", "Gypsum Rock", "gypsum-dominant evaporite rock", [214, 204, 186], {"Ca": 1.0, "S": 0.02}, "evaporite"),
            ("anhydrite_rock", "Anhydrite Rock", "anhydrite-dominant evaporite rock", [190, 186, 174], {"Ca": 1.0, "S": 0.02}, "evaporite"),
            ("calcareous_sandstone", "Calcareous Sandstone", "carbonate-cemented sandstone", [186, 160, 122], {"Si": 5.0, "Ca": 0.8, "C": 0.02}, "sand"),
            ("radiolarite", "Radiolarite", "microcrystalline siliceous sedimentary rock", [142, 88, 82], {"Si": 8.0}, "fine_basin_sediment"),
            ("oolitic_limestone", "Oolitic Limestone", "carbonate ooid grainstone", [204, 190, 154], {"Ca": 1.0, "C": 0.02}, "carbonate_basin"),
            ("claystone", "Claystone", "massive clay-rich sedimentary rock", [112, 98, 80], {"Si": 5.0, "Al": 1.5}, "fine_basin_sediment"),
        ],
    },
    {
        "subclass": "sediment",
        "classification": "unconsolidated sediment; transported or deposited surface material",
        "thresholds": {"O": 10.0, "Si": 4.0},
        "members": [
            ("gravel", "Gravel", "mixed coarse clastic sediment", [136, 124, 108], {}, "conglomerate"),
            ("clay", "Clay", "fine hydrated aluminosilicate sediment", [134, 116, 94], {"Al": 1.5}, "clay_weathering"),
            ("silt", "Silt", "fine quartz-feldspar sediment", [158, 142, 116], {}, "fine_basin_sediment"),
            ("dune_sand", "Dune Sand", "wind-sorted granular silicate sediment", [202, 166, 112], {}, "sand"),
            ("beach_sand", "Beach Sand", "shoreline-sorted granular sediment", [194, 176, 138], {}, "sand"),
            ("lacustrine_mud", "Lacustrine Mud", "fine lake-basin sediment", [102, 94, 76], {"Al": 1.0}, "fine_basin_sediment"),
            ("marine_mud", "Marine Mud", "fine marine-basin sediment", [86, 92, 84], {"Al": 1.0}, "fine_basin_sediment"),
            ("colluvium", "Colluvium", "gravity-transported slope sediment", [138, 116, 92], {}, "colluvial_sediment"),
            ("talus", "Talus", "angular rockfall debris", [118, 110, 102], {}, "colluvial_sediment"),
            ("tephra", "Tephra", "unconsolidated pyroclastic ejecta", [132, 112, 102], {}, "fresh_pyroclastic"),
        ],
    },
    {
        "subclass": "mineral",
        "classification": "silicate mineral; rock-forming or accessory crystalline phase",
        "thresholds": {"O": 14.0, "Si": 4.0},
        "members": [
            ("muscovite", "Muscovite", "KAl2(AlSi3O10)(OH)2", [184, 176, 154], {"Al": 2.0, "K": 0.4}, "plutonic_mineral"),
            ("orthoclase", "Orthoclase", "KAlSi3O8", [206, 170, 154], {"Al": 1.5, "K": 0.5}, "plutonic_mineral"),
            ("microcline", "Microcline", "KAlSi3O8", [174, 194, 166], {"Al": 1.5, "K": 0.5}, "plutonic_mineral"),
            ("albite", "Albite", "NaAlSi3O8", [218, 214, 204], {"Al": 1.5, "Na": 0.7}, "plutonic_mineral"),
            ("anorthite", "Anorthite", "CaAl2Si2O8", [178, 174, 164], {"Al": 2.0, "Ca": 0.8}, "plutonic_mineral"),
            ("forsterite", "Forsterite", "Mg2SiO4", [154, 174, 112], {"Mg": 2.0}, "mafic_bedrock"),
            ("fayalite", "Fayalite", "Fe2SiO4", [86, 76, 56], {"Fe": 2.0}, "mafic_bedrock"),
            ("enstatite", "Enstatite", "MgSiO3", [124, 136, 104], {"Mg": 1.0}, "mafic_bedrock"),
            ("augite", "Augite", "(Ca,Na)(Mg,Fe,Al,Ti)(Si,Al)2O6", [64, 78, 62], {"Ca": 0.5, "Mg": 0.5}, "mafic_bedrock"),
            ("diopside", "Diopside", "CaMgSi2O6", [122, 158, 118], {"Ca": 0.8, "Mg": 0.7}, "plutonic_mineral"),
            ("hornblende", "Hornblende", "complex Ca-Mg-Fe amphibole", [46, 62, 52], {"Ca": 0.5, "Fe": 0.8}, "hydrated_alteration"),
            ("glaucophane", "Glaucophane", "Na2(Mg3Al2)Si8O22(OH)2", [74, 96, 146], {"Na": 0.7, "Mg": 0.6, "Al": 1.0}, "metamorphic_uplift"),
            ("kyanite", "Kyanite", "Al2SiO5", [92, 122, 172], {"Al": 2.0}, "metamorphic_uplift"),
            ("sillimanite", "Sillimanite", "Al2SiO5", [180, 170, 146], {"Al": 2.0}, "metamorphic_uplift"),
            ("andalusite", "Andalusite", "Al2SiO5", [184, 132, 112], {"Al": 2.0}, "metamorphic_uplift"),
            ("staurolite", "Staurolite", "(Fe,Mg)2Al9Si4O23(OH)", [112, 72, 46], {"Fe": 0.8, "Al": 2.0}, "metamorphic_uplift"),
            ("epidote", "Epidote", "Ca2(Al,Fe)3Si3O12(OH)", [126, 146, 62], {"Ca": 0.8, "Al": 1.5}, "hydrated_alteration"),
            ("tourmaline", "Tourmaline", "complex borosilicate", [72, 54, 62], {"Al": 1.0, "B": 0.002}, "hydrothermal"),
            ("beryl", "Beryl", "Be3Al2Si6O18", [132, 188, 170], {"Be": 0.001, "Al": 1.0}, "heavy_mineral"),
            ("spodumene", "Spodumene", "LiAlSi2O6", [174, 160, 188], {"Li": 0.001, "Al": 1.0}, "heavy_mineral"),
            ("lepidolite", "Lepidolite", "K(Li,Al)3(Al,Si)4O10(F,OH)2", [186, 134, 174], {"Li": 0.001, "K": 0.3}, "hydrothermal"),
            ("nepheline", "Nepheline", "(Na,K)AlSiO4", [190, 188, 168], {"Na": 0.5, "Al": 1.0}, "plutonic_mineral"),
            ("sodalite", "Sodalite", "Na8(Al6Si6O24)Cl2", [76, 104, 174], {"Na": 0.7, "Al": 1.0, "Cl": 0.005}, "plutonic_mineral"),
            ("wollastonite", "Wollastonite", "CaSiO3", [210, 208, 196], {"Ca": 0.8}, "metamorphic_uplift"),
        ],
    },
    {
        "subclass": "mineral",
        "classification": "clay or hydrated alteration mineral; secondary crystalline phase",
        "thresholds": {"O": 16.0},
        "members": [
            ("illite", "Illite", "K0.65Al2(Al0.65Si3.35)O10(OH)2", [142, 132, 106], {"Si": 5.0, "Al": 1.5, "K": 0.2}, "clay_weathering"),
            ("smectite", "Smectite", "hydrated expandable aluminosilicate", [152, 140, 112], {"Si": 5.0, "Al": 1.0}, "clay_weathering"),
            ("halloysite", "Halloysite", "Al2Si2O5(OH)4", [202, 198, 180], {"Si": 4.0, "Al": 1.5}, "clay_weathering"),
            ("pyrophyllite", "Pyrophyllite", "Al2Si4O10(OH)2", [192, 190, 174], {"Si": 6.0, "Al": 1.5}, "hydrated_alteration"),
            ("brucite", "Brucite", "Mg(OH)2", [194, 208, 186], {"Mg": 1.0}, "hydrated_alteration"),
            ("vermiculite", "Vermiculite", "hydrated Mg-Al-Fe phyllosilicate", [150, 126, 82], {"Si": 4.0, "Mg": 0.6, "Al": 1.0}, "clay_weathering"),
        ],
    },
    {
        "subclass": "mineral",
        "classification": "oxide, tungstate, or rare-element ore mineral",
        "thresholds": {"O": 8.0},
        "members": [
            ("rutile", "Rutile", "TiO2", [106, 66, 54], {"Ti": 0.03}, "heavy_mineral"),
            ("anatase", "Anatase", "TiO2", [72, 82, 112], {"Ti": 0.03}, "heavy_mineral"),
            ("brookite", "Brookite", "TiO2", [98, 72, 54], {"Ti": 0.03}, "heavy_mineral"),
            ("corundum", "Corundum", "Al2O3", [146, 154, 166], {"Al": 2.0}, "metamorphic_uplift"),
            ("spinel", "Spinel", "MgAl2O4", [112, 90, 102], {"Mg": 0.5, "Al": 1.5}, "metamorphic_uplift"),
            ("cuprite", "Cuprite", "Cu2O", [156, 46, 34], {"Cu": 0.002}, "heavy_mineral"),
            ("uraninite", "Uraninite", "UO2", [44, 50, 42], {"U": 0.0001}, "heavy_mineral"),
            ("pyrolusite", "Pyrolusite", "MnO2", [54, 52, 56], {"Mn": 0.03}, "heavy_mineral"),
            ("manganite", "Manganite", "MnO(OH)", [58, 54, 54], {"Mn": 0.03}, "hydrothermal"),
            ("boehmite", "Boehmite", "AlO(OH)", [196, 190, 172], {"Al": 2.0}, "bauxite"),
            ("gibbsite", "Gibbsite", "Al(OH)3", [208, 204, 190], {"Al": 2.0}, "bauxite"),
            ("periclase", "Periclase", "MgO", [190, 196, 180], {"Mg": 1.0}, "metamorphic_uplift"),
            ("columbite", "Columbite", "(Fe,Mn)Nb2O6", [48, 48, 50], {"Fe": 0.5, "Nb": 0.0001}, "heavy_mineral"),
            ("tantalite", "Tantalite", "(Fe,Mn)Ta2O6", [50, 44, 44], {"Fe": 0.5, "Ta": 0.0001}, "heavy_mineral"),
            ("wolframite", "Wolframite", "(Fe,Mn)WO4", [54, 46, 42], {"Fe": 0.5, "W": 0.0001}, "heavy_mineral"),
            ("scheelite", "Scheelite", "CaWO4", [200, 188, 124], {"Ca": 0.5, "W": 0.0001}, "hydrothermal"),
            ("monazite", "Monazite", "(Ce,La,Nd,Th)PO4", [156, 116, 66], {"P": 0.005, "Ce": 0.0001}, "heavy_mineral"),
            ("xenotime", "Xenotime", "YPO4", [142, 106, 68], {"P": 0.005, "Y": 0.0001}, "heavy_mineral"),
        ],
    },
    {
        "subclass": "mineral",
        "classification": "sulfide or sulfosalt ore mineral; concentrated hydrothermal phase",
        "thresholds": {"S": 0.01},
        "members": [
            ("bornite", "Bornite", "Cu5FeS4", [116, 72, 76], {"Cu": 0.002, "Fe": 0.5}, "sulfide_ore"),
            ("chalcocite", "Chalcocite", "Cu2S", [54, 58, 62], {"Cu": 0.002}, "sulfide_ore"),
            ("covellite", "Covellite", "CuS", [48, 66, 94], {"Cu": 0.002}, "sulfide_ore"),
            ("molybdenite", "Molybdenite", "MoS2", [88, 92, 98], {"Mo": 0.0001}, "sulfide_ore"),
            ("pentlandite", "Pentlandite", "(Fe,Ni)9S8", [126, 110, 72], {"Fe": 0.5, "Ni": 0.002}, "sulfide_ore"),
            ("arsenopyrite", "Arsenopyrite", "FeAsS", [154, 150, 140], {"Fe": 0.5, "As": 0.0005}, "sulfide_ore"),
            ("cinnabar", "Cinnabar", "HgS", [176, 44, 36], {"Hg": 0.0001}, "hydrothermal"),
            ("stibnite", "Stibnite", "Sb2S3", [92, 96, 104], {"Sb": 0.0001}, "hydrothermal"),
            ("realgar", "Realgar", "As4S4", [212, 82, 42], {"As": 0.0005}, "hydrothermal"),
            ("orpiment", "Orpiment", "As2S3", [224, 174, 54], {"As": 0.0005}, "hydrothermal"),
            ("marcasite", "Marcasite", "FeS2", [158, 146, 102], {"Fe": 0.5}, "sulfide_ore"),
            ("cobaltite", "Cobaltite", "CoAsS", [126, 130, 132], {"Co": 0.0005, "As": 0.0005}, "sulfide_ore"),
        ],
    },
]


def geological_material_expansion():
    """Return independent catalog dictionaries for the geological additions."""
    materials = []
    for group in GEOLOGICAL_MATERIAL_GROUPS:
        for suffix, name, formula, color, thresholds, profile_id in group["members"]:
            required = dict(group["thresholds"])
            required.update(thresholds)
            materials.append({
                "id": f"mat_{suffix}",
                "name": name,
                "scientific_name": name.lower(),
                "chemical_formula": formula,
                "material_subclass": group["subclass"],
                "scientific_classification": group["classification"],
                "display_color": list(color),
                "required_element_thresholds": required,
                "favorable_planet_tags": list(PROFILE_PLANET_TAGS[profile_id]),
                "worldgen_affinity_profile": profile_id,
                "production_role_tags": list(
                    SPECIAL_PRODUCTION_TAGS.get(f"mat_{suffix}", [])
                ),
            })
    return materials


GEOLOGICAL_PROFILE_TYPES = {
    material["id"]: material["worldgen_affinity_profile"]
    for material in geological_material_expansion()
}
