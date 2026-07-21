import unittest

from simulations.world_gen.tectonics import derive_tectonic_model, mature_tectonics_model
from simulations.world_gen.worldgen_realism import derive_worldgen_realism_metrics


class WorldgenRealismTests(unittest.TestCase):
    def test_tectonic_model_exposes_realism_contracts(self):
        terrain = {
            "map_seed": "realism-contracts",
            "map_canvas": {"circumference_m": 40_075_000.0},
            "tectonics": {"plate_count": 9},
            "hydrology": {"water_inventory_index": 0.6},
        }
        model = mature_tectonics_model(
            derive_tectonic_model(terrain, planet_id="realism_contract_planet"),
            terrain,
            cycles=2,
            million_years_per_cycle=35.0,
        )
        self.assertTrue(model["plate_topology"]["closed_surface"])
        self.assertTrue(model["continental_province_model"]["cratons"])
        self.assertTrue(model["continental_province_model"]["failed_rifts"])
        self.assertTrue(model["hotspot_model"]["hotspots"])
        self.assertTrue(all(plate["motion_model"]["type"] == "spherical_euler_rotation" for plate in model["plates"]))
        self.assertTrue(all("normal_velocity_cm_year" in segment for segment in model["boundary_segments"]))

    def test_realism_audit_reports_surface_and_drainage_metrics(self):
        tectonics = {
            "plates": [{"area_fraction": 0.5}, {"area_fraction": 0.5}],
            "boundary_segments": [
                {"kind": "divergent"},
                {"kind": "subduction", "subducting_plate": "a", "overriding_plate": "b"},
                {"kind": "transform"},
            ],
            "plate_topology": {"closed_surface": True, "triple_junctions": [{"x": 0.5, "y": 0.5}]},
            "lithosphere_grid": {"ocean_floor_age_rows_myr": [[0.0, 80.0, 180.0]]},
        }
        heightmap = {
            "sea_level_m": 0.0,
            "sample_grid": {"rows": [[-3000.0, 200.0, -2500.0], [-2000.0, 2400.0, -1000.0]]},
            "hypsometry_summary": {
                "deep_basin_fraction_below_minus_2000m": 0.4,
                "mountain_fraction_above_2000m": 0.1,
                "continental_shelf_fraction": 0.05,
            },
        }
        water = {
            "hydrology_enabled": True,
            "drainage_network_model": {
                "maximum_stream_order": 3,
                "lake_outlet_fraction": 0.7,
                "delta_count": 2,
            },
        }
        audit = derive_worldgen_realism_metrics(
            tectonics, heightmap, water,
            {"feedback_iterations": [{"iteration": 1}, {"iteration": 2}]},
        )
        self.assertEqual("audited", audit["status"])
        self.assertEqual(2, audit["metrics"]["climate_landscape_feedback_iterations"])
        self.assertEqual(2, audit["metrics"]["delta_count"])
        self.assertTrue(audit["checks"]["iterated_climate_landscape_coupling"])

    def test_audit_does_not_apply_plate_and_river_checks_to_stagnant_ocean_world(self):
        heightmap = {
            "sea_level_m": 0.0,
            "sample_grid": {"rows": [[-3000.0, -2500.0], [-2000.0, -1000.0]]},
            "hypsometry_summary": {"land_fraction": 0.0, "ocean_fraction": 1.0},
        }
        audit = derive_worldgen_realism_metrics(
            {}, heightmap,
            {"hydrology_enabled": True, "drainage_network_model": {}},
            {"feedback_iterations": [{"iteration": 1}, {"iteration": 2}]},
        )
        self.assertFalse(audit["applicability"]["closed_plate_topology"])
        self.assertFalse(audit["applicability"]["branching_drainage_present"])
        self.assertEqual([], audit["warnings"])


if __name__ == "__main__":
    unittest.main()
