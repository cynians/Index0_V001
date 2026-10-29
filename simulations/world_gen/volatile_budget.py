"""Volatile budget: the element distribution decides air, seas and ices.

The planet's element distribution describes its surface inventory -- crust,
hydrosphere and atmosphere together (Earth: 0.45 % H, most of it in the
oceans).  This module turns it into the atmosphere composition and pressure,
the surface temperature, and which volatile forms seas or ices:

1. **Inventory.**  Element mass fractions times the reservoir mass (crust
   thickness x area x density) give moles of each element.
2. **Speciation (oxygen budget).**  Oxygen first binds the rock cations as
   oxides (iron can give its oxygen back, down to metal: the iron-wustite
   buffer), then turns hydrogen into water, carbon into CO2 and sulfur into
   sulfate.  Hydrogen left without oxygen makes methane (with carbon),
   ammonia (with nitrogen), H2S and H2.  An Earth-like inventory is
   oxidized; an ice-rich, carbon-bearing one (Titan) is reducing.
3. **Surface exchange.**  Water beyond what the rock binds is at the
   surface.  Carbon, nitrogen, sulfur and noble gases reach the surface in
   proportion to how actively the interior exchanges with it (tectonic
   regime); icy crusts release little and their water ice is bedrock.
4. **Escape.**  Jeans escape of light gases, energy-limited (XUV) loss of
   free hydrogen, and a non-thermal loss that strips small, strongly
   irradiated bodies (Mars keeps a few percent, Earth and Venus nearly all).
5. **Climate + phases.**  The surface temperature is the first stable
   radiative equilibrium above the bare-rock temperature: each condensable's
   vapour is capped by its saturation pressure (Clausius-Clapeyron from the
   triple point; none above the critical point), the rest condenses as
   liquid or ice, and a grey two-stream greenhouse sets the temperature.
   Water bands saturate, so water vapour cannot run away inside the grey
   model; the runaway is the explicit Simpson-Nakajima limit: above ~282
   W/m2 of absorbed starlight a wet planet keeps its oceans as steam and
   loses the hydrogen (Venus).
6. **Carbonate-silicate cycle.**  Where oceans are open and the interior
   cycles, weathering regulates CO2 (Walker, Hays & Kasting 1981): low at
   288 K, rising steeply as the planet cools, so an Earth moved outward
   builds a CO2 greenhouse instead of freezing solid.

Earth's inventory at 1 AU gives ~1 bar of N2, ~288 K, ~2.6 km of ocean and
a few hundred ppm CO2; the same inventory at Venus's distance runs away and
keeps its carbon as ~50 bar of CO2; a Titan-like icy inventory at 9.5 AU
gives ~1 bar of nitrogen with a few percent methane and methane seas on a
water-ice crust; Mars-like crust at 1.5 AU keeps ~20 mbar of CO2 and polar
water ice.

Abundant O2 is biological and is left to a biosphere stage; the budget keeps
abiotic oxygen at trace level.  The element share held in air, seas and
surface ices (``envelope_element_percent``) is removed from the rock
chemistry the material roster sees.
"""

from __future__ import annotations

import math

VOLATILE_BUDGET_MODEL_VERSION = "volatile-budget-v1-element-distribution"
GAS_CONSTANT = 8.314462618
AVOGADRO_MOLE_MASS = {
    "H": 1.008, "He": 4.0026, "C": 12.011, "N": 14.007, "O": 15.999, "Ne": 20.180,
    "S": 32.06, "Cl": 35.45, "Ar": 39.948,
}

# Condensable species: molar mass, triple point, critical point, latent heats
# (J/mol; vaporization near the triple point, sublimation), phase densities.
CONDENSABLES = {
    "H2O": dict(molar_mass=0.018015, triple_k=273.16, triple_bar=0.006117, critical_k=647.1, critical_bar=220.64,
                h_vap=45050.0, h_sub=51060.0, liquid_density=1000.0, solid_density=917.0),
    "CO2": dict(molar_mass=0.04401, triple_k=216.58, triple_bar=5.185, critical_k=304.13, critical_bar=73.77,
                h_vap=15300.0, h_sub=25230.0, liquid_density=1100.0, solid_density=1560.0),
    "CH4": dict(molar_mass=0.016043, triple_k=90.67, triple_bar=0.117, critical_k=190.56, critical_bar=45.99,
                h_vap=8170.0, h_sub=9110.0, liquid_density=450.0, solid_density=490.0),
    "N2": dict(molar_mass=0.028014, triple_k=63.15, triple_bar=0.1253, critical_k=126.2, critical_bar=33.96,
               h_vap=5570.0, h_sub=6290.0, liquid_density=808.0, solid_density=1030.0),
    "NH3": dict(molar_mass=0.017031, triple_k=195.4, triple_bar=0.0607, critical_k=405.4, critical_bar=113.3,
                h_vap=23350.0, h_sub=29000.0, liquid_density=682.0, solid_density=817.0),
    "SO2": dict(molar_mass=0.064066, triple_k=197.64, triple_bar=0.0167, critical_k=430.7, critical_bar=78.8,
                h_vap=24940.0, h_sub=32300.0, liquid_density=1460.0, solid_density=1600.0),
    "H2S": dict(molar_mass=0.034081, triple_k=187.7, triple_bar=0.232, critical_k=373.1, critical_bar=89.6,
                h_vap=18670.0, h_sub=21100.0, liquid_density=950.0, solid_density=1120.0),
    "CO": dict(molar_mass=0.02801, triple_k=68.1, triple_bar=0.154, critical_k=132.9, critical_bar=34.99,
               h_vap=6040.0, h_sub=6900.0, liquid_density=790.0, solid_density=930.0),
    "Ar": dict(molar_mass=0.039948, triple_k=83.81, triple_bar=0.689, critical_k=150.7, critical_bar=48.6,
               h_vap=6430.0, h_sub=7620.0, liquid_density=1400.0, solid_density=1620.0),
}
GASES = {"H2": 0.002016, "He": 0.004003, "Ne": 0.02018, "O2": 0.031998}
MOLAR_MASS = {**{key: value["molar_mass"] for key, value in CONDENSABLES.items()}, **GASES}

# Near-surface relative humidity of condensables that are minor gases; a
# condensable that is the bulk gas sits at saturation (CO2 frost on Mars).
RELATIVE_HUMIDITY = {"H2O": 0.75, "CH4": 0.45, "NH3": 0.5, "SO2": 0.5, "H2S": 0.5}

