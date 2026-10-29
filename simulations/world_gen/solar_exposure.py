"""How much of the open sky's sunlight a piece of ground receives, read off its slope.

Level ground under an open sky is the measure (1).  A slope turned towards
the sun's path receives as much or more and counts as 1; one turned away
receives less, down to the diffuse light of the sky alone.  The sun is taken
through the year at the map's latitude and the planet's axial tilt, and its
beam is weighed against the ground's own normal:

    exposure = diffuse + (1 - diffuse) * sum(max(0, n . s)) / sum(s_up)

over the hours the sun is up.  ``n`` is the surface normal from the
heightfield's gradient, ``s`` the direction to the sun.  The shadow other
ground throws (a valley floor under its walls) is not in it: only the
ground's own tilt is.

Nothing here knows about plants.  The raster is kept at the heightfield's own
lattice in ``water_cycle_model["insolation_grid"]``; consumers sample it by
position (``worldgen_substrate``: ``surface_solar_exposure``).
"""

from __future__ import annotations

import math

import numpy as np

from simulations.world_gen.exact_rounding import round_rows

MODEL_VERSION = "surface-solar-exposure-v1"
# Share of the light on level ground that comes from the whole sky and not from the sun's disc.  It reaches
# a slope whichever way it faces.  A third is a round figure for a clear-to-broken sky under an atmosphere
# like Earth's (Iqbal 1983 gives 0.2 to 0.5 over the year for most climates).
DIFFUSE_SHARE = 0.3
# The year is walked in this many steps of the sun's declination, each day in this many of its hour angle.
YEAR_STEPS = 12
DAY_STEPS = 24


def surface_solar_exposure(elevation, dx_m, dy_m, latitude_deg, axial_tilt_deg=23.44):
    """Exposure of every cell of a heightfield, 0..1.  Rows run from north to south, columns from west to east."""
    height = np.asarray(elevation, dtype=np.float64)
    if height.ndim != 2 or min(height.shape) < 2 or dx_m <= 0.0 or dy_m <= 0.0:
        return np.ones(height.shape if height.ndim == 2 else (0, 0))
    south, east = np.gradient(np.nan_to_num(height, nan=float(np.nanmean(height))), dy_m, dx_m)
    length = np.sqrt(east ** 2 + south ** 2 + 1.0)
    # The normal in east, north, up: ground rising to the south leans its face to the north.
    normal_east, normal_north, normal_up = -east / length, south / length, 1.0 / length
    latitude = math.radians(max(-89.9, min(89.9, float(latitude_deg))))
    tilt = math.radians(abs(float(axial_tilt_deg)))
    on_slope, on_level = np.zeros(height.shape), 0.0
    for step in range(YEAR_STEPS):
        declination = tilt * math.sin(math.tau * (step + 0.5) / YEAR_STEPS)
        for hour in range(DAY_STEPS):
            angle = math.tau * (hour + 0.5) / DAY_STEPS - math.pi
            up = math.sin(latitude) * math.sin(declination) + math.cos(latitude) * math.cos(declination) * math.cos(angle)
            if up <= 0.0:
                continue
            sun_east = -math.cos(declination) * math.sin(angle)
            sun_north = math.cos(latitude) * math.sin(declination) - math.sin(latitude) * math.cos(declination) * math.cos(angle)
            on_slope += np.maximum(0.0, normal_east * sun_east + normal_north * sun_north + normal_up * up)
            on_level += up
    if on_level <= 0.0:
        return np.ones(height.shape)
    return np.clip(DIFFUSE_SHARE + (1.0 - DIFFUSE_SHARE) * on_slope / on_level, 0.0, 1.0)


def with_surface_solar_exposure(heightmap, water_cycle, axial_tilt_deg=23.44):
    """``water_cycle`` with the exposure of the heightfield's own ground in its ``insolation_grid``.

    Returned unchanged where the heightfield, its spacing or its place on the
    planet is missing.
    """
    if not isinstance(heightmap, dict) or not isinstance(water_cycle, dict):
        return water_cycle
    rows = (heightmap.get("sample_grid") or {}).get("rows") or []
    dx = float(heightmap.get("sample_spacing_x_m") or 0.0)
    dy = float(heightmap.get("sample_spacing_y_m") or 0.0)
    bounds = heightmap.get("source_uv_bounds")
    if not rows or not rows[0] or dx <= 0.0 or dy <= 0.0 or not isinstance(bounds, dict):
        return water_cycle
    middle = (float(bounds.get("min_v", 0.5) or 0.0) + float(bounds.get("max_v", 0.5) or 0.0)) * 0.5
    latitude_deg = (0.5 - middle) * 180.0
    elevation = np.asarray([getattr(row, "values", row) for row in rows], dtype=np.float64)
    exposure = surface_solar_exposure(elevation, dx, dy, latitude_deg, axial_tilt_deg)
    result = dict(water_cycle)
    result["insolation_grid"] = {
        "status": "read_from_heightfield",
        "model_version": MODEL_VERSION,
        "width": int(elevation.shape[1]),
        "height": int(elevation.shape[0]),
        "latitude_deg": round(latitude_deg, 4),
        "axial_tilt_deg": round(abs(float(axial_tilt_deg)), 3),
        "surface_solar_exposure_rows": round_rows(exposure, 3),
        "exposure_contract": (
            "yearly sunlight on the ground's own slope against level ground under an open sky, capped at 1; "
            "direct beam by the surface normal plus a fixed diffuse share; no cast shadow"
        ),
    }
    return result
