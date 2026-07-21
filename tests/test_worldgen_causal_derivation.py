import math
import unittest

from simulations.world_gen.heightmap import sea_level_for_equivalent_water_depth
from simulations.world_gen.tectonics import _plate_distance, derive_tectonic_model
from simulations.world_gen.terrain_seed import derive_terrain_seed_model


class WorldgenCausalDerivationTests(unittest.TestCase):
    def test_water_volume_not_requested_coverage_sets_sea_level(self):
        shallow_basins = [
            [-1000.0, -500.0, 0.0, 500.0, -1000.0],
            [-800.0, -300.0, 200.0, 700.0, -800.0],
            [-1000.0, -500.0, 0.0, 500.0, -1000.0],
        ]
        deep_narrow_basin = [
            [-3000.0, 500.0, 1000.0, 1500.0, -3000.0],
            [-2500.0, 700.0, 1200.0, 1700.0, -2500.0],
            [-3000.0, 500.0, 1000.0, 1500.0, -3000.0],
        ]
        shallow_level = sea_level_for_equivalent_water_depth(shallow_basins, 350.0)
        deep_level = sea_level_for_equivalent_water_depth(deep_narrow_basin, 350.0)
        self.assertIsNotNone(shallow_level)
        self.assertIsNotNone(deep_level)
        self.assertNotAlmostEqual(shallow_level, deep_level)
        self.assertIsNone(sea_level_for_equivalent_water_depth(shallow_basins, 0.0))

    def test_first_screen_water_becomes_inventory_depth(self):
        regime = {
            "interior": {"internal_heat_w_m2": 0.087, "tectonic_regime": "mobile_lid"},
            "surface_processes": {
                "hydrologic_cycle": "active",
                "liquid_water_possible": True,
                "crater_retention": "low",
                "primary_topography": "continental_oceanic",
                "erosion_processes": ["fluvial"],
            },
        }
        terrain = derive_terrain_seed_model(
            {"map_seed": "causal-water", "water_fraction": 0.71},
            {"radius_earth": 1.0, "radius_m": 6_371_000.0, "surface_gravity_g": 1.0},
            {"surface_pressure_bar": 1.0, "estimated_surface_temperature_k": 288.0},
            regime,
        )
        hydrology = terrain["hydrology"]
        self.assertEqual("derived_from_inventory_and_hypsometry", hydrology["coverage_mode"])
        self.assertEqual(0.0, hydrology["target_ocean_fraction"])
        self.assertGreater(hydrology["equivalent_global_water_depth_m"], 1800.0)
        self.assertLess(hydrology["equivalent_global_water_depth_m"], 3800.0)

    def test_geologic_history_is_seeded_prehistory_not_registry_time(self):
        terrain = {
            "map_seed": "causal-history",
            "map_canvas": {"circumference_m": 40_075_000.0},
            "tectonics": {"plate_count": 8},
            "hydrology": {"water_inventory_index": 0.4},
        }
        model = derive_tectonic_model(terrain, planet_id="planet_history_test")
        history = model["geologic_history"]
        self.assertFalse(history["registry_time_coupled"])
        self.assertEqual("pre_generation_geologic_history", history["time_domain"])
        self.assertGreaterEqual(len(history["snapshots"]), 4)
        self.assertEqual(0.0, history["snapshots"][-1]["age_before_present_myr"])
        self.assertFalse(model["lithosphere_prior"]["uses_final_ocean_coverage"])

    def test_plate_boundaries_use_curved_seeded_geometry(self):
        terrain = {
            "map_seed": "curved-plate-boundaries",
            "map_canvas": {"circumference_m": 40_075_000.0},
            "tectonics": {"plate_count": 8},
            "hydrology": {"water_inventory_index": 0.5},
        }
        model = derive_tectonic_model(terrain, planet_id="curved_plate_test")
        plate = model["plates"][0]
        shape = plate["boundary_shape"]
        self.assertEqual("anisotropic_lobed_plate_metric_v1", shape["model"])
        radius = 0.04
        distances = [
            _plate_distance(
                (plate["center_x"] + math.cos(angle) * radius) % 1.0,
                max(0.0, min(1.0, plate["center_y"] + math.sin(angle) * radius)),
                plate,
            )
            for angle in (index * math.tau / 16.0 for index in range(16))
        ]
        self.assertGreater(max(distances) - min(distances), 0.01)
        self.assertGreaterEqual(model["sample_grid"]["width"], 97)
        self.assertTrue(model["boundary_segments"])
        for segment in model["boundary_segments"][:20]:
            self.assertIn("activity_scale", segment)
            self.assertIn("influence_width", segment)
            self.assertIn("normal_velocity_cm_year", segment)
            self.assertIn("shear_velocity_cm_year", segment)
            self.assertIn("obliquity_deg", segment)
        self.assertTrue(model["plate_topology"]["closed_surface"])
        self.assertEqual(
            "mixed_crust_and_ocean_floor_age_v1",
            model["lithosphere_grid"]["model"],
        )
        self.assertEqual(
            model["sample_grid"]["height"],
            len(model["lithosphere_grid"]["ocean_floor_age_rows_myr"]),
        )
        self.assertTrue(model["hotspot_model"]["hotspots"])
        self.assertTrue(
            any(
                event["kind"] in {
                    "supercontinent_assembly",
                    "supercontinent_rifting_and_breakup",
                }
                for event in model["geologic_history"]["events"]
            )
        )


if __name__ == "__main__":
    unittest.main()