# Upper-crust background of the volatile elements (mass %), used for unlisted
# elements when the material catalog (the ontology reference) is not loaded.
VOLATILE_REFERENCE_PERCENT = {
    "H": 0.14, "C": 0.324, "N": 0.0083, "S": 0.035, "Cl": 0.037, "F": 0.0557,
    "He": 8e-7, "Ne": 5e-7, "Ar": 0.00035,
}

# Element make-up of each volatile species (atoms per molecule).
SPECIES_ELEMENTS = {
    "H2O": {"H": 2, "O": 1}, "CO2": {"C": 1, "O": 2}, "CH4": {"C": 1, "H": 4}, "N2": {"N": 2},
    "NH3": {"N": 1, "H": 3}, "SO2": {"S": 1, "O": 2}, "H2S": {"H": 2, "S": 1}, "CO": {"C": 1, "O": 1},
    "Ar": {"Ar": 1}, "H2": {"H": 2}, "He": {"He": 1}, "Ne": {"Ne": 1}, "O2": {"O": 2},
}

LIQUID_NAMES = {
    "H2O": "water", "CH4": "methane_ethane", "N2": "liquid_nitrogen", "CO2": "liquid_carbon_dioxide",
    "NH3": "ammonia", "SO2": "sulfur_dioxide", "H2S": "hydrogen_sulfide", "CO": "carbon_monoxide", "Ar": "argon",
}

# Oxygen bound by rock cations as oxides (O atoms per cation atom).
CATION_OXYGEN = {
    "Si": 2.0, "Ti": 2.0, "Al": 1.5, "Fe": 1.0, "Mn": 1.0, "Mg": 1.0, "Ca": 1.0, "Na": 0.5, "K": 0.5,
    "P": 2.5, "Cr": 1.5, "Zn": 1.0, "Ba": 1.0, "Sr": 1.0, "Zr": 2.0,
    "Li": 0.5, "Be": 1.0, "B": 1.5, "V": 1.5,
}
# Cations whose oxides are less stable than water (Ellingham, standard Gibbs
# energy of formation per mol O at 298 K: CuO -130, Cu2O -146, NiO -212,
# CoO -214 kJ against H2O -237): hydrogen and carbon take oxygen before them,
# so they are oxidized only by what is left and otherwise stay native metal.
NOBLE_CATION_OXYGEN = {"Ni": 1.0, "Co": 1.0, "Cu": 1.0}
# Abiotic O2 (photolysis of water, hydrogen escape) is a balance of
# production and sinks; native metal at the surface is a sink that keeps it
# lower in proportion: this much metal (mol per 100 g of crust, ~0.6 wt%
# native copper) halves it.  A calibration (Kasting 1993 for sink-set
# abiotic O2).
NATIVE_METAL_OXYGEN_SINK_MOL = 0.01
# Oxygen per iron atom that the iron buffer can release to the volatiles.
IRON_REDOX_BUFFER = 1.0
# Fraction of each exchangeable reservoir that reaches the surface, by how
# actively the interior exchanges with it.  Water is handled separately (all
# water beyond what the rock binds is at the surface).
EXCHANGE_FRACTIONS = {
    "active": {"C": 1.0, "N": 0.5, "S": 3e-3, "noble": 0.4},
    "stagnant": {"C": 0.5, "N": 0.35, "S": 2e-3, "noble": 0.3},
    "inactive": {"C": 0.1, "N": 0.15, "S": 5e-4, "noble": 0.15},
    "icy": {"C": 0.002, "N": 0.015, "S": 1e-5, "noble": 0.05},
}
# Volcanic sulfur gases (SO2, H2S) rain out within weeks over liquid water
# and are photochemically removed in cold air; only hot, dry worlds
# accumulate them (Venus: ~150 ppm SO2).
SULFUR_GAS_WET_REMOVAL = 1e-4
# Below ~400 K sulfur gases photolyse and settle out as sulfate aerosol within
# years (Mars keeps < 1 ppb SO2).
SULFUR_GAS_COLD_REMOVAL = 1e-4
SULFUR_GAS_PERSISTENCE_K = 400.0
# Open-ocean fraction ramps from 0 to 1 between these global-mean surface
# temperatures (sea ice retreats to the poles).
OPEN_OCEAN_RAMP_K = (253.0, 273.0)
ROCK_DENSITY = 2800.0
ICE_DENSITY = 950.0
# Water a silicate crust binds in hydrous minerals (mass fraction of rock).
ROCK_BOUND_WATER = 0.012
# Carbonate-silicate regulation of CO2 over liquid-water oceans: weathering
# W ~ open_ocean * (pCO2/p0)^beta * exp((T - T0)/Te) balances outgassing
# (Walker, Hays & Kasting 1981; Te ~ 13.7 K, beta ~ 0.5), so the regulated
# pCO2 = p0 * open_ocean^(-1/beta) * exp((T0 - T)/(Te * beta)).
CARBONATE_REFERENCE_BAR = 2.8e-4
CARBONATE_REFERENCE_K = 288.0
CARBONATE_SENSITIVITY_K = 7.0
CARBONATE_WEATHERING_BETA = 0.5
CARBONATE_MAX_REGULATED_BAR = 10.0
MINIMUM_OCEAN_DEPTH_FOR_CARBONATES_M = 10.0
# Outgoing longwave limit of a moist atmosphere (Simpson-Nakajima limit,
# Goldblatt et al. 2013, Nature Geoscience 6, 661): absorbed flux above it
# drives a runaway greenhouse.
RUNAWAY_GREENHOUSE_LIMIT_W_M2 = 282.0
STEFAN_BOLTZMANN = 5.670374419e-8
MAXIMUM_SURFACE_K = 2500.0
# Global-equivalent condensate depth below which a species is a trace frost,
# not a surface ice material.
MINIMUM_SURFACE_ICE_DEPTH_M = 0.05
# Below this surface pressure the body is treated as airless (exosphere).
EXOSPHERE_BAR = 1e-4
# Energy-limited escape: heating efficiency and the XUV energy the Sun has
# delivered per square metre at 1 AU over 4.5 Gyr (most of it in the first
# few hundred Myr of saturated activity; Ribas et al. 2005).
ENERGY_LIMITED_EFFICIENCY = 0.1
XUV_FLUENCE_1AU_J_M2 = 2.0e15
# A steam atmosphere loses its water on this timescale (H escape).
STEAM_WATER_LOSS_GYR = 0.3
# Non-thermal escape (ion pickup, sputtering, photochemical loss) removes a
# fraction exp(-k * F * exp(-(v_esc / v0)^2)) of the atmosphere, with F the
# stellar flux relative to Earth's times the age in Gyr.  Calibrated so a
# Mars-sized body at 1.5 AU keeps a few percent, Earth and Venus > 95 %, and
# a Titan-sized body at 9.5 AU about two thirds.
NONTHERMAL_ESCAPE_COEFFICIENT = 33.0
NONTHERMAL_ESCAPE_VELOCITY_M_S = 3500.0
NONTHERMAL_ESCAPE_SPECIES = ("N2", "CO2", "CH4", "NH3", "CO", "SO2", "H2S", "Ar", "Ne", "He", "H2")


