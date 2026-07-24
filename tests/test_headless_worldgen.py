import json
import tempfile
import unittest
from pathlib import Path

from simulations.world_gen.headless_runner import (
    HeadlessWorldGenConfig,
    HeadlessWorldGenRunner,
)
from simulations.world_gen.generation_contract import build_generation_input_contract


class HeadlessWorldGenRuntimeTests(unittest.TestCase):
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
            self.assertEqual(7, len(result.stage_screenshots))
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
            self.assertIsInstance(planet.get("coastal_geomorphology_model"), dict)
            self.assertIsInstance(planet.get("coastal_summary"), dict)
            self.assertGreater(
                float((planet.get("surface_evolution_model") or {}).get("surface_pressure_bar", 0.0)),
                0.0,
            )


if __name__ == "__main__":
    unittest.main()
