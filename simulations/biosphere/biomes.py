"""Naming the biome a piece of ground belongs to.

A biome is the climate zone world generation gave the ground (its Köppen
class), split further by water and by height only where there is a word for
the result: a wetland, a salt marsh, a riverside, open water; montane, alpine.  Dry ground
within a climate, or a hill that is not yet a mountain, has no word of its
own and stays with the zone.

A planet's flora is kept biome by biome (``flora``): what was established in a
Temperate Oceanic wetland is what a city founded on such ground finds there.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# Ground is a wetland where its water table stands within this of the surface: the "wet" class of forest
# site classification (Klinka et al. 1989), and the depth wetland delineation asks saturation to reach.
# A map that does not tell the depth of its water table is read by its wetness index instead.
WETLAND_TABLE_M = 0.3
WETLAND_WETNESS = 0.75
# Wet ground whose ground water is more the sea's than the rain's is a salt marsh, not a fen: what grows in
# the one does not grow in the other (``fine_hydrology.groundwater_salinity``).
SALT_MARSH_SALINITY = 0.5
# Metres above the sea from which ground is mountain ground.
MONTANE_M = 1000.0
# Mountain ground whose warmest month stays under this is above the trees.
ALPINE_WARMEST_C = 10.0

OPEN_WATER, WETLAND, RIVERSIDE, SALT_MARSH = "open water", "wetland", "riverside", "salt marsh"
MONTANE, ALPINE = "montane", "alpine"


@dataclass(frozen=True)
class Biome:
    climate: str            # the Köppen class, or "" for ground that carries none
    climate_label: str = ""
    water: str = ""         # "", open water, wetland, salt marsh or riverside
    height: str = ""        # "", montane or alpine

    @property
    def key(self):
        """What a flora is filed under: ``Cfb``, ``Cfb/wetland``, ``Cfb/montane``, ``Cfb/wetland/montane``."""
        return "/".join(part for part in (self.climate or "unclassified", self.water.replace(" ", "_"), self.height) if part)

    @property
    def label(self):
        """In words: *Temperate Oceanic*, *Temperate Oceanic wetland*, *Montane Temperate Oceanic riverside*."""
        climate = self.climate_label or self.climate or "Unclassified ground"
        return " ".join(part for part in (self.height.capitalize(), climate, self.water) if part)


def _sea_level(substrate):
    heightmap = getattr(substrate, "heightmap", None)
    if heightmap is None:
        heightmap = getattr(getattr(substrate, "base", None), "heightmap", None) or {}
    return float(heightmap.get("sea_level_m") or 0.0)


def classify(climate, climate_label, *, open_water=False, wetness=0.0, wetland=False, channel=False,
             height_m=0.0, warmest_c=None, water_table_depth_m=None, groundwater_salinity=0.0):
    """The biome of ground described by a few figures."""
    wet = wetness >= WETLAND_WETNESS if water_table_depth_m is None else water_table_depth_m <= WETLAND_TABLE_M
    marsh = SALT_MARSH if float(groundwater_salinity or 0.0) >= SALT_MARSH_SALINITY else WETLAND
    water = OPEN_WATER if open_water else marsh if (wetland or wet) else RIVERSIDE if channel else ""
    height = ""
    if height_m >= MONTANE_M:
        height = ALPINE if (warmest_c is not None and warmest_c < ALPINE_WARMEST_C) else MONTANE
    return Biome(str(climate or ""), str(climate_label or ""), water, height)


def biome_at(substrate, x, y):
    """The biome at one point of a substrate (``worldgen_substrate``)."""
    zone = getattr(substrate, "koppen_at", lambda _x, _y: None)(x, y)
    environment = substrate.environment_at(x, y)
    warmest = environment.get("warmest_month_temperature_k")
    table = environment.get("water_table_depth_m")
    return classify(
        zone[0] if zone else "", zone[1] if zone else "",
        open_water=bool(environment.get("open_water")),
        wetness=float(environment.get("soil_moisture", 0.0) or 0.0),
        wetland=float(environment.get("wetland_presence", 0.0) or 0.0) > 0.5,
        channel=float(environment.get("channel_presence", 0.0) or 0.0) > 0.5,
        height_m=float(environment.get("elevation_m", 0.0) or 0.0) - _sea_level(substrate),
        warmest_c=None if warmest is None else float(warmest) - 273.15,
        water_table_depth_m=None if table is None or not np.isfinite(table) else float(table),
        groundwater_salinity=float(environment.get("groundwater_salinity") or 0.0),
    )


def biome_grid(substrate, xs, ys):
    """Biomes over arrays of points: ``(index array, list of the biomes it indexes)``.

    The climate zone is read point by point (it is a class, not a quantity);
    everything else is sampled at once.
    """
    xs, ys = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)

    def field(key, default):
        return np.asarray(substrate.sample_array(key, xs, ys, default), dtype=np.float64)

    open_water = np.asarray(substrate.open_water_array(xs, ys), dtype=bool)
    table = field("water_table_depth_m", np.nan)
    wet = (field("wetland_presence", 0.0) > 0.5) | np.where(
        np.isfinite(table), table <= WETLAND_TABLE_M, field("soil_moisture", 0.0) >= WETLAND_WETNESS)
    channel = field("channel_presence", 0.0) > 0.5
    salinity = np.nan_to_num(field("groundwater_salinity", 0.0))
    height = field("elevation_m", 0.0) - _sea_level(substrate)
    warmest = field("warmest_month_temperature_k", np.nan) - 273.15
    koppen = getattr(substrate, "koppen_at", lambda _x, _y: None)
    index = np.empty(xs.shape, dtype=np.int32)
    biomes, known = [], {}
    for position in np.ndindex(xs.shape):
        zone = koppen(float(xs[position]), float(ys[position]))
        biome = classify(
            zone[0] if zone else "", zone[1] if zone else "",
            open_water=bool(open_water[position]), wetland=bool(wet[position]), channel=bool(channel[position]),
            height_m=float(height[position]), groundwater_salinity=float(salinity[position]),
            warmest_c=None if np.isnan(warmest[position]) else float(warmest[position]),
        )
        if biome not in known:
            known[biome] = len(biomes)
            biomes.append(biome)
        index[position] = known[biome]
    return index, biomes