def saturation_pressure_bar(species, temperature_k):
    """Saturation vapour pressure (bar); ``inf`` above the critical point."""
    data = CONDENSABLES[species]
    temperature_k = max(1.0, float(temperature_k))
    if temperature_k >= data["critical_k"]:
        return math.inf
    latent = data["h_sub"] if temperature_k < data["triple_k"] else data["h_vap"]
    exponent = -latent / GAS_CONSTANT * (1.0 / temperature_k - 1.0 / data["triple_k"])
    return data["triple_bar"] * math.exp(max(-700.0, min(700.0, exponent)))


WATER_TAU_COEFFICIENT = 1.03
WATER_TAU_SATURATION = 2.0


def frost_point_k(species, partial_bar):
    """Temperature below which ``species`` at ``partial_bar`` condenses (inverse Clausius-Clapeyron)."""
    data = CONDENSABLES[species]
    partial = max(1e-30, float(partial_bar))
    if partial >= data["triple_bar"]:
        latent = data["h_vap"]
    else:
        latent = data["h_sub"]
    inverse = 1.0 / data["triple_k"] - GAS_CONSTANT / latent * math.log(partial / data["triple_bar"])
    return 1.0 / inverse if inverse > 0.0 else data["critical_k"]


def _optical_depth(partial_bar, total_bar):
    """Grey infrared optical depth; calibrated on Earth, Venus and Titan."""
    broadening = max(1e-4, total_bar) ** 0.35
    tau = 0.0
    # Water bands saturate while the infrared windows stay open, so its
    # optical depth levels off (the runaway itself is the explicit
    # Simpson-Nakajima flux limit, not a grey-model instability).
    water = WATER_TAU_COEFFICIENT * math.sqrt(max(0.0, partial_bar.get("H2O", 0.0)) / 0.012) * broadening
    tau += water / (1.0 + water / WATER_TAU_SATURATION)
    tau += 0.22 * (max(0.0, partial_bar.get("CO2", 0.0)) / 2.8e-4) ** 0.3 * broadening
    tau += 0.034 * (max(0.0, partial_bar.get("CH4", 0.0)) / 1.8e-6) ** 0.3 * broadening
    tau += 0.05 * (max(0.0, partial_bar.get("NH3", 0.0)) / 1e-6) ** 0.3 * broadening
    tau += 0.02 * (max(0.0, partial_bar.get("SO2", 0.0)) / 1e-6) ** 0.3 * broadening
    tau += 0.005 * max(0.0, total_bar) ** 1.6
    return min(5000.0, tau)


def _speciate(elements):
    """Moles per 100 g of inventory for each volatile species, from the oxygen budget."""
    moles = {symbol: float(elements.get(symbol, 0.0) or 0.0) / mass for symbol, mass in AVOGADRO_MOLE_MASS.items()}
    from simulations.world_gen.material_chemistry import ATOMIC_MASS

    oxygen_rock = sum(
        float(elements.get(symbol, 0.0) or 0.0) / ATOMIC_MASS[symbol] * per_atom
        for symbol, per_atom in CATION_OXYGEN.items()
        if symbol in ATOMIC_MASS
    )
    # Iron buffers the oxygen budget: ferrous iron gives up its oxygen (down to
    # metal, the iron-wustite buffer) before the volatiles are reduced, so a
    # rock-dominated inventory only makes methane and hydrogen when it is
    # short of oxygen beyond what its iron can supply.
    iron_buffer = float(elements.get("Fe", 0.0) or 0.0) / ATOMIC_MASS["Fe"] * IRON_REDOX_BUFFER
    oxygen_free = moles["O"] - oxygen_rock + iron_buffer
    hydrogen = moles["H"]
    water = min(hydrogen / 2.0, max(0.0, oxygen_free))
    oxygen_free -= water
    hydrogen_left = hydrogen - 2.0 * water
    # Carbon takes one oxygen (CO) before a second (CO2): an oxygen-short
    # inventory outgasses carbon monoxide, an oxygen-rich one CO2.
    carbon_oxidized = min(moles["C"], max(0.0, oxygen_free))
    oxygen_free -= carbon_oxidized
    carbon_dioxide = min(carbon_oxidized, max(0.0, oxygen_free))
    oxygen_free -= carbon_dioxide
    carbon_monoxide = carbon_oxidized - carbon_dioxide
    carbon_left = moles["C"] - carbon_oxidized
    noble_demand = sum(
        float(elements.get(symbol, 0.0) or 0.0) / ATOMIC_MASS[symbol] * per_atom
        for symbol, per_atom in NOBLE_CATION_OXYGEN.items()
        if symbol in ATOMIC_MASS
    )
    noble_oxide = min(noble_demand, max(0.0, oxygen_free))
    oxygen_free -= noble_oxide
    sulfate = min(moles["S"], max(0.0, oxygen_free) / 3.0)
    oxygen_free -= 3.0 * sulfate
    sulfur_reduced = moles["S"] - sulfate
    methane = min(carbon_left, hydrogen_left / 4.0)
    hydrogen_left -= 4.0 * methane
    ammonia = min(moles["N"], hydrogen_left / 3.0) if hydrogen_left > 0.0 else 0.0
    hydrogen_left -= 3.0 * ammonia
    nitrogen = (moles["N"] - ammonia) / 2.0
    hydrogen_sulfide = min(sulfur_reduced, hydrogen_left / 2.0) if hydrogen_left > 0.0 else 0.0
    hydrogen_left -= 2.0 * hydrogen_sulfide
    hydrogen_gas = max(0.0, hydrogen_left) / 2.0
    demand = moles["H"] / 2.0 + 2.0 * moles["C"]
    oxidation = (moles["O"] - oxygen_rock + iron_buffer) / demand if demand > 0.0 else 1.0
    if oxidation >= 1.0:
        state = "oxidized"
    elif methane > 0.0 or hydrogen_gas > 0.0 or oxidation < 0.5:
        state = "reducing"
    else:
        state = "intermediate"
    return {
        "H2O": water, "CO2": carbon_dioxide, "CO": carbon_monoxide, "CH4": methane, "NH3": ammonia, "N2": nitrogen,
        "H2S": hydrogen_sulfide, "H2": hydrogen_gas, "sulfate_S": sulfate, "sulfide_S": sulfur_reduced - hydrogen_sulfide,
        "reduced_carbon": carbon_left - methane,
        "He": moles["He"], "Ne": moles["Ne"], "Ar": moles["Ar"],
    }, {
        "redox_state": state,
        "oxygen_to_volatile_demand": round(oxidation, 4),
        "oxygen_rock_mol_per_100g": round(oxygen_rock, 4),
        # Noble metal the oxygen could not oxidize: it stays native.
        "native_metal_mol_per_100g": round(max(0.0, noble_demand - noble_oxide), 6),
    }


