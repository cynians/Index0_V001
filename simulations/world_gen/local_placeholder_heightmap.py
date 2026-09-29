"""Standalone placeholder heightmap for locations with no generated planet parent.

Real regional heightmaps are cropped from an ancestor planet's worldgen
output (see MapSimulation._inherited_surface_context in
simulations/map/map_simulation.py). That path requires a real, already
-generated planet-scale ancestor in a matching coordinate space, which the
lumber test site does not have and is not meant to grow one for -- it is a
hand-authored site_meters test fixture, not a worldgen product.

This module produces a heightmap_model-shaped dict from deterministic
meter-space noise instead, using the same fractal_noise_m primitive real
worldgen uses, so map/relief rendering has something to draw while a site is
being interacted with. It is explicitly tagged
"standalone_placeholder_heightmap" (as opposed to the real
"parent_surface_inherited"/"parent_climate_inherited" status values) so it is
never mistaken for worldgen-derived truth by downstream consumers.
"""

from simulations.world_gen.geological_noise import fractal_noise_m

PLACEHOLDER_HEIGHTMAP_STATUS = "standalone_placeholder_heightmap"

# fractal_noise_m samples a continuous field in absolute meter coordinates,
# not bounds-normalized ones. Passing the same seed for every location in
# one local area (site, surrounding region, road-corridor slices) means any
# two overlapping windows sample the *same* underlying field, so they stay
# consistent with each other without needing to crop from a stored raster.
LUMBER_AREA_SEED = "location_lumber_region_surrounds"


def build_placeholder_heightmap(
    bounds,
    seed,
    *,
    resolution=33,
    wavelength_m=60.0,
    elevation_range_m=15.0,
    octaves=4,
):
    """Build a small deterministic relief patch for a site_meters-scale bounds dict.

    `bounds` must have min_x/max_x/min_y/max_y. `seed` should be stable
    per-location (e.g. the location id) so regeneration is reproducible.
    """
    min_x, max_x = float(bounds["min_x"]), float(bounds["max_x"])
    min_y, max_y = float(bounds["min_y"]), float(bounds["max_y"])
    columns = max(2, int(resolution))
    rows_count = max(2, int(resolution))

    rows = []
    values = []
    for row_index in range(rows_count):
        v = row_index / (rows_count - 1)
        y_m = min_y + (max_y - min_y) * v
        row = []
        for column_index in range(columns):
            u = column_index / (columns - 1)
            x_m = min_x + (max_x - min_x) * u
            noise = fractal_noise_m(
                seed, "placeholder_relief", x_m, y_m, wavelength_m, octaves=octaves,
            )
            elevation = noise * float(elevation_range_m)
            row.append(elevation)
            values.append(elevation)
        rows.append(row)

    return {
        "status": PLACEHOLDER_HEIGHTMAP_STATUS,
        "model_version": "standalone-placeholder-v1",
        "coverage": "standalone_placeholder",
        "projection": "local_equirectangular",
        "wrap_x": False,
        "wrap_y": False,
        "sea_level_m": None,
        "min_elevation_m": min(values),
        "max_elevation_m": max(values),
        "region_width_m": max_x - min_x,
        "region_height_m": max_y - min_y,
        "sample_grid": {
            "width": columns,
            "height": rows_count,
            "wrap_x": False,
            "wrap_y": False,
            "rows": rows,
        },
        "surface_masks": {"ice_rows": []},
    }
