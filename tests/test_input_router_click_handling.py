import unittest
from types import SimpleNamespace

import pygame

from engine.input_controller import InputController
from app.input_router import InputRouter
from ui.knowledge_browser_ui import KnowledgeBrowserUI


class FakeUIManager:
    def __init__(self, action):
        self.action = action

    def handle_event(self, event):
        return self.action


class FakeNavigation:
    def __init__(self):
        self.actions = []

    def handle_ui_action(self, action, active_sim):
        self.actions.append(action)
        return False


class InputRouterClickHandlingTests(unittest.TestCase):
    def _router_for_action(self, action):
        navigation = FakeNavigation()
        app = SimpleNamespace(
            ui_manager=FakeUIManager(action),
            navigation=navigation,
        )
        return InputRouter(app), navigation

    def test_legacy_ui_consumed_action_stops_before_navigation(self):
        router, navigation = self._router_for_action("ui_consumed")

        handled = router._handle_ui_action(SimpleNamespace(), active_sim=None)

        self.assertTrue(handled)
        self.assertEqual([], navigation.actions)

    def test_canonical_ui_consumed_action_stops_before_navigation(self):
        router, navigation = self._router_for_action("__ui_consumed__")

        handled = router._handle_ui_action(SimpleNamespace(), active_sim=None)

        self.assertTrue(handled)
        self.assertEqual([], navigation.actions)

    def test_real_ui_action_still_routes_to_navigation(self):
        router, navigation = self._router_for_action("open_repository")

        handled = router._handle_ui_action(SimpleNamespace(), active_sim=None)

        self.assertFalse(handled)
        self.assertEqual(["open_repository"], navigation.actions)

    def test_dict_ui_action_does_not_hit_consumed_action_set(self):
        action = {"id": "knowledge_launch_entry", "entity_id": "loc_test"}
        router, navigation = self._router_for_action(action)

        handled = router._handle_ui_action(SimpleNamespace(), active_sim=None)

        self.assertFalse(handled)
        self.assertEqual([action], navigation.actions)

    def test_mouse_motion_reuses_existing_ui_layout(self):
        app = SimpleNamespace(
            ui_manager=SimpleNamespace(
                buttons=[object()],
                tab_hitboxes=[],
                simulation_panel_tab_hitboxes=[],
                simulation_bar_resize_hitbox=None,
                simulation_selection_buttons=[],
                system_menu_buttons=[],
                repository_return_confirm_buttons=[],
                selection_inspector=SimpleNamespace(is_open=False),
            )
        )
        router = InputRouter(app)

        needs_rebuild = router._event_needs_fresh_ui_layout(
            SimpleNamespace(type=pygame.MOUSEMOTION)
        )

        self.assertFalse(needs_rebuild)

    def test_mouse_button_still_rebuilds_ui_before_hit_testing(self):
        app = SimpleNamespace(ui_manager=SimpleNamespace())
        router = InputRouter(app)

        needs_rebuild = router._event_needs_fresh_ui_layout(
            SimpleNamespace(type=pygame.MOUSEBUTTONDOWN)
        )

        self.assertTrue(needs_rebuild)

    def test_knowledge_wheel_reuses_existing_layout(self):
        app = SimpleNamespace(
            knowledge_layer_active=True,
            ui_manager=SimpleNamespace(
                knowledge_ui=SimpleNamespace(layout={"left_rect": object()})
            ),
        )
        router = InputRouter(app)

        needs_rebuild = router._event_needs_fresh_ui_layout(
            SimpleNamespace(type=pygame.MOUSEWHEEL)
        )

        self.assertFalse(needs_rebuild)

    def test_knowledge_rebuild_skips_when_signature_is_unchanged(self):
        pygame.font.init()
        ui = KnowledgeBrowserUI()
        font = pygame.font.SysFont("consolas", 16)
        calls = []

        ui._build_browser_items = lambda world_model: calls.append("browser") or []

        def refresh_layout():
            calls.append("layout")
            ui.layout = {"left_rect": pygame.Rect(0, 0, 200, 200)}

        ui._refresh_layout_geometry = refresh_layout
        ui._relayout_cards = lambda: calls.append("cards")

        ui.rebuild(1200, 800, None, None, font)
        ui.rebuild(1200, 800, None, None, font)

        self.assertEqual(["browser", "layout", "cards"], calls)

    def test_input_controller_coalesces_knowledge_wheel_bursts(self):
        class FakeCamera:
            def __init__(self):
                self.events = []

            def handle_event(self, event):
                self.events.append(event)

        class FakeSimulation:
            knowledge_layer_active = True

            def __init__(self):
                self.events = []

            def handle_pre_camera_event(self, event):
                return False

            def handle_event(self, event):
                self.events.append(event)

        camera = FakeCamera()
        simulation = FakeSimulation()
        controller = InputController(camera, simulation)

        controller.process(
            [
                pygame.event.Event(pygame.MOUSEWHEEL, {"x": 0, "y": 1}),
                pygame.event.Event(pygame.MOUSEWHEEL, {"x": 0, "y": 2}),
                pygame.event.Event(pygame.MOUSEMOTION, {"pos": (10, 10)}),
                pygame.event.Event(pygame.MOUSEWHEEL, {"x": 0, "y": -1}),
            ]
        )

        wheel_events = [event for event in simulation.events if event.type == pygame.MOUSEWHEEL]
        self.assertEqual([3, -1], [event.y for event in wheel_events])
        self.assertEqual([], [event for event in camera.events if event.type == pygame.MOUSEWHEEL])


if __name__ == "__main__":
    unittest.main()