def abiotic_oxygen(water_mole_fraction, speciation):
    """Trace O2 mole fraction of an oxidized, watered air, lowered by native metal at the surface."""
    oxygen = 0.0004 + 0.0012 * min(1.0, float(water_mole_fraction) * 40.0)
    return oxygen / (1.0 + float(speciation.get("native_metal_mol_per_100g", 0.0) or 0.0) / NATIVE_METAL_OXYGEN_SINK_MOL)


def _exchange_regime(seed, physics, water_mass_fraction, equilibrium_k):
    tectonics = str(seed.get("tectonics_mode") or "unknown").strip().lower()
    if water_mass_fraction >= 0.3 and equilibrium_k < 200.0:
        return "icy"
    if tectonics in {"plate_tectonics", "mobile_lid"}:
        return "active"
    if tectonics in {"stagnant_lid", "episodic_lid", "heat_pipe", "plutonic_squishy_lid"}:
        return "stagnant"
    if tectonics in {"inactive", "cryotectonic"}:
        return "inactive"
    mass_earth = float(physics.get("mass_earth", seed.get("radius_earth", 1.0) ** 3) or 0.0)
    return "active" if mass_earth >= 0.4 else "stagnant"


def _partition(available_kg, temperature_k, gravity, area):
    """Split each species into vapour and condensate at ``temperature_k``.

    Vapour partial pressure of a condensable is capped by its relative
    humidity x saturation pressure; the column pressure is the weight of the
    vapour.  Solved by fixed-point iteration (the total pressure depends on
    what stays in the air).
    """
    vapour = dict(available_kg)
    for _iteration in range(60):
        column_moles = {species: mass / MOLAR_MASS[species] for species, mass in vapour.items() if mass > 0.0}
        total_moles = sum(column_moles.values())
        total_bar = sum(vapour.values()) * gravity / area / 1e5
        if total_moles <= 0.0:
            break
        changed = False
        for species in CONDENSABLES:
            mass = vapour.get(species, 0.0)
            if mass <= 0.0:
                continue
            cap = saturation_pressure_bar(species, temperature_k) * RELATIVE_HUMIDITY.get(species, 1.0)
            partial = total_bar * column_moles[species] / total_moles
            if partial > cap * 1.0001:
                # Keep only as much of this species as meets the cap over the
                # other gases (damped: the others are adjusting too).
                others_moles = total_moles - column_moles[species]
                others_mass = sum(vapour.values()) - mass
                keep = _vapour_mass_for_partial(cap, MOLAR_MASS[species], others_moles, others_mass, gravity, area)
                vapour[species] = max(0.0, min(mass, 0.5 * mass + 0.5 * keep))
                changed = True
        if not changed:
            break
    condensed = {species: max(0.0, available_kg.get(species, 0.0) - vapour.get(species, 0.0)) for species in available_kg}
    return vapour, condensed


def _vapour_mass_for_partial(partial_bar, molar_mass, others_moles, others_mass, gravity, area):
    """Mass of one gas whose partial pressure equals ``partial_bar`` over the other gases."""
    target_pa = partial_bar * 1e5
    low, high = 0.0, max(1.0, target_pa * area / gravity * 10.0)
    for _step in range(80):
        middle = 0.5 * (low + high)
        moles = middle / molar_mass
        total_pa = (middle + others_mass) * gravity / area
        partial = total_pa * moles / max(1e-30, moles + others_moles)
        if partial > target_pa:
            high = middle
        else:
            low = middle
    return 0.5 * (low + high)


