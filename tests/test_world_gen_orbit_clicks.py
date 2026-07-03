import unittest
import random
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pygame

from app.input_router import InputRouter
from engine.camera import Camera
from engine.input_controller import InputController
from simulations.space.system import CelestialSystem
from simulations.world_gen.crust import MAJOR_CRUST_TARGET_PERCENT, estimate_crust_density_kg_m3
from simulations.world_gen.heightmap import (
    contour_levels_for_heightmap,
    derive_heightmap_model,
    display_contour_interval_m,
    height_marker_interval_m,
)
from simulations.world_gen.interior_regime import derive_interior_regime_model
from simulations.world_gen.material_heatmaps import generate_material_heatmap_model
from simulations.world_gen.terrain_seed import derive_terrain_seed_model
from simulations.world_gen.world_gen_sim import WorldGenSimulation


class FakeLoader:
    def __init__(self, entries_directory):
        self.entries_directory = Path(entries_directory)
        self.entity_aliases = {}
        self.datasets = {}
        self.entities = {}
        self.reference_graph_rebuilt = False

    def build_reference_graph(self):
        self.reference_graph_rebuilt = True

    def persist_entity(self, entity, previous_entity_id=None):
        entity_id = entity.get("id")
        if not entity_id:
            return False
        previous_entity_id = previous_entity_id or None
        if previous_entity_id and previous_entity_id != entity_id:
            self.entities.pop(previous_entity_id, None)
        entity["_dataset"] = entity.get("_dataset") or "locations"
        dataset = self.datasets.setdefault(entity["_dataset"], [])
        dataset[:] = [
            item for item in dataset
            if not (isinstance(item, dict) and item.get("id") in {entity_id, previous_entity_id})
        ]
        dataset.append(entity)
        self.entities[entity_id] = entity
        return True


class FakeTouchDegrees:
    def __init__(self):
        self.refreshed = False

    def refresh(self):
        self.refreshed = True


class FakeWorldModel:
    def __init__(self, entries_directory=None):
        self.loader = FakeLoader(entries_directory or tempfile.mkdtemp())
        self.entities = {
            "system_alpha": {
                "id": "system_alpha",
                "type": "location",
                "_dataset": "locations",
                "name": "Alpha",
                "location_class": "star_system",
            },
            "star_alpha": {
                "id": "star_alpha",
                "type": "location",
                "_dataset": "locations",
                "name": "Alpha Primary",
                "location_class": "star",
                "star_system": "system_alpha",
                "luminosity_solar": 1.0,
            },
        }
        self.loader.entities.update(self.entities)
        self.loader.datasets["locations"] = list(self.entities.values())
        self.touch_degrees = FakeTouchDegrees()

    def get_entity(self, entity_id):
        return self.loader.entities.get(entity_id)

    def get_entities_by_dataset(self, dataset_name):
        return [
            entity for entity in self.loader.entities.values()
            if entity.get("_dataset") == dataset_name
        ]


class FakeCamera:
    def __init__(self, points):
        self.points = dict(points)

    def screen_to_world(self, pos):
        return self.points[pos]


