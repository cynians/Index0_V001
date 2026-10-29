"""Vectorised world-generation helpers must match their per-cell references."""

import math
import random
import unittest

import numpy as np

from simulations.world_gen import drainage
from simulations.world_gen import geological_noise
from simulations.world_gen import heightmap
from simulations.world_gen.exact_rounding import round_rows
from simulations.world_gen import regional_refinement as refinement
from simulations.world_gen import water_cycle
from simulations.world_gen.world_gen_sim import ice_mask_with_freezing_climate


def _random_rows(height, width, seed, low=-2000.0, high=3000.0):
    rng = random.Random(seed)
    return [[rng.uniform(low, high) for _x in range(width)] for _y in range(height)]


class RegionalReliefParityTests(unittest.TestCase):
    def setUp(self):
        self.rows = _random_rows(17, 25, 1)
        self.values = np.asarray(self.rows)
        rng = random.Random(2)
        self.samples = [(rng.uniform(-0.2, 1.2), rng.uniform(-0.1, 1.1)) for _ in range(200)]

    def test_bicubic_and_bilinear_grids_match_scalar_samplers(self):
        u = np.asarray([item[0] for item in self.samples])
        v = np.asarray([item[1] for item in self.samples])
        for wrap_x in (True, False):
            bicubic = refinement._sample_bicubic_grid(self.values, u, v, wrap_x=wrap_x)
            bilinear = refinement._sample_bilinear_grid(self.values, u, v, wrap_x=wrap_x)
            for index, (su, sv) in enumerate(self.samples):
                self.assertAlmostEqual(refinement._sample_bicubic(self.rows, su, sv, wrap_x=wrap_x), float(bicubic[index]), places=9)
                self.assertAlmostEqual(refinement._sample_bilinear(self.rows, su, sv, wrap_x=wrap_x), float(bilinear[index]), places=9)

    def test_structure_and_topology_grids_match_scalar_context(self):
        u = np.asarray([item[0] for item in self.samples])
        v = np.asarray([item[1] for item in self.samples])
        ruggedness, anchor = refinement._parent_structure_context_grid(self.values, u, v, 5000.0, wrap_x=True)
        topology = refinement._parent_topology_certainty_grid(self.values, u, v, 0.0, wrap_x=True)
        for index, (su, sv) in enumerate(self.samples):
            scalar_rugged, scalar_anchor = refinement._parent_structure_context(self.rows, su, sv, 5000.0, wrap_x=True)
            self.assertAlmostEqual(scalar_rugged, float(ruggedness[index]), places=9)
            self.assertAlmostEqual(scalar_anchor, float(anchor[index]), places=9)
            self.assertEqual(refinement._parent_topology_certainty(self.rows, su, sv, 0.0, wrap_x=True), int(topology[index]))

    def test_geological_noise_grids_match_scalar_noise(self):
        rng = np.random.default_rng(5)
        x = rng.uniform(-3.0e6, 4.1e7, 300)
        y = rng.uniform(-5.0e4, 2.0e7, 300)
        for period in (None, 40_030_000.0):
            fractal = geological_noise.fractal_noise_grid("seed", "k", x, y, 9_000.0, octaves=2, gain=0.44, period_x_m=period)
            branching = geological_noise.branching_mountain_relief_grid("seed", "b", x, y, 42_000.0, period_x_m=period)
            for index in range(x.size):
                self.assertEqual(
                    geological_noise.fractal_noise_m("seed", "k", x[index], y[index], 9_000.0, octaves=2, gain=0.44, period_x_m=period),
                    float(fractal[index]),
                )
                self.assertEqual(
                    geological_noise.branching_mountain_relief_m("seed", "b", x[index], y[index], 42_000.0, period_x_m=period),
                    float(branching[index]),
                )


