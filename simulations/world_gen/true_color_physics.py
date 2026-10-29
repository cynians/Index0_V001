"""Physical controls on a planet's true-colour appearance.

Every term here is a function of the planet's physical state -- element
inventory, atmosphere (pressure, composition, redox), temperature, water,
stellar flux and time -- never of a planet type.  Terraforming that changes
the state (thicker air, oxygen, water, a warmer climate, removing methane)
therefore changes the colour through the same relationships.

Surface alteration (applied to the material-mixed land reflectance):

* **Ferric staining** -- ferrous iron oxidizes to nanophase hematite /
  goethite.  Needs iron, an oxidizing inventory and time; proceeds by wet
  chemical weathering (Arrhenius in temperature, scaled by precipitation)
  and by slow dry photo-oxidation under UV (Mars).  Arid/warm conditions
  favour red hematite, wet/cool ones yellow-brown goethite.  Colours come
  from the ontology's hematite and goethite optical cards.
* **Dust mantle** -- the finest, most altered particles are lifted where the
  surface is dry and an atmosphere can carry them, and settle in low-slope
  sinks; they homogenise a dry world's colour (Mars).  Wind sweeps it off
  where gusts exceed the saltation threshold, which depends on air density
  (so on elevation): bright dusty uplands, dark swept lowlands.
* **Space weathering** -- on airless bodies solar-wind and micrometeorite
  products (nanophase iron) darken and redden exposed regolith with age.
* **Organic haze fallout** -- methane photolysis under UV makes tholin haze
  (when CH4/CO2 > ~0.1) that settles as dark, reddish-brown sediment (Titan).

Atmosphere (applied to the final image in linear light):

* **Rayleigh scattering** per channel from the gas column (P / g / mean
  molar mass) and the gases' polarizability, relative to Earth's
  ~0.20 / 0.11 / 0.06 optical depth at 460 / 540 / 620 nm.
* **Aerosols** -- photochemical haze and lifted dust, each with a spectral
  single-scattering albedo (both absorb blue: orange Titan, butterscotch
  Mars).  Condensate cloud decks are not drawn (as for Earth's water
  clouds); their scattering would hide the surface.

Seen from orbit at nadir, the surface is attenuated two ways, exp(-2 tau),
and the column adds its own path reflectance.  Thick columns (Venus, Titan)
would hide the surface completely; ``MAP_SURFACE_VISIBILITY_FLOOR`` keeps a
fraction of the surface legible on the map -- the one cartographic
concession in the model.
"""

from __future__ import annotations

import math

import numpy as np

# Effective wavelengths (um) of the red, green and blue channels.
CHANNEL_WAVELENGTH_UM = (0.62, 0.54, 0.46)
# Earth's Rayleigh optical depth (dry air, 1013 hPa): tau ~ 0.0088 lambda^-4.05.
EARTH_RAYLEIGH_TAU = tuple(0.0088 * wavelength ** -4.05 for wavelength in CHANNEL_WAVELENGTH_UM)
EARTH_COLUMN = 1.01325 / (1.0 * 28.97)  # bar / (g x g/mol)
# Rayleigh cross-section per molecule relative to N2 (Sneep & Ubachs 2005;
# Bates 1984): CO2 ~2.5x, CH4 ~2.2x, Ar ~0.9x, H2 ~0.2x.
RAYLEIGH_RELATIVE_CROSS_SECTION = {
    "N2": 1.0, "O2": 0.86, "Ar": 0.90, "CO2": 2.50, "CH4": 2.20, "H2O": 0.73, "H2": 0.21,
    "He": 0.015, "Ne": 0.037, "NH3": 1.90, "CO": 1.15, "SO2": 4.0, "H2S": 2.9,
}
MOLAR_MASS_G = {
    "N2": 28.01, "O2": 32.0, "Ar": 39.95, "CO2": 44.01, "CH4": 16.04, "H2O": 18.02, "H2": 2.016,
    "He": 4.003, "Ne": 20.18, "NH3": 17.03, "CO": 28.01, "SO2": 64.07, "H2S": 34.08,
}

