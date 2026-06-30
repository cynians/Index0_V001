import math

from simulations.world_gen.planetary_physics import GRAVITATIONAL_CONSTANT


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
    "none": 0.01,
    "dry": 0.08,
    "thin": 0.25,
    "earthlike": 1.0,
    "wet": 1.4,
    "dense": 4.0,
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
        return {"CO2": 1.0}
    return {symbol: amount / total for symbol, amount in positive.items()}


def _is_gas_giant(seed, physics):
    radius_earth = max(0.0, float(physics.get("radius_earth", seed.get("radius_earth", 0.0)) or 0.0))
    mass_earth = max(0.0, float(physics.get("mass_earth", 0.0) or 0.0))
    explicit_kind = str(
        seed.get("planet_class")
        or seed.get("body_class")
        or seed.get("world_kind")
        or seed.get("planet_type")
        or ""
    ).strip().lower()
    if explicit_kind in {"gas_giant", "ice_giant", "jovian", "neptune", "sub_neptune"}:
        return True
    return radius_earth >= 3.0 or mass_earth >= 12.0


def _gas_giant_class(seed, physics, equilibrium_temp):
    radius_earth = max(0.0, float(physics.get("radius_earth", seed.get("radius_earth", 0.0)) or 0.0))
    mass_earth = max(0.0, float(physics.get("mass_earth", 0.0) or 0.0))
    explicit_kind = str(
        seed.get("planet_class")
        or seed.get("body_class")
        or seed.get("world_kind")
        or seed.get("planet_type")
        or ""
    ).strip().lower()
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
    if atmosphere_class == "ice_giant":
        return {
            "H2": 0.78,
            "He": 0.18,
            "CH4": 0.025,
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

    if atmosphere_class == "exosphere":
        return {
            "CO2": 0.36,
            "Ar": 0.22,
            "N2": 0.17,
            "SO2": 0.07,
            "CO": 0.06,
            "H2O": 0.04 * water_fraction,
            "He": 0.04,
            "H2": 0.03,
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
        "exosphere": 0.08,
        "dry_co2": 0.75,
        "frozen_methane_nitrogen": 0.55,
        "mixed_volcanic": 1.0,
        "temperate_nitrogen": 1.05,
        "steam_co2": 1.55,
        "reducing_dense": 1.35,
    }.get(atmosphere_class, 1.0)


def derive_atmosphere_model(seed, physics, stellar_luminosity_solar, semi_major_axis_au):
    equilibrium_temp = equilibrium_temperature_k(stellar_luminosity_solar, semi_major_axis_au)
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
    for symbol, amount in raw_mix.items():
        retained_amount = max(0.0, amount * retained.get(symbol, 0.0))
        if retained_amount > 0:
            adjusted[symbol] = retained_amount

    raw_total = sum(max(0.0, amount) for amount in raw_mix.values())
    total = sum(adjusted.values())
    if total <= 0:
        adjusted = {"CO2": 1.0}
        total = 1.0
    retained_column_fraction = total / raw_total if raw_total > 0 else 0.0
    if gas_giant:
        pressure_bar = max(100.0, volatile_supply_bar * retained_column_fraction)
    else:
        pressure_bar = max(
            0.000001,
            volatile_supply_bar
            * retained_column_fraction
            * surface_gravity_g
            * _atmosphere_pressure_multiplier(atmosphere_class),
        )

    composition = [
        {
            "molecule": symbol,
            "name": MOLECULES[symbol]["name"],
            "fraction": amount / total,
            "percent": (amount / total) * 100.0,
        }
        for symbol, amount in sorted(adjusted.items(), key=lambda item: item[1], reverse=True)
    ]

    co2_fraction = next((item["fraction"] for item in composition if item["molecule"] == "CO2"), 0.0)
    h2_fraction = next((item["fraction"] for item in composition if item["molecule"] == "H2"), 0.0)
    if gas_giant:
        greenhouse_k = min(260.0, 12.0 * math.log1p(max(0.0, pressure_bar)) + h2_fraction * 70.0)
    else:
        greenhouse_k = min(120.0, 18.0 * math.log1p(max(0.0, pressure_bar)) + co2_fraction * pressure_bar * 22.0)
    surface_temp = equilibrium_temp + greenhouse_k

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
        "has_solid_surface": not gas_giant,
        "equilibrium_temperature_k": equilibrium_temp,
        "estimated_surface_temperature_k": surface_temp,
        "greenhouse_delta_k": greenhouse_k,
        "exobase_temperature_k": exobase_temp,
        "escape_velocity_m_s": escape_velocity,
        "volatile_supply_bar": volatile_supply_bar,
        "retained_column_fraction": retained_column_fraction,
        "surface_pressure_bar": pressure_bar,
        "composition": composition,
        "retention": retention_rows,
        "notes": notes,
    }
