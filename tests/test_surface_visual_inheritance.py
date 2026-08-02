import unittest

from simulations.world_gen.heightmap import (
    _crater_height_adjustment_m,
    condition_crater_model_to_surface,
)
from simulations.world_gen.regional_refinement import (
    _enforce_parent_height_contract,
    _parent_structure_context,
    _refinement_detail_band,
    _sample_bicubic,
    _stable_region_id,
)


class RegionalIdentityTests(unittest.TestCase):
    def test_nested_region_id_does_not_embed_ancestral_path(self):
        bounds = {"min_x": 1.0, "max_x": 2.0, "min_y": 3.0, "max_y": 4.0}
        parent = "refined_" + ("very_long_parent_" * 20)
        region_id = _stable_region_id(parent, 6, bounds)
        self.assertTrue(region_id.startswith("refined_lod6_"))
        self.assertLess(len(region_id), 32)
        self.assertNotIn("very_long_parent", region_id)


class CraterSurfaceResolutionTests(unittest.TestCase):
    def test_deep_water_suppresses_seafloor_crater_but_not_land_impact(self):
        crater_model = {
            "radius_m": 6_371_000.0,
            "resurfacing_fraction": 0.0,
            "craters": [
                {
                    "id": "land",
                    "x": 0.25,
                    "y": 0.5,
                    "diameter_km": 16.0,
                    "depth_m": 1200.0,
                    "rim_height_m": 300.0,
                    "morphology": "simple",
                },
                {
                    "id": "marine",
                    "x": 0.75,
                    "y": 0.5,
                    "diameter_km": 16.0,
                    "depth_m": 1200.0,
                    "rim_height_m": 300.0,
                    "morphology": "simple",
                },
            ],
        }
        # Two identical rows: left side is land, right side is a deep ocean.
        base_rows = [[500.0, 500.0, 0.0, -5000.0, 500.0]] * 3
        terrain = {
            "erosion": {
                "strength": 0.2,
                "atmospheric_pressure_bar": 1.0,
            },
            "hydrology": {"target_ice_fraction": 0.0},
            "cratering": {"resurfacing_fraction": 0.0},
        }

        conditioned, audit = condition_crater_model_to_surface(
            crater_model, terrain, base_rows, 0.0,
        )
        by_id = {crater["id"]: crater for crater in conditioned["craters"]}

        self.assertEqual("subaerial", by_id["land"]["target_environment"])
        self.assertEqual("marine", by_id["marine"]["target_environment"])
        self.assertLess(
            by_id["marine"]["morphology_preservation"],
            by_id["land"]["morphology_preservation"] * 0.2,
        )
        self.assertEqual(1, audit["strongly_suppressed_marine_crater_count"])
        self.assertLess(
            abs(_crater_height_adjustment_m(0.75, 0.5, conditioned)),
            abs(_crater_height_adjustment_m(0.25, 0.5, conditioned)) * 0.2,
        )


class ParentHeightContractTests(unittest.TestCase):
    def test_new_mountain_detail_is_anchored_to_inherited_structure(self):
        flat = [[0.0 for _x in range(7)] for _y in range(7)]
        ramp = [[float(x * 100) for x in range(7)] for _y in range(7)]
        ridge = [[float(900 - abs(x - 3) * 300) for x in range(7)] for _y in range(7)]

        self.assertEqual((0.0, 0.0), _parent_structure_context(
            flat, 0.5, 0.5, 2000.0, wrap_x=False,
        ))
        ramp_ruggedness, ramp_anchor = _parent_structure_context(
            ramp, 0.5, 0.5, 2000.0, wrap_x=False,
        )
        ridge_ruggedness, ridge_anchor = _parent_structure_context(
            ridge, 0.5, 0.5, 2000.0, wrap_x=False,
        )
        self.assertGreater(ramp_ruggedness, 0.0)
        self.assertLess(ramp_anchor, 0.05)
        self.assertGreater(ridge_ruggedness, 0.0)
        self.assertGreater(ridge_anchor, 0.6)

    def test_refinement_only_adds_the_missing_physical_wavelength_band(self):
        parent = [[0.0 for _x in range(101)] for _y in range(51)]
        band = _refinement_detail_band(
            100_000.0, 50_000.0, parent,
            10_000.0, 5_000.0, 501, 251,
        )
        self.assertIsNotNone(band)
        self.assertGreater(
            band["longest_wavelength_m"],
            band["shortest_wavelength_m"],
        )
        self.assertLessEqual(
            band["longest_wavelength_m"],
            band["parent_sample_spacing_m"] * 1.81,
        )
        self.assertGreaterEqual(
            band["shortest_wavelength_m"],
            band["child_sample_spacing_m"] * 4.0,
        )

    def test_refinement_stops_inventing_relief_below_data_floor(self):
        parent = [[0.0 for _x in range(101)] for _y in range(101)]
        band = _refinement_detail_band(
            10.0, 10.0, parent,
            10.0, 10.0, 101, 101,
        )
        self.assertIsNone(band)

    def test_bicubic_parent_sampling_preserves_a_linear_surface(self):
        rows = [[float(x * 10 + y * 7) for x in range(6)] for y in range(5)]
        for u, v in ((0.27, 0.32), (0.37, 0.51), (0.74, 0.68)):
            expected = u * 5.0 * 10.0 + v * 4.0 * 7.0
            self.assertAlmostEqual(
                expected,
                _sample_bicubic(rows, u, v, wrap_x=False),
                places=5,
            )

    def test_certain_parent_ocean_cannot_become_child_archipelago(self):
        heightmap = {
            "sea_level_m": 0.0,
            "sample_grid": {
                "width": 3,
                "height": 2,
                "rows": [[500.0, 100.0, 500.0], [500.0, 100.0, 500.0]],
            },
        }
        inherited = [[-50.0, -50.0, -50.0], [-50.0, -50.0, -50.0]]
        # The middle column is an unresolved parent shoreline cell and may
        # resolve either way; the outer columns are certainly ocean.
        topology = [[-1, 0, -1], [-1, 0, -1]]

        resolved, audit = _enforce_parent_height_contract(
            heightmap, inherited, topology, detail_amplitude_m=100.0,
        )
        rows = resolved["sample_grid"]["rows"]

        self.assertTrue(all(row[0] < 0.0 and row[2] < 0.0 for row in rows))
        self.assertTrue(all(row[1] > 0.0 for row in rows))
        self.assertGreater(audit["topology_correction_count"], 0)
        self.assertLessEqual(audit["maximum_child_residual_m"], 215.0)


if __name__ == "__main__":
    unittest.main()