class ClimateContextParityTests(unittest.TestCase):
    def setUp(self):
        self.rows = _random_rows(14, 22, 7, low=-1500.0, high=2500.0)
        self.ocean = [[value < 0.0 for value in row] for row in self.rows]
        self.span = 4000.0

    def test_terrain_metrics_grid_matches_per_cell_metrics(self):
        grid = water_cycle._terrain_metrics_grid(self.rows, self.ocean, self.span)
        for y in range(len(self.rows)):
            for x in range(len(self.rows[0])):
                scalar = water_cycle._terrain_metrics(self.rows, self.ocean, x, y, self.span)
                for key, value in scalar.items():
                    self.assertAlmostEqual(value, grid[y][x][key], places=12, msg=key)

    def test_upwind_relief_grid_matches_per_cell_ray_march(self):
        rng = random.Random(11)
        wind = [[(rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0)) for _x in row] for row in self.rows]
        grid = water_cycle._upwind_relief_context_grid(
            self.rows, self.ocean,
            [[item[0] for item in row] for row in wind],
            [[item[1] for item in row] for row in wind],
            self.span,
        )
        for y in range(len(self.rows)):
            for x in range(len(self.rows[0])):
                scalar = water_cycle._upwind_relief_context(
                    self.rows, self.ocean, x, y, wind[y][x][0], wind[y][x][1], self.span,
                )
                for key, value in scalar.items():
                    self.assertAlmostEqual(value, grid[y][x][key], places=12, msg=key)

    def test_prevailing_wind_grid_matches_scalar_vector(self):
        v_values = [index / 40.0 for index in range(41)]
        u_values = [0.13 + index / 57.0 for index in range(29)]
        wind_x, wind_y = water_cycle._prevailing_wind_grid(v_values, u_values, "wind-seed")
        for y, v in enumerate(v_values):
            for x, u in enumerate(u_values):
                scalar = water_cycle._prevailing_wind_vector(v, "wind-seed", nx=u)
                self.assertEqual(scalar, (float(wind_x[y, x]), float(wind_y[y, x])))

    def test_inherited_rows_grid_matches_scalar_parent_sampling(self):
        rows = _random_rows(9, 13, 3, low=240.0, high=310.0)
        rows[4][6] = None
        bounds = {"min_u": 0.2, "max_u": 0.6, "min_v": 0.1, "max_v": 0.5}
        u_values = [0.15 + index * 0.03 for index in range(17)]
        v_values = [0.05 + index * 0.03 for index in range(15)]
        grid = water_cycle._inherited_rows_grid(rows, u_values, v_values, bounds, 13)
        for y, v in enumerate(v_values):
            for x, u in enumerate(u_values):
                scalar = water_cycle._sample_inherited_rows(rows, u, v, bounds, width_hint=13)
                if scalar is None:
                    self.assertTrue(math.isnan(grid[y, x]))
                else:
                    self.assertAlmostEqual(scalar, float(grid[y, x]), places=9)


def _lithosphere_model(height=9, width=17, seed=3):
    rng = random.Random(seed)
    return {
        "lithosphere_grid": {
            "crust_type_rows": [["oceanic"] * width for _ in range(height)],
            "continental_fraction_rows": [[rng.uniform(0.0, 1.0) for _x in range(width)] for _y in range(height)],
            "ocean_floor_age_rows_myr": [[rng.uniform(0.0, 180.0) for _x in range(width)] for _y in range(height)],
        }
    }


