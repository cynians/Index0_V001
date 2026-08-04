"""Discrete permafrost patterned-ground classification.

The water cycle already resolves ET Tundra / EF Ice Cap Koppen classes and a
continuous seasonal freeze-thaw signal, but nothing currently distinguishes
*how* a cold, low-relief surface actually looks on the ground once repeated
freeze-thaw cycling has had time to work on it. Real periglacial terrain is
not a uniform "cold and flat" texture -- ice segregation and thermal
contraction sort and heave the ground into a small number of recognisable,
named forms depending on relief and how much ground ice is available:

- Flat, well-drained tundra with abundant ground ice sorts itself into
  polygon patterned ground (ice-wedge polygons on Arctic coastal plains,
  sorted circles/polygons at altitude).
- Gently sloped tundra instead stretches the same sorting process
  downslope into stripes (sorted stripes / solifluction lobes).
- Where the ground ice itself has begun to melt out (a warming margin, or
  simply an older, degrading permafrost table) the patterned ground
  collapses into irregular thermokarst pits and ponds instead.

This module deliberately does not solve real ice-segregation thermodynamics
or an evolving active-layer depth; it is a reduced-physics classification in
the same spirit as desert_surface_morphology.py, built from fields that
already exist (temperature, its seasonal swing, slope, and the existing
Koppen tundra/ice-cap classification).
"""

from simulations.world_gen.surface_geomorphology import derive_surface_geomorphology_fields

try:
    import numpy as np
except ImportError:  # pragma: no cover - requirements include numpy.
    np = None


PATTERNED_GROUND_MODEL_VERSION = "periglacial-patterned-ground-v1"

MAXIMUM_MEAN_TEMPERATURE_K = 276.0
MINIMUM_SEASONAL_SWING_K = 12.0
FLAT_SLOPE = 0.12
STRIPE_SLOPE = 0.32
THERMOKARST_DEGRADATION_WEATHERING = 0.30

ASSEMBLAGE_LABELS = {
    "polygon_patterned_ground": "Polygon Patterned Ground",
    "sorted_stripes": "Sorted Stripes / Solifluction Lobes",
    "thermokarst_terrain": "Thermokarst Terrain",
}


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _resample_nearest(rows, target_h, target_w):
    height = len(rows)
    width = len(rows[0]) if height and isinstance(rows[0], list) else 0
    if not height or not width:
        return [[0.0 for _ in range(target_w)] for _ in range(target_h)]
    out = []
    for ty in range(target_h):
        source_y = min(height - 1, int(ty * height / target_h))
        row = rows[source_y]
        row_width = min(width, len(row))
        out_row = []
        for tx in range(target_w):
            source_x = min(row_width - 1, int(tx * row_width / target_w))
            value = row[source_x]
            out_row.append(float(value) if value is not None else 0.0)
        out.append(out_row)
    return out


def _classify_cell(mean_temperature_k, seasonal_swing_k, slope, weathering, is_permanently_iced):
    if is_permanently_iced:
        # Ice-cap interiors are not periglacial ground; there is no active
        # layer to freeze-thaw cycle at all.
        return None
    if mean_temperature_k > MAXIMUM_MEAN_TEMPERATURE_K:
        return None
    if seasonal_swing_k < MINIMUM_SEASONAL_SWING_K:
        # Patterned ground needs a real freeze/thaw cycle, not just cold.
        return None
    if weathering >= THERMOKARST_DEGRADATION_WEATHERING:
        return "thermokarst_terrain"
    if slope <= FLAT_SLOPE:
        return "polygon_patterned_ground"
    if slope <= STRIPE_SLOPE:
        return "sorted_stripes"
    return None


def derive_periglacial_patterned_ground_model(heightmap, water_cycle=None, surface_evolution=None, target_size=(128, 64)):
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    surface_evolution = surface_evolution if isinstance(surface_evolution, dict) else {}
    if np is None:
        return {"status": "unavailable", "model_version": PATTERNED_GROUND_MODEL_VERSION}

    fields = derive_surface_geomorphology_fields(
        heightmap,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        target_size=target_size,
    )
    if not fields:
        return {"status": "unavailable", "model_version": PATTERNED_GROUND_MODEL_VERSION}

    target_w, target_h = max(2, int(target_size[0])), max(2, int(target_size[1]))
    climate_grid = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else {}
    temperature_rows = climate_grid.get("temperature_rows_k") or []
    seasonal_min_rows = climate_grid.get("seasonal_min_temperature_rows_k") or []
    seasonal_max_rows = climate_grid.get("seasonal_max_temperature_rows_k") or []
    temperature = _resample_nearest(temperature_rows, target_h, target_w)
    seasonal_min = _resample_nearest(seasonal_min_rows, target_h, target_w) if seasonal_min_rows else None
    seasonal_max = _resample_nearest(seasonal_max_rows, target_h, target_w) if seasonal_max_rows else None
    permanent_ice_rows = (heightmap.get("surface_masks") or {}).get("ice_rows") or []
    permanent_ice = _resample_nearest(
        [[1.0 if value else 0.0 for value in row] for row in permanent_ice_rows], target_h, target_w,
    ) if permanent_ice_rows else None

    sea_level_m = heightmap.get("sea_level_m")
    elevation = fields["elevation"]
    slope = fields["slope"]
    weathering = fields["weathering"]

    assemblage_rows = []
    counts = {}
    total_land_cells = 0
    for y in range(target_h):
        row = []
        for x in range(target_w):
            is_ocean = sea_level_m is not None and float(elevation[y][x]) < float(sea_level_m)
            if is_ocean:
                row.append(None)
                continue
            total_land_cells += 1
            seasonal_swing = (
                float(seasonal_max[y][x]) - float(seasonal_min[y][x])
                if seasonal_min is not None and seasonal_max is not None
                else 0.0
            )
            is_permanently_iced = bool(permanent_ice[y][x] >= 0.5) if permanent_ice is not None else False
            assemblage = _classify_cell(
                float(temperature[y][x]),
                seasonal_swing,
                float(slope[y][x]),
                float(weathering[y][x]),
                is_permanently_iced,
            )
            row.append(assemblage)
            if assemblage:
                counts[assemblage] = counts.get(assemblage, 0) + 1
        assemblage_rows.append(row)

    dominant_assemblages = [
        {
            "id": assemblage_id,
            "label": ASSEMBLAGE_LABELS.get(assemblage_id, assemblage_id),
            "cell_count": count,
            "land_fraction": round(count / max(1, total_land_cells), 4),
        }
        for assemblage_id, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]
    patterned_ground_cell_count = sum(counts.values())
    return {
        "status": "periglacial_patterned_ground_derived",
        "model_version": PATTERNED_GROUND_MODEL_VERSION,
        "width": target_w,
        "height": target_h,
        "assemblage_rows": assemblage_rows,
        "summary": {
            "patterned_ground_land_fraction": round(patterned_ground_cell_count / max(1, total_land_cells), 4),
            "dominant_assemblages": dominant_assemblages,
        },
        "notes": [
            "Reduced-physics classification from existing temperature, "
            "seasonal freeze-thaw swing, slope and permanent-ice fields -- "
            "not an ice-segregation or active-layer thermodynamics simulation.",
        ],
    }
