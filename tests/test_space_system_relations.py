import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from app.navigation_controller import NavigationController
from simulations.space.space_simulation import SpaceSimulation
from simulations.space.system import CelestialSystem


def location(entity_id, class_key, **fields):
    return {"id": entity_id, "name": entity_id, "type": "location",
            "_dataset": "locations", "location_class": class_key, **fields}


def world_with(*entities, aliases=None):
    loader = SimpleNamespace(entities={entity["id"]: entity for entity in entities},
                             entity_aliases=aliases or {})
    return SimpleNamespace(loader=loader, get_entity=lambda key: loader.entities.get(key),
                           get_entities_by_dataset=lambda dataset: list(loader.entities.values()))


class SpaceSystemRelationTests(unittest.TestCase):
    def test_empty_system_launch_ignores_unrelated_list_relations(self):
        world = world_with(
            location("system_empty", "star_system"),
            location("loc_unassigned", "planet", system_role="orbital_body", star_system=[]),
            location("star_other", "star", star_system=["system_other"]),
        )
        simulation = SpaceSimulation(world, root_system_id="system_empty")
        self.assertEqual([], simulation.system.get_entries())

    def test_list_and_dictionary_relations_resolve_aliases_and_orbital_parents(self):
        world = world_with(
            location("system_alpha", "star_system"),
            location("star_alpha", "star", star_system=[{"id": "legacy_alpha"}],
                     parent_location=["system_alpha"], parent_body=[]),
            location("planet_alpha", "planet", star_system=["system_alpha"],
                     parent_body=[{"id": "star_alpha"}], semi_major_axis_m=1.5e11),
            location("moon_alpha", "moon", star_system={"id": "system_alpha"},
                     parent_body=["planet_alpha"], semi_major_axis_m=4e8),
            aliases={"legacy_alpha": "system_alpha"},
        )
        simulation = SpaceSimulation(world, root_system_id="system_alpha")
        objects = simulation.system.objects_by_id
        self.assertEqual({"star_alpha", "planet_alpha", "moon_alpha"}, set(objects))
        self.assertIs(objects["star_alpha"], objects["planet_alpha"].orbit.parent)
        self.assertIs(objects["planet_alpha"], objects["moon_alpha"].orbit.parent)

        local = SpaceSimulation(world, root_system_id="system_alpha", root_body_id="planet_alpha")
        self.assertEqual({"planet_alpha", "moon_alpha"}, set(local.system.objects_by_id))

    def test_system_membership_checks_all_relation_targets(self):
        world = world_with(location("star_alpha", "star",
                                    star_system=["system_other", "system_alpha"]))
        bodies = CelestialSystem()._get_active_system_entities(world, 2400, "system_alpha")
        self.assertEqual(["star_alpha"], [body["id"] for body in bodies])

    def test_navigation_passes_a_single_system_id_from_a_link_list(self):
        world = world_with(location("star_alpha", "star", star_system=["system_alpha"]))
        navigation = NavigationController(SimpleNamespace(world_model=world))
        navigation.launch_space_root_tab = Mock()
        self.assertTrue(navigation.launch_entity_mode("star_alpha", "space"))
        navigation.launch_space_root_tab.assert_called_once_with("system_alpha")
