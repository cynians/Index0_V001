"""Discrete long-term chemical-weathering duricrust classification.

Chemical weathering intensity is already a real, continuous per-cell field
(surface_evolution.py's chemical_weathering_rows, resolved by
surface_geomorphology.py) that tints regolith color generically on any
sufficiently weathered world -- it is not a template special case. What is
still missing is a DISCRETE, named landform layer, analogous to what
desert_surface_morphology.py already does for arid dune fields and
coastal_geomorphology.py does for coastlines: on old, low-relief land left
exposed to weathering for a long time, the *balance* of climate (not just its
intensity) decides which mineral gets left behind as a hardened crust:

- Warm, wet, well-drained terrain leaches silica and bases out and
  concentrates iron/aluminium oxides in place: a ferricrete/laterite
  profile (this is what makes old, stable, humid-tropical shields red --
  Australia's interior, the Amazon and Congo basins, southern India).
- Warm, semi-arid terrain with a strongly negative water balance instead
  precipitates dissolved calcium carbonate near the surface: a pale
  calcrete duricrust (the U.S. Southwest, the Kalahari).
- Terrain with a pronounced wet/dry season, rather than either climate
  extreme, tends to precipitate silica instead: a silcrete duricrust.

This module deliberately does not solve real pedogenic geochemistry; it is a
reduced-physics classification in the same spirit as desert_surface_morphology.py,
built from fields that already exist (chemical weathering intensity, the
transported/weathered-mantle cover fraction, slope, precipitation and
temperature).
"""

import math

from simulations.world_gen.surface_geomorphology import derive_surface_material_partition_fields

try:
    import numpy as np
except ImportError:  # pragma: no cover - requirements include numpy.
    np = None


DURICRUST_MODEL_VERSION = "duricrust-weathering-v1"

MINIMUM_WEATHERING = 0.16
MINIMUM_MANTLE_COVER = 0.30
MAXIMUM_SLOPE = 0.55
HUMID_PRECIPITATION_MM = 900.0
SEMI_ARID_PRECIPITATION_MM = 250.0
WARM_TEMPERATURE_K = 280.0
STRONG_SEASONALITY = 0.62

ASSEMBLAGE_LABELS = {
    "ferricrete_laterite": "Ferricrete / Laterite",
    "calcrete": "Calcrete",
    "silcrete": "Silcrete",
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


def _classify_cell(weathering, mantle_cover, slope, precipitation_mm, temperature_k, seasonality):
    if weathering < MINIMUM_WEATHERING or mantle_cover < MINIMUM_MANTLE_COVER:
        return None
    if slope > MAXIMUM_SLOPE:
        # A duricrust needs a stable, low-relief surface to accumulate on;
        # a steep slope sheds weathered material faster than it hardens.
        return None
    if temperature_k < WARM_TEMPERATURE_K:
        return None
    if precipitation_mm >= HUMID_PRECIPITATION_MM:
        return "ferricrete_laterite"
    if precipitation_mm < SEMI_ARID_PRECIPITATION_MM:
        return None
    if seasonality >= STRONG_SEASONALITY:
        return "silcrete"
    return "calcrete"


def derive_duricrust_weathering_model(heightmap, water_cycle=None, surface_evolution=None, target_size=(128, 64)):
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    surface_evolution = surface_evolution if isinstance(surface_evolution, dict) else {}
    if np is None:
        return {"status": "unavailable", "model_version": DURICRUST_MODEL_VERSION}

    fields = derive_surface_material_partition_fields(
        heightmap,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        target_size=target_size,
    )
    if not fields:
        return {"status": "unavailable", "model_version": DURICRUST_MODEL_VERSION}

    target_w, target_h = max(2, int(target_size[0])), max(2, int(target_size[1]))
    climate_grid = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else {}
    precipitation_rows = climate_grid.get("annual_precipitation_rows_mm") or []
    temperature_rows = climate_grid.get("temperature_rows_k") or []
    summer_fraction_rows = climate_grid.get("summer_precipitation_fraction_rows") or []
    precipitation = _resample_nearest(precipitation_rows, target_h, target_w)
    temperature = _resample_nearest(temperature_rows, target_h, target_w)
    summer_fraction = _resample_nearest(summer_fraction_rows, target_h, target_w) if summer_fraction_rows else None

    sea_level_m = heightmap.get("sea_level_m")
    elevation = fields["elevation"]
    weathering = fields["weathering"]
    mantle_cover = fields["weathered_mantle_fraction"]
    slope = fields["slope"]

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
            # A 50/50 wet-vs-dry half-year split is the seasonally neutral
            # case; distance from 0.5 measures how pronounced the wet/dry
            # season contrast is, independent of which half-year is wetter.
            seasonality = abs(float(summer_fraction[y][x]) - 0.5) * 2.0 if summer_fraction else 0.0
            assemblage = _classify_cell(
                float(weathering[y][x]),
                float(mantle_cover[y][x]),
                float(slope[y][x]),
                precipitation[y][x],
                temperature[y][x],
                seasonality,
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
    duricrust_cell_count = sum(counts.values())
    return {
        "status": "duricrust_weathering_derived",
        "model_version": DURICRUST_MODEL_VERSION,
        "width": target_w,
        "height": target_h,
        "assemblage_rows": assemblage_rows,
        "summary": {
            "duricrust_land_fraction": round(duricrust_cell_count / max(1, total_land_cells), 4),
            "dominant_assemblages": dominant_assemblages,
        },
        "notes": [
            "Reduced-physics classification from existing chemical-weathering, "
            "weathered-mantle-cover, precipitation and temperature fields -- "
            "not a pedogenic geochemistry simulation.",
        ],
    }
