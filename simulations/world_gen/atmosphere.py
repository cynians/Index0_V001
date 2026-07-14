import math

from simulations.world_gen.planetary_physics import GRAVITATIONAL_CONSTANT
from simulations.world_gen.formation_theory import volatile_history_from_seed


AU_M = 149_597_870_700.0
GAS_CONSTANT = 8.314462618


MOLECULES = {
    "H2": {"name": "Hydrogen", "molar_mass_kg_mol": 0.002016},
    "He": {"name": "Helium", "molar_mass_kg_mol": 0.004003},
    "Ne": {"name": "Neon", "molar_mass_kg_mol": 0.020180},
    "H2O": {"name": "Water vapor", "molar_mass_kg_mol": 0.018015},
    "NH3": {"name": "Ammonia", "molar_mass_kg_mol": 0.017031},
    "CH4": {"name": "Methane", "molar_mass_kg_mol": 0.016043},
    "CO": {"name": "Carbon monoxide", "molar_mass_kg_mol": 0.028010},
    "N2": {"name": "Nitrogen", "molar_mass_kg_mol": 0.028014},
    "O2": {"name": "Oxygen", "molar_mass_kg_mol": 0.031998},
    "CO2": {"name": "Carbon dioxide", "molar_mass_kg_mol": 0.04401},
    "Ar": {"name": "Argon", "molar_mass_kg_mol": 0.039948},
    "SO2": {"name": "Sulfur dioxide", "molar_mass_kg_mol": 0.064066},
    "H2S": {"name": "Hydrogen sulfide", "molar_mass_kg_mol": 0.034081},
}

from simulations.world_gen.material_catalog import ATMOSPHERE_MOLECULES as MOLECULES


VOLATILE_PRESSURE_BAR = {
    "none": 0.0,
    "dry": 0.025,
    "thin": 0.12,
    "earthlike": 1.0,
    "wet": 1.4,
    "dense": 4.0,
}

EXPLICIT_AIRLESS_SURFACE_CLASSES = {
    "airless_rocky",
    "cratered_airless",
}


def equilibrium_temperature_k(luminosity_solar, semi_major_axis_au, bond_albedo=0.30):
    luminosity = max(0.0001, float(luminosity_solar or 1.0))
    orbit = max(0.01, float(semi_major_axis_au or 1.0))
    absorbed = max(0.01, 1.0 - float(bond_albedo))
    return 278.5 * (luminosity ** 0.25) * (absorbed ** 0.25) / math.sqrt(orbit)


def escape_velocity_m_s(mass_kg, radius_m):
    radius = max(1.0, float(radius_m or 1.0))
    mass = max(0.0, float(mass_kg or 0.0))
    return math.sqrt(2.0 * GRAVITATIONAL_CONSTANT * mass / radius)


def rms_speed_m_s(temperature_k, molar_mass_kg_mol):
    return math.sqrt(3.0 * GAS_CONSTANT * max(1.0, temperature_k) / molar_mass_kg_mol)


def retention_factor(escape_velocity, exobase_temperature_k, molecule):
    molecular_speed = rms_speed_m_s(exobase_temperature_k, molecule["molar_mass_kg_mol"])
    ratio = escape_velocity / molecular_speed if molecular_speed > 0 else 0.0
    if ratio >= 6.0:
        return 1.0, ratio, "stable"
    if ratio >= 3.0:
        return (ratio - 3.0) / 3.0, ratio, "leaky"
    return 0.0, ratio, "lost"


def _volatile_pressure(seed):
    inventory = str(seed.get("volatile_inventory") or "earthlike").strip().lower()
    return VOLATILE_PRESSURE_BAR.get(inventory, VOLATILE_PRESSURE_BAR["earthlike"])


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def _normalized_mix(raw_mix):
    positive = {
        symbol: max(0.0, float(amount or 0.0))
        for symbol, amount in raw_mix.items()
        if symbol in MOLECULES and max(0.0, float(amount or 0.0)) > 0.0
    }
    total = sum(positive.values())
    if total <= 0:
        return {}
    return {symbol: amount / total for symbol, amount in positive.items()}


