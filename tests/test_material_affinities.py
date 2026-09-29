import math
import tempfile
import unittest
from pathlib import Path

from simulations.world_gen.material_affinities import (
    MATERIAL_AFFINITY_PROFILES,
    material_affinity_score,
    material_distribution_role,
)
from simulations.world_gen.lithotectonic_settings import resolve_setting_recipes
from simulations.world_gen.material_heatmaps import generate_material_heatmap_model
from simulations.world_gen.material_lod import regional_crater_ejecta
from simulations.world_gen.material_formation import formation_contract
from simulations.world_gen.natural_materials import (
    configure_material_catalog,
    derive_natural_material_model,
    natural_material_entries,
)


from simulations.world_gen.regional_materials import derive_regional_material_model
from world.persistent_ontology_store import PersistentOntologyStore


def setUpModule():
    rows = PersistentOntologyStore(
        Path(__file__).resolve().parents[1] / "ontology" / "index0.owl"
    ).load_datasets().get("materials") or []
    configure_material_catalog(rows)


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
    def test_talus_and_colluvium_are_surface_covers_not_bedrock_units(self):
        for material_id in ("mat_talus", "mat_colluvium"):
            profile = MATERIAL_AFFINITY_PROFILES[material_id]
            contract = formation_contract(
                material_id,
                "sediment",
                profile["profile_id"],
            )
            self.assertEqual("colluvial_sediment", contract["category_id"])
            self.assertEqual("surface_cover", contract["spatial_representation"])
            self.assertEqual(
                "surface_cover",
                material_distribution_role(material_id, "sediment", 1),
            )

    def test_every_natural_material_has_an_explicit_profile(self):
        catalog_ids = {
            material["id"]
            for material in natural_material_entries()
            if material.get("material_subclass") not in {"atmospheric_gas", "element"}
        }

        self.assertEqual(210, len(catalog_ids))
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

    def test_distribution_roles_separate_substrate_cover_and_deposits(self):
        self.assertEqual(
            "bedrock",
            material_distribution_role("mat_basalt", "rock", 0),
        )
        self.assertEqual(
            "surface_cover",
            material_distribution_role("mat_clay_rich_regolith", "regolith", 1),
        )
        self.assertEqual(
            "mineral_constituent",
            material_distribution_role("mat_quartz", "mineral", 1),
        )
        self.assertEqual(
            "sparse_deposit",
            material_distribution_role("mat_bauxite", "regolith", 2),
        )

    def test_regional_craters_use_metre_scale_local_footprints(self):
        field = regional_crater_ejecta(
            {
                "region_width_m": 100_000.0,
                "region_height_m": 50_000.0,
                "craters": [{
                    "x": 0.5,
                    "y": 0.5,
                    "diameter_m": 4_000.0,
                }],
            },
            (32, 64),
        )

        affected = int((field > 0.0).sum())
        self.assertGreater(affected, 0)
        self.assertLess(affected, 64 * 32 // 3)

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

    def test_substrate_recipes_keep_bedrock_when_regolith_candidates_dominate(self):
        candidates = [
            {
                "material_id": f"mat_regolith_{index}",
                "name": f"Regolith {index}",
                "material_subclass": "regolith",
                "spatial_representation": "surface_cover",
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

        recipes, _provenance = resolve_setting_recipes({"likely_materials": candidates})

        used = {material_id for recipe in recipes.values() for material_id, _share in recipe}
        self.assertEqual({"mat_basalt", "mat_granite"}, used)
        self.assertEqual("mat_basalt", recipes["oceanic_ridge"][0][0])
        self.assertIn("mat_granite", dict(recipes["exposed_shield"]))

    def test_ores_and_minor_minerals_are_deferred_from_planetary_substrate(self):
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
            MATERIAL_AFFINITY_PROFILES["mat_obsidian"][
                "minimum_map_detail_level"
            ],
            2,
        )
        recipes, _provenance = resolve_setting_recipes(model)
        used = {material_id for recipe in recipes.values() for material_id, _share in recipe}
        self.assertIn("mat_basalt", used)
        for material_id in used:
            self.assertNotIn(
                candidates[material_id]["spatial_representation"],
                {"bounded_deposit", "constituent_abundance"},
                material_id,
            )
        self.assertNotIn("mat_chalcopyrite", used)

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
        self.assertEqual("inferred", occurrence["knowledge_state"])
        self.assertEqual(
            "generated_hidden_deposit_body",
            occurrence["deposit_body"]["truth_state"],
        )
        self.assertEqual(
            "residual_laterite_blanket",
            occurrence["deposit_body"]["deposit_type"],
        )
        estimate = occurrence["deposit_body"]["resource_estimate"]
        self.assertLess(0, estimate["in_situ_tonnage_range_t"][0])
        self.assertLess(
            estimate["in_situ_tonnage_range_t"][0],
            estimate["in_situ_tonnage_range_t"][1],
        )
        self.assertEqual(
            "generated_geometry_density_and_process_range_not_a_reserve",
            estimate["estimate_basis"],
        )
        self.assertGreaterEqual(
            len(occurrence["deposit_body"]["geometry"]["footprint_vertices"]),
            8,
        )
        self.assertEqual(
            "process_conditioned_irregular_lobed_v1",
            occurrence["deposit_body"]["geometry"]["boundary_model"],
        )
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

        parent_occurrence = regional["occurrences"][0]
        global_center = parent_occurrence["center_global_uv"]
        child_half_span = 0.08
        child_bounds = {
            "min_u": max(0.0, global_center["u"] - child_half_span),
            "max_u": min(1.0, global_center["u"] + child_half_span),
            "min_v": max(0.0, global_center["v"] - child_half_span),
            "max_v": min(1.0, global_center["v"] + child_half_span),
        }
        child = derive_regional_material_model(
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
            map_seed="child-map-seed-is-allowed-to-differ",
            root_map_seed="regional-bauxite-test",
            source_uv_bounds=child_bounds,
            parent_regional_material_model=regional,
            detail_level=3,
        )

        self.assertEqual(1, child["inherited_occurrence_count"])
        inherited = child["occurrences"][0]
        self.assertEqual(parent_occurrence["id"], inherited["id"])
        self.assertEqual(
            parent_occurrence["center_global_uv"],
            inherited["center_global_uv"],
        )
        self.assertEqual(
            parent_occurrence["deposit_body"],
            inherited["deposit_body"],
        )
        self.assertEqual(
            parent_occurrence["estimated_radius_m"],
            inherited["estimated_radius_m"],
        )
        self.assertTrue(inherited["inherited_from_parent"])

        radius_m = float(parent_occurrence["estimated_radius_m"])
        radius_u = radius_m / regional["region_width_m"]
        direction = 1.0 if global_center["u"] <= 0.5 else -1.0
        near_edge = global_center["u"] + direction * radius_u * 0.45
        far_edge = global_center["u"] + direction * radius_u * 1.45
        intersecting_bounds = {
            "min_u": min(near_edge, far_edge),
            "max_u": max(near_edge, far_edge),
            "min_v": max(0.0, global_center["v"] - radius_u * 0.45),
            "max_v": min(1.0, global_center["v"] + radius_u * 0.45),
        }
        intersecting_child = derive_regional_material_model(
            natural_model,
            heightmap,
            {},
            map_seed="intersecting-child",
            root_map_seed="regional-bauxite-test",
            source_uv_bounds=intersecting_bounds,
            parent_regional_material_model=regional,
            detail_level=3,
        )
        inherited_edge = intersecting_child["occurrences"][0]
        self.assertFalse(inherited_edge["center_inside_child_bounds"])
        self.assertTrue(inherited_edge["footprint_intersects_child_bounds"])
        self.assertTrue(
            inherited_edge["center"]["x"] < 0.0
            or inherited_edge["center"]["x"] > 1.0
        )

    def test_bauxite_is_a_regional_deposit_body_never_planetary_cover(self):
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
            rows = [
                [-300.0, 600.0, 900.0, 700.0, -300.0],
                [-200.0, 500.0, 1200.0, 800.0, -200.0],
                [-250.0, 450.0, 1000.0, 650.0, -250.0],
                [-400.0, 300.0, 700.0, 500.0, -400.0],
            ]
            heightmap = {
                "planet_id": "bauxite_scale_test",
                "map_seed": "bauxite-scale-test",
                "projection": "equirectangular",
                "min_elevation_m": -1000.0,
                "max_elevation_m": 1800.0,
                "sea_level_m": 0.0,
                "sample_grid": {"width": 5, "height": 4, "rows": rows},
            }
            natural_model = {
                "planet_tags": ["active_hydrology", "weathered_surface", "basaltic_surface"],
                "likely_materials": candidates,
            }
            cold = generate_material_heatmap_model(
                planet={"id": "bauxite_scale_test"},
                natural_material_model=natural_model,
                terrain={"map_seed": "bauxite-scale-test"},
                heightmap=heightmap,
                atmosphere={"estimated_surface_temperature_k": 273.8, "surface_pressure_bar": 1.0},
                output_root=Path(temp_dir) / "heatmaps",
                storage_root=Path(temp_dir),
            )
            cold_layers = {layer["material_id"]: layer for layer in cold["layers"]}
            self.assertNotIn("mat_bauxite", cold_layers)
            self.assertNotIn("mat_laterite", cold_layers)
            self.assertGreater(cold_layers["mat_basalt"]["mean_fraction"], 0.0)
            self.assertLessEqual(
                {layer["distribution_role"] for layer in cold["layers"]},
                {"bedrock", "surface_cover"},
            )

            warm_rows = [[302.0] * 5 for _row in range(4)]
            wet_rows = [[2400.0] * 5 for _row in range(4)]
            weathering_rows = [[0.82] * 5 for _row in range(4)]
            warm_planet = {
                "id": "bauxite_warm_test",
                "surface_evolution_model": {"process_grid": {"chemical_weathering_rows": weathering_rows}},
            }
            warm_climate = {"climate_grid": {
                "temperature_rows_k": warm_rows,
                "annual_precipitation_rows_mm": wet_rows,
            }}
            warm = generate_material_heatmap_model(
                planet=warm_planet,
                natural_material_model=natural_model,
                terrain={"map_seed": "bauxite-warm-test"},
                heightmap={**heightmap, "planet_id": "bauxite_warm_test"},
                atmosphere={"estimated_surface_temperature_k": 302.0, "surface_pressure_bar": 1.0},
                water_cycle=warm_climate,
                output_root=Path(temp_dir) / "heatmaps",
                storage_root=Path(temp_dir),
            )
            self.assertNotIn("mat_bauxite", {layer["material_id"] for layer in warm["layers"]})

            regional = generate_material_heatmap_model(
                planet={**warm_planet, "id": "bauxite_regional_test"},
                natural_material_model=natural_model,
                terrain={"map_seed": "bauxite-regional-test"},
                heightmap={
                    **heightmap,
                    "planet_id": "bauxite_regional_test",
                    "map_detail_level": 2,
                    "wrap_x": False,
                    "source_uv_bounds": {"min_u": 0.50, "max_u": 0.5025, "min_v": 0.50, "max_v": 0.5025},
                },
                atmosphere={"estimated_surface_temperature_k": 302.0, "surface_pressure_bar": 1.0},
                water_cycle=warm_climate,
                output_root=Path(temp_dir) / "regional_heatmaps",
                storage_root=Path(temp_dir),
                occurrences=[{
                    "material_id": "mat_bauxite",
                    "center_global_uv": {"u": 0.50125, "v": 0.50125},
                    "estimated_radius_m": 40_000.0,
                    "deposit_body": {"geometry": {
                        "bounding_radius_m": 40_000.0,
                        "orientation_deg": 0.0,
                        "geometry_fill_fraction": 0.6,
                        "footprint_vertices": [
                            [math.cos(index * math.tau / 12.0), math.sin(index * math.tau / 12.0)]
                            for index in range(12)
                        ],
                    }},
                }],
            )
            regional_layers = {layer["material_id"]: layer for layer in regional["layers"]}
            self.assertIn("mat_bauxite", regional_layers)
            self.assertEqual("sparse_deposit", regional_layers["mat_bauxite"]["distribution_role"])


if __name__ == "__main__":
    unittest.main()
