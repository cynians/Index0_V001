import unittest
from types import SimpleNamespace

import pygame

from ui.knowledge_browser_model import KnowledgeBrowserModel
from ui.knowledge_browser_ui import KnowledgeBrowserUI


class CardTypePickerTests(unittest.TestCase):
    def _world_model_with(self, datasets):
        loader = SimpleNamespace(datasets=datasets, entities={})
        for entities in datasets.values():
            for entity in entities:
                loader.entities[entity["id"]] = entity
        return SimpleNamespace(
            loader=loader,
            get_entity=lambda entity_id: loader.entities.get(entity_id),
            get_entities_by_dataset=lambda dataset_name: loader.datasets.get(dataset_name, []),
            get_dataset_names=lambda: list(loader.datasets.keys()),
        )

    def test_conversion_templates_include_every_schema_template(self):
        ui = KnowledgeBrowserUI()
        self.assertIsInstance(ui._browser_model(), KnowledgeBrowserModel)
        ui.schema_entry_templates = [
            {"dataset_name": "ideas", "label": "Idea"},
            {"dataset_name": "vehicles", "label": "Vehicle"},
            {"dataset_name": "materials", "label": "Material"},
        ]

        dataset_names = [template["dataset_name"] for template in ui._conversion_templates()]

        self.assertIn("ideas", dataset_names)
        self.assertCountEqual(["ideas", "vehicles", "materials"], dataset_names)

    def test_card_type_picker_scrolls_past_first_eight_templates(self):
        ui = KnowledgeBrowserUI()
        templates = [
            {"dataset_name": f"dataset_{index}", "label": f"Template {index}"}
            for index in range(12)
        ]
        card = {
            "rect": pygame.Rect(0, 0, 320, 170),
            "type_label_rect": pygame.Rect(12, 28, 220, 18),
            "type_picker_scroll": 8,
        }

        visible, scroll, max_scroll = ui._card_type_picker_visible_templates(card, templates)

        self.assertGreater(max_scroll, 0)
        self.assertEqual(8, scroll)
        self.assertEqual(templates[8:10], visible)

    def test_conversion_templates_include_existing_location_subclasses(self):
        ui = KnowledgeBrowserUI()
        ui.schema_entry_templates = [
            {
                "dataset_name": "locations",
                "entity_type": "location",
                "label": "Location",
                "id_prefix": "loc",
            }
        ]
        ui.world_model = SimpleNamespace(
            get_entities_by_dataset=lambda dataset_name: [
                {
                    "id": "planet_earth",
                    "type": "location",
                    "_dataset": "locations",
                    "location_class": "planet",
                }
            ] if dataset_name == "locations" else []
        )

        templates = ui._conversion_templates()
        planet_template = next(
            template
            for template in templates
            if template.get("subclass_field") == "location_class"
            and template.get("subclass_value") == "planet"
        )

        self.assertEqual("Planet", planet_template["label"])
        self.assertEqual({"location_class": "planet"}, planet_template["initial_fields"])

    def test_conversion_templates_include_canonical_location_classes(self):
        ui = KnowledgeBrowserUI()
        ui.schema_entry_templates = [
            {
                "dataset_name": "locations",
                "entity_type": "location",
                "label": "Location",
                "id_prefix": "loc",
            }
        ]
        ui.world_model = None

        templates = ui._conversion_templates()
        subclasses = {
            template.get("subclass_value")
            for template in templates
            if template.get("dataset_name") == "locations"
            and template.get("subclass_field") == "location_class"
        }

        self.assertIn("building", subclasses)
        self.assertIn("room", subclasses)
        self.assertIn("state", subclasses)
        self.assertIn("quarter", subclasses)

    def test_location_subclass_templates_prefer_canonical_location_class(self):
        ui = KnowledgeBrowserUI()
        ui.schema_entry_templates = [
            {
                "dataset_name": "locations",
                "entity_type": "location",
                "label": "Location",
                "id_prefix": "loc",
            }
        ]
        ui.world_model = SimpleNamespace(
            get_entities_by_dataset=lambda dataset_name: [
                {
                    "id": "planet_earth",
                    "type": "location",
                    "_dataset": "locations",
                    "location_class": "planet",
                    "body_class": "planet",
                    "system_role": "orbital_body",
                }
            ] if dataset_name == "locations" else []
        )

        planet_templates = [
            template
            for template in ui._conversion_templates()
            if template.get("label") == "Planet"
        ]

        self.assertEqual(1, len(planet_templates))
        self.assertEqual("location_class", planet_templates[0].get("subclass_field"))

    def test_template_picker_search_filters_subclass_templates(self):
        ui = KnowledgeBrowserUI()
        ui.schema_entry_templates = [
            {
                "dataset_name": "locations",
                "entity_type": "location",
                "label": "Location",
                "id_prefix": "loc",
            }
        ]
        ui.world_model = SimpleNamespace(
            get_entities_by_dataset=lambda dataset_name: [
                {
                    "id": "planet_earth",
                    "type": "location",
                    "_dataset": "locations",
                    "location_class": "planet",
                },
                {
                    "id": "loc_himalaya",
                    "type": "location",
                    "_dataset": "locations",
                    "location_class": "mountain_range",
                },
            ] if dataset_name == "locations" else []
        )
        ui.template_picker_mode = "convert"
        ui.template_picker_search_query = "planet"

        labels = [template["label"] for template in ui._filtered_template_picker_templates()]

        self.assertIn("Planet", labels)
        self.assertNotIn("Mountain Range", labels)

    def test_template_picker_rows_group_subclasses_under_base_template(self):
        ui = KnowledgeBrowserUI()
        rows = ui._template_picker_hierarchical_rows(
            [
                {
                    "dataset_name": "locations",
                    "entity_type": "location",
                    "label": "Location",
                },
                {
                    "dataset_name": "locations",
                    "entity_type": "location",
                    "label": "Planet",
                    "subclass_field": "location_class",
                    "subclass_value": "planet",
                },
            ]
        )

        self.assertEqual("header", rows[0]["kind"])
        self.assertEqual("Location", rows[0]["label"])
        self.assertEqual(
            ["Location", "Planet"],
            [row["items"][0]["label"] for row in rows[1:]],
        )

    def test_template_picker_rows_pack_short_items_and_wrap_long_items(self):
        ui = KnowledgeBrowserUI()
        rows = ui._template_picker_hierarchical_rows(
            [
                {
                    "dataset_name": "locations",
                    "entity_type": "location",
                    "label": "A",
                    "subclass_field": "location_class",
                    "subclass_value": "a",
                },
                {
                    "dataset_name": "locations",
                    "entity_type": "location",
                    "label": "B",
                    "subclass_field": "location_class",
                    "subclass_value": "b",
                },
                {
                    "dataset_name": "locations",
                    "entity_type": "location",
                    "label": "Itemwithaveryverylongname",
                    "subclass_field": "location_class",
                    "subclass_value": "long",
                },
            ],
            available_width=190,
        )

        item_rows = [row for row in rows if row["kind"] == "template_row"]

        self.assertEqual(["A", "B"], [item["label"] for item in item_rows[0]["items"]])
        self.assertEqual(["Itemwithaveryverylongname"], [item["label"] for item in item_rows[1]["items"]])

    def test_template_picker_has_local_ellipsize_helper(self):
        pygame.font.init()
        ui = KnowledgeBrowserUI()
        font = pygame.font.SysFont("consolas", 14)

        text = ui._ellipsize_text("Itemwithaveryverylongname", font, 48)

        self.assertTrue(text.endswith("..."))
        self.assertLessEqual(font.size(text)[0], 48)

    def test_card_class_click_opens_template_picker_convert_mode(self):
        ui = KnowledgeBrowserUI()
        entity = {
            "id": "idea_seed",
            "type": "idea",
            "_dataset": "ideas",
            "pretty_name": "Seed",
        }
        card = {
            "entity_id": "idea_seed",
            "title": "Seed",
            "card_view": SimpleNamespace(entity=entity),
            "type_picker_open": True,
            "type_picker_hitboxes": [],
            "type_picker_rect": pygame.Rect(0, 0, 10, 10),
        }
        ui.cards = [card]

        self.assertTrue(ui._open_card_class_template_picker(card))

        self.assertTrue(ui.show_template_picker)
        self.assertEqual("convert", ui.template_picker_mode)
        self.assertEqual("idea_seed", ui.template_picker_context.get("entity_id"))
        self.assertIs(card, ui.template_picker_context.get("card"))
        self.assertFalse(card["type_picker_open"])

    def test_template_picker_convert_uses_retained_card_reference(self):
        ui = KnowledgeBrowserUI()
        entity = {
            "id": "idea_seed",
            "type": "idea",
            "_dataset": "ideas",
            "pretty_name": "Seed",
        }
        card = {
            "entity_id": "idea_renamed",
            "title": "Seed",
            "card_view": SimpleNamespace(entity=entity),
        }
        ui.cards = [card]
        ui.template_picker_mode = "convert"
        ui.template_picker_context = {
            "entity_id": "stale_context_id",
            "card": card,
        }
        converted = []
        ui._convert_card_to_template = lambda selected_card, template: converted.append(selected_card) or True

        self.assertTrue(ui._select_template_picker_template({"dataset_name": "ideas"}))

        self.assertEqual([card], converted)

    def test_template_picker_context_survives_layout_reset(self):
        ui = KnowledgeBrowserUI()
        entity = {
            "id": "idea_seed",
            "type": "idea",
            "_dataset": "ideas",
            "pretty_name": "Seed",
        }
        card = {
            "entity_id": "idea_seed",
            "title": "Seed",
            "card_view": SimpleNamespace(entity=entity),
        }
        ui.cards = [card]
        ui.template_picker_mode = "convert"
        ui.template_picker_context = {
            "entity_id": "idea_seed",
            "card": card,
        }
        converted = []
        ui._convert_card_to_template = lambda selected_card, template: converted.append(selected_card) or True

        ui.reset()

        self.assertTrue(ui._select_template_picker_template({"dataset_name": "locations"}))
        self.assertEqual([card], converted)

    def test_subclass_initial_fields_apply_to_created_entry(self):
        ui = KnowledgeBrowserUI()
        ui.world_model = self._world_model_with({"locations": []})
        building_template = {
            "dataset_name": "locations",
            "entity_type": "location",
            "label": "Building",
            "id_prefix": "loc",
            "subclass_field": "location_class",
            "subclass_value": "building",
            "initial_fields": {"location_class": "building"},
        }

        entity = ui._create_template_entity(
            building_template,
            requested_id="loc_test_building",
            initial_fields={"pretty_name": "Test Building", "name": "Test Building"},
        )

        self.assertEqual("locations", entity["_dataset"])
        self.assertEqual("location", entity["type"])
        self.assertEqual("building", entity["location_class"])

    def test_card_reclassification_to_building_keeps_subclass(self):
        ui = KnowledgeBrowserUI()
        entity = {
            "id": "idea_seed",
            "type": "idea",
            "_dataset": "ideas",
            "pretty_name": "Test Building",
            "name": "Test Building",
        }
        ui.world_model = self._world_model_with({"ideas": [entity], "locations": []})
        card = {
            "entity_id": "idea_seed",
            "title": "Test Building",
            "card_view": SimpleNamespace(entity=entity),
            "is_draft_entity": True,
        }
        ui.cards = [card]
        ui._save_card_draft = lambda selected_card: True
        ui._build_browser_items = lambda world_model: []
        ui._refresh_timeline_items = lambda: None
        ui._rebuild_browser_hitboxes = lambda: None
        ui._relayout_cards = lambda: None
        building_template = {
            "dataset_name": "locations",
            "entity_type": "location",
            "label": "Building",
            "id_prefix": "loc",
            "subclass_field": "location_class",
            "subclass_value": "building",
            "initial_fields": {"location_class": "building"},
        }

        self.assertTrue(ui._convert_card_to_template(card, building_template))

        converted = card["card_view"].entity
        self.assertEqual("locations", converted["_dataset"])
        self.assertEqual("location", converted["type"])
        self.assertEqual("building", converted["location_class"])
        self.assertEqual("Location | Building", card["subtitle"])

    def test_card_subtitle_uses_class_and_subclass_labels(self):
        ui = KnowledgeBrowserUI()

        self.assertEqual(
            "Vehicle | Ground Vehicle",
            ui._card_subtitle_for_entity({
                "id": "veh_rover",
                "type": "vehicle",
                "_dataset": "vehicles",
                "vehicle_class": "ground_vehicle",
            }),
        )
        self.assertEqual(
            "Vehicle",
            ui._card_subtitle_for_entity({
                "id": "veh_unknown",
                "type": "vehicle",
                "_dataset": "vehicles",
            }),
        )


if __name__ == "__main__":
    unittest.main()
