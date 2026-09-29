import math

from simulations.world_gen.world_classification import infer_world_class, is_envelope_world

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


# Sputtered/solar-wind exosphere of an airless body (Moon, Mercury).
EXOSPHERE_MIX = {"O": 0.36, "Na": 0.25, "H": 0.16, "He": 0.12, "K": 0.07, "Ar": 0.015}


def equilibrium_temperature_k(luminosity_solar, semi_major_axis_au, bond_albedo=0.30, eccentricity=0.0):
    """Annual-mean radiative equilibrium temperature.

    The time-mean stellar flux of an eccentric Keplerian orbit is larger than
    the circular-orbit flux at the same semi-major axis by
    ``1 / sqrt(1 - e²)``.  The fourth-root temperature response makes the
    correction modest, but omitting it systematically cools eccentric worlds.
    """
    luminosity = max(0.0001, float(luminosity_solar or 1.0))
    orbit = max(0.01, float(semi_major_axis_au or 1.0))
    absorbed = max(0.01, 1.0 - float(bond_albedo))
    e = _clamp(eccentricity, 0.0, 0.85)
    annual_flux_factor = 1.0 / math.sqrt(max(1e-6, 1.0 - e * e))
    return 278.5 * (luminosity ** 0.25) * (absorbed ** 0.25) * (annual_flux_factor ** 0.25) / math.sqrt(orbit)


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


def _exosphere_mix(seed):
    water_fraction = _clamp(seed.get("water_fraction", 0.0), 0.0, 1.0)
    return {**EXOSPHERE_MIX, "H2O": 0.025 * water_fraction}


def _is_gas_giant(seed, physics):
    return is_envelope_world(seed, physics)


