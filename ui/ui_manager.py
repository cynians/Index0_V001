import pygame


class UIButton:
    """
    Minimal screen-space button description.
    """

    def __init__(self, button_id, label, rect, visible=True, enabled=True):
        self.id = button_id
        self.label = label
        self.rect = rect
        self.visible = visible
        self.enabled = enabled


class UIManager:
    """
    Minimal app-level UI manager.

    Responsibilities:
    * rebuild visible widgets for current app state
    * draw widgets
    * consume UI clicks and return action ids
    * draw simple scope/breadcrumb labels and hover tooltip
    """

    def __init__(self):
        self.buttons = []
        self.scope_label = None
        self.breadcrumb_label = None
        self.hover_tooltip_lines = []
        self.hover_tooltip_pos = None

    def rebuild_for_state(self, active_sim, app_width, app_height):
        """
        Rebuild the current widget set for the active simulation state.
        """
        self.buttons = []
        self.scope_label = None
        self.breadcrumb_label = None
        self.hover_tooltip_lines = []
        self.hover_tooltip_pos = None

        if active_sim is None:
            return

        button_width = 180
        button_height = 32
        button_x = app_width - button_width - 20
        button_y = 42

        # --------------------------------------------------
        # MAP UI
        # --------------------------------------------------

        if getattr(active_sim, "render_mode", None) == "map":
            root_name = None
            if hasattr(active_sim, "get_root_name"):
                root_name = active_sim.get_root_name()

            if root_name:
                self.scope_label = f"Scope: {root_name}"

            existing_status_line = None
            if hasattr(active_sim, "get_root_entity"):
                root_entity = active_sim.get_root_entity()
                if root_entity:
                    canvas_w = root_entity.get("map_canvas_width_px")
                    canvas_h = root_entity.get("map_canvas_height_px")
                    map_status = root_entity.get("map_status")

                    if canvas_w and canvas_h:
                        self.scope_label = f"Scope: {root_name} | Canvas: {canvas_w} x {canvas_h}"

                    if map_status:
                        existing_status_line = f"Status: {map_status}"

            if hasattr(active_sim, "get_scope_breadcrumb"):
                breadcrumb_parts = active_sim.get_scope_breadcrumb()
                if breadcrumb_parts:
                    breadcrumb_text = " > ".join(breadcrumb_parts)
                    if existing_status_line:
                        self.breadcrumb_label = f"{existing_status_line} | {breadcrumb_text}"
                    else:
                        self.breadcrumb_label = breadcrumb_text
                elif existing_status_line:
                    self.breadcrumb_label = existing_status_line
            elif existing_status_line:
                self.breadcrumb_label = existing_status_line

            selected_entity_id = getattr(active_sim, "selected_entity_id", None)
            root_entity_id = getattr(active_sim.context, "root_entity_id", None)

            if selected_entity_id is not None and selected_entity_id != root_entity_id:
                self.buttons.append(
                    UIButton(
                        button_id="open_region_map",
                        label="Open Region Map",
                        rect=pygame.Rect(button_x, button_y, button_width, button_height),
                        visible=True,
                        enabled=True,
                    )
                )

            parent_root_entity_id = None
            if hasattr(active_sim, "get_parent_root_entity_id"):
                parent_root_entity_id = active_sim.get_parent_root_entity_id()

            if parent_root_entity_id is not None:
                self.buttons.append(
                    UIButton(
                        button_id="open_parent_region_map",
                        label="Up To Parent",
                        rect=pygame.Rect(button_x, button_y + 40, button_width, button_height),
                        visible=True,
                        enabled=True,
                    )
                )

            hover_entity_id = getattr(active_sim, "hover_entity_id", None)
            hover_screen_pos = getattr(active_sim, "hover_screen_pos", None)

            if hover_entity_id and hover_screen_pos:
                entity = active_sim.world_model.get_entity(hover_entity_id)
                if entity:
                    entity_name = entity.get("name", hover_entity_id)
                    location_class = entity.get("location_class", entity.get("type", "entity"))

                    self.hover_tooltip_lines = [
                        entity_name,
                        f"class: {location_class}",
                    ]

                    if hover_entity_id == selected_entity_id:
                        self.hover_tooltip_lines.append("selected")

                    self.hover_tooltip_pos = hover_screen_pos

            return

        # --------------------------------------------------
        # SPACE UI
        # --------------------------------------------------

        if getattr(active_sim, "render_mode", None) == "space":
            selected_body_entity = None
            if hasattr(active_sim, "get_selected_body_entity"):
                selected_body_entity = active_sim.get_selected_body_entity()

            if selected_body_entity:
                body_name = selected_body_entity.get("name", selected_body_entity.get("id"))
                body_class = selected_body_entity.get("body_class", "body")
                self.scope_label = f"Selected: {body_name}"
                self.breadcrumb_label = f"class: {body_class}"

                self.buttons.append(
                    UIButton(
                        button_id="open_space_body_map",
                        label="Open Map",
                        rect=pygame.Rect(button_x, button_y, button_width, button_height),
                        visible=True,
                        enabled=True,
                    )
                )

            hover_body_id = getattr(active_sim, "hover_system_entity_id", None)
            hover_screen_pos = getattr(active_sim, "hover_screen_pos", None)

            if hover_body_id and hover_screen_pos:
                entity = active_sim.world_model.get_entity(hover_body_id)
                if entity:
                    entity_name = entity.get("name", hover_body_id)
                    body_class = entity.get("body_class", entity.get("type", "entity"))

                    self.hover_tooltip_lines = [
                        entity_name,
                        f"class: {body_class}",
                    ]

                    selected_system_entity_id = getattr(active_sim, "selected_system_entity_id", None)
                    if hover_body_id == selected_system_entity_id:
                        self.hover_tooltip_lines.append("selected")

                    self.hover_tooltip_pos = hover_screen_pos

    def _draw_button(self, screen, font, button):
        fill_color = (55, 55, 55) if button.enabled else (35, 35, 35)
        border_color = (210, 210, 210) if button.enabled else (100, 100, 100)
        text_color = (245, 245, 245) if button.enabled else (140, 140, 140)

        pygame.draw.rect(screen, fill_color, button.rect)
        pygame.draw.rect(screen, border_color, button.rect, 2)

        text_surface = font.render(button.label, True, text_color)
        text_rect = text_surface.get_rect(center=button.rect.center)
        screen.blit(text_surface, text_rect)

    def _draw_info_panel(self, screen, font, x, y, lines):
        if not lines:
            return

        padding = 8
        line_gap = 4

        rendered = [font.render(line, True, (240, 240, 240)) for line in lines]
        panel_width = max(text.get_width() for text in rendered) + padding * 2
        panel_height = (
            sum(text.get_height() for text in rendered)
            + line_gap * (len(rendered) - 1)
            + padding * 2
        )

        panel_rect = pygame.Rect(x, y, panel_width, panel_height)
        pygame.draw.rect(screen, (28, 28, 32), panel_rect)
        pygame.draw.rect(screen, (200, 200, 200), panel_rect, 1)

        current_y = panel_rect.y + padding
        for text_surface in rendered:
            screen.blit(text_surface, (panel_rect.x + padding, current_y))
            current_y += text_surface.get_height() + line_gap

    def _draw_hover_tooltip(self, screen, font):
        if not self.hover_tooltip_lines or not self.hover_tooltip_pos:
            return

        padding = 8
        line_gap = 4
        rendered = [font.render(line, True, (240, 240, 240)) for line in self.hover_tooltip_lines]
        panel_width = max(text.get_width() for text in rendered) + padding * 2
        panel_height = (
            sum(text.get_height() for text in rendered)
            + line_gap * (len(rendered) - 1)
            + padding * 2
        )

        tooltip_x = self.hover_tooltip_pos[0] + 14
        tooltip_y = self.hover_tooltip_pos[1] + 14

        screen_width = screen.get_width()
        screen_height = screen.get_height()

        if tooltip_x + panel_width > screen_width - 10:
            tooltip_x = self.hover_tooltip_pos[0] - panel_width - 14

        if tooltip_y + panel_height > screen_height - 10:
            tooltip_y = self.hover_tooltip_pos[1] - panel_height - 14

        tooltip_rect = pygame.Rect(tooltip_x, tooltip_y, panel_width, panel_height)
        pygame.draw.rect(screen, (24, 24, 28), tooltip_rect)
        pygame.draw.rect(screen, (210, 210, 210), tooltip_rect, 1)

        current_y = tooltip_rect.y + padding
        for text_surface in rendered:
            screen.blit(text_surface, (tooltip_rect.x + padding, current_y))
            current_y += text_surface.get_height() + line_gap

    def draw(self, screen, font):
        """
        Draw all visible UI widgets and info overlays.
        """
        for button in self.buttons:
            if not button.visible:
                continue
            self._draw_button(screen, font, button)

        info_lines = []
        if self.scope_label:
            info_lines.append(self.scope_label)
        if self.breadcrumb_label:
            info_lines.append(self.breadcrumb_label)

        if info_lines:
            self._draw_info_panel(screen, font, 20, 100, info_lines)

        self._draw_hover_tooltip(screen, font)

    def handle_event(self, event):
        """
        Handle UI events.

        Returns:
            action_id if a UI element consumed the click, otherwise None.
        """
        if event.type != pygame.MOUSEBUTTONDOWN:
            return None

        if event.button != 1:
            return None

        mouse_pos = event.pos

        for button in self.buttons:
            if not button.visible or not button.enabled:
                continue

            if button.rect.collidepoint(mouse_pos):
                return button.id

        return None