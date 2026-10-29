"""Continuous-coordinate ecology kernel for the isometric Biosphere builder.

A species stands on the ground as *stands*: discs with a centre, a radius and
a cover.  Crusts and swards are nothing more than that.  Every other plant is
kept as individuals (``individuals.IndividualRegister``): its stand is the
plants in it, the disc is where they may stand and the cover is how many of
them there are.  One balance of growth and loss decides both: for a cover it
is its rate of change, for a stand of plants how many take root or die in a
season.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import math

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships with the app
    np = None

from simulations.biosphere.individuals import IndividualRegister
from simulations.biosphere.vegetation import VegetationSampler, _canopy_light
from simulations.species.forest_ecology import light_at, shade_profile
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.plant_life_timing import resolve_plant_life_timing
from simulations.species.plant_nutrition import resolve_plant_nutrient_response


def _clamp(value, lower=0.0, upper=1.0):
    return max(lower, min(upper, float(value)))


@dataclass(frozen=True)
class SpeciesProfile:
    species_id: str
    label: str
    growth_form: str
    growth_rate: float
    dispersal: float
    moisture_optimum: float
    moisture_tolerance: float
    light_minimum: float
    carrying_biomass_kg_m2: float
    color: tuple[int, int, int]
    provenance: str
    shade_tolerance: str = "other_unknown"
    light_requirement_source: str = "growth_form_default"
    mature_height_m: float = 1.0
    maturity_days: float = 120.0
    crown_openness: float = 0.5
    succession_tier: int = 1
    soil_organic_requirement_kg_m2: float = 0.15
    succession_source: str = "growth_form_runtime_default"
    nitrogen_fixation: str = "other_unknown"
    nutrition_mode: str = "other_unknown"
    surface_growth_profile: object = None
    mycorrhizal_type: str = "other_unknown"
    root_architecture: str = "other_unknown"
    root_depth_class: str = "other_unknown"
    max_root_depth: object = None
    moisture_source: str = "growth_form_default"
    # How long its roots bear standing water: the authored ``waterlogging_tolerance`` (low, medium, high),
    # else what its moisture preference suggests.
    waterlogging_tolerance: str = "low"
    waterlogging_source: str = "moisture preference default"
    # How much sea water the water its roots meet may hold: the authored ``salinity_tolerance`` (low, medium,
    # high); a plant that says nothing is taken for one of fresh ground, as nearly all are.
    salinity_tolerance: str = "low"
    salinity_source: str = "unauthored: taken for a plant of fresh ground"
    # The soil reaction it grows in, ``(lowest, highest)`` pH: the authored ``soil_ph_range``.  A plant
    # without one is not asked: the soil's chemistry then counts in its fertility, for all plants alike.
    soil_ph_range: object = None
    frost_min_c: object = None
    # Limits of its own in monthly means, each a ramp in degrees C, where the species says where it grows
    # wild (``thermal_range_coldest`` / ``thermal_range_warmest``) or gives exact figures.  ``None`` leaves
    # the limit every plant shares; no plant has a winter limit it did not author.
    winter_limit_c: object = None  # (gone, unharmed), coldest month
    warmth_need_c: object = None   # (no growth, full growth), warmest month
    heat_limit_c: object = None    # (unharmed, gone), warmest month
    thermal_source: str = "limits shared by all plants"
    # ``maturity_days`` is real time to mature size (plant_life_timing).  The
    # seedling stage, while a cohort still depends on light at the ground, is
    # the short span Species Sim's developmental clock gives it.
    establishment_days: object = None
    # Real time to setting seed: a woody plant does long before it is full-grown.  ``None``: at full size.
    seed_days: object = None
    lifespan_days: object = None
    maturity_source: str = "developmental clock"
    lifespan_source: str = "unresolved"
    clonal_spread: str = "other_unknown"
    # Whether it sprouts again from its stock when what stands above ground is taken: the authored ``resprouting``.
    resprouting: str = "other_unknown"
    soil_fertility_increment_per_season: float = 0.0
    soil_fertility_bonus_cap: float = 0.0


@dataclass(frozen=True)
class SpeciesIntroduction:
    introduction_id: str
    species_id: str
    x: float
    y: float
    radius_world: float
    propagule_pressure: float
    season: int


@dataclass
class PopulationPatch:
    patch_id: str
    species_id: str
    x: float
    y: float
    radius_m: float
    abundance: float
    season_introduced: int
    seed: int
    soil_fertility_bonus: float = 0.0
    development_days: float = 1.0
    establishment_canopies: tuple | None = None
    # Suitability just beyond the rim, refreshed every few seasons.
    edge_suitability: float | None = None
    # Suitability summed over points half-way out in a wide stand, and how
    # many points that was; likewise refreshed every few seasons.
    stand_ring: tuple | None = None


# Where an authored ``moisture_preference`` class sits on worldgen's
# dimensionless wetness index.  Qualitative placement, not a measurement.
_MOISTURE_PREFERENCE_OPTIMUM = {
    "very_dry": 0.08, "dry": 0.20, "mesic": 0.42, "moist": 0.58, "wet": 0.78, "aquatic": 0.92,
}
# Rain alone brings ground to "fresh", all demand met (``water_balance.FRESH_WETNESS``).  Wetter than that
# means water standing in the roots, from a water table or for want of drainage, and what a plant makes of
# it is no matter of how much water it likes but of how long its roots live without air.  By the authored
# tolerance (the classes of Niinemets & Valladares 2006, who scored 806 woody species: intolerant of more
# than a week or two of waterlogging in the growing season, tolerant of about a month, tolerant of most of
# the season): the wetness a plant bears unharmed and the wetness at which it fails.  Low: a water table
# from about a metre down, gone where it stands at 45 cm; medium: from 65 cm, gone at 15 cm; high: any
# ground that is not open water.
_WATERLOGGING_LIMITS = {"low": (0.55, 0.68), "medium": (0.62, 0.80), "high": (1.0, 1.1)}
# Where no tolerance is authored: plants of wet ground bear it, plants of moist ground bear some.
_WATERLOGGING_BY_OPTIMUM = ((0.70, "high"), (0.50, "medium"), (0.0, "low"))


def waterlogging_limits(profile):
    """``(bears, fails)``: the wetness up to which a species' roots are unharmed and at which it fails."""
    bears, fails = _WATERLOGGING_LIMITS.get(profile.waterlogging_tolerance, _WATERLOGGING_LIMITS["low"])
    # A species is at least at home where it grows best.
    bears = max(bears, profile.moisture_optimum)
    return bears, max(fails, bears + 0.05)


def moisture_response(profile, wetness):
    """How well a species is watered at a wetness, 0..1, over arrays.

    Two limits, and the lower counts.  Short of the wetness it grows best at
    it lacks water, down to nothing a tolerance below that.  Above it more
    water does no harm as long as the ground drains: a pine is not hurt by a
    soil that never dries.  Only water standing in the roots is, by the
    species' tolerance of waterlogging.
    """
    wet = np.asarray(wetness, dtype=np.float64)
    thirst = np.clip(1.0 - (profile.moisture_optimum - wet) / profile.moisture_tolerance, 0.0, 1.0)
    bears, fails = waterlogging_limits(profile)
    return np.minimum(thirst, np.clip(1.0 - (wet - bears) / (fails - bears), 0.0, 1.0))

# The share of sea water in the water its roots meet that a plant bears unharmed, and from which it fails.
# Sea water conducts about 55 dS/m.  Plants of fresh ground are harmed from 2 to 4 dS/m in the soil water
# and few live past 15 (Maas & Hoffman 1977); the moderately tolerant bear 10 and fail towards 30; a
# halophyte completes its life at 200 mM of salt and more, two fifths of sea water, and those of salt marsh
# and mangrove in the sea itself (Flowers & Colmer 2008).
_SALINITY_LIMITS = {"low": (0.05, 0.25), "medium": (0.20, 0.55), "high": (1.0, 1.1)}


def salinity_limits(profile):
    """``(bears, fails)`` of a plant in sea-water share, by its salinity tolerance."""
    return _SALINITY_LIMITS.get(getattr(profile, "salinity_tolerance", "low"), _SALINITY_LIMITS["low"])


def salt_response(profile, salt):
    """How a plant fares on water that is ``salt`` parts sea water, over arrays: 1 unharmed, 0 gone."""
    bears, fails = salinity_limits(profile)
    return np.clip(1.0 - (np.asarray(salt, dtype=np.float64) - bears) / (fails - bears), 0.0, 1.0)


def salt_in_reach(profile, salinity, water_table_depth_m, capillary_rise_m=None, open_water=False):
    """The sea-water share of the water a plant's roots meet, over arrays.

    ``salinity`` is that of the ground water at the table
    (``fine_hydrology.groundwater_salinity``).  It counts as far as the
    ground water is within reach of the roots or of the capillary rise above
    it (``water_balance.groundwater_reach``): salt ground water metres below
    a dune harms nothing that roots in the rain-fed sand.  A plant that
    stands in the water meets all of it.
    """
    from simulations.biosphere.water_balance import DEFAULT_CAPILLARY_RISE_M, groundwater_reach

    salinity = np.nan_to_num(np.asarray(salinity, dtype=np.float64), nan=0.0)
    if profile.growth_form == "aquatic":
        return salinity
    rise = DEFAULT_CAPILLARY_RISE_M if capillary_rise_m is None else capillary_rise_m
    reach = groundwater_reach(rooting_depth_m(profile), np.nan_to_num(np.asarray(rise, dtype=np.float64),
                                                                      nan=DEFAULT_CAPILLARY_RISE_M),
                              np.asarray(water_table_depth_m, dtype=np.float64))
    return np.where(np.asarray(open_water, dtype=bool), salinity, salinity * reach)


def salt_score(profile, environment):
    """``salt_response`` at one place, or ``None`` where its map tells no ground-water salinity."""
    unresolved = environment.get("runtime_default_fields", ())
    salinity = environment.get("groundwater_salinity")
    if salinity is None or "groundwater_salinity" in unresolved or profile.surface_growth_profile:
        return None
    table = environment.get("water_table_depth_m")
    salt = salt_in_reach(profile, salinity, np.nan if table is None else table, environment.get("capillary_rise_m"),
                         bool(environment.get("open_water", False)))
    return float(salt_response(profile, salt))


# Monthly-mean limits shared by every plant until a species authors its own:
# no net growth where the warmest month stays near freezing, and heat injury
# where even the monthly mean is far above photosynthetic optima.
_GROWING_WARMTH_C = (5.0, 10.0)
_HEAT_LIMIT_C = (38.0, 48.0)
_FROST_RAMP_C = 6.0

# Where a plant grows wild, as zones of one ordered scale, coldest first (authored as
# ``thermal_range_coldest`` and ``thermal_range_warmest``; the words are ``plant_traits.PLANT_THERMAL_ZONES``).
# Exact temperatures are known for few species; the zones of a distribution map are known for nearly all.
# Per zone, in monthly means: the coldest month it bears, the warmest month it needs, the warmest month it
# bears.  A plant takes the first two from its coldest zone and the third from its warmest, so "cold to
# very hot" bears a boreal winter and a desert summer and "hot" alone neither a cool winter nor a furnace.
# The figures are where the zones of a climate map end: trees stop where the warmest month has about 10
# degrees (a boreal plant is at full strength from 11 and gone at 5), 22 parts cool summers from warm ones
# (Koeppen's b and a), the frost-free tropics begin at 18 in the coldest month (taken a little lower:
# chilling harms tropical plants from about 12 down).  The hottest months on Earth have about 39 degrees and
# plants in them; "very hot" bears a little more and ends where the shared limit ends.
THERMAL_ZONES = ("frigid", "cold", "cool", "mild", "warm", "hot", "very_hot")
THERMAL_ZONE_C = {
    "frigid": (-40.0, 6.0, 12.0),
    "cold": (-25.0, 11.0, 18.0),
    "cool": (-10.0, 15.0, 22.0),
    "mild": (0.0, 18.0, 26.0),
    "warm": (8.0, 21.0, 30.0),
    "hot": (15.0, 25.0, 36.0),
    "very_hot": (15.0, 28.0, 42.0),
}
# A range does not end on a line.  A plant stands unharmed at a figure and is gone this far beyond it, the
# width an authored frost figure has always had.
THERMAL_ZONE_RAMP_C = _FROST_RAMP_C
# How far a closed canopy lowers the warmest-month mean for what grows under
# it: relief from heat.  Shade does not help against cold, and the warmth a
# plant needs is asked of the open air, as its zone is read off a climate map
# (a forest fern of the tropics is not short of warmth under its trees).
CANOPY_COOLING_C = 6.0