def derive_volatile_budget(seed, physics, stellar_luminosity_solar, semi_major_axis_au):
    """Atmosphere, surface temperature, seas and ices from the element distribution."""
    from simulations.world_gen import natural_materials
    from simulations.world_gen.atmosphere import equilibrium_temperature_k, escape_velocity_m_s, retention_factor
    from simulations.world_gen.material_chemistry import planet_element_distribution

    seed = seed if isinstance(seed, dict) else {}
    physics = physics if isinstance(physics, dict) else {}
    elements = planet_element_distribution(
        seed.get("crust_composition"),
        {**VOLATILE_REFERENCE_PERCENT, **natural_materials.reference_crust_percent()},
        rock_only=False,
    )
    radius_m = max(1.0, float(physics.get("radius_m", float(seed.get("radius_earth", 1.0) or 1.0) * 6_371_000.0) or 1.0))
    gravity = max(0.05, float(physics.get("surface_gravity_g", 1.0) or 1.0)) * 9.80665
    area = 4.0 * math.pi * radius_m ** 2
    eccentricity = max(0.0, min(0.85, float(seed.get("orbital_eccentricity", seed.get("eccentricity", 0.0)) or 0.0)))
    equilibrium_k = equilibrium_temperature_k(
        stellar_luminosity_solar, semi_major_axis_au,
        bond_albedo=float(seed.get("bond_albedo", 0.30) or 0.30), eccentricity=eccentricity,
    )
    age_gyr = max(0.05, float(seed.get("system_age_gyr", 4.5) or 4.5))

    species, speciation = _speciate(elements)
    water_mass_fraction = species["H2O"] * MOLAR_MASS["H2O"] * 1000.0 / 100.0
    rock_fraction = max(0.0, 1.0 - water_mass_fraction)
    density = 1.0 / (water_mass_fraction / ICE_DENSITY + rock_fraction / ROCK_DENSITY) if water_mass_fraction < 1.0 else ICE_DENSITY
    crust_m = max(1000.0, float(seed.get("crust_thickness_km", 35.0) or 35.0) * 1000.0)
    reservoir_kg = crust_m * area * density
    moles_per_kg = {key: value * 10.0 for key, value in species.items()}  # per 100 g -> per kg
    regime = _exchange_regime(seed, physics, water_mass_fraction, equilibrium_k)
    fractions = EXCHANGE_FRACTIONS[regime]

    bound_water_kg = ROCK_BOUND_WATER * rock_fraction * reservoir_kg if regime != "icy" else 0.0
    water_total_kg = moles_per_kg["H2O"] * MOLAR_MASS["H2O"] * reservoir_kg
    available = {
        "H2O": max(0.0, water_total_kg - bound_water_kg),
        "CO2": moles_per_kg["CO2"] * MOLAR_MASS["CO2"] * reservoir_kg * fractions["C"],
        "CH4": moles_per_kg["CH4"] * MOLAR_MASS["CH4"] * reservoir_kg * fractions["C"],
        "CO": moles_per_kg["CO"] * MOLAR_MASS["CO"] * reservoir_kg * fractions["C"],
        "NH3": moles_per_kg["NH3"] * MOLAR_MASS["NH3"] * reservoir_kg * fractions["N"] * (0.2 if regime != "icy" else 0.0),
        "N2": (moles_per_kg["N2"] + moles_per_kg["NH3"] / 2.0 * (0.8 if regime != "icy" else 1.0))
        * MOLAR_MASS["N2"] * reservoir_kg * fractions["N"],
        "SO2": moles_per_kg["sulfate_S"] * MOLAR_MASS["SO2"] * reservoir_kg * fractions["S"],
        "H2S": moles_per_kg["H2S"] * MOLAR_MASS["H2S"] * reservoir_kg * fractions["S"],
        "H2": moles_per_kg["H2"] * MOLAR_MASS["H2"] * reservoir_kg * fractions["C"],
        "He": moles_per_kg["He"] * MOLAR_MASS["He"] * reservoir_kg * fractions["noble"],
        "Ne": moles_per_kg["Ne"] * MOLAR_MASS["Ne"] * reservoir_kg * fractions["noble"],
        "Ar": moles_per_kg["Ar"] * MOLAR_MASS["Ar"] * reservoir_kg * fractions["noble"],
    }

    # Thermal (Jeans) escape of light gases.
    escape_velocity = escape_velocity_m_s(physics.get("mass_kg"), physics.get("radius_m"))
    exobase_k = max(450.0, equilibrium_k * 2.8)
    retention = {}
    for key in list(available):
        factor, _ratio, _status = retention_factor(escape_velocity, exobase_k, {"molar_mass_kg_mol": MOLAR_MASS[key]})
        retention[key] = factor
        if key in GASES or key == "H2":
            available[key] *= factor
    fluence = max(0.0, float(stellar_luminosity_solar or 1.0)) / max(0.01, float(semi_major_axis_au or 1.0)) ** 2 * age_gyr
    nonthermal_retention = math.exp(
        -NONTHERMAL_ESCAPE_COEFFICIENT * fluence * math.exp(-((escape_velocity / NONTHERMAL_ESCAPE_VELOCITY_M_S) ** 2))
    )
    for key in NONTHERMAL_ESCAPE_SPECIES:
        if key in available:
            available[key] *= nonthermal_retention
    if regime != "icy":
        # Surface water cycles through the air and is photolysed; an ice-rich
        # crust is bedrock and stays.
        available["H2O"] *= nonthermal_retention
    # Energy-limited (XUV-driven) escape strips free hydrogen and drags helium:
    # dM = eps * pi * R^3 * F_xuv / (G * M) (Watson et al. 1981).
    xuv_fluence = (
        XUV_FLUENCE_1AU_J_M2
        * max(0.0, float(stellar_luminosity_solar or 1.0)) / max(0.01, float(semi_major_axis_au or 1.0)) ** 2
        * (0.75 + 0.25 * min(age_gyr, 10.0) / 4.5)
    )
    mass_kg = max(1.0, float(physics.get("mass_kg", 5.97e24) or 5.97e24))
    hydrogen_capacity_kg = ENERGY_LIMITED_EFFICIENCY * math.pi * radius_m ** 3 * xuv_fluence / (6.674e-11 * mass_kg)
    hydrogen_lost = min(available.get("H2", 0.0), hydrogen_capacity_kg)
    available["H2"] = available.get("H2", 0.0) - hydrogen_lost
    helium_lost = min(available.get("He", 0.0), 0.5 * (hydrogen_capacity_kg - hydrogen_lost))
    available["He"] = available.get("He", 0.0) - helium_lost
    has_atmosphere = sum(available.values()) * gravity / area / 1e5 > 1e-6 and escape_velocity > 1200.0

    def state_at(inventory, temperature, carbonate_branch):
        """Phases, sinks and the radiative target temperature at one surface temperature."""
        vapour, condensed = _partition(dict(inventory), temperature, gravity, area)
        water_ocean_m = condensed.get("H2O", 0.0) / CONDENSABLES["H2O"]["liquid_density"] / area
        low, high = OPEN_OCEAN_RAMP_K
        open_ocean = (
            min(1.0, max(0.0, (temperature - low) / (high - low)))
            if water_ocean_m >= MINIMUM_OCEAN_DEPTH_FOR_CARBONATES_M and temperature < 373.0
            else 0.0
        )
        wet = open_ocean >= 0.5
        locked = 0.0
        # Open water on rock forms carbonates whatever the tectonics (seafloor
        # weathering); tectonics only decides how much carbon comes back.
        if carbonate_branch and open_ocean > 0.0 and regime != "icy" and age_gyr >= 0.3:
            target_bar = (
                CARBONATE_REFERENCE_BAR
                * open_ocean ** (-1.0 / CARBONATE_WEATHERING_BETA)
                * math.exp(min(30.0, (CARBONATE_REFERENCE_K - temperature) / CARBONATE_SENSITIVITY_K))
            )
            target_bar = min(max(target_bar, 1e-6), CARBONATE_MAX_REGULATED_BAR)
            others = {key: value for key, value in vapour.items() if key != "CO2"}
            others_moles = sum(value / MOLAR_MASS[key] for key, value in others.items())
            keep = _vapour_mass_for_partial(target_bar, MOLAR_MASS["CO2"], others_moles, sum(others.values()), gravity, area)
            total_co2 = inventory.get("CO2", 0.0)
            if total_co2 > keep:
                # Carbonates take all the CO2 above the regulated level,
                # including any that would otherwise condense.
                locked = total_co2 - keep
                vapour["CO2"] = keep
                condensed["CO2"] = 0.0
        if wet:
            for key in ("SO2", "H2S"):
                vapour[key] = vapour.get(key, 0.0) * SULFUR_GAS_WET_REMOVAL
        elif temperature < SULFUR_GAS_PERSISTENCE_K:
            for key in ("SO2", "H2S"):
                vapour[key] = vapour.get(key, 0.0) * SULFUR_GAS_COLD_REMOVAL
        total = sum(vapour.values()) * gravity / area / 1e5
        moles = sum(value / MOLAR_MASS[key] for key, value in vapour.items() if value > 0.0)
        partial = {
            key: total * (value / MOLAR_MASS[key]) / moles if moles > 0.0 else 0.0
            for key, value in vapour.items()
        }
        tau = _optical_depth(partial, total) if has_atmosphere else 0.0
        return {"vapour": vapour, "condensed": condensed, "locked": locked, "partial": partial,
                "total": total, "tau": tau, "wet": wet, "open_ocean": open_ocean, "temperature": temperature,
                "target": equilibrium_k * (1.0 + 0.75 * tau) ** 0.25}

    def solve(inventory, carbonate_branch):
        """The first stable radiative equilibrium above the bare-rock temperature.

        The surface warms from its equilibrium temperature until the greenhouse
        target falls below the surface temperature; the crossing is refined by
        bisection.
        """
        low_state = state_at(inventory, equilibrium_k, carbonate_branch)
        if low_state["target"] <= equilibrium_k + 0.01:
            return low_state
        low = equilibrium_k
        high = None
        temperature = equilibrium_k
        while temperature < MAXIMUM_SURFACE_K:
            temperature = min(MAXIMUM_SURFACE_K, temperature * 1.03 + 0.5)
            if state_at(inventory, temperature, carbonate_branch)["target"] <= temperature:
                high = temperature
                break
            low = temperature
        if high is None:
            return state_at(inventory, MAXIMUM_SURFACE_K, carbonate_branch)
        for _iteration in range(30):
            if high - low < 0.02:
                break
            middle = 0.5 * (low + high)
            if state_at(inventory, middle, carbonate_branch)["target"] > middle:
                low = middle
            else:
                high = middle
        return state_at(inventory, 0.5 * (low + high), carbonate_branch)

    water_lost_fraction = 0.0
    # Runaway greenhouse: above the Simpson-Nakajima limit a wet planet cannot
    # radiate the absorbed starlight, its oceans stay steam and the hydrogen
    # escapes (Venus).  Below it the oceans condense early and draw CO2 into
    # carbonates (Earth), so the same inventory splits on stellar flux.
    absorbed_flux = STEFAN_BOLTZMANN * equilibrium_k ** 4
    steam_capable = available.get("H2O", 0.0) / area / CONDENSABLES["H2O"]["liquid_density"] >= MINIMUM_OCEAN_DEPTH_FOR_CARBONATES_M
    runaway = bool(steam_capable and has_atmosphere and absorbed_flux > RUNAWAY_GREENHOUSE_LIMIT_W_M2)
    if runaway:
        water_lost_fraction = 1.0 - math.exp(-age_gyr / STEAM_WATER_LOSS_GYR)
        available["H2O"] *= 1.0 - water_lost_fraction
        state = solve(available, carbonate_branch=False)
    else:
        state = solve(available, carbonate_branch=True)
        steam = state["partial"].get("H2O", 0.0) > 0.1 * max(state["total"], 1e-9) and state["temperature"] > 340.0
        if steam and available.get("H2O", 0.0) > 0.0:
            # A CO2 greenhouse hot enough to keep the oceans as steam loses
            # them the same way.
            runaway = True
            water_lost_fraction = 1.0 - math.exp(-age_gyr / STEAM_WATER_LOSS_GYR)
            available["H2O"] *= 1.0 - water_lost_fraction
            state = solve(available, carbonate_branch=False)
    vapour, condensed = state["vapour"], state["condensed"]
    carbonate_locked_kg = state["locked"]
    temperature = state["temperature"]
    tau = state["tau"]

    total_bar = sum(vapour.values()) * gravity / area / 1e5 if has_atmosphere else 0.0
    total_moles = sum(value / MOLAR_MASS[key] for key, value in vapour.items() if value > 0.0)
    composition = {
        key: (value / MOLAR_MASS[key]) / total_moles
        for key, value in vapour.items()
        if value > 0.0 and total_moles > 0.0 and has_atmosphere
    }
    # Abiotic oxygen stays trace; a biosphere stage owns Earth-like O2.
    if composition and speciation["redox_state"] == "oxidized" and condensed.get("H2O", 0.0) > 0.0:
        composition["O2"] = abiotic_oxygen(composition.get("H2O", 0.0), speciation)
        norm = sum(composition.values())
        composition = {key: value / norm for key, value in composition.items()}

    condensates = {}
    for key, mass in condensed.items():
        if mass <= 0.0 or key not in CONDENSABLES:
            continue
        data = CONDENSABLES[key]
        liquid = data["triple_k"] <= temperature < data["critical_k"] and total_bar >= data["triple_bar"]
        if key == "H2O" and state["wet"]:
            # Global mean a little below freezing still leaves open tropical seas.
            liquid = True
        density = data["liquid_density"] if liquid else data["solid_density"]
        condensates[key] = {
            "phase": "liquid" if liquid else "ice",
            "mass_kg": mass,
            "global_depth_m": mass / density / area,
        }
        if key == "H2O":
            condensates[key]["open_water_fraction"] = round(state["open_ocean"], 3)
    if regime == "icy":
        # The water of an ice-rich crust is its bedrock, not a surface layer.
        crust_ice = condensates.pop("H2O", None)
        ice_crust_depth = (crust_ice or {}).get("global_depth_m", 0.0)
    else:
        ice_crust_depth = 0.0
    liquids = {key: value for key, value in condensates.items() if value["phase"] == "liquid"}
    dominant = max(liquids.items(), key=lambda item: item[1]["global_depth_m"]) if liquids else None
    water = condensates.get("H2O", {})
    water_depth = water.get("global_depth_m", 0.0)
    water_index = min(1.0, max(0.0, (water_depth / 9000.0) ** (1.0 / 3.4))) if water_depth > 0.0 else 0.0
    # First-screen label: the preset whose nominal pressure is nearest
    # (geometric midpoints of 0.025 / 0.12 / 1 / 4 bar).
    if total_bar <= EXOSPHERE_BAR:
        inventory_label = "none"
    elif total_bar < 0.055:
        inventory_label = "dry"
    elif total_bar < 0.35:
        inventory_label = "thin"
    elif total_bar < 2.0:
        inventory_label = "earthlike"
    else:
        inventory_label = "dense"
    surface_fluid = LIQUID_NAMES[dominant[0]] if dominant else "water"
    frozen_ocean_depth = water_depth if water.get("phase") == "ice" else 0.0

    # Coldest surface (winter pole) from the same contrast scaling the climate
    # grid uses, and every volatile that can exist as ice somewhere: condensed
    # ices, freezing seas, frost in polar cold traps (Mars's CO2 caps), and
    # an icy crust's water.
    contrast = meridional_contrast_factor(total_bar, gravity / 9.80665, temperature)
    coldest_k = temperature - EARTH_LATITUDE_CONTRAST_K * contrast * (1.0 - LATITUDE_MEAN_ABS) - 14.0 * contrast
    ice_species = set()
    for key, value in condensates.items():
        if value["global_depth_m"] < MINIMUM_SURFACE_ICE_DEPTH_M:
            continue
        if value["phase"] == "ice" or coldest_k < CONDENSABLES[key]["triple_k"]:
            ice_species.add(key)
    for key, fraction in composition.items():
        if key in CONDENSABLES and fraction > 0.0 and total_bar > 0.0:
            if frost_point_k(key, total_bar * fraction) > coldest_k:
                ice_species.add(key)
    if regime == "icy" and ice_crust_depth > 0.0:
        ice_species.add("H2O")

    # Element mass held outside the rock (air, seas, surface ices), as percent
    # of the reservoir: the rock chemistry is the distribution minus this.
    envelope_moles = {}
    envelope_species = dict(vapour if has_atmosphere else {})
    for key, value in condensates.items():
        envelope_species[key] = envelope_species.get(key, 0.0) + value["mass_kg"]
    for key, mass in envelope_species.items():
        for symbol, count in SPECIES_ELEMENTS.get(key, {}).items():
            envelope_moles[symbol] = envelope_moles.get(symbol, 0.0) + mass / MOLAR_MASS[key] * count
    envelope_percent = {
        symbol: round(moles * AVOGADRO_MOLE_MASS[symbol] / 1000.0 / reservoir_kg * 100.0, 6)
        for symbol, moles in envelope_moles.items()
        if moles > 0.0
    }
    return {
        "model_version": VOLATILE_BUDGET_MODEL_VERSION,
        "source": "element_distribution",
        "input_key": budget_input_key(seed, stellar_luminosity_solar, semi_major_axis_au),
        "reservoir": {
            "mass_kg": reservoir_kg,
            "crust_thickness_km": crust_m / 1000.0,
            "density_kg_m3": round(density, 1),
            "water_mass_fraction": round(water_mass_fraction, 5),
            "ice_crust_equivalent_depth_m": round(ice_crust_depth, 1),
        },
        "speciation": speciation,
        "exchange_regime": regime,
        "equilibrium_temperature_k": equilibrium_k,
        "surface_temperature_k": temperature,
        "optical_depth": tau if has_atmosphere else 0.0,
        "surface_pressure_bar": total_bar,
        "composition": dict(sorted(composition.items(), key=lambda item: -item[1])),
        "partial_pressures_bar": {key: round(total_bar * value, 8) for key, value in composition.items()},
        "condensates": condensates,
        "surface_liquid": {
            "species": dominant[0] if dominant else None,
            "fluid": surface_fluid if dominant else None,
            "global_depth_m": dominant[1]["global_depth_m"] if dominant else 0.0,
        },
        "carbonate_locked_co2_kg": carbonate_locked_kg,
        "runaway_greenhouse": runaway,
        "water_lost_to_space_fraction": round(water_lost_fraction, 5),
        "retention": {key: round(value, 4) for key, value in retention.items()},
        "nonthermal_escape_retention": round(nonthermal_retention, 5),
        "envelope_element_percent": envelope_percent,
        "surface_gravity_g": round(gravity / 9.80665, 4),
        "coldest_surface_k": round(coldest_k, 2),
        "surface_ice_species": sorted(ice_species),
        "atmosphere_class": _atmosphere_class(composition, total_bar, temperature, runaway, dominant),
        "derived_seed": {
            "water_fraction": round(water_index, 4),
            "volatile_inventory": inventory_label,
            "surface_fluid": surface_fluid,
            "surface_liquid_depth_m": round(dominant[1]["global_depth_m"], 3) if dominant else 0.0,
            "frozen_ocean_depth_m": round(frozen_ocean_depth, 3),
        },
    }


