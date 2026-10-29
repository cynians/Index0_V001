import unittest
from types import SimpleNamespace

import pygame

from tests.test_entity_id_updates import KnowledgeBrowserHarness
from ui.card import EntityCard


class PersonCharacterEditorToolbeltTests(unittest.TestCase):
    def test_person_card_exposes_a_jump_to_character_tab_tool(self):
        card = EntityCard.__new__(EntityCard)
        card.entity = {"id": "person_test", "type": "person", "_dataset": "people"}
        card.dataset_name = "people"
        tools = card._toolbelt_items()
        character_tools = [t for t in tools if t.get("id") == "person_character_editor"]
        self.assertEqual(1, len(character_tools))
        self.assertEqual("jump_to_character_tab", character_tools[0]["kind"])

    def test_non_person_card_does_not_get_the_character_editor_tool(self):
        card = EntityCard.__new__(EntityCard)
        card.entity = {"id": "idea_x", "type": "idea", "_dataset": "ideas"}
        card.dataset_name = "ideas"
        tools = card._toolbelt_items()
        self.assertFalse(any(t.get("id") == "person_character_editor" for t in tools))

    def test_clicking_the_toolbelt_tool_jumps_the_card_to_the_data_subtab(self):
        entity = {"id": "person_test", "type": "person", "_dataset": "people"}
        ui = KnowledgeBrowserHarness({"person_test": entity})
        tool_rect = pygame.Rect(40, 30, 120, 20)
        subtab_calls = []
        card = {
            "entity_id": "person_test",
            "card_view": SimpleNamespace(
                entity=entity,
                set_active_subtab=lambda tab, subtab: subtab_calls.append((tab, subtab)),
                handle_location_click=lambda card_arg, mouse_pos: False,
                handle_production_click=lambda card_arg, mouse_pos: False,
                handle_timeline_click=lambda card_arg, mouse_pos: False,
                handle_phylogeny_click=lambda card_arg, mouse_pos: False,
                handle_pixeltile_click=lambda card_arg, mouse_pos: False,
            ),
            "toolbelt_hitboxes": [
                ({"id": "person_character_editor", "kind": "jump_to_character_tab"}, tool_rect),
            ],
        }
        ui.cards = [card]

        result = ui._handle_card_canvas_click(tool_rect.center, pygame.Rect(0, 0, 260, 180))

        self.assertEqual("__ui_consumed__", result)
        self.assertEqual([("simulation", "data")], subtab_calls)


if __name__ == "__main__":
    unittest.main()
