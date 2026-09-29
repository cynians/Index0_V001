import unittest
from types import SimpleNamespace

from app.navigation_controller import NavigationController
from simulations.map.map_simulation import MapSimulation
from simulations.space.space_simulation import SpaceSimulation


class FakeWorldModel:
    def __init__(self, entities):
        self.entities = {entity["id"]: entity for entity in entities}

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)


class SimulationSelectionInspectorTests(unittest.TestCase):
    def test_map_inspector_text_save_uses_partial_persistence(self):
        entity = {
            "id": "loc_test_region",
            "pretty_name": "Old name",
            "name": "Old name",
            "wiki_entry": "Old notes",
            "type": "location",
            "location_class": "region",
        }
        partial_writes = []

        class Loader:
            entities = {entity["id"]: entity}

            @staticmethod
            def persist_entity_fields(candidate, field_names):
                partial_writes.append((candidate["id"], set(field_names)))
                return True

            @staticmethod
            def persist_entity(*_args, **_kwargs):
                raise AssertionError("Inspector text edits must not replace the full entity")

        sim = MapSimulation.__new__(MapSimulation)
        sim.world_model = SimpleNamespace(loader=Loader())

        self.assertTrue(sim._update_repository_entity_fields(
            entity["id"],
            {
                "pretty_name": "New name",
                "name": "New name",
                "wiki_entry": "New notes",
            },
        ))

        self.assertEqual(
            [(entity["id"], {"pretty_name", "name", "wiki_entry"})],
            partial_writes,
        )
        self.assertEqual("New name", entity["name"])
        self.assertEqual("New notes", entity["wiki_entry"])

    def test_map_inspector_save_does_not_reload_world_model(self):
        sim = MapSimulation.__new__(MapSimulation)
        notifications = []
        invalidations = []
        sim.world_model = SimpleNamespace(
            refresh=lambda: (_ for _ in ()).throw(
                AssertionError("Inspector text save must not reload the world model")
            ),
        )
        sim._can_open_location_inspector = lambda _target_id: True
        sim._update_location_text_fields = (
            lambda target_id, name, notes: notifications.append(
                ("write", target_id, name, notes)
            ) or True
        )
        sim._notify_incremental_repository_change = (
            lambda **kwargs: notifications.append(
                ("notify", kwargs.get("rebuild_relations"))
            )
        )
        sim._invalidate_layer_cache = lambda: invalidations.append(True)

        self.assertTrue(sim.save_selection_inspector_updates(
            "location",
            "loc_test_region",
            {"name": "New name", "wiki_entry": "New notes"},
        ))

        self.assertEqual(
            [
                ("write", "loc_test_region", "New name", "New notes"),
                ("notify", False),
            ],
            notifications,
        )
        self.assertEqual([True], invalidations)

    def test_map_selection_exposes_repository_backed_payload(self):
        entity = {
            "id": "loc_test_region",
            "pretty_name": "Test Region",
            "type": "location",
            "location_class": "region",
            "start_year": 120,
        }
        sim = MapSimulation.__new__(MapSimulation)
        sim.world_model = FakeWorldModel([entity])
        sim.selected_entity_id = entity["id"]
        sim.selected_spatial_feature_id = None
        sim.get_active_layer_label = lambda: "Locations"

        payload = sim.get_selection_inspector_payload()

        self.assertEqual("loc_test_region", payload["entity_id"])
        self.assertEqual("Test Region", payload["title"])
        self.assertIn("Class: region", payload["details"])
        self.assertEqual("open_selection_wiki", payload["actions"][0]["id"])

    def test_virtual_map_selection_has_no_wiki_action(self):
        sim = MapSimulation.__new__(MapSimulation)
        sim.world_model = FakeWorldModel([])
        sim.selected_entity_id = None
        sim.selected_spatial_feature_id = "virtual:ecoregions"
        sim.get_active_layer_label = lambda: "Ecoregions"

        payload = sim.get_selection_inspector_payload()

        self.assertIsNone(payload["entity_id"])
        self.assertEqual([], payload["actions"])

    def test_space_selection_exposes_source_entity(self):
        entity = {
            "id": "system_test_planet",
            "name": "Test Planet",
            "type": "system",
            "body_class": "planet",
        }
        sim = SpaceSimulation.__new__(SpaceSimulation)
        sim.get_selected_body_entity = lambda: entity

        payload = sim.get_selection_inspector_payload()

        self.assertEqual("system_test_planet", payload["entity_id"])
        self.assertEqual("Space body", payload["kind"])
        self.assertIn("Class: planet", payload["details"])

    def test_open_wiki_action_focuses_selected_repository_entry(self):
        entity = {"id": "loc_test_region", "name": "Test Region"}
        world_model = FakeWorldModel([entity])
        app = SimpleNamespace(
            world_model=world_model,
            repository_scope_entity_id=None,
            knowledge_layer_active=False,
            repository_return_confirm_active=True,
            system_menu_active=True,
            system_settings_active=True,
        )
        controller = NavigationController(app)
        sim = SimpleNamespace(
            get_selection_inspector_payload=lambda: {"entity_id": entity["id"]},
        )

        handled = controller.handle_ui_action("open_selection_wiki", sim)

        self.assertTrue(handled)
        self.assertEqual("loc_test_region", app.repository_scope_entity_id)
        self.assertTrue(app.knowledge_layer_active)
        self.assertFalse(app.repository_return_confirm_active)
        self.assertFalse(app.system_menu_active)


if __name__ == "__main__":
    unittest.main()
