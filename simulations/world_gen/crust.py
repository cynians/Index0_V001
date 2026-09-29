TRACE_RESERVE_PERCENT = 1.0
MAJOR_CRUST_TARGET_PERCENT = 100.0 - TRACE_RESERVE_PERCENT


CRUST_ELEMENT_DENSITY_PROXY_KG_M3 = {
    "H": 90.0,
    "He": 170.0,
    "O": 2650.0,
    "Si": 2650.0,
    "Al": 2700.0,
    "Fe": 5200.0,
    "Ca": 2900.0,
    "Na": 2400.0,
    "K": 2300.0,
    "Mg": 3300.0,
    "Ti": 4500.0,
    "Mn": 4800.0,
    "P": 1820.0,
    "S": 2000.0,
    "C": 2200.0,
    "Ni": 8900.0,
    "Co": 8900.0,
    "Cr": 7200.0,
    "Cu": 8960.0,
    "Zn": 7140.0,
    "Ag": 10490.0,
    "Au": 19300.0,
    "Pt": 21450.0,
    "Os": 22590.0,
    "U": 19050.0,
    "Th": 11700.0,
}

DEFAULT_CRUST_DENSITY_KG_M3 = 2850.0


EARTH_CRUST_MAJOR_ELEMENTS = [
    {"symbol": "O", "name": "Oxygen", "abundance_percent": 46.86},
    {"symbol": "Si", "name": "Silicon", "abundance_percent": 27.84},
    {"symbol": "Al", "name": "Aluminium", "abundance_percent": 8.14},
    {"symbol": "Fe", "name": "Iron", "abundance_percent": 5.03},
    {"symbol": "Ca", "name": "Calcium", "abundance_percent": 3.62},
    {"symbol": "Na", "name": "Sodium", "abundance_percent": 2.81},
    {"symbol": "K", "name": "Potassium", "abundance_percent": 2.61},
    {"symbol": "Mg", "name": "Magnesium", "abundance_percent": 2.11},
]


TRACE_ELEMENT_RARITY = {
    "Ti": "common",
    "Mn": "common",
    "P": "common",
    "S": "common",
    "C": "common",
    "Ni": "common",
    "Cr": "common",
    "Cu": "uncommon",
    "Zn": "uncommon",
    "Mo": "uncommon",
    "Sn": "uncommon",
    "Pb": "uncommon",
    "Ag": "rare",
    "W": "rare",
    "Re": "very_rare",
    "Ir": "very_rare",
    "Os": "very_rare",
    "Pt": "very_rare",
    "Au": "very_rare",
    "Th": "very_rare",
    "U": "very_rare",
    "Tc": "synthetic_or_transient",
    "Pm": "synthetic_or_transient",
    "Po": "synthetic_or_transient",
    "At": "synthetic_or_transient",
    "Fr": "synthetic_or_transient",
    "Ra": "very_rare",
    "Ac": "very_rare",
    "Pa": "very_rare",
}


TRACE_RARITY_WEIGHTS = {
    "common": 1.0,
    "uncommon": 0.42,
    "rare": 0.12,
    "very_rare": 0.025,
    "synthetic_or_transient": 0.001,
}


TRACE_PROMOTION_ABUNDANCE_BY_RARITY = {
    "common": 0.85,
    "uncommon": 0.45,
    "rare": 0.18,
    "very_rare": 0.05,
    "synthetic_or_transient": 0.01,
}


