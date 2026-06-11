import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pygame
import yaml

from app.input_router import InputRouter
from simulations.world_gen.crust import MAJOR_CRUST_TARGET_PERCENT, estimate_crust_density_kg_m3
from simulations.world_gen.heightmap import (
    contour_levels_for_heightmap,
    derive_heightmap_model,
    display_contour_interval_m,
    height_marker_interval_m,
)
from simulations.world_gen.interior_regime import derive_interior_regime_model
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
            entity for entity in self.entities.values()
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
            self.assertEqual(1.5 * sim.AU_M, planet["semi_major_axis_m"])
            self.assertAlmostEqual(1.0 / 3.0, planet["eccentricity"])
            self.assertIn("orbit_locked", planet["tags"])
            self.assertEqual("orbit_locked", planet["environment_summary"]["status"])
            self.assertIn(planet, sim._active_system_bodies())
            self.assertTrue(world_model.loader.reference_graph_rebuilt)
            self.assertTrue(world_model.touch_degrees.refreshed)

            locations_path = Path(temp_dir) / "locations.yaml"
            data = yaml.safe_load(locations_path.read_text(encoding="utf-8"))
            self.assertEqual("planet_blue", data[-1]["id"])

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
