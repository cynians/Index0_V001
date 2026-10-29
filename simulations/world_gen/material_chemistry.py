"""Material chemistry: formulas, a planet's element distribution, availability.

The planet's element distribution is the first step of world generation; the
materials that can exist follow from it.  This module holds the pieces that
turn it into a material roster:

``formula_composition``
    Parses a computational formula (``Ca5(PO4)3F``, ``CaSO4*2H2O``,
    ``(Mg,Fe)2SiO4``) into element mass fractions.  Comma groups inside
    parentheses are solid solutions split equally; authored end-members give
    real proportions (``endmember_composition``).
``planet_element_distribution``
    Explicit elements as set on the seed; every unlisted element fills the
    trace reserve in proportion to its reference crustal abundance, so "not
    listed" means Earth-like background.  An element listed at zero is absent.
``material_availability``
    How available a material is relative to an Earth-like crust:
    reachability of its major-element chemistry by magmatic and sedimentary
    differentiation, times Liebig's law on its minor defining elements.  An
    Earth-like crust gives 1 for every material.

All inputs are percentages by mass.  Reference abundances come from the
ontology element entities (``earth_upper_crust_abundance_ppm``).
"""

from __future__ import annotations

import math
import re

ATOMIC_MASS = {
    "H": 1.008, "He": 4.0026, "Li": 6.94, "Be": 9.0122, "B": 10.81, "C": 12.011, "N": 14.007,
    "O": 15.999, "F": 18.998, "Ne": 20.180, "Na": 22.990, "Mg": 24.305, "Al": 26.982,
    "Si": 28.085, "P": 30.974, "S": 32.06, "Cl": 35.45, "Ar": 39.948, "K": 39.098,
    "Ca": 40.078, "Sc": 44.956, "Ti": 47.867, "V": 50.942, "Cr": 51.996, "Mn": 54.938,
    "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38, "Ga": 69.723,
    "Ge": 72.630, "As": 74.922, "Se": 78.971, "Br": 79.904, "Kr": 83.798, "Rb": 85.468,
    "Sr": 87.62, "Y": 88.906, "Zr": 91.224, "Nb": 92.906, "Mo": 95.95, "Tc": 98.0,
    "Ru": 101.07, "Rh": 102.91, "Pd": 106.42, "Ag": 107.87, "Cd": 112.41, "In": 114.82,
    "Sn": 118.71, "Sb": 121.76, "Te": 127.60, "I": 126.90, "Xe": 131.29, "Cs": 132.91,
    "Ba": 137.33, "La": 138.91, "Ce": 140.12, "Pr": 140.91, "Nd": 144.24, "Pm": 145.0,
    "Sm": 150.36, "Eu": 151.96, "Gd": 157.25, "Tb": 158.93, "Dy": 162.50, "Ho": 164.93,
    "Er": 167.26, "Tm": 168.93, "Yb": 173.05, "Lu": 174.97, "Hf": 178.49, "Ta": 180.95,
    "W": 183.84, "Re": 186.21, "Os": 190.23, "Ir": 192.22, "Pt": 195.08, "Au": 196.97,
    "Hg": 200.59, "Tl": 204.38, "Pb": 207.2, "Bi": 208.98, "Po": 209.0, "At": 210.0,
    "Rn": 222.0, "Fr": 223.0, "Ra": 226.0, "Ac": 227.0, "Th": 232.04, "Pa": 231.04,
    "U": 238.03,
}

_TOKEN = re.compile(r"\s*(?:([A-Z][a-z]?)|(\d+(?:\.\d+)?)|([()\[\],]))")


class FormulaError(ValueError):
    pass


def _tokens(text):
    position = 0
    tokens = []
    text = text.strip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match or match.end() == position:
            raise FormulaError(f"cannot parse formula near {text[position:]!r}")
        symbol, number, punct = match.groups()
        if symbol:
            if symbol not in ATOMIC_MASS:
                raise FormulaError(f"unknown element {symbol!r}")
            tokens.append(("element", symbol))
        elif number:
            tokens.append(("number", float(number)))
        else:
            tokens.append(("punct", punct))
        position = match.end()
    return tokens


