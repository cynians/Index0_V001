import pygame


class InputRouter:
    """
    Central app-level input router.

    Responsibilities:
    * route key input to navigation
    * rebuild UI before hit-testing
    * route UI actions into navigation
    * stop simulation input while in the knowledge layer
    * forward events to tab manager
    * reset the active simulation camera on middle click
    * forward pointer motion / left-click input to the active simulation
    """

    def __init__(self, app):
        self.app = app

    def _rebuild_ui_for_event(self, active_sim):
        """
        Rebuild the current UI state before any event hit-testing.
        """
        self.app.ui_manager.rebuild_for_state(
            active_sim=active_sim,
            app_width=self.app.width,
            app_height=self.app.height,
            tab_manager=self.app.tab_manager,
            camera=self.app.camera,
            menu_active=self.app.knowledge_layer_active,
            world_model=self.app.world_model,
            repository_scope_entity_id=self.app.repository_scope_entity_id,
        )

    def _handle_keydown_navigation(self, event):
        """
        Route global keydown events into navigation.
        """
        if event.type == pygame.KEYDOWN:
            self.app.navigation.handle_keydown(event)

    def _handle_ui_action(self, event, active_sim):
        """
        Route UI clicks/actions via the UI manager and navigation controller.

        Returns:
            True if the event was fully consumed by UI routing, otherwise False.
        """
        action = self.app.ui_manager.handle_event(event)

        if action == "__ui_consumed__":
            return True

        if action is None:
            return False

        handled = self.app.navigation.handle_ui_action(action, active_sim)
        return bool(handled)

    def _handle_middle_click_reset(self, event, active_sim):
        """
        Reset camera view for the active simulation on middle click.
        """
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
            if active_sim is not None:
                self.app.camera_controller.setup_for_sim(active_sim)
            return True

        return False

    def _handle_simulation_pointer_input(self, event, active_sim):
        """
        Forward pointer motion and primary-button pointer events to the active simulation.
        """
        if active_sim and hasattr(active_sim, "handle_pointer_motion"):
            if event.type == pygame.MOUSEMOTION:
                active_sim.handle_pointer_motion(
                    event=event,
                    camera=self.app.camera,
                    screen_pos=event.pos,
                )

        if active_sim and hasattr(active_sim, "handle_pointer_event"):
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                active_sim.handle_pointer_event(
                    event=event,
                    camera=self.app.camera,
                    screen_pos=event.pos,
                )
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                active_sim.handle_pointer_event(
                    event=event,
                    camera=self.app.camera,
                    screen_pos=event.pos,
                )

    def route_event(self, event):
        """
        Route one pygame event through the app's input pipeline.

        Order:
        * global keydown navigation
        * UI rebuild + UI hit testing
        * knowledge-layer block
        * tab-manager forwarding
        * middle-click reset
        * simulation pointer forwarding
        """
        self._handle_keydown_navigation(event)

        active_sim = self.app.get_active_simulation()
        self._rebuild_ui_for_event(active_sim)

        if self._handle_ui_action(event, active_sim):
            return True

        if self.app.knowledge_layer_active:
            return True

        self.app.tab_manager.handle_event(event)

        active_sim = self.app.get_active_simulation()

        if self._handle_middle_click_reset(event, active_sim):
            return True

        self._handle_simulation_pointer_input(event, active_sim)
        return False