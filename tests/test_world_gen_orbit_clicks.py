import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pygame
import yaml

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
            self.assertEqual("star_alpha", planet["parent_body"])
            self.assertEqual(1.5 * sim.AU_M, planet["semi_major_axis_m"])
            self.assertAlmostEqual(1.0 / 3.0, planet["eccentricity"])
            self.assertTrue(world_model.loader.reference_graph_rebuilt)
            self.assertTrue(world_model.touch_degrees.refreshed)

            locations_path = Path(temp_dir) / "locations.yaml"
            data = yaml.safe_load(locations_path.read_text(encoding="utf-8"))
            self.assertEqual("planet_blue", data[-1]["id"])


if __name__ == "__main__":
    unittest.main()
