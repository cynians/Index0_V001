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

    def test_mouse_wheel_reuses_existing_ui_layout(self):
        app = SimpleNamespace(
            knowledge_layer_active=False,
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
            SimpleNamespace(type=pygame.MOUSEWHEEL)
        )

        self.assertFalse(needs_rebuild)

    def test_mouse_wheel_rebuilds_when_layout_is_empty(self):
        app = SimpleNamespace(
            knowledge_layer_active=False,
            ui_manager=SimpleNamespace(
                buttons=[],
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
            SimpleNamespace(type=pygame.MOUSEWHEEL)
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

    def test_floating_card_input_is_noop_when_no_card_is_open(self):
        app = SimpleNamespace(
            ui_manager=SimpleNamespace(floating_card_rect=None, knowledge_ui=SimpleNamespace(cards=[])),
        )
        router = InputRouter(app)

        handled = router._handle_floating_card_input(
            SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1, pos=(50, 50))
        )

        self.assertFalse(handled)

    def test_escape_closes_an_open_floating_card_and_takes_priority(self):
        closed = []
        app = SimpleNamespace(
            ui_manager=SimpleNamespace(
                floating_card_rect=pygame.Rect(0, 0, 100, 100),
                knowledge_ui=SimpleNamespace(cards=[]),
                close_floating_card=lambda: closed.append(True),
            ),
        )
        router = InputRouter(app)

        handled = router._handle_floating_card_input(
            SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_ESCAPE)
        )

        self.assertTrue(handled)
        self.assertEqual([True], closed)

    def test_click_inside_floating_card_rect_is_routed_and_scrubbed(self):
        scrub_calls = []
        click_calls = []

        def fake_click(pos, rect):
            click_calls.append((pos, rect))
            return "__ui_consumed__"

        app = SimpleNamespace(
            ui_manager=SimpleNamespace(
                floating_card_rect=pygame.Rect(0, 0, 100, 100),
                knowledge_ui=SimpleNamespace(cards=[], _handle_card_canvas_click=fake_click),
                scrub_floating_card_hitboxes=lambda: scrub_calls.append(True),
            ),
        )
        router = InputRouter(app)

        handled = router._handle_floating_card_input(
            SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1, pos=(50, 50))
        )

        self.assertTrue(handled)
        self.assertEqual([((50, 50), pygame.Rect(0, 0, 100, 100))], click_calls)
        self.assertEqual([True], scrub_calls)

    def test_click_outside_floating_card_rect_is_not_consumed(self):
        app = SimpleNamespace(
            ui_manager=SimpleNamespace(
                floating_card_rect=pygame.Rect(0, 0, 100, 100),
                knowledge_ui=SimpleNamespace(
                    cards=[], _handle_card_canvas_click=lambda pos, rect: None,
                ),
                scrub_floating_card_hitboxes=lambda: None,
            ),
        )
        router = InputRouter(app)

        handled = router._handle_floating_card_input(
            SimpleNamespace(type=pygame.MOUSEBUTTONDOWN, button=1, pos=(500, 500))
        )

        self.assertFalse(handled)

    def test_keydown_routes_to_card_when_a_field_is_being_edited(self):
        keydown_calls = []
        app = SimpleNamespace(
            ui_manager=SimpleNamespace(
                floating_card_rect=pygame.Rect(0, 0, 100, 100),
                knowledge_ui=SimpleNamespace(
                    cards=[{"is_edit_mode": True, "active_edit_field": "name"}],
                    _handle_keydown_event=lambda event: keydown_calls.append(event),
                ),
            ),
        )
        router = InputRouter(app)
        event = SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_x, unicode="x")

        handled = router._handle_floating_card_input(event)

        self.assertTrue(handled)
        self.assertEqual([event], keydown_calls)

    def test_keydown_falls_through_when_no_field_is_being_edited(self):
        app = SimpleNamespace(
            ui_manager=SimpleNamespace(
                floating_card_rect=pygame.Rect(0, 0, 100, 100),
                knowledge_ui=SimpleNamespace(cards=[{"is_edit_mode": False, "active_edit_field": None}]),
            ),
        )
        router = InputRouter(app)

        handled = router._handle_floating_card_input(
            SimpleNamespace(type=pygame.KEYDOWN, key=pygame.K_x, unicode="x")
        )

        self.assertFalse(handled)

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
