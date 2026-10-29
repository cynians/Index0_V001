"""Read-only physical sampler shared by Map/Biosphere; no geography generation."""
import math
from simulations.world_gen.reference_raster import NativeRasterTiles

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships with the app
    np = None


NEAREST_FIELDS = frozenset({"landcover_class", "water_presence", "wetland_presence", "channel_presence"})
# Standing or flowing water a land plant cannot root in and nothing is built on.
OPEN_WATER_DEPTH_M = 0.05


def _ground_screen_to_world(substrate, state, screen_pos):
    """Ray/heightfield intersection, preserving clicking on elevated ground.

    ``state`` may carry ``datum_m`` (the elevation drawn at the ground plane)
    and ``vertical_scale``; both default to the original 1:1 absolute view.
    """
    scale = state["scale"]
    datum = float(state.get("datum_m", 0.0) or 0.0)
    vertical = float(state.get("vertical_scale", 1.0) or 1.0)
    a = (screen_pos[0] - state["origin_x"]) / scale
    b = (screen_pos[1] - state["origin_y"]) / (scale * .5)
    bx, by = state["center_x"] + (a+b)*.5, state["center_y"] + (b-a)*.5
    lo = (substrate.heightmap["min_elevation_m"] - datum) * vertical - 1
    hi = (substrate.heightmap["max_elevation_m"] - datum) * vertical + 1
    if hi < lo:
        lo, hi = hi, lo
    def residual(z):
        return (substrate.elevation(bx+z, by+z, True) - datum) * vertical - z
    # Pick the frontmost crossing in a potentially non-monotone terrain ray.
    previous, fp = hi, residual(hi)
    for i in range(1, 129):
        z = hi - (hi-lo)*i/128
        f = residual(z)
        if fp <= 0 <= f:
            low, high = z, previous
            for _ in range(24):
                mid = (low+high)*.5
                if residual(mid) >= 0:
                    low = mid
                else:
                    high = mid
            z = (low+high)*.5
            return bx+z, by+z
        previous, fp = z, f
    return bx, by


# What ``biosphere.water_balance`` reads, where a map carries it: the air's demand and the year's rain, what
# the soil holds and lifts, how deep it can be rooted, what runs on from upslope, and the depth to ground water.
WATER_BALANCE_FIELDS = (
    "annual_potential_evaporation_mm", "driest_month_precipitation_mm", "wettest_month_precipitation_mm",
    "summer_precipitation_fraction", "available_water_mm_per_m", "capillary_rise_m", "rootable_depth_m",
    "water_table_depth_m", "lateral_water_mm", "drainage_mm_per_day", "groundwater_salinity",
)


# How often a river covers the ground and how often it reworks it, in years (``world_gen.river_floods``).
FLOOD_FIELDS = ("flood_return_period_years", "flood_reworking_return_period_years")


