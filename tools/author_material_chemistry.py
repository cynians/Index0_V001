"""Author material chemistry on the ontology so element distributions decide the material roster.

Writes, on the live ontology store (no ``.owl`` export unless ``--export``):

1. element entities: ``earth_upper_crust_abundance_ppm`` -- the reference
   crust used as the yardstick for enrichment and as the shape of the
   background for elements a planet does not list;
2. minerals and ices: ``elemental_composition_wt`` from the formula, with a
   ``computational_formula`` or ``composition_endmembers`` (solid solutions)
   where the display formula is not computable;
3. rocks, sediments and regolith: ``bulk_composition_wt`` (component formula
   -> wt %; oxides, salts, native elements, organic carbon as C),
   ``modal_mineralogy_wt`` (mineral id -> approximate wt %, ``modal_basis``
   ``modal`` or ``normative`` for glassy and organic rocks) and the derived
   ``elemental_composition_wt``;
4. ``required_element_thresholds`` derived from the composition (the crust
   abundance at which the material falls to 15 % of its Earth availability),
   replacing hand-set placeholders;
5. the new fields on ``schema_materials``.

Reference abundances: Rudnick & Gao (2003) upper continental crust; carbon
from Wedepohl (1995) upper crust (3240 ppm, carbonate carbon included, since
surface materials are what the roster describes); sulfur and H, noble gases,
Rh, Te and short-lived nuclides from CRC Handbook crustal abundances, which
Rudnick & Gao do not list (their S of 62 ppm would leave an Earth-like crust
below the evaporite and sulfide tags).  Values were entered from memory
and are unverified against the primary tables.  Bulk compositions are typical
literature averages (Le Maitre 1976 igneous averages, standard sedimentary and
metamorphic averages), rounded.

Existing entities are merged from their full current dict (the store replaces
whole entities).  Re-runnable.
"""

from __future__ import annotations

import argparse
import copy
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulations.world_gen import material_chemistry as chem  # noqa: E402
from simulations.world_gen.crust import default_crust_composition  # noqa: E402
from world.persistent_ontology_store import PersistentOntologyStore  # noqa: E402

ONTOLOGY_PATH = ROOT / "ontology" / "index0.owl"

ELEMENT_REFERENCE_PPM = {
    "H": 1400.0, "He": 0.008, "Li": 24.0, "Be": 2.1, "B": 17.0, "C": 3240.0, "N": 83.0,
    "O": 473000.0, "F": 557.0, "Ne": 0.005, "Na": 24259.0, "Mg": 14956.0, "Al": 81500.0,
    "Si": 311400.0, "P": 655.0, "S": 350.0, "Cl": 370.0, "Ar": 3.5, "K": 23244.0,
    "Ca": 25657.0, "Sc": 14.0, "Ti": 3836.0, "V": 97.0, "Cr": 92.0, "Mn": 774.0,
    "Fe": 39180.0, "Co": 17.3, "Ni": 47.0, "Cu": 28.0, "Zn": 67.0, "Ga": 17.5, "Ge": 1.4,
    "As": 4.8, "Se": 0.09, "Br": 1.6, "Kr": 0.0001, "Rb": 84.0, "Sr": 320.0, "Y": 21.0,
    "Zr": 193.0, "Nb": 12.0, "Mo": 1.1, "Tc": 1e-12, "Ru": 0.00034, "Rh": 0.001,
    "Pd": 0.00052, "Ag": 0.053, "Cd": 0.09, "In": 0.056, "Sn": 2.1, "Sb": 0.4, "Te": 0.001,
    "I": 1.4, "Xe": 0.00003, "Cs": 4.9, "Ba": 624.0, "La": 31.0, "Ce": 63.0, "Pr": 7.1,
    "Nd": 27.0, "Pm": 1e-15, "Sm": 4.7, "Eu": 1.0, "Gd": 4.0, "Tb": 0.7, "Dy": 3.9,
    "Ho": 0.83, "Er": 2.3, "Tm": 0.3, "Yb": 1.96, "Lu": 0.31, "Hf": 5.3, "Ta": 0.9,
    "W": 1.9, "Re": 0.000198, "Os": 0.000031, "Ir": 0.000022, "Pt": 0.0005, "Au": 0.0015,
    "Hg": 0.05, "Tl": 0.9, "Pb": 17.0, "Bi": 0.16, "Po": 2e-10, "At": 3e-20, "Rn": 4e-13,
    "Fr": 1e-18, "Ra": 9e-7, "Ac": 5.5e-10, "Th": 10.5, "Pa": 1.4e-6, "U": 2.7,
}


def _em(*pairs):
    return [{"formula": formula, "mass_fraction": fraction, "name": name} for name, formula, fraction in pairs]


# Minerals whose display formula is prose, a site placeholder, or a solid
# solution that needs real proportions.
MINERAL_CHEMISTRY = {
    "mat_alkali_feldspar": {"endmembers": _em(("orthoclase", "KAlSi3O8", 0.7), ("albite", "NaAlSi3O8", 0.3))},
    "mat_plagioclase_feldspar": {"endmembers": _em(("albite", "NaAlSi3O8", 0.5), ("anorthite", "CaAl2Si2O8", 0.5))},
    "mat_amphibole": {"endmembers": _em(
        ("tremolite", "Ca2Mg5Si8O22(OH)2", 0.35), ("ferro-actinolite", "Ca2Fe5Si8O22(OH)2", 0.15),
        ("tschermakite", "Ca2(Mg3Al2)(Si6Al2)O22(OH)2", 0.35), ("pargasite", "NaCa2(Mg4Al)(Si6Al2)O22(OH)2", 0.15))},
    "mat_hornblende": {"endmembers": _em(
        ("magnesio-hornblende", "Ca2(Mg4Al)(Si7Al)O22(OH)2", 0.5), ("ferro-hornblende", "Ca2(Fe4Al)(Si7Al)O22(OH)2", 0.3),
        ("pargasite", "NaCa2(Mg4Al)(Si6Al2)O22(OH)2", 0.2))},
    "mat_augite": {"endmembers": _em(
        ("diopside", "CaMgSi2O6", 0.55), ("hedenbergite", "CaFeSi2O6", 0.25), ("enstatite", "Mg2Si2O6", 0.1),
        ("Ca-Tschermak", "CaAl2SiO6", 0.07), ("jadeite", "NaAlSi2O6", 0.03))},
    "mat_pyroxene": {"endmembers": _em(
        ("diopside", "CaMgSi2O6", 0.35), ("hedenbergite", "CaFeSi2O6", 0.15), ("enstatite", "Mg2Si2O6", 0.3),
        ("ferrosilite", "Fe2Si2O6", 0.2))},
    "mat_olivine": {"endmembers": _em(("forsterite", "Mg2SiO4", 0.85), ("fayalite", "Fe2SiO4", 0.15))},
    "mat_biotite": {"endmembers": _em(("phlogopite", "KMg3AlSi3O10(OH)2", 0.45), ("annite", "KFe3AlSi3O10(OH)2", 0.55))},
    "mat_chlorite": {"endmembers": _em(("clinochlore", "Mg5Al2Si3O10(OH)8", 0.6), ("chamosite", "Fe5Al2Si3O10(OH)8", 0.4))},
    "mat_serpentine": {"endmembers": _em(("lizardite", "Mg3Si2O5(OH)4", 0.93), ("greenalite", "Fe3Si2O5(OH)4", 0.07))},
    "mat_epidote": {"endmembers": _em(("clinozoisite", "Ca2Al3Si3O12(OH)", 0.5), ("epidote", "Ca2Al2FeSi3O12(OH)", 0.5))},
    "mat_garnet": {"endmembers": _em(
        ("almandine", "Fe3Al2Si3O12", 0.5), ("pyrope", "Mg3Al2Si3O12", 0.2), ("grossular", "Ca3Al2Si3O12", 0.2),
        ("spessartine", "Mn3Al2Si3O12", 0.1))},
    "mat_staurolite": {"endmembers": _em(("Fe-staurolite", "Fe2Al9Si4O23(OH)", 0.85), ("Mg-staurolite", "Mg2Al9Si4O23(OH)", 0.15))},
    "mat_columbite": {"endmembers": _em(("ferrocolumbite", "FeNb2O6", 0.7), ("manganocolumbite", "MnNb2O6", 0.3))},
    "mat_tantalite": {"endmembers": _em(("ferrotantalite", "FeTa2O6", 0.6), ("manganotantalite", "MnTa2O6", 0.4))},
    "mat_wolframite": {"endmembers": _em(("ferberite", "FeWO4", 0.5), ("huebnerite", "MnWO4", 0.5))},
    "mat_monazite": {"endmembers": _em(("monazite-Ce", "CePO4", 0.5), ("monazite-La", "LaPO4", 0.25), ("monazite-Nd", "NdPO4", 0.2), ("huttonite", "ThSiO4", 0.05))},
    "mat_apatite": {"endmembers": _em(("fluorapatite", "Ca5(PO4)3F", 0.7), ("hydroxylapatite", "Ca5(PO4)3(OH)", 0.2), ("chlorapatite", "Ca5(PO4)3Cl", 0.1))},
    "mat_nepheline": {"formula": "Na3KAl4Si4O16"},
    "mat_lepidolite": {"formula": "KLi1.5Al2.5Si3O10F2"},
    "mat_montmorillonite": {"formula": "Na0.33Al1.67Mg0.33Si4O10(OH)2*4H2O"},
    "mat_smectite": {"formula": "Na0.2Ca0.1Al1.67Mg0.33Si4O10(OH)2*4H2O"},
    "mat_vermiculite": {"formula": "Mg2.3Fe0.5Al1.2Si3O10(OH)2*4H2O"},
    "mat_tourmaline": {"endmembers": _em(("schorl", "NaFe3Al6(BO3)3Si6O18(OH)4", 0.7), ("dravite", "NaMg3Al6(BO3)3Si6O18(OH)4", 0.3))},
    "mat_zeolite": {"endmembers": _em(("clinoptilolite", "Na3K3Al6Si30O72*20H2O", 0.6), ("natrolite", "Na2Al2Si3O10*2H2O", 0.4))},
    "mat_chrysoprase": {"endmembers": _em(("chalcedony", "SiO2", 0.97), ("nickel oxide pigment", "NiO", 0.03))},
    "mat_banded_jasper": {"endmembers": _em(("chalcedony", "SiO2", 0.8), ("hematite", "Fe2O3", 0.2))},
    "mat_malachite_azurite_gossan": {"endmembers": _em(
        ("malachite", "Cu2CO3(OH)2", 0.5), ("azurite", "Cu3(CO3)2(OH)2", 0.2), ("goethite", "FeO(OH)", 0.3))},
    "mat_siliceous_sinter": {"formula": "SiO2*0.4H2O"},
}

