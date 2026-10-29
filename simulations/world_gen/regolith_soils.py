"""Abiotic regolith and soil-state derivation from existing surface outputs."""

import math

import numpy as np


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _nearest_rows(rows, height, width, default):
    """Nearest-sample a same-footprint grid onto (height, width) cells."""
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list) or not rows[0]:
        return np.full((height, width), default, dtype=np.float64)
    source_width = min(len(row) for row in rows)
    values = np.asarray([row[:source_width] for row in rows], dtype=np.float64)
    source_y = np.clip(np.rint(np.arange(height) * (values.shape[0] - 1) / max(1, height - 1)).astype(np.int64), 0, values.shape[0] - 1)
    source_x = np.clip(np.rint(np.arange(width) * (source_width - 1) / max(1, width - 1)).astype(np.int64), 0, source_width - 1)
    return np.nan_to_num(values[np.ix_(source_y, source_x)], nan=default)


def _province_elements(planet, heightmap, height, width):
    """Per-cell province element arrays (Ca, S, N, P) or None.

    Uses the LOD0 province index raster in global UV, so a regional child
    reads the chemistry of the provinces it actually covers.
    """
    placement = planet.get("geochemical_material_model") if isinstance(planet.get("geochemical_material_model"), dict) else {}
    provinces = placement.get("provinces") or []
    index_rows = placement.get("province_index_rows")
    if not provinces or not index_rows:
        return None
    index = np.asarray(index_rows, dtype=np.int64)
    bounds = heightmap.get("source_uv_bounds") if isinstance(heightmap.get("source_uv_bounds"), dict) else {}
    min_u = float(bounds.get("min_u", 0.0) or 0.0)
    max_u = float(bounds.get("max_u", 1.0) if bounds.get("max_u") is not None else 1.0)
    min_v = float(bounds.get("min_v", 0.0) or 0.0)
    max_v = float(bounds.get("max_v", 1.0) if bounds.get("max_v") is not None else 1.0)
    u = min_u + (max_u - min_u) * np.arange(width) / max(1, width - 1)
    v = min_v + (max_v - min_v) * np.arange(height) / max(1, height - 1)
    grid_height, grid_width = index.shape
    columns = np.rint(np.mod(u, 1.0) * (grid_width - 1)).astype(np.int64) % grid_width
    rows = np.clip(np.rint(np.clip(v, 0.0, 1.0) * (grid_height - 1)).astype(np.int64), 0, grid_height - 1)
    cell_index = index[np.ix_(rows, columns)]
    arrays = {}
    for symbol in ("Ca", "S", "N", "P"):
        lookup = np.asarray(
            [float((province.get("elements") or {}).get(symbol, 0.0) or 0.0) for province in provinces] + [np.nan]
        )
        arrays[symbol] = lookup[np.where(cell_index >= 0, cell_index, len(provinces))]
    return arrays