# Aerosol spectral single-scattering albedo (R, G, B) and asymmetry.
# Titan tholin haze absorbs blue strongly (Tomasko et al. 2008); Martian
# dust likewise (Pollack et al. 1995).
HAZE_SSA = (0.94, 0.78, 0.55)
DUST_SSA = (0.97, 0.87, 0.66)
# Asymmetry parameters: both aerosols scatter mostly forward, so diffuse
# light still reaches the surface (delta scaling tau' = tau (1 - omega g)).
HAZE_ASYMMETRY = 0.6
DUST_ASYMMETRY = 0.65
# Permanent sulfuric-acid cloud deck (Venus): nearly conservative, with a
# blue/UV absorber that makes the planet pale yellow (visual albedo ~0.7).
SULFURIC_DECK_SSA = (0.998, 0.992, 0.95)
SULFURIC_DECK_ASYMMETRY = 0.72
# Tholin sediment reflectance (linear R, G, B): dark reddish brown.
THOLIN_REFLECTANCE = (0.115, 0.062, 0.028)
# Space-weathering spectral response of fully mature regolith (R, G, B):
# darkened, reddened (lunar maturity trend).
SPACE_WEATHERING_FILTER = (0.80, 0.70, 0.58)
# Fallback ferric reflectances if the ontology cards are missing (R, G, B).
HEMATITE_FALLBACK = (0.32, 0.075, 0.04)
GOETHITE_FALLBACK = (0.34, 0.17, 0.055)

# Staining a fully altered rock with ~1.0 iron factor reaches (tint strength;
# Martian dust, the most altered material, reaches ~0.8 via the dust term).
FERRIC_PIGMENT_CAPACITY = 0.75
# Most pigment the finest dust carries (Martian dust: red/blue ~3-4).
DUST_MAX_PIGMENT = 0.78
NANOPHASE_FILTER_EXPONENT = 0.65
# Fine-powder brightening r_fine = r ** exponent (basalt 0.075 -> ~0.19).
FINE_GRAIN_EXPONENT = 0.62
# Chemical weathering activation energy (silicate dissolution ~50-80 kJ/mol).
WEATHERING_ACTIVATION_J_MOL = 60_000.0
GAS_CONSTANT = 8.314462618
# Fraction of the surface that stays legible under a thick column (see module docstring).
MAP_SURFACE_VISIBILITY_FLOOR = 0.3

# --- near-surface wind and saltation --------------------------------------
STEFAN_BOLTZMANN = 5.670374e-8
# Neutral 10 m drag coefficient over ~1 cm roughness: (0.4 / ln(1000))^2.
SURFACE_DRAG_COEFFICIENT = 0.0034
# Kinetic-energy generation per absorbed stellar flux when the circulation
# carries the heat (Earth's heat engine: ~2 of 240 W m^-2).
CIRCULATION_EFFICIENCY = 0.025
# Time for the circulation to carry heat across a planetary-scale eddy
# (~6 days).  A column that radiates its heat away faster (thin air, Mars)
# drives weaker winds than its flux alone suggests.
ADVECTIVE_TIME_S = 5.0e5
# The most easily lifted sand grain (~100 um) and its density.
SALTATION_GRAIN_M = 1.0e-4
GRAIN_DENSITY_KG_M3 = 2650.0
# Shao & Lu (2000) threshold: u*_t^2 = A (rho_p/rho_a g d + gamma/(rho_a d)).
SHAO_LU_A = 0.0123
SHAO_LU_GAMMA_N_M = 3.0e-4
# Ground is kept swept where upper-quartile winds (1.33x the mean for a
# Rayleigh distribution) reach the threshold: (u*/u*_t)^2 >= 1/1.33^2.
SWEEPING_MOBILITY = 1.0 / 1.33 ** 2
# --- weathering in physical time -----------------------------------------
# Ferric pigment grows at a rate (1/yr) while a grain sits at the surface,
# for a residence time H / E set by erosion.  Wet chemical weathering of
# fully moist ground at 288 K: ~30 kyr (laterites form in 10^4-10^5 yr);
# dry UV photo-oxidation at full UV and vapour: ~200 Myr (Mars, with a
# tenth of that vapour, rusts only because its surface is billions of
# years old).
WET_WEATHERING_RATE_PER_YR = 3.0e-5
DRY_OXIDATION_RATE_PER_YR = 5.0e-9
# Mixing depth of the weathering zone and denudation rates: fluvial
# erosion ~0.02 mm/yr for 300 mm/yr runoff on low relief, growing with
# runoff and slope (mountains ~0.1-1 mm/yr); without runoff, wind and
# impact gardening only (~1e-10 m/yr, Mars since the Hesperian).
REGOLITH_MIXING_DEPTH_M = 1.0
FLUVIAL_DENUDATION_M_PER_YR = 2.0e-5
DRY_DENUDATION_M_PER_YR = 1.0e-10
# Saltating sand abrades its own coatings on fully swept, loose ground (1/yr);
# negligible against wet weathering, decisive against Mars's dry oxidation.
SAND_ABRASION_RATE_PER_YR = 3.0e-9