def _gas_giant_class(seed, physics, equilibrium_temp):
    radius_earth = max(0.0, float(physics.get("radius_earth", seed.get("radius_earth", 0.0)) or 0.0))
    mass_earth = max(0.0, float(physics.get("mass_earth", 0.0) or 0.0))
    explicit_kind = infer_world_class(seed, physics)
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
    co2_partial_pressure_bar = pressure_bar * fractions.get("CO2", 0.0)
    logarithmic_co2_forcing_k = 0.0
    if not gas_giant and 0.0 < pressure_bar < 12.0 and co2_partial_pressure_bar > 0.0004:
        # At terrestrial pressures, CO2 forcing grows approximately
        # logarithmically rather than linearly with mixing ratio.  This
        # conservative climate-sensitivity term prevents high-CO2 temperate
        # atmospheres from receiving less greenhouse warming than modern Earth.
        pressure_blend = (
            1.0
            if pressure_bar <= 4.0
            else _clamp((12.0 - pressure_bar) / 8.0, 0.0, 1.0)
        )
        logarithmic_co2_forcing_k = min(
            32.0,
            3.2 * math.log(co2_partial_pressure_bar / 0.0004),
        ) * pressure_blend
        delta_k += logarithmic_co2_forcing_k
    delta_k *= _clamp(greenhouse_efficiency, 0.25, 4.0)
    delta_k = min(350.0 if gas_giant else 650.0, delta_k)
    dominant = [gas for gas, value in sorted(contributions.items(), key=lambda item: item[1], reverse=True) if value > 0.001][:3]
    return {
        "delta_k": delta_k,
        "optical_strength": optical_strength,
        "dominant_absorbers": dominant,
        "co2_partial_pressure_bar": co2_partial_pressure_bar,
        "logarithmic_co2_forcing_k": logarithmic_co2_forcing_k,
    }


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
    if atmosphere_class in {"gas_giant", "ice_giant", "hot_gas_giant"}:
        methane_ammonia = fractions.get("CH4", 0.0) + fractions.get("NH3", 0.0)
        water = fractions.get("H2O", 0.0)
        if methane_ammonia >= 0.003:
            cloud_class = "methane_ammonia_cloud_deck"
            condensate = "CH4-NH3"
        elif water >= 0.001:
            cloud_class = "deep_water_cloud_deck"
            condensate = "H2O"
        else:
            cloud_class = "hydrogen_helium_haze"
            condensate = "photochemical_haze"
        return {
            "cloud_class": cloud_class,
            "coverage_fraction": _clamp(
                0.42 + math.log1p(max(0.0, pressure_bar)) * 0.10,
                0.42,
                0.98,
            ),
            "optical_depth": _clamp(
                (methane_ammonia * 85.0 + water * 45.0)
                * math.log1p(max(1.0, pressure_bar)),
                0.4,
                18.0,
            ),
            "condensate": condensate,
            "condensate_cycle": "giant_planet_cloud_circulation",
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
    elif isinstance(cloud_model, dict) and cloud_model.get("cloud_class") == "methane_haze_and_clouds":
        # Photochemical (tholin) haze: Titan is orange in visible light.
        tint = [196, 138, 58]
        opacity = max(opacity, 0.48)
    return {"tint_color": tint, "opacity": opacity, "visible": opacity > 0.005}


def element_volatile_budget(seed, physics, stellar_luminosity_solar, semi_major_axis_au):
    """The seed's volatile budget, reusing the one stored on it when it matches."""
    from simulations.world_gen.volatile_budget import budget_matches_inputs, derive_volatile_budget

    stored = seed.get("volatile_budget")
    if isinstance(stored, dict) and budget_matches_inputs(stored, seed, stellar_luminosity_solar, semi_major_axis_au):
        return stored
    return derive_volatile_budget(seed, physics, stellar_luminosity_solar, semi_major_axis_au)


def derive_atmosphere_model(seed, physics, stellar_luminosity_solar, semi_major_axis_au):
    orbital_eccentricity = _clamp(seed.get("orbital_eccentricity", seed.get("eccentricity", 0.0)), 0.0, 0.85)
    equilibrium_temp = equilibrium_temperature_k(
        stellar_luminosity_solar,
        semi_major_axis_au,
        bond_albedo=float(seed.get("bond_albedo", 0.30) or 0.30),
        eccentricity=orbital_eccentricity,
    )
    stellar_age_gyr = max(0.05, float(seed.get("system_age_gyr", 4.5) or 4.5))
    stellar_temperature_k = max(1800.0, float(seed.get("stellar_effective_temperature_k", 5772.0) or 5772.0))
    uv_xray_activity = _clamp(
        (0.75 / stellar_age_gyr) ** 0.72
        * (stellar_temperature_k / 5772.0) ** 2.2,
        0.08,
        8.0,
    )
    exobase_temp = max(450.0, equilibrium_temp * (2.55 + 0.45 * math.sqrt(uv_xray_activity)))
    escape_velocity = escape_velocity_m_s(physics.get("mass_kg"), physics.get("radius_m"))
    surface_gravity_g = max(0.03, float(physics.get("surface_gravity_g", 1.0) or 1.0))
    gas_giant = _is_gas_giant(seed, physics)
    # Rocky worlds: the element distribution decides the air through the
    # volatile budget; the class is only a label for clouds and hazes.
    budget = None if gas_giant else element_volatile_budget(seed, physics, stellar_luminosity_solar, semi_major_axis_au)
    atmosphere_class = _gas_giant_class(seed, physics, equilibrium_temp) if gas_giant else budget["atmosphere_class"]

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

    if gas_giant or atmosphere_class == "exosphere":
        raw_mix = _normalized_mix(
            _gas_giant_mix(atmosphere_class, equilibrium_temp) if gas_giant else _exosphere_mix(seed)
        )
        adjusted = {}
        for symbol, amount in raw_mix.items():
            residence = retained.get(symbol, 0.0)
            if not gas_giant:
                # Exospheres are continuously replenished by sputtering and
                # solar wind; short-lived atoms are present even when
                # long-term retention is poor.
                residence = 0.45 + 0.55 * residence
            retained_amount = max(0.0, amount * residence)
            if retained_amount > 0:
                adjusted[symbol] = retained_amount
        raw_total = sum(max(0.0, amount) for amount in raw_mix.values())
        total = sum(adjusted.values())
        retained_column_fraction = total / raw_total if raw_total > 0 else 0.0
        if gas_giant:
            volatile_supply_bar = max(100.0, surface_gravity_g * 120.0)
            pressure_bar = max(100.0, volatile_supply_bar * retained_column_fraction)
        else:
            volatile_supply_bar = 0.0
            source_strength = _clamp(seed.get("exosphere_source_strength", 0.5), 0.0, 2.0)
            stellar_flux = max(0.02, float(stellar_luminosity_solar or 1.0)) / max(0.01, float(semi_major_axis_au or 1.0)) ** 2
            pressure_bar = 1e-14 * source_strength * min(20.0, stellar_flux) * max(0.05, retained_column_fraction) if adjusted else 0.0
        composition = [
            {
                "molecule": symbol,
                "name": MOLECULES[symbol]["name"],
                "fraction": amount / total if total > 0 else 0.0,
                "percent": (amount / total) * 100.0 if total > 0 else 0.0,
            }
            for symbol, amount in sorted(adjusted.items(), key=lambda item: item[1], reverse=True)
        ]
    else:
        pressure_bar = float(budget["surface_pressure_bar"])
        volatile_supply_bar = pressure_bar
        retained_column_fraction = 1.0
        composition = [
            {
                "molecule": symbol,
                "name": MOLECULES.get(symbol, {}).get("name", symbol),
                "fraction": fraction,
                "percent": fraction * 100.0,
            }
            for symbol, fraction in budget["composition"].items()
            if fraction > 0.0
        ]
    volatile_history = volatile_history_from_seed(seed, retained_column_fraction=retained_column_fraction)
    redox_state = (budget or {}).get("speciation", {}).get("redox_state") if budget else None

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
    if budget is not None:
        surface_temp = float(budget["surface_temperature_k"])
        greenhouse_k = surface_temp - equilibrium_temp
        greenhouse_model = {
            **greenhouse_model,
            "delta_k": greenhouse_k,
            "method": "grey_two_stream_from_volatile_budget",
            "infrared_optical_depth": budget["optical_depth"],
        }
    periapsis_au = max(0.001, float(semi_major_axis_au or 1.0) * (1.0 - orbital_eccentricity))
    apoapsis_au = max(periapsis_au, float(semi_major_axis_au or 1.0) * (1.0 + orbital_eccentricity))
    circular_flux = max(0.0001, float(stellar_luminosity_solar or 1.0)) / max(0.01, float(semi_major_axis_au or 1.0)) ** 2
    periapsis_flux = max(0.0001, float(stellar_luminosity_solar or 1.0)) / periapsis_au ** 2
    apoapsis_flux = max(0.0001, float(stellar_luminosity_solar or 1.0)) / apoapsis_au ** 2
    cloud_model = _cloud_model(seed, composition, pressure_bar, atmosphere_class)
    circulation_model = _circulation_model(seed, pressure_bar, cloud_model)
    visual_model = _visual_model(composition, pressure_bar, atmosphere_state, cloud_model=cloud_model)
    rotation_hours = max(0.1, abs(float(physics.get("rotation_period_hours", 24.0) or 24.0)))
    core_fraction = _clamp(physics.get("core_radius_fraction", 0.0), 0.0, 0.95)
    magnetic_shielding_proxy = _clamp(
        core_fraction / 0.55 * (24.0 / rotation_hours) ** 0.28,
        0.0,
        1.5,
    )
    nonthermal_escape_pressure = uv_xray_activity * (1.0 - min(1.0, magnetic_shielding_proxy))
    water_fraction = _clamp(seed.get("water_fraction", 0.0), 0.0, 1.0)
    h2o_surface = "vapor"
    if surface_temp < 250.0:
        h2o_surface = "surface_ice_or_subsurface_liquid"
    elif surface_temp <= 373.15 and pressure_bar >= 0.006:
        h2o_surface = "liquid_and_vapor"
    elif surface_temp > 647.1 and pressure_bar > 220.6:
        h2o_surface = "supercritical"
    co2_surface = "gas"
    if surface_temp < 195.0:
        co2_surface = "polar_or_surface_ice"
    elif pressure_bar > 5.2 and surface_temp < 304.1:
        co2_surface = "gas_with_possible_condensed_reservoir"

    notes = [
        "Composition, pressure and temperature come from the element distribution's volatile budget; the class is a label.",
        "O2 remains trace (abiotic); later biosphere stages should own abundant oxygen.",
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

    model = {
        "climate_hierarchy": {
            "level": 0,
            "method": "global_energy_balance_with_parameterized_greenhouse_clouds_and_escape",
            "next_level": "latitude_or_spatial_climate_in_water_cycle_stage",
        },
        "atmosphere_class": atmosphere_class,
        "outgassing_redox_state": redox_state,
        "atmosphere_state": atmosphere_state,
        "has_collisional_atmosphere": atmosphere_state not in {"vacuum", "exosphere"},
        "has_exosphere": atmosphere_state == "exosphere",
        "has_solid_surface": not gas_giant,
        "equilibrium_temperature_k": equilibrium_temp,
        "equilibrium_temperature_c": equilibrium_temp - 273.15,
        "orbital_forcing": {
            "eccentricity": round(orbital_eccentricity, 5),
            "semi_major_axis_au": round(float(semi_major_axis_au or 1.0), 6),
            "periapsis_au": round(periapsis_au, 6),
            "apoapsis_au": round(apoapsis_au, 6),
            "annual_mean_flux_factor": round((1.0 - orbital_eccentricity * orbital_eccentricity) ** -0.5, 5),
            "periapsis_flux_factor": round(periapsis_flux / circular_flux, 4),
            "apoapsis_flux_factor": round(apoapsis_flux / circular_flux, 4),
            "annual_mean_temperature_corrected": orbital_eccentricity > 0.0,
        },
        "estimated_surface_temperature_k": surface_temp,
        "estimated_surface_temperature_c": surface_temp - 273.15,
        "greenhouse_delta_k": greenhouse_k,
        "greenhouse_model": greenhouse_model,
        "visual_model": visual_model,
        "cloud_model": cloud_model,
        "circulation_model": circulation_model,
        "exobase_temperature_k": exobase_temp,
        "exobase_temperature_c": exobase_temp - 273.15,
        "stellar_escape_forcing": {
            "stellar_age_gyr": round(stellar_age_gyr, 4),
            "effective_temperature_k": round(stellar_temperature_k, 1),
            "uv_xray_activity_relative_sun": round(uv_xray_activity, 3),
            "magnetic_shielding_proxy": round(magnetic_shielding_proxy, 3),
            "nonthermal_escape_pressure": round(nonthermal_escape_pressure, 3),
            "included_mechanisms": ["jeans_escape", "hydrodynamic_proxy", "nonthermal_magnetic_shielding_proxy", "volcanic_replenishment"],
        },
        "escape_velocity_m_s": escape_velocity,
        "volatile_supply_bar": volatile_supply_bar,
        "volatile_history": volatile_history,
        "retained_column_fraction": retained_column_fraction,
        "surface_pressure_bar": pressure_bar,
        "composition": composition,
        "retention": retention_rows,
        "volatile_phase_state": {
            "H2O": h2o_surface if water_fraction > 0.0 else "trace_or_absent",
            "CO2": co2_surface,
            "reservoirs_considered": ["atmosphere", "surface_liquid", "surface_ice", "subsurface", "mineral_bound"],
            "model_level": "global_pressure_temperature_screen",
        },
        "notes": notes,
    }
    if budget is not None:
        model["volatile_budget"] = budget
        condensates = budget.get("condensates") or {}
        water = condensates.get("H2O") or {}
        model["volatile_phase_state"].update({
            "H2O": (
                "liquid_and_vapor" if water.get("phase") == "liquid"
                else ("surface_ice_or_subsurface_liquid" if water else "trace_or_absent")
            ),
            "CO2": (
                "polar_or_surface_ice" if (condensates.get("CO2") or {}).get("phase") == "ice"
                else ("gas_with_possible_condensed_reservoir" if condensates.get("CO2") else "gas")
            ),
            "surface_liquid": budget.get("surface_liquid"),
            "condensates": {
                key: {"phase": value["phase"], "global_depth_m": round(value["global_depth_m"], 3)}
                for key, value in condensates.items()
            },
            "model_level": "element_volatile_budget",
        })
    return model
