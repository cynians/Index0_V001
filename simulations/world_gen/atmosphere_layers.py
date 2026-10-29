import math

from simulations.world_gen.atmosphere import GAS_CONSTANT, MOLECULES

EARTH_LAPSE_RATE_K_PER_KM = 6.5
EARTH_REFERENCE_SURFACE_TEMPERATURE_K = 288.15

# Each band: (name, top altitude in surface scale heights -- None for the
# final, unbounded band -- a temperature trend, and a short description).
# Altitude breakpoints are expressed in scale heights rather than fixed km so
# the same template scales sensibly across a thin Mars-like world and a dense
# Venus-like one.
BAND_TEMPLATES = {
    "full": (
        {"name": "troposphere", "top_scale_heights": 1.1, "temperature_trend": "lapse",
         "notes": "Well-mixed, weather-bearing layer; temperature falls with altitude."},
        {"name": "stratosphere", "top_scale_heights": 2.6, "temperature_trend": "inversion",
         "notes": "Radiative absorption warms this layer; strong vertical stratification suppresses mixing."},
        {"name": "mesosphere", "top_scale_heights": 4.2, "temperature_trend": "lapse",
         "notes": "Coldest layer; too thin for significant radiative absorption."},
        {"name": "thermosphere", "top_scale_heights": 8.0, "temperature_trend": "rise",
         "notes": "Direct stellar UV/X-ray heating; collisional but very low density."},
        {"name": "exosphere", "top_scale_heights": None, "temperature_trend": "isothermal",
         "notes": "Outermost, non-collisional envelope; particles can escape near the exobase temperature."},
    ),
    "thin": (
        {"name": "lower_atmosphere", "top_scale_heights": 2.0, "temperature_trend": "lapse",
         "notes": "Thin, weakly-mixed layer with a shallow temperature gradient."},
        {"name": "upper_atmosphere", "top_scale_heights": 5.0, "temperature_trend": "isothermal",
         "notes": "Diffuse, close to the exobase; increasingly non-collisional with altitude."},
        {"name": "exosphere", "top_scale_heights": None, "temperature_trend": "isothermal",
         "notes": "Outermost, non-collisional envelope."},
    ),
    "envelope": (
        {"name": "upper_envelope", "top_scale_heights": 1.5, "temperature_trend": "lapse",
         "notes": "Cloud-forming region near the modeled reference pressure level."},
        {"name": "deep_envelope", "top_scale_heights": 4.0, "temperature_trend": "rise",
         "notes": "Adiabatic compression heating with depth below the cloud deck."},
        {"name": "outer_envelope", "top_scale_heights": None, "temperature_trend": "isothermal",
         "notes": "Tenuous outer envelope approaching the exobase."},
    ),
}


def _clamp(value, low, high):
    return max(low, min(high, float(value)))


def _mixture_molar_mass_kg_mol(composition):
    total = sum(max(0.0, float(row.get("fraction", 0.0) or 0.0)) for row in composition)
    if total <= 0.0:
        return 0.02896  # dry-air-like fallback
    return sum(
        max(0.0, float(row.get("fraction", 0.0) or 0.0))
        * MOLECULES.get(row.get("molecule"), {}).get("molar_mass_kg_mol", 0.02896)
        for row in composition
    ) / total


def _gravity_at_altitude(surface_gravity_m_s2, planet_radius_m, altitude_m):
    radius_ratio = planet_radius_m / max(1.0, planet_radius_m + altitude_m)
    return surface_gravity_m_s2 * radius_ratio * radius_ratio


def _scale_height_m(temperature_k, molar_mass_kg_mol, gravity_m_s2):
    return (GAS_CONSTANT * max(1.0, temperature_k)) / max(1e-6, molar_mass_kg_mol * max(0.01, gravity_m_s2))


def _select_band_template(atmosphere_state, gas_giant):
    if gas_giant:
        return "envelope"
    if atmosphere_state in {"vacuum", "exosphere", "trace", "thin"}:
        return "thin"
    return "full"


