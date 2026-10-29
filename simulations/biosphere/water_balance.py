"""How wet a place is for a plant: rain against demand, month by month, with what its rooted soil stores.

"Wet" and "dry" are not properties of the ground alone.  Stephenson (1990,
1998) showed that vegetation follows the soil water balance, not rain or
temperature: how much water is used (actual evapotranspiration) and how much
is missing (the deficit) once supply and demand are set against each other
through the year with the soil as a store.  The method is Thornthwaite and
Mather's (1955) monthly book-keeping:

* every month rain (and what runs on from upslope) meets the demand of the
  air (potential evapotranspiration);
* what rain does not cover is drawn from the water the rooted soil holds,
  ever harder the emptier it is; what is left over refills it, and the excess
  drains away;
* rain comes in showers, and a store smaller than a shower loses the rest of
  it (Milly 1994: the yearly balance turns on the store against the depth of
  a storm, beside rain against demand);
* where roots or the capillary fringe above them reach the water table, the
  ground water makes up what is missing (Fan et al. 2017: roots follow
  infiltration on well-drained uplands, reach for the capillary fringe where
  it lies within metres, and stay shallow where the table is at the surface).

The store is the soil's available water capacity (field capacity less wilting
point, by texture: Salter & Williams 1969) times the depth the plant roots
through it.  So the same ground is drier for a herb than for a deep-rooted
tree where the table lies between their depths, a slope turned to the sun is
drier than one turned away (demand), and a sand is drier than a loam under
the same rain (supply): different "dries" (Stephenson 1998).

The result is the share of the demand that is met, ``alpha = AET / PET``
(Prentice et al. 1992 draw the limits of the world's biomes on it), and it is
read onto the Biosphere's wetness scale, on which species' preferences are
authored: 0.08 very dry, 0.20 dry, 0.42 mesic, 0.58 moist, 0.78 wet.  Above
"fresh" it is the water table that decides, as in the actual soil moisture
regime of forest site classification (Klinka et al. 1989: classes by length
of the deficit below, by depth to the water table above: wet within 30 cm,
very moist to 60 cm, moist to a metre).  The table counts for a plant as far
as its roots or the ground's capillary rise reach it: a table a metre down
keeps a loam moist for a herb and leaves the surface of a gravel dry, while
the tree rooted through that gravel stands in it.

Ground can also be wet for want of drainage alone.  What a month's rain
leaves over once demand is met and the store is full has to go down through
the subsoil; where that passes less than arrives (a heavy clay, a silted
channel fill), the water stands in the soil above it: the perched water of
a pseudogley or stagnosol, gone again in the dry season.  The share of the
year it stands is read onto the same scale above "fresh" as a water table,
after the lengths of waterlogging plants are classed by (Niinemets &
Valladares 2006: a week or two, a month, most of the growing season).

The figures of the two scales, of a shower and of raw ground are this
module's reading of those sources, not theirs.

Every function takes numbers or arrays of one shape; the twelve months are
the first axis (month 0 is midwinter).  ``point_wetness`` is the same
arithmetic in plain floats for the one place the kernel asks about at a time.
"""

from __future__ import annotations

import math

import numpy as np