MOLECULE_ELEMENTS = {
    "H": {"H": 1}, "H2": {"H": 2}, "He": {"He": 1}, "Ne": {"Ne": 1},
    "O": {"O": 1}, "Na": {"Na": 1}, "K": {"K": 1},
    "H2O": {"H": 2, "O": 1}, "NH3": {"N": 1, "H": 3},
    "CH4": {"C": 1, "H": 4}, "CO": {"C": 1, "O": 1},
    "N2": {"N": 2}, "O2": {"O": 2}, "CO2": {"C": 1, "O": 2},
    "Ar": {"Ar": 1}, "SO2": {"S": 1, "O": 2}, "H2S": {"H": 2, "S": 1},
}

ELEMENT_REFERENCE_PERCENT = {
    "H": 0.15, "He": 0.02, "C": 0.20, "N": 0.08, "O": 12.0,
    "Na": 0.30, "K": 0.10, "S": 0.20, "Ar": 0.005, "Ne": 0.002,
}


def _element_profile(seed):
    composition = seed.get("crust_composition") or {}
    profile = {}
    for group in ("major_elements", "trace_elements"):
        for row in composition.get(group, []) if isinstance(composition, dict) else []:
            symbol = str(row.get("symbol") or "").strip()
            if symbol:
                profile[symbol] = profile.get(symbol, 0.0) + max(0.0, float(row.get("abundance_percent", 0.0) or 0.0))
    if isinstance(composition, dict):
        reserve = max(0.0, float(composition.get("trace_reserve_percent", 0.0) or 0.0))
        # An unexpanded trace reserve represents volatile/noble elements that have
        # not been individually authored yet; it must not behave like zero abundance.
        for symbol, share in {"C": 0.20, "N": 0.12, "Ar": 0.01, "Ne": 0.002, "He": 0.005}.items():
            profile[symbol] = max(profile.get(symbol, 0.0), reserve * share)
        profile["H"] = max(profile.get("H", 0.0), reserve * 0.1 * _clamp(seed.get("water_fraction", 0.0), 0.0, 1.0))
    return profile


def _element_availability(symbol, profile):
    if not profile:
        return 1.0
    requirements = MOLECULE_ELEMENTS.get(symbol, {})
    if not requirements:
        return 1.0
    factors = []
    for element in requirements:
        reference = ELEMENT_REFERENCE_PERCENT.get(element, 0.05)
        factors.append(_clamp(profile.get(element, 0.0) / reference, 0.0, 1.0))
    return min(factors) if factors else 1.0


def _is_gas_giant(seed, physics):
    radius_earth = max(0.0, float(physics.get("radius_earth", seed.get("radius_earth", 0.0)) or 0.0))
    mass_earth = max(0.0, float(physics.get("mass_earth", 0.0) or 0.0))
    explicit_kind = str(
        seed.get("planet_class")
        or seed.get("planet_template")
        or seed.get("body_class")
        or seed.get("world_kind")
        or seed.get("planet_type")
        or ""
    ).strip().lower()
    if explicit_kind in EXPLICIT_AIRLESS_SURFACE_CLASSES or explicit_kind in {"hycean", "water_rich_super_earth"}:
        return False
    if explicit_kind in {"gas_giant", "ice_giant", "jovian", "neptune", "sub_neptune"}:
        return True
    return radius_earth >= 3.0 or mass_earth >= 12.0


def _gas_giant_class(seed, physics, equilibrium_temp):
    radius_earth = max(0.0, float(physics.get("radius_earth", seed.get("radius_earth", 0.0)) or 0.0))
    mass_earth = max(0.0, float(physics.get("mass_earth", 0.0) or 0.0))
    explicit_kind = str(
        seed.get("planet_class")
        or seed.get("planet_template")
        or seed.get("body_class")
        or seed.get("world_kind")
        or seed.get("planet_type")
        or ""
    ).strip().lower()
    requested = str(seed.get("atmosphere_regime") or "").strip().lower()
    if requested in {"hot_gas_giant", "hot_ice_giant"}:
        return requested
    if explicit_kind in {"ice_giant", "neptune", "sub_neptune"}:
        return "ice_giant"
    if radius_earth < 5.0 and mass_earth < 40.0:
        return "ice_giant"
    if equilibrium_temp >= 700.0:
        return "hot_gas_giant"
    return "gas_giant"


