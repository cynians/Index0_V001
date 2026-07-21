import tempfile
import unittest
from pathlib import Path

from simulations.world_gen.material_affinities import (
    MATERIAL_AFFINITY_PROFILES,
    material_affinity_score,
)
from simulations.world_gen.material_heatmaps import (
    _select_material_layers,
    generate_material_heatmap_model,
)
from simulations.world_gen.natural_materials import (
    NATURAL_MATERIAL_CATALOG,
    derive_natural_material_model,
    natural_material_entries,
)
from simulations.world_gen.regional_materials import derive_regional_material_model


def _context(**overrides):
    context = {
        "temperature_k": 292.0,
        "precipitation_mm": 1200.0,
        "land": 1.0,
        "ocean": 0.0,
        "elevation": 0.5,
        "highland": 0.5,
        "lowland": 0.5,
        "slope": 0.35,
        "low_slope": 0.65,
        "polar": 0.1,
        "shoreline": 0.1,
        "ice": 0.0,
        "humidity": 0.67,
        "aridity": 0.0,
        "drainage": 0.45,
        "weathering": 0.55,
        "deposition": 0.35,
        "aeolian": 0.1,
        "erosion": 0.3,
        "glacial": 0.0,
        "age": 0.8,
        "volcanic": 0.2,
        "resurfacing": 0.1,
        "impact": 0.0,
        "carbonate": 0.5,
        "regional": 0.6,
        "noise": 0.5,
        "active_hydrology": True,
        "active_volcanism": True,
    }
    context.update(overrides)
    return context


