"""Discrete inland karst-dissolution landform classification.

coastal_geomorphology.py already scores a continuous "carbonate_influence"
for shoreline segments (thermal suitability, latitude, sediment exclusion,
substrate) and tags them carbonate_karst. What is still missing is the
inland equivalent: on a planet with carbonate-favorable crust chemistry
(warm, active hydrology, calcium-bearing crust -- see
natural_materials.derive_planet_material_tags's "carbonate_favorable" tag),
sustained chemical weathering of carbonate country rock dissolves it into
recognisable, named landforms rather than a single continuous "how weathered"
tint:

- Low-relief carbonate plains under long, warm, wet exposure develop
  doline/sinkhole karst -- a pockmarked plain of closed depressions
  (classic examples: Kentucky's Pennyroyal Plateau, the Yucatan).
- Where uplift or dissection has left more relief, the same dissolution
  process instead isolates steep-sided residual towers separated by flat
  alluviated floors -- tower karst (Guilin, Ha Long Bay).

This module deliberately does not solve real carbonate dissolution kinetics
or cave/conduit networks; it is a reduced-physics classification in the same
spirit as desert_surface_morphology.py, built from fields that already exist
plus the planet's global carbonate-favorable gate.
"""

from simulations.world_gen.surface_geomorphology import derive_surface_material_partition_fields

try:
    import numpy as np
except ImportError:  # pragma: no cover - requirements include numpy.
    np = None


KARST_MODEL_VERSION = "karst-dissolution-v1"

MINIMUM_WEATHERING = 0.22
MINIMUM_PRECIPITATION_MM = 550.0
WARM_TEMPERATURE_K = 279.0
LOW_RELIEF_SLOPE = 0.30
TOWER_RELIEF_SLOPE = 0.55
TOWER_PRECIPITATION_MM = 1400.0

ASSEMBLAGE_LABELS = {
    "doline_sinkhole_plain": "Doline / Sinkhole Karst Plain",
    "tower_karst": "Tower Karst",
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


def _classify_cell(weathering, slope, precipitation_mm, temperature_k):
    if weathering < MINIMUM_WEATHERING or precipitation_mm < MINIMUM_PRECIPITATION_MM:
        return None
    if temperature_k < WARM_TEMPERATURE_K:
        return None
    if slope <= LOW_RELIEF_SLOPE:
        return "doline_sinkhole_plain"
    if slope <= TOWER_RELIEF_SLOPE and precipitation_mm >= TOWER_PRECIPITATION_MM:
        return "tower_karst"
    return None


def derive_karst_dissolution_model(
    heightmap, water_cycle=None, surface_evolution=None, planet_tags=None, target_size=(128, 64),
):
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    surface_evolution = surface_evolution if isinstance(surface_evolution, dict) else {}
    if np is None:
        return {"status": "unavailable", "model_version": KARST_MODEL_VERSION}

    tags = set(planet_tags or [])
    if tags and "carbonate_favorable" not in tags:
        return {
            "status": "not_applicable",
            "model_version": KARST_MODEL_VERSION,
            "reason": "crust_chemistry_not_carbonate_favorable",
            "assemblage_rows": [],
            "summary": {"karst_land_fraction": 0.0, "dominant_assemblages": []},
        }

    fields = derive_surface_material_partition_fields(
        heightmap,
        water_cycle=water_cycle,
        surface_evolution=surface_evolution,
        target_size=target_size,
    )
    if not fields:
        return {"status": "unavailable", "model_version": KARST_MODEL_VERSION}

    target_w, target_h = max(2, int(target_size[0])), max(2, int(target_size[1]))
    climate_grid = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else {}
    precipitation_rows = climate_grid.get("annual_precipitation_rows_mm") or []
    temperature_rows = climate_grid.get("temperature_rows_k") or []
    precipitation = _resample_nearest(precipitation_rows, target_h, target_w)
    temperature = _resample_nearest(temperature_rows, target_h, target_w)

    sea_level_m = heightmap.get("sea_level_m")
    elevation = fields["elevation"]
    weathering = fields["weathering"]
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
            assemblage = _classify_cell(
                float(weathering[y][x]),
                float(slope[y][x]),
                precipitation[y][x],
                temperature[y][x],
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
    karst_cell_count = sum(counts.values())
    return {
        "status": "karst_dissolution_derived",
        "model_version": KARST_MODEL_VERSION,
        "width": target_w,
        "height": target_h,
        "assemblage_rows": assemblage_rows,
        "summary": {
            "karst_land_fraction": round(karst_cell_count / max(1, total_land_cells), 4),
            "dominant_assemblages": dominant_assemblages,
        },
        "notes": [
            "Reduced-physics classification gated on the planet's carbonate-"
            "favorable crust chemistry, then placed from existing chemical-"
            "weathering, slope, precipitation and temperature fields -- not "
            "a dissolution-kinetics or conduit-network simulation.",
        ],
    }