class WorldGenOrbitClickTests(unittest.TestCase):
    def _sim(self):
        return WorldGenSimulation(
            world_model=FakeWorldModel(),
            parent_system_id="system_alpha",
            year=2400,
        )

    def _click(self, pos):
        return SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1, pos=pos)

    def test_first_orbit_click_sets_circular_candidate(self):
        sim = self._sim()
        camera = FakeCamera({(10, 10): (sim.AU_M, 0.0)})

        sim.handle_pointer_event(self._click((10, 10)), camera, (10, 10))

        self.assertEqual("1", sim.input_buffers["periapsis_au"])
        self.assertEqual("1", sim.input_buffers["apoapsis_au"])
        self.assertEqual("second", sim.orbit_pick_stage)
        self.assertTrue(sim.planetary_model["orbit_valid"])
        self.assertEqual(0.0, sim.planetary_model["eccentricity"])

    def test_second_orbit_click_sets_elliptical_candidate(self):
        sim = self._sim()
        camera = FakeCamera({
            (10, 10): (sim.AU_M, 0.0),
            (20, 20): (2.5 * sim.AU_M, 0.0),
        })

        sim.handle_pointer_event(self._click((10, 10)), camera, (10, 10))
        sim.handle_pointer_event(self._click((20, 20)), camera, (20, 20))

        self.assertEqual("1", sim.input_buffers["periapsis_au"])
        self.assertEqual("2.5", sim.input_buffers["apoapsis_au"])
        self.assertEqual("first", sim.orbit_pick_stage)
        self.assertAlmostEqual(1.75, sim.planetary_model["semi_major_axis_au"])
        self.assertAlmostEqual(1.5 / 3.5, sim.planetary_model["eccentricity"])

    def test_control_panel_click_does_not_set_orbit(self):
        sim = self._sim()
        sim.set_control_panel_rect(pygame.Rect(0, 0, 100, 100))
        camera = FakeCamera({(10, 10): (sim.AU_M, 0.0)})

        sim.handle_pointer_event(self._click((10, 10)), camera, (10, 10))

        self.assertEqual("", sim.input_buffers["periapsis_au"])
        self.assertEqual("", sim.input_buffers["apoapsis_au"])
        self.assertFalse(sim.planetary_model["orbit_valid"])

    def test_enter_names_and_persists_planet_from_locked_orbit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            world_model = FakeWorldModel(entries_directory=temp_dir)
            sim = WorldGenSimulation(
                world_model=world_model,
                parent_system_id="system_alpha",
                year=2400,
            )
            sim._set_orbit_distances(1.0, 2.0)

            sim.handle_event(SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_RETURN, unicode="", mod=0))
            self.assertTrue(sim.planet_name_prompt_active)

            for char in "Blue":
                sim.handle_event(SimpleNamespace(type=pygame.KEYDOWN, key=0, unicode=char, mod=0))
            sim.handle_event(SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_RETURN, unicode="", mod=0))

            planet = world_model.get_entity("planet_blue")
            self.assertIsNotNone(planet)
            self.assertEqual("Blue", planet["name"])
            self.assertEqual("system_alpha", planet["star_system"])
            self.assertEqual("star_alpha", planet["parent_location"])
            self.assertEqual("star_alpha", planet["parent_body"])
            self.assertIn("system_alpha", planet["parents"])
            self.assertIn("star_alpha", planet["parents"])
            self.assertGreaterEqual(planet["mean_anomaly_deg_at_epoch"], 0.0)
            self.assertLess(planet["mean_anomaly_deg_at_epoch"], 360.0)
            self.assertEqual(1.5 * sim.AU_M, planet["semi_major_axis_m"])
            self.assertAlmostEqual(1.0 / 3.0, planet["eccentricity"])
            self.assertIn("orbit_locked", planet["tags"])
            self.assertIn("world_gen_unfinished", planet["tags"])
            self.assertIn("world_gen_stage_crust", planet["tags"])
            self.assertEqual("orbit_locked", planet["environment_summary"]["status"])
            self.assertEqual("orbit_locked", planet["map_status"])
            self.assertEqual("equirectangular", planet["map_projection"])
            self.assertEqual(2048, planet["map_canvas_width_px"])
            self.assertEqual(1024, planet["map_canvas_height_px"])
            self.assertEqual({"type": "bbox", "min_x": -180.0, "max_x": 180.0, "min_y": -90.0, "max_y": 90.0}, planet["bounds"])
            self.assertIn(planet, sim._active_system_bodies())
            self.assertTrue(world_model.loader.reference_graph_rebuilt)
            self.assertTrue(world_model.touch_degrees.refreshed)

            self.assertEqual("planet_blue", world_model.loader.datasets["locations"][-1]["id"])

    def test_named_planet_reuses_existing_planet_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            world_model = FakeWorldModel(entries_directory=temp_dir)
            existing = {
                "id": "planet_blue",
                "name": "Blue",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "star_system": "system_alpha",
                "tags": ["canon"],
                "wiki_entry": "Existing encyclopedic notes.",
            }
            world_model.loader.entities["planet_blue"] = existing
            world_model.loader.datasets["locations"].append(existing)
            sim = WorldGenSimulation(
                world_model=world_model,
                parent_system_id="system_alpha",
                year=2400,
            )
            sim._set_orbit_distances(1.0, 2.0)
            sim.planet_name_buffer = "Blue"

            self.assertTrue(sim._commit_named_planet())

            planet = world_model.get_entity("planet_blue")
            self.assertIs(planet, existing)
            self.assertEqual("planet_blue", sim.selected_world_gen_planet_id)
            self.assertEqual("Existing encyclopedic notes.", planet["wiki_entry"])
            self.assertEqual("system_alpha", planet["star_system"])
            self.assertEqual("star_alpha", planet["parent_location"])
            self.assertIn("canon", planet["tags"])
            self.assertIn("orbit_locked", planet["tags"])
            self.assertIn("world_gen_candidate", planet["tags"])
            self.assertEqual(1, sum(
                1 for item in world_model.loader.datasets["locations"]
                if isinstance(item, dict) and item.get("id") == "planet_blue"
            ))
            self.assertIn("Linked planet: Blue", sim.commit_status)

    def test_clicking_committed_planet_selects_it_without_replacing_orbit(self):
        sim = self._sim()
        sim.set_planet_hitboxes([("planet_blue", pygame.Rect(0, 0, 30, 30))])
        sim.world_model.loader.entities["planet_blue"] = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
        }
        sim._set_orbit_distances(1.0, 2.0)
        camera = FakeCamera({(10, 10): (9.0 * sim.AU_M, 0.0)})

        sim.handle_pointer_event(self._click((10, 10)), camera, (10, 10))

        self.assertEqual("planet_blue", sim.selected_world_gen_planet_id)
        self.assertEqual("1", sim.input_buffers["periapsis_au"])
        self.assertEqual("2", sim.input_buffers["apoapsis_au"])
        self.assertIn("Selected Blue", sim.commit_status)

    def test_name_prompt_consumes_global_shortcuts(self):
        sim = self._sim()
        sim.planet_name_prompt_active = True

        class FakeNavigation:
            def __init__(self):
                self.keydowns = 0

            def handle_keydown(self, event):
                self.keydowns += 1

        class FakeApp:
            knowledge_layer_active = False
            repository_return_confirm_active = False
            system_menu_active = False
            system_settings_active = False

            def __init__(self, active_sim):
                self.active_sim = active_sim
                self.navigation = FakeNavigation()

            def get_active_simulation(self):
                return self.active_sim

        app = FakeApp(sim)
        router = InputRouter(app)

        handled = router._handle_keydown_navigation(
            SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_f, unicode="f", mod=0)
        )

        self.assertTrue(handled)
        self.assertEqual("f", sim.planet_name_buffer)
        self.assertEqual(0, app.navigation.keydowns)

    def test_name_prompt_blocks_window_shortcuts_before_app_router(self):
        sim = self._sim()
        sim.planet_name_prompt_active = True

        class FakeApp:
            def __init__(self, active_sim):
                self.active_sim = active_sim

            def consumes_global_keydown(self):
                return self.active_sim.consumes_global_keydown()

            def handle_event(self, event):
                self.active_sim.handle_event(event)

        controller = InputController(Camera(800, 600), FakeApp(sim))
        controller.process([SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_f, unicode="f", mod=0)])

        self.assertTrue(controller.show_fps)
        self.assertEqual("f", sim.planet_name_buffer)

    def test_cancel_name_prompt_resets_draft_state(self):
        sim = self._sim()
        sim._set_orbit_distances(1.0, 2.0)
        sim.editor_stage = "atmosphere"
        sim.planet_name_prompt_active = True
        sim.planet_name_buffer = "Old"

        sim._cancel_planet_name_prompt()

        self.assertFalse(sim.planet_name_prompt_active)
        self.assertEqual("", sim.input_buffers["periapsis_au"])
        self.assertEqual("", sim.input_buffers["apoapsis_au"])
        self.assertEqual("crust", sim.editor_stage)

    def test_selected_planet_seed_is_saved_to_planet(self):
        sim = self._sim()
        planet = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "tags": ["world_gen_candidate"],
        }
        sim.world_model.loader.entities["planet_blue"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_blue"
        sim.seed_input_buffers.update({
            "radius_earth": "1.2",
            "core_radius_fraction": "0.5",
            "crust_thickness_km": "40",
            "angular_velocity_deg_per_hour": "12",
            "water_fraction": "0.65",
            "volatile_inventory": "wet",
            "tectonics_mode": "mobile_lid",
        })

        self.assertTrue(sim._save_selected_planet_seed())

        self.assertEqual(1.2, planet["world_gen_seed"]["radius_earth"])
        self.assertEqual("mobile_lid", planet["world_gen_seed"]["tectonics_mode"])
        self.assertIn("crust_composition", planet["world_gen_seed"])
        self.assertIn("derived_planet_physics", planet["world_gen_seed"])
        self.assertAlmostEqual(30.0, planet["world_gen_seed"]["rotation_hours"])
        self.assertGreater(planet["world_gen_seed"]["mass_earth"], 0.0)
        self.assertIn("crust_composition", planet)
        self.assertIn("derived_planet_physics", planet)
        self.assertEqual(planet["derived_planet_physics"]["mass_kg"], planet["mass_kg"])
        self.assertIn("world_gen_seeded", planet["tags"])
        self.assertIn("world_gen_unfinished", planet["tags"])
        self.assertIn("world_gen_stage_atmosphere", planet["tags"])
        self.assertEqual("seed_defined", planet["environment_summary"]["status"])
        self.assertEqual("atmosphere", sim.editor_stage)

    def test_atmosphere_model_is_saved_after_crust_step(self):
        sim = self._sim()
        planet = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "semi_major_axis_m": sim.AU_M,
            "tags": ["world_gen_candidate"],
        }
        sim.world_model.loader.entities["planet_blue"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_blue"
        sim._save_selected_planet_seed()

        self.assertTrue(sim._save_atmosphere_model())

        self.assertIn("atmosphere_model", planet)
        self.assertIn("atmosphere_summary", planet)
        self.assertIn("composition", planet["atmosphere_model"])
        self.assertGreater(planet["atmosphere_model"]["escape_velocity_m_s"], 0.0)
        self.assertIn("atmosphere_modeled", planet["tags"])
        self.assertEqual("regime", sim.editor_stage)

    def test_gas_giant_atmosphere_completes_without_surface_route(self):
        sim = self._sim()
        planet = {
            "id": "planet_jove",
            "name": "Jove",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "semi_major_axis_m": 5.2 * sim.AU_M,
            "tags": ["world_gen_candidate"],
        }
        sim.world_model.loader.entities["planet_jove"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_jove"
        sim.seed_input_buffers.update({
            "radius_earth": "9.5",
            "core_radius_fraction": "0.12",
            "crust_thickness_km": "5",
            "angular_velocity_deg_per_hour": "36",
            "water_fraction": "0.05",
            "volatile_inventory": "dense",
            "tectonics_mode": "unknown",
        })
        sim._save_selected_planet_seed()

        self.assertTrue(sim._save_atmosphere_model())

        self.assertEqual("gas_giant_envelope_modeled", planet["map_status"])
        self.assertFalse(planet["world_gen_complete"])
        self.assertIn("world_gen_unfinished", planet["tags"])
        self.assertIn("world_gen_stage_atmosphere", planet["tags"])
        self.assertEqual("gas_giant_bands", planet["surface_render_mode"])
        self.assertIn("gas_giant", planet["tags"])
        self.assertIn("mat_molecular_hydrogen_gas", planet["atmospheric_materials"])
        self.assertGreaterEqual(len(planet["atmosphere_bands"]), 3)
        self.assertEqual("atmosphere", sim.editor_stage)

        self.assertTrue(sim._world_gen_can_finish())
        self.assertTrue(sim._finish_world_gen())
        self.assertTrue(planet["world_gen_complete"])
        self.assertIn("world_gen_complete", planet["tags"])
        self.assertIn("world_gen_stage_complete", planet["tags"])

        layers = CelestialSystem()._create_layers_for_entity(planet).get_layers()
        self.assertEqual("atmospheric bands", layers[0]["name"])
        self.assertEqual("gas_giant_bands", layers[0]["render_style"])

    def test_complete_worldgen_button_finalizes_ready_gas_giant(self):
        sim = self._sim()
        planet = {
            "id": "planet_jove",
            "name": "Jove",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "semi_major_axis_m": 5.2 * sim.AU_M,
            "tags": ["world_gen_candidate"],
        }
        sim.world_model.loader.entities["planet_jove"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_jove"
        sim.seed_input_buffers.update({
            "radius_earth": "9.5",
            "core_radius_fraction": "0.12",
            "crust_thickness_km": "5",
            "angular_velocity_deg_per_hour": "36",
            "water_fraction": "0.05",
            "volatile_inventory": "dense",
            "tectonics_mode": "unknown",
        })
        sim._save_selected_planet_seed()
        sim._save_atmosphere_model()
        sim.set_control_panel_rect(pygame.Rect(0, 0, 500, 120))
        sim.set_crust_ui_rects(
            save_rect=pygame.Rect(10, 10, 100, 30),
            complete_rect=pygame.Rect(130, 10, 190, 30),
        )

        sim.handle_pointer_event(self._click((150, 20)), None, (150, 20))

        self.assertTrue(planet["world_gen_complete"])
        self.assertIn("world_gen_stage_complete", planet["tags"])

    def test_resuming_misrouted_gas_giant_repairs_heightmap_route(self):
        sim = self._sim()
        planet = {
            "id": "planet_jove",
            "name": "Jove",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "world_gen_seed": {
                **sim.DEFAULT_SEED,
                "radius_earth": 9.5,
                "core_radius_fraction": 0.12,
                "crust_thickness_km": 5.0,
                "angular_velocity_deg_per_hour": 36.0,
                "water_fraction": 0.05,
                "volatile_inventory": "dense",
                "crust_composition": sim._serializable_crust_composition(),
            },
            "atmosphere_model": {"has_solid_surface": True, "surface_pressure_bar": 1.0},
            "terrain_seed_model": {"status": "wrong_route"},
            "heightmap_model": {"status": "heightmap_seeded"},
            "map_status": "heightmap_seeded",
            "tags": ["world_gen_unfinished", "world_gen_stage_heightmap"],
        }
        sim.world_model.loader.entities["planet_jove"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)

        self.assertTrue(sim._select_planet_for_worldgen("planet_jove"))

        self.assertEqual("atmosphere", sim.editor_stage)
        self.assertEqual("gas_giant_envelope_modeled", planet["map_status"])
        self.assertNotIn("heightmap_model", planet)
        self.assertNotIn("terrain_seed_model", planet)
        self.assertEqual("gas_giant_bands", planet["surface_render_mode"])
        self.assertIn("mat_molecular_hydrogen_gas", planet["atmospheric_materials"])
        self.assertIn("Repaired gas giant envelope", sim.commit_status)

    def test_interior_regime_is_saved_after_atmosphere_step(self):
        sim = self._sim()
        planet = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "semi_major_axis_m": sim.AU_M,
            "tags": ["world_gen_candidate"],
        }
        sim.world_model.loader.entities["planet_blue"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_blue"
        sim._save_selected_planet_seed()
        sim._save_atmosphere_model()

        self.assertTrue(sim._save_interior_regime_model())

        self.assertIn("interior_regime_model", planet)
        self.assertIn("surface_process_model", planet)
        self.assertIn("map_generation_recipe", planet)
        self.assertIn("interior_regime_modeled", planet["tags"])
        self.assertIn("surface_processes_modeled", planet["tags"])
        self.assertIn("tectonic_regime", planet["geology_summary"])
        self.assertIn("hydrologic_cycle", planet["environment_summary"])
        self.assertEqual("terrain", sim.editor_stage)

    def test_terrain_seed_for_tectonic_planet_defines_plates(self):
        sim = self._sim()
        planet = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "semi_major_axis_m": sim.AU_M,
            "tags": ["world_gen_candidate"],
        }
        sim.world_model.loader.entities["planet_blue"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_blue"
        sim._save_selected_planet_seed()
        sim._save_atmosphere_model()
        sim._save_interior_regime_model()

        self.assertTrue(sim._save_terrain_seed_model())

        self.assertEqual("tectonic_plates_defined", planet["map_status"])
        self.assertEqual("equirectangular", planet["map_projection"])
        self.assertEqual(2048, planet["map_canvas_width_px"])
        self.assertEqual(1024, planet["map_canvas_height_px"])
        self.assertIn("terrain_seed_model", planet)
        self.assertIn("tectonic_model", planet)
        self.assertNotIn("heightmap_model", planet)
        self.assertIn("map_layers", planet)
        self.assertIn("terrain_seeded", planet["tags"])
        self.assertIn("tectonic_plates_defined", planet["tags"])
        self.assertIn("relief_driver", planet["geology_summary"])
        self.assertIn("target_ocean_fraction", planet["hydrology_summary"])
        self.assertEqual("tectonics", sim.editor_stage)
        self.assertGreaterEqual(planet["tectonic_model"]["plate_count"], 3)
        self.assertIn("mantle_currents", planet["tectonic_model"])

    def test_advancing_tectonics_creates_heightmap(self):
        sim = self._sim()
        planet = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "semi_major_axis_m": sim.AU_M,
            "tags": ["world_gen_candidate"],
        }
        sim.world_model.loader.entities["planet_blue"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_blue"
        sim._save_selected_planet_seed()
        sim._save_atmosphere_model()
        sim._save_interior_regime_model()
        sim._save_terrain_seed_model()

        self.assertTrue(sim._advance_tectonics_model())

        self.assertEqual("tectonics_advanced", planet["map_status"])
        self.assertEqual("heightmap", sim.editor_stage)
        self.assertIn("heightmap_model", planet)
        self.assertIn("tectonics_advanced", planet["tags"])
        self.assertEqual("tectonics_advanced", planet["heightmap_model"]["source_models"]["tectonics"])
        self.assertGreaterEqual(planet["tectonic_model"]["age_myr"], 125.0)
        self.assertIn("orogenic_uplift", planet["geology_summary"])
        sample_values = [
            value
            for row in planet["heightmap_model"]["sample_grid"]["rows"]
            for value in row
        ]
        self.assertGreater(max(sample_values) - min(sample_values), 5000.0)
        self.assertGreater(planet["heightmap_model"]["hypsometry_summary"]["land_fraction"], 0.05)
        self.assertGreater(planet["heightmap_model"]["hypsometry_summary"]["ocean_fraction"], 0.05)

        self.assertTrue(sim._world_gen_can_finish())
        self.assertTrue(sim._finish_world_gen())
        self.assertTrue(planet["world_gen_complete"])
        self.assertIn("world_gen_complete", planet["tags"])

    def test_heightmap_primary_action_advances_when_tectonics_available(self):
        sim = self._sim()
        planet = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "semi_major_axis_m": sim.AU_M,
            "tags": ["world_gen_candidate"],
        }
        sim.world_model.loader.entities["planet_blue"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_blue"
        sim._save_selected_planet_seed()
        sim._save_atmosphere_model()
        sim._save_interior_regime_model()
        sim._save_terrain_seed_model()
        sim.editor_stage = "heightmap"

        self.assertTrue(sim._heightmap_can_advance_tectonics())
        self.assertTrue(sim._handle_heightmap_primary_action())

        self.assertEqual("tectonics_advanced", planet["map_status"])
        self.assertIn("heightmap_model", planet)

    def test_selecting_existing_planet_resumes_next_unfinished_stage(self):
        sim = self._sim()
        planet = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "world_gen_seed": {
                **sim.DEFAULT_SEED,
                "crust_composition": sim._serializable_crust_composition(),
            },
            "atmosphere_model": {"surface_pressure_bar": 1.0, "estimated_surface_temperature_k": 288.0},
            "tags": ["world_gen_unfinished", "world_gen_stage_regime"],
        }
        sim.world_model.loader.entities["planet_blue"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)

        self.assertTrue(sim._select_planet_for_worldgen("planet_blue"))

        self.assertEqual("regime", sim.editor_stage)

    def test_existing_heightmap_with_plate_regime_can_advance_tectonics(self):
        sim = self._sim()
        planet = {
            "id": "planet_legacy",
            "name": "Legacy",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "semi_major_axis_m": sim.AU_M,
            "map_status": "heightmap_seeded",
            "interior_regime_model": {
                "interior": {
                    "tectonic_regime": "plate_tectonics",
                },
                "surface_processes": {
                    "surface_pressure_bar": 1.0,
                    "surface_temperature_k": 288.0,
                    "hydrologic_cycle": "active",
                    "liquid_water_possible": True,
                    "crater_retention": "low",
                    "primary_topography": "plate_boundaries_mountain_belts_and_trenches",
                    "erosion_processes": ["fluvial"],
                },
                "map_recipe": ["initialize_spherical_height_field"],
            },
            "heightmap_model": {"status": "heightmap_seeded"},
            "tags": ["world_gen_candidate"],
        }
        sim.world_model.loader.entities["planet_legacy"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_legacy"
        sim.editor_stage = "heightmap"

        self.assertTrue(sim._heightmap_can_advance_tectonics())
        self.assertTrue(sim._handle_heightmap_primary_action())

        self.assertEqual("tectonics_advanced", planet["map_status"])
        self.assertIn("tectonic_model", planet)
        self.assertIn("heightmap_model", planet)

    def test_airless_inactive_planet_generates_crater_heightmap(self):
        sim = self._sim()
        sim.seed_input_buffers.update({
            "radius_earth": "0.25",
            "core_radius_fraction": "0",
            "crust_thickness_km": "120",
            "angular_velocity_deg_per_hour": "8",
            "water_fraction": "0",
            "volatile_inventory": "none",
            "tectonics_mode": "unknown",
        })
        planet = {
            "id": "planet_rock",
            "name": "Rock",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "semi_major_axis_m": 2.0 * sim.AU_M,
            "tags": ["world_gen_candidate"],
        }
        sim.world_model.loader.entities["planet_rock"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_rock"
        sim._save_selected_planet_seed()
        sim._save_atmosphere_model()
        sim._save_interior_regime_model()

        self.assertTrue(sim._save_terrain_seed_model())

        self.assertEqual("crater_heightmap_seeded", planet["map_status"])
        self.assertEqual("heightmap", sim.editor_stage)
        self.assertIn("crater_model", planet)
        self.assertIn("heightmap_model", planet)
        self.assertNotIn("tectonic_model", planet)
        self.assertEqual("craters_seeded", planet["heightmap_model"]["source_models"]["craters"])
        self.assertGreater(len(planet["crater_model"]["craters"]), 10)

    def test_escape_closes_worldgen_fullscreen_editor_before_repository_prompt(self):
        sim = self._sim()
        sim.world_model.loader.entities["planet_blue"] = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
        }
        sim.selected_world_gen_planet_id = "planet_blue"

        class FakeApp:
            knowledge_layer_active = False
            repository_return_confirm_active = False
            system_menu_active = False
            system_settings_active = False

            def __init__(self, active_sim):
                self.active_sim = active_sim

            def get_active_simulation(self):
                return self.active_sim

        app = FakeApp(sim)
        router = InputRouter(app)

        handled = router._handle_keydown_navigation(
            SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0)
        )

        self.assertTrue(handled)
        self.assertFalse(app.repository_return_confirm_active)
        self.assertIsNone(sim.selected_world_gen_planet_id)

    def test_crust_slider_redistributes_major_elements_to_target_total(self):
        sim = self._sim()

        self.assertAlmostEqual(MAJOR_CRUST_TARGET_PERCENT, sim._crust_major_total(), places=3)

        sim.crust_composition = sim._serializable_crust_composition()
        sim.crust_slider_rects = {"O": pygame.Rect(0, 0, 990, 20)}
        sim._set_crust_abundance_from_screen_x("O", 500)

        oxygen = next(
            element for element in sim.crust_composition["major_elements"]
            if element["symbol"] == "O"
        )
        self.assertAlmostEqual(50.0, oxygen["abundance_percent"], places=3)
        self.assertAlmostEqual(MAJOR_CRUST_TARGET_PERCENT, sim._crust_major_total(), places=3)

    def test_add_abundant_trace_element_promotes_it_to_major_slider(self):
        sim = self._sim()

        self.assertTrue(sim._add_abundant_trace_element("Au"))

        symbols = [element["symbol"] for element in sim.crust_composition["major_elements"]]
        self.assertIn("Au", symbols)
        self.assertAlmostEqual(MAJOR_CRUST_TARGET_PERCENT, sim._crust_major_total(), places=3)
        gold = next(element for element in sim.crust_composition["major_elements"] if element["symbol"] == "Au")
        self.assertGreater(gold["abundance_percent"], 0.0)

    def test_generic_seed_randomizer_varies_inputs_and_low_trace_elements(self):
        sim = self._sim()
        before = dict(sim.seed_input_buffers)

        self.assertTrue(sim.randomize_seed("generic", rng=random.Random(42)))

        self.assertNotEqual(before, sim.seed_input_buffers)
        seed = sim._coerce_seed_payload()
        self.assertIsNotNone(seed)
        self.assertGreaterEqual(seed["radius_earth"], 0.75)
        self.assertLessEqual(seed["radius_earth"], 1.35)
        self.assertGreaterEqual(seed["core_radius_fraction"], 0.42)
        self.assertLessEqual(seed["core_radius_fraction"], 0.68)
        self.assertGreaterEqual(seed["crust_thickness_km"], 18.0)
        self.assertLessEqual(seed["crust_thickness_km"], 55.0)
        self.assertGreaterEqual(seed["water_fraction"], 0.15)
        self.assertLessEqual(seed["water_fraction"], 0.78)
        self.assertIn(seed["volatile_inventory"], {"dry", "wet", "earthlike"})
        self.assertIn(seed["tectonics_mode"], {"stagnant_lid", "mobile_lid", "unknown"})
        self.assertAlmostEqual(MAJOR_CRUST_TARGET_PERCENT, sim._crust_major_total(), places=3)
        trace_elements = sim.crust_composition["trace_elements"]
        self.assertGreaterEqual(len(trace_elements), 2)
        self.assertLessEqual(sum(element["abundance_percent"] for element in trace_elements), 1.0)
        self.assertEqual("Generated generic seed", sim.commit_status)

    def test_eccentric_seed_randomizer_uses_wider_ranges_and_exotic_trace_elements(self):
        sim = self._sim()

        self.assertTrue(sim.randomize_seed("eccentric", rng=random.Random(7)))

        seed = sim._coerce_seed_payload()
        self.assertIsNotNone(seed)
        self.assertGreaterEqual(seed["radius_earth"], 0.22)
        self.assertLessEqual(seed["radius_earth"], 2.6)
        self.assertGreaterEqual(seed["core_radius_fraction"], 0.08)
        self.assertLessEqual(seed["core_radius_fraction"], 0.82)
        self.assertGreaterEqual(seed["crust_thickness_km"], 4.0)
        self.assertLessEqual(seed["crust_thickness_km"], 145.0)
        self.assertIn(seed["volatile_inventory"], {"none", "thin", "dry", "wet", "earthlike", "dense"})
        self.assertIn(seed["tectonics_mode"], {"inactive", "stagnant_lid", "mobile_lid", "episodic_lid", "heat_pipe", "unknown"})
        symbols = {element["symbol"] for element in sim.crust_composition["trace_elements"]}
        self.assertTrue(symbols & {"Au", "Pt", "Os", "U", "Th", "Ir", "W", "Re"})
        self.assertLessEqual(sum(element["abundance_percent"] for element in sim.crust_composition["trace_elements"]), 1.0)
        self.assertAlmostEqual(MAJOR_CRUST_TARGET_PERCENT, sim._crust_major_total(), places=3)
        self.assertEqual("Generated eccentric seed", sim.commit_status)

    def test_seed_randomizer_buttons_apply_mode(self):
        sim = self._sim()
        planet = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
        }
        sim.world_model.loader.entities["planet_blue"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_blue"
        sim.set_control_panel_rect(pygame.Rect(0, 0, 500, 200))
        sim.set_crust_ui_rects(
            random_generic_rect=pygame.Rect(10, 10, 100, 30),
            random_eccentric_rect=pygame.Rect(120, 10, 120, 30),
        )

        sim.handle_pointer_event(self._click((15, 15)), None, (15, 15))

        self.assertEqual("Generated generic seed", sim.commit_status)

        sim.handle_pointer_event(self._click((125, 15)), None, (125, 15))

        self.assertEqual("Generated eccentric seed", sim.commit_status)

    def test_crust_density_changes_with_composition(self):
        sim = self._sim()
        baseline_density = estimate_crust_density_kg_m3(sim.crust_composition)

        sim.crust_composition = sim._serializable_crust_composition()
        sim.crust_composition["major_elements"] = [
            {"symbol": "Fe", "name": "Iron", "abundance_percent": 99.0},
        ]
        iron_density = estimate_crust_density_kg_m3(sim.crust_composition)

        self.assertGreater(iron_density, baseline_density)

    def test_planet_physics_derives_mass_and_day_length_from_inputs(self):
        sim = self._sim()
        sim.seed_input_buffers.update({
            "radius_earth": "1",
            "core_radius_fraction": "0.55",
            "crust_thickness_km": "35",
            "angular_velocity_deg_per_hour": "30",
            "water_fraction": "0.5",
        })

        physics = sim._derive_planet_physics()

        self.assertAlmostEqual(12.0, physics["rotation_period_hours"])
        self.assertGreater(physics["mass_earth"], 0.0)
        self.assertGreater(physics["mean_density_kg_m3"], physics["crust_density_kg_m3"])
        self.assertGreater(physics["mantle_radius_fraction"], 0.0)

    def test_atmosphere_model_reflects_retention_and_temperature(self):
        sim = self._sim()
        sim.world_model.loader.entities["planet_blue"] = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "semi_major_axis_m": sim.AU_M,
        }
        sim.selected_world_gen_planet_id = "planet_blue"

        atmosphere = sim._derive_atmosphere_model()
        retention = {row["molecule"]: row for row in atmosphere["retention"]}

        self.assertGreater(atmosphere["estimated_surface_temperature_k"], atmosphere["equilibrium_temperature_k"])
        self.assertIn(retention["H2"]["status"], {"lost", "leaky"})
        self.assertEqual("stable", retention["N2"]["status"])
        self.assertNotEqual(1.0, round(atmosphere["surface_pressure_bar"], 6))
        self.assertLessEqual(atmosphere["surface_pressure_bar"], atmosphere["volatile_supply_bar"] * 2.0)
        self.assertGreaterEqual(atmosphere["retained_column_fraction"], 0.0)
        self.assertIn("composition", atmosphere)

    def test_dry_rocky_atmosphere_is_not_earthlike_by_default(self):
        sim = self._sim()
        sim.seed_input_buffers.update({
            "radius_earth": "0.7",
            "core_radius_fraction": "0.42",
            "crust_thickness_km": "45",
            "angular_velocity_deg_per_hour": "11",
            "water_fraction": "0",
            "volatile_inventory": "dry",
            "tectonics_mode": "stagnant_lid",
        })

        atmosphere = sim._derive_atmosphere_model()
        composition = {row["molecule"]: row["fraction"] for row in atmosphere["composition"]}

        self.assertEqual("dry_co2", atmosphere["atmosphere_class"])
        self.assertTrue(atmosphere["has_solid_surface"])
        self.assertGreater(composition.get("CO2", 0.0), composition.get("N2", 0.0))
        self.assertLess(composition.get("O2", 0.0), 0.01)

    def test_gas_giant_atmosphere_keeps_hydrogen_helium_envelope(self):
        sim = self._sim()
        sim.world_model.loader.entities["planet_jove"] = {
            "id": "planet_jove",
            "name": "Jove",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
            "semi_major_axis_m": 5.2 * sim.AU_M,
        }
        sim.selected_world_gen_planet_id = "planet_jove"
        sim.seed_input_buffers.update({
            "radius_earth": "9.5",
            "core_radius_fraction": "0.12",
            "crust_thickness_km": "5",
            "angular_velocity_deg_per_hour": "36",
            "water_fraction": "0.05",
            "volatile_inventory": "dense",
            "tectonics_mode": "unknown",
        })

        self.assertTrue(sim._save_atmosphere_model())
        atmosphere = sim.world_model.loader.entities["planet_jove"]["atmosphere_model"]
        summary = sim.world_model.loader.entities["planet_jove"]["atmosphere_summary"]
        composition = {row["molecule"]: row["fraction"] for row in atmosphere["composition"]}

        self.assertEqual("gas_giant", atmosphere["atmosphere_class"])
        self.assertFalse(atmosphere["has_solid_surface"])
        self.assertGreater(composition.get("H2", 0.0), 0.7)
        self.assertGreater(composition.get("He", 0.0), 0.1)
        self.assertEqual("gas_giant", summary["atmosphere_class"])
        self.assertFalse(summary["has_solid_surface"])

    def test_regime_model_allows_earthlike_erosion_and_reduces_craters(self):
        seed = {
            "radius_earth": 1.0,
            "core_radius_fraction": 0.55,
            "crust_thickness_km": 35.0,
            "water_fraction": 0.7,
            "volatile_inventory": "earthlike",
            "tectonics_mode": "unknown",
        }
        physics = {
            "radius_earth": 1.0,
            "core_radius_fraction": 0.55,
            "mantle_radius_fraction": 0.4445,
            "crust_radius_fraction": 0.0055,
            "crust_thickness_km": 35.0,
            "surface_gravity_g": 1.0,
        }
        atmosphere = {
            "surface_pressure_bar": 1.0,
            "estimated_surface_temperature_k": 288.0,
        }

        regime = derive_interior_regime_model(seed, physics, atmosphere, crust_type="silicate")

        self.assertEqual("plate_tectonics", regime["interior"]["tectonic_regime"])
        self.assertEqual("active", regime["surface_processes"]["hydrologic_cycle"])
        self.assertEqual("low", regime["surface_processes"]["crater_retention"])
        self.assertIn("fluvial", regime["surface_processes"]["erosion_processes"])

    def test_regime_model_preserves_cratered_airless_surfaces(self):
        seed = {
            "radius_earth": 0.25,
            "core_radius_fraction": 0.0,
            "crust_thickness_km": 120.0,
            "water_fraction": 0.0,
            "volatile_inventory": "none",
            "tectonics_mode": "unknown",
        }
        physics = {
            "radius_earth": 0.25,
            "core_radius_fraction": 0.0,
            "mantle_radius_fraction": 0.0,
            "crust_radius_fraction": 0.45,
            "crust_thickness_km": 120.0,
            "surface_gravity_g": 0.15,
        }
        atmosphere = {
            "surface_pressure_bar": 0.0,
            "estimated_surface_temperature_k": 220.0,
        }

        regime = derive_interior_regime_model(seed, physics, atmosphere, crust_type="basaltic")

        self.assertEqual("inactive", regime["interior"]["tectonic_regime"])
        self.assertFalse(regime["interior"]["mantle_present"])
        self.assertEqual("none", regime["surface_processes"]["hydrologic_cycle"])
        self.assertEqual("high", regime["surface_processes"]["crater_retention"])
        self.assertIn("impact_gardening", regime["surface_processes"]["erosion_processes"])

    def test_terrain_seed_reflects_plate_tectonics_and_hydrology(self):
        seed = {
            "radius_earth": 1.0,
            "core_radius_fraction": 0.55,
            "crust_thickness_km": 35.0,
            "water_fraction": 0.7,
            "volatile_inventory": "earthlike",
            "tectonics_mode": "unknown",
        }
        physics = {
            "radius_m": 6_371_000.0,
            "radius_earth": 1.0,
            "core_radius_fraction": 0.55,
            "mantle_radius_fraction": 0.4445,
            "crust_radius_fraction": 0.0055,
            "crust_thickness_km": 35.0,
            "surface_gravity_g": 1.0,
        }
        atmosphere = {
            "surface_pressure_bar": 1.0,
            "estimated_surface_temperature_k": 288.0,
        }
        regime = derive_interior_regime_model(seed, physics, atmosphere, crust_type="silicate")

        terrain = derive_terrain_seed_model(seed, physics, atmosphere, regime)

        self.assertTrue(terrain["tectonics"]["enabled"])
        self.assertGreaterEqual(terrain["tectonics"]["plate_count"], 3)
        self.assertEqual("active", terrain["hydrology"]["cycle"])
        self.assertTrue(terrain["hydrology"]["drainage_enabled"])
        self.assertGreater(terrain["hydrology"]["target_ocean_fraction"], 0.0)
        self.assertIn("tectonic_boundaries", [layer["id"] for layer in terrain["map_layers"]])
        self.assertIn("water_mask", [layer["id"] for layer in terrain["map_layers"]])

    def test_terrain_seed_reflects_airless_cratered_surface(self):
        seed = {
            "radius_earth": 0.25,
            "core_radius_fraction": 0.0,
            "crust_thickness_km": 120.0,
            "water_fraction": 0.0,
            "volatile_inventory": "none",
            "tectonics_mode": "unknown",
        }
        physics = {
            "radius_m": 1_592_750.0,
            "radius_earth": 0.25,
            "core_radius_fraction": 0.0,
            "mantle_radius_fraction": 0.0,
            "crust_radius_fraction": 0.45,
            "crust_thickness_km": 120.0,
            "surface_gravity_g": 0.15,
        }
        atmosphere = {
            "surface_pressure_bar": 0.0,
            "estimated_surface_temperature_k": 220.0,
        }
        regime = derive_interior_regime_model(seed, physics, atmosphere, crust_type="basaltic")

        terrain = derive_terrain_seed_model(seed, physics, atmosphere, regime)

        self.assertFalse(terrain["tectonics"]["enabled"])
        self.assertEqual(0, terrain["tectonics"]["plate_count"])
        self.assertEqual("none", terrain["hydrology"]["cycle"])
        self.assertFalse(terrain["hydrology"]["drainage_enabled"])
        self.assertGreater(terrain["cratering"]["density"], 0.6)
        self.assertEqual("impact_basin_relief", terrain["heightfield"]["relief_driver"])
        self.assertIn("crater_population", [layer["id"] for layer in terrain["map_layers"]])

    def test_heightmap_model_is_chunked_and_samples_elevation(self):
        seed = {
            "radius_earth": 1.0,
            "core_radius_fraction": 0.55,
            "crust_thickness_km": 35.0,
            "water_fraction": 0.7,
            "volatile_inventory": "earthlike",
            "tectonics_mode": "unknown",
        }
        physics = {
            "radius_m": 6_371_000.0,
            "radius_earth": 1.0,
            "core_radius_fraction": 0.55,
            "mantle_radius_fraction": 0.4445,
            "crust_radius_fraction": 0.0055,
            "crust_thickness_km": 35.0,
            "surface_gravity_g": 1.0,
        }
        atmosphere = {
            "surface_pressure_bar": 1.0,
            "estimated_surface_temperature_k": 288.0,
        }
        regime = derive_interior_regime_model(seed, physics, atmosphere, crust_type="silicate")
        terrain = derive_terrain_seed_model(seed, physics, atmosphere, regime)

        heightmap = derive_heightmap_model(terrain, seed, physics, planet_id="planet_blue")

        self.assertEqual("heightmap_seeded", heightmap["status"])
        self.assertEqual("equirectangular", heightmap["projection"])
        self.assertTrue(heightmap["spherical_body"])
        self.assertTrue(heightmap["wrap_x"])
        self.assertFalse(heightmap["wrap_y"])
        self.assertEqual("longitude_wrap_latitude_clamp", heightmap["edge_policy"])
        self.assertEqual("chunked_heightfield_seed", heightmap["storage"]["kind"])
        self.assertEqual("longitude_wrap_latitude_clamp", heightmap["storage"]["edge_policy"])
        self.assertEqual(8, heightmap["storage"]["chunk_cols"])
        self.assertEqual(4, heightmap["storage"]["chunk_rows"])
        self.assertEqual(65, heightmap["sample_grid"]["width"])
        self.assertEqual(33, heightmap["sample_grid"]["height"])
        self.assertTrue(heightmap["sample_grid"]["wrap_x"])
        self.assertEqual(33, len(heightmap["sample_grid"]["rows"]))
        self.assertEqual(65, len(heightmap["sample_grid"]["rows"][0]))
        for row in heightmap["sample_grid"]["rows"]:
            self.assertEqual(row[0], row[-1])
        sample_values = [
            value
            for row in heightmap["sample_grid"]["rows"]
            for value in row
        ]
        self.assertGreater(max(sample_values), min(sample_values))
        self.assertGreaterEqual(min(sample_values), heightmap["min_elevation_m"])
        self.assertLessEqual(max(sample_values), heightmap["max_elevation_m"])
        self.assertGreater(heightmap["hypsometry_summary"]["broad_plain_fraction"], 0.55)
        self.assertLess(heightmap["hypsometry_summary"]["mountain_fraction_above_2000m"], 0.18)

    def test_material_heatmap_generator_writes_png_layers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_root = Path(temp_dir)
            heightmap = {
                "status": "heightmap_seeded",
                "planet_id": "planet_blue",
                "map_seed": "heatmap-test",
                "projection": "equirectangular",
                "wrap_x": True,
                "wrap_y": False,
                "min_elevation_m": -1000.0,
                "max_elevation_m": 2000.0,
                "sea_level_m": 0.0,
                "sample_grid": {
                    "width": 3,
                    "height": 3,
                    "rows": [
                        [-500.0, 900.0, -500.0],
                        [100.0, 1600.0, 100.0],
                        [-300.0, 700.0, -300.0],
                    ],
                },
            }
            natural_material_model = {
                "planet_tags": ["active_hydrology", "weathered_surface", "basaltic_surface"],
                "likely_materials": [
                    {
                        "material_id": "mat_basalt",
                        "name": "Basalt",
                        "confidence": 0.82,
                        "display_color": [72, 76, 70],
                        "evidence_tags": ["basaltic_surface"],
                    },
                    {
                        "material_id": "mat_clay_rich_regolith",
                        "name": "Clay-Rich Regolith",
                        "confidence": 0.66,
                        "display_color": [132, 118, 92],
                        "evidence_tags": ["active_hydrology", "weathered_surface"],
                    },
                ],
            }

            model = generate_material_heatmap_model(
                planet={"id": "planet_blue"},
                natural_material_model=natural_material_model,
                terrain={"map_seed": "heatmap-test", "hydrology": {"cycle": "active", "target_ocean_fraction": 0.35}},
                heightmap=heightmap,
                output_root=storage_root / "assets" / "maps" / "material_heatmaps",
                storage_root=storage_root,
                image_size=(32, 16),
            )

            self.assertEqual("generated", model["status"])
            self.assertEqual("png", model["image_format"])
            self.assertEqual("deterministic_generated_truth", model["truth_model"])
            self.assertEqual("inferred", model["default_confidence_state"])
            self.assertEqual(2, len(model["layers"]))
            self.assertTrue((storage_root / model["composite_layer"]["image_path"]).exists())
            for layer in model["layers"]:
                self.assertTrue((storage_root / layer["image_path"]).exists())

    def test_solid_worldgen_adds_material_heatmap_metadata_after_heightmap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            world_model = FakeWorldModel(entries_directory=temp_dir)
            sim = WorldGenSimulation(
                world_model=world_model,
                parent_system_id="system_alpha",
                year=2400,
            )
            planet = {
                "id": "planet_blue",
                "name": "Blue",
                "type": "location",
                "_dataset": "locations",
                "location_class": "planet",
                "star_system": "system_alpha",
                "semi_major_axis_m": sim.AU_M,
                "tags": ["world_gen_candidate"],
            }
            world_model.loader.entities["planet_blue"] = planet
            world_model.loader.datasets["locations"].append(planet)
            sim.selected_world_gen_planet_id = "planet_blue"
            sim.seed_input_buffers.update({
                "radius_earth": "0.35",
                "core_radius_fraction": "0.2",
                "crust_thickness_km": "80",
                "angular_velocity_deg_per_hour": "9",
                "water_fraction": "0.0",
                "volatile_inventory": "none",
                "tectonics_mode": "inactive",
            })
            sim._save_selected_planet_seed()
            sim._save_atmosphere_model()
            sim._save_interior_regime_model()

            self.assertTrue(sim._save_terrain_seed_model())

            heatmap_model = planet.get("material_heatmap_model")
            self.assertIsInstance(heatmap_model, dict)
            self.assertEqual("generated", heatmap_model["status"])
            self.assertGreaterEqual(len(heatmap_model["layers"]), 1)
            self.assertNotIn("material_heatmaps", world_model.loader.datasets)
            self.assertEqual("generated", planet["materials_summary"]["heatmap_status"])
            self.assertTrue((Path(temp_dir) / heatmap_model["composite_layer"]["image_path"]).exists())

    def test_height_marker_interval_gets_finer_with_zoom(self):
        self.assertEqual(100, height_marker_interval_m(0.1))
        self.assertEqual(50, height_marker_interval_m(0.5))
        self.assertEqual(10, height_marker_interval_m(2.0))
        self.assertEqual(1, height_marker_interval_m(12.0))

    def test_heightmap_contour_display_is_capped_for_performance(self):
        heightmap = {
            "min_elevation_m": -4775,
            "max_elevation_m": 6271,
            "sea_level_m": 0,
        }

        interval = display_contour_interval_m(heightmap, 20, max_levels=18)
        levels = contour_levels_for_heightmap(heightmap, 20, max_levels=18)

        self.assertGreaterEqual(interval, 500)
        self.assertLessEqual(len(levels), 18)

    def test_heightmap_preview_consumes_wheel_inside_preview(self):
        sim = self._sim()
        planet = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
        }
        sim.world_model.loader.entities["planet_blue"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_blue"
        sim.editor_stage = "heightmap"
        sim.set_heightmap_preview_rect(pygame.Rect(10, 10, 100, 80))

        handled = sim.handle_pre_camera_event(
            SimpleNamespace(type=pygame.MOUSEWHEEL, y=1, pos=(30, 30))
        )

        self.assertTrue(handled)
        self.assertGreater(sim.heightmap_preview_zoom, 1.0)

    def test_heightmap_preview_does_not_consume_wheel_outside_preview(self):
        sim = self._sim()
        planet = {
            "id": "planet_blue",
            "name": "Blue",
            "type": "location",
            "_dataset": "locations",
            "location_class": "planet",
            "star_system": "system_alpha",
        }
        sim.world_model.loader.entities["planet_blue"] = planet
        sim.world_model.loader.datasets["locations"].append(planet)
        sim.selected_world_gen_planet_id = "planet_blue"
        sim.editor_stage = "heightmap"
        sim.set_heightmap_preview_rect(pygame.Rect(10, 10, 100, 80))

        handled = sim.handle_pre_camera_event(
            SimpleNamespace(type=pygame.MOUSEWHEEL, y=1, pos=(300, 300))
        )

        self.assertFalse(handled)
        self.assertEqual(1.0, sim.heightmap_preview_zoom)


if __name__ == "__main__":
    unittest.main()