ELEMENT_NAMES = {
    "H": "Hydrogen", "He": "Helium",
    "Li": "Lithium", "Be": "Beryllium", "B": "Boron", "C": "Carbon", "N": "Nitrogen", "O": "Oxygen",
    "F": "Fluorine", "Ne": "Neon",
    "Na": "Sodium", "Mg": "Magnesium", "Al": "Aluminium", "Si": "Silicon", "P": "Phosphorus",
    "S": "Sulfur", "Cl": "Chlorine", "Ar": "Argon",
    "K": "Potassium", "Ca": "Calcium", "Sc": "Scandium", "Ti": "Titanium", "V": "Vanadium",
    "Cr": "Chromium", "Mn": "Manganese", "Fe": "Iron", "Co": "Cobalt", "Ni": "Nickel",
    "Cu": "Copper", "Zn": "Zinc", "Ga": "Gallium", "Ge": "Germanium", "As": "Arsenic",
    "Se": "Selenium", "Br": "Bromine", "Kr": "Krypton",
    "Rb": "Rubidium", "Sr": "Strontium", "Y": "Yttrium", "Zr": "Zirconium", "Nb": "Niobium",
    "Mo": "Molybdenum", "Tc": "Technetium", "Ru": "Ruthenium", "Rh": "Rhodium", "Pd": "Palladium",
    "Ag": "Silver", "Cd": "Cadmium", "In": "Indium", "Sn": "Tin", "Sb": "Antimony",
    "Te": "Tellurium", "I": "Iodine", "Xe": "Xenon",
    "Cs": "Caesium", "Ba": "Barium", "La": "Lanthanum", "Ce": "Cerium", "Pr": "Praseodymium",
    "Nd": "Neodymium", "Pm": "Promethium", "Sm": "Samarium", "Eu": "Europium", "Gd": "Gadolinium",
    "Tb": "Terbium", "Dy": "Dysprosium", "Ho": "Holmium", "Er": "Erbium", "Tm": "Thulium",
    "Yb": "Ytterbium", "Lu": "Lutetium",
    "Hf": "Hafnium", "Ta": "Tantalum", "W": "Tungsten", "Re": "Rhenium", "Os": "Osmium",
    "Ir": "Iridium", "Pt": "Platinum", "Au": "Gold", "Hg": "Mercury", "Tl": "Thallium",
    "Pb": "Lead", "Bi": "Bismuth", "Po": "Polonium", "At": "Astatine", "Rn": "Radon",
    "Fr": "Francium", "Ra": "Radium", "Ac": "Actinium", "Th": "Thorium", "Pa": "Protactinium",
    "U": "Uranium",
}