class HeightmapDerivativeParityTests(unittest.TestCase):
    def setUp(self):
        self._shelf_switch = heightmap.VECTORISED_SHELF_MODEL

    def tearDown(self):
        heightmap.VECTORISED_SHELF_MODEL = self._shelf_switch

    def test_lithosphere_grid_matches_scalar_sampler(self):
        model = _lithosphere_model()
        rng = random.Random(8)
        points = [(rng.uniform(-0.3, 1.3), rng.uniform(-0.1, 1.1)) for _ in range(300)]
        continental, age, oceanic = heightmap._sample_lithosphere_grid(
            model, [p[0] for p in points], [p[1] for p in points]
        )
        for index, (u, v) in enumerate(points):
            scalar = heightmap._sample_lithosphere(model, u, v)
            self.assertEqual(scalar["continental_fraction"], float(continental[index]))
            self.assertEqual(scalar["age_myr"], float(age[index]))
            self.assertEqual(scalar["oceanic_fraction"], float(oceanic[index]))

    def test_grid_distance_matches_breadth_first_search(self):
        rng = np.random.default_rng(4)
        mask = rng.random((13, 21)) < 0.06
        for wrap_x in (True, False):
            distance = heightmap._grid_l1_distance(mask, wrap_x=wrap_x, cap=999)
            for y in range(13):
                for x in range(21):
                    best = 999
                    for ty, tx in zip(*np.nonzero(mask)):
                        dx = abs(int(tx) - x)
                        if wrap_x:
                            dx = min(dx, 21 - dx)
                        best = min(best, dx + abs(int(ty) - y))
                    self.assertEqual(best, int(distance[y, x]))

    def test_shelf_model_array_matches_per_cell_path(self):
        rows = _random_rows(12, 19, 21, low=-900.0, high=400.0)
        model = _lithosphere_model()
        cases = [
            {"wrap_x": True, "source_uv_bounds": None},
            {"wrap_x": False, "source_uv_bounds": {"min_u": 0.3, "max_u": 0.42, "min_v": 0.55, "max_v": 0.66}},
        ]
        for kwargs in cases:
            heightmap.VECTORISED_SHELF_MODEL = True
            fast = heightmap._shelf_and_sediment_model(rows, 0.0, model, **kwargs)
            heightmap.VECTORISED_SHELF_MODEL = False
            slow = heightmap._shelf_and_sediment_model(rows, 0.0, model, **kwargs)
            self.assertEqual(slow, fast)

    def test_regional_shelf_sediment_reads_the_tiles_own_ocean_floor(self):
        # Old ocean floor only inside the tile's footprint: a tile that maps
        # its bounds sees thick pelagic sediment, local-as-global UV did not.
        height, width = 9, 17
        model = {
            "lithosphere_grid": {
                "crust_type_rows": [["oceanic"] * width for _ in range(height)],
                "continental_fraction_rows": [[0.0] * width for _ in range(height)],
                "ocean_floor_age_rows_myr": [
                    [200.0 if 6 <= x <= 10 and 3 <= y <= 5 else 0.0 for x in range(width)]
                    for y in range(height)
                ],
            }
        }
        rows = [[-4000.0] * 12 for _ in range(10)]
        rows[0][0] = 50.0
        bounds = {"min_u": 0.42, "max_u": 0.58, "min_v": 0.42, "max_v": 0.58}
        shelf = heightmap._shelf_and_sediment_model(rows, 0.0, model, wrap_x=False, source_uv_bounds=bounds)
        self.assertGreater(shelf["sediment_thickness_rows_m"][9][11], 1000.0)

    def test_sea_level_solve_matches_python_bisection(self):
        rows = _random_rows(17, 33, 5, low=-6000.0, high=4000.0)
        fast = heightmap.sea_level_for_equivalent_water_depth(rows, 1500.0)
        numpy_module = heightmap.np
        heightmap.np = None
        try:
            slow = heightmap.sea_level_for_equivalent_water_depth(rows, 1500.0)
        finally:
            heightmap.np = numpy_module
        self.assertAlmostEqual(fast, slow, places=6)

    def test_cached_forcing_grid_is_reused_and_read_only(self):
        model = heightmap._ensure_heightmap_tectonic_model({
            "boundary_segments": [],
            "orogen_system_model": {"systems": []},
        })
        u = np.linspace(0.1, 0.2, 5)
        v = np.linspace(0.3, 0.4, 4)
        first = heightmap.cached_orogen_forcing_grid(u, v, model)
        again = heightmap.cached_orogen_forcing_grid(u.copy(), v.copy(), model)
        self.assertIs(first, again)
        with self.assertRaises(ValueError):
            first["rock_uplift_m"][0, 0] = 1.0


