import math

from simulations.world_gen.planetary_physics import GRAVITATIONAL_CONSTANT


AU_M = 149_597_870_700.0
GAS_CONSTANT = 8.314462618


MOLECULES = {
    "H2": {"name": "Hydrogen", "molar_mass_kg_mol": 0.002016},
    "He": {"name": "Helium", "molar_mass_kg_mol": 0.004003},
    "H2O": {"name": "Water vapor", "molar_mass_kg_mol": 0.018015},
    "NH3": {"name": "Ammonia", "molar_mass_kg_mol": 0.017031},
    "CH4": {"name": "Methane", "molar_mass_kg_mol": 0.016043},
    "N2": {"name": "Nitrogen", "molar_mass_kg_mol": 0.028014},
    "O2": {"name": "Oxygen", "molar_mass_kg_mol": 0.031998},
    "CO2": {"name": "Carbon dioxide", "molar_mass_kg_mol": 0.04401},
    "Ar": {"name": "Argon", "molar_mass_kg_mol": 0.039948},
    "SO2": {"name": "Sulfur dioxide", "molar_mass_kg_mol": 0.064066},
}


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


def _base_outgassing_mix(seed, equilibrium_temp):
    water_fraction = max(0.0, min(1.0, float(seed.get("water_fraction", 0.5))))
    pressure = _volatile_pressure(seed)
    hot = equilibrium_temp > 330.0
    frozen = equilibrium_temp < 240.0

    h2o = 0.02 + water_fraction * (0.06 if not hot else 0.20)
    if frozen:
        h2o *= 0.1

    co2 = 0.12 if pressure <= 1.5 else 0.22
    if frozen and equilibrium_temp < 195.0:
        co2 *= 0.15

    return {
        "N2": 0.66,
        "CO2": co2,
        "Ar": 0.012,
        "H2O": h2o,
        "CH4": 0.008 if not hot else 0.002,
        "NH3": 0.004 if equilibrium_temp < 310.0 else 0.0,
        "O2": 0.001,
        "SO2": 0.004,
        "H2": 0.01,
        "He": 0.004,
    }


def derive_atmosphere_model(seed, physics, stellar_luminosity_solar, semi_major_axis_au):
    equilibrium_temp = equilibrium_temperature_k(stellar_luminosity_solar, semi_major_axis_au)
    exobase_temp = max(450.0, equilibrium_temp * 3.0)
    escape_velocity = escape_velocity_m_s(physics.get("mass_kg"), physics.get("radius_m"))
    volatile_supply_bar = _volatile_pressure(seed)

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

    raw_mix = _base_outgassing_mix(seed, equilibrium_temp)
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
    surface_gravity_g = max(0.03, float(physics.get("surface_gravity_g", 1.0) or 1.0))
    pressure_bar = max(0.0001, volatile_supply_bar * total * surface_gravity_g)

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
    greenhouse_k = min(80.0, 18.0 * math.log1p(max(0.0, pressure_bar)) + co2_fraction * pressure_bar * 22.0)
    surface_temp = equilibrium_temp + greenhouse_k

    return {
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
        "notes": [
            "O2 is kept trace by default; abundant oxygen should come from later biosphere or photochemistry stages.",
            "H2/He retention is usually poor unless gravity is high or temperature is low.",
            "Condensation is approximated for water and carbon dioxide.",
        ],
    }