MONTHS = 12
# The share of the yearly demand met, against the wetness it stands for.  Prentice et al. (1992): desert
# below about 0.2, grass and scrub from 0.2 to 0.3, dry woodland to 0.65, forest from 0.65, rain forest 0.8.
ALPHA_TO_WETNESS = ((0.0, 0.02), (0.18, 0.08), (0.30, 0.20), (0.65, 0.36), (0.80, 0.42), (1.0, 0.50))
# Depth to the water table in metres, against the wetness of the ground above it for a plant it reaches:
# wet within 30 cm, very moist to 60 cm, moist to a metre, fresh from a metre and a half.
WATER_TABLE_TO_WETNESS = ((0.0, 0.90), (0.15, 0.78), (0.45, 0.68), (0.8, 0.58), (1.5, 0.50))
# Demand follows the sun on the slope for the part of it that is radiation (Priestley & Taylor 1972 have
# radiation carry about two thirds of evaporation from wet surfaces).
DEMAND_RADIATION_SHARE = 0.65
# Demand swings through the year with temperature: by this share of its mean for a range of thirty kelvin
# between the coldest and the warmest month.
DEMAND_SWING_PER_30_K = 0.9
# Rain of a wet day, in millimetres: a store this deep keeps 63 % of a shower, one three times as deep 95 %.
SHOWER_MM = 12.0
# Raw mineral ground keeps this share of what the same ground holds once a soil has formed on it: no crumb,
# a sealing surface, rain running off instead of in.  A runtime assumption of the terraforming loop.
RAW_GROUND_STORAGE_SHARE = 0.35
# The least a plant has to draw on, in millimetres: the film of water in whatever it roots in.
LEAST_STORAGE_MM = 5.0
# Years the book-keeping is run before the last is read: the store starts full and settles.
SETTLING_YEARS = 3
# Where a map gives no figure of its own.
DEFAULT_AVAILABLE_WATER_MM_PER_M = 150.0
DEFAULT_CAPILLARY_RISE_M = 1.0
# The wetness rain alone brings ground to, all its demand met: above it water stands in the roots.
FRESH_WETNESS = ALPHA_TO_WETNESS[-1][1]
# Wetness of ground waterlogged all year, and how the share of the year it is waterlogged is read between
# that and fresh: two weeks 0.56, a month 0.59, three months 0.67, half the year 0.76.
SODDEN_WETNESS = 0.90
WATERLOGGED_EXPONENT = 0.6
DAYS_PER_MONTH = 365.25 / MONTHS
# Perched water stands on the subsoil: what fills before it does is the soil above that, not the roots of
# whoever asks.  Reckoned with a plant's own store, a tree's deep roots took up the surplus a herb's could
# not, and the tree read drier than the herb on the same sodden ground.
PERCHED_SOIL_DEPTH_M = 1.0

_WAVE = tuple(math.cos(math.tau * (month - 6) / MONTHS) for month in range(MONTHS))


def _swing(coldest_month_k, warmest_month_k):
    spread = np.asarray(warmest_month_k, dtype=np.float64) - np.asarray(coldest_month_k, dtype=np.float64)
    return np.where(np.isfinite(spread), np.clip(spread / 30.0 * DEMAND_SWING_PER_30_K, 0.05, 0.95), 0.3)


def monthly_rain(annual_mm, driest_month_mm=None, wettest_month_mm=None, summer_fraction=None):
    """Twelve monthly rains from a year's total, its driest and wettest month and the share that falls in summer.

    A single wave through the year, highest in midsummer or midwinter as the
    summer share says.
    """
    annual = np.maximum(0.0, np.asarray(annual_mm, dtype=np.float64))
    mean = annual / MONTHS
    if driest_month_mm is None or wettest_month_mm is None:
        swing = np.zeros(annual.shape)
    else:
        swing = np.clip(np.nan_to_num(
            (np.asarray(wettest_month_mm, dtype=np.float64) - np.asarray(driest_month_mm, dtype=np.float64)) * 0.5), 0.0, mean)
    sign = 1.0 if summer_fraction is None else np.where(np.asarray(summer_fraction, dtype=np.float64) >= 0.5, 1.0, -1.0)
    wave = np.asarray(_WAVE).reshape((MONTHS,) + (1,) * annual.ndim)
    return mean[None, ...] + (swing * sign)[None, ...] * wave


def monthly_demand(annual_mm, coldest_month_k=None, warmest_month_k=None, exposure=1.0):
    """Twelve monthly demands of the air from a year's total, the year's temperature range and the slope's sun."""
    annual = np.maximum(0.0, np.asarray(annual_mm, dtype=np.float64))
    swing = (np.full(annual.shape, 0.3) if coldest_month_k is None or warmest_month_k is None
             else _swing(coldest_month_k, warmest_month_k))
    sun = (1.0 - DEMAND_RADIATION_SHARE) + DEMAND_RADIATION_SHARE * np.clip(
        np.nan_to_num(np.asarray(exposure, dtype=np.float64), nan=1.0), 0.0, 1.0)
    wave = np.asarray(_WAVE).reshape((MONTHS,) + (1,) * annual.ndim)
    return (annual * sun / MONTHS)[None, ...] * (1.0 + swing[None, ...] * wave)


def storage_mm(available_water_mm_per_m, root_depth_m, rootable_depth_m=None, development=1.0):
    """The water a plant's rooted soil holds for it, in millimetres.

    ``development`` is how far a soil has formed on the ground (0 raw, 1
    built): raw ground keeps ``RAW_GROUND_STORAGE_SHARE`` of the store.
    """
    depth = np.asarray(root_depth_m, dtype=np.float64)
    if rootable_depth_m is not None:
        ground = np.asarray(rootable_depth_m, dtype=np.float64)
        depth = np.where(np.isnan(ground), depth, np.minimum(depth, ground))
    formed = RAW_GROUND_STORAGE_SHARE + (1.0 - RAW_GROUND_STORAGE_SHARE) * np.clip(development, 0.0, 1.0)
    return np.maximum(LEAST_STORAGE_MM, np.asarray(available_water_mm_per_m, dtype=np.float64) * depth * formed)