def _atmosphere_class(composition, pressure_bar, temperature_k, runaway, dominant_liquid):
    """The descriptive class downstream stages key clouds and hazes on."""
    if pressure_bar <= EXOSPHERE_BAR or not composition:
        return "exosphere"
    main = max(composition.items(), key=lambda item: item[1])[0]
    methane = composition.get("CH4", 0.0)
    if main == "H2":
        return "hydrogen_ocean" if dominant_liquid and dominant_liquid[0] == "H2O" else "reducing_dense"
    if main == "CO2":
        if runaway or (pressure_bar >= 10.0 and temperature_k >= 500.0):
            return "runaway_co2"
        return "dry_co2"
    if main == "CH4" or methane >= 0.2:
        return "reducing_dense"
    if main == "N2":
        if methane >= 0.005 and temperature_k < 200.0:
            return "methane_nitrogen" if dominant_liquid else "frozen_methane_nitrogen"
        if dominant_liquid and dominant_liquid[0] == "H2O":
            return "temperate_nitrogen"
        if temperature_k < 240.0:
            return "cold_nitrogen"
        return "anoxic_nitrogen" if methane > 0.0 else "mixed_volcanic"
    if main == "H2O":
        return "steam_co2"
    return "mixed_volcanic"


# Nominal surface pressure (bar) of each first-screen volatile preset.
VOLATILE_PRESET_PRESSURE_BAR = {"none": 0.0, "dry": 0.025, "thin": 0.12, "earthlike": 1.0, "wet": 1.4, "dense": 4.0}
# Earth: 0.022 % N gives ~1 bar of N2; 0.32 % C is its carbonate rock.
EARTH_NITROGEN_PERCENT = 0.022
EARTH_CARBON_PERCENT = 0.32
# Without oceans to lock carbon in carbonates it all stays CO2: ~0.004 % C
# per bar on an Earth-sized body.
DRY_CARBON_PERCENT_PER_BAR = 0.004
OCEAN_WATER_INDEX = 0.3