def _reference_wetness(runoff_rows, precipitation_rows, evaporation_rows, recharge_rows, height, width):
    """The per-cell climatic wetness loop ``derive_surface_hydrology_grids`` used to run."""

    def sample(rows, x, y, default=0.0):
        try:
            return max(0.0, float(rows[y][x] or 0.0))
        except (IndexError, TypeError, ValueError):
            return float(default)

    wetness = []
    for y in range(height):
        wetness_row = []
        for x in range(width):
            supply = (
                sample(runoff_rows, x, y)
                + sample(recharge_rows, x, y) * 0.7
                + sample(precipitation_rows, x, y) * 0.08
            )
            climatic = supply / max(1.0, supply + sample(evaporation_rows, x, y, 350.0))
            wetness_row.append(round(max(0.0, min(1.0, 0.04 + climatic * 0.68)), 4))
        wetness.append(wetness_row)
    return wetness


def _reference_cones(emit, decay, cap, dx, dy):
    """Per cell, the largest capped cone over every source, by straight-line distance."""
    height, width = emit.shape
    sources = [(y, x) for y in range(height) for x in range(width) if emit[y, x] > 0.0]
    result = np.zeros((height, width))
    for y in range(height):
        for x in range(width):
            result[y, x] = max(
                (
                    min(cap[sy, sx], emit[sy, sx] - decay[sy, sx] * math.hypot((sx - x) * dx, (sy - y) * dy))
                    for sy, sx in sources
                ),
                default=0.0,
            )
    return np.clip(result, 0.0, 1.0)


class SurfaceHydrologyParityTests(unittest.TestCase):
    def test_climatic_wetness_matches_per_cell_reference(self):
        # Away from water the raster is the climate's water balance alone,
        # whatever the input rows are missing.
        height, width = 18, 27
        elevation = _random_rows(height, width, 31, low=50.0, high=900.0)
        ocean = [[False] * width for _y in range(height)]
        rng = random.Random(5)
        runoff = [[rng.uniform(-20.0, 900.0) for _x in range(width)] for _y in range(height)]
        runoff[4][7] = None
        precipitation = [[rng.uniform(0.0, 2500.0) for _x in range(width)] for _y in range(height)]
        evaporation = [[rng.uniform(100.0, 1800.0) for _x in range(width)] for _y in range(height - 2)]
        runoff_grid, _surface_grid = drainage.derive_surface_hydrology_grids(
            elevation, ocean, {},
            sea_level_m=0.0, region_width_m=270_000.0, region_height_m=180_000.0,
            runoff_rows=runoff, precipitation_rows=precipitation,
            potential_evaporation_rows=evaporation, groundwater_recharge_rows=None,
        )
        expected = _reference_wetness(runoff, precipitation, evaporation, None, height, width)
        self.assertEqual(expected, runoff_grid["wetness_index_rows"])

    def test_wetting_cones_match_the_per_cell_maximum_over_sources(self):
        # A river with a wide margin, a rill crossing it and a lake, on 2 m cells.
        height, width = 40, 56
        emit, decay, cap = (np.zeros((height, width)) for _field in range(3))
        for x in range(width):
            y = int(14 + 6 * math.sin(x / 7.0))
            emit[y, x], decay[y, x], cap[y, x] = 1.2, 1.0 / 32.0, 1.0
        for y in range(height):
            if emit[y, 40] == 0.0:
                emit[y, 40], decay[y, 40], cap[y, 40] = 0.03, 0.03 / 0.6, 0.012
        emit[30:36, 8:16], decay[30:36, 8:16], cap[30:36, 8:16] = 1.0, 1.0 / 30.0, 1.0
        fast = drainage._capped_cones(emit, decay, cap, 2.0, 2.0)
        slow = _reference_cones(emit, decay, cap, 2.0, 2.0)
        # The chamfer overestimates distance by a percent or two: at most
        # half a metre at the far edge of the river's 38 m margin.
        self.assertLess(float(np.abs(fast - slow).max()), 0.02)
        self.assertAlmostEqual(float(slow.mean()), float(fast.mean()), delta=0.005)

    def test_round_rows_matches_builtin_round(self):
        rng = np.random.default_rng(3)
        values = np.round(rng.uniform(-100.0, 100.0, (40, 50)), 2) + 0.05
        values[0, :4] = [-0.0, np.nan, np.inf, 1.0e12 + 0.25]
        for digits in (0, 1, 3, 4):
            fast = round_rows(values, digits)
            slow = [[round(value, digits) for value in row] for row in values.tolist()]
            for fast_row, slow_row in zip(fast, slow):
                for a, b in zip(fast_row, slow_row):
                    if math.isnan(b):
                        self.assertTrue(math.isnan(a))
                    else:
                        self.assertEqual(b, a)
                        self.assertEqual(math.copysign(1.0, b), math.copysign(1.0, a))


