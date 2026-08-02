import unittest

import numpy as np

from simulations.world_gen.surface_geomorphology import (
    SURFACE_GEOMORPHOLOGY_MODEL_VERSION,
    derive_surface_geomorphology_fields,
    derive_surface_geomorphology_model,
    derive_surface_material_partition_fields,
    dominant_structural_strike_degrees,
)


def _heightmap(rows):
    return {
        "model_version": "test-height-v1",
        "map_seed": "folded-range",
        "sample_spacing_x_m": 1000.0,
        "sample_spacing_y_m": 1000.0,
        "sample_grid": {"rows": rows},
    }


class SurfaceGeomorphologyTests(unittest.TestCase):
    def test_model_persists_landform_and_structural_contract(self):
        heightmap = _heightmap([
            [0, 100, 350, 100, 0],
            [0, 250, 900, 250, 0],
            [0, 100, 350, 100, 0],
        ])
        model = derive_surface_geomorphology_model(
            {"id": "range"},
            heightmap=heightmap,
            tectonic_model={"regime": "mobile_lid_plate_tectonics"},
        )
        self.assertEqual(SURFACE_GEOMORPHOLOGY_MODEL_VERSION, model["model_version"])
        self.assertIn("exposed_ridge", model["landform_classes"])
        self.assertTrue(model["structural_fabric"]["bedrock_banding_enabled"])
        self.assertEqual(
            "deterministically_reconstructed_from_height_drainage_and_surface_process_grids",
            model["field_contract"],
        )

    def test_relief_produces_more_ridge_scarp_and_bedrock_than_plain(self):
        mountain = _heightmap([
            [0, 300, 900, 300, 0],
            [0, 600, 1800, 600, 0],
            [0, 300, 900, 300, 0],
        ])
        plain = _heightmap([[200.0] * 5 for _ in range(3)])
        rugged = derive_surface_geomorphology_fields(mountain, target_size=(96, 48))
        flat = derive_surface_geomorphology_fields(plain, target_size=(96, 48))
        self.assertGreater(float(np.mean(rugged["ridge"])), float(np.mean(flat["ridge"])) + 0.05)
        self.assertGreater(float(np.mean(rugged["scarp"])), float(np.mean(flat["scarp"])) + 0.005)
        self.assertGreater(float(np.mean(rugged["bedrock_exposure"])), float(np.mean(flat["bedrock_exposure"])) + 0.02)

    def test_fields_are_deterministic_and_drainage_conditioned(self):
        heightmap = _heightmap([
            [500, 400, 300, 400, 500],
            [450, 300, 100, 300, 450],
            [500, 400, 250, 400, 500],
        ])
        water = {"drainage_network_model": {"flow_accumulation_rows": [
            [1, 1, 9, 1, 1], [1, 2, 40, 2, 1], [1, 1, 80, 1, 1],
        ]}}
        first = derive_surface_geomorphology_fields(heightmap, water_cycle=water, target_size=(80, 40))
        second = derive_surface_geomorphology_fields(heightmap, water_cycle=water, target_size=(80, 40))
        np.testing.assert_allclose(first["incised_valley"], second["incised_valley"])
        center = float(np.mean(first["drainage_accumulation"][:, 35:45]))
        edge = float(np.mean(first["drainage_accumulation"][:, :10]))
        self.assertGreater(center, edge)

    def test_nested_regions_inherit_nearest_boundary_strike(self):
        tectonics = {"boundary_segments": [{
            "kind": "collision",
            "x1": 0.2,
            "y1": 0.4,
            "x2": 0.8,
            "y2": 0.6,
        }]}
        broad = {"source_uv_bounds": {"min_u": 0.25, "max_u": 0.75, "min_v": 0.35, "max_v": 0.65}}
        nested = {"source_uv_bounds": {"min_u": 0.45, "max_u": 0.55, "min_v": 0.45, "max_v": 0.55}}

        self.assertEqual(
            dominant_structural_strike_degrees(tectonics, broad),
            dominant_structural_strike_degrees(tectonics, nested),
        )

    def test_material_partition_exposes_cliffs_and_fills_valleys(self):
        heightmap = _heightmap([
            [1200, 900, 250, 900, 1200],
            [1500, 1050, 100, 1050, 1500],
            [1200, 900, 0, 900, 1200],
        ])
        deposition = [
            [0.02, 0.08, 0.75, 0.08, 0.02],
            [0.02, 0.08, 0.90, 0.08, 0.02],
            [0.02, 0.08, 0.82, 0.08, 0.02],
        ]
        fields = derive_surface_material_partition_fields(
            heightmap,
            surface_evolution={"process_grid": {
                "sediment_deposition_rows": deposition,
                "erosion_potential_rows": [[0.7] * 5 for _ in range(3)],
            }},
            target_size=(100, 60),
        )
        valley = slice(44, 56)
        sides = np.concatenate((
            fields["exposed_bedrock_fraction"][:, 20:38].ravel(),
            fields["exposed_bedrock_fraction"][:, 62:80].ravel(),
        ))
        self.assertGreater(float(np.mean(sides)), float(np.mean(fields["exposed_bedrock_fraction"][:, valley])))
        self.assertGreater(
            float(np.mean(fields["alluvial_cover_fraction"][:, valley])),
            float(np.mean(fields["alluvial_cover_fraction"][:, 10:25])) + 0.08,
        )
        total = (
            fields["exposed_bedrock_fraction"]
            + fields["colluvial_cover_fraction"]
            + fields["alluvial_cover_fraction"]
            + fields["weathered_mantle_fraction"]
            + fields["residual_regolith_fraction"]
        )
        self.assertLessEqual(float(np.max(total)), 1.00001)
        self.assertGreaterEqual(float(np.min(total)), 0.99999)


if __name__ == "__main__":
    unittest.main()