# Soil organic matter holds rain the mineral ground would lose.  It can lift
# dry ground towards a mesic wetness, never past it, and only as far as rain
# actually falls.  Half the effect is reached at ``RETENTION_HALF_KG_M2``.
RETENTION_CEILING = 0.45
RETENTION_HALF_KG_M2 = 1.0
RETENTION_FULL_RAIN_MM = 1000.0


# How much soil a plant needs under it, as shares of the depth it roots to: it stands at its best from the
# first (most of a root system is in its upper part), and does not hold below the second.  An oak that
# roots two metres deep is at its best on 80 cm of soil and cannot stand on 20 cm; a grass that roots 40 cm
# deep is at its best on 16 cm.
ROOTING_FULL_SHARE = 0.4
ROOTING_NONE_SHARE = 0.1
# The depth a full-grown plant roots to where neither a depth nor a depth class is authored, in metres by
# growth form.  Runtime assumptions like the other growth-form defaults, not measurements.
_ROOTING_DEPTH_BY_FORM_M = {
    "tree": 1.5, "shrub": 0.8, "vine": 0.8, "subshrub": 0.4, "graminoid": 0.4, "forb": 0.4, "fern": 0.3,
    "succulent": 0.3,
}
# The depth classes are Species Sim's (``root_growth.root_profile``).
_ROOTING_DEPTH_BY_CLASS_M = {"shallow": 0.35, "intermediate": 1.0, "deep": 2.0}


def rooting_depth_m(profile):
    """How deep a full-grown plant of a species roots, in metres: as authored, by its depth class, or by its form."""
    authored = profile.max_root_depth
    if isinstance(authored, dict):
        authored = authored.get("max_m", authored.get("value_m"))
    if isinstance(authored, (int, float)) and not isinstance(authored, bool) and math.isfinite(authored) and authored > 0:
        return float(authored)
    by_class = _ROOTING_DEPTH_BY_CLASS_M.get(str(profile.root_depth_class or "").lower())
    if by_class is not None:
        return by_class
    # A herb a hand high does not root as deep as its form's metre-scale kin.
    return min(_ROOTING_DEPTH_BY_FORM_M.get(profile.growth_form, 0.5), max(0.05, float(profile.mature_height_m) * 0.75))


def rootable_depth_of(environment):
    """The depth of ground a place lets roots into, or ``None`` where its map does not say.

    Loose sediment counts whether or not a soil has formed on it
    (``rootable_depth_m``); a map without that figure gives its soil's depth.
    """
    unresolved = environment.get("runtime_default_fields", ())
    for key in ("rootable_depth_m", "soil_depth_m"):
        if key in environment and key not in unresolved:
            return environment[key]
    return None


def rooting_response(profile, soil_depth_m):
    """How well a depth of soil lets a species root, for a number or an array: 1 at its best, 0 where it cannot hold.

    Ground whose depth is not known (NaN) is left unjudged.  What grows on a
    surface or in water does not root in soil at all.
    """
    depth = np.asarray(soil_depth_m, dtype=np.float64)
    if profile.surface_growth_profile or profile.growth_form == "aquatic":
        return np.ones(depth.shape)
    share = depth / rooting_depth_m(profile)
    response = np.clip((share - ROOTING_NONE_SHARE) / (ROOTING_FULL_SHARE - ROOTING_NONE_SHARE), 0.0, 1.0)
    return np.where(np.isnan(depth), 1.0, response)


# Beyond its authored range of soil reaction a plant fails within this many units of pH.
SOIL_REACTION_RAMP_PH = 1.0


def authored_soil_ph_range(entity):
    """``(lowest, highest)`` pH of a species' authored ``soil_ph_range``, or ``None``."""
    told = entity.get("soil_ph_range") if isinstance(entity, dict) or hasattr(entity, "get") else None
    try:
        low, high = float(told["min"]), float(told["max"])
    except (TypeError, KeyError, ValueError):
        return None
    return (low, high) if math.isfinite(low) and math.isfinite(high) and low < high else None


def reaction_response(profile, soil_ph):
    """How far the soil's reaction lets a species grow, 0..1, over arrays.

    Full within its authored range of pH and nothing a unit beyond it: a
    plant of sour heath does not stand on chalk, nor a plant of chalk on
    peat.  One without an authored range, and ground that tells no pH, is
    not limited here.
    """
    ph = np.asarray(soil_ph, dtype=np.float64)
    if profile.soil_ph_range is None:
        return np.ones(ph.shape)
    low, high = profile.soil_ph_range
    ramp = SOIL_REACTION_RAMP_PH
    return np.where(np.isnan(ph), 1.0, np.clip(np.minimum((ph - (low - ramp)) / ramp, ((high + ramp) - ph) / ramp), 0.0, 1.0))


def reaction_score(profile, environment):
    """``reaction_response`` at one place, or ``None`` where the species or the ground does not say."""
    if profile.soil_ph_range is None or profile.surface_growth_profile or environment.get("soil_ph") is None:
        return None
    if "soil_ph" in environment.get("runtime_default_fields", ()):
        return None
    return float(reaction_response(profile, environment["soil_ph"]))


def mineral_soil_index(soil_ph, salinity_index=0.0):
    """How far a mineral soil's chemistry lets plants at large use what it holds, 0..1: its reaction and its salt.

    Full between pH 5.5 and 7.5, nothing below 3.5 or above 9.5, and less by
    the soil's salinity index.  The worldgen's soil model leaves fertility out
    on purpose (it knows no life); this is the Biosphere's reading of the
    chemistry that model does give.
    """
    ph = float(soil_ph)
    return _clamp(min((ph - 3.5) / 2.0, (9.5 - ph) / 2.0)) * _clamp(1.0 - float(salinity_index or 0.0))


# The roots the site's wetness is told for where no plant is asked about: a herb's.
REFERENCE_ROOT_DEPTH_M = 0.4
# Years between floods from which ground counts as never reworked (``world_gen.river_floods.NEVER_YEARS``).
FLOOD_NEVER_YEARS = 999.0
FLOOD_REWORKING_FIELD = "flood_reworking_return_period_years"


def years_to_grow(profile):
    """The years a plant of a species takes to stand full-grown."""
    return float(profile.maturity_days) / (4.0 * BiosphereEcology.DAYS_PER_SEASON)


def seed_days_of(profile):
    """Days a stand takes to set seed: full size, or earlier for a woody plant."""
    seed_days = getattr(profile, "seed_days", None)
    return float(profile.maturity_days) if seed_days is None else min(float(profile.maturity_days), float(seed_days))


def flood_standing_share(profile, reworked_years):
    """The share of ground a river reworks that often on which a species stands full-grown, over arrays.

    A flood that reworks a surface takes what grows on it.  Floods come
    without memory, so the chance that a plant has had its years to grow up
    since the last one is ``exp(-years / return)``: a herb stands on a bar
    reworked every three years, a tree needs ground left alone for decades.
    Ground no flood reworks (and ground that does not tell) carries all of it.
    """
    returns = np.asarray(reworked_years, dtype=np.float64)
    quiet = ~np.isfinite(returns) | (returns >= FLOOD_NEVER_YEARS)
    return np.where(quiet, 1.0, np.exp(-years_to_grow(profile) / np.maximum(np.where(quiet, 1.0, returns), 1e-3)))


def raw_ground_wetness(environment):
    """How wet a place is as bare mineral ground, for a herb: its water balance, else its map's index."""
    balance = water_ground(environment)
    if balance is None:
        return float(environment.get("soil_moisture", 0.0) or 0.0)
    from simulations.biosphere.water_balance import point_wetness

    return point_wetness(balance, REFERENCE_ROOT_DEPTH_M, 0.0)


def water_ground(environment):
    """What a place gives the water balance (``water_balance.point_ground``), or ``None``.

    ``None`` where its map carries no demand of the air: a hand-built plot,
    or ground generated before the balance was read.  There wetness stays
    the map's own index, lifted by what a built soil holds.
    """
    from simulations.biosphere.water_balance import (
        DEFAULT_AVAILABLE_WATER_MM_PER_M, DEFAULT_CAPILLARY_RISE_M, point_ground,
    )

    unresolved = environment.get("runtime_default_fields", ())

    def given(key):
        return environment[key] if key in environment and key not in unresolved else None

    demand, rain = given("annual_potential_evaporation_mm"), given("annual_precipitation_mm")
    if demand is None or rain is None:
        return None
    rootable = given("rootable_depth_m")
    return point_ground(
        rain, demand, drainage_mm_per_day=given("drainage_mm_per_day"),
        driest_month_mm=given("driest_month_precipitation_mm"), wettest_month_mm=given("wettest_month_precipitation_mm"),
        summer_fraction=given("summer_precipitation_fraction"),
        coldest_month_k=given("coldest_month_temperature_k"), warmest_month_k=given("warmest_month_temperature_k"),
        exposure=environment.get("surface_solar_exposure", 1.0),
        available_water_mm_per_m=given("available_water_mm_per_m") or DEFAULT_AVAILABLE_WATER_MM_PER_M,
        rootable_depth_m=rootable if rootable is not None else given("soil_depth_m"),
        lateral_mm=given("lateral_water_mm") or 0.0,
        capillary_rise_m=given("capillary_rise_m") or DEFAULT_CAPILLARY_RISE_M,
        water_table_depth_m=given("water_table_depth_m"),
    )


def moisture_retention_bonus(abiotic_moisture, organic_matter_kg_m2, annual_precipitation_mm=None):
    """Wetness added by soil organic matter at one place."""

    headroom = max(0.0, RETENTION_CEILING - float(abiotic_moisture))
    organic = max(0.0, float(organic_matter_kg_m2))
    developed = organic / (organic + RETENTION_HALF_KG_M2)
    rain = 1.0 if annual_precipitation_mm is None else _clamp(float(annual_precipitation_mm) / RETENTION_FULL_RAIN_MM)
    return headroom * developed * rain


def _ramp(low, high):
    """``(low, high)`` as an ordered pair of finite degrees with some width, or ``None``."""
    try:
        low, high = float(low), float(high)
    except (TypeError, ValueError):
        return None
    return (low, high) if math.isfinite(low) and math.isfinite(high) and high - low >= 0.5 else None


def authored_thermal_limits(entity):
    """What a species says of heat and cold: ``(winter, warmth, heat, source)``, a ramp each or ``None``.

    Its zones (``thermal_range_coldest`` to ``thermal_range_warmest``) give a
    ramp from the zone's figure to ``THERMAL_ZONE_RAMP_C`` beyond it.  Exact
    figures stand before them: ``temperature_range`` for the warmth it needs
    (``min_c`` to ``optimal_min_c``) and the heat it bears (``optimal_max_c``
    to ``max_c``).  ``frost_tolerance`` is read where the limits are used
    (``thermal_limits``), as it was before there were zones.
    """
    zones = []
    for key in ("thermal_range_coldest", "thermal_range_warmest"):
        zone = str(entity.get(key) or "").strip().lower().replace("-", "_").replace(" ", "_")
        zones.append(THERMAL_ZONES.index(zone) if zone in THERMAL_ZONE_C else None)
    coldest, warmest = zones
    if coldest is not None and warmest is not None and coldest > warmest:
        coldest, warmest = warmest, coldest
    ramp, winter, warmth, heat, said = THERMAL_ZONE_RAMP_C, None, None, None, []
    if coldest is not None:
        winter_c, need_c, _bears = THERMAL_ZONE_C[THERMAL_ZONES[coldest]]
        winter, warmth = (winter_c - ramp, winter_c), (need_c - ramp, need_c)
    if warmest is not None:
        bears_c = THERMAL_ZONE_C[THERMAL_ZONES[warmest]][2]
        heat = (bears_c, bears_c + ramp)
    if coldest is not None or warmest is not None:
        ends = [THERMAL_ZONES[zone].replace("_", " ") for zone in (coldest, warmest) if zone is not None]
        said.append("authored thermal range (" + (ends[0] if len(set(ends)) == 1 else " to ".join(ends)) + ")")
    exact = entity.get("temperature_range") if isinstance(entity.get("temperature_range"), dict) else {}
    exact_warmth = _ramp(exact.get("min_c"), exact.get("optimal_min_c"))
    exact_heat = _ramp(exact.get("optimal_max_c"), exact.get("max_c"))
    if exact_warmth or exact_heat:
        warmth, heat = exact_warmth or warmth, exact_heat or heat
        said.insert(0, "authored temperature_range")
    return winter, warmth, heat, " over ".join(said) or "limits shared by all plants"


