import math
import unittest

from simulations.world_gen.heightmap import (
    _continuous_crustal_base_height_m,
    derive_heightmap_model,
    sea_level_for_equivalent_water_depth,
)
from simulations.world_gen.water_cycle import _rows_from_heightmap
from simulations.world_gen.tectonics import _plate_distance, advance_tectonics_model, derive_tectonic_model
from simulations.world_gen.terrain_seed import derive_terrain_seed_model


class WorldgenCausalDerivationTests(unittest.TestCase):
    def test_planetary_parent_uses_continuous_crustal_freeboard(self):
        samples = [
            _continuous_crustal_base_height_m(index / 100.0)
            for index in range(101)
        ]
        self.assertTrue(all(a <= b for a, b in zip(samples, samples[1:])))
        self.assertLess(max(b - a for a, b in zip(samples, samples[1:])), 90.0)
        self.assertLess(samples[0], -3500.0)
        self.assertGreater(samples[-1], 800.0)

    def test_dense_parent_is_filtered_to_full_climate_resolution(self):
        rows = [
            [float(x + y) for x in range(385)]
            for y in range(193)
        ]
        for row in rows:
            row[-1] = row[0]
        sampled = _rows_from_heightmap({
            "sample_grid": {"rows": rows},
            "map_detail_level": 0,
        })
        self.assertEqual((129, 257), (len(sampled), len(sampled[0])))
        self.assertTrue(all(row[0] == row[-1] for row in sampled))

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

    def test_mobile_lid_resurfacing_keeps_crater_retention_low_under_thin_air(self):
        regime = {
            "interior": {
                "internal_heat_w_m2": 0.07,
                "tectonic_regime": "mobile_lid",
            },
            "surface_processes": {
                "hydrologic_cycle": "limited",
                "liquid_water_possible": True,
                "crater_retention": "low",
                "resurfacing_fraction": 0.24,
                "primary_topography": "plate_boundaries_mountain_belts_and_trenches",
                "erosion_processes": ["episodic_fluvial", "aeolian"],
            },
        }
        terrain = derive_terrain_seed_model(
            {"map_seed": "thin-air-mobile-lid", "water_fraction": 0.08},
            {"radius_earth": 1.0, "radius_m": 6_371_000.0, "surface_gravity_g": 1.0},
            {"surface_pressure_bar": 0.04, "estimated_surface_temperature_k": 270.0},
            regime,
        )

        self.assertEqual("low", terrain["cratering"]["retention"])
        self.assertLess(terrain["cratering"]["density"], 0.1)
        self.assertEqual(0.24, terrain["cratering"]["resurfacing_fraction"])

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
        self.assertEqual(
            "continuous_plate_distance_contour_v1",
            model["boundary_trace_grid"]["geometry_model"],
        )
        self.assertGreater(model["boundary_trace_grid"]["width"], model["sample_grid"]["width"])
        self.assertTrue(any(
            abs(float(segment["x2"]) - float(segment["x1"])) > 1e-6
            and abs(float(segment["y2"]) - float(segment["y1"])) > 1e-6
            for segment in model["boundary_segments"]
        ))
        for segment in model["boundary_segments"][:20]:
            self.assertEqual("continuous_plate_distance_contour_v1", segment["geometry_model"])
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
        orogen_model = model["orogen_system_model"]
        self.assertEqual("orogen-systems-v2-spaced-margin-profiles", orogen_model["model_version"])
        self.assertGreater(orogen_model["system_count"], 0)
        system_ids = {system["id"] for system in orogen_model["systems"]}
        self.assertTrue(system_ids)
        for system in orogen_model["systems"]:
            self.assertIn("rock_uplift_peak_m", system["forcing_profile"])
            self.assertIn("tectonic_subsidence_peak_m", system["forcing_profile"])
            self.assertTrue(system["forcing_profile"]["zones"])
            self.assertTrue(system["source_segment_ids"])
        self.assertTrue(
            any(segment.get("orogen_system_id") in system_ids for segment in model["boundary_segments"])
        )
        heightmap = derive_heightmap_model(
            terrain,
            seed={"map_seed": "causal-orogen-height"},
            physics={"radius_m": 6_371_000.0},
            planet_id="test_causal_orogen",
            tectonic_model=model,
            mechanical_lithology_model={
                "status": "mechanical_lithology_prior_derived",
                "model_version": "mechanical-lithology-v1-ontology-prior",
                "dominant_mechanical_class": "massive_crystalline_rock",
                "aggregate_profile": {
                    "bulk_density_kg_m3": 2720,
                    "erodibility_index": 0.23,
                    "slope_resistance_index": 0.86,
                    "elastic_strength_index": 0.82,
                },
            },
        )
        deformation = heightmap["deformation_state_model"]
        self.assertEqual("deformation_state_derived", deformation["status"])
        self.assertEqual(
            "planetary-deformation-v1-reduced-flexure",
            deformation["model_version"],
        )
        for field in (
            "crust_thickness_km", "cumulative_strain_index", "rock_uplift_m",
            "tectonic_subsidence_m", "volcanic_construction_m",
            "effective_elastic_thickness_km", "isostatic_response_m",
            "flexural_response_m", "surface_response_m",
        ):
            self.assertIn(field, deformation["fields"])
            self.assertIn(field, deformation["summaries"])
        self.assertGreater(deformation["summaries"]["rock_uplift_m"]["max"], 0.0)
        self.assertLess(deformation["summaries"]["flexural_response_m"]["min"], 0.0)
        self.assertEqual("massive_crystalline_rock", deformation["dominant_mechanical_class"])
        self.assertEqual(
            "mechanical-lithology-v1-ontology-prior",
            deformation["source_mechanical_model_version"],
        )
        advanced = advance_tectonics_model(model, terrain, million_years=45.0)
        self.assertEqual(45.0, advanced["orogen_system_model"]["age_myr"])
        self.assertGreaterEqual(
            max(system["maturity"] for system in advanced["orogen_system_model"]["systems"]),
            max(system["maturity"] for system in orogen_model["systems"]),
        )
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