def near_surface_wind(pressure_bar, gravity_g, mean_molar_g, surface_temperature_k, equilibrium_k, absorbed_flux_w_m2):
    """Typical near-surface wind (m/s), air density and radiative time.

    Dissipation balance: surface drag rho C_D U^3 consumes the kinetic energy
    the heat engine makes, efficiency x absorbed flux x the share of heat the
    circulation carries before the column radiates it away (Earth ~9 m/s,
    Mars ~5-10, Titan ~1).
    """
    pressure_pa = max(0.0, pressure_bar) * 1.0e5
    molar_kg = max(1e-3, mean_molar_g / 1000.0)
    air_density = pressure_pa * molar_kg / (GAS_CONSTANT * max(20.0, surface_temperature_k))
    if air_density <= 1e-7:
        return 0.0, air_density, 0.0
    heat_capacity = 3.5 * GAS_CONSTANT / molar_kg
    radiative_time = heat_capacity * pressure_pa / (9.80665 * max(0.01, gravity_g)) / (
        4.0 * STEFAN_BOLTZMANN * max(20.0, equilibrium_k) ** 3
    )
    dynamic_share = radiative_time / (radiative_time + ADVECTIVE_TIME_S)
    wind = (CIRCULATION_EFFICIENCY * dynamic_share * max(0.0, absorbed_flux_w_m2)
            / (air_density * SURFACE_DRAG_COEFFICIENT)) ** (1.0 / 3.0)
    return float(min(60.0, wind)), air_density, radiative_time


def saltation_mobility(wind_m_s, air_density, gravity_g):
    """(u* / u*_t)^2: >1 sand saltates under the mean wind, <<1 only in rare gusts."""
    if air_density <= 1e-7 or wind_m_s <= 0.0:
        return 0.0
    friction = math.sqrt(SURFACE_DRAG_COEFFICIENT) * wind_m_s
    threshold_sq = SHAO_LU_A * (
        GRAIN_DENSITY_KG_M3 / air_density * 9.80665 * max(0.01, gravity_g) * SALTATION_GRAIN_M
        + SHAO_LU_GAMMA_N_M / (air_density * SALTATION_GRAIN_M)
    )
    return float(friction * friction / threshold_sq)


def _regional_mean(values, radius):
    """Box mean over +-radius pixels, wrapping in longitude."""
    values = np.asarray(values, dtype=np.float64)
    radius = max(1, int(radius))
    padded = np.concatenate([values[:, -radius:], values, values[:, :radius]], axis=1)
    cumulative = np.cumsum(np.pad(padded, ((0, 0), (1, 0))), axis=1)
    horizontal = (cumulative[:, 2 * radius + 1:] - cumulative[:, :-2 * radius - 1]) / (2 * radius + 1)
    padded = np.pad(horizontal, ((radius, radius), (0, 0)), mode="edge")
    cumulative = np.cumsum(np.pad(padded, ((1, 0), (0, 0))), axis=0)
    return ((cumulative[2 * radius + 1:] - cumulative[:-2 * radius - 1]) / (2 * radius + 1)).astype(np.float32)


def _ssa(values):
    return np.asarray(values, dtype=np.float32)


def _reflectance(material_id, fallback):
    try:
        from simulations.world_gen.material_optics import material_optical_surface_profile

        profile = material_optical_surface_profile(material_id) or {}
        reflectance = profile.get("visible_reflectance") or {}
        values = (reflectance.get("red_650nm"), reflectance.get("green_550nm"), reflectance.get("blue_450nm"))
        if all(value is not None for value in values):
            return tuple(float(value) for value in values)
    except Exception:
        pass
    return tuple(fallback)