PERIODIC_TABLE_ROWS = [
    ["H", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "He"],
    ["Li", "Be", "", "", "", "", "", "", "", "", "", "", "B", "C", "N", "O", "F", "Ne"],
    ["Na", "Mg", "", "", "", "", "", "", "", "", "", "", "Al", "Si", "P", "S", "Cl", "Ar"],
    ["K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Kr"],
    ["Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn", "Sb", "Te", "I", "Xe"],
    ["Cs", "Ba", "La", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg", "Tl", "Pb", "Bi", "Po", "At", "Rn"],
    ["Fr", "Ra", "Ac", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
    ["", "", "", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", ""],
    ["", "", "", "Th", "Pa", "U", "", "", "", "", "", "", "", "", "", "", "", ""],
]

from simulations.world_gen.material_catalog import (
    ELEMENT_NAMES,
    TRACE_ELEMENT_RARITY,
    TRACE_PROMOTION_ABUNDANCE_BY_RARITY,
    TRACE_RARITY_WEIGHTS,
)


def element_name(symbol):
    return ELEMENT_NAMES.get(symbol, symbol)


def trace_element_rarity(symbol):
    return TRACE_ELEMENT_RARITY.get(str(symbol or "").strip(), "uncommon")


def trace_element_weight(symbol):
    return TRACE_RARITY_WEIGHTS.get(trace_element_rarity(symbol), 0.25)


def trace_promotion_abundance(symbol):
    return TRACE_PROMOTION_ABUNDANCE_BY_RARITY.get(trace_element_rarity(symbol), 0.25)


def normalize_major_elements(elements):
    clean = []
    for element in elements or []:
        symbol = str(element.get("symbol") or "").strip()
        if not symbol:
            continue
        try:
            abundance = max(0.0, float(element.get("abundance_percent", 0.0)))
        except (TypeError, ValueError):
            abundance = 0.0
        row = {
            "symbol": symbol,
            "name": str(element.get("name") or element_name(symbol)),
            "abundance_percent": abundance,
        }
        if element.get("rarity"):
            row["rarity"] = element.get("rarity")
        clean.append(row)

    if not clean:
        clean = [dict(element) for element in EARTH_CRUST_MAJOR_ELEMENTS]

    total = sum(element["abundance_percent"] for element in clean)
    if total <= 0:
        even = MAJOR_CRUST_TARGET_PERCENT / len(clean)
        for element in clean:
            element["abundance_percent"] = even
        return clean

    scale = MAJOR_CRUST_TARGET_PERCENT / total
    for element in clean:
        element["abundance_percent"] *= scale
    return clean


def default_crust_composition():
    return {
        "major_elements": normalize_major_elements(EARTH_CRUST_MAJOR_ELEMENTS),
        "trace_reserve_percent": TRACE_RESERVE_PERCENT,
        "trace_elements": [],
    }


def crust_composition_from_seed(seed):
    composition = seed.get("crust_composition") if isinstance(seed, dict) else None
    if not isinstance(composition, dict):
        return default_crust_composition()
    return {
        "major_elements": normalize_major_elements(composition.get("major_elements")),
        "trace_reserve_percent": TRACE_RESERVE_PERCENT,
        "trace_elements": list(composition.get("trace_elements") or []),
    }


def set_major_element_abundance(composition, symbol, abundance_percent):
    elements = normalize_major_elements(composition.get("major_elements"))
    target = max(0.0, min(MAJOR_CRUST_TARGET_PERCENT, float(abundance_percent)))
    for element in elements:
        if element["symbol"] == symbol:
            selected = element
            break
    else:
        return composition

    selected["abundance_percent"] = target
    other_elements = [element for element in elements if element["symbol"] != symbol]
    other_target = MAJOR_CRUST_TARGET_PERCENT - target
    other_total = sum(element["abundance_percent"] for element in other_elements)
    if other_elements:
        if other_total <= 0:
            even = other_target / len(other_elements)
            for element in other_elements:
                element["abundance_percent"] = even
        else:
            scale = other_target / other_total
            for element in other_elements:
                element["abundance_percent"] *= scale

    composition["major_elements"] = elements
    composition["trace_reserve_percent"] = TRACE_RESERVE_PERCENT
    return composition


def add_abundant_trace_element(composition, symbol, initial_abundance=1.0):
    symbol = str(symbol or "").strip()
    if not symbol:
        return composition

    elements = normalize_major_elements(composition.get("major_elements"))
    if any(element["symbol"] == symbol for element in elements):
        return composition

    try:
        requested = float(initial_abundance)
    except (TypeError, ValueError):
        requested = trace_promotion_abundance(symbol)
    abundance = min(max(0.0, requested), trace_promotion_abundance(symbol))

    elements.append({
        "symbol": symbol,
        "name": element_name(symbol),
        "abundance_percent": abundance,
        "rarity": trace_element_rarity(symbol),
    })
    composition["major_elements"] = normalize_major_elements(elements)
    composition["trace_reserve_percent"] = TRACE_RESERVE_PERCENT
    return composition


def estimate_crust_density_kg_m3(composition):
    elements = normalize_major_elements((composition or {}).get("major_elements"))
    denominator = 0.0
    total_weight = 0.0
    for element in elements:
        weight = max(0.0, float(element.get("abundance_percent", 0.0)))
        density = CRUST_ELEMENT_DENSITY_PROXY_KG_M3.get(element.get("symbol"), DEFAULT_CRUST_DENSITY_KG_M3)
        if density <= 0:
            continue
        denominator += weight / density
        total_weight += weight
    if denominator <= 0 or total_weight <= 0:
        return DEFAULT_CRUST_DENSITY_KG_M3
    return total_weight / denominator


def classify_crust_type(composition):
    elements = {
        element.get("symbol"): float(element.get("abundance_percent", 0.0))
        for element in normalize_major_elements((composition or {}).get("major_elements"))
    }
    silica = elements.get("Si", 0.0)
    iron_magnesium = elements.get("Fe", 0.0) + elements.get("Mg", 0.0)
    heavy_metals = sum(
        elements.get(symbol, 0.0)
        for symbol in ("Fe", "Ni", "Co", "Cr", "Ti", "Os", "Pt", "Au", "U", "Th")
    )
    if heavy_metals >= 18.0:
        return "metal-rich"
    if iron_magnesium >= 12.0:
        return "mafic"
    if silica >= 28.0:
        return "felsic silicate"
    return "intermediate silicate"
