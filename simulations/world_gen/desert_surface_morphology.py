"""Discrete desert-surface / dune-field bedform morphology classification.

Aeolian transport intensity is already a real, emergent, continuous per-cell
field (surface_evolution.py's aeolian_transport_rows, resolved by
surface_geomorphology.py) that blends material/color tinting on any
sufficiently arid, windy world -- it is not a template special case. What is
still missing is a DISCRETE, named landform layer, analogous to what
coastal_geomorphology.py already does for coastlines (rocky_cliff,
headland_bay, emergent_marine_terrace, ...): real deserts are visually and
functionally distinct depending on wind regime and sand supply, not just a
single continuous "how sandy" tint.

- A strongly unidirectional wind organizes loose sand into crescentic
  (barchan) dunes.
- A bimodal wind regime (two dominant directions) organizes linear (seif)
  dunes aligned with the resultant transport direction.
- A complex, multidirectional wind regime with abundant sand builds star
  dunes.
- Thin or patchy sand cover that hasn't organized into bedforms is a sand
  sheet.
- Where wind has stripped fine material and sand supply is scarce, a lag of
  coarse material remains: stony desert pavement (reg/hamada); this is also
  used as the reduced-physics stand-in for duricrust-armoured pavements,
  since distinguishing them requires geochemical weathering-type data this
  module does not model.

This module deliberately does not solve real saltation/dune-migration
physics; it is a reduced-physics classification in the same spirit as
coastal_geomorphology.py, built from fields that already exist.
"""

import math

from simulations.world_gen.surface_geomorphology import derive_surface_geomorphology_fields

try:
    import numpy as np
except ImportError:  # pragma: no cover - requirements include numpy.
    np = None


DESERT_MORPHOLOGY_MODEL_VERSION = "desert-surface-morphology-v1"

ARIDITY_THRESHOLD_MM = 250.0
AEOLIAN_ACTIVE_THRESHOLD = 0.30
SAND_AVAILABLE_THRESHOLD = 0.35
STAR_DUNE_SAND_THRESHOLD = 0.60
HIGH_CONSISTENCY = 0.72
MID_CONSISTENCY = 0.40
CALM_WIND_SPEED = 1.2

ASSEMBLAGE_LABELS = {
    "barchan_crescentic_dunes": "Barchan/Crescentic Dunes",
    "linear_seif_dunes": "Linear (Seif) Dunes",
    "star_dunes": "Star Dunes",
    "sand_sheet": "Sand Sheet",
    "stony_desert_reg": "Stony Desert (Reg/Hamada)",
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


def _block_wind_consistency(wind_vector_rows, target_h, target_w):
    """Downsample wind vectors by block-averaging.

    Consistency = |mean vector| / mean(|vector|), 1.0 for a perfectly
    unidirectional wind regime over the block, falling toward 0.0 as the
    wind direction becomes multidirectional/complex (a standard circular
    concentration measure).
    """
    height = len(wind_vector_rows)
    width = len(wind_vector_rows[0]) if height and isinstance(wind_vector_rows[0], list) else 0
    consistency = [[0.0 for _ in range(target_w)] for _ in range(target_h)]
    mean_speed = [[0.0 for _ in range(target_w)] for _ in range(target_h)]
    if not height or not width:
        return consistency, mean_speed
    for ty in range(target_h):
        y0 = int(ty * height / target_h)
        y1 = max(y0 + 1, int((ty + 1) * height / target_h))
        for tx in range(target_w):
            x0 = int(tx * width / target_w)
            x1 = max(x0 + 1, int((tx + 1) * width / target_w))
            sum_u = sum_v = sum_speed = 0.0
            count = 0
            for y in range(y0, min(y1, height)):
                row = wind_vector_rows[y]
                for x in range(x0, min(x1, width)):
                    if x >= len(row) or row[x] is None:
                        continue
                    entry = row[x]
                    u, v = float(entry[0]), float(entry[1])
                    speed = float(entry[2]) if len(entry) > 2 and entry[2] is not None else math.hypot(u, v)
                    sum_u += u
                    sum_v += v
                    sum_speed += speed
                    count += 1
            if count == 0:
                continue
            mean_magnitude = math.hypot(sum_u / count, sum_v / count)
            average_speed = sum_speed / count
            consistency[ty][tx] = _clamp(mean_magnitude / max(1e-6, average_speed))
            mean_speed[ty][tx] = average_speed
    return consistency, mean_speed


def _classify_cell(precipitation_mm, aeolian, mantled_plain, wind_consistency, wind_speed):
    if precipitation_mm >= ARIDITY_THRESHOLD_MM or aeolian < AEOLIAN_ACTIVE_THRESHOLD:
        return None
    if mantled_plain < SAND_AVAILABLE_THRESHOLD:
        return "stony_desert_reg"
    if wind_speed < CALM_WIND_SPEED:
        return "sand_sheet"
    if wind_consistency >= HIGH_CONSISTENCY:
        return "barchan_crescentic_dunes"
    if wind_consistency >= MID_CONSISTENCY:
        return "linear_seif_dunes"
    if mantled_plain >= STAR_DUNE_SAND_THRESHOLD:
        return "star_dunes"
    return "sand_sheet"


def derive_desert_surface_morphology_model(heightmap, water_cycle=None, surface_evolution=None, target_size=(128, 64)):
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    surface_evolution = surface_evolution if isinstance(surface_evolution, dict) else {}
    if np is None:
        return {"status": "unavailable", "model_version": DESERT_MORPHOLOGY_MODEL_VERSION}

    fields = derive_surface_geomorphology_fields(
        heightmap,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        target_size=target_size,
    )
    if not fields:
        return {"status": "unavailable", "model_version": DESERT_MORPHOLOGY_MODEL_VERSION}

    target_w, target_h = max(2, int(target_size[0])), max(2, int(target_size[1]))
    climate_grid = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else {}
    precipitation_rows = climate_grid.get("annual_precipitation_rows_mm") or []
    wind_rows = climate_grid.get("prevailing_wind_rows") or []
    precipitation = _resample_nearest(precipitation_rows, target_h, target_w)
    wind_consistency, wind_speed = _block_wind_consistency(wind_rows, target_h, target_w)

    sea_level_m = heightmap.get("sea_level_m")
    elevation = fields["elevation"]
    aeolian = fields["aeolian"]
    mantled_plain = fields["mantled_plain"]

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
            assemblage = _classify_cell(
                precipitation[y][x],
                float(aeolian[y][x]),
                float(mantled_plain[y][x]),
                wind_consistency[y][x],
                wind_speed[y][x],
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
    desert_cell_count = sum(counts.values())
    return {
        "status": "desert_surface_morphology_derived",
        "model_version": DESERT_MORPHOLOGY_MODEL_VERSION,
        "width": target_w,
        "height": target_h,
        "assemblage_rows": assemblage_rows,
        "summary": {
            "desert_land_fraction": round(desert_cell_count / max(1, total_land_cells), 4),
            "dominant_assemblages": dominant_assemblages,
        },
        "notes": [
            "Reduced-physics classification from existing aeolian transport, "
            "aridity, and wind-consistency fields -- not a saltation or "
            "dune-migration simulation.",
        ],
    }