def thermal_limits(profile):
    """``(warmth, heat, winter)`` of a plant as ramps in monthly means.

    Its own where it has them, else the limits every plant shares; no winter
    limit where it authored none.  An exact frost figure stands before the
    winter of its zone.
    """
    warmth = getattr(profile, "warmth_need_c", None) or _GROWING_WARMTH_C
    heat = getattr(profile, "heat_limit_c", None) or _HEAT_LIMIT_C
    winter = getattr(profile, "winter_limit_c", None)
    frost_min = getattr(profile, "frost_min_c", None)
    if frost_min is not None:
        # Monthly normals understate the coldest night; the ramp is the margin.
        winter = (float(frost_min), float(frost_min) + _FROST_RAMP_C)
    return warmth, heat, winter


def thermal_response(profile, environment):
    """Return ``(score, limiting)`` from worldgen's monthly temperature normals.

    Only environments that carry seasonal normals are judged; a substrate
    without them leaves temperature unresolved rather than assumed benign.
    """

    warmest = environment.get("warmest_month_temperature_k")
    coldest = environment.get("coldest_month_temperature_k")
    if warmest is None or coldest is None:
        return 1.0, None
    warmest_c, coldest_c = float(warmest) - 273.15, float(coldest) - 273.15
    sheltered_c = warmest_c - CANOPY_COOLING_C * _clamp(environment.get("canopy_shade", 0.0))
    warmth, heat, winter = thermal_limits(profile)
    scores = {
        "growing-season warmth": _clamp((warmest_c - warmth[0]) / (warmth[1] - warmth[0])),
        "heat": _clamp((heat[1] - sheltered_c) / (heat[1] - heat[0])),
    }
    if winter is not None:
        scores["frost"] = _clamp((coldest_c - winter[0]) / (winter[1] - winter[0]))
    limiting = min(scores, key=scores.get)
    return scores[limiting], (limiting if scores[limiting] < 1.0 else None)


def mature_wetness(abiotic_moisture, annual_precipitation_mm=None, typical_moisture=None):
    """Wetness of ground whose soil is built, over arrays: the mineral ground's own plus all a soil can hold.

    ``typical_moisture`` is the wetness of the site's ordinary ground.  What a
    built soil adds is reckoned for that and added everywhere alike, so a
    hollow stays as much wetter than a rise as the terrain made it.  Without
    it each place is lifted towards the ceiling on its own, which levels them.
    """
    abiotic = np.asarray(abiotic_moisture, dtype=np.float64)
    rain = 1.0 if annual_precipitation_mm is None else np.clip(
        np.asarray(annual_precipitation_mm, dtype=np.float64) / RETENTION_FULL_RAIN_MM, 0.0, 1.0)
    reference = abiotic if typical_moisture is None else np.asarray(typical_moisture, dtype=np.float64)
    return np.clip(abiotic + np.maximum(0.0, RETENTION_CEILING - reference) * rain, 0.0, 1.0)


def thermal_response_array(profile, warmest_k, coldest_k, canopy_shade=0.0):
    """``thermal_response`` over arrays of monthly normals; ground without them (NaN) is left unjudged."""
    warmest = np.asarray(warmest_k, dtype=np.float64) - 273.15
    sheltered = warmest - CANOPY_COOLING_C * np.clip(canopy_shade, 0.0, 1.0)
    coldest = np.asarray(coldest_k, dtype=np.float64) - 273.15
    warmth, heat, winter = thermal_limits(profile)
    score = np.minimum(
        np.clip((warmest - warmth[0]) / (warmth[1] - warmth[0]), 0.0, 1.0),
        np.clip((heat[1] - sheltered) / (heat[1] - heat[0]), 0.0, 1.0),
    )
    if winter is not None:
        score = np.minimum(score, np.clip((coldest - winter[0]) / (winter[1] - winter[0]), 0.0, 1.0))
    return np.where(np.isnan(warmest) | np.isnan(coldest), 1.0, score)


def potential_suitability(profile, wetness, warmest_k, coldest_k, light=1.0, canopy_shade=0.0, soil_depth_m=None,
                          salt=None, soil_ph=None):
    """What built ground gives a species, over arrays.

    The kernel's own arithmetic (``BiosphereEcology.suitability_factors``)
    with what is built at its best: water, temperature, the depth of the
    mineral ground and the salt in reach of its roots (``salt_in_reach``),
    which come with it, cap it; light counts with the kernel's weight beside
    nutrients and fertility, which a mature soil supplies.
    """
    moisture = moisture_response(profile, wetness)
    thermal = thermal_response_array(profile, warmest_k, coldest_k, canopy_shade)
    light_score = np.clip((np.asarray(light, dtype=np.float64) - profile.light_minimum)
                          / max(0.08, 1.0 - profile.light_minimum), 0.0, 1.0)
    weights = BiosphereEcology.LIGHT_WEIGHT, BiosphereEcology.NUTRIENT_WEIGHT, BiosphereEcology.FERTILITY_WEIGHT
    support = (weights[0] * light_score + weights[1] + weights[2]) / sum(weights)
    limit = np.minimum(moisture, thermal)
    if soil_depth_m is not None:
        limit = np.minimum(limit, rooting_response(profile, soil_depth_m))
    if salt is not None and not profile.surface_growth_profile:
        limit = np.minimum(limit, salt_response(profile, salt))
    if soil_ph is not None and profile.soil_ph_range is not None and not profile.surface_growth_profile:
        limit = np.minimum(limit, reaction_response(profile, soil_ph))
    return np.clip(limit * support, 0.0, 1.0)


def expected_cover_array(profile, suitability, competition=0.0, overtopping=0.0):
    """``BiosphereEcology.expected_cover`` over arrays: the cover a population settles at.

    ``competition`` and ``overtopping`` are what the kernel reckons from the
    stands sharing its ground (``BiosphereEcology._competition_at_patch``):
    the first takes room from its growth, the second adds to what it loses.
    """
    suitability = np.asarray(suitability, dtype=np.float64)
    kernel = BiosphereEcology
    loss = ((1.0 - suitability) * kernel.STRESS_PER_SEASON + kernel.TYPICAL_MORTALITY_PER_SEASON
            + np.asarray(overtopping, dtype=np.float64) * kernel.OVERTOPPED_STRESS_PER_SEASON)
    with np.errstate(divide="ignore", invalid="ignore"):
        cover = (1.0 - np.asarray(competition, dtype=np.float64) * kernel.COMPETITION_SHARE
                 - loss / (profile.growth_rate * suitability))
    return np.where(suitability > 0.0, np.clip(cover, 0.0, 1.0), 0.0)


# How far a season's seeds, spores or fragments found a new patch beyond the
# parent's rim, in metres.  Qualitative reach by growth form.
_DISPERSAL_REACH_M = {
    "lichen": 6.0, "graminoid": 8.0, "forb": 10.0, "fern": 15.0, "subshrub": 6.0,
    "shrub": 12.0, "succulent": 4.0, "tree": 25.0, "aquatic": 5.0,
}

_FORM_DEFAULTS = {
    "tree": (0.10, 0.045, 7.5, 0.48, 0.30, 0.22),
    "shrub": (0.16, 0.070, 3.5, 0.46, 0.34, 0.18),
    "graminoid": (0.29, 0.125, 1.4, 0.48, 0.42, 0.28),
    "forb": (0.25, 0.105, 1.0, 0.52, 0.38, 0.25),
    "succulent": (0.13, 0.050, 2.1, 0.22, 0.25, 0.35),
    "aquatic": (0.22, 0.095, 2.4, 0.88, 0.20, 0.18),
    "lichen": (0.48, 0.180, 2.8, 0.38, 0.52, 0.12),
}


def profile_from_entity(entity):
    entity = entity or {}
    species_id = str(entity.get("id") or "unknown_species")
    label = entity.get("pretty_name") or entity.get("name") or species_id.replace("spec_", "").replace("_", " ").title()
    growth_form = str(entity.get("plant_growth_form") or "forb").strip().lower()
    defaults = _FORM_DEFAULTS.get(growth_form, _FORM_DEFAULTS["forb"])
    authored = entity.get("biosphere_growth_profile") if isinstance(entity.get("biosphere_growth_profile"), dict) else {}

    def number(key, default):
        try:
            value = float(authored.get(key, default))
            return value if math.isfinite(value) else float(default)
        except (TypeError, ValueError):
            return float(default)

    digest = hashlib.sha256(species_id.encode("utf-8")).digest()
    shade = shade_profile(str(entity.get("shade_tolerance") or "other_unknown").lower())
    light_default = shade["minimum_light"] if shade["tolerance"] != "other_unknown" else defaults[5]
    try:
        explicit_light = "light_minimum" in authored and math.isfinite(float(authored["light_minimum"]))
    except (TypeError, ValueError):
        explicit_light = False
    light_source = ("authored biosphere light_minimum" if explicit_light else
                    "shade_tolerance qualitative default" if shade["tolerance"] != "other_unknown" else
                    "growth_form_default")
    growth = PlantBlueprint.from_species_entity(entity, species_id).growth
    timing = resolve_plant_life_timing(entity, growth)
    moisture_class = str(entity.get("moisture_preference") or "").strip().lower()
    try:
        explicit_moisture = "moisture_optimum" in authored and math.isfinite(float(authored["moisture_optimum"]))
    except (TypeError, ValueError):
        explicit_moisture = False
    moisture_default = _MOISTURE_PREFERENCE_OPTIMUM.get(moisture_class, defaults[3])
    moisture_source = ("authored biosphere moisture_optimum" if explicit_moisture else
                       "moisture_preference qualitative default" if moisture_class in _MOISTURE_PREFERENCE_OPTIMUM else
                       "growth_form_default")
    waterlogging = str(entity.get("waterlogging_tolerance") or "").strip().lower()
    waterlogging_source = "authored waterlogging_tolerance"
    if waterlogging not in _WATERLOGGING_LIMITS:
        optimum = _clamp(number("moisture_optimum", moisture_default))
        waterlogging = "high" if growth_form == "aquatic" else next(
            name for least, name in _WATERLOGGING_BY_OPTIMUM if optimum >= least)
        waterlogging_source = "moisture preference default"
    salinity = str(entity.get("salinity_tolerance") or "").strip().lower()
    salinity_source = "authored salinity_tolerance"
    if salinity not in _SALINITY_LIMITS:
        salinity, salinity_source = "low", "unauthored: taken for a plant of fresh ground"
    frost = entity.get("frost_tolerance")
    try:
        frost_min_c = float(frost.get("min_c")) if isinstance(frost, dict) and frost.get("min_c") is not None else None
        if frost_min_c is not None and not math.isfinite(frost_min_c):
            frost_min_c = None
    except (TypeError, ValueError):
        frost_min_c = None
    winter_limit_c, warmth_need_c, heat_limit_c, thermal_source = authored_thermal_limits(entity)
    if frost_min_c is not None:
        thermal_source = ("authored frost_tolerance" if thermal_source == "limits shared by all plants"
                          else f"authored frost_tolerance over {thermal_source}")
    roles = entity.get("succession_roles") or entity.get("ecological_roles") or []
    if isinstance(roles, str):
        roles = [roles]
    roles = {str(role).strip().lower() for role in roles}
    explicit_tier = authored.get("succession_tier", entity.get("succession_tier"))
    try:
        succession_tier = max(0, min(3, int(explicit_tier)))
        succession_source = "authored succession_tier"
    except (TypeError, ValueError):
        if entity.get("biosphere_bootstrap_species") or growth_form in {"lichen", "aquatic"} or "primary_pioneer" in roles:
            succession_tier = 0
        elif growth_form in {"graminoid", "forb", "fern"}:
            succession_tier = 1
        elif growth_form in {"shrub", "subshrub", "succulent"}:
            succession_tier = 2
        elif growth_form == "tree":
            succession_tier = 3
        else:
            succession_tier = 1
        succession_source = "growth_form runtime default"
    from simulations.biosphere.soil_succession import SoilOrganicMatterField
    explicit_requirement = authored.get(
        "minimum_soil_organic_matter_kg_m2",
        entity.get("minimum_soil_organic_matter_kg_m2"),
    )
    try:
        organic_requirement = max(0.0, float(explicit_requirement))
        if not math.isfinite(organic_requirement):
            raise ValueError
        succession_source = f"{succession_source}; authored organic-matter requirement"
    except (TypeError, ValueError):
        organic_requirement = SoilOrganicMatterField.requirement_for_tier(succession_tier)
    return SpeciesProfile(
        species_id=species_id, label=str(label), growth_form=growth_form,
        growth_rate=_clamp(number("seasonal_growth_rate", defaults[0]), 0.01, 0.8),
        dispersal=_clamp(number("seasonal_dispersal", defaults[1]), 0.0, 0.45),
        carrying_biomass_kg_m2=(_clamp(number('carrying_biomass_kg_m2', defaults[2]), 0., 20.)
                              if growth.get('surface_growth_profile') else max(0.05, number("carrying_biomass_kg_m2", defaults[2]))),
        moisture_optimum=_clamp(number("moisture_optimum", moisture_default)),
        moisture_tolerance=max(0.08, number("moisture_tolerance", defaults[4])),
        light_minimum=_clamp(number("light_minimum", light_default)),
        color=(58 + digest[0] % 78, 122 + digest[1] % 112, 55 + digest[2] % 76),
        provenance="authored biosphere_growth_profile" if authored else f"visible {growth_form} runtime defaults",
        shade_tolerance=shade["tolerance"], light_requirement_source=light_source,
        mature_height_m=max(0.01, min(150.0, float(growth["max_height_m"]))),
        maturity_days=max(1.0, timing.maturity_days),
        establishment_days=max(1.0, min(timing.maturity_days, float(growth["maturity_days"]))),
        seed_days=max(1.0, timing.seed_days),
        lifespan_days=timing.lifespan_days,
        maturity_source=timing.maturity_source,
        lifespan_source=timing.lifespan_source,
        clonal_spread=str(growth.get("clonal_spread") or "other_unknown").strip().lower(),
        resprouting=str(entity.get("resprouting") or growth.get("resprouting") or "other_unknown").strip().lower(),
        soil_fertility_increment_per_season=_clamp(number('soil_fertility_increment_per_season', 0.), 0., .02),
        soil_fertility_bonus_cap=_clamp(number('soil_fertility_bonus_cap', 0.), 0., .5),
        crown_openness=_clamp(growth["crown_openness"]),
        succession_tier=succession_tier,
        soil_organic_requirement_kg_m2=organic_requirement,
        succession_source=succession_source,
        nitrogen_fixation=growth["nitrogen_fixation"],
        nutrition_mode=growth["nutrition_mode"],
        surface_growth_profile=growth.get("surface_growth_profile"),
        mycorrhizal_type=growth["mycorrhizal_type"],
        root_architecture=growth["root_architecture"] or "other_unknown",
        root_depth_class=growth["root_depth_class"] or "other_unknown",
        max_root_depth=growth["max_root_depth"],
        moisture_source=moisture_source,
        waterlogging_tolerance=waterlogging,
        waterlogging_source=waterlogging_source,
        salinity_tolerance=salinity,
        salinity_source=salinity_source,
        soil_ph_range=authored_soil_ph_range(entity),
        frost_min_c=frost_min_c,
        winter_limit_c=winter_limit_c,
        warmth_need_c=warmth_need_c,
        heat_limit_c=heat_limit_c,
        thermal_source=thermal_source,
    )