# Below Site scale a tile is a piece of its parent's ground: the broad state
# of its soil is the parent's, and the tile adds what its own relief decides.
FINE_SOIL_MIN_LEVEL = 5
# Soil thins on convex ground and thickens in hollows (Heimsath et al. 1997:
# depth falls with curvature on soil-mantled slopes).  ``exp(curvature x
# length)``, bounded: a nose bent by 5 % per metre keeps about 60 % of the
# depth, a hollow of the same curvature holds about 160 %.
CURVATURE_LENGTH_M = 10.0
CURVATURE_LOG_SPAN = 0.5
# Bars of a river's former bed are coarse and thinly covered while fresh; an
# abandoned channel fills with the fines of later floods (clay plugs,
# Toonen et al. 2012).  Each order of relic channel moves soil between its
# own floors and bars at the level that builds it; the mean over a few of its
# lanes stays what the parent gave.
BAR_THINNING = 0.35
CHANNEL_FILL_POROSITY = 0.08
CHANNEL_FILL_PERMEABILITY = 0.45
# Rock scarps (``rock_scarps``).  A face carries no soil.  Talus is open-work
# rubble: fines only in pockets between the blocks, and it drains freely.
# The debris mantle of a rampart is a thin skin over the weak rock.
TALUS_SOIL_DEPTH_M = 0.12
RAMPART_SOIL_DEPTH_M = 0.4
TALUS_POROSITY = 0.4
_INHERITED_SOIL_FIELDS = (
    "soil_depth_m_rows", "porosity_rows", "relative_permeability_rows", "ph_rows", "salinity_index_rows",
)
# Fields a parent built before they existed does not carry; the tile then works them out for itself.
_INHERITED_WHERE_PRESENT = (
    "available_water_capacity_rows_mm_per_m", "capillary_rise_rows_m", "rootable_depth_m_rows",
    "drainage_rate_rows_mm_per_day",
)
# The water a metre of soil holds for plants (field capacity less wilting point), by texture: 60 to 90 mm in
# coarse sand, 160 to 190 mm in loams and clay loams, 130 to 190 mm in clays (Salter & Williams 1969, the
# figures land-capability surveys still use).  Read off the clay share weathering and deposition leave.
AWC_COARSE_MM_PER_M = 70.0
AWC_LOAM_MM_PER_M = 190.0
AWC_HEAVY_CLAY_MM_PER_M = 150.0
# How high the ground lifts water above a water table: centimetres in gravel and coarse sand, a few
# decimetres in fine sand, about a metre in loam and silt, two and more in clay (the capillary-rise table
# of Fetter 2001, Applied Hydrogeology).
CAPILLARY_RISE_COARSE_M = 0.1
CAPILLARY_RISE_CLAY_M = 2.0
CAPILLARY_RISE_FILL_M = 1.5
# A floodplain is built of its river's bars and fills: metres of loose sediment that roots go into whether
# or not a soil has formed on top.  ``soil_depth`` stays the depth of the soil; this is what can be rooted.
FLOODPLAIN_ROOTABLE_M = 3.0


# What the subsoil lets through when saturated, in millimetres a day: metres in sand, decimetres in loam,
# centimetres in clay loam, a few millimetres in clay and less in heavy clay.  The fall with the clay share
# is that of Rawls, Brakensiek & Saxton (1982) for topsoils (sand 5000, loam 320, clay loam 55, clay
# 14 mm a day); a subsoil passes about a fifth of its topsoil, which is this module's reading.  Where a
# wet month leaves more to drain than this, the water stands in the soil (``biosphere.water_balance``).
DRAINAGE_SAND_LOG10_MM_PER_DAY = 3.0
DRAINAGE_LOG10_PER_CLAY_SHARE = -5.0
# An abandoned channel's fill is a plug of silt and clay; a fresh bar is clean sand and gravel.
DRAINAGE_FILL_MM_PER_DAY = 1.0
DRAINAGE_BAR_MM_PER_DAY = 1000.0


def soil_drainage_rate(clay):
    """What a soil's subsoil lets through when saturated, in mm a day, by its clay share (0..1)."""
    clay = np.clip(np.asarray(clay, dtype=np.float64), 0.0, 1.0)
    return 10.0 ** (DRAINAGE_SAND_LOG10_MM_PER_DAY + DRAINAGE_LOG10_PER_CLAY_SHARE * clay)


def soil_water_properties(clay):
    """``(available water in mm per metre, capillary rise in m)`` of a soil by its clay share (0..1)."""
    clay = np.clip(np.asarray(clay, dtype=np.float64), 0.0, 1.0)
    available = (AWC_COARSE_MM_PER_M + (AWC_LOAM_MM_PER_M - AWC_COARSE_MM_PER_M) * np.clip(clay / 0.35, 0.0, 1.0)
                 - (AWC_LOAM_MM_PER_M - AWC_HEAVY_CLAY_MM_PER_M) * np.clip((clay - 0.6) / 0.4, 0.0, 1.0))
    rise = CAPILLARY_RISE_COARSE_M + (CAPILLARY_RISE_CLAY_M - CAPILLARY_RISE_COARSE_M) * clay ** 0.8
    return available, rise


