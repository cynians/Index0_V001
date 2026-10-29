import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from app.launch_affordance_resolver import LaunchAffordanceResolver
from simulations.pop.pop_simulation import PopSimulation
from ui.ui_manager import UIManager


class _World:
    def __init__(self, entities):
        self.entities = {entity["id"]: entity for entity in entities}

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_dataset(self, dataset_name):
        return [entity for entity in self.entities.values() if entity.get("_dataset") == dataset_name]


class PopSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def setUp(self):
        self.world = _World([
            {
                "id": "pop_city_x", "_dataset": "pops", "type": "pop",
                "name": "City X Residents", "pop_type": "location",
                "population_count": 1000,
                "age_distribution": {"mean_age": 40, "stddev": 15, "min_age": 0, "max_age": 90},
                "sex_ratio": 0.5,
            },
            {
                "id": "pop_german_culture_city_x", "_dataset": "pops", "type": "pop",
                "name": "German Culture (City X)", "pop_type": "cultural",
                "population_count": 600,
            },
            {
                "id": "pop_interstellar_workplain", "_dataset": "pops", "type": "pop",
                "name": "Interstellar Workplain Culture", "pop_type": "cultural",
                "population_count": 5000,
            },
            {
                "id": "pop_factory_workers", "_dataset": "pops", "type": "pop",
                "name": "Factory Workers", "pop_type": "employment",
            },
            {
                "id": "pop_city_x_factory_workers", "_dataset": "pops", "type": "pop",
                "name": "City X Factory Workers", "pop_type": "employment",
                "parent_pop": "pop_factory_workers",
                "employer": "producer_city_x_factory",
                "source_allocations": [
                    {"source_pop": "pop_german_culture_city_x", "count": 324},
                    {"source_pop": "pop_interstellar_workplain", "count": 100},
                ],
                "age_distribution": {"mean_age": 34, "stddev": 10, "min_age": 18, "max_age": 60},
                "sex_ratio": 0.45,
            },
            {
                "id": "producer_city_x_factory", "_dataset": "producers", "type": "producer",
                "name": "City X Factory",
            },
        ])

    def test_location_pop_uses_authored_count_not_derived(self):
        sim = PopSimulation(self.world, "pop_city_x")
        self.assertEqual(1000, sim.derived_population_count(sim.get_pop()))
        model = sim.get_population_panel_model()
        self.assertFalse(model["is_derived_count"])
        self.assertEqual([], model["composition"])

    def test_employment_pop_count_is_derived_and_never_double_counts(self):
        sim = PopSimulation(self.world, "pop_city_x_factory_workers")
        pop = sim.get_pop()
        # 424 total, derived purely from source_allocations -- population_count
        # was never authored on this pop at all.
        self.assertEqual(424, sim.derived_population_count(pop))
        self.assertNotIn("population_count", pop)

        model = sim.get_population_panel_model()
        self.assertTrue(model["is_derived_count"])
        self.assertEqual(424, model["total_population"])
        self.assertEqual("City X Factory", model["employer_label"])
        self.assertEqual("pop_factory_workers", model["parent_pop"]["id"])

    def test_composition_breakdown_matches_source_allocations(self):
        sim = PopSimulation(self.world, "pop_city_x_factory_workers")
        composition = sim.resolve_composition()
        by_id = {row["source_pop_id"]: row for row in composition}
        self.assertEqual(324, by_id["pop_german_culture_city_x"]["count"])
        self.assertEqual("German Culture (City X)", by_id["pop_german_culture_city_x"]["label"])
        self.assertAlmostEqual(324 / 424, by_id["pop_german_culture_city_x"]["fraction"])
        self.assertEqual(100, by_id["pop_interstellar_workplain"]["count"])

    def test_nested_children_found_via_parent_pop(self):
        sim = PopSimulation(self.world, "pop_factory_workers")
        children = sim.nested_children()
        self.assertEqual(1, len(children))
        self.assertEqual("pop_city_x_factory_workers", children[0]["id"])
        self.assertEqual(424, children[0]["total_population"])

    def test_age_buckets_sum_close_to_total_population(self):
        sim = PopSimulation(self.world, "pop_city_x_factory_workers")
        model = sim.get_population_panel_model()
        bucket_total = sum(bucket["count"] for bucket in model["age_buckets"])
        # Rounding per-bucket means this won't be exact, but should be close.
        self.assertLessEqual(abs(bucket_total - model["total_population"]), 3)

    def test_launch_affordance_offers_pop_mode(self):
        options = LaunchAffordanceResolver().options_for_entity(self.world.get_entity("pop_city_x"))
        self.assertEqual(["pop"], [option["mode"] for option in options])

    def test_pop_view_renders_without_crashing(self):
        # Regression-style coverage matching the floating-card lesson: drive
        # the real UIManager rebuild/draw path, not just the model method.
        sim = PopSimulation(self.world, "pop_city_x_factory_workers")
        ui = UIManager()
        ui.rebuild_for_state(sim, 1200, 800, world_model=self.world)
        self.assertTrue(ui.pop_ui_active)
        self.assertIsNotNone(ui.pop_panel_model)

        screen = pygame.Surface((1200, 800))
        font = pygame.font.SysFont("consolas", 14)
        ui.draw(screen, font)  # must not raise


if __name__ == "__main__":
    unittest.main()