class BiosphereEcology:
    """Population patches spread and overlap in continuous world coordinates."""

    MODEL_VERSION = "biosphere-soil-succession-v1"
    DAYS_PER_SEASON = 91.3125

    def __init__(self, bounds, profiles, columns=None, rows=None):
        self.bounds = {key: float(bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}
        self.profiles = {profile.species_id: profile for profile in profiles}
        self.patches: list[PopulationPatch] = []
        self.introductions = []
        self.season = 0
        self._next_introduction = 1
        self._next_patch = 1
        self.canopy_light_enabled = True
        self._canopy_cache = None
        self._season_canopies = None
        self._canopy_arrays = None
        self.substrate = None
        self.soil = None
        self.representative_feedback = {}
        self.individuals = IndividualRegister()
        # What tells one site's run of flood years from another's, and what the last flood took.
        self.flood_seed = 0
        self.last_flood = None
        # The planet's kept plant pictures (``plant_pictures``), when the simulation has them.
        self.pictures = None

    # ------------------------------------------------------------------
    # Stands of individuals
    # ------------------------------------------------------------------
    # A grass below this height grows as a sward; above it (a bamboo) as plants.
    SWARD_HEIGHT_M = 2.5
    # How strongly a plant takes after the simulated plant nearest to it: drawn anew for each plant each season.
    NEIGHBOUR_EFFECT = (0.5, 1.5)

    def keeps_individuals(self, profile):
        """Whether a species is recorded plant by plant; a crust or a sward is cover and nothing else."""
        form = profile.growth_form
        return not (form == "lichen" or (form == "graminoid" and profile.mature_height_m < self.SWARD_HEIGHT_M))

    # A plant that grows into a clone metres wide takes at least this share of its width as ground.
    BODY_ROOM_SHARE = 0.30

    def spacing_m(self, profile):
        """The ground one full-grown plant takes.

        The room the display has always given its crown; and for a plant that
        is not a tree, at least a share of how wide the planet's kept
        individuals of it stand: a creeping thistle or a bamboo is a clone
        that fills a room, and a stand of them is not one every hand's breadth.
        """
        form = profile.growth_form
        spacing = max(VegetationSampler.SPACING_M.get(form, 0.28),
                      profile.mature_height_m * VegetationSampler.CROWN_SPACING.get(form, 0.0))
        if self.pictures is not None and form != "tree":
            spacing = max(spacing, self.BODY_ROOM_SHARE * self.pictures.body_width(profile.species_id))
        return spacing

    def _capacity(self, patch, profile):
        """How many plants a stand's disc has room for."""
        return max(1e-9, math.pi * patch.radius_m ** 2 / self.spacing_m(profile) ** 2)

    def _seed_members(self, patch, profile, records, rng, lag_days):
        """Root up to ``records`` new plants at free places in a stand; returns how many took."""
        if records <= 0:
            return 0
        register = self.individuals
        members = register.members(patch.patch_id)
        cell = self.spacing_m(profile) * math.sqrt(register.unit_of(patch.species_id))
        if members is None and records == 1:
            x, y = np.array([patch.x]), np.array([patch.y])  # the one plant set by hand stands where it was set
        else:
            tries = records * 3 + 4
            distance = patch.radius_m * np.sqrt(rng.random(tries))
            angle = rng.random(tries) * math.tau
            x, y = patch.x + np.cos(angle) * distance, patch.y + np.sin(angle) * distance
        bounds = self.bounds
        free = (x >= bounds["min_x"]) & (x <= bounds["max_x"]) & (y >= bounds["min_y"]) & (y <= bounds["max_y"])
        if self.canopy_light_enabled and profile.light_minimum > 0.0:
            # A seedling takes where the light at the ground lets it: at the
            # edge of a wood and in its gaps.  Its own stand's crowns are not
            # what keeps it out.
            sample = getattr(self.substrate, "sample_array", None)
            incident = (np.asarray(sample("surface_solar_exposure", x, y, 1.0), dtype=np.float64) if callable(sample)
                        else np.array([self._incident_light_at(px, py) for px, py in zip(x.tolist(), y.tolist())]))
            crowns = [canopy for canopy in self.canopy_footprints() if canopy["id"] != patch.patch_id]
            light = incident * _canopy_light(x, y, 0.05, crowns)
            free &= rng.random(len(x)) < np.clip((light / profile.light_minimum - 0.65) / 0.35, 0.0, 1.0)
        water = getattr(self.substrate, "open_water_array", None)
        if callable(water) and getattr(self.substrate, "native", None) is None:
            # Land plants root on land and water plants in water.
            free &= np.asarray(water(x, y), dtype=bool) == (profile.growth_form == "aquatic")
        # One plant to a place: a place is the ground a full-grown plant takes.
        place = np.floor(x / cell).astype(np.int64) * 2000003 + np.floor(y / cell).astype(np.int64)
        if members is not None and len(members):
            taken = np.floor(members.x / cell).astype(np.int64) * 2000003 + np.floor(members.y / cell).astype(np.int64)
            free &= ~np.isin(place, taken)
        _places, first = np.unique(place, return_index=True)
        chosen = np.sort(first[free[first]])[:records]
        if not len(chosen):
            return 0
        variants = self.pictures.count(patch.species_id) if self.pictures is not None else 0
        register.add(patch.patch_id, patch.species_id, x[chosen], y[chosen], lag_days, self.season,
                     rng.integers(0, max(1, variants), len(chosen)))
        return len(chosen)

    def _found_members(self, patch, profile):
        """Turn a new stand's cover into the plants it is: its founding cohort."""
        if self.pictures is not None:
            self.pictures.settle(patch.species_id, {"ground_light": self.ground_light_at(patch.x, patch.y)})
        unit = self.individuals.unit_of(patch.species_id)
        records = max(1, round(patch.abundance * self._capacity(patch, profile) / unit))
        # Fewer plants than one cannot be sown, and a stand is never less than the ground its plants take.
        patch.radius_m = max(patch.radius_m, self.spacing_m(profile) * math.sqrt(records * unit / math.pi))
        self._seed_members(patch, profile, records, np.random.default_rng((patch.seed, 0x5eed)), 0.0)
        self._fit_stand(patch, profile)

    def _fit_stand(self, patch, profile, hold=False):
        """Bring a stand's cover in line with the plants in it, and its rim with where they stand.

        ``hold`` widens the disc to hold every plant, after two stands were made one.
        """
        members = self.individuals.members(patch.patch_id)
        if members is None or not len(members):
            patch.abundance = 0.0
            return
        reach = self.spacing_m(profile) * math.sqrt(self.individuals.unit_of(patch.species_id))
        extent = float(np.hypot(members.x - patch.x, members.y - patch.y).max())
        # The rim runs no further ahead of the plants than their seedlings would root.
        patch.radius_m = max(0.12, min(patch.radius_m, extent + reach * 2.0))
        if hold:
            patch.radius_m = max(patch.radius_m, extent + reach * 0.5)
        patch.abundance = _clamp(members.plants() / self._capacity(patch, profile), 0.0, 0.98)

    def _neighbour_effect(self, species_id, x, y, effect, feedback):
        """Per plant, the growth multiplier and the mortality it takes from the simulated plant nearest to it.

        ``effect`` is how strongly each plant takes after it.  Before any
        plant of the species is simulated, the species' own figures stand in.
        """
        simulated = feedback.get("simulated") or ()
        if not len(simulated):
            growth = np.full(len(x), _clamp(feedback.get("growth_multiplier", 1.0), 0.25, 1.75))
            mortality = np.full(len(x), _clamp(feedback.get("mortality_pressure", 0.0), 0.0, 0.20))
        else:
            near = np.asarray(simulated, dtype=np.float64)
            nearest = np.argmin(np.hypot(x[:, None] - near[None, :, 0], y[:, None] - near[None, :, 1]), axis=1)
            growth, mortality = near[nearest, 2], near[nearest, 3]
        return np.clip(1.0 + (growth - 1.0) * effect, 0.25, 1.75), np.clip(mortality * effect, 0.0, 0.20)

    def _advance_members(self, patch, profile, members, suitability, recruitment, competition, overtopping, feedback):
        """One season for the plants of a stand: how many take root or die, which of them, and how each grows.

        The balance is the cover kernel's: growth that fades as the stand
        fills, less what stress and mortality take.  What is left over roots
        as seedlings; a shortfall is paid in plants, the young and those
        beside a failing simulated neighbour first.  A stand at its balance
        keeps the plants it has, and where the species holds at all the last
        plant of a stand is not lost to its own crowding.
        """
        register = self.individuals
        rng = np.random.default_rng((patch.seed, self.season))
        number = len(members)
        growth, mortality = self._neighbour_effect(
            patch.species_id, members.x, members.y, rng.uniform(*self.NEIGHBOUR_EFFECT, number), feedback)
        followed = (np.isin(members.uid, list(register.simulated)) if register.simulated
                    else np.zeros(number, dtype=bool))
        plants = members.plants()
        occupancy = min(0.98, plants / self._capacity(patch, profile))
        gain = (profile.growth_rate * suitability * recruitment
                * max(0.0, 1.0 - occupancy - competition * self.COMPETITION_SHARE)
                * float((members.count * growth).sum()))
        loss = ((1.0 - suitability) * self.STRESS_PER_SEASON + (1.0 - recruitment) * 0.35
                + overtopping * self.OVERTOPPED_STRESS_PER_SEASON) * plants + float((members.count * mortality).sum())
        net = gain - loss
        share = np.clip((patch.development_days - members.lag_days) / profile.maturity_days, 0.0, 1.0)
        dies = np.zeros(number, dtype=bool)
        if net < 0.0:
            holds = (profile.growth_rate * suitability * recruitment * max(0.0, 1.0 - competition * self.COMPETITION_SHARE)
                     * float(growth.mean()) > loss / plants)
            lost = min(number - (1 if holds else 0), int(rng.poisson(-net / max(1e-9, plants / number))))
            if lost > 0:
                # A plant followed in depth is the last to be given up, but it stands on the same ground.
                weight = ((1.5 - share) * (0.5 + mortality / max(1e-9, float(mortality.mean())))
                          * np.where(followed, 0.3, 1.0))
                dies[rng.choice(number, size=lost, replace=False, p=weight / weight.sum())] = True
        renewed = np.zeros(number, dtype=bool)
        if profile.lifespan_days:
            # A plant that has lived its span leaves its place to a seedling of its own.
            span = float(profile.lifespan_days) * (0.75 + 0.25 * ((members.uid * 7919) % 997) / 996.0)
            renewed = ((self.season - members.born) * self.DAYS_PER_SEASON >= span) & ~dies & ~followed
        # Each plant grows at its own pace beside the stand's founding cohort.
        step = self.DAYS_PER_SEASON * recruitment
        members.lag_days = members.lag_days + step * (1.0 - growth)
        seedling_lag = patch.development_days + step
        if renewed.any():
            members.lag_days[renewed] = seedling_lag
            members.born[renewed] = self.season
            variants = self.pictures.count(patch.species_id) if self.pictures is not None else 0
            members.variant[renewed] = rng.integers(0, max(1, variants), int(renewed.sum()))
            register.revision += 1
        register.remove(patch.patch_id, dies)
        if net > 0.0:
            self._seed_members(patch, profile, int(rng.poisson(net / register.unit_of(patch.species_id))), rng, seedling_lag)

    def species_individuals(self, species_id):
        """Every recorded plant of a species: places, share of full size, kept individual, count and id."""
        profile = self.profiles[species_id]
        columns = {name: [] for name in ("x", "y", "share", "grown_days", "variant", "count", "uid")}
        for patch in self.species_patches(species_id):
            members = self.individuals.members(patch.patch_id)
            if members is None or not len(members):
                continue
            columns["x"].append(members.x)
            columns["y"].append(members.y)
            grown = np.maximum(0.0, patch.development_days - members.lag_days)
            columns["grown_days"].append(grown)
            columns["share"].append(np.clip(grown / profile.maturity_days, 0.0, 1.0))
            columns["variant"].append(members.variant)
            columns["count"].append(members.count)
            columns["uid"].append(members.uid)
        return {name: (np.concatenate(parts) if parts else np.empty(0)) for name, parts in columns.items()}

    def follow_individual(self, uid, grown_days=None, variant=None):
        """Mark a recorded plant as simulated in depth, and let its record follow its body.

        Returns ``False`` if the plant no longer stands.
        """
        found = self.individuals.find(uid)
        if found is None:
            return False
        patch_id, index = found
        members = self.individuals.members(patch_id)
        self.individuals.simulated.add(int(uid))
        if grown_days is not None:
            patch = next(patch for patch in self.patches if patch.patch_id == patch_id)
            members.lag_days[index] = patch.development_days - float(grown_days)
        if variant is not None:
            members.variant[index] = int(variant)
        self.individuals.revision += 1
        return True

    def release_individual(self, uid, renew):
        """A simulated plant has died: its place goes to a seedling of its own, or falls empty."""
        self.individuals.simulated.discard(int(uid))
        found = self.individuals.find(uid)
        if found is None:
            return
        patch_id, index = found
        members = self.individuals.members(patch_id)
        if renew:
            patch = next(patch for patch in self.patches if patch.patch_id == patch_id)
            variants = self.pictures.count(patch.species_id) if self.pictures is not None else 0
            members.lag_days[index] = patch.development_days
            members.born[index] = self.season
            members.variant[index] = (int(uid) * 7919 + self.season) % max(1, variants)
            self.individuals.revision += 1
        else:
            gone = np.zeros(len(members), dtype=bool)
            gone[index] = True
            self.individuals.remove(patch_id, gone)

    def canopy_footprints(self):
        """Ecological patch envelopes, independent of decorative plant counts/LOD."""
        if self._season_canopies is not None:
            return self._season_canopies
        key = tuple(sorted((p.patch_id, p.species_id, p.x, p.y, p.radius_m,
                            p.abundance, p.development_days,
                            self.profiles[p.species_id].mature_height_m,
                            self.profiles[p.species_id].maturity_days,
                            self.profiles[p.species_id].crown_openness,
                            self.profiles[p.species_id].growth_form) for p in self.patches))
        if self._canopy_cache is not None and self._canopy_cache[0] == key:
            return self._canopy_cache[1]
        canopies = []
        for p in sorted(self.patches, key=lambda p: p.patch_id):
            profile = self.profiles[p.species_id]
            height = profile.mature_height_m * _clamp(p.development_days / profile.maturity_days)
            if profile.growth_form not in {"tree", "shrub", "subshrub"} or height < 0.25:
                continue
            canopies.append({"id": p.patch_id, "x": p.x, "y": p.y,
                             "height_m": height, "radius_m": p.radius_m,
                             "opacity": (0.90 - 0.50 * profile.crown_openness) * _clamp(p.abundance)})
        self._canopy_cache = key, canopies
        return canopies

    @contextmanager
    def canopies_held(self):
        """One canopy picture for a batch of questions.

        Outside a season every light question rebuilds the picture's key from
        all patches; a caller asking about hundreds of points holds it instead.
        Populations must not change inside.
        """
        if self._season_canopies is not None:
            yield
            return
        self._season_canopies = self.canopy_footprints()
        try:
            yield
        finally:
            self._season_canopies = None

    # Below this many crowns the plain loop is as fast as building arrays.
    CANOPY_ARRAY_MINIMUM = 12

    def _canopy_light_at(self, x, y, sample_height_m, canopies, exclude=None):
        """``forest_ecology.light_at`` over many crowns at once."""
        if np is None or len(canopies) < self.CANOPY_ARRAY_MINIMUM:
            return light_at(x, y, sample_height_m, canopies, exclude)
        held = getattr(self, "_canopy_arrays", None)
        if held is None or held[0] is not canopies or held[1] != len(canopies):
            held = (canopies, len(canopies), (
                np.array([canopy["x"] for canopy in canopies], dtype=np.float64),
                np.array([canopy["y"] for canopy in canopies], dtype=np.float64),
                np.array([canopy["radius_m"] * 1.25 for canopy in canopies], dtype=np.float64),
                np.array([canopy["height_m"] for canopy in canopies], dtype=np.float64),
                np.array([canopy["opacity"] for canopy in canopies], dtype=np.float64),
                {canopy["id"]: index for index, canopy in enumerate(canopies)},
            ))
            self._canopy_arrays = held
        centre_x, centre_y, reach, top, opacity, index = held[2]
        overlap = np.maximum(0.0, 1.0 - (np.hypot(x - centre_x, y - centre_y) / reach) ** 2)
        vertical = np.minimum(1.0, (top - sample_height_m) / (top * 0.35))
        passing = np.where(top > sample_height_m, 1.0 - overlap * vertical * opacity, 1.0)
        if exclude is not None and exclude in index:
            passing[index[exclude]] = 1.0
        return max(0.02, min(1.0, float(np.prod(passing))))

    def ground_light_at(self, x, y, sample_height_m=0.05, exclude_patch_id=None):
        """Available light including substrate exposure and shared crown attenuation."""
        incident = self._incident_light_at(x, y)
        if not self.canopy_light_enabled:
            return incident
        return incident * self._canopy_light_at(x, y, sample_height_m, self.canopy_footprints(), exclude_patch_id)

    def _incident_light_at(self, x, y):
        """Light reaching the ground before any canopy, from the substrate alone."""
        sample = getattr(self.substrate, "sample", None)
        if callable(sample):
            return sample("surface_solar_exposure", x, y, 1.0)
        return self.abiotic_environment_at(x, y)["surface_solar_exposure"]

    def _recruitment_response(self, species_id, light):
        if not self.canopy_light_enabled:
            return 1.0
        minimum = self.profiles[species_id].light_minimum
        if minimum <= 0.0:
            return 1.0
        # A short transition below the existing shade experiment's threshold.
        # These coefficients are qualitative, not measured seedling physiology.
        return _clamp((light / minimum - 0.65) / 0.35)

    def recruitment_at(self, species_id, x, y):
        return self._recruitment_response(species_id, self.ground_light_at(x, y))

    def _cohort_support(self, patch):
        """Area samples preserve bright margins of a seedbed with a dark centre."""
        factors, lights = [], []
        for index in range(25):
            radius = patch.radius_m * math.sqrt((index + 0.5) / 25)
            angle = index * 2.399963229728653
            x, y = patch.x + math.cos(angle) * radius, patch.y + math.sin(angle) * radius
            if not self.contains(x, y):
                continue
            light = self.ground_light_at(x, y)
            lights.append(light)
            factors.append(self._recruitment_response(patch.species_id, light))
        return ((sum(factors) / len(factors), sum(lights) / len(lights)) if factors else (0.0, 0.0))

    @property
    def width(self):
        return self.bounds["max_x"] - self.bounds["min_x"]

    @property
    def height(self):
        return self.bounds["max_y"] - self.bounds["min_y"]

    def contains(self, x, y):
        return self.bounds["min_x"] <= float(x) <= self.bounds["max_x"] and self.bounds["min_y"] <= float(y) <= self.bounds["max_y"]

    def abiotic_environment_at(self, x, y):
        """Return only inherited mineral/climate state, never biological soil."""
        if self.substrate is not None:
            return self.substrate.environment_at(x, y)
        nx = _clamp((float(x) - self.bounds["min_x"]) / max(0.001, self.width))
        ny = _clamp((float(y) - self.bounds["min_y"]) / max(0.001, self.height))
        channel = math.exp(-((nx - (0.23 + 0.18 * ny)) ** 2) / 0.006)
        ridge = math.exp(-((nx - 0.76) ** 2 + (ny - 0.30) ** 2) / 0.045)
        return {
            "elevation_norm": _clamp(0.18 + 0.46 * nx + 0.24 * ridge),
            "soil_moisture": _clamp(0.26 + 0.58 * channel + 0.18 * (1.0 - ny) - 0.17 * ridge),
            "soil_fertility": _clamp(0.48 + 0.28 * channel - 0.12 * ridge),
            "surface_solar_exposure": _clamp(0.82 - 0.16 * ny + 0.08 * ridge),
            "channel_presence": _clamp(channel),
            "temperature_k": 289.0,
            "runtime_default_fields": ("soil_fertility",),
            "parent_nitrogen_index": 0.18,
            "parent_phosphorus_index": 0.42,
        }

    def _substrate_environment_at(self, x, y):
        environment = self.abiotic_environment_at(x, y)
        environment = dict(environment)
        if self.soil is not None:
            organic = self.soil.environment_at(x, y)
            environment.update(organic)
            balance = water_ground(environment)
            if balance is not None:
                # Rain against demand through the year, with what the rooted soil stores, what runs on and
                # what ground water gives (``water_balance``).  A soil in the making stores more of it.
                from simulations.biosphere.water_balance import point_wetness

                developed = float(organic["soil_organic_matter_kg_m2"])
                developed = developed / (developed + RETENTION_HALF_KG_M2)
                raw = point_wetness(balance, REFERENCE_ROOT_DEPTH_M, 0.0)
                environment["water_balance"] = balance
                environment["soil_development"] = developed
                environment["map_wetness_index"] = float(environment.get("soil_moisture", 0.0))
                environment["abiotic_soil_moisture"] = raw
                environment["soil_moisture"] = point_wetness(balance, REFERENCE_ROOT_DEPTH_M, developed)
                environment["moisture_retention_bonus"] = environment["soil_moisture"] - raw
            elif "soil_moisture" in environment:
                abiotic_moisture = float(environment["soil_moisture"])
                precipitation = (
                    environment.get("annual_precipitation_mm")
                    if "annual_precipitation_mm" not in environment.get("runtime_default_fields", ()) else None
                )
                # Reckoned for the site's ordinary ground and added everywhere alike: a built soil holds more
                # water in a hollow and on a rise, and the hollow stays the wetter of the two.
                typical = float(environment.get("typical_soil_moisture", abiotic_moisture))
                bonus = moisture_retention_bonus(typical, organic["soil_organic_matter_kg_m2"], precipitation)
                environment["abiotic_soil_moisture"] = abiotic_moisture
                environment["moisture_retention_bonus"] = bonus
                environment["soil_moisture"] = _clamp(abiotic_moisture + bonus)
            unresolved = environment.get("runtime_default_fields", ())
            mineral_is_resolved = "soil_fertility" not in unresolved
            mineral = _clamp(environment.get("soil_fertility", 0.0)) if mineral_is_resolved else 0.0
            environment["mineral_nutrient_index"] = mineral if mineral_is_resolved else None
            environment["soil_fertility"] = _clamp(
                organic["organic_fertility_index"] if not mineral_is_resolved
                else mineral * 0.55 + organic["organic_fertility_index"] * 0.45
            )
            environment["soil_fertility_source"] = (
                "mineral substrate plus biosphere organic matter" if mineral_is_resolved
                else "biosphere organic matter; mineral nutrients unresolved"
            )
            if not mineral_is_resolved and "soil_ph" in environment and "soil_ph" not in unresolved:
                # No mineral fertility comes with generated ground, but its chemistry does: what life has
                # built counts as far as the soil's reaction and salt let plants use it.
                chemistry = mineral_soil_index(environment["soil_ph"], environment.get("soil_salinity_index", 0.0))
                environment["mineral_soil_index"] = chemistry
                environment["soil_fertility"] = _clamp(environment["soil_fertility"] * chemistry)
                environment["soil_fertility_source"] = "biosphere organic matter, as far as the soil's reaction and salt allow"
        else:
            bonus = sum(
                patch.soil_fertility_bonus * max(0.0, 1.0 - math.hypot(float(x) - patch.x, float(y) - patch.y) / max(0.05, patch.radius_m))
                for patch in self.patches if patch.soil_fertility_bonus > 0.0
            )
            environment["soil_fertility"] = _clamp(environment.get("soil_fertility", 0.0) + bonus)
        return environment

    def environment_at(self, x, y, sample_height_m=0.05, exclude_patch_id=None):
        environment = self._substrate_environment_at(x, y)
        environment["sample_x"] = float(x)
        environment["sample_y"] = float(y)
        environment["plant_available_light"] = self.ground_light_at(x, y, sample_height_m, exclude_patch_id)
        environment["ground_light_fraction"] = environment["plant_available_light"]
        incident = float(environment.get("surface_solar_exposure", 1.0) or 0.0)
        environment["canopy_shade"] = (
            _clamp(1.0 - environment["plant_available_light"] / incident) if incident > 0.0 else 0.0
        )
        return environment

    def _suitability(self, profile, environment):
        return self.suitability_factors(profile, environment)["suitability"]

    @staticmethod
    def wetness_for(profile, environment):
        """How wet a place is for a species: the same ground is wetter for roots that reach more soil or its water."""
        balance = environment.get("water_balance")
        if balance is None or profile.surface_growth_profile or profile.growth_form == "aquatic":
            return environment["soil_moisture"]
        from simulations.biosphere.water_balance import point_wetness

        return point_wetness(balance, rooting_depth_m(profile), environment.get("soil_development", 1.0))

    def suitability_factors(self, profile, environment):
        """Every term of a species' suitability at one place, by name.

        Water, soil organic matter and temperature are limits: the scarcest of
        them caps growth, because no amount of light or nitrogen replaces
        them.  Light, nutrients and fertility share the rest as a weighted
        mean.  ``suitability`` is what growth uses, ``limiting`` names the
        lowest score, so a failed planting can be explained.
        """
        scores = {}
        if self.substrate is not None and profile.growth_form != "aquatic" and (environment.get("open_water", False) or not environment.get("terrain_elevation_known", True)):
            return {"suitability": 0.0, "scores": {"habitat": 0.0}, "limiting": "habitat", "thermal_limit": None}
        wet = self.wetness_for(profile, environment)
        moisture_score = float(moisture_response(profile, wet))
        if profile.surface_growth_profile:
            from simulations.species.surface_growth import surface_activity
            moisture_score = surface_activity(profile.surface_growth_profile,environment)["surface_activity"]
        light = environment.get("plant_available_light", environment["surface_solar_exposure"])
        light_score = _clamp((light - profile.light_minimum) / max(0.08, 1.0 - profile.light_minimum))
        limits = [moisture_score]
        shared = [(self.LIGHT_WEIGHT, light_score)]
        scores["moisture"] = moisture_score
        scores["light"] = light_score
        rootable = rootable_depth_of(environment)
        if rootable is not None:
            # The depth of ground that can be rooted, a limit like water: no light or nitrogen replaces it.
            rooting = float(rooting_response(profile, rootable))
            if not profile.surface_growth_profile and profile.growth_form != "aquatic":
                limits.append(rooting)
                scores["rooting depth"] = rooting
        salt = salt_score(profile, environment)
        if salt is not None:
            # Sea water in reach of its roots, a limit like water itself.
            limits.append(salt)
            scores["salt"] = salt
        reaction = reaction_score(profile, environment)
        if reaction is not None:
            # A soil too sour or too limy for it: no soil that is built changes the rock it lies on.
            limits.append(reaction)
            scores["soil reaction"] = reaction
        if self.soil is not None:
            organic_support = self.soil.support_at(
                environment.get("sample_x", 0.0),
                environment.get("sample_y", 0.0),
                profile.soil_organic_requirement_kg_m2,
            ) if "sample_x" in environment else (
                1.0 if profile.soil_organic_requirement_kg_m2 <= 0.0 else
                _clamp((environment.get("soil_organic_matter_kg_m2", 0.0) / profile.soil_organic_requirement_kg_m2 - 0.45) / 0.55)
            )
            limits.append(organic_support)
            scores["organic soil"] = organic_support
            nutrient = resolve_plant_nutrient_response({
                "surface_growth_profile":profile.surface_growth_profile,
                "nitrogen_fixation": profile.nitrogen_fixation,
                "mycorrhizal_type": profile.mycorrhizal_type,
                "root_architecture": profile.root_architecture,
                "root_depth_class": profile.root_depth_class,
                "max_root_depth": profile.max_root_depth,
            }, environment)
            # The scarcer of the two nutrients speaks for both.
            shared.append((self.NUTRIENT_WEIGHT, min(nutrient["nitrogen_response"], nutrient["phosphorus_response"])))
            scores["nitrogen"] = nutrient["nitrogen_response"]
            scores["phosphorus"] = nutrient["phosphorus_response"]
        if not profile.surface_growth_profile and ("soil_fertility" not in environment.get("runtime_default_fields", ()) or self.soil is not None):
            shared.append((self.FERTILITY_WEIGHT, environment["soil_fertility"]))
        thermal, thermal_limit = thermal_response(profile, environment)
        if profile.surface_growth_profile and profile.surface_growth_profile.get('atmospheric_tolerance'):
            from simulations.species.surface_atmosphere import atmosphere_response
            response = atmosphere_response(profile.surface_growth_profile, environment)
            thermal = response.get('atmospheric_scores', {}).get('temperature_c', 1.)
            thermal_limit = 'authored surface growth temperature' if thermal < 1 else None
            scores['atmosphere'] = response['atmospheric_activity']
        limits.append(thermal)
        scores["temperature"] = thermal
        weight = sum(item[0] for item in shared)
        support = sum(item_weight * score for item_weight, score in shared) / max(1e-9, weight)
        return {
            "suitability": _clamp(min(limits) * support),
            "scores": scores,
            "limiting": min(scores, key=scores.get),
            "thermal_limit": thermal_limit,
            # How wet the place is for this plant (its own rooting depth where the ground tells a water balance).
            "wetness": wet,
        }

    # How strongly light, nutrients and fertility count against each other.
    LIGHT_WEIGHT, NUTRIENT_WEIGHT, FERTILITY_WEIGHT = 0.22, 0.18, 0.08
    STRESS_PER_SEASON = 0.075

    # What representatives typically report back as mortality pressure.
    TYPICAL_MORTALITY_PER_SEASON = 0.010

    def expected_cover(self, profile, suitability):
        """The cover a population settles at on open ground of this suitability.

        Where logistic growth balances the kernel's stress loss and a typical
        mortality.  Fast growers fill poorer ground than slow ones: at 60 %
        suitability a lichen settles near full cover, a tree near a third.
        Zero means a sown population dwindles.
        """
        if suitability <= 0.0:
            return 0.0
        loss = (1.0 - suitability) * self.STRESS_PER_SEASON + self.TYPICAL_MORTALITY_PER_SEASON
        return _clamp(1.0 - loss / (profile.growth_rate * suitability))

    def sustains(self, profile, suitability):
        """Whether a sparse population holds at this suitability."""
        return self.expected_cover(profile, suitability) > 0.0

    def site_potential(self, profile, environment):
        """What the site's water, temperature and depth of ground allow a species, at best.

        Soil, nutrients and shade are built or planted; water, temperature and
        the depth of the mineral ground come with the site.  Three situations
        are scored, each with every buildable term at its best:

        * ``raw``: on the mineral ground as it is, in the open;
        * ``open``: on mature soil (full water retention), in the open;
        * ``sheltered``: on mature soil under a closed canopy.
        """
        if self.substrate is not None and profile.growth_form != "aquatic" and environment.get("open_water", False):
            return {"raw": 0.0, "open": 0.0, "sheltered": 0.0, "moisture_mature": 0.0,
                    "thermal_open": 0.0, "thermal_sheltered": 0.0, "rooting": 0.0,
                    "wetness_raw": 1.0, "wetness_mature": 1.0, "flood_standing": 1.0}
        abiotic = float(environment.get("abiotic_soil_moisture", environment["soil_moisture"]))
        precipitation = (
            environment.get("annual_precipitation_mm")
            if "annual_precipitation_mm" not in environment.get("runtime_default_fields", ()) else None
        )
        typical = float(environment.get("typical_soil_moisture", abiotic))
        mature = _clamp(abiotic + moisture_retention_bonus(typical, 1e9, precipitation))
        balance = environment.get("water_balance")
        if balance is not None and not profile.surface_growth_profile and profile.growth_form != "aquatic":
            from simulations.biosphere.water_balance import point_wetness

            abiotic = point_wetness(balance, rooting_depth_m(profile), 0.0)
            mature = point_wetness(balance, rooting_depth_m(profile), 1.0)

        def moisture_score(wetness):
            return float(moisture_response(profile, wetness))

        thermal_open, _limit = thermal_response(profile, dict(environment, canopy_shade=0.0))
        thermal_sheltered, _limit = thermal_response(profile, dict(environment, canopy_shade=1.0))
        raw_soil = 1.0 if profile.soil_organic_requirement_kg_m2 <= 0.0 else 0.0
        rootable = rootable_depth_of(environment)
        rooting = 1.0 if rootable is None else float(rooting_response(profile, rootable))
        standing = 1.0
        if profile.growth_form != "aquatic" and FLOOD_REWORKING_FIELD in environment:
            standing = float(flood_standing_share(profile, environment[FLOOD_REWORKING_FIELD]))
        salt = salt_score(profile, environment)
        salt = 1.0 if salt is None else salt
        reaction = reaction_score(profile, environment)
        reaction = 1.0 if reaction is None else reaction
        return {
            "raw": min(moisture_score(abiotic), thermal_open, raw_soil, rooting, salt, reaction),
            "open": min(moisture_score(mature), thermal_open, rooting, salt, reaction),
            "sheltered": min(moisture_score(mature), thermal_sheltered, rooting, salt, reaction),
            # What the soil's reaction leaves a plant with an authored range of pH.
            "reaction": reaction,
            "moisture_mature": moisture_score(mature),
            "thermal_open": thermal_open,
            "thermal_sheltered": thermal_sheltered,
            "rooting": rooting,
            # What the sea water in reach of its roots leaves it; no soil that is built changes it.
            "salt": salt,
            # How wet the ground is for this plant, raw and with its soil built.
            "wetness_raw": abiotic,
            "wetness_mature": mature,
            # The share of this ground on which the river leaves the plant its years to grow up.
            "flood_standing": standing,
        }

    def _new_patch(self, species_id, x, y, radius_m, abundance, season_introduced, seed_text):
        digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
        patch = PopulationPatch(
            patch_id=f"population_patch_{self._next_patch:04d}", species_id=species_id,
            x=float(x), y=float(y), radius_m=max(0.12, float(radius_m)),
            abundance=_clamp(abundance, 0.01, 0.98), season_introduced=int(season_introduced),
            seed=int.from_bytes(digest[:4], "big"),
        )
        self._next_patch += 1
        self.patches.append(patch)
        profile = self.profiles[species_id]
        if self.keeps_individuals(profile):
            self._found_members(patch, profile)
        return patch

    def found_grown_stand(self, species_id, x, y, radius_m, plants_x, plants_y, grown, seed_text, cover=None,
                          variants=None):
        """A stand that is there already: full-grown, its plants where they stand.

        ``grown`` is each plant's share of its full size.  A species that is
        not recorded plant by plant (a sward, a crust) takes ``cover`` instead.
        ``variants`` says which of the species' kept individuals each plant
        is drawn as, for whoever knows the plants from elsewhere.
        Nothing is sown and no seedling has to find its light: this is not an
        introduction (``resident_start``).
        """
        profile = self.profiles[species_id]
        digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
        patch = PopulationPatch(
            patch_id=f"population_patch_{self._next_patch:04d}", species_id=species_id,
            x=float(x), y=float(y), radius_m=max(0.12, float(radius_m)),
            abundance=_clamp(0.01 if cover is None else cover, 0.01, 0.98), season_introduced=int(self.season),
            seed=int.from_bytes(digest[:4], "big"), development_days=float(profile.maturity_days),
        )
        self._next_patch += 1
        self.patches.append(patch)
        plants_x = np.asarray(plants_x, dtype=np.float64)
        if self.keeps_individuals(profile) and len(plants_x):
            if self.pictures is not None:
                self.pictures.settle(species_id, {"ground_light": self.ground_light_at(patch.x, patch.y)})
            grown = np.clip(np.asarray(grown, dtype=np.float64), 0.0, 1.0)
            kept = max(1, self.pictures.count(species_id) if self.pictures is not None else 1)
            number = np.arange(len(plants_x))
            self.individuals.add(
                patch.patch_id, species_id, plants_x, np.asarray(plants_y, dtype=np.float64),
                lag_days=(1.0 - grown) * profile.maturity_days,
                born=self.season - np.rint(grown * profile.maturity_days / self.DAYS_PER_SEASON).astype(np.int64),
                variant=((number * 7919 + patch.seed) if variants is None else np.asarray(variants, dtype=np.int64)) % kept,
            )
            members = self.individuals.members(patch.patch_id)
            patch.abundance = _clamp(members.plants() / self._capacity(patch, profile), 0.01, 0.98)
        return patch

    def introduce(self, species_id, x, y, radius_world, propagule_pressure=0.28):
        if species_id not in self.profiles or not self.contains(x, y):
            return None
        introduction = SpeciesIntroduction(
            introduction_id=f"introduction_{self._next_introduction:04d}", species_id=species_id,
            x=float(x), y=float(y), radius_world=max(0.18, float(radius_world)),
            propagule_pressure=_clamp(propagule_pressure, 0.02, 0.95), season=self.season,
        )
        self._next_introduction += 1
        self.introductions.append(introduction)
        self._new_patch(species_id, x, y, introduction.radius_world, introduction.propagule_pressure, self.season,
                        f"{species_id}:{x:.5f}:{y:.5f}:{self.season}:{introduction.introduction_id}")
        return introduction

    def species_patches(self, species_id=None):
        return [patch for patch in self.patches if species_id is None or patch.species_id == species_id]

    def abundance_at(self, species_id, x, y, habitat_checked=False):
        # Do not render or retain terrestrial populations beneath imported open water.
        # This is an occupancy guard, not species-specific flood/salinity physiology.
        # ``habitat_checked`` is for callers that tested the ground themselves.
        if (not habitat_checked and self.substrate is not None
                and self.profiles[species_id].growth_form != "aquatic" and not self.substrate.terrestrial_habitat_at(x,y)):
            return 0.0
        abundance = 0.0
        recruitment = None
        for patch in self.species_patches(species_id):
            distance = math.hypot(float(x) - patch.x, float(y) - patch.y)
            if distance <= patch.radius_m:
                factor = 1.0
                if patch.development_days < self.establishment_days(self.profiles[species_id]):
                    if recruitment is None:
                        recruitment = self.recruitment_at(species_id, x, y)
                    factor = recruitment
                elif patch.establishment_canopies is not None and self.canopy_light_enabled:
                    # Maturing a seedbed must not create adults in previously shaded holes.
                    incident = self._incident_light_at(x, y)
                    birth_light = incident * self._canopy_light_at(x, y, 0.05, patch.establishment_canopies)
                    factor = self._recruitment_response(species_id, birth_light)
                abundance += patch.abundance * factor * math.sqrt(max(0.0, 1.0 - distance / patch.radius_m))
        return _clamp(abundance)

    def total_abundance_at(self, x, y):
        return _clamp(sum(self.abundance_at(species_id, x, y) for species_id in self.profiles), 0.0, 4.0)

    def representative_sites(self, species_id, count=12):
        candidates = []
        # A species spread over many discs is represented from its strongest
        # few; probing all of them cost more than the season itself.
        patches = sorted(self.species_patches(species_id),
                         key=lambda patch: (-patch.abundance * patch.radius_m, patch.patch_id))[:8]
        for patch in patches:
            candidates.append((self.abundance_at(species_id, patch.x, patch.y), patch.x, patch.y))
            for index in range(24):
                angle = (patch.seed % 6283) / 1000.0 + index * 2.399963229728653
                distance = patch.radius_m * math.sqrt((index + .5) / 24)
                x, y = patch.x + math.cos(angle) * distance, patch.y + math.sin(angle) * distance
                if self.contains(x, y):
                    candidates.append((self.abundance_at(species_id, x, y), x, y))
        return sorted((c for c in candidates if c[0] > .003), key=lambda item: (-item[0], item[2], item[1]))[:max(0, int(count))]

    # A neighbour far below a plant only meets its roots; one standing well
    # above it takes its light and, over the years, its place.  What counts of
    # the neighbours' cover takes this share of the room a stand grows into.
    NEIGHBOUR_COMPETITION = 0.75
    UNDERSTOREY_COMPETITION = 0.15
    COMPETITION_SHARE = 0.55
    OVERTOPPED_STRESS_PER_SEASON = 0.04

    @classmethod
    def competition_weight(cls, own_stature_m, their_stature_m):
        """How much of another species' cover on the same ground counts against a stand of this stature."""
        return cls.UNDERSTOREY_COMPETITION if their_stature_m < own_stature_m * 0.25 else cls.NEIGHBOUR_COMPETITION

    @staticmethod
    def overtops(their_stature_m, own_stature_m):
        """Whether a neighbour stands far enough above a stand to take its light."""
        return their_stature_m > max(own_stature_m * 2.0, own_stature_m + 0.3)

    def _stature_m(self, patch):
        profile = self.profiles[patch.species_id]
        return profile.mature_height_m * _clamp(patch.development_days / profile.maturity_days)

    @staticmethod
    def establishment_days(profile):
        """How long a cohort stays a seedbed: the short developmental span, not the years to full size."""
        return getattr(profile, "establishment_days", None) or profile.maturity_days

    # A stand of seedlings carries next to nothing; biomass follows its height.
    JUVENILE_BIOMASS_SHARE = 0.02

    def stature_share(self, patch):
        """The share of its mature standing biomass a stand of this age carries per unit of cover."""
        profile = self.profiles[patch.species_id]
        members = self.individuals.members(patch.patch_id)
        if members is not None and len(members):
            # A stand of plants carries what its plants have grown to, the young ones among them too.
            share = np.clip((patch.development_days - members.lag_days) / profile.maturity_days,
                            self.JUVENILE_BIOMASS_SHARE, 1.0)
            count = members.count.astype(np.float64)
            return round(float((share * count).sum() / count.sum()), 12)
        return max(self.JUVENILE_BIOMASS_SHARE, _clamp(patch.development_days / profile.maturity_days))

    # Before a stand is old enough to set seed it only creeps outward, as far
    # as its plants spread vegetatively.
    JUVENILE_SPREAD_SHARE = {"high": 1.0, "moderate": 0.7, "low": 0.4}
    JUVENILE_SPREAD_DEFAULT = 0.25

    def _competition_at_patch(self, patch):
        """``(competition, overtopping)`` from every population sharing ground with this one."""
        own = self._stature_m(patch)
        total = overtopping = 0.0
        for other in self.patches:
            if other is patch:
                continue
            overlap = max(0.0, 1.0 - math.hypot(patch.x - other.x, patch.y - other.y) / max(0.05, patch.radius_m + other.radius_m))
            if overlap <= 0.0:
                continue
            if other.species_id == patch.species_id:
                weight = 0.45
            else:
                theirs = self._stature_m(other)
                weight = self.competition_weight(own, theirs)
                if self.overtops(theirs, own):
                    overtopping += other.abundance * overlap
            total += other.abundance * overlap * weight
        return _clamp(total), _clamp(overtopping)

    WIDE_STAND_RADIUS_M = 3.0

    def _stand_ring(self, patch, profile, sample_height_m):
        """Suitability summed over four points half-way out in a stand, and the number inside the area.

        Judged as the centre is: at the height the stand has reached, and
        without its own crowns shading it.
        """
        total, count = 0.0, 0
        for index in range(4):
            angle = (patch.seed % 6283) / 1000.0 + math.pi / 4.0 + index * math.tau / 4.0
            x = patch.x + math.cos(angle) * patch.radius_m * 0.55
            y = patch.y + math.sin(angle) * patch.radius_m * 0.55
            if self.contains(x, y):
                total += self._suitability(profile, self.environment_at(x, y, sample_height_m, patch.patch_id))
                count += 1
        return total, count

    def _edge_suitability(self, patch, profile):
        """Mean suitability just beyond a patch's rim, where it would spread next."""
        total = 0.0
        for index in range(4):
            angle = (patch.seed % 6283) / 1000.0 + index * math.tau / 4.0
            x = patch.x + math.cos(angle) * patch.radius_m * 1.08
            y = patch.y + math.sin(angle) * patch.radius_m * 1.08
            # Seedlings at the rim start at the ground; the stand's own crowns
            # are not what keeps them out.
            if self.contains(x, y):
                total += self._suitability(profile, self.environment_at(x, y, 0.05, patch.patch_id))
            else:
                # Beyond the simulated area conditions are unknown: assume the
                # patch's own, so the population can press on the edge and
                # make the area grow.
                total += self._suitability(profile, self.environment_at(patch.x, patch.y, 0.05, patch.patch_id))
        return total / 4.0

    # A front advances this many times the dimensionless dispersal trait per
    # season; with it a dense lichen crust gains about 1.5 m a year.
    SPREAD_SCALE = 4.0
    EDGE_REFRESH_SEASONS = 4
    # Populations are discs; a species never needs more of them than this to
    # describe where it grows.  Beyond it the two nearest are fused.
    MAX_PATCHES_PER_SPECIES = 48

    def _spawn_satellite(self, patch, profile, dispersal_multiplier):
        if patch.abundance < 0.42 or (self.season + patch.seed) % 3:
            return
        angle_seed = hashlib.sha256(f"{patch.patch_id}:{self.season}".encode("utf-8")).digest()
        angle = int.from_bytes(angle_seed[:2], "big") / 65535.0 * math.tau
        # Founders land anywhere from the rim to the form's reach beyond it.
        reach = _DISPERSAL_REACH_M.get(profile.growth_form, 8.0) * dispersal_multiplier
        distance = patch.radius_m * 1.05 + reach * (0.2 + 0.8 * angle_seed[2] / 255.0)
        x, y = patch.x + math.cos(angle) * distance, patch.y + math.sin(angle) * distance
        recruitment = self.recruitment_at(patch.species_id, x, y)
        if self.contains(x, y) and recruitment > 0.0 and self._suitability(profile, self.environment_at(x, y)) > 0.0:
            self._new_patch(patch.species_id, x, y, max(0.16, min(patch.radius_m * 0.24, reach * 0.2)),
                            max(0.035, patch.abundance * profile.dispersal * 0.55) * recruitment, self.season + 1,
                            f"satellite:{patch.patch_id}:{self.season}")

    def _consolidate_patches(self):
        """Fuse populations of one species that have grown into each other.

        A patch swallowed by a larger one of its species adds its plants to
        it.  If a species still holds more discs than it may, its two nearest
        are fused into one of the same total area.
        """
        by_species = {}
        for patch in self.patches:
            by_species.setdefault(patch.species_id, []).append(patch)
        removed = set()
        for patches in by_species.values():
            patches.sort(key=lambda item: (-item.radius_m, item.patch_id))
            for index, large in enumerate(patches):
                if large.patch_id in removed:
                    continue
                for small in patches[index + 1:]:
                    if small.patch_id in removed:
                        continue
                    if math.hypot(small.x - large.x, small.y - large.y) + small.radius_m <= large.radius_m * 1.1:
                        self._fuse(large, small, keep_footprint=True)
                        removed.add(small.patch_id)
            alive = [patch for patch in patches if patch.patch_id not in removed]
            while len(alive) > self.MAX_PATCHES_PER_SPECIES:
                first, second = min(
                    ((a, b) for i, a in enumerate(alive) for b in alive[i + 1:]),
                    key=lambda pair: (math.hypot(pair[0].x - pair[1].x, pair[0].y - pair[1].y)
                                      - pair[0].radius_m - pair[1].radius_m, pair[0].patch_id, pair[1].patch_id),
                )
                large, small = (first, second) if first.radius_m >= second.radius_m else (second, first)
                self._fuse(large, small, keep_footprint=False)
                removed.add(small.patch_id)
                alive.remove(small)
        if removed:
            self.patches = [patch for patch in self.patches if patch.patch_id not in removed]

    def _fuse(self, large, small, keep_footprint):
        """Absorb a stand into another, its plants with it."""
        grown_large, grown_small = large.development_days, small.development_days
        self._absorb(large, small, keep_footprint)
        if self.individuals.members(small.patch_id) is None and self.individuals.members(large.patch_id) is None:
            return
        # The stand's clock is now the older cohort's; every plant keeps the growth it had.
        self.individuals.merge(large.patch_id, small.patch_id,
                               large.development_days - grown_large, large.development_days - grown_small)
        self._fit_stand(large, self.profiles[large.species_id], hold=not keep_footprint)

    @staticmethod
    def _absorb(large, small, keep_footprint):
        large_area, small_area = large.radius_m ** 2, small.radius_m ** 2
        if keep_footprint:
            # The small disc lay inside the large one: same ground, more plants.
            large.abundance = _clamp(large.abundance + small.abundance * small_area / large_area, 0.01, 0.98)
        else:
            total = large_area + small_area
            large.x = (large.x * large_area + small.x * small_area) / total
            large.y = (large.y * large_area + small.y * small_area) / total
            large.abundance = _clamp(
                (large.abundance * large_area + small.abundance * small_area) / total, 0.01, 0.98)
            large.radius_m = math.sqrt(total)
            large.edge_suitability = None
            large.stand_ring = None
        large.development_days = max(large.development_days, small.development_days)

    def advance(self, seasons=1, representative_feedback=None):
        representative_feedback = representative_feedback or {}
        self.representative_feedback = representative_feedback
        for _ in range(max(0, int(seasons))):
            if self.season and self.season % 4 == 0:
                # Between two years: what was sown in a year has that year before the river comes.
                self._river_flood()
            # Freeze neighbour shade for the season; no generation-order light feedback.
            self._season_canopies = self.canopy_footprints()
            for patch in sorted(self.patches, key=lambda p: p.patch_id):
                profile = self.profiles[patch.species_id]
                feedback = representative_feedback.get(patch.species_id) or {}
                growth_multiplier = _clamp(feedback.get("growth_multiplier", 1.0), 0.25, 1.75)
                dispersal_multiplier = _clamp(feedback.get("dispersal_multiplier", 1.0), 0.25, 1.75)
                mortality = _clamp(feedback.get("mortality_pressure", 0.0), 0.0, 0.20)
                establishment = self.establishment_days(profile)
                juvenile = patch.development_days < establishment
                recruitment, seedbed_light = self._cohort_support(patch) if juvenile else (1.0, 0.0)
                height = profile.mature_height_m * _clamp(patch.development_days / profile.maturity_days)
                environment = self.environment_at(patch.x, patch.y, max(0.05, height * 0.5), patch.patch_id)
                if juvenile:
                    environment["plant_available_light"] = seedbed_light
                suitability = self._suitability(profile, environment)
                if patch.radius_m >= self.WIDE_STAND_RADIUS_M:
                    # A wide stand lives on more ground than the point at its
                    # centre: a sowing centred on a gully is not all gully.
                    if patch.stand_ring is None or (self.season + patch.seed) % self.EDGE_REFRESH_SEASONS == 0:
                        patch.stand_ring = self._stand_ring(patch, profile, max(0.05, height * 0.5))
                    ring_sum, ring_count = patch.stand_ring
                    suitability = (suitability + ring_sum) / (1 + ring_count)
                competition, overtopping = self._competition_at_patch(patch)
                members = self.individuals.members(patch.patch_id)
                if members is not None:
                    self._advance_members(patch, profile, members, suitability, recruitment, competition, overtopping, feedback)
                else:
                    growth = (profile.growth_rate * growth_multiplier * suitability * recruitment * patch.abundance
                              * max(0.0, 1.0 - patch.abundance - competition * self.COMPETITION_SHARE))
                    stress = ((1.0 - suitability) * self.STRESS_PER_SEASON + (1.0 - recruitment) * 0.35
                              + overtopping * self.OVERTOPPED_STRESS_PER_SEASON) * patch.abundance
                    patch.abundance = _clamp(patch.abundance + growth - stress - mortality * patch.abundance)
                patch.development_days += self.DAYS_PER_SEASON * recruitment
                if juvenile and patch.development_days >= establishment:
                    patch.establishment_canopies = tuple(dict(c) for c in self._season_canopies
                                                         if c["id"] != patch.patch_id)
                # A population only advances over ground that would carry it.
                if patch.edge_suitability is None or (self.season + patch.seed) % self.EDGE_REFRESH_SEASONS == 0:
                    patch.edge_suitability = self._edge_suitability(patch, profile)
                sets_seed = patch.development_days >= seed_days_of(profile)
                spread_share = 1.0 if sets_seed else self.JUVENILE_SPREAD_SHARE.get(
                    getattr(profile, "clonal_spread", ""), self.JUVENILE_SPREAD_DEFAULT)
                patch.radius_m = max(0.12, patch.radius_m + self.SPREAD_SCALE * profile.dispersal * dispersal_multiplier
                                     * recruitment * (0.12 + patch.abundance * 0.34) * patch.edge_suitability * spread_share)
                if self.soil is None and profile.soil_fertility_increment_per_season > 0:
                    patch.soil_fertility_bonus = _clamp(
                        patch.soil_fertility_bonus + patch.abundance * suitability * profile.soil_fertility_increment_per_season,
                        0.0, profile.soil_fertility_bonus_cap)
                if members is not None:
                    self._fit_stand(patch, profile)
                if sets_seed:
                    self._spawn_satellite(patch, profile, dispersal_multiplier)
            living = []
            for patch in self.patches:
                members = self.individuals.members(patch.patch_id)
                # A stand of plants lasts as long as one of them stands; a cover until it has thinned away.
                if (len(members) > 0) if members is not None else (patch.abundance > 0.006):
                    living.append(patch)
                else:
                    self.individuals.drop(patch.patch_id)
            self.patches = living
            self._consolidate_patches()
            for species_id in {patch.species_id for patch in self.patches}:
                if self.individuals.records(species_id) > self.individuals.RECORD_LIMIT:
                    self.individuals.coarsen(species_id, np.random.default_rng((self.season, len(species_id))))
            if self.soil is not None:
                self.soil.advance(self, 1)
            self._season_canopies = None
            self.season += 1
        return self.summary()

    def flood_of_year(self, year):
        """The size of a year's largest flood, as the years between floods that large.

        Drawn afresh for every year of a site: one year in two brings at least
        the two-year flood, one in ten the ten-year flood.
        """
        chance = float(np.random.default_rng((int(self.flood_seed), int(year))).random())
        return 1.0 / max(1.0 - chance, 1e-6)

    def _river_flood(self):
        """The year's largest flood takes what grows on the ground it reworks.

        Ground tells how often it is reworked (``world_gen.river_floods``); a
        flood at least that large takes the plants standing there one by one,
        and of a cover the share of its ground that lies that low.  What is
        left spreads back from the ground the flood did not reach.
        """
        self.last_flood = None
        substrate = self.substrate
        if substrate is None or (getattr(substrate, "fields", None) or {}).get(FLOOD_REWORKING_FIELD) is None:
            return
        size = self.flood_of_year(self.season // 4)

        def reworked(x, y):
            returns = np.asarray(substrate.sample_array(FLOOD_REWORKING_FIELD, x, y, FLOOD_NEVER_YEARS), dtype=np.float64)
            return np.nan_to_num(returns, nan=FLOOD_NEVER_YEARS) <= size

        lost, emptied = {}, set()
        for patch in self.patches:
            if self.profiles[patch.species_id].growth_form == "aquatic":
                continue
            members = self.individuals.members(patch.patch_id)
            if members is not None:
                if not len(members):
                    continue
                gone = reworked(members.x, members.y)
                if gone.any():
                    lost[patch.species_id] = lost.get(patch.species_id, 0) + int(np.asarray(members.count)[gone].sum())
                    self.individuals.remove(patch.patch_id, gone)
                    if not len(members):
                        emptied.add(patch.patch_id)
            else:
                turn = np.arange(8) * (math.tau / 8.0)
                share = float(reworked(np.concatenate([[patch.x], patch.x + 0.6 * patch.radius_m * np.cos(turn)]),
                                       np.concatenate([[patch.y], patch.y + 0.6 * patch.radius_m * np.sin(turn)])).mean())
                if share > 0.0:
                    lost.setdefault(patch.species_id, 0)
                    patch.abundance *= 1.0 - share
        for patch_id in emptied:
            self.individuals.drop(patch_id)
        if emptied:
            self.patches = [patch for patch in self.patches if patch.patch_id not in emptied]
        if lost:
            self.last_flood = {"season": self.season, "return_years": size, "lost": lost}

    def edge_abundance(self, ignore=()):
        """The densest stand that has reached the rim of the domain; ``ignore`` names species that do not count."""
        return max((patch.abundance for patch in self.patches if patch.species_id not in ignore and (
                    patch.x - patch.radius_m <= self.bounds["min_x"] or patch.x + patch.radius_m >= self.bounds["max_x"] or
                    patch.y - patch.radius_m <= self.bounds["min_y"] or patch.y + patch.radius_m >= self.bounds["max_y"])), default=0.0)

    def expand(self, margin_cells=4, limit=None):
        """Grow the domain on every side; ``limit`` is the frame it may not leave."""
        margin = max(0.5, min(self.width, self.height) * 0.2)
        self.bounds = {
            "min_x": self.bounds["min_x"] - margin, "max_x": self.bounds["max_x"] + margin,
            "min_y": self.bounds["min_y"] - margin, "max_y": self.bounds["max_y"] + margin,
        }
        if limit is not None:
            self.bounds = {
                "min_x": max(float(limit["min_x"]), self.bounds["min_x"]),
                "max_x": min(float(limit["max_x"]), self.bounds["max_x"]),
                "min_y": max(float(limit["min_y"]), self.bounds["min_y"]),
                "max_y": min(float(limit["max_y"]), self.bounds["max_y"]),
            }
        return 0, 0

    def population_footprints(self):
        return [{"patch_id": patch.patch_id, "species_id": patch.species_id, "x": patch.x, "y": patch.y,
                 "radius_m": patch.radius_m, "abundance": patch.abundance,
                 "color": self.profiles[patch.species_id].color} for patch in self.patches]

    def summary(self):
        domain_area = max(0.01, self.width * self.height)
        total_kg = 0.0
        footprint = 0.0
        species = []
        for species_id, profile in self.profiles.items():
            patches = self.species_patches(species_id)
            if not patches:
                continue
            area = sum(math.pi * patch.radius_m ** 2 for patch in patches)
            biomass = sum(math.pi * patch.radius_m ** 2 * patch.abundance * profile.carrying_biomass_kg_m2
                          * self.stature_share(patch) for patch in patches)
            footprint += area
            total_kg += biomass
            members = [self.individuals.members(patch.patch_id) for patch in patches]
            species.append({"species_id": species_id, "population_patches": len(patches),
                            # ``None`` for a crust or a sward, which is cover and not a count of plants.
                            "individuals": (round(sum(m.plants() for m in members if m is not None))
                                            if self.keeps_individuals(profile) else None),
                            "shade_tolerance": profile.shade_tolerance, "light_minimum": profile.light_minimum,
                            "light_requirement_source": profile.light_requirement_source,
                            "established_patches": sum(patch.abundance >= 0.18 for patch in patches),
                            "biomass_kg": round(biomass, 3)})
        established = sum(item["established_patches"] for item in species)
        result = {
            "model_version": self.MODEL_VERSION, "spatial_model": "continuous_population_patches",
            "recruitment_model": "canopy_light_v1" if self.canopy_light_enabled else "disabled_control",
            "season": self.season, "introductions": len(self.introductions),
            "population_patch_count": len(self.patches), "occupied_cell_species": len(self.patches),
            "established_cell_species": established, "biomass_index": round(total_kg, 3),
            "living_biomass_kg": round(total_kg, 3), "living_footprint_m2": round(min(domain_area, footprint), 3),
            "species": species,
        }
        if self.soil is not None:
            result["soil"] = self.soil.summary()
        return result