class MaterialAffinityTests(unittest.TestCase):
    def test_every_natural_material_has_an_explicit_profile(self):
        catalog_ids = {material["id"] for material in NATURAL_MATERIAL_CATALOG}

        self.assertEqual(78, len(catalog_ids))
        self.assertEqual(catalog_ids, set(MATERIAL_AFFINITY_PROFILES))
        for material_id, profile in MATERIAL_AFFINITY_PROFILES.items():
            self.assertTrue(profile.get("profile_id"), material_id)
            self.assertTrue(profile.get("weights"), material_id)
            self.assertGreater(profile.get("abundance", 0.0), 0.0, material_id)
            self.assertIn("minimum_map_detail_level", profile, material_id)
            self.assertTrue(profile.get("distribution_scale"), material_id)

    def test_repository_material_entries_expose_their_surface_profiles(self):
        entries = {
            entry["id"]: entry
            for entry in natural_material_entries()
            if entry["id"] in MATERIAL_AFFINITY_PROFILES
        }

        self.assertEqual(set(MATERIAL_AFFINITY_PROFILES), set(entries))
        self.assertEqual("bauxite", entries["mat_bauxite"]["surface_affinity_profile"]["profile_id"])
        self.assertEqual(
            "fluvial_sediment",
            entries["mat_alluvium"]["surface_affinity_profile"]["profile_id"],
        )

    def test_bauxite_requires_warm_wet_old_well_drained_weathering_surface(self):
        favorable = material_affinity_score(
            "mat_bauxite",
            _context(
                temperature_k=302.0,
                precipitation_mm=2400.0,
                drainage=0.62,
                weathering=0.78,
                age=0.9,
                low_slope=0.8,
            ),
        )
        cold = material_affinity_score(
            "mat_bauxite",
            _context(
                temperature_k=270.0,
                precipitation_mm=900.0,
                drainage=0.62,
                weathering=0.78,
            ),
        )
        poorly_weathered = material_affinity_score(
            "mat_bauxite",
            _context(
                temperature_k=302.0,
                precipitation_mm=2400.0,
                drainage=0.62,
                weathering=0.12,
            ),
        )

        self.assertGreater(favorable, 0.4)
        self.assertEqual(0.0, cold)
        self.assertEqual(0.0, poorly_weathered)

    def test_alluvium_prefers_drained_depositional_lowlands(self):
        floodplain = material_affinity_score(
            "mat_alluvium",
            _context(lowland=0.9, highland=0.1, drainage=0.9, deposition=0.85, slope=0.08),
        )
        mountain = material_affinity_score(
            "mat_alluvium",
            _context(lowland=0.1, highland=0.9, drainage=0.1, deposition=0.05, slope=0.9),
        )

        self.assertGreater(floodplain, mountain * 2.0)

    def test_layer_selection_keeps_bedrock_when_regolith_candidates_dominate(self):
        candidates = [
            {
                "material_id": f"mat_regolith_{index}",
                "name": f"Regolith {index}",
                "material_subclass": "regolith",
                "confidence": 0.98 - index * 0.01,
            }
            for index in range(5)
        ]
        candidates.extend([
            {
                "material_id": "mat_basalt",
                "name": "Basalt",
                "material_subclass": "rock",
                "confidence": 0.80,
            },
            {
                "material_id": "mat_granite",
                "name": "Granite",
                "material_subclass": "rock",
                "confidence": 0.79,
            },
        ])

        selected = _select_material_layers({"likely_materials": candidates}, max_layers=5)

        self.assertEqual(2, sum(item["material_subclass"] == "regolith" for item in selected))
        self.assertEqual(2, sum(item["material_subclass"] == "rock" for item in selected))

    def test_ores_and_minor_minerals_are_deferred_from_planetary_heatmap(self):
        model = derive_natural_material_model(
            {
                "major_elements": [
                    {"symbol": "O", "abundance_percent": 42.0},
                    {"symbol": "Si", "abundance_percent": 22.0},
                    {"symbol": "Al", "abundance_percent": 9.0},
                    {"symbol": "Fe", "abundance_percent": 9.0},
                    {"symbol": "Mg", "abundance_percent": 8.0},
                    {"symbol": "S", "abundance_percent": 2.0},
                    {"symbol": "Cu", "abundance_percent": 0.5},
                ],
                "trace_elements": [],
            },
            [
                "silicate_crust",
                "mafic_crust",
                "volcanic_surface",
                "weathered_surface",
                "active_hydrology",
                "oxidizing_surface",
            ],
        )
        candidates = {
            item["material_id"]: item
            for item in model["likely_materials"]
        }

        self.assertEqual(0, candidates["mat_basalt"]["minimum_map_detail_level"])
        self.assertGreaterEqual(
            candidates["mat_chalcopyrite"]["minimum_map_detail_level"],
            2,
        )
        self.assertGreaterEqual(
            MATERIAL_AFFINITY_PROFILES["mat_banded_iron_formation"][
                "minimum_map_detail_level"
            ],
            2,
        )
        self.assertGreaterEqual(
            MATERIAL_AFFINITY_PROFILES["mat_gabbro"]["minimum_map_detail_level"],
            1,
        )
        self.assertGreaterEqual(
            MATERIAL_AFFINITY_PROFILES["mat_obsidian"][
                "minimum_map_detail_level"
            ],
            2,
        )
        self.assertGreaterEqual(
            MATERIAL_AFFINITY_PROFILES["mat_scoria"][
                "minimum_map_detail_level"
            ],
            1,
        )
        selected_ids = {
            item["material_id"]
            for item in _select_material_layers(model, max_layers=5)
        }
        self.assertTrue(selected_ids)
        self.assertTrue(
            any(
                candidates[material_id]["material_subclass"] == "rock"
                for material_id in selected_ids
            )
        )
        self.assertNotIn("mat_chalcopyrite", selected_ids)

    def test_wet_oxidizing_surface_suppresses_exposed_native_sulfur(self):
        dry = material_affinity_score(
            "mat_native_sulfur",
            _context(
                temperature_k=290.0,
                volcanic=1.0,
                resurfacing=0.8,
                wet_oxidizing_surface=False,
            ),
        )
        wet = material_affinity_score(
            "mat_native_sulfur",
            _context(
                temperature_k=290.0,
                volcanic=1.0,
                resurfacing=0.8,
                wet_oxidizing_surface=True,
            ),
        )

        self.assertGreater(dry, 0.0)
        self.assertLess(wet, dry * 0.25)

    def test_region_refinement_resolves_deferred_material_prospects(self):
        natural_model = {
            "planet_tags": [
                "active_hydrology",
                "oxidizing_surface",
                "weathered_surface",
                "mafic_crust",
                "volcanic_surface",
            ],
            "likely_materials": [
                {
                    "material_id": "mat_bauxite",
                    "name": "Bauxite",
                    "material_subclass": "regolith",
                    "confidence": 0.95,
                    "minimum_map_detail_level": 2,
                    "surface_affinity_profile": MATERIAL_AFFINITY_PROFILES["mat_bauxite"],
                },
            ],
        }
        heightmap = {
            "sea_level_m": 0.0,
            "min_elevation_m": -100.0,
            "max_elevation_m": 1000.0,
            "region_width_m": 200_000.0,
            "region_height_m": 120_000.0,
            "sample_grid": {
                "rows": [[400.0] * 5 for _index in range(5)],
            },
        }
        climate_rows = [[302.0] * 5 for _index in range(5)]
        precipitation_rows = [[2400.0] * 5 for _index in range(5)]
        runoff_rows = [[900.0] * 5 for _index in range(5)]
        process_rows = [[0.82] * 5 for _index in range(5)]

        planetary = derive_regional_material_model(
            natural_model,
            heightmap,
            {},
            map_seed="regional-bauxite-test",
            detail_level=0,
        )
        regional = derive_regional_material_model(
            natural_model,
            heightmap,
            {
                "climate_grid": {
                    "temperature_rows_k": climate_rows,
                    "annual_precipitation_rows_mm": precipitation_rows,
                    "annual_runoff_rows_mm": runoff_rows,
                },
            },
            {
                "process_grid": {
                    "chemical_weathering_rows": process_rows,
                    "sediment_deposition_rows": process_rows,
                    "erosion_potential_rows": [[0.2] * 5 for _index in range(5)],
                    "relative_surface_age_rows": [[0.9] * 5 for _index in range(5)],
                },
            },
            map_seed="regional-bauxite-test",
            detail_level=2,
        )

        self.assertEqual([], planetary["occurrences"])
        self.assertEqual(1, regional["occurrence_count"])
        occurrence = regional["occurrences"][0]
        self.assertEqual("mat_bauxite", occurrence["material_id"])
        self.assertEqual("ore_or_mineral_prospect", occurrence["occurrence_role"])
        self.assertEqual(
            "prolonged_residual_lateritic_weathering",
            occurrence["genesis_model"],
        )
        self.assertTrue(occurrence["scale_stable"])
        self.assertLess(occurrence["estimated_radius_m"], 5000.0)
        repeated = derive_regional_material_model(
            natural_model,
            heightmap,
            {
                "climate_grid": {
                    "temperature_rows_k": climate_rows,
                    "annual_precipitation_rows_mm": precipitation_rows,
                    "annual_runoff_rows_mm": runoff_rows,
                },
            },
            {
                "process_grid": {
                    "chemical_weathering_rows": process_rows,
                    "sediment_deposition_rows": process_rows,
                    "erosion_potential_rows": [[0.2] * 5 for _index in range(5)],
                    "relative_surface_age_rows": [[0.9] * 5 for _index in range(5)],
                },
            },
            map_seed="regional-bauxite-test",
            detail_level=2,
        )
        self.assertEqual(regional["occurrences"], repeated["occurrences"])

    def test_cold_earthlike_heightmap_does_not_paint_bauxite_continents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            candidates = [
                {
                    "material_id": material_id,
                    "name": name,
                    "material_subclass": subclass,
                    "confidence": confidence,
                    "display_color": color,
                }
                for material_id, name, subclass, confidence, color in [
                    ("mat_bauxite", "Bauxite", "regolith", 0.90, [172, 92, 64]),
                    ("mat_laterite", "Laterite", "regolith", 0.88, [150, 74, 46]),
                    ("mat_clay_rich_regolith", "Clay-Rich Regolith", "regolith", 0.86, [132, 118, 92]),
                    ("mat_basalt", "Basalt", "rock", 0.82, [72, 76, 70]),
                    ("mat_granite", "Granite", "rock", 0.80, [174, 162, 146]),
                ]
            ]
            heightmap = {
                "planet_id": "cold_affinity_test",
                "map_seed": "cold-affinity-test",
                "projection": "equirectangular",
                "min_elevation_m": -1000.0,
                "max_elevation_m": 1800.0,
                "sea_level_m": 0.0,
                "sample_grid": {
                    "width": 4,
                    "height": 3,
                    "rows": [
                        [-300.0, 600.0, 900.0, -300.0],
                        [-200.0, 500.0, 1200.0, -200.0],
                        [-400.0, 300.0, 700.0, -400.0],
                    ],
                },
            }

            model = generate_material_heatmap_model(
                planet={"id": "cold_affinity_test"},
                natural_material_model={
                    "planet_tags": ["active_hydrology", "weathered_surface", "basaltic_surface"],
                    "likely_materials": candidates,
                },
                terrain={
                    "map_seed": "cold-affinity-test",
                    "hydrology": {"cycle": "active", "target_ocean_fraction": 0.5},
                },
                heightmap=heightmap,
                atmosphere={"estimated_surface_temperature_k": 273.8},
                output_root=Path(temp_dir) / "heatmaps",
                storage_root=Path(temp_dir),
                image_size=(32, 16),
            )
            layers = {layer["material_id"]: layer for layer in model["layers"]}

            self.assertNotIn("mat_bauxite", layers)
            self.assertNotIn("mat_laterite", layers)
            self.assertGreater(layers["mat_basalt"]["coverage_fraction"], 0.0)

            warm_rows = [[302.0] * 4 for _row in range(3)]
            wet_rows = [[2400.0] * 4 for _row in range(3)]
            runoff_rows = [[900.0] * 4 for _row in range(3)]
            weathering_rows = [[0.82] * 4 for _row in range(3)]
            old_surface_rows = [[0.92] * 4 for _row in range(3)]
            warm_model = generate_material_heatmap_model(
                planet={
                    "id": "warm_affinity_test",
                    "surface_evolution_model": {
                        "process_grid": {
                            "chemical_weathering_rows": weathering_rows,
                            "relative_surface_age_rows": old_surface_rows,
                        },
                    },
                },
                natural_material_model={
                    "planet_tags": ["active_hydrology", "weathered_surface", "basaltic_surface"],
                    "likely_materials": candidates,
                },
                terrain={
                    "map_seed": "warm-affinity-test",
                    "hydrology": {"cycle": "active", "target_ocean_fraction": 0.5},
                },
                heightmap={**heightmap, "planet_id": "warm_affinity_test", "map_seed": "warm-affinity-test"},
                atmosphere={"estimated_surface_temperature_k": 302.0},
                water_cycle={
                    "climate_grid": {
                        "temperature_rows_k": warm_rows,
                        "annual_precipitation_rows_mm": wet_rows,
                        "annual_runoff_rows_mm": runoff_rows,
                    },
                },
                output_root=Path(temp_dir) / "heatmaps",
                storage_root=Path(temp_dir),
                image_size=(32, 16),
            )
            warm_layers = {layer["material_id"]: layer for layer in warm_model["layers"]}

            self.assertNotIn("mat_bauxite", warm_layers)


if __name__ == "__main__":
    unittest.main()