def _parent_soil_fields(parent_soil_model, parent_window, shape):
    """The parent's soil over a child's footprint, on the child's lattice.

    ``parent_window`` is the footprint ``(u0, u1, v0, v1)`` in the parent's
    grid (0..1).  Cells the parent holds under water carry no soil record;
    they take the soil of the ground beside them, so a stream the parent drew
    a cell wide does not come down as a strip of bare ground.
    """
    from simulations.world_gen.material_routing import box_mean

    grid = (parent_soil_model or {}).get("grid") if isinstance(parent_soil_model, dict) else None
    if not isinstance(grid, dict) or parent_window is None:
        return None
    try:
        depth = np.asarray(grid.get("soil_depth_m_rows"), dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if depth.ndim != 2 or depth.shape[0] < 2 or depth.shape[1] < 2:
        return None
    ground = (depth > 0.0).astype(np.float64)
    if not ground.any():
        return None
    cover = box_mean(ground, 2)
    u0, u1, v0, v1 = (float(value) for value in parent_window)
    height, width = shape
    gx = np.clip(u0 + (u1 - u0) * np.arange(width) / max(1, width - 1), 0.0, 1.0) * (depth.shape[1] - 1)
    gy = np.clip(v0 + (v1 - v0) * np.arange(height) / max(1, height - 1), 0.0, 1.0) * (depth.shape[0] - 1)
    ix = np.minimum(depth.shape[1] - 2, gx.astype(int))
    iy = np.minimum(depth.shape[0] - 2, gy.astype(int))
    fx = (gx - ix)[None, :]
    fy = (gy - iy)[:, None]
    fields = {}
    for name in _INHERITED_SOIL_FIELDS + _INHERITED_WHERE_PRESENT:
        if name in _INHERITED_WHERE_PRESENT and not grid.get(name):
            continue
        try:
            values = np.asarray(grid.get(name), dtype=np.float64)
        except (TypeError, ValueError):
            return None
        if values.shape != depth.shape:
            return None
        beside = box_mean(values * ground, 2) / np.maximum(cover, 1e-6)
        filled = np.where(ground > 0.0, values, np.where(cover > 0.0, beside, float(values[ground > 0.0].mean())))
        top = filled[iy][:, ix] * (1.0 - fx) + filled[iy][:, ix + 1] * fx
        bottom = filled[iy + 1][:, ix] * (1.0 - fx) + filled[iy + 1][:, ix + 1] * fx
        fields[name] = top * (1.0 - fy) + bottom * fy
    return fields


def derive_regolith_soil_model(
    planet, heightmap, water_cycle, surface_evolution, material_model, *, parent_soil_model=None, parent_window=None,
):
    """Resolve parent material + climate + relief + time into abiotic soils.

    Biology is deliberately absent; a later biosphere model may amend organic
    carbon, nutrient cycling, aggregation, and bioturbation.

    From ``FINE_SOIL_MIN_LEVEL`` the tile inherits its parent's soil
    (``parent_soil_model`` over ``parent_window``) and adds only what its own
    relief decides: curvature, and the bars and channel fills of a floodplain.
    """
    planet = planet if isinstance(planet, dict) else {}
    heightmap = heightmap if isinstance(heightmap, dict) else {}
    water_cycle = water_cycle if isinstance(water_cycle, dict) else {}
    surface_evolution = surface_evolution if isinstance(surface_evolution, dict) else {}
    material_model = material_model if isinstance(material_model, dict) else {}
    climate = water_cycle.get("climate_grid") if isinstance(water_cycle.get("climate_grid"), dict) else {}
    grid = heightmap.get("sample_grid") if isinstance(heightmap.get("sample_grid"), dict) else {}
    elevation_rows = grid.get("rows") or []
    if not elevation_rows:
        return {"status": "unavailable", "reason": "heightfield_missing"}
    height, width = len(elevation_rows), len(elevation_rows[0])
    process = surface_evolution.get("process_grid") if isinstance(surface_evolution.get("process_grid"), dict) else {}
    sea_level_value = heightmap.get("sea_level_m")
    sea_level = None if sea_level_value is None else float(sea_level_value)
    runoff_grid = water_cycle.get("runoff_grid") if isinstance(water_cycle.get("runoff_grid"), dict) else {}
    wetness_rows = runoff_grid.get("wetness_index_rows") or []
    surface_water = water_cycle.get("surface_water_grid") if isinstance(water_cycle.get("surface_water_grid"), dict) else {}
    surface_age_myr = max(0.0, float(planet.get("simulated_geology_age_myr", planet.get("surface_record_age_myr", 100.0)) or 100.0))
    age_factor = _clamp(math.log1p(surface_age_myr) / math.log(4501.0))
    elements = material_model.get("element_profile") if isinstance(material_model.get("element_profile"), dict) else {}

    elevation = np.asarray([row[:width] for row in elevation_rows], dtype=np.float64)
    # A cell is under water by the share of it the water covers, not because
    # a stream narrower than the cell is drawn through it: such a cell is
    # ground, with that much less soil on average.  Regions without the
    # share fall back on the flag.
    if surface_water.get("water_fraction_rows"):
        water_share = np.clip(_nearest_rows(surface_water.get("water_fraction_rows"), height, width, 0.0), 0.0, 1.0)
    else:
        water_share = (_nearest_rows(surface_water.get("water_presence_rows"), height, width, 0.0) > 0.5).astype(np.float64)
    if sea_level is not None:
        water_share = np.where(elevation <= sea_level, 1.0, water_share)
    water = water_share >= 0.5
    land = ~water
    land_cells = int(land.sum())

    local = _province_elements(planet, heightmap, height, width)

    def element(symbol):
        default = float(elements.get(symbol, 0.0) or 0.0)
        if local is None:
            return np.full((height, width), default)
        return np.where(np.isnan(local[symbol]), default, local[symbol])

    carbonate_buffer = np.clip(element("Ca") / 5.0, 0.0, 1.0)
    sulfur_acidity = np.clip(element("S") / 1.5, 0.0, 1.0)
    # Inventory potentials only: availability is resolved later by
    # biosphere weathering/cycling. Element profiles are percentages.
    parent_nitrogen = np.clip(np.log1p(np.maximum(0.0, element("N")) * 10.0) / math.log(2.0), 0.0, 1.0)
    parent_phosphorus = np.clip(np.log1p(np.maximum(0.0, element("P")) * 5.0) / math.log(2.0), 0.0, 1.0)
    temperature = _nearest_rows(climate.get("temperature_rows_k"), height, width, 273.15)
    precipitation = np.maximum(0.0, _nearest_rows(climate.get("annual_precipitation_rows_mm"), height, width, 0.0))
    infiltration = np.maximum(0.0, _nearest_rows(climate.get("annual_infiltration_rows_mm"), height, width, 0.0))
    weathering = np.clip(_nearest_rows(process.get("chemical_weathering_rows"), height, width, 0.0), 0.0, 1.0)
    deposition = np.clip(_nearest_rows(process.get("sediment_deposition_rows"), height, width, 0.0), 0.0, 1.0)
    erosion = np.clip(_nearest_rows(process.get("erosion_intensity_rows") or process.get("erosion_potential_rows"), height, width, 0.0), 0.0, 1.0)
    ice_rows = (heightmap.get("surface_masks") or {}).get("ice_rows") or []
    icy = _nearest_rows([[1.0 if value else 0.0 for value in row] for row in ice_rows], height, width, 0.0) > 0.5
    if wetness_rows:
        moisture = np.clip(_nearest_rows(wetness_rows, height, width, 0.0), 0.0, 1.0)
    else:
        moisture = np.clip((precipitation + infiltration * 0.7) / 1800.0, 0.0, 1.0)
    aridity = np.clip(1.0 - precipitation / np.maximum(180.0, (temperature - 245.0) * 42.0), 0.0, 1.0)
    depth_m = np.clip((weathering * 2.4 + deposition * 3.1 + age_factor * 0.55) * (1.0 - erosion * 0.72), 0.01, 6.0)
    depth_m = np.where(icy, depth_m * 0.55, depth_m)
    soil_classes = np.select(
        [
            icy,
            (deposition > 0.58) & (moisture > 0.25),
            (weathering > 0.56) & (temperature > 285.0) & (moisture > 0.45),
            aridity > 0.72,
            erosion > 0.62,
        ],
        [
            "glacial_till_or_frozen_regolith",
            "alluvial_abiotic_soil",
            "deep_weathered_saprolitic_soil",
            "arid_saline_regolith",
            "thin_colluvial_regolith",
        ],
        default="weathered_mineral_soil",
    )
    names, counts = np.unique(soil_classes[land], return_counts=True)
    classes = {str(name): int(count) for name, count in zip(names, counts)}
    clay = np.clip(weathering * 0.62 + deposition * 0.24, 0.0, 1.0)
    porosity = np.clip(0.18 + clay * 0.24 + deposition * 0.14 - depth_m * 0.012, 0.08, 0.62)
    permeability = np.clip((1.0 - clay) * (0.35 + porosity) * (1.0 - deposition * 0.28), 0.0, 1.0)
    ph = np.clip(7.1 + carbonate_buffer * 1.4 - moisture * sulfur_acidity * 2.0 - weathering * 0.7, 3.2, 10.5)
    salinity = np.clip(aridity * (0.25 + deposition * 0.55) + (1.0 - moisture) * sulfur_acidity * 0.16, 0.0, 1.0)
    available_water, capillary_rise = soil_water_properties(clay)
    drainage_rate = soil_drainage_rate(clay)
    rootable_m = None

    fine_soil = None
    level = int(heightmap.get("map_detail_level", 0) or 0)
    spacing_x = float(heightmap.get("sample_spacing_x_m") or 0.0)
    spacing_y = float(heightmap.get("sample_spacing_y_m") or 0.0)
    inherited = None
    if level >= FINE_SOIL_MIN_LEVEL:
        from simulations.world_gen.material_routing import box_mean, gaussian_blur

        inherited = _parent_soil_fields(parent_soil_model, parent_window, (height, width))
        if inherited is not None:
            depth_m = inherited["soil_depth_m_rows"]
            porosity = inherited["porosity_rows"]
            permeability = inherited["relative_permeability_rows"]
            ph = inherited["ph_rows"]
            salinity = inherited["salinity_index_rows"]
            available_water = inherited.get("available_water_capacity_rows_mm_per_m", available_water)
            capillary_rise = inherited.get("capillary_rise_rows_m", capillary_rise)
            drainage_rate = inherited.get("drainage_rate_rows_mm_per_day", drainage_rate)
            rootable_m = inherited.get("rootable_depth_m_rows")
        if spacing_x > 0.0 and spacing_y > 0.0:
            # Curvature of the ground at the scale soil creeps over (a metre
            # or two), kept zero-mean at the parent's spacing.
            cells = max(1.0, 1.5 / min(spacing_x, spacing_y))
            smooth = gaussian_blur(elevation, cells)
            padded = np.pad(smooth, 1, mode="edge")
            curvature = (
                (padded[1:-1, 2:] + padded[1:-1, :-2] - 2.0 * smooth) / (spacing_x * spacing_x)
                + (padded[2:, 1:-1] + padded[:-2, 1:-1] - 2.0 * smooth) / (spacing_y * spacing_y)
            )
            factor = np.exp(np.clip(curvature * CURVATURE_LENGTH_M, -CURVATURE_LOG_SPAN, CURVATURE_LOG_SPAN))
            parent_spacing = float((heightmap.get("refinement_detail_band") or {}).get("parent_sample_spacing_m") or 0.0)
            radius = max(1, int(round(0.5 * parent_spacing / max(spacing_x, spacing_y))))
            depth_m = depth_m * factor / np.maximum(box_mean(factor, radius), 1e-6)
    # The relic-channel orders this level built, whatever the level (the
    # first order is a Site-scale form); wider ones are in the parent's soil.
    from simulations.world_gen.floodplain_relics import _wide_blur, heightmap_relic_fields

    relics = heightmap_relic_fields(heightmap, (height, width), built_at_level=level) if spacing_x > 0.0 and spacing_y > 0.0 else None
    if relics is not None:
        floor = relics["floor"]
        bar = (1.0 - relics["floor"]) * relics["floodplain"]
        cover = 1.0 - BAR_THINNING * bar * relics["fresh"]
        lanes = relics["spacing_m"] / max(spacing_x, spacing_y)
        depth_m = (
            depth_m * cover / np.maximum(_wide_blur(cover, lanes), 1e-6)
            + relics["fill_m"] - _wide_blur(relics["fill_m"], lanes)
        )
        porosity = np.clip(porosity + CHANNEL_FILL_POROSITY * floor, 0.08, 0.62)
        permeability = np.clip(permeability * (1.0 - CHANNEL_FILL_PERMEABILITY * floor), 0.0, 1.0)
        # The fill of an abandoned channel is fines that hold water and lift it; a fresh bar is coarse and
        # does neither.  Both are loose sediment roots can go into.
        coarse = bar * relics["fresh"]
        available_water = available_water + (AWC_LOAM_MM_PER_M - available_water) * floor
        available_water = available_water + (AWC_COARSE_MM_PER_M - available_water) * coarse
        capillary_rise = capillary_rise + (CAPILLARY_RISE_FILL_M - capillary_rise) * floor
        capillary_rise = capillary_rise + (CAPILLARY_RISE_COARSE_M - capillary_rise) * coarse
        # Rates span orders of magnitude: they are blended by their logarithms.
        drainage_rate = np.exp(np.log(drainage_rate) + (math.log(DRAINAGE_FILL_MM_PER_DAY) - np.log(drainage_rate)) * floor)
        drainage_rate = np.exp(np.log(drainage_rate) + (math.log(DRAINAGE_BAR_MM_PER_DAY) - np.log(drainage_rate)) * coarse)
        rootable_m = np.maximum(depth_m if rootable_m is None else rootable_m, FLOODPLAIN_ROOTABLE_M * relics["floodplain"])
    if level >= FINE_SOIL_MIN_LEVEL or relics is not None:
        depth_m = np.clip(depth_m, 0.01, 6.0)
        fine_soil = {
            "inherits_parent_soil": inherited is not None,
            "curvature_length_m": CURVATURE_LENGTH_M if level >= FINE_SOIL_MIN_LEVEL else None,
            "relic_channel_fills": relics is not None,
        }

    from simulations.world_gen import rock_scarps

    if spacing_x > 0.0 and spacing_y > 0.0:
        # Soil does not rest on ground steeper than the angle of repose,
        # whatever made it that steep.
        from simulations.world_gen.material_routing import CLIFF_GRADIENT, REPOSE_GRADIENT

        fall_y, fall_x = np.gradient(elevation, spacing_y, spacing_x)
        depth_m = depth_m * (1.0 - np.clip((np.hypot(fall_x, fall_y) - REPOSE_GRADIENT) / (CLIFF_GRADIENT - REPOSE_GRADIENT), 0.0, 1.0))
    scarps = rock_scarps.heightmap_scarp_fields(heightmap, (height, width))
    scarp_soil = None
    if scarps is not None:
        # Limits, not factors: a finer level that inherits this soil and
        # applies its own scarp does not thin it twice.
        talus, rampart = scarps["talus"], scarps["rampart"]
        depth_m = depth_m + (np.minimum(depth_m, RAMPART_SOIL_DEPTH_M) - depth_m) * rampart
        depth_m = depth_m + (np.minimum(depth_m, TALUS_SOIL_DEPTH_M) - depth_m) * talus
        depth_m = depth_m * (1.0 - scarps["face"])
        porosity = porosity + (TALUS_POROSITY - porosity) * talus
        permeability = permeability + (1.0 - permeability) * talus
        scarp_soil = {
            name: round(float((scarps[name] > 0.5)[land].mean()) if land_cells else 0.0, 5)
            for name in ("face", "talus", "rampart")
        }

    def rows_of(values, water_value, digits):
        return np.round(np.where(land, values, water_value), digits).tolist()

    depth_rows = np.round(depth_m * (1.0 - water_share), 4).tolist()
    # What can be rooted is at least the soil, and no more than the soil where scarps and steep ground bared it.
    rootable_m = depth_m if rootable_m is None else np.maximum(depth_m, np.where(depth_m > 0.0, rootable_m, 0.0))
    rootable_rows = np.round(rootable_m * (1.0 - water_share), 3).tolist()
    porosity_rows = rows_of(porosity, 0.0, 4)
    permeability_rows = rows_of(permeability, 0.0, 4)
    ph_rows = rows_of(ph, 7.0, 3)
    salinity_rows = rows_of(salinity, 1.0, 4)
    moisture_rows = rows_of(moisture, 1.0, 4)
    parent_nitrogen_rows = rows_of(parent_nitrogen, 0.0, 4)
    parent_phosphorus_rows = rows_of(parent_phosphorus, 0.0, 4)

    dominant = sorted(classes.items(), key=lambda row: (-row[1], row[0]))
    return {
        "status": "abiotic_soils_resolved",
        "model_version": "regolith-soils-v2-hydrology-coupled",
        "causal_inputs": ["parent_material", "climate", "topography", "surface_processes", "surface_record_age"],
        "biosphere_contribution": "excluded_pending_separate_design",
        "nutrient_status": "deferred_to_biomatter_system",
        "dominant_soil_classes": [{"id": name, "land_fraction": round(count / max(1, land_cells), 4)} for name, count in dominant[:6]],
        "grid": {
            "width": width, "height": height,
            "soil_depth_m_rows": depth_rows,
            "porosity_rows": porosity_rows,
            "relative_permeability_rows": permeability_rows,
            "ph_rows": ph_rows,
            "salinity_index_rows": salinity_rows,
            "soil_moisture_rows": moisture_rows,
            "parent_nitrogen_index_rows": parent_nitrogen_rows,
            "parent_phosphorus_index_rows": parent_phosphorus_rows,
            # The sediment's own figures, under water too: read at a bank they are the bank's, not half of it.
            "available_water_capacity_rows_mm_per_m": np.round(available_water * np.ones(land.shape), 1).tolist(),
            "capillary_rise_rows_m": np.round(capillary_rise * np.ones(land.shape), 3).tolist(),
            "drainage_rate_rows_mm_per_day": np.round(drainage_rate * np.ones(land.shape), 3).tolist(),
            "rootable_depth_m_rows": rootable_rows,
        },
        **({"fine_scale_soil": fine_soil} if fine_soil is not None else {}),
        **({"rock_scarp_cell_fractions": scarp_soil} if scarp_soil is not None else {}),
        "tracked_properties": ["depth", "porosity", "permeability", "pH", "salinity", "moisture", "parent_mineralogy", "parent_nitrogen_inventory", "parent_phosphorus_inventory", "available_water_capacity", "capillary_rise", "rootable_depth", "subsoil_drainage_rate"],
        "excluded_properties": ["organic_matter", "nutrient_availability", "fertility", "bioturbation"],
    }