def _parse_sequence(tokens, index, closing=None):
    """Parse until ``closing``; return (alternatives, index).

    ``alternatives`` is a list of mole dicts, one per comma-separated
    alternative (a solid-solution site); a plain sequence has one.
    """
    alternatives = [{}]
    while index < len(tokens):
        kind, value = tokens[index]
        if kind == "punct" and value == closing:
            return alternatives, index + 1
        if kind == "punct" and value == ",":
            alternatives.append({})
            index += 1
            continue
        if kind == "punct" and value in "([":
            inner, index = _parse_sequence(tokens, index + 1, ")" if value == "(" else "]")
            group = {}
            for alternative in inner:
                for element, count in alternative.items():
                    group[element] = group.get(element, 0.0) + count / len(inner)
        elif kind == "element":
            group = {value: 1.0}
            index += 1
        else:
            raise FormulaError(f"unexpected token {value!r}")
        multiplier = 1.0
        if index < len(tokens) and tokens[index][0] == "number":
            multiplier = tokens[index][1]
            index += 1
        target = alternatives[-1]
        for element, count in group.items():
            target[element] = target.get(element, 0.0) + count * multiplier
    if closing is not None:
        raise FormulaError("unbalanced parentheses")
    return alternatives, index


def formula_moles(formula):
    """Moles of each element in one formula unit of ``formula``."""
    moles = {}
    for part in re.split(r"[*·]", str(formula or "")):
        part = part.strip()
        if not part:
            continue
        coefficient = 1.0
        match = re.match(r"^(\d+(?:\.\d+)?)(?=[A-Z(\[])", part)
        if match:
            coefficient = float(match.group(1))
            part = part[match.end():]
        alternatives, _index = _parse_sequence(_tokens(part), 0)
        for alternative in alternatives:
            for element, count in alternative.items():
                moles[element] = moles.get(element, 0.0) + coefficient * count / len(alternatives)
    if not moles:
        raise FormulaError(f"empty formula {formula!r}")
    return moles


def formula_composition(formula):
    """Element mass percentages of ``formula`` (sums to 100)."""
    masses = {element: count * ATOMIC_MASS[element] for element, count in formula_moles(formula).items()}
    total = sum(masses.values())
    return {element: 100.0 * mass / total for element, mass in masses.items()}


def mix_compositions(parts):
    """Mass-weighted mix of ``[(composition_percent, weight), ...]``."""
    total_weight = sum(max(0.0, float(weight)) for _composition, weight in parts)
    if total_weight <= 0.0:
        return {}
    mixed = {}
    for composition, weight in parts:
        share = max(0.0, float(weight)) / total_weight
        for element, percent in composition.items():
            mixed[element] = mixed.get(element, 0.0) + percent * share
    return mixed


def endmember_composition(endmembers):
    """Composition of a solid solution from ``[{"formula", "mass_fraction"}, ...]``."""
    return mix_compositions([
        (formula_composition(item["formula"]), float(item.get("mass_fraction", 0.0) or 0.0))
        for item in endmembers or []
        if isinstance(item, dict) and item.get("formula")
    ])


def bulk_composition(components):
    """Element percentages of ``{component_formula: wt_percent}`` (oxides, salts, native elements)."""
    return mix_compositions([
        (formula_composition(formula), float(percent or 0.0))
        for formula, percent in (components or {}).items()
    ])


def rounded_composition(composition, digits=4):
    return {element: round(float(percent), digits) for element, percent in sorted(composition.items()) if percent > 0.0}


# --- planet element distribution -------------------------------------------

def _explicit_elements(crust_composition):
    from simulations.world_gen.crust import crust_composition_from_seed

    composition = crust_composition_from_seed({"crust_composition": crust_composition})
    explicit = {}
    for group_name in ("major_elements", "trace_elements"):
        for element in composition.get(group_name) or []:
            symbol = str(element.get("symbol") or "").strip()
            if not symbol:
                continue
            try:
                abundance = max(0.0, float(element.get("abundance_percent", 0.0) or 0.0))
            except (TypeError, ValueError):
                abundance = 0.0
            explicit[symbol] = max(explicit.get(symbol, 0.0), abundance)
    return explicit, composition