def appearance_environment(atmosphere, seed=None, natural_material_model=None):
    """Planet-level optical/chemical state from the atmosphere and inventory."""
    atmosphere = atmosphere if isinstance(atmosphere, dict) else {}
    seed = seed if isinstance(seed, dict) else {}
    natural_material_model = natural_material_model if isinstance(natural_material_model, dict) else {}
    budget = atmosphere.get("volatile_budget") if isinstance(atmosphere.get("volatile_budget"), dict) else {}
    pressure = max(0.0, float(atmosphere.get("surface_pressure_bar", budget.get("surface_pressure_bar", 0.0)) or 0.0))
    gravity = float(budget.get("surface_gravity_g")
                    or (seed.get("derived_planet_physics") or {}).get("surface_gravity_g") or 1.0)
    composition = {
        str(row.get("molecule")): float(row.get("fraction", 0.0) or 0.0)
        for row in atmosphere.get("composition") or []
        if isinstance(row, dict) and row.get("molecule")
    } or {str(key): float(value) for key, value in (budget.get("composition") or {}).items()}
    total = sum(composition.values()) or 1.0
    composition = {key: value / total for key, value in composition.items()}
    mean_molar = sum(MOLAR_MASS_G.get(key, 28.97) * value for key, value in composition.items()) or 28.97
    column = pressure / max(0.01, gravity) / mean_molar
    column_relative = column / EARTH_COLUMN
    cross_section = sum(RAYLEIGH_RELATIVE_CROSS_SECTION.get(key, 1.0) * value for key, value in composition.items()) or 1.0
    rayleigh_tau = [tau * column_relative * cross_section for tau in EARTH_RAYLEIGH_TAU]

    equilibrium_k = float(atmosphere.get("equilibrium_temperature_k", 255.0) or 255.0)
    stellar_flux = (equilibrium_k / 254.6) ** 4  # relative to Earth (Bond albedo 0.3)
    age_gyr = max(0.05, float(seed.get("system_age_gyr", 4.5) or 4.5))

    redox = str((budget.get("speciation") or {}).get("redox_state") or "")
    if composition.get("O2", 0.0) >= 0.01 or redox == "oxidized":
        oxidant = 1.0
    elif redox == "intermediate":
        oxidant = 0.35
    elif redox == "reducing":
        oxidant = 0.0
    else:
        oxidant = 0.6
    elements = natural_material_model.get("element_profile") or {}
    iron_percent = float(elements.get("Fe", 5.0) or 5.0)
    # Ferric pigment supply: soils carry a few percent iron oxide (Earth
    # crust 5 % Fe -> ~0.6), Mars's 14 % saturates.
    iron_factor = float(np.clip(iron_percent / 8.0, 0.2, 1.4))
    surface_temperature = float(atmosphere.get("estimated_surface_temperature_k", 288.0) or 288.0)
    # Element pigments (copper's weathering minerals and the like) read the
    # air's O2 and CO2 and the planet's chloride against the reference crust.
    from simulations.world_gen.element_pigments import pigment_systems
    from simulations.world_gen.natural_materials import reference_element_distribution

    try:
        reference_chlorine = float(reference_element_distribution().get("Cl", 0.0) or 0.0)
    except Exception:
        reference_chlorine = 0.0
    chloride_ratio = float(elements.get("Cl", reference_chlorine) or 0.0) / reference_chlorine if reference_chlorine > 0.0 else 1.0
    carbon_dioxide_bar = pressure * composition.get("CO2", 0.0)

    # Dry photo-oxidation: UV reaching the surface (thick columns absorb it)
    # making oxidants from trace water vapour.
    uv_transmission = math.exp(-column_relative / 4.0)
    water_vapour_bar = pressure * composition.get("H2O", 0.0)
    vapour_factor = min(1.0, water_vapour_bar / 1e-5)
    photo_oxidation = stellar_flux * uv_transmission * vapour_factor

    # Photochemical haze: methane photolysis under UV, when CH4/CO2 > ~0.1
    # (Trainer et al. 2006); Titan (p_CH4 ~0.07 bar, 1 % of Earth's flux)
    # has a visible optical depth of a few.
    methane_bar = pressure * composition.get("CH4", 0.0)
    carbon_dioxide = composition.get("CO2", 0.0)
    haze_allowed = composition.get("CH4", 0.0) >= 1e-3 and (carbon_dioxide <= 0.0 or composition["CH4"] / carbon_dioxide > 0.1)
    haze_tau = (
        float(np.clip(3.0 * math.sqrt(methane_bar / 0.066) * math.sqrt(stellar_flux / 0.011), 0.0, 8.0))
        if haze_allowed and pressure > 1e-3 else 0.0
    )

    # Permanent global cloud decks are part of the planet's appearance
    # (transient water-weather clouds are not drawn).
    cloud_model = atmosphere.get("cloud_model") if isinstance(atmosphere.get("cloud_model"), dict) else {}
    deck_tau = (
        float(cloud_model.get("optical_depth", 0.0) or 0.0)
        if str(cloud_model.get("cloud_class") or "") == "sulfuric_acid_aerosol_deck" else 0.0
    )

    # Solar-wind and micrometeorite weathering where no atmosphere stops them.
    airless = math.exp(-pressure / 1e-7)
    # Atmospheric scale height H = R T / (M g): wind stress falls with the
    # air density exp(-z / H), so dust survives on high plains.
    scale_height_m = GAS_CONSTANT * surface_temperature / (mean_molar / 1000.0 * 9.80665 * max(0.01, gravity))
    wind, air_density, radiative_time = near_surface_wind(
        pressure, gravity, mean_molar, surface_temperature, equilibrium_k, 240.0 * stellar_flux,
    )

    return {
        "pressure_bar": pressure,
        "gravity_g": gravity,
        "column_relative_to_earth": column_relative,
        "rayleigh_tau_rgb": [round(value, 5) for value in rayleigh_tau],
        "stellar_flux_relative": stellar_flux,
        "age_gyr": age_gyr,
        "oxidant": oxidant,
        "iron_percent": iron_percent,
        "iron_factor": iron_factor,
        "photo_oxidation": photo_oxidation,
        "haze_tau": haze_tau,
        "sulfuric_deck_tau": deck_tau,
        "airless": airless,
        "scale_height_m": scale_height_m,
        "air_density_kg_m3": air_density,
        "surface_wind_m_s": wind,
        "radiative_time_s": radiative_time,
        "saltation_mobility": saltation_mobility(wind, air_density, gravity),
        "ice_is_bedrock": str(budget.get("exchange_regime") or "") == "icy",
        "water_ice_rgb": _reflectance("mat_water_ice", (0.78, 0.86, 0.92)),
        "hematite_rgb": _reflectance("mat_hematite", HEMATITE_FALLBACK),
        "goethite_rgb": _reflectance("mat_goethite", GOETHITE_FALLBACK),
        "o2_relative": pressure * composition.get("O2", 0.0) / 0.21,
        "log_pco2_bar": math.log10(max(carbon_dioxide_bar, 1e-9)),
        "chloride_ratio": chloride_ratio,
        "element_pigments": pigment_systems(natural_material_model),
    }