# Rocks, sediments, regolith: (bulk composition wt %, modal mineralogy wt %, basis)
BULK = {
    # --- igneous ---
    "mat_granite": ({"SiO2": 71.3, "TiO2": 0.31, "Al2O3": 14.3, "FeO": 2.7, "MnO": 0.05, "MgO": 0.71, "CaO": 1.84, "Na2O": 3.68, "K2O": 4.07, "P2O5": 0.12, "H2O": 0.6},
                    {"mat_quartz": 30, "mat_alkali_feldspar": 33, "mat_plagioclase_feldspar": 27, "mat_biotite": 6, "mat_muscovite": 2, "mat_hornblende": 1, "mat_magnetite": 0.6, "mat_apatite": 0.3, "mat_zircon": 0.05}, "modal"),
    "mat_granodiorite": ({"SiO2": 66.1, "TiO2": 0.54, "Al2O3": 15.7, "FeO": 3.8, "MnO": 0.08, "MgO": 1.57, "CaO": 3.56, "Na2O": 3.84, "K2O": 3.07, "P2O5": 0.18, "H2O": 0.8},
                         {"mat_quartz": 25, "mat_alkali_feldspar": 15, "mat_plagioclase_feldspar": 42, "mat_biotite": 10, "mat_hornblende": 6, "mat_magnetite": 1.2, "mat_apatite": 0.4, "mat_zircon": 0.05}, "modal"),
    "mat_tonalite": ({"SiO2": 61.5, "TiO2": 0.73, "Al2O3": 16.5, "FeO": 5.3, "MnO": 0.1, "MgO": 2.8, "CaO": 5.4, "Na2O": 3.9, "K2O": 1.4, "P2O5": 0.2, "H2O": 1.1},
                     {"mat_quartz": 22, "mat_plagioclase_feldspar": 55, "mat_biotite": 10, "mat_hornblende": 10, "mat_magnetite": 1.5, "mat_apatite": 0.5}, "modal"),
    "mat_diorite": ({"SiO2": 57.5, "TiO2": 0.95, "Al2O3": 16.7, "FeO": 7.0, "MnO": 0.12, "MgO": 3.7, "CaO": 6.6, "Na2O": 3.5, "K2O": 1.8, "P2O5": 0.29, "H2O": 1.1},
                    {"mat_plagioclase_feldspar": 58, "mat_hornblende": 20, "mat_biotite": 7, "mat_augite": 8, "mat_quartz": 4, "mat_magnetite": 2, "mat_apatite": 0.6}, "modal"),
    "mat_gabbro": ({"SiO2": 50.1, "TiO2": 1.12, "Al2O3": 15.5, "FeO": 9.4, "MnO": 0.16, "MgO": 7.6, "CaO": 9.6, "Na2O": 2.4, "K2O": 0.9, "P2O5": 0.24, "H2O": 1.3},
                   {"mat_plagioclase_feldspar": 55, "mat_augite": 30, "mat_olivine": 8, "mat_hornblende": 2, "mat_magnetite": 2.5, "mat_ilmenite": 1.5, "mat_apatite": 0.5}, "modal"),
    "mat_syenite": ({"SiO2": 58.6, "TiO2": 0.84, "Al2O3": 16.6, "FeO": 6.1, "MnO": 0.13, "MgO": 1.9, "CaO": 3.5, "Na2O": 5.2, "K2O": 5.4, "P2O5": 0.29, "H2O": 1.0},
                    {"mat_alkali_feldspar": 65, "mat_plagioclase_feldspar": 12, "mat_hornblende": 10, "mat_biotite": 5, "mat_augite": 4, "mat_quartz": 2, "mat_magnetite": 1.5, "mat_apatite": 0.6}, "modal"),
    "mat_nepheline_syenite": ({"SiO2": 54.6, "TiO2": 0.6, "Al2O3": 20.9, "FeO": 4.4, "MnO": 0.15, "MgO": 0.8, "CaO": 2.3, "Na2O": 8.6, "K2O": 5.5, "P2O5": 0.17, "H2O": 1.3, "Cl": 0.1},
                              {"mat_alkali_feldspar": 55, "mat_nepheline": 25, "mat_sodalite": 3, "mat_augite": 8, "mat_biotite": 4, "mat_magnetite": 1.5, "mat_apatite": 0.4}, "modal"),
    "mat_monzonite": ({"SiO2": 62.6, "TiO2": 0.78, "Al2O3": 15.7, "FeO": 5.0, "MnO": 0.1, "MgO": 2.0, "CaO": 4.3, "Na2O": 3.7, "K2O": 3.9, "P2O5": 0.25, "H2O": 0.9},
                      {"mat_alkali_feldspar": 35, "mat_plagioclase_feldspar": 35, "mat_hornblende": 12, "mat_biotite": 8, "mat_quartz": 5, "mat_augite": 3, "mat_magnetite": 1.5, "mat_apatite": 0.5}, "modal"),
    "mat_anorthosite": ({"SiO2": 50.3, "TiO2": 0.6, "Al2O3": 25.9, "FeO": 2.9, "MnO": 0.05, "MgO": 2.1, "CaO": 12.5, "Na2O": 3.2, "K2O": 0.7, "P2O5": 0.09, "H2O": 0.9},
                        {"mat_plagioclase_feldspar": 45, "mat_anorthite": 45, "mat_augite": 5, "mat_olivine": 2, "mat_magnetite": 1.5, "mat_ilmenite": 1}, "modal"),
    "mat_peridotite": ({"SiO2": 44.5, "TiO2": 0.15, "Al2O3": 3.5, "FeO": 8.0, "MnO": 0.13, "MgO": 38.5, "CaO": 3.1, "Na2O": 0.3, "K2O": 0.03, "Cr2O3": 0.4, "NiO": 0.25, "H2O": 0.5},
                       {"mat_olivine": 62, "mat_enstatite": 20, "mat_augite": 12, "mat_spinel": 3, "mat_chromite": 0.5, "mat_serpentine": 2.5}, "modal"),
    "mat_dunite": ({"SiO2": 40.2, "Al2O3": 0.8, "FeO": 9.0, "MnO": 0.14, "MgO": 47.5, "CaO": 0.5, "Na2O": 0.1, "Cr2O3": 0.5, "NiO": 0.3, "H2O": 1.0},
                   {"mat_olivine": 92, "mat_chromite": 2, "mat_serpentine": 5, "mat_enstatite": 1}, "modal"),
    "mat_komatiite": ({"SiO2": 45.5, "TiO2": 0.3, "Al2O3": 6.5, "FeO": 11.0, "MnO": 0.18, "MgO": 28.0, "CaO": 6.5, "Na2O": 0.4, "K2O": 0.1, "Cr2O3": 0.35, "NiO": 0.2, "H2O": 1.0},
                      {"mat_olivine": 50, "mat_augite": 30, "mat_plagioclase_feldspar": 5, "mat_serpentine": 8, "mat_chlorite": 5, "mat_magnetite": 1.5, "mat_chromite": 0.5}, "modal"),
    "mat_kimberlite": ({"SiO2": 33.5, "TiO2": 1.8, "Al2O3": 3.0, "FeO": 9.0, "MnO": 0.17, "MgO": 29.0, "CaO": 8.8, "Na2O": 0.2, "K2O": 1.0, "P2O5": 0.8, "CO2": 5.0, "H2O": 7.0, "Cr2O3": 0.2, "NiO": 0.2},
                       {"mat_olivine": 45, "mat_serpentine": 25, "mat_calcite": 12, "mat_biotite": 8, "mat_ilmenite": 3, "mat_garnet": 3, "mat_apatite": 1.5, "mat_magnetite": 1.5, "mat_diamond": 0.0001}, "modal"),
    "mat_carbonatite": ({"SiO2": 4.0, "TiO2": 0.3, "Al2O3": 1.0, "FeO": 6.0, "MnO": 0.8, "MgO": 4.5, "CaO": 44.0, "Na2O": 0.3, "K2O": 0.3, "P2O5": 2.0, "CO2": 35.0, "SO3": 1.0, "BaO": 0.5, "SrO": 0.8, "F": 0.3},
                        {"mat_calcite": 75, "mat_dolomite": 8, "mat_apatite": 5, "mat_magnetite": 5, "mat_biotite": 3, "mat_monazite": 0.5, "mat_fluorite": 0.5, "mat_pyrite": 1}, "modal"),
    "mat_basalt": ({"SiO2": 49.2, "TiO2": 1.84, "Al2O3": 15.7, "FeO": 10.4, "MnO": 0.2, "MgO": 6.7, "CaO": 9.5, "Na2O": 2.9, "K2O": 1.1, "P2O5": 0.35, "H2O": 1.0},
                   {"mat_plagioclase_feldspar": 48, "mat_augite": 33, "mat_olivine": 8, "mat_magnetite": 4, "mat_ilmenite": 3, "mat_apatite": 0.8, "mat_hornblende": 2}, "modal"),
    "mat_diabase": ({"SiO2": 50.1, "TiO2": 1.4, "Al2O3": 15.0, "FeO": 10.8, "MnO": 0.18, "MgO": 7.3, "CaO": 9.8, "Na2O": 2.6, "K2O": 0.9, "P2O5": 0.2, "H2O": 1.2},
                    {"mat_plagioclase_feldspar": 50, "mat_augite": 38, "mat_olivine": 4, "mat_magnetite": 3.5, "mat_ilmenite": 2, "mat_apatite": 0.5, "mat_biotite": 1}, "modal"),
    "mat_andesite": ({"SiO2": 57.9, "TiO2": 0.87, "Al2O3": 17.0, "FeO": 7.3, "MnO": 0.14, "MgO": 3.3, "CaO": 6.8, "Na2O": 3.5, "K2O": 1.6, "P2O5": 0.21, "H2O": 1.2},
                     {"mat_plagioclase_feldspar": 55, "mat_augite": 15, "mat_hornblende": 15, "mat_biotite": 3, "mat_quartz": 5, "mat_magnetite": 3, "mat_ilmenite": 1, "mat_apatite": 0.5}, "modal"),
    "mat_dacite": ({"SiO2": 65.0, "TiO2": 0.58, "Al2O3": 15.9, "FeO": 4.6, "MnO": 0.1, "MgO": 1.8, "CaO": 4.3, "Na2O": 3.8, "K2O": 2.2, "P2O5": 0.15, "H2O": 1.2},
                   {"mat_plagioclase_feldspar": 45, "mat_quartz": 20, "mat_alkali_feldspar": 10, "mat_hornblende": 10, "mat_biotite": 10, "mat_magnetite": 2, "mat_apatite": 0.4}, "modal"),
    "mat_rhyolite": ({"SiO2": 72.8, "TiO2": 0.28, "Al2O3": 13.3, "FeO": 2.3, "MnO": 0.06, "MgO": 0.39, "CaO": 1.14, "Na2O": 3.55, "K2O": 4.3, "P2O5": 0.07, "H2O": 1.5},
                     {"mat_quartz": 33, "mat_alkali_feldspar": 38, "mat_plagioclase_feldspar": 22, "mat_biotite": 4, "mat_magnetite": 1, "mat_apatite": 0.2, "mat_hornblende": 1}, "normative"),
    "mat_latite": ({"SiO2": 61.3, "TiO2": 0.9, "Al2O3": 16.0, "FeO": 5.8, "MnO": 0.1, "MgO": 2.5, "CaO": 4.4, "Na2O": 3.6, "K2O": 3.9, "P2O5": 0.4, "H2O": 1.0},
                   {"mat_plagioclase_feldspar": 35, "mat_alkali_feldspar": 35, "mat_augite": 10, "mat_hornblende": 8, "mat_biotite": 7, "mat_magnetite": 2, "mat_apatite": 0.8, "mat_quartz": 2}, "modal"),
    "mat_trachyte": ({"SiO2": 61.2, "TiO2": 0.7, "Al2O3": 16.9, "FeO": 4.6, "MnO": 0.15, "MgO": 0.96, "CaO": 2.3, "Na2O": 5.5, "K2O": 5.0, "P2O5": 0.2, "H2O": 1.2},
                     {"mat_alkali_feldspar": 70, "mat_plagioclase_feldspar": 10, "mat_augite": 7, "mat_biotite": 5, "mat_hornblende": 4, "mat_magnetite": 2, "mat_apatite": 0.5}, "modal"),
    "mat_phonolite": ({"SiO2": 56.2, "TiO2": 0.6, "Al2O3": 19.0, "FeO": 4.3, "MnO": 0.15, "MgO": 1.1, "CaO": 2.7, "Na2O": 7.8, "K2O": 5.2, "P2O5": 0.17, "H2O": 2.0, "Cl": 0.2},
                      {"mat_alkali_feldspar": 55, "mat_nepheline": 25, "mat_sodalite": 5, "mat_augite": 8, "mat_magnetite": 2, "mat_apatite": 0.4, "mat_zeolite": 3}, "modal"),
    "mat_obsidian": ({"SiO2": 74.5, "TiO2": 0.2, "Al2O3": 13.3, "FeO": 1.6, "MnO": 0.05, "MgO": 0.2, "CaO": 0.9, "Na2O": 4.0, "K2O": 4.5, "P2O5": 0.03, "H2O": 0.3},
                     {"mat_quartz": 35, "mat_alkali_feldspar": 40, "mat_plagioclase_feldspar": 22, "mat_magnetite": 1, "mat_biotite": 1}, "normative"),
    "mat_pumice": ({"SiO2": 71.0, "TiO2": 0.3, "Al2O3": 13.5, "FeO": 2.2, "MnO": 0.06, "MgO": 0.4, "CaO": 1.5, "Na2O": 3.8, "K2O": 3.9, "P2O5": 0.05, "H2O": 3.0},
                   {"mat_quartz": 30, "mat_alkali_feldspar": 35, "mat_plagioclase_feldspar": 25, "mat_biotite": 3, "mat_magnetite": 1.2, "mat_zeolite": 4}, "normative"),
    "mat_scoria": ({"SiO2": 49.5, "TiO2": 1.7, "Al2O3": 16.0, "FeO": 10.5, "MnO": 0.18, "MgO": 6.5, "CaO": 9.8, "Na2O": 3.0, "K2O": 1.1, "P2O5": 0.4, "H2O": 0.5},
                   {"mat_plagioclase_feldspar": 45, "mat_augite": 33, "mat_olivine": 10, "mat_magnetite": 5, "mat_ilmenite": 3, "mat_apatite": 0.9}, "normative"),
    "mat_tuff": ({"SiO2": 66.0, "TiO2": 0.5, "Al2O3": 14.5, "FeO": 3.5, "MnO": 0.08, "MgO": 1.2, "CaO": 2.8, "Na2O": 3.2, "K2O": 3.3, "P2O5": 0.1, "H2O": 4.5},
                 {"mat_quartz": 22, "mat_alkali_feldspar": 30, "mat_plagioclase_feldspar": 25, "mat_biotite": 5, "mat_zeolite": 8, "mat_smectite": 6, "mat_magnetite": 1.5}, "normative"),
    "mat_ignimbrite": ({"SiO2": 69.0, "TiO2": 0.4, "Al2O3": 14.0, "FeO": 2.8, "MnO": 0.07, "MgO": 0.7, "CaO": 2.0, "Na2O": 3.6, "K2O": 4.0, "P2O5": 0.08, "H2O": 2.5},
                       {"mat_quartz": 28, "mat_alkali_feldspar": 35, "mat_plagioclase_feldspar": 25, "mat_biotite": 5, "mat_zeolite": 3, "mat_magnetite": 1.5, "mat_hornblende": 1.5}, "normative"),
    "mat_welded_ignimbrite": ({"SiO2": 71.0, "TiO2": 0.35, "Al2O3": 13.8, "FeO": 2.5, "MnO": 0.06, "MgO": 0.5, "CaO": 1.6, "Na2O": 3.7, "K2O": 4.3, "P2O5": 0.07, "H2O": 1.2},
                              {"mat_quartz": 30, "mat_alkali_feldspar": 38, "mat_plagioclase_feldspar": 25, "mat_biotite": 4, "mat_magnetite": 1.2}, "normative"),
    "mat_pegmatite": ({"SiO2": 73.5, "TiO2": 0.05, "Al2O3": 15.0, "FeO": 0.8, "MnO": 0.05, "MgO": 0.2, "CaO": 0.8, "Na2O": 3.5, "K2O": 5.2, "P2O5": 0.15, "Li2O": 0.1, "B2O3": 0.05, "F": 0.1, "H2O": 0.5},
                      {"mat_quartz": 30, "mat_alkali_feldspar": 40, "mat_albite": 20, "mat_muscovite": 7, "mat_tourmaline": 1, "mat_lepidolite": 0.8, "mat_spodumene": 0.6, "mat_beryl": 0.2, "mat_apatite": 0.3}, "modal"),
    # --- metamorphic ---
    "mat_gneiss": ({"SiO2": 68.0, "TiO2": 0.5, "Al2O3": 15.0, "FeO": 4.0, "MnO": 0.07, "MgO": 1.5, "CaO": 2.8, "Na2O": 3.4, "K2O": 3.4, "P2O5": 0.13, "H2O": 0.8},
                   {"mat_quartz": 28, "mat_alkali_feldspar": 22, "mat_plagioclase_feldspar": 32, "mat_biotite": 10, "mat_hornblende": 4, "mat_garnet": 2, "mat_magnetite": 1}, "modal"),
    "mat_schist": ({"SiO2": 60.0, "TiO2": 0.9, "Al2O3": 19.0, "FeO": 7.0, "MnO": 0.1, "MgO": 2.8, "CaO": 1.4, "Na2O": 1.6, "K2O": 3.7, "P2O5": 0.15, "H2O": 3.2},
                   {"mat_quartz": 35, "mat_muscovite": 25, "mat_biotite": 15, "mat_chlorite": 5, "mat_garnet": 8, "mat_plagioclase_feldspar": 8, "mat_staurolite": 2, "mat_graphite": 0.5, "mat_ilmenite": 1}, "modal"),
    "mat_phyllite": ({"SiO2": 60.5, "TiO2": 0.85, "Al2O3": 18.5, "FeO": 6.8, "MnO": 0.08, "MgO": 2.6, "CaO": 1.3, "Na2O": 1.5, "K2O": 3.6, "P2O5": 0.15, "H2O": 4.0},
                     {"mat_quartz": 35, "mat_muscovite": 30, "mat_chlorite": 18, "mat_albite": 10, "mat_graphite": 0.8, "mat_illite": 4, "mat_ilmenite": 1}, "modal"),
    "mat_slate": ({"SiO2": 60.0, "TiO2": 0.8, "Al2O3": 17.5, "FeO": 6.5, "MnO": 0.08, "MgO": 2.6, "CaO": 1.5, "Na2O": 1.4, "K2O": 3.6, "P2O5": 0.15, "H2O": 4.0, "C": 0.5},
                  {"mat_quartz": 32, "mat_illite": 25, "mat_muscovite": 15, "mat_chlorite": 15, "mat_albite": 8, "mat_graphite": 1.5, "mat_pyrite": 1, "mat_hematite": 1}, "modal"),
    "mat_amphibolite": ({"SiO2": 49.0, "TiO2": 1.5, "Al2O3": 15.0, "FeO": 11.0, "MnO": 0.2, "MgO": 7.5, "CaO": 10.5, "Na2O": 2.6, "K2O": 0.6, "P2O5": 0.2, "H2O": 1.5},
                        {"mat_hornblende": 60, "mat_plagioclase_feldspar": 30, "mat_garnet": 3, "mat_quartz": 3, "mat_epidote": 2, "mat_ilmenite": 1.5, "mat_magnetite": 1}, "modal"),
    "mat_greenschist": ({"SiO2": 48.5, "TiO2": 1.5, "Al2O3": 15.0, "FeO": 10.5, "MnO": 0.18, "MgO": 7.5, "CaO": 8.5, "Na2O": 3.0, "K2O": 0.4, "P2O5": 0.2, "H2O": 4.0, "CO2": 0.5},
                        {"mat_chlorite": 30, "mat_amphibole": 25, "mat_epidote": 20, "mat_albite": 18, "mat_quartz": 3, "mat_calcite": 2, "mat_magnetite": 1.5}, "modal"),
    "mat_blueschist": ({"SiO2": 49.0, "TiO2": 1.4, "Al2O3": 15.0, "FeO": 10.0, "MnO": 0.18, "MgO": 6.5, "CaO": 9.0, "Na2O": 4.0, "K2O": 0.4, "P2O5": 0.2, "H2O": 3.5},
                       {"mat_glaucophane": 45, "mat_epidote": 20, "mat_garnet": 10, "mat_chlorite": 10, "mat_albite": 5, "mat_quartz": 5, "mat_rutile": 1, "mat_calcite": 3}, "modal"),
    "mat_eclogite": ({"SiO2": 48.5, "TiO2": 1.5, "Al2O3": 15.5, "FeO": 10.5, "MnO": 0.18, "MgO": 8.0, "CaO": 11.0, "Na2O": 3.0, "K2O": 0.3, "P2O5": 0.2, "H2O": 0.3},
                     {"mat_garnet": 45, "mat_augite": 45, "mat_quartz": 3, "mat_rutile": 1.5, "mat_kyanite": 2, "mat_amphibole": 3}, "modal"),
    "mat_granulite": ({"SiO2": 60.0, "TiO2": 0.8, "Al2O3": 16.0, "FeO": 6.5, "MnO": 0.1, "MgO": 3.5, "CaO": 5.5, "Na2O": 3.3, "K2O": 2.0, "P2O5": 0.15, "H2O": 0.3},
                      {"mat_plagioclase_feldspar": 45, "mat_quartz": 20, "mat_enstatite": 12, "mat_augite": 8, "mat_garnet": 8, "mat_alkali_feldspar": 5, "mat_magnetite": 1.5}, "modal"),
    "mat_migmatite": ({"SiO2": 66.0, "TiO2": 0.6, "Al2O3": 15.5, "FeO": 4.6, "MnO": 0.08, "MgO": 1.8, "CaO": 2.9, "Na2O": 3.3, "K2O": 3.5, "P2O5": 0.14, "H2O": 0.8},
                      {"mat_quartz": 27, "mat_alkali_feldspar": 25, "mat_plagioclase_feldspar": 30, "mat_biotite": 13, "mat_hornblende": 2, "mat_garnet": 2, "mat_magnetite": 0.8}, "modal"),
    "mat_hornfels": ({"SiO2": 60.0, "TiO2": 0.9, "Al2O3": 18.5, "FeO": 7.0, "MnO": 0.1, "MgO": 3.0, "CaO": 2.0, "Na2O": 1.8, "K2O": 3.3, "P2O5": 0.15, "H2O": 1.5},
                     {"mat_quartz": 30, "mat_biotite": 22, "mat_plagioclase_feldspar": 20, "mat_andalusite": 8, "mat_alkali_feldspar": 10, "mat_garnet": 3, "mat_magnetite": 2, "mat_muscovite": 5}, "modal"),
    "mat_marble": ({"CaO": 53.5, "MgO": 1.5, "CO2": 42.5, "SiO2": 1.5, "Al2O3": 0.4, "FeO": 0.3, "MnO": 0.02},
                   {"mat_calcite": 90, "mat_dolomite": 6, "mat_quartz": 1.5, "mat_diopside": 1, "mat_graphite": 0.2, "mat_muscovite": 0.5}, "modal"),
    "mat_metabasalt": ({"SiO2": 48.8, "TiO2": 1.8, "Al2O3": 15.5, "FeO": 10.3, "MnO": 0.2, "MgO": 6.8, "CaO": 9.2, "Na2O": 2.9, "K2O": 0.8, "P2O5": 0.3, "H2O": 2.5},
                       {"mat_plagioclase_feldspar": 40, "mat_hornblende": 30, "mat_chlorite": 10, "mat_epidote": 10, "mat_augite": 5, "mat_magnetite": 3, "mat_ilmenite": 2}, "modal"),
    "mat_metaconglomerate": ({"SiO2": 78.0, "TiO2": 0.3, "Al2O3": 9.0, "FeO": 3.0, "MnO": 0.05, "MgO": 1.0, "CaO": 1.5, "Na2O": 1.5, "K2O": 2.5, "P2O5": 0.08, "H2O": 1.2},
                             {"mat_quartz": 65, "mat_alkali_feldspar": 10, "mat_muscovite": 10, "mat_plagioclase_feldspar": 8, "mat_chlorite": 4, "mat_biotite": 2, "mat_magnetite": 1}, "modal"),
    "mat_quartzite": ({"SiO2": 95.0, "TiO2": 0.1, "Al2O3": 2.0, "Fe2O3": 0.8, "MgO": 0.2, "CaO": 0.3, "Na2O": 0.2, "K2O": 0.7, "H2O": 0.4},
                      {"mat_quartz": 94, "mat_muscovite": 3, "mat_alkali_feldspar": 1.5, "mat_hematite": 0.8, "mat_zircon": 0.05}, "modal"),
    "mat_cataclasite": ({"SiO2": 66.0, "TiO2": 0.5, "Al2O3": 15.0, "FeO": 4.0, "MnO": 0.07, "MgO": 1.8, "CaO": 3.0, "Na2O": 3.0, "K2O": 3.2, "P2O5": 0.13, "H2O": 1.8, "CO2": 1.0},
                        {"mat_quartz": 28, "mat_alkali_feldspar": 20, "mat_plagioclase_feldspar": 28, "mat_chlorite": 10, "mat_illite": 6, "mat_epidote": 4, "mat_calcite": 2, "mat_magnetite": 1}, "modal"),
    "mat_mylonite": ({"SiO2": 68.0, "TiO2": 0.45, "Al2O3": 15.0, "FeO": 3.6, "MnO": 0.06, "MgO": 1.3, "CaO": 2.6, "Na2O": 3.3, "K2O": 3.7, "P2O5": 0.12, "H2O": 1.0},
                     {"mat_quartz": 30, "mat_alkali_feldspar": 22, "mat_plagioclase_feldspar": 28, "mat_muscovite": 8, "mat_biotite": 8, "mat_chlorite": 3, "mat_magnetite": 1}, "modal"),
    "mat_serpentinite": ({"SiO2": 40.0, "Al2O3": 1.5, "FeO": 7.5, "MnO": 0.1, "MgO": 37.5, "CaO": 0.5, "Cr2O3": 0.4, "NiO": 0.3, "H2O": 12.0},
                         {"mat_serpentine": 85, "mat_magnetite": 5, "mat_brucite": 3, "mat_chromite": 1, "mat_olivine": 4, "mat_talc": 2}, "modal"),
    "mat_soapstone": ({"SiO2": 50.0, "Al2O3": 1.5, "FeO": 5.0, "MgO": 30.0, "CaO": 1.5, "H2O": 5.0, "CO2": 6.0},
                      {"mat_talc": 70, "mat_dolomite": 10, "mat_chlorite": 12, "mat_magnetite": 3, "mat_serpentine": 5}, "modal"),
    "mat_skarn": ({"SiO2": 42.0, "TiO2": 0.4, "Al2O3": 10.0, "FeO": 10.0, "MnO": 0.5, "MgO": 4.0, "CaO": 28.0, "Na2O": 0.3, "K2O": 0.3, "CO2": 3.0, "H2O": 1.0},
                  {"mat_garnet": 32, "mat_diopside": 20, "mat_wollastonite": 18, "mat_calcite": 12, "mat_epidote": 8, "mat_magnetite": 6, "mat_quartz": 2, "mat_scheelite": 0.3}, "modal"),
    "mat_lapis_lazuli_marble": ({"CaO": 42.0, "MgO": 2.0, "CO2": 33.0, "SiO2": 10.0, "Al2O3": 7.0, "Na2O": 4.0, "SO3": 2.0, "Cl": 0.2, "FeO": 0.5, "K2O": 0.3},
                                {"mat_calcite": 75, "mat_sodalite": 12, "mat_diopside": 6, "mat_pyrite": 2, "mat_dolomite": 3, "mat_quartz": 1}, "modal"),
    "mat_anthracite": ({"C": 88.0, "H2O": 3.0, "SiO2": 4.0, "Al2O3": 2.0, "FeO": 1.0, "SO3": 1.5, "CaO": 0.5},
                       {"mat_graphite": 90, "mat_kaolinite": 5, "mat_pyrite": 2, "mat_quartz": 2, "mat_calcite": 1}, "normative"),
    # --- sedimentary ---
    "mat_lignite": ({"C": 45.0, "H2O": 30.0, "SiO2": 8.0, "Al2O3": 5.0, "FeO": 2.0, "CaO": 2.0, "SO3": 2.0, "MgO": 0.5},
                    {"mat_graphite": 45, "mat_kaolinite": 12, "mat_quartz": 8, "mat_pyrite": 3, "mat_gypsum": 4, "mat_calcite": 3}, "normative"),
    "mat_sandstone": ({"SiO2": 78.7, "TiO2": 0.25, "Al2O3": 4.8, "Fe2O3": 1.4, "MgO": 1.2, "CaO": 5.5, "Na2O": 0.45, "K2O": 1.3, "P2O5": 0.08, "CO2": 5.0, "H2O": 1.3},
                      {"mat_quartz": 75, "mat_alkali_feldspar": 7, "mat_plagioclase_feldspar": 3, "mat_calcite": 9, "mat_kaolinite": 3, "mat_illite": 2, "mat_hematite": 0.5, "mat_zircon": 0.03}, "modal"),
    "mat_arkose": ({"SiO2": 77.5, "TiO2": 0.3, "Al2O3": 10.5, "Fe2O3": 1.5, "MgO": 0.4, "CaO": 1.2, "Na2O": 2.0, "K2O": 3.8, "P2O5": 0.1, "H2O": 1.0},
                   {"mat_quartz": 58, "mat_alkali_feldspar": 28, "mat_plagioclase_feldspar": 8, "mat_kaolinite": 3, "mat_muscovite": 2, "mat_hematite": 1}, "modal"),
    "mat_greywacke": ({"SiO2": 66.7, "TiO2": 0.6, "Al2O3": 13.5, "FeO": 5.5, "MnO": 0.1, "MgO": 2.1, "CaO": 2.5, "Na2O": 2.9, "K2O": 2.0, "P2O5": 0.16, "H2O": 2.4, "CO2": 1.2},
                      {"mat_quartz": 45, "mat_plagioclase_feldspar": 20, "mat_alkali_feldspar": 5, "mat_chlorite": 12, "mat_illite": 10, "mat_calcite": 3, "mat_biotite": 3, "mat_pyrite": 0.5}, "modal"),
    "mat_red_bed_sandstone": ({"SiO2": 80.0, "TiO2": 0.3, "Al2O3": 7.0, "Fe2O3": 3.5, "MgO": 0.8, "CaO": 2.0, "Na2O": 0.8, "K2O": 2.0, "CO2": 1.5, "H2O": 1.2},
                              {"mat_quartz": 75, "mat_alkali_feldspar": 10, "mat_hematite": 3.5, "mat_calcite": 3, "mat_illite": 5, "mat_kaolinite": 3}, "modal"),
    "mat_calcareous_sandstone": ({"SiO2": 60.0, "Al2O3": 4.0, "Fe2O3": 1.2, "MgO": 1.0, "CaO": 17.0, "Na2O": 0.4, "K2O": 1.0, "CO2": 14.0, "H2O": 0.8},
                                 {"mat_quartz": 55, "mat_calcite": 32, "mat_alkali_feldspar": 5, "mat_illite": 4, "mat_dolomite": 2, "mat_hematite": 1}, "modal"),
    "mat_conglomerate": ({"SiO2": 73.0, "TiO2": 0.4, "Al2O3": 9.5, "FeO": 3.5, "MnO": 0.06, "MgO": 1.3, "CaO": 3.5, "Na2O": 1.6, "K2O": 2.4, "CO2": 2.5, "H2O": 1.5},
                         {"mat_quartz": 60, "mat_alkali_feldspar": 12, "mat_plagioclase_feldspar": 8, "mat_calcite": 6, "mat_illite": 6, "mat_chlorite": 5, "mat_hematite": 2}, "modal"),
    "mat_sedimentary_breccia": ({"SiO2": 68.0, "TiO2": 0.5, "Al2O3": 11.5, "FeO": 4.5, "MnO": 0.07, "MgO": 1.8, "CaO": 4.5, "Na2O": 2.0, "K2O": 2.5, "CO2": 3.0, "H2O": 1.8},
                                {"mat_quartz": 50, "mat_alkali_feldspar": 12, "mat_plagioclase_feldspar": 12, "mat_calcite": 8, "mat_chlorite": 8, "mat_illite": 6, "mat_hematite": 2}, "modal"),
    "mat_siltstone": ({"SiO2": 68.0, "TiO2": 0.7, "Al2O3": 12.5, "FeO": 4.5, "MgO": 1.8, "CaO": 2.5, "Na2O": 1.6, "K2O": 2.6, "P2O5": 0.14, "CO2": 1.8, "H2O": 3.0},
                      {"mat_quartz": 45, "mat_illite": 20, "mat_alkali_feldspar": 8, "mat_plagioclase_feldspar": 10, "mat_chlorite": 8, "mat_calcite": 4, "mat_kaolinite": 3, "mat_hematite": 1}, "modal"),
    "mat_shale": ({"SiO2": 62.8, "TiO2": 1.0, "Al2O3": 18.9, "FeO": 6.5, "MnO": 0.11, "MgO": 2.2, "CaO": 1.3, "Na2O": 1.2, "K2O": 3.7, "P2O5": 0.16, "H2O": 3.5, "C": 0.5},
                  {"mat_illite": 35, "mat_quartz": 30, "mat_kaolinite": 10, "mat_chlorite": 10, "mat_plagioclase_feldspar": 6, "mat_alkali_feldspar": 3, "mat_hematite": 2, "mat_pyrite": 1, "mat_calcite": 1, "mat_graphite": 0.5}, "modal"),
    "mat_mudstone": ({"SiO2": 60.0, "TiO2": 0.8, "Al2O3": 16.5, "FeO": 6.0, "MgO": 2.5, "CaO": 3.0, "Na2O": 1.2, "K2O": 3.3, "P2O5": 0.15, "CO2": 2.0, "H2O": 4.5},
                     {"mat_illite": 30, "mat_quartz": 30, "mat_kaolinite": 10, "mat_chlorite": 10, "mat_calcite": 5, "mat_plagioclase_feldspar": 6, "mat_alkali_feldspar": 4, "mat_hematite": 2, "mat_smectite": 3}, "modal"),
    "mat_claystone": ({"SiO2": 55.0, "TiO2": 0.9, "Al2O3": 22.0, "Fe2O3": 6.5, "MgO": 2.0, "CaO": 1.5, "Na2O": 0.8, "K2O": 3.0, "H2O": 8.0},
                      {"mat_kaolinite": 25, "mat_illite": 30, "mat_smectite": 10, "mat_quartz": 25, "mat_chlorite": 5, "mat_hematite": 5}, "modal"),
    "mat_oil_shale": ({"SiO2": 45.0, "Al2O3": 12.0, "FeO": 4.5, "MgO": 2.0, "CaO": 8.0, "Na2O": 1.0, "K2O": 2.5, "CO2": 6.0, "C": 14.0, "SO3": 1.5, "H2O": 3.5},
                      {"mat_illite": 25, "mat_quartz": 18, "mat_calcite": 15, "mat_dolomite": 5, "mat_graphite": 14, "mat_pyrite": 3, "mat_kaolinite": 8, "mat_alkali_feldspar": 5, "mat_plagioclase_feldspar": 4}, "normative"),
    "mat_limestone": ({"CaO": 52.0, "MgO": 1.5, "CO2": 42.0, "SiO2": 3.0, "Al2O3": 0.8, "Fe2O3": 0.5, "K2O": 0.2},
                      {"mat_calcite": 90, "mat_dolomite": 4, "mat_quartz": 3, "mat_kaolinite": 1.5, "mat_hematite": 0.5}, "modal"),
    "mat_oolitic_limestone": ({"CaO": 53.5, "MgO": 0.6, "CO2": 42.8, "SiO2": 1.5, "Al2O3": 0.3, "Fe2O3": 0.3},
                              {"mat_calcite": 96, "mat_quartz": 1.5, "mat_dolomite": 1.5, "mat_hematite": 0.3}, "modal"),
    "mat_chalk": ({"CaO": 54.0, "MgO": 0.4, "CO2": 43.0, "SiO2": 1.2, "Al2O3": 0.4, "Fe2O3": 0.2},
                  {"mat_calcite": 96, "mat_quartz": 1.5, "mat_kaolinite": 1, "mat_dolomite": 1}, "modal"),
    "mat_coquina": ({"CaO": 51.0, "MgO": 0.8, "CO2": 41.0, "SiO2": 4.0, "Al2O3": 0.8, "Fe2O3": 0.6, "P2O5": 0.3, "SrO": 0.2},
                    {"mat_calcite": 88, "mat_quartz": 4, "mat_dolomite": 3, "mat_apatite": 0.7, "mat_kaolinite": 1.5}, "modal"),
    "mat_travertine": ({"CaO": 55.0, "MgO": 0.4, "CO2": 43.5, "SiO2": 0.5, "Fe2O3": 0.2},
                       {"mat_calcite": 98, "mat_quartz": 0.5, "mat_hematite": 0.2}, "modal"),
    "mat_dolostone": ({"CaO": 30.4, "MgO": 21.7, "CO2": 47.0, "SiO2": 1.0, "Fe2O3": 0.3},
                      {"mat_dolomite": 94, "mat_calcite": 3, "mat_quartz": 1, "mat_hematite": 0.3}, "modal"),
    "mat_chert": ({"SiO2": 96.0, "Al2O3": 1.0, "Fe2O3": 0.8, "CaO": 0.5, "H2O": 1.2},
                  {"mat_quartz": 95, "mat_hematite": 0.8, "mat_kaolinite": 2, "mat_calcite": 1}, "modal"),
    "mat_diatomite": ({"SiO2": 86.0, "Al2O3": 3.5, "Fe2O3": 1.3, "CaO": 0.8, "MgO": 0.5, "H2O": 7.0},
                      {"mat_siliceous_sinter": 85, "mat_kaolinite": 7, "mat_quartz": 3, "mat_calcite": 2, "mat_hematite": 1.3}, "modal"),
    "mat_radiolarite": ({"SiO2": 90.0, "Al2O3": 3.0, "Fe2O3": 2.5, "MnO": 0.3, "MgO": 0.5, "CaO": 0.5, "K2O": 0.6, "H2O": 2.0},
                        {"mat_quartz": 88, "mat_siliceous_sinter": 3, "mat_hematite": 2.5, "mat_illite": 4, "mat_pyrolusite": 0.4}, "modal"),
    "mat_banded_iron_formation": ({"SiO2": 48.0, "Fe2O3": 45.0, "Al2O3": 0.8, "MgO": 1.5, "CaO": 2.0, "MnO": 0.3, "CO2": 1.5, "P2O5": 0.1},
                                  {"mat_quartz": 48, "mat_hematite": 30, "mat_magnetite": 15, "mat_dolomite": 3, "mat_chlorite": 2}, "modal"),
    "mat_ironstone": ({"Fe2O3": 44.0, "SiO2": 18.0, "Al2O3": 6.0, "CaO": 6.0, "MgO": 2.5, "MnO": 0.3, "P2O5": 1.2, "CO2": 8.0, "H2O": 8.0},
                      {"mat_goethite": 30, "mat_hematite": 18, "mat_chlorite": 12, "mat_quartz": 15, "mat_calcite": 12, "mat_apatite": 2.5, "mat_kaolinite": 6}, "modal"),
    "mat_phosphorite": ({"CaO": 45.0, "P2O5": 30.0, "F": 3.0, "CO2": 3.0, "SiO2": 8.0, "Al2O3": 2.0, "Fe2O3": 1.5, "MgO": 0.5, "SO3": 2.0, "Na2O": 0.5},
                        {"mat_apatite": 75, "mat_quartz": 8, "mat_calcite": 6, "mat_kaolinite": 4, "mat_dolomite": 2, "mat_gypsum": 3, "mat_hematite": 1}, "modal"),
    "mat_rock_salt": ({"NaCl": 95.0, "CaSO4": 3.0, "KCl": 0.5, "MgCl2": 0.3, "SiO2": 0.5, "Al2O3": 0.2, "H2O": 0.5},
                      {"mat_halite": 95, "mat_anhydrite": 3, "mat_sylvite": 0.5, "mat_quartz": 0.5, "mat_dolomite": 0.5}, "modal"),
    "mat_gypsum_rock": ({"CaSO4": 73.0, "H2O": 19.0, "CaCO3": 3.0, "SiO2": 2.5, "Al2O3": 1.0, "MgO": 0.5, "FeO": 0.3, "NaCl": 0.3},
                        {"mat_gypsum": 92, "mat_anhydrite": 1, "mat_calcite": 3, "mat_quartz": 2.5, "mat_dolomite": 0.5, "mat_halite": 0.3, "mat_kaolinite": 1}, "modal"),
    "mat_anhydrite_rock": ({"CaSO4": 93.0, "CaCO3": 2.0, "CaMg(CO3)2": 1.5, "SiO2": 1.5, "Al2O3": 0.5, "NaCl": 1.0, "H2O": 0.5},
                           {"mat_anhydrite": 93, "mat_dolomite": 1.5, "mat_calcite": 2, "mat_quartz": 1.5, "mat_halite": 1, "mat_gypsum": 1}, "modal"),
    # --- sediments ---
    "mat_alluvium": ({"SiO2": 68.0, "TiO2": 0.6, "Al2O3": 12.0, "FeO": 4.0, "MnO": 0.08, "MgO": 1.6, "CaO": 3.0, "Na2O": 1.8, "K2O": 2.3, "P2O5": 0.12, "H2O": 3.0, "CO2": 2.0, "C": 0.8},
                     {"mat_quartz": 50, "mat_alkali_feldspar": 10, "mat_plagioclase_feldspar": 10, "mat_illite": 8, "mat_kaolinite": 6, "mat_chlorite": 4, "mat_calcite": 4, "mat_hematite": 2, "mat_goethite": 1, "mat_biotite": 2, "mat_smectite": 2}, "modal"),
    "mat_beach_sand": ({"SiO2": 85.0, "Al2O3": 5.0, "FeO": 1.5, "TiO2": 0.3, "MgO": 0.5, "CaO": 3.0, "Na2O": 0.8, "K2O": 1.5, "CO2": 2.2, "H2O": 0.2},
                       {"mat_quartz": 82, "mat_alkali_feldspar": 6, "mat_plagioclase_feldspar": 3, "mat_calcite": 5, "mat_magnetite": 1, "mat_ilmenite": 0.5, "mat_zircon": 0.1, "mat_garnet": 0.5}, "modal"),
    "mat_clay": ({"SiO2": 50.0, "TiO2": 0.9, "Al2O3": 25.0, "Fe2O3": 6.0, "MgO": 1.8, "CaO": 1.0, "Na2O": 0.5, "K2O": 2.5, "H2O": 12.0},
                 {"mat_kaolinite": 40, "mat_illite": 25, "mat_smectite": 15, "mat_quartz": 10, "mat_chlorite": 5, "mat_goethite": 3}, "modal"),
    "mat_colluvium": ({"SiO2": 64.0, "TiO2": 0.7, "Al2O3": 14.0, "FeO": 5.0, "MnO": 0.1, "MgO": 2.0, "CaO": 2.8, "Na2O": 2.2, "K2O": 2.6, "P2O5": 0.13, "H2O": 3.5, "C": 1.0},
                      {"mat_quartz": 40, "mat_alkali_feldspar": 12, "mat_plagioclase_feldspar": 15, "mat_biotite": 5, "mat_illite": 8, "mat_kaolinite": 6, "mat_chlorite": 5, "mat_goethite": 3, "mat_hornblende": 2, "mat_calcite": 2}, "modal"),
    "mat_dune_sand": ({"SiO2": 90.0, "Al2O3": 4.0, "Fe2O3": 1.2, "TiO2": 0.2, "MgO": 0.3, "CaO": 1.5, "Na2O": 0.6, "K2O": 1.5, "CO2": 0.6},
                      {"mat_quartz": 88, "mat_alkali_feldspar": 6, "mat_plagioclase_feldspar": 2, "mat_calcite": 2.5, "mat_hematite": 0.8, "mat_magnetite": 0.4}, "modal"),
    "mat_evaporite_salt_crust": ({"NaCl": 60.0, "CaSO4": 20.0, "H2O": 5.0, "Na2SO4": 5.0, "MgCl2": 2.0, "KCl": 1.0, "CaCO3": 3.0, "SiO2": 3.0, "Al2O3": 1.0},
                                 {"mat_halite": 60, "mat_gypsum": 25, "mat_calcite": 3, "mat_quartz": 3, "mat_sylvite": 1, "mat_anhydrite": 3, "mat_kaolinite": 1}, "modal"),
    "mat_glacial_till": ({"SiO2": 64.0, "TiO2": 0.7, "Al2O3": 14.0, "FeO": 5.2, "MnO": 0.1, "MgO": 2.6, "CaO": 4.0, "Na2O": 2.6, "K2O": 2.5, "P2O5": 0.15, "CO2": 2.5, "H2O": 1.6},
                         {"mat_quartz": 35, "mat_plagioclase_feldspar": 18, "mat_alkali_feldspar": 14, "mat_calcite": 5, "mat_dolomite": 2, "mat_biotite": 4, "mat_hornblende": 5, "mat_chlorite": 6, "mat_illite": 7, "mat_magnetite": 1.5}, "modal"),
    "mat_gravel": ({"SiO2": 70.0, "TiO2": 0.5, "Al2O3": 11.0, "FeO": 4.0, "MnO": 0.07, "MgO": 1.8, "CaO": 4.0, "Na2O": 2.2, "K2O": 2.5, "P2O5": 0.1, "CO2": 2.5, "H2O": 1.3},
                   {"mat_quartz": 50, "mat_alkali_feldspar": 12, "mat_plagioclase_feldspar": 12, "mat_calcite": 7, "mat_chlorite": 6, "mat_illite": 5, "mat_hornblende": 3, "mat_hematite": 2}, "modal"),
    "mat_lacustrine_mud": ({"SiO2": 52.0, "TiO2": 0.7, "Al2O3": 14.0, "FeO": 5.5, "MnO": 0.12, "MgO": 2.2, "CaO": 6.0, "Na2O": 1.0, "K2O": 2.5, "P2O5": 0.2, "CO2": 5.0, "C": 3.0, "H2O": 7.0},
                           {"mat_illite": 25, "mat_quartz": 25, "mat_calcite": 15, "mat_kaolinite": 10, "mat_smectite": 8, "mat_chlorite": 6, "mat_graphite": 3, "mat_pyrite": 1, "mat_plagioclase_feldspar": 4}, "modal"),
    "mat_loess": ({"SiO2": 72.0, "TiO2": 0.6, "Al2O3": 10.5, "FeO": 3.2, "MnO": 0.07, "MgO": 1.4, "CaO": 4.5, "Na2O": 1.6, "K2O": 2.1, "P2O5": 0.12, "CO2": 3.0, "H2O": 1.2},
                  {"mat_quartz": 60, "mat_alkali_feldspar": 8, "mat_plagioclase_feldspar": 10, "mat_calcite": 10, "mat_dolomite": 2, "mat_illite": 6, "mat_chlorite": 2, "mat_hematite": 1}, "modal"),
    "mat_marine_mud": ({"SiO2": 55.0, "TiO2": 0.8, "Al2O3": 16.0, "FeO": 6.5, "MnO": 0.3, "MgO": 2.8, "CaO": 3.5, "Na2O": 2.5, "K2O": 3.0, "P2O5": 0.2, "CO2": 2.5, "C": 1.0, "NaCl": 1.5, "H2O": 5.5},
                       {"mat_illite": 30, "mat_quartz": 22, "mat_smectite": 12, "mat_chlorite": 10, "mat_calcite": 8, "mat_kaolinite": 6, "mat_plagioclase_feldspar": 5, "mat_halite": 1.5, "mat_pyrite": 1, "mat_graphite": 1}, "modal"),
    "mat_marl": ({"CaO": 28.0, "CO2": 22.0, "SiO2": 26.0, "Al2O3": 8.0, "Fe2O3": 3.0, "MgO": 2.0, "K2O": 1.6, "Na2O": 0.5, "H2O": 7.0},
                 {"mat_calcite": 50, "mat_illite": 20, "mat_quartz": 15, "mat_kaolinite": 6, "mat_dolomite": 3, "mat_chlorite": 4, "mat_hematite": 1}, "modal"),
    "mat_silica_sand": ({"SiO2": 97.5, "Al2O3": 1.0, "Fe2O3": 0.3, "TiO2": 0.1, "CaO": 0.3, "K2O": 0.3, "Na2O": 0.1, "H2O": 0.3},
                        {"mat_quartz": 97, "mat_alkali_feldspar": 1, "mat_kaolinite": 1, "mat_zircon": 0.05, "mat_ilmenite": 0.2}, "modal"),
    "mat_silt": ({"SiO2": 70.0, "TiO2": 0.8, "Al2O3": 11.5, "FeO": 3.8, "MgO": 1.5, "CaO": 3.0, "Na2O": 1.8, "K2O": 2.4, "P2O5": 0.12, "CO2": 2.0, "H2O": 3.0},
                 {"mat_quartz": 55, "mat_illite": 12, "mat_alkali_feldspar": 9, "mat_plagioclase_feldspar": 10, "mat_calcite": 5, "mat_chlorite": 5, "mat_kaolinite": 3, "mat_hematite": 1}, "modal"),
    "mat_talus": ({"SiO2": 66.6, "TiO2": 0.64, "Al2O3": 15.4, "FeO": 5.04, "MnO": 0.1, "MgO": 2.48, "CaO": 3.59, "Na2O": 3.27, "K2O": 2.8, "P2O5": 0.15},
                  {"mat_quartz": 27, "mat_alkali_feldspar": 18, "mat_plagioclase_feldspar": 35, "mat_biotite": 8, "mat_hornblende": 7, "mat_magnetite": 2, "mat_chlorite": 2}, "modal"),
    "mat_tephra": ({"SiO2": 62.0, "TiO2": 0.7, "Al2O3": 16.0, "FeO": 5.5, "MnO": 0.1, "MgO": 2.3, "CaO": 5.0, "Na2O": 3.8, "K2O": 2.2, "P2O5": 0.2, "H2O": 2.0},
                   {"mat_plagioclase_feldspar": 40, "mat_quartz": 12, "mat_alkali_feldspar": 12, "mat_hornblende": 10, "mat_augite": 8, "mat_biotite": 5, "mat_magnetite": 3, "mat_zeolite": 5}, "normative"),
    # --- regolith ---
    "mat_bauxite": ({"Al2O3": 55.0, "Fe2O3": 15.0, "SiO2": 4.0, "TiO2": 2.5, "H2O": 25.0},
                    {"mat_gibbsite": 55, "mat_boehmite": 10, "mat_goethite": 12, "mat_hematite": 6, "mat_kaolinite": 10, "mat_anatase": 2.5}, "modal"),
    "mat_calcrete": ({"CaO": 39.2, "CO2": 30.8, "SiO2": 20.0, "Al2O3": 3.5, "Fe2O3": 1.5, "MgO": 2.0, "K2O": 0.5, "H2O": 2.0},
                     {"mat_calcite": 68, "mat_quartz": 18, "mat_dolomite": 3, "mat_illite": 4, "mat_smectite": 3, "mat_hematite": 1}, "modal"),
    "mat_clay_rich_regolith": ({"SiO2": 50.0, "TiO2": 1.0, "Al2O3": 23.0, "Fe2O3": 8.0, "MgO": 1.5, "CaO": 1.0, "Na2O": 0.6, "K2O": 2.0, "H2O": 12.0, "C": 1.0},
                               {"mat_kaolinite": 40, "mat_illite": 18, "mat_smectite": 12, "mat_quartz": 15, "mat_goethite": 8, "mat_hematite": 3, "mat_graphite": 1}, "modal"),
    "mat_evaporite_crust": ({"NaCl": 45.0, "CaSO4": 25.0, "Na2SO4": 10.0, "MgSO4": 5.0, "H2O": 6.0, "CaCO3": 4.0, "SiO2": 4.0, "Al2O3": 1.0},
                            {"mat_halite": 45, "mat_gypsum": 32, "mat_anhydrite": 5, "mat_calcite": 4, "mat_quartz": 4, "mat_sylvite": 1, "mat_kaolinite": 1}, "modal"),
    "mat_ferricrete": ({"Fe2O3": 50.0, "SiO2": 20.0, "Al2O3": 14.0, "TiO2": 1.2, "H2O": 9.0, "MnO": 0.3, "CaO": 0.5, "MgO": 0.4, "K2O": 0.3, "P2O5": 0.2},
                       {"mat_goethite": 35, "mat_hematite": 20, "mat_kaolinite": 20, "mat_quartz": 18, "mat_gibbsite": 3, "mat_anatase": 1.2}, "modal"),
    "mat_impact_breccia": ({"SiO2": 62.0, "TiO2": 0.8, "Al2O3": 15.0, "FeO": 6.0, "MnO": 0.1, "MgO": 3.5, "CaO": 4.5, "Na2O": 3.0, "K2O": 2.5, "P2O5": 0.15, "H2O": 1.0},
                           {"mat_quartz": 25, "mat_plagioclase_feldspar": 32, "mat_alkali_feldspar": 15, "mat_augite": 8, "mat_biotite": 5, "mat_hornblende": 5, "mat_magnetite": 2}, "normative"),
    "mat_laterite": ({"Fe2O3": 33.0, "Al2O3": 28.0, "SiO2": 14.0, "TiO2": 2.0, "H2O": 17.0, "MnO": 0.3, "MgO": 0.3, "CaO": 0.2, "K2O": 0.2},
                     {"mat_goethite": 25, "mat_hematite": 12, "mat_gibbsite": 25, "mat_kaolinite": 25, "mat_quartz": 8, "mat_anatase": 2}, "modal"),
    "mat_limonite": ({"Fe2O3": 76.0, "H2O": 15.0, "SiO2": 6.0, "Al2O3": 3.0, "MnO": 0.5, "P2O5": 0.3},
                     {"mat_goethite": 85, "mat_quartz": 6, "mat_kaolinite": 5, "mat_pyrolusite": 0.5, "mat_apatite": 0.5}, "modal"),
    "mat_nickel_laterite": ({"Fe2O3": 45.0, "SiO2": 12.0, "MgO": 8.0, "Al2O3": 5.0, "NiO": 1.8, "Cr2O3": 1.5, "CoO": 0.1, "MnO": 0.8, "H2O": 14.0},
                            {"mat_goethite": 40, "mat_serpentine": 22, "mat_hematite": 8, "mat_chrysoprase": 5, "mat_chromite": 2, "mat_kaolinite": 5, "mat_quartz": 3}, "modal"),
    "mat_rock_varnish": ({"MnO2": 20.0, "Fe2O3": 12.0, "SiO2": 30.0, "Al2O3": 18.0, "CaO": 2.0, "MgO": 1.5, "K2O": 1.5, "Na2O": 0.5, "BaO": 0.4, "H2O": 12.0},
                         {"mat_pyrolusite": 20, "mat_hematite": 12, "mat_kaolinite": 25, "mat_illite": 25, "mat_quartz": 10, "mat_calcite": 3}, "modal"),
    "mat_saprolite": ({"SiO2": 55.0, "TiO2": 0.8, "Al2O3": 22.0, "Fe2O3": 7.0, "MgO": 1.0, "CaO": 0.5, "Na2O": 0.6, "K2O": 2.5, "H2O": 10.0},
                      {"mat_kaolinite": 45, "mat_quartz": 25, "mat_illite": 12, "mat_goethite": 7, "mat_alkali_feldspar": 5, "mat_smectite": 4}, "modal"),
    "mat_solfataric_sulfur_crust": ({"S": 85.0, "SiO2": 8.0, "CaSO4": 3.0, "Al2O3": 1.5, "Fe2O3": 1.0, "H2O": 1.5},
                                    {"mat_native_sulfur": 85, "mat_siliceous_sinter": 8, "mat_gypsum": 3, "mat_kaolinite": 3, "mat_hematite": 1}, "modal"),
}