def _gas_giant_mix(atmosphere_class, equilibrium_temp):
    if atmosphere_class == "hot_gas_giant":
        return {
            "H2": 0.80,
            "He": 0.17,
            "CO": 0.014,
            "H2O": 0.008,
            "Ne": 0.003,
            "CH4": 0.002,
            "NH3": 0.001,
        }
    if atmosphere_class in {"ice_giant", "hot_ice_giant"}:
        hot = atmosphere_class == "hot_ice_giant"
        return {
            "H2": 0.78,
            "He": 0.18,
            "CH4": 0.006 if hot else 0.025,
            "CO": 0.018 if hot else 0.001,
            "NH3": 0.006,
            "H2O": 0.006,
            "H2S": 0.002,
            "Ne": 0.001,
        }
    methane = 0.006 if equilibrium_temp < 220.0 else 0.002
    ammonia = 0.003 if equilibrium_temp < 260.0 else 0.001
    return {
        "H2": 0.835,
        "He": 0.155,
        "CH4": methane,
        "NH3": ammonia,
        "H2O": 0.003,
        "Ne": 0.002,
        "H2S": 0.001,
    }


def _rocky_atmosphere_class(seed, equilibrium_temp, gravity_g):
    water_fraction = max(0.0, min(1.0, float(seed.get("water_fraction", 0.5))))
    inventory = str(seed.get("volatile_inventory") or "earthlike").strip().lower()
    pressure = _volatile_pressure(seed)
    radius_earth = max(0.01, float(seed.get("radius_earth", 1.0) or 1.0))

    requested = str(seed.get("atmosphere_regime") or "").strip().lower()
    if requested in {
        "runaway_co2", "oxygenated_nitrogen", "anoxic_nitrogen", "cold_nitrogen",
        "methane_nitrogen", "frozen_methane_nitrogen", "dry_co2",
        "mixed_volcanic", "rock_vapor", "hydrogen_ocean", "temperate_nitrogen",
    }:
        return requested

    if inventory == "none" or pressure <= 0.02 or radius_earth < 0.35 or gravity_g < 0.12:
        return "exosphere"
    if equilibrium_temp >= 340.0 and water_fraction >= 0.12:
        return "steam_co2"
    if equilibrium_temp <= 170.0:
        return "frozen_methane_nitrogen"
    if inventory in {"dry", "thin"} or water_fraction < 0.08:
        return "dry_co2"
    if inventory == "dense" and water_fraction < 0.35:
        return "reducing_dense"
    if 245.0 <= equilibrium_temp <= 315.0 and water_fraction >= 0.35 and inventory in {"earthlike", "wet"}:
        return "temperate_nitrogen"
    return "mixed_volcanic"