def _arrhenius(temperature_k):
    temperature = np.clip(np.asarray(temperature_k, dtype=np.float32), 60.0, 700.0)
    return np.exp(-WEATHERING_ACTIVATION_J_MOL / GAS_CONSTANT * (1.0 / temperature - 1.0 / 288.0))


def weathering_slope(gradient):
    """Steepness index (0..1) from the surface gradient (m/m): loose sediment and dust shed between ~11 and ~31 degrees."""
    return np.clip((np.asarray(gradient, dtype=np.float32) - 0.2) / 0.4, 0.0, 1.0)


def residence_years(env, age, runoff_mm, gradient):
    """Residence time of a grain in the weathering zone (years).

    Erosion renews Earth's surface every 10^3-10^6 yr (fluvial denudation
    growing with runoff and slope); a dry world keeps it for its whole age.
    ``age`` is the relative surface age (0..1) of the exposure fields.
    """
    surface_age_yr = np.asarray(age, dtype=np.float32) * env["age_gyr"] * 1.0e9
    denudation = (
        FLUVIAL_DENUDATION_M_PER_YR * np.sqrt(np.maximum(np.asarray(runoff_mm, dtype=np.float32), 0.0) / 300.0)
        * (1.0 + np.asarray(gradient, dtype=np.float32) / 0.003)
        + DRY_DENUDATION_M_PER_YR
    )
    return np.minimum(surface_age_yr, REGOLITH_MIXING_DEPTH_M / denudation)