def groundwater_reach(root_depth_m, capillary_rise_m, water_table_depth_m):
    """How much of what is missing the ground water makes up, 0..1.

    All of it where the table lies within the roots, none where it lies
    below them by more than the capillary rise of the ground.
    """
    table = np.asarray(water_table_depth_m, dtype=np.float64)
    rise = np.maximum(0.05, np.asarray(capillary_rise_m, dtype=np.float64))
    reach = np.clip((np.asarray(root_depth_m, dtype=np.float64) + rise - table) / rise, 0.0, 1.0)
    return np.where(np.isnan(table), 0.0, reach)


def demand_met(rain, demand, store_mm, lateral_mm=0.0, groundwater=0.0):
    """The share of the year's demand that is met, ``AET / PET``, by Thornthwaite and Mather's book-keeping.

    ``lateral_mm`` is the water a year brings in from upslope (or, negative,
    sends on); ``groundwater`` is ``groundwater_reach``.
    """
    return _book_keeping(rain, demand, store_mm, lateral_mm, groundwater)[0]


def waterlogged_share(rain, demand, soil_store_mm, lateral_mm, drainage_mm_per_day):
    """The share of the year a soil stands waterlogged for want of drainage.

    ``soil_store_mm`` is what the soil above its subsoil holds
    (``PERCHED_SOIL_DEPTH_M`` of it); ``drainage_mm_per_day`` what the
    subsoil lets through.  What a month leaves over once demand is met and
    that store is full has to drain; what does not pass stands in the soil.
    """
    return _book_keeping(rain, demand, soil_store_mm, lateral_mm, 0.0, drainage_mm_per_day)[1]


def _book_keeping(rain, demand, store_mm, lateral_mm=0.0, groundwater=0.0, drainage_mm_per_day=None):
    """``(share of demand met, share of the year waterlogged)`` of one store through the months."""
    rain, demand = np.asarray(rain, dtype=np.float64), np.asarray(demand, dtype=np.float64)
    capacity = np.maximum(LEAST_STORAGE_MM, np.asarray(store_mm, dtype=np.float64))
    yearly = rain.sum(axis=0)
    # Run-on comes with the rain that causes it; ground that sheds cannot shed more than falls.  Of every
    # shower the store keeps what it has room for.
    gain = np.maximum(-0.9, np.asarray(lateral_mm, dtype=np.float64) / np.maximum(yearly, 1e-9))
    supply = rain * (1.0 + gain) * (1.0 - np.exp(-capacity / SHOWER_MM))
    held = capacity * np.ones(np.broadcast(supply[0], capacity, groundwater).shape)
    passes = None if drainage_mm_per_day is None else np.maximum(
        np.asarray(drainage_mm_per_day, dtype=np.float64) * DAYS_PER_MONTH, 1e-6)
    used = waterlogged = 0.0
    for _year in range(SETTLING_YEARS):
        used, waterlogged = np.zeros(held.shape), np.zeros(held.shape)
        for month in range(MONTHS):
            short = demand[month] - supply[month]
            drawn = held * (1.0 - np.exp(-np.maximum(short, 0.0) / capacity))
            met = np.where(short <= 0.0, demand[month], supply[month] + drawn)
            if passes is not None:
                # What is left over once demand is met and the store is full has to drain; what the subsoil
                # does not pass in the month stands in the soil.
                left = np.maximum(0.0, -short - (capacity - held))
                waterlogged = waterlogged + np.clip((left - passes) / passes, 0.0, 1.0) / MONTHS
            held = np.where(short <= 0.0, np.minimum(capacity, held - short), held - drawn)
            used = used + met + groundwater * (demand[month] - met)
    alpha = np.clip(used / np.maximum(demand.sum(axis=0), 1e-9), 0.0, 1.0)
    return alpha, (0.0 if passes is None else np.where(np.isfinite(passes), waterlogged, 0.0))


def _read(scale, value):
    xs, ys = zip(*scale)
    return np.interp(value, xs, ys)


def waterlogged_wetness(share_of_year):
    """The wetness of ground that stands waterlogged for a share of the year (0 for none)."""
    share = np.clip(np.asarray(share_of_year, dtype=np.float64), 0.0, 1.0)
    return np.where(share > 0.0, FRESH_WETNESS + (SODDEN_WETNESS - FRESH_WETNESS) * share ** WATERLOGGED_EXPONENT, 0.0)