# Rocks made of (fossil) life. Only a planet with a biosphere history -- Earth
# -- has them; world generation never places them on other worlds.
# Limestone, dolostone, marble, marl, chert and oolitic limestone stay
# abiotic: carbonate and silica also precipitate without life (Mars
# carbonates, Precambrian chert).
BIOGENIC_MATERIALS = {
    "mat_lignite": "coalified plant matter",
    "mat_anthracite": "metamorphosed coal",
    "mat_oil_shale": "kerogen from algal and microbial organic matter",
    "mat_chalk": "coccolith plates",
    "mat_coquina": "cemented shell fragments",
    "mat_diatomite": "diatom frustules",
    "mat_radiolarite": "radiolarian tests",
    "mat_phosphorite": "biogenic phosphate (skeletal debris, pellets, upwelling productivity)",
}

SCHEMA_FIELDS = {
    "biogenic_origin": {
        "type": "boolean", "section": "Chemistry", "optional": True,
        "description": "Made of (fossil) life: needs a biosphere history. World generation keeps it off every planet except Earth.",
    },
    "biogenic_source": {
        "type": "string", "section": "Chemistry", "optional": True,
        "description": "What living material the rock is made of (coccoliths, shells, plant matter, ...).",
    },
    "earth_upper_crust_abundance_ppm": {
        "type": "number", "section": "Chemistry", "optional": True,
        "description": "Element entities: reference crustal abundance (ppm by mass). The yardstick for a planet's enrichment and the shape of the background for elements a planet does not list.",
    },
    "computational_formula": {
        "type": "string", "section": "Chemistry", "optional": True,
        "description": "Parseable formula used for chemistry when the display formula is prose or a site placeholder.",
    },
    "composition_endmembers": {
        "type": "object_list", "section": "Chemistry", "optional": True,
        "description": "Solid-solution end-members: [{name, formula, mass_fraction}].",
    },
    "elemental_composition_wt": {
        "type": "dict", "section": "Chemistry", "optional": True,
        "description": "Element -> mass percent (derived from formula, end-members or bulk composition).",
    },
    "bulk_composition_wt": {
        "type": "dict", "section": "Chemistry", "optional": True,
        "description": "Rocks, sediments, regolith: component formula (oxide, salt, native element, C for organic carbon) -> mass percent.",
    },
    "modal_mineralogy_wt": {
        "type": "dict", "section": "Chemistry", "optional": True,
        "description": "Mineral material id -> approximate mass percent of the typical rock.",
    },
    "modal_basis": {
        "type": "string", "section": "Chemistry", "optional": True,
        "description": "'modal' (observed minerals) or 'normative' (glassy or organic rocks, expressed as equivalent minerals).",
    },
    "chemistry_status": {
        "type": "string", "section": "Chemistry", "optional": True,
        "description": "How the composition was obtained: formula, computational_formula, endmembers or bulk.",
    },
}