def alter_surface(linear_rgb, env, fields, land):
    """Apply ferric staining, dust, space weathering and organic fallout.

    ``linear_rgb``: H x W x 3 linear reflectance.  ``fields`` holds H x W
    arrays: temperature_k, wetness, aridity, weathering, age, deposition,
    slope, bedrock (missing ones default).  ``land``: boolean mask of land
    (ocean and ice are drawn over later).  Returns (rgb, diagnostics).
    """
    shape = linear_rgb.shape[:2]

    def field(name, default):
        value = fields.get(name)
        return np.asarray(value, dtype=np.float32) if value is not None else np.full(shape, default, dtype=np.float32)

    temperature = field("temperature_k", 288.0)
    wetness = field("wetness", 0.0)
    aridity = field("aridity", 1.0)
    runoff_mm = np.maximum(field("runoff_mm", 0.0), 0.0)
    age = field("age", 0.55)
    deposition = field("deposition", 0.0)
    bedrock = field("bedrock", 0.35)
    # Steepness from the true surface gradient (m/m): loose sediment and dust
    # shed between ~11 and ~31 degrees.  Falls back to the exposure slope
    # index, which saturates on rough terrain at planetary scale.
    gradient = fields.get("gradient")
    if gradient is not None:
        gradient = np.asarray(gradient, dtype=np.float32)
        slope = weathering_slope(gradient)
    else:
        gradient = np.zeros(shape, dtype=np.float32)
        slope = field("slope", 0.1)
    residence_yr = residence_years(env, age, runoff_mm, gradient)
    rgb = np.asarray(linear_rgb, dtype=np.float32).copy()

    # 1. Organic haze fallout (tholin sediment) accumulates for the planet's
    # age (Titan: hundreds of metres) and buries the bedrock; only steep,
    # eroding slopes stay partly clean.
    burial = 1.0 - np.exp(-env["haze_tau"] * min(env["age_gyr"], 4.5) / 3.0)
    organic = burial * (0.85 + 0.15 * aridity) * (1.0 - 0.25 * slope * slope)
    organic = np.clip(organic, 0.0, 0.97)[..., None]
    rgb = rgb * (1.0 - organic) + np.asarray(THOLIN_REFLECTANCE, dtype=np.float32) * organic
    # Dust is ground from whatever covers the surface now (rock, or organics).
    dust_source = rgb.copy()

    # Wind sweeps the ground where gusts saltate sand.  The threshold falls
    # as air density rises, exp(-z/H) with elevation (regional terrain, not
    # single crater floors), so dust is kept on high plains and stripped
    # from lowlands.  retention = share of time/area the ground stays calm.
    mobility = np.full(shape, float(env.get("saltation_mobility", 0.0) or 0.0), dtype=np.float32)
    elevation = fields.get("elevation_m")
    if elevation is not None and env.get("scale_height_m"):
        elevation = np.asarray(elevation, dtype=np.float32)
        regional = _regional_mean(elevation, elevation.shape[1] / 96.0)
        reference = float(np.median(regional[land])) if land.any() else 0.0
        mobility = mobility * np.exp(-(regional - reference) / float(env["scale_height_m"]))
    retention = 1.0 / (1.0 + (mobility / SWEEPING_MOBILITY) ** 2)

    # 2. Ferric staining, in physical time.
    # Wet chemical weathering is set by climate (moisture x Arrhenius in
    # temperature); fresh bedrock kept exposed by erosion stays less altered.
    # Over a grain's residence time this reddens the humid tropics, browns
    # temperate ground and leaves tundra and cold deserts grey.
    wet_rate = WET_WEATHERING_RATE_PER_YR * wetness * np.minimum(3.0, _arrhenius(temperature)) * (1.0 - 0.6 * bedrock)
    dry_rate = DRY_OXIDATION_RATE_PER_YR * env["photo_oxidation"] * aridity
    growth = wet_rate + dry_rate
    # Saltating loose sand abrades its own coatings, so they settle at
    # growth / (growth + abrasion): Mars's swept dark sand stays little
    # altered, Earth's wet weathering outpaces it.
    abrasion = SAND_ABRASION_RATE_PER_YR * (1.0 - retention) * aridity * (1.0 - bedrock)
    # Degree of alteration (0 fresh .. 1 equilibrium) times the pigment a
    # fully altered rock can hold: soils are a few percent iron oxide, so
    # staining tints rather than replaces the rock colour.
    alteration = growth / np.maximum(growth + abrasion, 1e-30) * (1.0 - np.exp(-(growth + abrasion) * residence_yr))
    # Pigment supply follows each rock's own iron (basalt ~8 wt%, limestone
    # ~0.3 %), scaled so the land's mean matches the planet's crust.
    iron_factor = np.full(shape, float(env["iron_factor"]), dtype=np.float32)
    iron = fields.get("iron_wt_percent")
    if iron is not None:
        iron = np.asarray(iron, dtype=np.float32)
        known = land & np.isfinite(iron)
        if known.any():
            mean_iron = max(0.05, float(iron[known].mean()))
            iron_factor = np.clip(
                env["iron_factor"] * np.where(np.isfinite(iron), iron, mean_iron) / mean_iron, 0.02, 2.0,
            ).astype(np.float32)
    ferric = env["oxidant"] * iron_factor * FERRIC_PIGMENT_CAPACITY * alteration
    ferric = np.clip(ferric * (1.0 - 0.45 * bedrock * slope), 0.0, 0.9)
    # Goethite (yellow-brown) precipitates from water in cool, moist soils;
    # warmth and dry seasons dehydrate it to hematite (red), and dry
    # photo-oxidation makes only nanophase hematite (Schwertmann).
    wet_share = wet_rate / np.maximum(growth, 1e-30)
    goethite_preference = np.clip(0.5 - 0.03 * (temperature - 288.0), 0.1, 0.9) * (1.0 - 0.6 * aridity)
    hematite_share = np.clip(1.0 - wet_share * goethite_preference, 0.05, 1.0)[..., None]
    stain = hematite_share * np.asarray(env["hematite_rgb"], dtype=np.float32) + (1.0 - hematite_share) * np.asarray(env["goethite_rgb"], dtype=np.float32)
    # Nanophase ferric oxide has a softer absorption edge than crystalline
    # hematite (Morris et al.), so the tint filter is flattened.
    stain_filter = (stain / np.maximum(1e-6, stain.max(axis=-1, keepdims=True))) ** NANOPHASE_FILTER_EXPONENT
    f = ferric[..., None]
    rgb = rgb * (1.0 - f + f * stain_filter) + f * 0.35 * stain

    # (Element minerals -- copper's hosts and the weathering minerals over
    # them -- are materials of the rock map, ``element_pigments.surface_minerals``
    # via ``material_lod``: the mix above already holds them.)

    # 3. Space weathering (airless regolith darkens and reddens with age).
    maturity = env["airless"] * (1.0 - np.exp(-env["stellar_flux_relative"] * env["age_gyr"] * age * 0.8))
    maturity = np.clip(maturity * (1.0 - 0.5 * slope), 0.0, 1.0)[..., None]
    rgb = rgb * (1.0 - maturity * (1.0 - np.asarray(SPACE_WEATHERING_FILTER, dtype=np.float32)))

    # 4. Dust mantle: the planet's finest, most altered particles, lifted
    # where it is dry and air can carry them, settling on low slopes.
    carrier = (1.0 - math.exp(-env["pressure_bar"] / 0.002)) * min(1.6, env["gravity_g"] ** -0.5)
    dry_land = land & (aridity > 0.6)
    dust_supply = carrier * (float(dry_land.mean()) if dry_land.any() else 0.0)
    if dust_supply > 0.0 and dry_land.any():
        # Dust is the finest, fully altered material: the dry land's mean
        # cover, brighter for its small grains (grinding shortens the
        # absorbing path per scattering event: fine powders of dark rock are
        # several times brighter), at full ferric staining.
        base = np.power(np.clip(dust_source[dry_land].mean(axis=0), 1e-4, 1.0), FINE_GRAIN_EXPONENT)
        dust_ferric = min(DUST_MAX_PIGMENT, env["oxidant"] * env["iron_factor"] * FERRIC_PIGMENT_CAPACITY * 1.45)
        dust_filter = stain_filter[dry_land].mean(axis=0)
        dust_stain = stain[dry_land].mean(axis=0)
        dust_rgb = np.clip(base * (1.0 - dust_ferric + dust_ferric * dust_filter) + dust_ferric * 0.35 * dust_stain, 0.0, 0.9)
        # Dust settles where the ground stays calm; sheltered sinks keep some.
        dust = min(1.0, dust_supply) * aridity * np.clip(retention + deposition * 1.5, 0.0, 1.0) * (1.0 - 0.6 * slope * slope)
        dust = np.clip(dust, 0.0, 0.92)[..., None]
        rgb = rgb * (1.0 - dust) + dust_rgb * dust
    else:
        dust = np.zeros(shape + (1,), dtype=np.float32)
    rgb = np.where(land[..., None], rgb, linear_rgb)
    # Share of each pixel under a loose mantle (organics, dust): the bare
    # rock's texture (fractures, scarps, grain) shows only through the rest.
    mantle_cover = np.where(land, 1.0 - (1.0 - organic[..., 0]) * (1.0 - dust[..., 0]), 0.0).astype(np.float32)
    return rgb, {
        "mantle_cover": mantle_cover,
        "mantle_cover_mean": float(mantle_cover[land].mean()) if land.any() else 0.0,
        "dust_retention_mean": float(retention[land].mean()) if land.any() else 0.0,
        "ferric_mean": float(ferric[land].mean()) if land.any() else 0.0,
        "dust_mean": float(dust[..., 0][land].mean()) if land.any() else 0.0,
        "space_weathering_mean": float(maturity[..., 0][land].mean()) if land.any() else 0.0,
        "organic_mean": float(organic[..., 0][land].mean()) if land.any() else 0.0,
        "dust_supply": dust_supply,
        "saltation_mobility": float(env.get("saltation_mobility", 0.0) or 0.0),
        "alteration_mean": float(alteration[land].mean()) if land.any() else 0.0,
        "residence_kyr_median": float(np.median(residence_yr[land]) / 1000.0) if land.any() else 0.0,
        "dry_land_fraction": float(dry_land.mean()) if dry_land.size else 0.0,
        # Share of the disc that rains out dust: seas plus wet land.
        "wet_fraction": float(np.where(land, wetness, 1.0).mean()),
    }