def wetness(alpha, water_table_depth_m=None, reach=1.0, waterlogged=0.0):
    """The Biosphere's wetness for a share of demand met, a depth to a water table within ``reach`` (0..1)
    and a share of the year the soil stands waterlogged for want of drainage."""
    wet = _read(ALPHA_TO_WETNESS, np.asarray(alpha, dtype=np.float64))
    if water_table_depth_m is not None:
        table = np.asarray(water_table_depth_m, dtype=np.float64)
        near = np.where(np.isnan(table), 0.0, _read(WATER_TABLE_TO_WETNESS, np.nan_to_num(table)))
        wet = wet + np.asarray(reach, dtype=np.float64) * np.maximum(0.0, near - wet)
    return np.maximum(wet, waterlogged_wetness(waterlogged))


def plant_wetness(ground, root_depth_m, development=1.0):
    """How wet a place is for a plant that roots ``root_depth_m`` deep, on the Biosphere's scale.

    ``ground`` holds what the place gives: ``rain`` and ``demand`` (from
    ``monthly_rain`` and ``monthly_demand``), ``available_water_mm_per_m``,
    and where known ``rootable_depth_m``, ``lateral_mm``,
    ``capillary_rise_m``, ``water_table_depth_m`` and ``drainage_mm_per_day``.
    """
    table = ground.get("water_table_depth_m")
    rise = ground.get("capillary_rise_m", DEFAULT_CAPILLARY_RISE_M)
    store = storage_mm(ground.get("available_water_mm_per_m", DEFAULT_AVAILABLE_WATER_MM_PER_M), root_depth_m,
                       ground.get("rootable_depth_m"), development)
    reach = 0.0 if table is None else groundwater_reach(root_depth_m, rise, table)
    alpha = demand_met(ground["rain"], ground["demand"], store, ground.get("lateral_mm", 0.0), reach)
    drainage = ground.get("drainage_mm_per_day")
    if drainage is None:
        return wetness(alpha, table, reach)
    # The same for every plant of a place: reckoned once and kept with the ground.
    kept = ground.setdefault("_waterlogged", {})
    if development not in kept:
        soil = storage_mm(ground.get("available_water_mm_per_m", DEFAULT_AVAILABLE_WATER_MM_PER_M), PERCHED_SOIL_DEPTH_M,
                          ground.get("rootable_depth_m"), development)
        kept[development] = waterlogged_share(ground["rain"], ground["demand"], soil, ground.get("lateral_mm", 0.0), drainage)
    return wetness(alpha, table, reach, kept[development])


# ----------------------------------------------------------------------
# One place at a time, in plain floats
# ----------------------------------------------------------------------
def point_ground(annual_rain_mm, annual_demand_mm, *, driest_month_mm=None, wettest_month_mm=None,
                 summer_fraction=None, coldest_month_k=None, warmest_month_k=None, exposure=1.0,
                 available_water_mm_per_m=DEFAULT_AVAILABLE_WATER_MM_PER_M, rootable_depth_m=None, lateral_mm=0.0,
                 capillary_rise_m=DEFAULT_CAPILLARY_RISE_M, water_table_depth_m=None, drainage_mm_per_day=None):
    """What one place gives, ready for ``point_wetness``: the months as tuples of floats.

    ``monthly_rain`` and ``monthly_demand`` in plain floats.
    """
    known = lambda value: value is not None and math.isfinite(float(value))  # noqa: E731
    mean = max(0.0, float(annual_rain_mm)) / MONTHS
    swing = 0.0
    if known(driest_month_mm) and known(wettest_month_mm):
        swing = min(mean, max(0.0, (float(wettest_month_mm) - float(driest_month_mm)) * 0.5))
    if summer_fraction is not None and not float(summer_fraction) >= 0.5:
        swing = -swing
    rain = tuple(mean + swing * wave for wave in _WAVE)
    yearly = 0.3
    if known(coldest_month_k) and known(warmest_month_k):
        yearly = min(0.95, max(0.05, (float(warmest_month_k) - float(coldest_month_k)) / 30.0 * DEMAND_SWING_PER_30_K))
    sun = (1.0 - DEMAND_RADIATION_SHARE) + DEMAND_RADIATION_SHARE * (
        max(0.0, min(1.0, float(exposure))) if known(exposure) else 1.0)
    monthly = max(0.0, float(annual_demand_mm)) * sun / MONTHS
    demand = tuple(monthly * (1.0 + yearly * wave) for wave in _WAVE)
    return {
        "rain": rain, "demand": demand,
        "available_water_mm_per_m": float(available_water_mm_per_m),
        "rootable_depth_m": float(rootable_depth_m) if known(rootable_depth_m) else None,
        "lateral_mm": float(lateral_mm or 0.0), "capillary_rise_m": max(0.05, float(capillary_rise_m)),
        "water_table_depth_m": float(water_table_depth_m) if known(water_table_depth_m) else None,
        "drainage_mm_per_day": max(1e-6, float(drainage_mm_per_day)) if known(drainage_mm_per_day) else None,
    }


