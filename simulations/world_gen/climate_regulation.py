"""Long-timescale carbon–silicate climate-regulation diagnostic.

The map generator resolves a present-day climate snapshot.  Carbon cycling is
orders of magnitude slower, so this module deliberately reports a bounded
geological tendency instead of silently rewriting the atmosphere in a single
generation step.  It links volcanic degassing, liquid water, exposed land,
weathering, erosion/fresh-rock supply, and carbonate burial for downstream
materials and future time-advance simulation.
"""

import math


CLIMATE_REGULATION_MODEL_VERSION = "long-term-carbon-silicate-v1"


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _co2_partial_pressure_bar(atmosphere):
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    pressure = max(0.0, float(atmosphere.get("surface_pressure_bar", 0.0) or 0.0))
    for component in atmosphere.get("composition") or []:
        if isinstance(component, dict) and component.get("molecule") == "CO2":
            return pressure * max(0.0, float(component.get("fraction", 0.0) or 0.0))
    return 0.0


def derive_climate_regulation_model(planet, atmosphere, regime, water_cycle, surface_evolution):
    planet = planet if isinstance(planet, dict) else {}
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    regime = regime if isinstance(regime, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    surface_evolution = surface_evolution if isinstance(surface_evolution, dict) else {}
    interior = regime.get("interior") if isinstance(regime.get("interior"), dict) else {}
    surface = regime.get("surface_processes") if isinstance(regime.get("surface_processes"), dict) else {}
    summary = water_cycle.get("runoff_summary") if isinstance(water_cycle.get("runoff_summary"), dict) else {}
    means = surface_evolution.get("process_means") if isinstance(surface_evolution.get("process_means"), dict) else {}

    ocean_fraction = _clamp(summary.get("target_ocean_fraction", 0.0))
    land_fraction = 1.0 - ocean_fraction
    liquid_water = bool(water_cycle.get("liquid_water_possible"))
    pressure = max(0.0, float(atmosphere.get("surface_pressure_bar", 0.0) or 0.0))
    temperature = float(summary.get("mean_temperature_k", atmosphere.get("estimated_surface_temperature_k", 0.0)) or 0.0)
    co2_bar = _co2_partial_pressure_bar(atmosphere)
    runoff_mm = max(0.0, float(summary.get("mean_land_runoff_mm", 0.0) or 0.0))
    weathering = _clamp(float(means.get("weathering", 0.0) or 0.0))
    erosion = _clamp(float(means.get("erosion", 0.0) or 0.0))
    deposition = _clamp(float(means.get("deposition", 0.0) or 0.0))
    tectonics = str(interior.get("tectonic_regime") or "unknown")
    volcanism = str(interior.get("volcanic_activity") or "none")
    internal_heat = max(0.0, float(interior.get("internal_heat_w_m2", 0.0) or 0.0))

    tectonic_supply = {
        "plate_tectonics": 1.0,
        "mobile_lid": 0.92,
        "episodic_lid": 0.62,
        "plutonic_squishy_lid": 0.54,
        "heat_pipe": 0.78,
        "stagnant_lid": 0.24,
        "inactive": 0.04,
    }.get(tectonics, 0.18)
    volcanic_supply = {"high": 1.0, "moderate": 0.65, "low": 0.30, "none": 0.04}.get(volcanism, 0.18)
    degassing_index = _clamp((internal_heat / 0.12) * 0.48 + tectonic_supply * 0.30 + volcanic_supply * 0.22)
    runoff_factor = _clamp(math.log1p(runoff_mm / 100.0) / math.log(19.0))
    temperature_factor = _clamp(math.exp(-((temperature - 296.0) / 48.0) ** 2) + max(0.0, (temperature - 286.0) / 180.0) * 0.25)
    co2_acidity = _clamp(math.log1p(co2_bar / 0.0004) / math.log(501.0))
    fresh_rock_supply = _clamp(erosion * 0.58 + tectonic_supply * 0.42)
    kinetic_weathering = _clamp(runoff_factor * temperature_factor * (0.32 + co2_acidity * 0.68))
    weathering_index = _clamp(
        kinetic_weathering * (0.34 + fresh_rock_supply * 0.66) * (0.35 + weathering * 0.65) * land_fraction
    ) if liquid_water else 0.0
    carbonate_burial_index = _clamp(weathering_index * (0.35 + ocean_fraction * 0.65) * (0.45 + deposition * 0.55))

    if not liquid_water or land_fraction < 0.025:
        weathering_regime = "inactive_or_supply_limited"
    elif fresh_rock_supply < 0.18:
        weathering_regime = "supply_limited"
    else:
        weathering_regime = "kinetically_coupled"
    imbalance = degassing_index - carbonate_burial_index
    if abs(imbalance) < 0.10 and weathering_regime == "kinetically_coupled":
        tendency = "approximately_regulated"
    elif imbalance > 0.10:
        tendency = "net_co2_outgassing"
    else:
        tendency = "net_co2_drawdown"

    return {
        "status": "climate_regulation_diagnosed",
        "model_version": CLIMATE_REGULATION_MODEL_VERSION,
        "timescale": "10^5_to_10^7_year_geological_tendency",
        "not_a_single_step_atmosphere_override": True,
        "inputs": {
            "co2_partial_pressure_bar": round(co2_bar, 7),
            "liquid_water": liquid_water,
            "ocean_fraction": round(ocean_fraction, 3),
            "land_fraction": round(land_fraction, 3),
            "mean_land_runoff_mm": round(runoff_mm, 1),
            "mean_temperature_k": round(temperature, 1),
            "tectonic_regime": tectonics,
        },
        "indices": {
            "degassing": round(degassing_index, 4),
            "fresh_rock_supply": round(fresh_rock_supply, 4),
            "silicate_weathering": round(weathering_index, 4),
            "carbonate_burial": round(carbonate_burial_index, 4),
        },
        "weathering_regime": weathering_regime,
        "carbon_balance_tendency": tendency,
        "carbonate_province_favorable": bool(liquid_water and carbonate_burial_index >= 0.12),
        "climate_stabilizing_feedback": bool(weathering_regime == "kinetically_coupled" and liquid_water),
    }