THRESHOLD_AVAILABILITY = 0.15


def _significant(value, digits=3):
    if value <= 0.0:
        return 0.0
    return round(value, max(0, digits - 1 - int(math.floor(math.log10(abs(value))))))


def derived_thresholds(composition, earth_elements):
    """Crust abundance at which the material falls to 15 % of its Earth availability, per element it needs.

    Mirrors ``material_chemistry.material_availability``: defining minor
    elements follow Liebig's law; essential elements the enrichment penalty.
    """
    thresholds = {}
    defining = chem._defining_minor_elements(composition, earth_elements)
    for element in defining:
        earth = float(earth_elements.get(element, 0.0) or 0.0)
        if earth > 0.0:
            thresholds[element] = _significant(THRESHOLD_AVAILABILITY * earth)
    factor = THRESHOLD_AVAILABILITY ** (1.0 / chem.ENRICHMENT_PENALTY_EXPONENT)
    for element, share in composition.items():
        if element in {"O", "H"} or element in defining or share < chem.ESSENTIAL_ELEMENT_PERCENT:
            continue
        earth = float(earth_elements.get(element, 0.0) or 0.0)
        if earth <= 0.0:
            continue
        limit = chem.DIFFERENTIATION_LIMIT.get(element, chem.DEFAULT_DIFFERENTIATION_LIMIT)
        ratio = share / earth
        value = min(earth, share * factor / limit) if ratio <= limit else earth * factor
        thresholds[element] = _significant(value)
    return dict(sorted(thresholds.items()))