class WorldgenSubstrate:
    def __init__(self, source, bounds):
        self.source = source
        self.bounds = dict(bounds)
        self.heightmap = source["heightmap_model"]
        native = self.heightmap.get("native_raster_tiles")
        self.native = NativeRasterTiles(native, bounds) if native else None
        water = source.get("water_cycle_model") or {}
        climate = water.get("climate_grid") or (source.get("koppen_climate_model") or {}).get("climate_grid") or {}
        runoff = water.get("runoff_grid") or {}
        surface = water.get("surface_water_grid") or {}
        soil = (source.get("regolith_soil_model") or {}).get("grid") or {}
        insolation = water.get("insolation_grid") or {}
        self.fields = dict(elevation_m=self.heightmap["sample_grid"]["rows"],
                           soil_moisture=runoff.get("wetness_index_rows") or soil.get("soil_moisture_rows"), channel_presence=runoff.get("channel_presence_rows"),
                           surface_solar_exposure=(climate.get("surface_solar_exposure_rows")
                                                   or insolation.get("surface_solar_exposure_rows")),
                           temperature_k=climate.get("temperature_rows_k"), annual_precipitation_mm=climate.get("annual_precipitation_rows_mm"),
                           water_depth_m=surface.get("water_depth_m_rows"), water_surface_elevation_m=surface.get("water_surface_elevation_m_rows"),
                           salinity_psu=surface.get("salinity_psu_rows"), soil_depth_m=soil.get("soil_depth_m_rows"),
                           soil_salinity_index=soil.get("salinity_index_rows"),
                           available_water_mm_per_m=soil.get("available_water_capacity_rows_mm_per_m"),
                           capillary_rise_m=soil.get("capillary_rise_rows_m"),
                           rootable_depth_m=soil.get("rootable_depth_m_rows"),
                           drainage_mm_per_day=soil.get("drainage_rate_rows_mm_per_day"),
                           water_table_depth_m=runoff.get("water_table_depth_m_rows"),
                           groundwater_salinity=runoff.get("groundwater_salinity_rows"),
                           lateral_water_mm=runoff.get("lateral_water_rows_mm"),
                           flood_return_period_years=surface.get("flood_return_period_rows_years"),
                           flood_reworking_return_period_years=surface.get("flood_reworking_return_period_rows_years"),
                           annual_potential_evaporation_mm=climate.get("annual_potential_evaporation_rows_mm"),
                           driest_month_precipitation_mm=climate.get("driest_month_precipitation_rows_mm"),
                           wettest_month_precipitation_mm=climate.get("wettest_month_precipitation_rows_mm"),
                           summer_precipitation_fraction=climate.get("summer_precipitation_fraction_rows"),
                           soil_fertility=soil.get("fertility_index_rows"), soil_ph=soil.get("ph_rows"),
                           parent_nitrogen_index=soil.get("parent_nitrogen_index_rows"),
                           parent_phosphorus_index=soil.get("parent_phosphorus_index_rows"),
                           abiotic_rgb=self.heightmap.get("abiotic_rgb_rows"))
        self.fields.update(water_presence=surface.get("water_presence_rows"),
            landcover_class=((source.get("landcover_model") or {}).get("grid") or {}).get("class_rows"),
            wetland_presence=((source.get("wetlands_model") or {}).get("grid") or {}).get("wetland_presence_rows"))
        # Seasonal climate is optional: only generated regions carry it.
        self.fields.update(
            coldest_month_temperature_k=climate.get("seasonal_min_temperature_rows_k"),
            warmest_month_temperature_k=climate.get("seasonal_max_temperature_rows_k"),
        )
        self.nutrient_status = (source.get("regolith_soil_model") or {}).get(
            "nutrient_status", "unresolved"
        )
        self._koppen_rows = climate.get("koppen_rows") or None
        self._koppen_labels = {
            item.get("id"): item.get("label") for item in (water.get("koppen_classes") or [])
            if isinstance(item, dict)
        }
        for key, rows in self.fields.items():
            if rows is None:
                continue
            if len(rows) < 2 or len(rows[0]) < 2 or any(len(row) != len(rows[0]) for row in rows):
                raise ValueError(f"Invalid substrate grid: {key}")
        self.fingerprint = tuple((key, id(rows)) for key, rows in self.fields.items()) + (self.heightmap.get("input_fingerprint"),)
        self._arrays = {}

    def sample(self, key, x, y, default=0.0):
        if key == "elevation_m" and self.native is not None:
            value = self.native.sample(x, y)
            # Rendering/reference plane only; environment exposes unknown explicitly.
            return value if math.isfinite(value) else default
        rows = self.fields.get(key)
        if rows is None:
            return default
        b = self.bounds
        nx = max(0, min(1, (x - b["min_x"]) / (b["max_x"] - b["min_x"])))
        ny = max(0, min(1, (y - b["min_y"]) / (b["max_y"] - b["min_y"])))
        gx, gy = nx * (len(rows[0]) - 1), ny * (len(rows) - 1)
        if key in NEAREST_FIELDS:
            value = rows[round(gy)][round(gx)]
            return value.item() if hasattr(value, "item") else value
        ix, iy = min(len(rows[0]) - 2, int(gx)), min(len(rows) - 2, int(gy))
        fx, fy = gx - ix, gy - iy
        values = [rows[iy][ix], rows[iy][ix + 1], rows[iy + 1][ix], rows[iy + 1][ix + 1]]
        def blend(v):
            if not all(math.isfinite(float(a)) for a in v):
                raise ValueError(f"Non-finite substrate field: {key}")
            return (v[0] * (1-fx) + v[1] * fx) * (1-fy) + (v[2] * (1-fx) + v[3] * fx) * fy
        return tuple(float(blend([v[c] for v in values])) for c in range(3)) if key == "abiotic_rgb" else float(blend(values))

    def array(self, key):
        """The field as a float array, built once; ``None`` when absent."""
        if key not in self._arrays:
            rows = self.fields.get(key)
            self._arrays[key] = None if rows is None or np is None else np.asarray(
                [getattr(row, "values", row) for row in rows], dtype=np.float64,
            )
        return self._arrays[key]

    def sample_array(self, key, xs, ys, default=0.0):
        """``sample`` over arrays of points; one result per point."""
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)
        grid = self.array(key)
        if grid is None or (key == "elevation_m" and self.native is not None):
            if key == "elevation_m" and self.native is not None:
                return np.vectorize(lambda x, y: self.sample(key, x, y, default), otypes=[np.float64])(xs, ys)
            return np.full(xs.shape, float(default), dtype=np.float64)
        b = self.bounds
        gx = np.clip((xs - b["min_x"]) / (b["max_x"] - b["min_x"]), 0.0, 1.0) * (grid.shape[1] - 1)
        gy = np.clip((ys - b["min_y"]) / (b["max_y"] - b["min_y"]), 0.0, 1.0) * (grid.shape[0] - 1)
        if key in NEAREST_FIELDS:
            return grid[np.rint(gy).astype(int), np.rint(gx).astype(int)]
        ix = np.minimum(grid.shape[1] - 2, gx.astype(int))
        iy = np.minimum(grid.shape[0] - 2, gy.astype(int))
        fx, fy = gx - ix, gy - iy
        if grid.ndim == 3:
            fx, fy = fx[..., None], fy[..., None]
        top = grid[iy, ix] * (1 - fx) + grid[iy, ix + 1] * fx
        bottom = grid[iy + 1, ix] * (1 - fx) + grid[iy + 1, ix + 1] * fx
        return top * (1 - fy) + bottom * fy

    def elevation(self, x, y, visible_surface=False):
        z = self.sample("elevation_m", x, y)
        return z + self.sample("water_depth_m", x, y) if visible_surface else z

    def elevation_array(self, xs, ys, visible_surface=False):
        z = self.sample_array("elevation_m", xs, ys)
        return z + self.sample_array("water_depth_m", xs, ys) if visible_surface else z

    def typical(self, key):
        """The median of a field over the map's land, or ``None``: the ground where nothing special happens.

        What a built soil adds to wetness is reckoned for this ground and
        added everywhere alike (``ecology.mature_wetness``).
        """
        cache = self.__dict__.setdefault("_typical", {})
        if key not in cache:
            values = self.array(key)
            value = None
            if values is not None:
                depth = self.array("water_depth_m")
                land = values[depth <= OPEN_WATER_DEPTH_M] if depth is not None and depth.shape == values.shape else values
                land = land[np.isfinite(land)]
                value = float(np.median(land)) if land.size else None
            cache[key] = value
        return cache[key]

    def open_water_array(self, xs, ys):
        deep = self.sample_array("water_depth_m", xs, ys) > OPEN_WATER_DEPTH_M
        if self.fields.get("water_depth_m") is not None:
            return deep
        return deep | (self.sample_array("water_presence", xs, ys) > .5)

    def terrain_known_at(self, x, y):
        return self.native is None or math.isfinite(self.native.sample(x, y))

    def open_water_at(self, x, y):
        # Worldgen marks every characteristic channel as water, down to rills
        # a few centimetres deep that run only after rain.  Where depth is
        # resolved it decides; presence alone counts only without it.
        if self.sample("water_depth_m",x,y) > OPEN_WATER_DEPTH_M:
            return True
        return self.fields.get("water_depth_m") is None and self.sample("water_presence",x,y) > .5

    def terrestrial_habitat_at(self, x, y):
        return self.terrain_known_at(x,y) and not self.open_water_at(x,y)

    def koppen_at(self, x, y):
        """``(class id, label)`` of the climate zone at a point, or ``None``."""
        rows = self._koppen_rows
        if not rows or not rows[0]:
            return None
        b = self.bounds
        nx = max(0, min(1, (x - b["min_x"]) / (b["max_x"] - b["min_x"])))
        ny = max(0, min(1, (y - b["min_y"]) / (b["max_y"] - b["min_y"])))
        zone = rows[round(ny * (len(rows) - 1))][round(nx * (len(rows[0]) - 1))]
        return (zone, self._koppen_labels.get(zone) or zone) if zone else None

    def sample_spacing_m(self):
        """Ground distance between elevation samples in this substrate's frame."""
        rows = self.fields["elevation_m"]
        b = self.bounds
        return max((b["max_x"] - b["min_x"]) / max(1, len(rows[0]) - 1),
                   (b["max_y"] - b["min_y"]) / max(1, len(rows) - 1))

    def environment_at(self, x, y):
        result = {key: self.sample(key, x, y, default) for key, default in (
            ("elevation_m", 0.), ("soil_moisture", .5), ("soil_fertility", .5),
            ("surface_solar_exposure", 1.), ("channel_presence", 0.), ("water_depth_m", 0.),
            ("salinity_psu", 0.), ("temperature_k", 285.15), ("annual_precipitation_mm", 1000.),
            ("soil_depth_m", .3), ("soil_ph", 6.5), ("soil_salinity_index", 0.))}
        typical = self.typical("soil_moisture")
        if typical is not None:
            result["typical_soil_moisture"] = typical
        result["parent_nitrogen_index"] = self.sample("parent_nitrogen_index", x, y, 0.18)
        result["parent_phosphorus_index"] = self.sample("parent_phosphorus_index", x, y, 0.42)
        for key in ("coldest_month_temperature_k", "warmest_month_temperature_k") + WATER_BALANCE_FIELDS + FLOOD_FIELDS:
            if self.fields.get(key) is not None:
                result[key] = self.sample(key, x, y)
        lo, hi = self.heightmap["min_elevation_m"], self.heightmap["max_elevation_m"]
        result["elevation_norm"] = max(0, min(1, (result["elevation_m"] - lo) / max(.001, hi-lo)))
        result["terrain_elevation_known"] = self.terrain_known_at(x,y)
        result["observed_elevation_m"] = result["elevation_m"] if result["terrain_elevation_known"] else None
        result["open_water"] = self.open_water_at(x,y)
        result["landcover_class"] = self.sample("landcover_class",x,y,None)
        result["wetland_presence"] = self.sample("wetland_presence",x,y)
        result["runtime_default_fields"] = [k for k in result if k in self.fields and self.fields[k] is None]
        result["nutrient_status"] = self.nutrient_status
        if isinstance(self.source.get('atmosphere_model'), dict) and self.source['atmosphere_model']:
            result['atmosphere_model'] = self.source['atmosphere_model']
        return result

    def ground_screen_to_world(self, state, screen_pos):
        return _ground_screen_to_world(self, state, screen_pos)