def _base_outgassing_mix(seed, equilibrium_temp, atmosphere_class):
    water_fraction = _clamp(seed.get("water_fraction", 0.5), 0.0, 1.0)

    if atmosphere_class == "runaway_co2":
        return {
            "CO2": 0.965,
            "N2": 0.034,
            "SO2": 0.00055,
            "Ar": 0.00025,
            "H2O": 0.00012,
            "CO": 0.00008,
        }
    if atmosphere_class == "oxygenated_nitrogen":
        return {
            "N2": 0.7808,
            "O2": 0.2094,
            "Ar": 0.0093,
            "CO2": 0.00042,
            "H2O": 0.012,
            "CH4": 0.000002,
        }
    if atmosphere_class in {"anoxic_nitrogen", "cold_nitrogen"}:
        return {"N2": 0.72, "CO2": 0.19, "H2O": 0.045, "CH4": 0.018, "Ar": 0.014, "H2": 0.008, "SO2": 0.005}
    if atmosphere_class == "methane_nitrogen":
        return {"N2": 0.91, "CH4": 0.065, "H2": 0.009, "Ar": 0.007, "CO": 0.005, "H2O": 0.001, "NH3": 0.003}
    if atmosphere_class == "hydrogen_ocean":
        return {"H2": 0.79, "He": 0.10, "H2O": 0.055, "CH4": 0.022, "N2": 0.018, "NH3": 0.009, "CO2": 0.006}
    if atmosphere_class == "rock_vapor":
        return {"Na": 0.35, "O": 0.25, "K": 0.12, "CO": 0.10, "SO2": 0.08, "O2": 0.05, "CO2": 0.05}

    if atmosphere_class == "exosphere":
        return {
            "O": 0.36,
            "Na": 0.25,
            "H": 0.16,
            "He": 0.12,
            "K": 0.07,
            "H2O": 0.025 * water_fraction,
            "Ar": 0.015,
        }
    if atmosphere_class == "steam_co2":
        return {
            "H2O": 0.36 + water_fraction * 0.24,
            "CO2": 0.28,
            "N2": 0.11,
            "SO2": 0.055,
            "CO": 0.035,
            "H2": 0.025,
            "H2S": 0.012,
            "Ar": 0.01,
            "He": 0.006,
        }
    if atmosphere_class == "frozen_methane_nitrogen":
        return {
            "N2": 0.38,
            "CH4": 0.24,
            "CO": 0.12,
            "Ar": 0.08,
            "CO2": 0.05,
            "NH3": 0.035,
            "H2": 0.035,
            "He": 0.018,
            "H2O": 0.006,
        }
    if atmosphere_class == "dry_co2":
        return {
            "CO2": 0.55,
            "N2": 0.22,
            "Ar": 0.085,
            "SO2": 0.045,
            "CO": 0.035,
            "H2O": 0.018 + water_fraction * 0.035,
            "H2": 0.018,
            "He": 0.009,
            "CH4": 0.006,
        }
    if atmosphere_class == "reducing_dense":
        return {
            "N2": 0.34,
            "CO2": 0.20,
            "CH4": 0.14,
            "NH3": 0.07,
            "H2": 0.065,
            "H2O": 0.055 + water_fraction * 0.06,
            "CO": 0.035,
            "H2S": 0.025,
            "Ar": 0.012,
            "He": 0.008,
        }
    if atmosphere_class == "temperate_nitrogen":
        oxygen = 0.012 if water_fraction < 0.65 else 0.035
        return {
            "N2": 0.58,
            "CO2": 0.16,
            "H2O": 0.065 + water_fraction * 0.07,
            "O2": oxygen,
            "Ar": 0.014,
            "CH4": 0.01,
            "NH3": 0.004,
            "SO2": 0.005,
            "H2": 0.006,
            "He": 0.003,
        }
    return {
        "N2": 0.42,
        "CO2": 0.27,
        "H2O": 0.045 + water_fraction * 0.09,
        "SO2": 0.045,
        "CH4": 0.035,
        "CO": 0.03,
        "H2S": 0.018,
        "Ar": 0.016,
        "NH3": 0.01 if equilibrium_temp < 310.0 else 0.003,
        "H2": 0.012,
        "He": 0.006,
        "O2": 0.001,
    }


def _atmosphere_pressure_multiplier(atmosphere_class):
    return {
        "exosphere": 0.0,
        "dry_co2": 0.75,
        "frozen_methane_nitrogen": 0.55,
        "mixed_volcanic": 1.0,
        "temperate_nitrogen": 1.05,
        "steam_co2": 1.55,
        "reducing_dense": 1.35,
        "runaway_co2": 1.55,
        "oxygenated_nitrogen": 1.0,
        "anoxic_nitrogen": 1.1,
        "cold_nitrogen": 0.8,
        "methane_nitrogen": 1.25,
        "hydrogen_ocean": 5.0,
        "rock_vapor": 0.12,
    }.get(atmosphere_class, 1.0)


def _atmosphere_state(pressure_bar, composition, atmosphere_class):
    if atmosphere_class == "exosphere" and composition:
        return "exosphere"
    if pressure_bar < 1e-12 or not composition:
        return "vacuum"
    if pressure_bar < 1e-4:
        return "trace"
    if pressure_bar < 0.1:
        return "thin"
    if pressure_bar < 10.0:
        return "substantial"
    if pressure_bar < 100.0:
        return "dense"
    return "massive"


