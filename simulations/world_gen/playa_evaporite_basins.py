"""Discrete salt-pan / playa evaporite-basin classification.

drainage.py already resolves which lakes are endorheic -- their
`water_balance_limited` flag marks a lake whose basin has no surface outlet,
so everything that flows in can only leave by evaporation. What is still
missing is the landform consequence of that fact: under a sufficiently arid
water balance, an endorheic basin does not stay a normal lake, it
concentrates dissolved salts until they crust out on the basin floor --
exactly what makes the Salar de Uyuni, Bonneville, or Lake Eyre look the way
they do. Which salt actually crusts out depends on how extreme the aridity
is:

- A basin whose potential evaporation dwarfs its precipitation (and is
  correspondingly shallow) crusts out as a hard, largely halite salt pan.
- A less extreme endorheic basin still evaporites out, but as a softer,
  gypsum-dominated playa rather than a blinding-white salt flat.

This module deliberately does not solve real basin-scale brine chemistry or
seasonal flooding cycles; it is a reduced-physics classification in the same
spirit as desert_surface_morphology.py, built entirely from the lakes and
climate fields the water cycle already resolves.
"""

ARIDITY_SALT_PAN_THRESHOLD = 6.0
ARIDITY_GYPSUM_PLAYA_THRESHOLD = 2.5
SALT_PAN_MAXIMUM_DEPTH_M = 5.0

ASSEMBLAGE_LABELS = {
    "salt_pan_crust": "Salt Pan Crust",
    "gypsum_playa": "Gypsum Playa",
}


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _grid_dimensions(rows):
    height = len(rows)
    width = min((len(row) for row in rows if isinstance(row, list)), default=0)
    return height, width


def _map_source_cell_to_target(cx, cy, source_w, source_h, target_w, target_h):
    tx = min(target_w - 1, int(cx * target_w / max(1, source_w)))
    ty = min(target_h - 1, int(cy * target_h / max(1, source_h)))
    return tx, ty


def _mean_at_cells(rows, cells, source_h, source_w):
    if not cells:
        return 0.0
    total = 0.0
    count = 0
    for cx, cy in cells:
        if 0 <= cy < source_h and 0 <= cx < source_w and cy < len(rows) and cx < len(rows[cy]):
            total += float(rows[cy][cx] or 0.0)
            count += 1
    return total / count if count else 0.0


def derive_playa_evaporite_basin_model(heightmap, water_cycle=None, surface_evolution=None, target_size=(128, 64)):
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}

    climate_grid = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else {}
    precipitation_rows = climate_grid.get("annual_precipitation_rows_mm") or []
    evaporation_rows = climate_grid.get("annual_potential_evaporation_rows_mm") or []
    if not precipitation_rows or not evaporation_rows:
        return {"status": "unavailable", "model_version": "playa-evaporite-basins-v1"}
    source_h, source_w = _grid_dimensions(precipitation_rows)
    if not source_h or not source_w:
        return {"status": "unavailable", "model_version": "playa-evaporite-basins-v1"}

    drainage = water_cycle.get("drainage_network_model") if isinstance(water_cycle.get("drainage_network_model"), dict) else {}
    lakes = (
        water_cycle.get("lakes")
        if isinstance(water_cycle.get("lakes"), list)
        else drainage.get("lakes") if isinstance(drainage.get("lakes"), list) else []
    )
    endorheic_lakes = [
        lake for lake in lakes
        if isinstance(lake, dict) and lake.get("water_balance_limited") and lake.get("cells")
    ]

    target_w, target_h = max(2, int(target_size[0])), max(2, int(target_size[1]))
    assemblage_rows = [[None for _ in range(target_w)] for _ in range(target_h)]
    counts = {}
    basins = []
    for lake in endorheic_lakes:
        raw_cells = [
            (int(cell[0]), int(cell[1]))
            for cell in lake.get("cells") or []
            if isinstance(cell, (list, tuple)) and len(cell) >= 2
        ]
        if not raw_cells:
            continue
        mean_precip = _mean_at_cells(precipitation_rows, raw_cells, source_h, source_w)
        mean_evaporation = _mean_at_cells(evaporation_rows, raw_cells, source_h, source_w)
        aridity_index = mean_evaporation / max(1.0, mean_precip)
        depth_m = float(lake.get("maximum_depth_m", 0.0) or 0.0)
        if aridity_index >= ARIDITY_SALT_PAN_THRESHOLD and depth_m <= SALT_PAN_MAXIMUM_DEPTH_M:
            assemblage = "salt_pan_crust"
        elif aridity_index >= ARIDITY_GYPSUM_PLAYA_THRESHOLD:
            assemblage = "gypsum_playa"
        else:
            continue
        target_cells = {
            _map_source_cell_to_target(cx, cy, source_w, source_h, target_w, target_h)
            for cx, cy in raw_cells
        }
        for tx, ty in target_cells:
            assemblage_rows[ty][tx] = assemblage
        counts[assemblage] = counts.get(assemblage, 0) + len(target_cells)
        basins.append({
            "lake_id": lake.get("id"),
            "assemblage": assemblage,
            "aridity_index": round(aridity_index, 3),
            "maximum_depth_m": round(depth_m, 2),
            "cell_count": len(target_cells),
        })

    total_target_cells = target_w * target_h
    dominant_assemblages = [
        {
            "id": assemblage_id,
            "label": ASSEMBLAGE_LABELS.get(assemblage_id, assemblage_id),
            "cell_count": count,
            "land_fraction": round(count / max(1, total_target_cells), 4),
        }
        for assemblage_id, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]
    return {
        "status": "playa_evaporite_basins_derived",
        "model_version": "playa-evaporite-basins-v1",
        "width": target_w,
        "height": target_h,
        "assemblage_rows": assemblage_rows,
        "basins": basins,
        "summary": {
            "playa_basin_count": len(basins),
            "dominant_assemblages": dominant_assemblages,
        },
        "notes": [
            "Reduced-physics classification: an endorheic (water_balance_limited) "
            "lake with a sufficiently negative precipitation/potential-evaporation "
            "balance crusts out as a named evaporite assemblage -- not a brine "
            "chemistry or seasonal flooding simulation.",
        ],
    }