def derive_atmosphere_layer_profile(atmosphere_model, physics, seed=None):
    """
    Break the single global-point atmosphere model into a vertical stack of
    named bands (troposphere/stratosphere/mesosphere/thermosphere/exosphere
    for a substantial rocky atmosphere; a collapsed profile for thin/trace
    atmospheres; an envelope-style profile for gas giants). Each band reports
    an altitude range, boundary pressure/temperature, mean density, a local
    scale height, and a composition breakdown.

    This is a barometric scale-height approximation of an already-derived
    global energy-balance atmosphere model, not an independent radiative or
    photochemical vertical simulation.
    """
    composition = [
        row for row in (atmosphere_model.get("composition") or [])
        if isinstance(row, dict) and row.get("molecule")
    ]
    surface_pressure_bar = max(0.0, float(atmosphere_model.get("surface_pressure_bar", 0.0) or 0.0))

    if surface_pressure_bar <= 0.0 or not composition:
        return {
            "bands": [],
            "band_template": None,
            "notes": ["No collisional atmosphere -- there is no vertical structure to model."],
        }

    surface_temperature_k = max(1.0, float(atmosphere_model.get("estimated_surface_temperature_k", EARTH_REFERENCE_SURFACE_TEMPERATURE_K) or EARTH_REFERENCE_SURFACE_TEMPERATURE_K))
    exobase_temperature_k = max(
        surface_temperature_k,
        float(atmosphere_model.get("exobase_temperature_k", surface_temperature_k) or surface_temperature_k),
    )
    atmosphere_state = atmosphere_model.get("atmosphere_state", "substantial")
    gas_giant = not atmosphere_model.get("has_solid_surface", True)

    planet_radius_m = max(1.0, float((physics or {}).get("radius_m", 6_371_000.0) or 6_371_000.0))
    surface_gravity_m_s2 = max(0.1, float((physics or {}).get("surface_gravity_m_s2", 9.80665) or 9.80665))
    molar_mass_kg_mol = _mixture_molar_mass_kg_mol(composition)
    surface_scale_height_m = _scale_height_m(surface_temperature_k, molar_mass_kg_mol, surface_gravity_m_s2)

    template_name = _select_band_template(atmosphere_state, gas_giant)
    template = BAND_TEMPLATES[template_name]

    retention_by_molecule = {
        row.get("molecule"): float(row.get("retention_factor", 1.0) or 0.0)
        for row in (atmosphere_model.get("retention") or [])
        if isinstance(row, dict)
    }

    bands = []
    base_altitude_m = 0.0
    base_pressure_bar = surface_pressure_bar
    base_temperature_k = surface_temperature_k
    lapse_scale = _clamp(surface_temperature_k / EARTH_REFERENCE_SURFACE_TEMPERATURE_K, 0.4, 2.5)

    for index, entry in enumerate(template):
        is_last = entry["top_scale_heights"] is None
        top_altitude_m = None if is_last else entry["top_scale_heights"] * surface_scale_height_m

        trend = entry["temperature_trend"]
        if trend == "lapse":
            span_km = max(0.0, (top_altitude_m - base_altitude_m)) / 1000.0
            top_temperature_k = max(60.0, base_temperature_k - EARTH_LAPSE_RATE_K_PER_KM * span_km * lapse_scale)
        elif trend == "inversion":
            top_temperature_k = min(exobase_temperature_k, base_temperature_k * 1.15)
        elif trend == "rise":
            top_temperature_k = exobase_temperature_k
        else:
            top_temperature_k = base_temperature_k

        mean_temperature_k = (base_temperature_k + top_temperature_k) / 2.0
        gravity_here = _gravity_at_altitude(surface_gravity_m_s2, planet_radius_m, base_altitude_m)
        local_scale_height_m = _scale_height_m(mean_temperature_k, molar_mass_kg_mol, gravity_here)

        if is_last:
            top_pressure_bar = 0.0
        else:
            thickness_m = max(0.0, top_altitude_m - base_altitude_m)
            top_pressure_bar = base_pressure_bar * math.exp(-thickness_m / max(1.0, local_scale_height_m))

        mean_pressure_bar = base_pressure_bar * 0.5 if is_last else (base_pressure_bar + top_pressure_bar) / 2.0
        density_kg_m3 = (
            mean_pressure_bar * 1e5 * molar_mass_kg_mol / (GAS_CONSTANT * max(1.0, mean_temperature_k))
            if mean_pressure_bar > 0.0 else 0.0
        )

        # Above the lower half of the stack, bias composition toward
        # whatever the escape/retention model already says survives best --
        # an illustrative diffusive-separation cue, not a rigorous transport
        # calculation.
        altitude_fraction = _clamp(index / max(1, len(template) - 1), 0.0, 1.0)
        weighted = []
        for row in composition:
            fraction = max(0.0, float(row.get("fraction", 0.0) or 0.0))
            if altitude_fraction >= 0.5:
                fraction *= _clamp(retention_by_molecule.get(row.get("molecule"), 1.0), 0.02, 1.0)
            if fraction > 0.0:
                weighted.append({"molecule": row["molecule"], "name": row.get("name", row["molecule"]), "fraction": fraction})
        band_total = sum(row["fraction"] for row in weighted) or 1.0
        band_composition = sorted(
            ({**row, "fraction": row["fraction"] / band_total} for row in weighted),
            key=lambda row: row["fraction"], reverse=True,
        )[:6]

        bands.append({
            "name": entry["name"],
            "base_altitude_km": base_altitude_m / 1000.0,
            "top_altitude_km": None if is_last else top_altitude_m / 1000.0,
            "base_pressure_bar": base_pressure_bar,
            "top_pressure_bar": top_pressure_bar,
            "base_temperature_k": base_temperature_k,
            "top_temperature_k": top_temperature_k,
            "density_kg_m3": density_kg_m3,
            "scale_height_km": local_scale_height_m / 1000.0,
            "temperature_trend": trend,
            "composition": band_composition,
            "notes": entry["notes"],
        })

        if is_last:
            break
        base_altitude_m = top_altitude_m
        base_pressure_bar = top_pressure_bar
        base_temperature_k = top_temperature_k

    return {
        "bands": bands,
        "band_template": template_name,
        "surface_scale_height_km": surface_scale_height_m / 1000.0,
        "mixture_molar_mass_kg_mol": molar_mass_kg_mol,
        "notes": [
            "Layer boundaries are a barometric scale-height approximation over the global "
            "single-point atmosphere model's pressure/temperature/composition, not an "
            "independent radiative or photochemical vertical simulation.",
        ],
    }