def preset_volatile_elements(volatile_preset, water_index):
    """Carbon and nitrogen (mass %) for a template that leaves them unlisted.

    Nitrogen sets the background pressure of the preset.  Carbon is Earth's
    when the preset water forms oceans (carbonates take it); otherwise it is
    scaled so the CO2 that stays in the air matches the preset.
    """
    pressure = VOLATILE_PRESET_PRESSURE_BAR.get(str(volatile_preset or "earthlike").strip().lower(), 1.0)
    nitrogen = EARTH_NITROGEN_PERCENT * pressure
    if float(water_index or 0.0) >= OCEAN_WATER_INDEX and pressure > 0.0:
        carbon = EARTH_CARBON_PERCENT
    else:
        carbon = DRY_CARBON_PERCENT_PER_BAR * pressure
    return {"C": max(0.0001, carbon), "N": max(0.00005, nitrogen)}


# Area-weighted mean of |latitude| (as a fraction of 90 degrees) on a sphere:
# a profile T_s + C * (LATITUDE_MEAN_ABS - |lat|) averages exactly to T_s.
LATITUDE_MEAN_ABS = 1.0 - 2.0 / math.pi
EARTH_LATITUDE_CONTRAST_K = 48.0


def meridional_contrast_factor(pressure_bar, gravity_g, surface_temperature_k):
    """Equator-to-pole contrast relative to Earth's.

    A thick, cold atmosphere stores heat far longer than it radiates it
    (radiative time constant ~ c_p P / (g sigma T^3)), so it evens out the
    latitudes: Titan and Venus have small contrasts, thin Mars a large one.
    """
    pressure = max(1e-6, float(pressure_bar or 0.0))
    gravity = max(0.01, float(gravity_g or 1.0))
    temperature = max(20.0, float(surface_temperature_k or 288.0))
    ratio = pressure / gravity * (288.0 / temperature) ** 3
    return min(1.6, max(0.03, ratio ** -0.7))