# What the air brings does not change between two points a metre apart.
CLIMATE_FIELDS = (
    "temperature_k", "coldest_month_temperature_k", "warmest_month_temperature_k", "annual_precipitation_mm",
    "annual_potential_evaporation_mm", "driest_month_precipitation_mm", "wettest_month_precipitation_mm",
    "summer_precipitation_fraction",
)


class LayeredSubstrate:
    """One region's ground, overridden by finer refined patches where they exist.

    Every layer is a ``WorldgenSubstrate`` expressed in the same frame, so a
    point is answered by the finest layer that contains it.

    A refinement re-derives every field from its own models and drifts from
    its parent: a degree or two warmer, a tenth less rain, several times the
    wetness once it resolves rills.  A view that lets finer patches appear on
    demand must not let them change what the ground can carry, so it can ask
    for two things:

    ``climate_from_base``
        temperature and precipitation are read from the region everywhere;
    ``conserved_fields``
        a patch keeps its own pattern for these fields, brought to the
        region's mean over the same ground.  A patch shows where the region's
        water sits; it does not add water.  Its driest ground stays as dry as
        it was (that is what the climate gives); only what lies above that,
        the surplus a patch puts into its rills and hollows, is scaled.
    """

    def __init__(self, base, patches=(), *, climate_from_base=False, conserved_fields=()):
        self.base = base
        self.climate_from_base = bool(climate_from_base)
        self.conserved_fields = tuple(conserved_fields)
        self._gains = {}
        # Given coarsest first; kept finest first so the first hit wins.
        self.patches = list(reversed(list(patches)))
        self.bounds = base.bounds
        self.source = base.source
        self.heightmap = base.heightmap
        self.native = base.native
        self.fields = base.fields
        self.nutrient_status = base.nutrient_status
        self.fingerprint = (base.fingerprint,) + tuple(
            (substrate.source.get("id"), substrate.fingerprint) for _bounds, substrate in self.patches
        )

    def substrate_at(self, x, y):
        for bounds, substrate in self.patches:
            if bounds["min_x"] <= x <= bounds["max_x"] and bounds["min_y"] <= y <= bounds["max_y"]:
                return substrate
        return self.base

    def _from_base(self, key):
        return self.climate_from_base and key in CLIMATE_FIELDS and self.base.fields.get(key) is not None

    def conservation(self, bounds, substrate, key):
        """``(scale, offset)`` that brings a patch's ``key`` to the region's mean over the same ground."""
        if key not in self.conserved_fields or substrate is self.base:
            return 1.0, 0.0
        cache_key = (id(substrate), key)
        mapping = self._gains.get(cache_key)
        if mapping is None:
            mapping = (1.0, 0.0)
            fine = substrate.array(key)
            if fine is not None and self.base.array(key) is not None:
                xs, ys = np.meshgrid(np.linspace(bounds["min_x"], bounds["max_x"], 48),
                                     np.linspace(bounds["min_y"], bounds["max_y"], 48))
                target = float(np.mean(self.base.sample_array(key, xs, ys)))
                mean, low, high = float(np.mean(fine)), float(np.min(fine)), float(np.max(fine))
                if all(math.isfinite(value) for value in (target, mean, low, high)):
                    if mean - low < 1e-9 or high - mean < 1e-9:
                        mapping = (1.0, target - mean)  # nothing to redistribute
                    else:
                        # Detail around the region's mean: as much of it as leaves the
                        # driest ground no drier than it was and the wettest within range.
                        scale = min((target - min(low, target)) / (mean - low), (1.0 - target) / (high - mean))
                        mapping = (scale, target - mean * scale)
            self._gains[cache_key] = mapping
        return mapping

    def _conserved(self, bounds, substrate, key, value):
        scale, offset = self.conservation(bounds, substrate, key)
        return max(0.0, min(1.0, value * scale + offset))

    def _patch_at(self, x, y, key=None):
        """The finest layer at a point; with ``key``, the finest that carries that field."""
        for bounds, substrate in self.patches:
            if (bounds["min_x"] <= x <= bounds["max_x"] and bounds["min_y"] <= y <= bounds["max_y"]
                    and (key is None or substrate.fields.get(key) is not None)):
                return bounds, substrate
        return self.bounds, self.base

    def _table_from_base(self, x, y, default):
        """Depth to the water table at a point, from the site's table and the finest ground there.

        The table is one smooth surface under the whole site.  A patch cut out
        of it cannot see the water beyond its edge that sets that surface, so
        the depth is the site's, corrected by how much higher or lower the
        patch's own ground lies.
        """
        depth = self.base.sample("water_table_depth_m", x, y, default)
        substrate = self._patch_at(x, y)[1]
        if substrate is self.base:
            return depth
        return max(0.0, depth + substrate.sample("elevation_m", x, y) - self.base.sample("elevation_m", x, y))

    def sample(self, key, x, y, default=0.0):
        if self._from_base(key):
            return self.base.sample(key, x, y, default)
        if key == "water_table_depth_m" and self.base.fields.get(key) is not None:
            return self._table_from_base(x, y, default)
        # A patch that does not carry a field leaves it to the layer beneath.
        bounds, substrate = self._patch_at(x, y, key)
        value = substrate.sample(key, x, y, default)
        if key in self.conserved_fields and substrate is not self.base:
            value = self._conserved(bounds, substrate, key, value)
        return value

    def elevation(self, x, y, visible_surface=False):
        return self.substrate_at(x, y).elevation(x, y, visible_surface)

    def environment_at(self, x, y):
        bounds, substrate = self._patch_at(x, y)
        result = substrate.environment_at(x, y)
        if substrate is self.base:
            return result
        missing = [key for key in result.get("runtime_default_fields", ())
                   if self._patch_at(x, y, key)[1].fields.get(key) is not None]
        for key in missing:
            result[key] = self.sample(key, x, y, result[key])
        if missing:
            result["runtime_default_fields"] = [key for key in result["runtime_default_fields"] if key not in missing]
        for key in CLIMATE_FIELDS:
            if self._from_base(key):
                result[key] = self.base.sample(key, x, y)
        # What a patch made before a field existed does not carry is the layer's beneath it.
        for key in WATER_BALANCE_FIELDS + FLOOD_FIELDS:
            if key not in result and self._patch_at(x, y, key)[1].fields.get(key) is not None:
                result[key] = self.sample(key, x, y)
        for key in self.conserved_fields:
            if key in result and substrate.fields.get(key) is not None:
                result[key] = self._conserved(bounds, substrate, key, result[key])
        if result.get("open_water") is not None and substrate.fields.get("water_depth_m") is None:
            result["open_water"] = self.open_water_at(x, y)
        # The ordinary ground is the whole site's, not that of the patch a point happens to lie in.
        typical = self.base.typical("soil_moisture")
        if typical is not None:
            result["typical_soil_moisture"] = typical
        if self.base.fields.get("water_table_depth_m") is not None:
            result["water_table_depth_m"] = self._table_from_base(x, y, 0.0)
        return result

    def typical(self, key):
        return self.base.typical(key)

    def terrain_known_at(self, x, y):
        return self.substrate_at(x, y).terrain_known_at(x, y)

    def open_water_at(self, x, y):
        substrate = self.substrate_at(x, y)
        if substrate.fields.get("water_depth_m") is None and substrate.fields.get("water_presence") is None:
            # A patch that resolved no water of its own does not dry the region's.
            return self.base.open_water_at(x, y)
        return substrate.open_water_at(x, y)

    def terrestrial_habitat_at(self, x, y):
        return self.substrate_at(x, y).terrestrial_habitat_at(x, y)

    def detail_level_at(self, x, y):
        return int(self.substrate_at(x, y).source.get("map_detail_level", 0) or 0)

    def koppen_at(self, x, y):
        if self.climate_from_base:
            return self.base.koppen_at(x, y) or self.substrate_at(x, y).koppen_at(x, y)
        return self.substrate_at(x, y).koppen_at(x, y) or self.base.koppen_at(x, y)

    def layers(self):
        """``[(bounds, substrate)]`` coarsest first, the base region included."""
        return [(self.bounds, self.base)] + list(reversed(self.patches))

    def sample_spacing_at(self, x, y):
        return self.substrate_at(x, y).sample_spacing_m()

    def _layered(self, xs, ys, sampler, key=None):
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)
        result = sampler(self.base, xs, ys)
        # Coarsest patch first, so finer ones overwrite it.
        for bounds, substrate in reversed(self.patches):
            if key is not None and substrate.fields.get(key) is None:
                continue
            inside = (
                (xs >= bounds["min_x"]) & (xs <= bounds["max_x"])
                & (ys >= bounds["min_y"]) & (ys <= bounds["max_y"])
            )
            if inside.any():
                result[inside] = sampler(substrate, xs[inside], ys[inside])
        return result

    def sample_array(self, key, xs, ys, default=0.0):
        if self._from_base(key):
            return self.base.sample_array(key, np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64), default)
        if key == "water_table_depth_m" and self.base.fields.get(key) is not None:
            xs, ys = np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)
            return np.maximum(0.0, self.base.sample_array(key, xs, ys, default)
                              + self.sample_array("elevation_m", xs, ys) - self.base.sample_array("elevation_m", xs, ys))
        if key not in self.conserved_fields:
            return self._layered(xs, ys, lambda layer, x, y: layer.sample_array(key, x, y, default), key)
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)
        result = self.base.sample_array(key, xs, ys, default)
        for bounds, substrate in reversed(self.patches):
            inside = (
                (xs >= bounds["min_x"]) & (xs <= bounds["max_x"])
                & (ys >= bounds["min_y"]) & (ys <= bounds["max_y"])
            )
            if inside.any() and substrate.fields.get(key) is not None:
                scale, offset = self.conservation(bounds, substrate, key)
                result[inside] = np.clip(
                    substrate.sample_array(key, xs[inside], ys[inside], default) * scale + offset, 0.0, 1.0)
        return result

    def elevation_array(self, xs, ys, visible_surface=False):
        return self._layered(xs, ys, lambda layer, x, y: layer.elevation_array(x, y, visible_surface))

    def open_water_array(self, xs, ys):
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)
        result = self.base.open_water_array(xs, ys)
        for bounds, substrate in reversed(self.patches):
            if substrate.fields.get("water_depth_m") is None and substrate.fields.get("water_presence") is None:
                continue
            inside = (
                (xs >= bounds["min_x"]) & (xs <= bounds["max_x"])
                & (ys >= bounds["min_y"]) & (ys <= bounds["max_y"])
            )
            if inside.any():
                result[inside] = substrate.open_water_array(xs[inside], ys[inside])
        return result

    def ground_screen_to_world(self, state, screen_pos):
        return _ground_screen_to_world(self, state, screen_pos)