def planet_element_distribution(crust_composition, reference_percent=None, rock_only=True):
    """Full element distribution of a crust in mass percent.

    Listed elements keep their values (a listed zero is absent).  Every
    unlisted element is present at its reference crustal abundance
    (``reference_percent``): "not listed" means an Earth-like background, and
    listing other elements never inflates it.

    When the volatile budget has partitioned the inventory, the composition
    carries ``volatile_envelope_percent`` -- the element mass held in the air,
    seas and surface ices.  With ``rock_only`` that share is removed and the
    rest renormalised, so the rock chemistry excludes the oceans (Earth's
    0.45 % hydrogen inventory leaves ~0.15 % in its rocks).
    """
    explicit, _composition = _explicit_elements(crust_composition)
    distribution = dict(explicit)
    for symbol, value in (reference_percent or {}).items():
        if symbol not in explicit and float(value or 0.0) > 0.0:
            distribution[symbol] = float(value)
    envelope = crust_composition.get("volatile_envelope_percent") if isinstance(crust_composition, dict) else None
    if rock_only and isinstance(envelope, dict) and envelope:
        removed = 0.0
        for symbol, value in envelope.items():
            if symbol in distribution:
                taken = min(distribution[symbol], max(0.0, float(value or 0.0)))
                distribution[symbol] -= taken
                removed += taken
        if 0.0 < removed < 100.0:
            scale = 100.0 / (100.0 - removed)
            distribution = {symbol: value * scale for symbol, value in distribution.items()}
    return distribution


# --- availability ------------------------------------------------------------

# Elements below this share of the reference crust are minor.
MINOR_ELEMENT_PERCENT = 1.0
# An element is essential to a material at this mass share: without it the
# material cannot form.  Smaller shares are incidental (basalt's potassium).
ESSENTIAL_ELEMENT_PERCENT = 2.0
# A minor element defines a material (Liebig's law applies) when the material
# holds at least this share of it and concentrates it this far over the crust
# (copper in chalcopyrite, carbon in limestone, phosphorus in apatite).
DEFINING_MINOR_SHARE_PERCENT = 1.0
DEFINING_MINOR_CONCENTRATION = 10.0
# Enrichment over the crust that differentiation reaches without penalty.
DIFFERENTIATION_LIMIT = {
    "K": 4.0, "Na": 3.0, "P": 4.0, "Ti": 3.0, "Si": 1.7, "Al": 2.0,
    "Ca": 2.5, "Mg": 3.0, "Fe": 2.5, "Mn": 3.0,
}
DEFAULT_DIFFERENTIATION_LIMIT = 2.5
ENRICHMENT_PENALTY_EXPONENT = 2.0
# A crust made largely of an element the material lacks leaves less room for
# it: one gentle factor for the worst such element, ramping in between 2 % and
# 40 % of the crust so no threshold flips it on or off (a crust with 16 %
# carbon is still mostly silicate).
DEPLETION_RAMP_PERCENT = (2.0, 40.0)
DEPLETION_LIMIT = 0.25
DEPLETION_FLOOR = 0.3
AVAILABILITY_CAP = 10.0


def _defining_minor_elements(composition, reference_elements):
    defining = []
    for element, share in composition.items():
        if element in {"O", "H"} or share < DEFINING_MINOR_SHARE_PERCENT:
            continue
        reference = float(reference_elements.get(element, 0.0) or 0.0)
        if reference < MINOR_ELEMENT_PERCENT and (reference <= 0.0 or share / reference >= DEFINING_MINOR_CONCENTRATION):
            defining.append(element)
    return defining


# The limiting cause is reported only below this share of Earth availability.
LIMITING_REPORT_BELOW = 0.9