def liquid_freezing_point_k(surface_fluid):
    """Freezing (triple) point of a surface liquid named by ``LIQUID_NAMES``."""
    fluid = str(surface_fluid or "water").strip().lower()
    if fluid == "brine":
        return 252.0  # NaCl eutectic
    for species, name in LIQUID_NAMES.items():
        if name == fluid:
            return CONDENSABLES[species]["triple_k"]
    if "methane" in fluid or "ethane" in fluid:
        return CONDENSABLES["CH4"]["triple_k"]
    if "magma" in fluid:
        return 1400.0
    return CONDENSABLES["H2O"]["triple_k"]


def oxygen_demand_percent(elements):
    """Oxygen (mass %) that fully oxidizes ``elements``: cation oxides (ferrous
    iron), water, CO2 and sulfate.  Its ratio to the actual oxygen is the
    inventory's redox intent, which a randomizer keeps while jittering the
    other elements."""
    from simulations.world_gen.material_chemistry import ATOMIC_MASS

    oxygen_moles = sum(
        float(elements.get(symbol, 0.0) or 0.0) / ATOMIC_MASS[symbol] * per_atom
        for symbol, per_atom in (*CATION_OXYGEN.items(), *NOBLE_CATION_OXYGEN.items())
        if symbol in ATOMIC_MASS
    )
    oxygen_moles += float(elements.get("H", 0.0) or 0.0) / ATOMIC_MASS["H"] / 2.0
    oxygen_moles += float(elements.get("C", 0.0) or 0.0) / ATOMIC_MASS["C"] * 2.0
    oxygen_moles += float(elements.get("S", 0.0) or 0.0) / ATOMIC_MASS["S"] * 3.0
    return oxygen_moles * ATOMIC_MASS["O"]


def hydrogen_percent_for_water_index(water_index, crust_thickness_km, density_kg_m3=ROCK_DENSITY):
    """Hydrogen (mass % of the reservoir) that yields a first-screen water index.

    Inverse of the budget's water accounting at Earth-like conditions: the
    rock binds ``ROCK_BOUND_WATER`` and the rest forms a global layer of depth
    9000 m x index^3.4 (the terrain seed's inventory curve).
    """
    index = max(0.0, min(1.0, float(water_index or 0.0)))
    crust_m = max(1000.0, float(crust_thickness_km or 35.0) * 1000.0)
    ocean_depth_m = 9000.0 * index ** 3.4
    water_fraction = ROCK_BOUND_WATER + ocean_depth_m * 1000.0 / (crust_m * density_kg_m3)
    return water_fraction * 2.0 * AVOGADRO_MOLE_MASS["H"] / (MOLAR_MASS["H2O"] * 1000.0) * 100.0


BUDGET_INPUT_FIELDS = (
    "radius_earth", "core_radius_fraction", "crust_thickness_km", "angular_velocity_deg_per_hour",
    "tectonics_mode", "system_age_gyr", "bond_albedo", "orbital_eccentricity", "eccentricity",
    "core_density_kg_m3", "mantle_density_kg_m3",
)


def budget_input_key(seed, stellar_luminosity_solar, semi_major_axis_au):
    """Fingerprint of everything the budget depends on."""
    import hashlib
    import json

    seed = seed if isinstance(seed, dict) else {}
    composition = seed.get("crust_composition") if isinstance(seed.get("crust_composition"), dict) else {}
    rows = [
        (str(row.get("symbol")), round(float(row.get("abundance_percent", 0.0) or 0.0), 6))
        for group in ("major_elements", "trace_elements")
        for row in composition.get(group) or []
        if isinstance(row, dict) and row.get("symbol")
    ]
    payload = {
        "model": VOLATILE_BUDGET_MODEL_VERSION,
        "elements": sorted(rows),
        "fields": {field: seed.get(field) for field in BUDGET_INPUT_FIELDS},
        "luminosity": round(float(stellar_luminosity_solar or 1.0), 8),
        "semi_major_axis_au": round(float(semi_major_axis_au or 1.0), 8),
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def budget_matches_inputs(budget, seed, stellar_luminosity_solar, semi_major_axis_au):
    return (
        isinstance(budget, dict)
        and budget.get("input_key") == budget_input_key(seed, stellar_luminosity_solar, semi_major_axis_au)
    )


def apply_volatile_budget_to_seed(seed, budget):
    """Write the budget's derived first-screen values into ``seed`` (in place).

    The seed then carries the derived water/volatile inputs, the budget, and
    on its crust composition the element share held in air, seas and surface
    ices (``volatile_envelope_percent``), which the material chemistry
    removes to get the rock composition.
    """
    budget = budget if isinstance(budget, dict) else {}
    seed.update(budget.get("derived_seed") or {})
    seed["volatile_budget"] = budget
    composition = seed.get("crust_composition")
    if isinstance(composition, dict):
        composition["volatile_envelope_percent"] = dict(budget.get("envelope_element_percent") or {})
    return seed


def budget_from(atmosphere=None, seed=None):
    """The volatile budget carried by an atmosphere model or a seed (rocky worlds)."""
    for source in (atmosphere, seed):
        budget = source.get("volatile_budget") if isinstance(source, dict) else None
        if isinstance(budget, dict) and budget.get("derived_seed") is not None:
            return budget
    return None
