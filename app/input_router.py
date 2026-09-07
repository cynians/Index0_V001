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

    UI_CONSUMED_ACTIONS = {"__ui_consumed__", "ui_consumed"}

    def __init__(self, app):
        self.app = app

    def _is_ui_consumed_action(self, action):
        if not isinstance(action, str):
            return False
        return action in self.UI_CONSUMED_ACTIONS

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
            system_menu_active=self.app.system_menu_active,
            system_settings_active=self.app.system_settings_active,
            repository_return_confirm_active=self.app.repository_return_confirm_active,
            world_model=self.app.world_model,
            repository_scope_entity_id=self.app.repository_scope_entity_id,
            parent_assignment_request=getattr(self.app, "parent_assignment_request", None),
        )

    def _event_needs_fresh_ui_layout(self, event):
        if event.type in (pygame.MOUSEMOTION, pygame.MOUSEWHEEL):
            ui_manager = self.app.ui_manager
            knowledge_ui = getattr(ui_manager, "knowledge_ui", None)
            if (
                getattr(self.app, "knowledge_layer_active", False)
                and getattr(knowledge_ui, "layout", None) is not None
            ):
                return False

        if event.type not in (pygame.MOUSEMOTION, pygame.MOUSEWHEEL):
            return True

        ui_manager = self.app.ui_manager
        return not any(
            (
                getattr(ui_manager, "buttons", None),
                getattr(ui_manager, "tab_hitboxes", None),
                getattr(ui_manager, "simulation_panel_tab_hitboxes", None),
                getattr(ui_manager, "simulation_bar_resize_hitbox", None),
                getattr(ui_manager, "simulation_selection_buttons", None),
                getattr(ui_manager, "system_menu_buttons", None),
                getattr(ui_manager, "repository_return_confirm_buttons", None),
                getattr(getattr(ui_manager, "selection_inspector", None), "is_open", False),
            )
        )

    def _handle_keydown_navigation(self, event):
        """
        Route global keydown events into navigation.
        """
        if event.type == pygame.KEYDOWN:
            active_sim = self.app.get_active_simulation()
            if (active_sim is not None
                and not getattr(self.app, "knowledge_layer_active", False)
                and not getattr(self.app, "system_menu_active", False)
                and not getattr(self.app, "repository_return_confirm_active", False)
                and ((hasattr(active_sim, "handle_comparison_key") and active_sim.handle_comparison_key(event))
                     or (hasattr(active_sim, "handle_forest_key") and active_sim.handle_forest_key(event)))):
                return True
            if (
                active_sim is not None
                and bool(getattr(active_sim, "consumes_global_keydown", lambda: False)())
                and hasattr(active_sim, "handle_event")
            ):
                active_sim.handle_event(event)
                return True

            if event.key == pygame.K_ESCAPE:
                if (
                    active_sim is not None
                    and bool(getattr(active_sim, "consumes_global_escape", lambda: False)())
                    and hasattr(active_sim, "handle_event")
                ):
                    active_sim.handle_event(event)
                    return True

                if not self.app.knowledge_layer_active:
                    if self.app.repository_return_confirm_active:
                        self.app.repository_return_confirm_active = False
                        self.app.navigation.open_repository_workspace(active_sim)
                    else:
                        self.app.repository_return_confirm_active = True
                        self.app.system_menu_active = False
                        self.app.system_settings_active = False
                    return True

                knowledge_ui = getattr(self.app.ui_manager, "knowledge_ui", None)
                if (
                    knowledge_ui is not None
                    and getattr(knowledge_ui, "relation_link_target", None) is not None
                ):
                    finish_link = getattr(knowledge_ui, "_finish_relation_browser_link", None)
                    if finish_link is not None:
                        finish_link()
                    return True

                if self.app.system_menu_active and self.app.system_settings_active:
                    self.app.system_settings_active = False
                else:
                    self.app.system_menu_active = not self.app.system_menu_active
                    self.app.system_settings_active = False
                return True

            if self.app.system_menu_active:
                return True

            self.app.navigation.handle_keydown(event)
        return False

    def _handle_ui_action(self, event, active_sim):
        """
        Route UI clicks/actions via the UI manager and navigation controller.

        Returns:
            True if the event was fully consumed by UI routing, otherwise False.
        """
        action = self.app.ui_manager.handle_event(event)

        if self._is_ui_consumed_action(action):
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

    def _handle_floating_card_input(self, event):
        """
        Route input into the floating in-simulation entity card, if one is
        open. Reuses the real KnowledgeBrowserUI card-click/keydown/drag
        dispatch directly (see ui_manager.py's _rebuild_floating_card),
        through the dedicated ui_manager.floating_knowledge_ui instance kept
        separate from the full-screen modal browser's ui_manager.knowledge_ui
        so opening/dragging/closing a floating card never leaks canvas
        offset/zoom/card state into the browser or vice versa. Consumption
        here must happen before simulation pointer forwarding but does not
        touch knowledge_layer_active -- that gate still belongs solely to
        the full-screen modal browser.
        """
        ui_manager = self.app.ui_manager
        floating_ui = ui_manager.floating_knowledge_ui
        floating_rect = getattr(ui_manager, "floating_card_rect", None)

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE and floating_rect is not None:
            ui_manager.close_floating_card()
            return True

        if floating_rect is None:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # _handle_card_canvas_click returns None exactly when the click
            # fell outside floating_rect (its own first check), and always
            # returns a truthy sentinel/action otherwise -- so this doubles
            # as the "was this click ours to consume" test.
            result = floating_ui._handle_card_canvas_click(event.pos, floating_rect)
            # Several click branches re-layout (and thus re-populate hitboxes)
            # as a side effect of handling that same click, so the
            # inspect-mode-safety scrub must be re-applied every time, not
            # just once per frame -- see scrub_floating_card_hitboxes.
            ui_manager.scrub_floating_card_hitboxes()
            return result is not None

        # Drag/resize/color-slider continuation: only claim motion/buttonup
        # while one of these is actually in progress on this card, since the
        # floating card is non-modal -- otherwise every mouse move anywhere
        # on screen would get swallowed and the simulation underneath would
        # stop receiving hover/click events the moment a card is merely open.
        card_interaction_active = (
            floating_ui.active_card_drag_id is not None
            or floating_ui.active_card_resize_id is not None
            or floating_ui.active_card_color_slider is not None
        )
        if card_interaction_active and event.type == pygame.MOUSEMOTION:
            floating_ui._handle_mousemotion_event(event)
            return True
        if card_interaction_active and event.type == pygame.MOUSEBUTTONUP:
            floating_ui._handle_mousebuttonup_event(event)
            return True

        if event.type == pygame.KEYDOWN:
            active_edit_field = any(
                card.get("is_edit_mode") and card.get("active_edit_field")
                for card in floating_ui.cards
            )
            if active_edit_field:
                floating_ui._handle_keydown_event(event)
                return True

        return False

    def _handle_simulation_pointer_input(self, event, active_sim):
        """
        Forward pointer motion and map-edit pointer events to the active simulation.
        """
        handled_pointer = False
        if active_sim and hasattr(active_sim, "handle_pointer_motion"):
            if event.type == pygame.MOUSEMOTION:
                active_sim.handle_pointer_motion(
                    event=event,
                    camera=self.app.camera,
                    screen_pos=event.pos,
                )

        if active_sim and hasattr(active_sim, "handle_pointer_event"):
            if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
                active_sim.handle_pointer_event(
                    event=event,
                    camera=self.app.camera,
                    screen_pos=event.pos,
                )
                handled_pointer = True
            elif event.type == pygame.MOUSEBUTTONUP and event.button in (1, 3):
                active_sim.handle_pointer_event(
                    event=event,
                    camera=self.app.camera,
                    screen_pos=event.pos,
                )
                handled_pointer = True

        if handled_pointer and active_sim is not None:
            consume_action = getattr(active_sim, "consume_pending_navigation_action", None)
            if consume_action is not None:
                action = consume_action()
                if action is not None:
                    self.app.navigation.handle_ui_action(action, active_sim)

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
        if self._handle_keydown_navigation(event):
            return True

        active_sim = self.app.get_active_simulation()
        if self._event_needs_fresh_ui_layout(event):
            self._rebuild_ui_for_event(active_sim)

        if self._handle_ui_action(event, active_sim):
            return True

        if self._handle_floating_card_input(event):
            return True

        if self.app.system_menu_active:
            return True

        if self.app.knowledge_layer_active:
            return True

        self.app.tab_manager.handle_event(event)

        active_sim = self.app.get_active_simulation()

        if self._handle_middle_click_reset(event, active_sim):
            return True

        self._handle_simulation_pointer_input(event, active_sim)
        return False
