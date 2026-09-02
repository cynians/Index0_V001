import json
import tempfile
import unittest
from pathlib import Path

from simulations.world_gen.headless_runner import (
    HeadlessWorldGenConfig,
    HeadlessWorldGenRunner,
    verify_production_pipeline,
)
from simulations.world_gen.generation_contract import build_generation_input_contract
from simulations.world_gen.heightmap import (
    CANONICAL_LOD0_SAMPLE_HEIGHT,
    CANONICAL_LOD0_SAMPLE_WIDTH,
    _materialize_shallow_margin_bathymetry,
    derive_heightmap_model,
)
from simulations.world_gen.true_color import TRUE_COLOR_MODEL_VERSION
from simulations.world_gen.world_gen_sim import WorldGenSimulation
from simulations.world_gen.worldgen_diagnostics import derive_causal_feature_diagnostics


class HeadlessWorldGenRuntimeTests(unittest.TestCase):
    def test_normal_heightmap_uses_explicit_canonical_lod0_resolution(self):
        heightmap = derive_heightmap_model(
            {
                "map_seed": "canonical-lod0-contract-test",
                "map_canvas": {
                    "projection": "equirectangular",
                    "width_px": 8192,
                    "height_px": 4096,
                    "circumference_m": 40_000_000.0,
                },
                "heightfield": {
                    "min_elevation_m": -7000.0,
                    "max_elevation_m": 6000.0,
                },
                "hydrology": {},
            },
            seed={"map_seed": "canonical-lod0-contract-test"},
        )

        grid = heightmap["sample_grid"]
        self.assertEqual(CANONICAL_LOD0_SAMPLE_WIDTH, grid["width"])
        self.assertEqual(CANONICAL_LOD0_SAMPLE_HEIGHT, grid["height"])
        self.assertEqual(
            "canonical_lod0",
            heightmap["resolution_contract"]["mode"],
        )
        self.assertEqual(
            CANONICAL_LOD0_SAMPLE_WIDTH,
            heightmap["resolution_contract"]["scientific_sample_dimensions"]["width"],
        )
        self.assertLess(heightmap["sample_spacing_x_m"], 50_000.0)

    def test_representative_region_bounds_are_seeded_and_physical(self):
        runner = HeadlessWorldGenRunner(Path("representative-test"))
        parent = {
            "bounds": {"type": "bbox", "min_x": -180.0, "max_x": 180.0, "min_y": -90.0, "max_y": 90.0},
            "heightmap_model": {
                "circumference_m": 40_000_000.0,
                "region_width_m": 40_000_000.0,
                "region_height_m": 20_000_000.0,
            },
        }
        config = HeadlessWorldGenConfig(
            regional_width_km=100.0,
            regional_height_km=100.0,
            regional_center_seed=1234,
        )
        bounds_a, center_a = runner._representative_region_bounds(parent, config)
        bounds_b, center_b = runner._representative_region_bounds(parent, config)

        self.assertEqual(bounds_a, bounds_b)
        self.assertEqual(center_a, center_b)
        self.assertAlmostEqual(100.0, (bounds_a["max_x"] - bounds_a["min_x"]) / 360.0 * 40_000.0, places=3)
        self.assertAlmostEqual(100.0, (bounds_a["max_y"] - bounds_a["min_y"]) / 180.0 * 20_000.0, places=3)
        self.assertGreaterEqual(center_a["center_latitude"], -89.0)
        self.assertLessEqual(center_a["center_latitude"], 89.0)

    def test_representative_footprint_schedule_separates_macroregion_and_region(self):
        config = HeadlessWorldGenConfig(
            regional_width_km=100.0,
            regional_height_km=100.0,
            regional_footprint_schedule_km=(1000.0, 100.0, 25.0),
        )

        self.assertEqual(
            (1000.0, 1000.0),
            HeadlessWorldGenRunner._configured_refinement_footprint(config, 0),
        )
        self.assertEqual(
            (100.0, 100.0),
            HeadlessWorldGenRunner._configured_refinement_footprint(config, 1),
        )
        self.assertEqual(
            (25.0, 25.0),
            HeadlessWorldGenRunner._configured_refinement_footprint(config, 2),
        )

    def test_representative_generic_randomizer_forces_plate_branch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = HeadlessWorldGenRunner(Path(temp_dir) / "representative")
            _world, sim = runner._new_runtime(HeadlessWorldGenConfig(
                randomize_mode="generic",
                randomizer_seed=1234,
                force_plate_tectonics=True,
                earthlike_constraints=True,
                render_outputs=False,
            ))
            self.assertEqual("mobile_lid", sim.seed_input_buffers["tectonics_mode"])
            self.assertEqual("earthlike", sim.seed_input_buffers["volatile_inventory"])
            water_fraction = float(sim.seed_input_buffers["water_fraction"])
            self.assertGreaterEqual(water_fraction, 0.35)
            self.assertLessEqual(water_fraction, 0.65)

    def test_lod0_materializes_a_bounded_passive_margin_ramp(self):
        rows = [
            [100.0, 100.0, -2500.0, -2500.0, -2500.0, 100.0],
            [100.0, 100.0, -2500.0, -2500.0, -2500.0, 100.0],
            [100.0, 100.0, -2500.0, -2500.0, -2500.0, 100.0],
        ]
        audit = _materialize_shallow_margin_bathymetry(
            rows,
            0.0,
            circumference_m=6_000.0,
        )

        self.assertEqual("shallow_margin_bathymetry_materialized", audit["status"])
        self.assertGreater(audit["raised_cell_count"], 0)
        self.assertGreaterEqual(rows[0][2], -420.0)

    def test_representative_runner_reports_production_pipeline_binding(self):
        # The parity helper inspects bound production methods only; a bare
        # instance keeps this contract test independent of the persistent
        # ontology/output setup used by a full generation run.
        sim = object.__new__(WorldGenSimulation)
        report = verify_production_pipeline(
            sim,
            [
                "_save_selected_planet_seed",
                "_save_atmosphere_model",
                "_save_interior_regime_model",
                "_save_terrain_seed_model",
                "_handle_heightmap_primary_action",
                "_handle_heightmap_primary_action",
            ],
            tectonic_pass_used=True,
            regional_selection_diagnostics=[
                {"route": "MapSimulation.regenerate_visible_region"}
            ],
        )

        self.assertTrue(report["verified"])
        self.assertEqual(
            "production_worldgen_simulation_and_stage_handlers",
            report["generator_scope"],
        )
        self.assertTrue(report["regional_route_verified"])

    def test_causal_feature_inventory_reports_model_ownership(self):
        diagnostics = derive_causal_feature_diagnostics({
            "tectonic_model": {
                "plates": [{"id": "plate_a"}],
                "boundary_segments": [{"kind": "collision"}],
                "continental_province_model": {"cratons": []},
                "orogen_system_model": {"systems": []},
                "hotspot_model": {"hotspots": []},
                "geologic_history": {"snapshots": []},
            },
            "heightmap_model": {
                "sample_grid": {"rows": [[0.0]]},
                "mountain_morphology": {"mountain_cell_fraction": 0.1},
                "shelf_sediment_model": {},
                "geology_model": {},
                "simulated_age_myr": 100.0,
            },
            "water_cycle_model": {
                "climate_grid": {},
                "ocean_circulation_model": {},
                "drainage_network_model": {},
                "rivers": [],
            },
            "surface_evolution_model": {
                "process_grid": {},
                "sediment_budget": {},
            },
            "material_heatmap_model": {"layers": []},
            "natural_material_model": {},
            "coastal_geomorphology_model": {"segments": []},
        })

        self.assertEqual("causal_feature_inventory_diagnosed", diagnostics["status"])
        self.assertEqual("production_worldgen_models_only", diagnostics["ownership"])
        self.assertGreaterEqual(diagnostics["resolved_feature_count"], 1)
        self.assertTrue(all("last_distinguishable_lod" in item for item in diagnostics["features"]))

    def test_saved_player_contract_replays_identical_seed_physics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            direct = HeadlessWorldGenRunner(Path(temp_dir) / "direct")
            _world_a, sim_a = direct._new_runtime(HeadlessWorldGenConfig(
                name="Parity", map_seed="parity-seed", radius_earth=1.13,
                core_radius_fraction=0.49, water_fraction=0.37,
                render_outputs=False,
            ))
            self.assertTrue(sim_a._save_selected_planet_seed())
            planet_a = sim_a._selected_planet_entity()
            contract = planet_a["world_gen_input_contract"]

            replay = HeadlessWorldGenRunner(Path(temp_dir) / "replay")
            _world_b, sim_b = replay._new_runtime(HeadlessWorldGenConfig(
                replay_contract=contract, render_outputs=False,
            ))
            self.assertTrue(sim_b._save_selected_planet_seed())
            planet_b = sim_b._selected_planet_entity()

            self.assertEqual(planet_a["world_gen_seed"], planet_b["world_gen_seed"])
            self.assertEqual(planet_a["derived_planet_physics"], planet_b["derived_planet_physics"])

    def test_replay_contract_restores_player_star_orbit_and_first_screen(self):
        contract = build_generation_input_contract(
            planet={
                "id": "planet_replay", "name": "Replay", "location_class": "planet",
                "periapsis_au": 0.42, "apoapsis_au": 0.78, "parent_body": "star_k",
            },
            seed={
                "planet_template": "silicate_terrestrial", "radius_earth": 1.22,
                "core_radius_fraction": 0.48, "crust_thickness_km": 44.0,
                "angular_velocity_deg_per_hour": 9.0, "water_fraction": 0.31,
                "volatile_inventory": "wet", "tectonics_mode": "unknown",
                "map_seed": "replay-exact", "crust_composition": {"major_elements": []},
            },
            system={"id": "system_k", "system_age_gyr": 7.1, "constituents": ["star_k"]},
            star={"id": "star_k", "spectral_class": "K3V", "luminosity_solar": 0.31, "mass_solar": 0.74},
            year=6437,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            runner = HeadlessWorldGenRunner(Path(temp_dir) / "replay")
            world, sim = runner._new_runtime(HeadlessWorldGenConfig(replay_contract=contract, render_outputs=False))

            self.assertEqual("system_k", sim.parent_system_id)
            self.assertEqual(0.31, sim.star_luminosity_solar)
            self.assertEqual("1.22", sim.seed_input_buffers["radius_earth"])
            self.assertEqual("0.31", sim.seed_input_buffers["water_fraction"])
            planet = sim._selected_planet_entity()
            self.assertEqual(0.42, planet["periapsis_au"])
            self.assertEqual(0.78, planet["apoapsis_au"])
            self.assertIsNotNone(world.get_entity("star_k"))

    def test_gas_giant_route_terminates_after_atmosphere_without_surface_maps(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = HeadlessWorldGenRunner(Path(temp_dir) / "gas").run(
                HeadlessWorldGenConfig(
                    name="Headless Giant Route Test",
                    randomize_mode="gas_giant",
                    randomizer_seed=41007,
                    screen_size=(960, 540),
                    layer_size=(320, 160),
                    regional_refinement_depth=2,
                )
            )

            self.assertEqual(
                ["crust", "atmosphere", "atmosphere"],
                result.stage_history,
            )
            self.assertEqual([], result.regional_refinement_ids)
            self.assertEqual(1, len(result.layer_images))
            planet = json.loads(
                Path(result.planet_path).read_text(encoding="utf-8")
            )
            self.assertIn("no_solid_surface", planet.get("tags") or [])
            self.assertEqual(
                "gas_giant_bands",
                planet.get("surface_render_mode"),
            )

    def test_real_runtime_completes_ui_route_and_renders_map_layers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = HeadlessWorldGenRunner(Path(temp_dir) / "run").run(
                HeadlessWorldGenConfig(
                    name="Headless Route Test",
                    map_seed="headless-route-test-001",
                    screen_size=(960, 540),
                    layer_size=(320, 160),
                )
            )

            self.assertEqual(
                [
                    "crust",
                    "atmosphere",
                    "regime",
                    "terrain",
                    "heightmap",
                    "water_cycle",
                ],
                result.stage_history,
            )
            self.assertEqual(
                "simulations.world_gen.world_gen_sim.WorldGenSimulation",
                result.runtime_classes["simulation"],
            )
            self.assertEqual(
                "simulations.world_gen.world_gen_renderer.WorldGenRenderer",
                result.runtime_classes["renderer"],
            )
            self.assertEqual("world.world_model.WorldModel", result.runtime_classes["world_model"])
            summary = json.loads(Path(result.summary_path).read_text(encoding="utf-8"))
            self.assertTrue(summary["pipeline_parity"]["verified"])
            self.assertEqual(6, len(result.stage_screenshots))
            self.assertEqual(7, len(result.layer_images))
            for path in [
                *result.stage_screenshots,
                *(item["path"] for item in result.layer_images),
                result.contact_sheet,
                result.summary_path,
                result.planet_path,
            ]:
                artifact = Path(path)
                self.assertTrue(artifact.exists(), artifact)
                self.assertGreater(artifact.stat().st_size, 0, artifact)

            planet = json.loads(Path(result.planet_path).read_text(encoding="utf-8"))
            self.assertIsInstance(planet.get("atmosphere_model"), dict)
            self.assertIsInstance(planet.get("interior_regime_model"), dict)
            self.assertIsInstance(planet.get("terrain_seed_model"), dict)
            self.assertIsInstance(planet.get("heightmap_model"), dict)
            self.assertIsInstance(planet.get("water_cycle_model"), dict)
            self.assertIsInstance(planet.get("material_heatmap_model"), dict)
            self.assertEqual(
                TRUE_COLOR_MODEL_VERSION,
                (planet.get("true_color_model") or {}).get("model_version"),
            )
            self.assertIsInstance(planet.get("coastal_geomorphology_model"), dict)
            self.assertIsInstance(planet.get("coastal_summary"), dict)
            self.assertGreater(
                float((planet.get("surface_evolution_model") or {}).get("surface_pressure_bar", 0.0)),
                0.0,
            )


if __name__ == "__main__":
    unittest.main()