def _climate_heightmap(height, width, seed, **extra):
    rng = random.Random(seed)
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            continent = math.sin(x / width * math.tau * 2.0) * 1400.0 + math.cos(y / height * 5.0) * 600.0
            row.append(round(continent + rng.uniform(-250.0, 250.0), 1))
        rows.append(row)
    model = {
        "map_seed": "climate-parity",
        "sea_level_m": 0.0,
        "radius_m": 6_371_000.0,
        "circumference_m": 40_030_000.0,
        "wrap_x": True,
        "sample_grid": {"rows": rows},
        "surface_masks": {"ice_rows": [[y < 2 for _x in range(width)] for y in range(height)]},
    }
    model.update(extra)
    return model


class ClimatePassParityTests(unittest.TestCase):
    """Array climate passes against the per-cell passes, planet and region."""

    terrain = {
        "map_seed": "climate-parity",
        "hydrology": {
            "target_ocean_fraction": 0.45,
            "liquid_water_possible": True,
            "drainage_enabled": True,
            "surface_fluid": "water",
        },
    }
    atmosphere = {"estimated_surface_temperature_k": 287.0, "surface_pressure_bar": 1.0}
    seed = {"axial_tilt_deg": 23.4, "orbital_eccentricity": 0.02}

    def setUp(self):
        self._switch = water_cycle.VECTORISED_CLIMATE_PASSES

    def tearDown(self):
        water_cycle.VECTORISED_CLIMATE_PASSES = self._switch

    def _both(self, heightmap_model, **kwargs):
        results = []
        for flag in (True, False):
            water_cycle.VECTORISED_CLIMATE_PASSES = flag
            results.append(water_cycle.derive_water_cycle_model(
                dict(self.terrain), heightmap_model, self.atmosphere, dict(self.seed), **kwargs,
            ))
        return results

    def _assert_same_climate(self, fast, slow):
        for key, value in slow["climate_grid"].items():
            if isinstance(value, list) and value and isinstance(value[0], list):
                self.assertEqual(value, fast["climate_grid"][key], msg=key)
        self.assertEqual(slow["koppen_classes"], fast["koppen_classes"])

    def test_planet_and_regional_solves_match(self):
        planet_fast, planet_slow = self._both(_climate_heightmap(17, 33, 1))
        self._assert_same_climate(planet_fast, planet_slow)
        regional = _climate_heightmap(
            21, 25, 2,
            wrap_x=False,
            coverage="regional_patch",
            map_detail_level=1,
            region_width_m=900_000.0,
            region_height_m=760_000.0,
            source_uv_bounds={"min_u": 0.30, "max_u": 0.36, "min_v": 0.40, "max_v": 0.46},
        )
        region_fast, region_slow = self._both(regional, parent_climate_model=planet_slow)
        self._assert_same_climate(region_fast, region_slow)


class IceFeedbackTests(unittest.TestCase):
    def test_freezing_climate_on_a_coarser_grid_reaches_the_whole_mask(self):
        # Mask 9 x 17, climate grid 5 x 9 (same footprint): the south-pole
        # climate row freezes across the whole width.
        ice_rows = [[False] * 17 for _ in range(9)]
        climate = [[290.0] * 9 for _ in range(4)] + [[250.0] * 9]
        updated, changed = ice_mask_with_freezing_climate(ice_rows, climate)
        self.assertTrue(changed)
        self.assertTrue(all(updated[-1]))
        self.assertFalse(any(updated[0]))
        # Ice in the far east proves the mask was not filled at climate-grid indices.
        self.assertTrue(updated[-1][16])


if __name__ == "__main__":
    unittest.main()
