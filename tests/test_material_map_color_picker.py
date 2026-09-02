import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pygame

from tests.test_entity_id_updates import DummyLoader, KnowledgeBrowserHarness
from ui.card import EntityCard
from simulations.world_gen.natural_materials import material_geological_map_color


class MaterialColorPickerToolbeltTests(unittest.TestCase):
    def test_material_card_exposes_a_map_color_picker_tool(self):
        card = EntityCard.__new__(EntityCard)
        card.entity = {
            "id": "mat_test_granite_like",
            "type": "material",
            "_dataset": "materials",
        }
        card.dataset_name = "materials"
        tools = card._toolbelt_items()
        material_tools = [t for t in tools if t.get("id") == "material_map_color"]
        self.assertEqual(1, len(material_tools))
        self.assertEqual("color_picker", material_tools[0]["kind"])
        self.assertEqual("geological_map_color", material_tools[0]["color_field"])

    def test_non_material_card_does_not_get_the_material_color_tool(self):
        card = EntityCard.__new__(EntityCard)
        card.entity = {"id": "idea_x", "type": "idea", "_dataset": "ideas"}
        card.dataset_name = "ideas"
        tools = card._toolbelt_items()
        self.assertFalse(any(t.get("id") == "material_map_color" for t in tools))


class MaterialColorPickerDragFlowTests(unittest.TestCase):
    def _make_ui_with_material(self, initial_color=None):
        entity = {
            "id": "mat_test_stone",
            "type": "material",
            "_dataset": "materials",
            "material_system_role": "natural_geologic_material",
        }
        if initial_color is not None:
            entity["geological_map_color"] = initial_color
        ui = KnowledgeBrowserHarness({"mat_test_stone": entity})
        catalog_calls = []
        ui.world_model.get_entities_by_dataset = lambda name: (
            catalog_calls.append(name) or [entity]
        )
        return ui, entity, catalog_calls

    def test_drag_release_persists_hex_color_via_fast_palette_and_refreshes_catalog(self):
        ui, entity, catalog_calls = self._make_ui_with_material()
        slider_rect = pygame.Rect(40, 30, 120, 10)
        hit_rect = slider_rect.inflate(6, 8)
        card = {
            "entity_id": "mat_test_stone",
            "card_view": SimpleNamespace(
                entity=entity,
                handle_location_click=lambda card_arg, mouse_pos: False,
                handle_production_click=lambda card_arg, mouse_pos: False,
                handle_timeline_click=lambda card_arg, mouse_pos: False,
                handle_phylogeny_click=lambda card_arg, mouse_pos: False,
                handle_pixeltile_click=lambda card_arg, mouse_pos: False,
            ),
            "toolbelt_hitboxes": [
                (
                    {
                        "kind": "color_picker",
                        "control": "slider",
                        "channel": "h",
                        "slider_rect": slider_rect,
                        "color_field": "geological_map_color",
                    },
                    hit_rect,
                )
            ],
        }
        ui.cards = [card]
        palette_writes = []
        ui.world_model.loader.persist_entity_palette = (
            lambda candidate: palette_writes.append(candidate["id"]) or True
        )

        click_result = ui._handle_card_canvas_click(
            (slider_rect.x + 72, slider_rect.centery), pygame.Rect(0, 0, 260, 180)
        )
        self.assertEqual("__ui_consumed__", click_result)
        self.assertIsNotNone(ui.active_card_color_slider)
        self.assertEqual("geological_map_color", ui.active_card_color_slider.get("color_field"))
        self.assertIsInstance(entity["geological_map_color"], str)
        self.assertTrue(entity["geological_map_color"].startswith("#"))

        with patch(
            "simulations.world_gen.natural_materials.configure_material_catalog"
        ) as mock_configure:
            release_result = ui._handle_mousebuttonup_event(SimpleNamespace(button=1))

        self.assertEqual("__ui_consumed__", release_result)
        self.assertEqual(["mat_test_stone"], palette_writes)
        self.assertEqual(["materials"], catalog_calls)
        mock_configure.assert_called_once_with([entity])

    def test_persisted_hex_color_is_actually_consumable_by_the_map_renderer(self):
        # Guards the format-compatibility gap: the picker writes a "#rrggbb"
        # hex string, but material_geological_map_color's underlying
        # _coerce_color historically only accepted [r, g, b] lists (the
        # ontology-authoring migration's format) and would have silently
        # discarded a hex-string color, making the picker a no-op end to end.
        from simulations.world_gen import natural_materials

        original_by_id = natural_materials.MATERIAL_BY_ID
        try:
            natural_materials.MATERIAL_BY_ID = {
                "mat_test_stone": {
                    "id": "mat_test_stone",
                    "geological_map_color": "#8c5a3c",
                }
            }
            color = material_geological_map_color("mat_test_stone", fallback=(1, 2, 3))
            self.assertEqual([140, 90, 60], color)
        finally:
            natural_materials.MATERIAL_BY_ID = original_by_id


if __name__ == "__main__":
    unittest.main()