def _greenhouse_model(composition, pressure_bar, gas_giant, atmosphere_state, greenhouse_efficiency=1.0):
    fractions = {row["molecule"]: row["fraction"] for row in composition}
    if atmosphere_state in {"vacuum", "exosphere"}:
        return {"delta_k": 0.0, "optical_strength": 0.0, "dominant_absorbers": []}
    weights = {"H2O": 1.45, "CO2": 1.0, "CH4": 2.6, "NH3": 2.0, "SO2": 0.75, "H2": 0.20}
    contributions = {gas: fractions.get(gas, 0.0) * weight for gas, weight in weights.items()}
    optical_strength = sum(contributions.values())
    pressure_term = math.log1p(max(0.0, pressure_bar) * (3.0 if gas_giant else 1.0))
    dense_pressure_broadening = _clamp((pressure_bar - 8.0) / 85.0, 0.0, 1.0)
    delta_k = pressure_term * (
        18.0
        + 38.0 * optical_strength
        + dense_pressure_broadening * (22.5 + 37.0 * fractions.get("CO2", 0.0))
    )
    delta_k *= _clamp(greenhouse_efficiency, 0.25, 4.0)
    delta_k = min(350.0 if gas_giant else 650.0, delta_k)
    dominant = [gas for gas, value in sorted(contributions.items(), key=lambda item: item[1], reverse=True) if value > 0.001][:3]
    return {"delta_k": delta_k, "optical_strength": optical_strength, "dominant_absorbers": dominant}


def _cloud_model(seed, composition, pressure_bar, atmosphere_class):
    fractions = {row["molecule"]: row["fraction"] for row in composition}
    sulfur_clouds = atmosphere_class == "runaway_co2" and fractions.get("SO2", 0.0) > 0.00001
    if sulfur_clouds:
        return {
            "cloud_class": "sulfuric_acid_aerosol_deck",
            "coverage_fraction": 0.995,
            "base_altitude_km": 45.0,
            "top_altitude_km": 70.0,
            "optical_depth": 28.0,
            "condensate": "H2SO4-H2O",
            "precipitation": "acid_virga",
            "surface_precipitation_reaches_ground": False,
            "condensate_cycle": "sulfuric_acid_cloud_cycle",
            "precipitation_fate": "evaporates_before_reaching_surface",
            "sulfur_cycle": "photochemical_cloud_cycle",
        }
    if atmosphere_class == "methane_nitrogen":
        return {
            "cloud_class": "methane_haze_and_clouds", "coverage_fraction": 0.72,
            "optical_depth": 4.5, "condensate": "CH4-C2H6",
            "condensate_cycle": "hydrocarbon_precipitation_cycle",
        }
    return {
        "cloud_class": "water_or_mixed_clouds" if fractions.get("H2O", 0.0) > 0.01 else "mostly_clear",
        "coverage_fraction": _clamp(fractions.get("H2O", 0.0) * pressure_bar * 0.8, 0.0, 0.9),
        "optical_depth": _clamp(fractions.get("H2O", 0.0) * pressure_bar * 2.0, 0.0, 12.0),
    }


def _circulation_model(seed, pressure_bar, cloud_model):
    rotation_hours = max(0.1, abs(float(seed.get("rotation_hours", seed.get("rotation_period_hours", 24.0)) or 24.0)))
    slow_rotation = _clamp(math.log1p(rotation_hours / 24.0) / 5.0, 0.0, 1.0)
    density_drive = _clamp(math.log1p(pressure_bar) / math.log(101.0), 0.0, 1.0)
    superrotation = 1.0 + slow_rotation * density_drive * 58.0
    if cloud_model.get("cloud_class") == "sulfuric_acid_aerosol_deck":
        superrotation = max(superrotation, 55.0)
    return {
        "circulation_class": "atmospheric_superrotation" if superrotation >= 8.0 else "planetary_bands_and_cells",
        "superrotation_factor": round(superrotation, 2),
        "cloud_top_wind_m_s": round(min(115.0, 18.0 + superrotation * 1.48), 1),
        "near_surface_wind_m_s": round(0.25 + density_drive * 0.55, 2),
        "vertical_stratification": "strong" if pressure_bar >= 10.0 else "moderate",
    }