def material_chemistry(entity):
    """Return (fields, composition) for a material entity, or (None, None) if not computable."""
    material_id = str(entity.get("id") or "")
    subclass = str(entity.get("material_subclass") or "")
    fields = {}
    if material_id in BULK:
        bulk, modal, basis = BULK[material_id]
        composition = chem.bulk_composition(bulk)
        fields.update({
            "bulk_composition_wt": dict(bulk),
            "modal_mineralogy_wt": dict(modal),
            "modal_basis": basis,
            "chemistry_status": "bulk",
        })
    elif material_id in MINERAL_CHEMISTRY:
        spec = MINERAL_CHEMISTRY[material_id]
        if "endmembers" in spec:
            composition = chem.endmember_composition(spec["endmembers"])
            fields.update({"composition_endmembers": copy.deepcopy(spec["endmembers"]), "chemistry_status": "endmembers"})
        else:
            composition = chem.formula_composition(spec["formula"])
            fields.update({"computational_formula": spec["formula"], "chemistry_status": "computational_formula"})
    elif subclass in {"mineral", "ice"}:
        try:
            composition = chem.formula_composition(entity.get("chemical_formula"))
        except chem.FormulaError:
            return None, None
        fields["chemistry_status"] = "formula"
    else:
        return None, None
    fields["elemental_composition_wt"] = chem.rounded_composition(composition)
    return fields, composition


