import unittest

from ui.card import EntityCard
from ui.knowledge_browser_ui import KnowledgeBrowserUI


class VehicleClassRelationTests(unittest.TestCase):
    def test_vehicle_schema_adds_class_relation_section(self):
        card = EntityCard(
            {
                "id": "veh_test",
                "pretty_name": "Test Vehicle",
                "type": "vehicle",
                "_dataset": "vehicles",
                "vehicle_class": "ground_vehicle",
            },
            dataset_name="vehicles",
        )

        sections = card._sectioned_fields()
        class_relation_keys = [key for key, _ in sections["Class Relations"]]
        card.set_active_tab("relations")

        self.assertEqual(["operators", "markets", "producers"], class_relation_keys)
        self.assertIn("Class Relations", card._visible_sections())

    def test_vehicle_operator_target_accepts_multiple_classes(self):
        ui = KnowledgeBrowserUI()
        target = ["factions", "institutions", "formations"]

        self.assertTrue(ui._entity_matches_relation_target({"_dataset": "factions"}, target))
        self.assertTrue(ui._entity_matches_relation_target({"_dataset": "institutions"}, target))
        self.assertTrue(ui._entity_matches_relation_target({"_dataset": "formations"}, target))
        self.assertFalse(ui._entity_matches_relation_target({"_dataset": "markets"}, target))
        self.assertEqual("all", ui._relation_target_dataset_filter(target))

    def test_template_picker_context_restricts_relation_target(self):
        ui = KnowledgeBrowserUI.__new__(KnowledgeBrowserUI)
        ui.world_model = None
        ui.schema_entry_templates = [
            {"dataset_name": "ideas", "entity_type": "idea", "schema_name": "idea", "label": "Idea"},
            {"dataset_name": "locations", "entity_type": "location", "schema_name": "location", "label": "Location"},
            {"dataset_name": "events", "entity_type": "event", "schema_name": "event", "label": "Event"},
        ]
        ui.template_picker_mode = "create"
        ui.template_picker_context = {"target": "locations"}
        ui.template_picker_search_query = ""

        visible_templates = ui._filtered_template_picker_templates()

        self.assertTrue(visible_templates)
        self.assertTrue(all(template.get("dataset_name") == "locations" for template in visible_templates))
        self.assertEqual([], ui._template_picker_quick_templates())


if __name__ == "__main__":
    unittest.main()