def _visual_model(composition, pressure_bar, atmosphere_state, cloud_model=None):
    colors = {
        "H": (218, 210, 190), "H2": (218, 207, 178), "He": (224, 216, 195),
        "O": (172, 194, 214), "Na": (218, 176, 92), "K": (190, 132, 198),
        "N2": (145, 173, 207), "O2": (132, 173, 216), "CO2": (188, 156, 112),
        "H2O": (190, 215, 232), "CH4": (72, 151, 184), "SO2": (194, 174, 88),
        "NH3": (216, 204, 142), "Ar": (160, 156, 170), "CO": (176, 172, 164),
        "H2S": (154, 142, 82), "Ne": (190, 160, 178),
    }
    weighted = [(row["fraction"], colors.get(row["molecule"], (170, 180, 192))) for row in composition]
    total = sum(weight for weight, _color in weighted)
    tint = [170, 180, 192] if total <= 0 else [round(sum(weight * color[i] for weight, color in weighted) / total) for i in range(3)]
    if atmosphere_state in {"vacuum", "exosphere"}:
        opacity = 0.0
    else:
        opacity = _clamp(0.025 + 0.12 * math.log10(1.0 + pressure_bar * 10.0), 0.02, 0.58)
    if isinstance(cloud_model, dict) and cloud_model.get("cloud_class") == "sulfuric_acid_aerosol_deck":
        tint = [202, 166, 82]
        opacity = 0.56
    return {"tint_color": tint, "opacity": opacity, "visible": opacity > 0.005}