def reference_percent():
    return {symbol: ppm / 1e4 for symbol, ppm in ELEMENT_REFERENCE_PPM.items()}


def earth_distribution():
    return chem.planet_element_distribution(default_crust_composition(), reference_percent())


def modal_check(materials_by_id, composition, modal):
    """Largest deviation (wt %, O and H excluded, both normalised) between bulk and modal chemistry."""
    parts = []
    for mineral_id, share in modal.items():
        mineral = materials_by_id.get(mineral_id)
        mineral_composition = (mineral or {}).get("elemental_composition_wt")
        if not mineral_composition:
            return None, f"modal mineral without composition: {mineral_id}"
        parts.append((mineral_composition, share))
    modal_composition = chem.mix_compositions(parts)

    def cations(values):
        kept = {element: value for element, value in values.items() if element not in {"O", "H"}}
        total = sum(kept.values()) or 1.0
        return {element: 100.0 * value / total for element, value in kept.items()}

    bulk_c = cations(composition)
    modal_c = cations(modal_composition)
    worst = max(
        ((abs(bulk_c.get(element, 0.0) - modal_c.get(element, 0.0)), element) for element in set(bulk_c) | set(modal_c)),
        default=(0.0, None),
    )
    return worst, None


def author(export=False, report=True):
    store = PersistentOntologyStore(ONTOLOGY_PATH)
    datasets = store.load_datasets()
    materials = {str(entity.get("id") or ""): entity for entity in datasets.get("materials") or [] if isinstance(entity, dict)}
    missing = sorted(material_id for material_id in [*BULK, *MINERAL_CHEMISTRY, *BIOGENIC_MATERIALS] if material_id not in materials)
    if missing:
        raise KeyError(f"Chemistry targets missing from the ontology: {', '.join(missing)}")
    earth = earth_distribution()
    replacements = {}
    for material_id, entity in materials.items():
        subclass = str(entity.get("material_subclass") or "")
        if subclass == "element":
            symbol = str(entity.get("element_symbol") or "")
            if symbol in ELEMENT_REFERENCE_PPM:
                replacement = replacements.setdefault(material_id, dict(entity))
                replacement["earth_upper_crust_abundance_ppm"] = ELEMENT_REFERENCE_PPM[symbol]
            continue
        if subclass not in {"mineral", "ice", "rock", "sediment", "regolith"} or entity.get("worldgen_participation") == "none":
            continue
        if material_id in BIOGENIC_MATERIALS:
            replacement = replacements.setdefault(material_id, dict(entity))
            replacement["biogenic_origin"] = True
            replacement["biogenic_source"] = BIOGENIC_MATERIALS[material_id]
        fields, composition = material_chemistry(entity)
        if fields is None:
            continue
        replacement = replacements.setdefault(material_id, dict(entity))
        replacement.update(fields)
        thresholds = derived_thresholds(composition, earth)
        if thresholds:
            replacement["required_element_thresholds"] = thresholds
    # Consistency of the authored modal mineralogies with the bulk chemistry.
    merged = {**materials, **replacements}
    deviations = []
    for material_id, (bulk, modal, _basis) in BULK.items():
        worst, problem = modal_check(merged, chem.bulk_composition(bulk), modal)
        if problem:
            raise KeyError(f"{material_id}: {problem}")
        deviations.append((worst[0], worst[1], material_id))
    # Schema fields.
    schema = next((entity for entity in datasets.get("schemas") or [] if str(entity.get("id")) == "schema_materials"), None)
    if schema is None:
        raise RuntimeError("schema_materials is missing from the ontology")
    schema = dict(schema)
    schema["fields"] = {**dict(schema.get("fields") or {}), **copy.deepcopy(SCHEMA_FIELDS)}
    records = [replacements[material_id] for material_id in sorted(replacements)] + [schema]
    if not store.persist_entities(records):
        raise RuntimeError("Could not persist material chemistry")
    if export:
        store.export_rdfxml(ONTOLOGY_PATH)
    if report:
        deviations.sort(reverse=True)
        print("largest bulk-vs-modal deviations (cation wt %):")
        for value, element, material_id in deviations[:12]:
            print(f"  {material_id:32s} {element:3s} {value:5.1f}")
    return records, deviations


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true", help="Also rewrite the ontology .owl checkpoint.")
    parser.add_argument("--dry-run", action="store_true", help="Compute and check without writing.")
    arguments = parser.parse_args()
    if arguments.dry_run:
        PersistentOntologyStore.persist_entities = lambda self, records: True  # noqa: E731
    changed, _deviations = author(export=arguments.export and not arguments.dry_run)
    print(f"{'Checked' if arguments.dry_run else 'Authored'} chemistry on {len(changed) - 1} ontology materials.")