def _read_point(scale, value):
    for (x0, y0), (x1, y1) in zip(scale, scale[1:]):
        if value <= x1:
            return y0 if value <= x0 else y0 + (y1 - y0) * (value - x0) / (x1 - x0)
    return scale[-1][1]


def point_wetness(ground, root_depth_m, development=1.0):
    """``plant_wetness`` for one place (``point_ground``), in plain floats: the kernel asks it stand by stand."""
    depth = float(root_depth_m)
    if ground["rootable_depth_m"] is not None:
        depth = min(depth, ground["rootable_depth_m"])
    formed = RAW_GROUND_STORAGE_SHARE + (1.0 - RAW_GROUND_STORAGE_SHARE) * max(0.0, min(1.0, float(development)))
    capacity = max(LEAST_STORAGE_MM, ground["available_water_mm_per_m"] * depth * formed)
    table, rise = ground["water_table_depth_m"], ground["capillary_rise_m"]
    reach = 0.0 if table is None else max(0.0, min(1.0, (float(root_depth_m) + rise - table) / rise))
    rain, demand = ground["rain"], ground["demand"]
    yearly = sum(rain)
    gain = 1.0 + max(-0.9, ground["lateral_mm"] / max(yearly, 1e-9))
    kept = gain * (1.0 - math.exp(-capacity / SHOWER_MM))
    held, used = capacity, 0.0
    for _year in range(SETTLING_YEARS):
        used = 0.0
        for month in range(MONTHS):
            short = demand[month] - rain[month] * kept
            if short <= 0.0:
                met, held = demand[month], min(capacity, held - short)
            else:
                drawn = held * (1.0 - math.exp(-short / capacity))
                met, held = demand[month] - short + drawn, held - drawn
            used += met + reach * (demand[month] - met)
    alpha = max(0.0, min(1.0, used / max(sum(demand), 1e-9)))
    wet = _read_point(ALPHA_TO_WETNESS, alpha)
    if reach > 0.0:
        wet += reach * max(0.0, _read_point(WATER_TABLE_TO_WETNESS, table) - wet)
    waterlogged = _point_waterlogged(ground, formed, gain)
    if waterlogged > 0.0:
        wet = max(wet, FRESH_WETNESS + (SODDEN_WETNESS - FRESH_WETNESS) * min(1.0, waterlogged) ** WATERLOGGED_EXPONENT)
    return wet


def _point_waterlogged(ground, formed, gain):
    """``waterlogged_share`` for one place: the same for every plant there, so reckoned once and kept."""
    drainage = ground.get("drainage_mm_per_day")
    if drainage is None:
        return 0.0
    kept = ground.setdefault("_waterlogged", {})
    if formed in kept:
        return kept[formed]
    depth = PERCHED_SOIL_DEPTH_M if ground["rootable_depth_m"] is None else min(PERCHED_SOIL_DEPTH_M, ground["rootable_depth_m"])
    capacity = max(LEAST_STORAGE_MM, ground["available_water_mm_per_m"] * depth * formed)
    passes = max(drainage * DAYS_PER_MONTH, 1e-6)
    share = gain * (1.0 - math.exp(-capacity / SHOWER_MM))
    rain, demand = ground["rain"], ground["demand"]
    held, waterlogged = capacity, 0.0
    for _year in range(SETTLING_YEARS):
        waterlogged = 0.0
        for month in range(MONTHS):
            short = demand[month] - rain[month] * share
            if short <= 0.0:
                left = max(0.0, -short - (capacity - held))
                waterlogged += max(0.0, min(1.0, (left - passes) / passes)) / MONTHS
                held = min(capacity, held - short)
            else:
                held -= held * (1.0 - math.exp(-short / capacity))
    kept[formed] = waterlogged if math.isfinite(passes) else 0.0
    return kept[formed]