def _reach_terms(composition, elements, defining=()):
    """Factors that make a material harder to reach from a crust ``elements``.

    Keys are ``("scarce", element)`` for essential elements the material must
    concentrate and ``("diluted", element)`` for a crust element it lacks.
    Returns ``None`` when an essential element is absent altogether (the
    element is then the one returned second).
    """
    terms = {}
    for element, share in composition.items():
        if element in {"O", "H"} or element in defining or share < ESSENTIAL_ELEMENT_PERCENT:
            continue
        abundance = float(elements.get(element, 0.0) or 0.0)
        if abundance <= 0.0:
            return None, element
        ratio = share / abundance
        limit = DIFFERENTIATION_LIMIT.get(element, DEFAULT_DIFFERENTIATION_LIMIT)
        terms[("scarce", element)] = (limit / ratio) ** ENRICHMENT_PENALTY_EXPONENT if ratio > limit else 1.0
    worst = None
    low, high = DEPLETION_RAMP_PERCENT
    for element, abundance in elements.items():
        abundance = float(abundance or 0.0)
        if element in {"O", "H"} or abundance <= low:
            continue
        ratio = float(composition.get(element, 0.0)) / abundance
        if ratio < DEPLETION_LIMIT:
            strength = min(1.0, (abundance - low) / (high - low))
            base = max(DEPLETION_FLOOR, math.sqrt(max(ratio, 0.0) / DEPLETION_LIMIT))
            factor = 1.0 - strength * (1.0 - base)
            if worst is None or factor < worst[1]:
                worst = (element, factor)
    if worst is not None:
        terms[("diluted", worst[0])] = worst[1]
    return terms, None


def _reachability(composition, elements, defining=()):
    """Unnormalised reachability of ``composition`` from a crust ``elements``."""
    terms, _missing = _reach_terms(composition, elements, defining)
    if terms is None:
        return 0.0
    return math.prod(terms.values())


def _minor_supply(composition, distribution, defining):
    """Stoichiometric supply of a material from its defining minor elements.

    The element with the least abundance per unit of the material limits it
    (copper for chalcopyrite on Earth, sulfur once copper is plentiful).
    """
    return min(
        (float(distribution.get(element, 0.0) or 0.0) / float(composition[element]), element)
        for element in defining
    )


def material_availability_detail(composition, elements, reference_elements):
    """``material_availability`` plus the limiting cause.

    Returns ``(availability, limiting_element, limiting_kind)`` where the kind
    is ``"scarce"`` (the planet has too little of the element) or
    ``"diluted"`` (the crust is so rich in the element that materials without
    it are crowded out).  The cause is reported only when availability is
    below ``LIMITING_REPORT_BELOW`` of Earth's.
    """
    if not composition:
        return 1.0, None, None
    defining = _defining_minor_elements(composition, reference_elements)
    planet_terms, missing = _reach_terms(composition, elements, defining)
    reference_terms, _reference_missing = _reach_terms(composition, reference_elements, defining)
    if planet_terms is None:
        return 0.0, missing, "scarce"
    relative = {}
    for key in set(planet_terms) | set(reference_terms or {}):
        planet = planet_terms.get(key, 1.0)
        reference = (reference_terms or {}).get(key, 1.0)
        relative[key] = planet / reference if reference > 0.0 else (AVAILABILITY_CAP if planet > 0.0 else 0.0)
    if defining:
        planet_supply, liebig_element = _minor_supply(composition, elements, defining)
        reference_supply, _element = _minor_supply(composition, reference_elements, defining)
        if reference_supply > 0.0:
            liebig = planet_supply / reference_supply
        else:
            liebig = AVAILABILITY_CAP if planet_supply > 0.0 else 0.0
        relative[("scarce", liebig_element)] = relative.get(("scarce", liebig_element), 1.0) * liebig
    availability = max(0.0, min(AVAILABILITY_CAP, math.prod(relative.values()) if relative else 1.0))
    if availability >= LIMITING_REPORT_BELOW or not relative:
        return availability, None, None
    (kind, element), _factor = min(relative.items(), key=lambda item: item[1])
    return availability, element, kind


def material_availability(composition, elements, reference_elements):
    """Availability of a material relative to the reference crust.

    ``composition``: the material's element percentages; ``elements``: the
    planet's full distribution; ``reference_elements``: the reference crust
    run through the same distribution.  Returns ``(availability,
    limiting_element)``; 1 means Earth-like, 0 impossible.
    """
    availability, element, _kind = material_availability_detail(composition, elements, reference_elements)
    return availability, element


def defining_minor_elements(composition, reference_elements):
    """Minor elements a material concentrates (copper in chalcopyrite, carbon in graphite)."""
    return _defining_minor_elements(composition, reference_elements)