def direct_illumination_share(env, dust_tau=0.0, sun_mu=0.62):
    """Share of the surface's (green) irradiance that arrives as direct sunlight.

    Relief is shaded by the direct beam; scattered skylight lights slopes
    almost evenly.  Aerosols are delta-scaled (their forward peak keeps the
    beam's direction).  Earth ~0.9, dusty Mars ~0.75, Titan's haze ~0.2,
    under Venus's deck ~0, airless 1.
    """
    rayleigh = float(env["rayleigh_tau_rgb"][1])
    haze = float(env.get("haze_tau", 0.0) or 0.0) * (1.0 - HAZE_SSA[1] * HAZE_ASYMMETRY)
    dust = float(dust_tau) * (1.0 - DUST_SSA[1] * DUST_ASYMMETRY)
    deck = float(env.get("sulfuric_deck_tau", 0.0) or 0.0) * (1.0 - SULFURIC_DECK_SSA[1] * SULFURIC_DECK_ASYMMETRY)
    tau = rayleigh + haze + dust + deck
    if tau <= 1e-6:
        return 1.0
    direct = math.exp(-tau / max(0.05, sun_mu))
    albedo = (rayleigh + haze * HAZE_SSA[1] + dust * DUST_SSA[1] + deck * SULFURIC_DECK_SSA[1]) / tau
    # About half of the scattered beam continues downward.
    diffuse = 0.5 * (1.0 - direct) * albedo
    return float(direct / max(1e-9, direct + diffuse))