def derive_atmosphere_model(seed, physics, stellar_luminosity_solar, semi_major_axis_au):
    equilibrium_temp = equilibrium_temperature_k(
        stellar_luminosity_solar,
        semi_major_axis_au,
        bond_albedo=float(seed.get("bond_albedo", 0.30) or 0.30),
    )
    exobase_temp = max(450.0, equilibrium_temp * 3.0)
    escape_velocity = escape_velocity_m_s(physics.get("mass_kg"), physics.get("radius_m"))
    surface_gravity_g = max(0.03, float(physics.get("surface_gravity_g", 1.0) or 1.0))
    gas_giant = _is_gas_giant(seed, physics)
    atmosphere_class = (
        _gas_giant_class(seed, physics, equilibrium_temp)
        if gas_giant else _rocky_atmosphere_class(seed, equilibrium_temp, surface_gravity_g)
    )
    volatile_supply_bar = (
        max(100.0, surface_gravity_g * 120.0)
        if gas_giant else _volatile_pressure(seed)
    )

    retained = {}
    retention_rows = []
    for symbol, molecule in MOLECULES.items():
        factor, ratio, status = retention_factor(escape_velocity, exobase_temp, molecule)
        retained[symbol] = factor
        retention_rows.append({
            "molecule": symbol,
            "retention_factor": factor,
            "escape_speed_ratio": ratio,
            "status": status,
        })

    raw_mix = (
        _gas_giant_mix(atmosphere_class, equilibrium_temp)
        if gas_giant else _base_outgassing_mix(seed, equilibrium_temp, atmosphere_class)
    )
    raw_mix = _normalized_mix(raw_mix)
    adjusted = {}
    elemental_profile = _element_profile(seed)
    for symbol, amount in raw_mix.items():
        # A giant planet's envelope is not limited by the authored rocky-core
        # composition; its primordial hydrogen/helium inventory dominates.
        availability = 1.0 if gas_giant else _element_availability(symbol, elemental_profile)
        residence = retained.get(symbol, 0.0)
        if atmosphere_class == "exosphere":
            # Exospheres are continuously replenished by sputtering and solar wind;
            # short-lived atoms can therefore be present even when long-term retention is poor.
            residence = 0.45 + 0.55 * residence
            if symbol in {"H", "He"}:
                availability = 1.0
        retained_amount = max(0.0, amount * residence * availability)
        if retained_amount > 0:
            adjusted[symbol] = retained_amount

    raw_total = sum(max(0.0, amount) for amount in raw_mix.values())
    total = sum(adjusted.values())
    retained_column_fraction = total / raw_total if raw_total > 0 else 0.0
    volatile_history = volatile_history_from_seed(seed, retained_column_fraction=retained_column_fraction)
    source_total_bar = sum(float(volatile_history.get(field, 0.0) or 0.0) for field in (
        "primordial_volatiles_bar", "outgassed_volatiles_bar", "late_delivered_volatiles_bar",
        "terraforming_adjustment_bar",
    ))
    volatile_history_factor = _clamp(source_total_bar / max(0.02, volatile_supply_bar), 0.35, 2.5)
    if gas_giant:
        pressure_bar = max(100.0, volatile_supply_bar * retained_column_fraction)
    elif atmosphere_class == "exosphere" and adjusted:
        source_strength = _clamp(seed.get("exosphere_source_strength", 0.5), 0.0, 2.0)
        stellar_flux = max(0.02, float(stellar_luminosity_solar or 1.0)) / max(0.01, float(semi_major_axis_au or 1.0)) ** 2
        pressure_bar = 1e-14 * source_strength * min(20.0, stellar_flux) * max(0.05, retained_column_fraction)
    else:
        pressure_bar = max(0.0, volatile_supply_bar * volatile_history_factor * retained_column_fraction * surface_gravity_g * _atmosphere_pressure_multiplier(atmosphere_class))
        pressure_bar *= max(0.05, float(seed.get("volatile_pressure_scale", 1.0) or 1.0))

    composition = [
        {
            "molecule": symbol,
            "name": MOLECULES[symbol]["name"],
            "fraction": amount / total if total > 0 else 0.0,
            "percent": (amount / total) * 100.0 if total > 0 else 0.0,
        }
        for symbol, amount in sorted(adjusted.items(), key=lambda item: item[1], reverse=True)
    ]

    atmosphere_state = _atmosphere_state(pressure_bar, composition, atmosphere_class)
    greenhouse_model = _greenhouse_model(
        composition,
        pressure_bar,
        gas_giant,
        atmosphere_state,
        greenhouse_efficiency=seed.get("greenhouse_efficiency", 1.0),
    )
    greenhouse_k = greenhouse_model["delta_k"]
    surface_temp = equilibrium_temp + greenhouse_k
    cloud_model = _cloud_model(seed, composition, pressure_bar, atmosphere_class)
    circulation_model = _circulation_model(seed, pressure_bar, cloud_model)
    visual_model = _visual_model(composition, pressure_bar, atmosphere_state, cloud_model=cloud_model)

    notes = [
        "Atmosphere class is inferred from size, temperature, volatile inventory, gravity, and water fraction.",
        "O2 remains trace unless conditions imply a water-rich temperate atmosphere; later biosphere stages should own abundant oxygen.",
    ]
    if gas_giant:
        notes.extend([
            "Gas giant compositions use a hydrogen-helium envelope and report a deep reference pressure, not a solid surface pressure.",
            "Rocky terrain stages should treat this world as having no normal solid surface unless a later core/moon workflow says otherwise.",
        ])
    else:
        notes.extend([
            "H2/He retention is usually poor unless gravity is high or temperature is low.",
            "Condensation is approximated for water and carbon dioxide.",
        ])

    return {
        "atmosphere_class": atmosphere_class,
        "atmosphere_state": atmosphere_state,
        "has_collisional_atmosphere": atmosphere_state not in {"vacuum", "exosphere"},
        "has_exosphere": atmosphere_state == "exosphere",
        "has_solid_surface": not gas_giant,
        "equilibrium_temperature_k": equilibrium_temp,
        "equilibrium_temperature_c": equilibrium_temp - 273.15,
        "estimated_surface_temperature_k": surface_temp,
        "estimated_surface_temperature_c": surface_temp - 273.15,
        "greenhouse_delta_k": greenhouse_k,
        "greenhouse_model": greenhouse_model,
        "visual_model": visual_model,
        "cloud_model": cloud_model,
        "circulation_model": circulation_model,
        "exobase_temperature_k": exobase_temp,
        "exobase_temperature_c": exobase_temp - 273.15,
        "escape_velocity_m_s": escape_velocity,
        "volatile_supply_bar": volatile_supply_bar,
        "volatile_history": volatile_history,
        "volatile_history_factor": volatile_history_factor,
        "retained_column_fraction": retained_column_fraction,
        "surface_pressure_bar": pressure_bar,
        "composition": composition,
        "retention": retention_rows,
        "notes": notes,
    }
