import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from app.navigation_controller import NavigationController
from ui.knowledge_browser_ui import KnowledgeBrowserUI


class _World:
    def __init__(self, entities):
        self.entities = {entity["id"]: entity for entity in entities}
        self.repository_revision = 0

    def get_entity(self, entity_id):
        return self.entities.get(entity_id)

    def get_entities_by_dataset(self, name):
        return [entity for entity in self.entities.values() if entity.get("_dataset") == name]

    def get_active_entities(self, year=None, dataset_name=None, entity_type=None):
        entities = list(self.entities.values())
        if dataset_name:
            entities = [entity for entity in entities if entity.get("_dataset") == dataset_name]
        if entity_type:
            entities = [entity for entity in entities if entity.get("type") == entity_type]
        return entities

    def mark_repository_changed(self):
        pass


def _new_browser_ui(world):
    # KnowledgeBrowserUI() loads/writes a real on-disk draft cache -- isolate it.
    ui = KnowledgeBrowserUI()
    ui.card_drafts = {}
    ui.DRAFT_CACHE_PATH = None
    ui._write_card_drafts = lambda: None
    ui.world_model = world
    ui.layout = ui._build_layout(1200, 800)
    # Auto-height layout (get_minimum_height) needs a real layout font, or
    # every card silently clamps to the 260px fallback height and clips its
    # own content -- see _layout_all_cards in knowledge_canvas_controller.py.
    ui.font_for_layout = pygame.font.Font(None, 18)
    return ui


class IllustrationPixelEditorEntryPointTests(unittest.TestCase):
    """Covers the two entry points requested for opening a plain illustration
    in the pixel editor: an illustration card's own Launch button, and the
    pixel-art button on a parent card's Media tab. Both were previously
    unverified end-to-end (the media button had zero test coverage, and the
    Launch button had no illustration branch in LaunchAffordanceResolver at
    all)."""

    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_launch_button_on_illustration_card_opens_pixel_editor(self):
        illustration = {
            "id": "idea_launch_test", "_dataset": "ideas", "type": "idea",
            "idea_class": "illustration", "name": "Launch test art",
            "media_path": "",
        }
        world = _World([illustration])
        ui = _new_browser_ui(world)
        ui._ensure_card(illustration)

        card = ui.cards[0]
        launch_rect = card.get("launch_rect")
        self.assertIsNotNone(launch_rect)

        viewport = pygame.Rect(0, 0, 4000, 4000)
        action = ui._handle_card_canvas_click(launch_rect.center, viewport)
        self.assertIsInstance(action, dict)
        self.assertEqual("idea_launch_test", action.get("entity_id"))

        ui_manager = SimpleNamespace(knowledge_ui=ui)
        app = SimpleNamespace(world_model=world, ui_manager=ui_manager, knowledge_layer_active=True)
        navigation = NavigationController(app)
        self.assertTrue(navigation.handle_ui_action(action, active_sim=None))

        editor_state = ui.pixel_art_editor
        self.assertIsInstance(editor_state, dict)
        self.assertEqual("idea_launch_test", editor_state.get("illustration_id"))
        # Unlike every other launch mode, opening the pixel editor must not
        # kick the knowledge layer closed -- it's a modal on top of it.
        self.assertTrue(app.knowledge_layer_active)

    def test_media_tab_pixel_button_opens_pixel_editor_for_attached_illustration(self):
        parent = {"id": "idea_parent", "_dataset": "ideas", "type": "idea", "name": "Parent idea"}
        illustration = {
            "id": "idea_child_art", "_dataset": "ideas", "type": "idea",
            "idea_class": "illustration", "name": "Child art", "media_path": "",
            "parents": ["idea_parent"],
        }
        world = _World([parent, illustration])
        ui = _new_browser_ui(world)
        ui._ensure_card(parent)

        card = ui.cards[0]
        card["card_view"].set_active_tab("media")
        ui._layout_all_cards()
        card = ui.cards[0]

        pixel_buttons = dict(card.get("media_pixel_art_hitboxes", []))
        self.assertIn("idea_child_art", pixel_buttons)

        viewport = pygame.Rect(0, 0, 4000, 4000)
        action = ui._handle_card_canvas_click(pixel_buttons["idea_child_art"].center, viewport)
        self.assertEqual("__ui_consumed__", action)

        editor_state = ui.pixel_art_editor
        self.assertIsInstance(editor_state, dict)
        self.assertEqual("idea_child_art", editor_state.get("illustration_id"))


if __name__ == "__main__":
    unittest.main()