def dust_aerosol_tau(env, dry_land_fraction, wet_fraction=0.0):
    """Visible optical depth of lifted dust (Mars ~0.5, Earth a few hundredths).

    Lifted from dry land where air can carry it (lower gravity keeps it
    aloft longer); precipitation over seas and wet land scavenges it.
    """
    carrier = (1.0 - math.exp(-env["pressure_bar"] / 0.002)) * min(1.6, env["gravity_g"] ** -0.5)
    scavenging = math.exp(-2.5 * max(0.0, float(wet_fraction)))
    return float(np.clip(0.5 * dry_land_fraction * carrier * scavenging, 0.0, 2.0))


def apply_atmosphere(linear_rgb, env, dust_tau=0.0):
    """Nadir view from orbit: two-way extinction plus the column's path reflectance."""
    rayleigh = np.asarray(env["rayleigh_tau_rgb"], dtype=np.float32)
    ratio = np.asarray([wavelength / 0.54 for wavelength in CHANNEL_WAVELENGTH_UM], dtype=np.float32)
    haze = env["haze_tau"] * ratio ** -1.2
    dust = dust_tau * ratio ** -0.3
    if float((rayleigh + haze + dust).max()) <= 1e-6:
        return linear_rgb
    # Forward-scattering aerosols: delta-scaled extinction.
    haze_effective = haze * (1.0 - _ssa(HAZE_SSA) * HAZE_ASYMMETRY)
    dust_effective = dust * (1.0 - _ssa(DUST_SSA) * DUST_ASYMMETRY)
    # Path reflectance of each layer: single scattering (~0.19 x 2 tau for
    # Rayleigh at nadir) growing toward a thick layer's albedo; absorbing
    # aerosols (single-scattering albedo < 1) lose part of it to repeated
    # absorption (~ ssa^4).
    rayleigh_path = 0.19 + 0.7 * (1.0 - np.exp(-rayleigh / 3.0))
    haze_path = _ssa(HAZE_SSA) ** 4 * (0.10 + 0.6 * (1.0 - np.exp(-haze_effective / 1.5)))
    dust_path = _ssa(DUST_SSA) ** 4 * (0.10 + 0.6 * (1.0 - np.exp(-dust_effective / 1.5)))
    # Layers: gas and lifted dust near the surface, photochemical haze high
    # above (Titan's haze absorbs blue sunlight before it reaches the gas).
    lower_tau = rayleigh + dust_effective
    lower_transmission = np.exp(-2.0 * lower_tau)
    lower_path = (rayleigh * rayleigh_path + dust_effective * dust_path) / np.maximum(lower_tau, 1e-9)
    haze_transmission = np.exp(-2.0 * haze_effective)
    column_path = lower_path * (1.0 - lower_transmission) * haze_transmission + haze_path * (1.0 - haze_transmission)
    transmission = lower_transmission * haze_transmission
    deck_tau = float(env.get("sulfuric_deck_tau", 0.0) or 0.0)
    if deck_tau > 0.0:
        # A permanent cloud deck on top of everything.
        deck_effective = deck_tau * (1.0 - _ssa(SULFURIC_DECK_SSA) * SULFURIC_DECK_ASYMMETRY)
        deck_transmission = np.exp(-2.0 * deck_effective)
        deck_path = _ssa(SULFURIC_DECK_SSA) ** 4 * (0.10 + 0.75 * (1.0 - np.exp(-deck_effective / 1.5)))
        column_path = column_path * deck_transmission + deck_path * (1.0 - deck_transmission)
        transmission = transmission * deck_transmission
    # Map legibility floor: keep at least this much of the surface signal,
    # scaling the column's own light down to make room.
    visibility = np.maximum(transmission, MAP_SURFACE_VISIBILITY_FLOOR)
    column_scale = (1.0 - visibility) / np.maximum(1.0 - transmission, 1e-9)
    return linear_rgb * visibility + column_path * column_scale
