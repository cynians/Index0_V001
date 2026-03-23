import math
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
    App-level UI manager.

    Responsibilities:
    * rebuild visible widgets for current app state
    * draw widgets
    * consume UI clicks and return action ids
    * draw tab strip
    * draw time / timeline / mouse-world status
    * draw map/space info panels and hover tooltip
    * draw the Knowledge Layer shell when no simulation is active
    """

    DAY_SECONDS = 24 * 60 * 60

    def __init__(self):
        self.buttons = []
        self.scope_label = None
        self.breadcrumb_label = None
        self.hover_tooltip_lines = []
        self.hover_tooltip_pos = None

        self.tab_labels = []
        self.active_tab_index = 0
        self.tab_hitboxes = []

        self.time_lines = []
        self.timeline_fraction = 0.0
        self.mouse_world_label = None

        self.menu_active = False
        self.knowledge_layout = None
        self.knowledge_browser_items = []
        self.knowledge_browser_hitboxes = []
        self.knowledge_cards = []
        self.knowledge_world_model = None
        self.knowledge_selected_entity_id = None
        self.repository_scope_entity_id = None
        self.repository_scope_label = None

    def _format_sim_time(self, sim):
        """
        Convert sim year + elapsed sim seconds into a simple year/day/time display.
        """
        base_year = getattr(sim, "year", 0)
        elapsed_seconds = getattr(sim.sim_clock, "time", 0.0)

        whole_days = int(elapsed_seconds // self.DAY_SECONDS)
        seconds_in_day = elapsed_seconds % self.DAY_SECONDS

        hours = int(seconds_in_day // 3600)
        minutes = int((seconds_in_day % 3600) // 60)

        display_year = base_year + (whole_days // 365)
        day_of_year = (whole_days % 365) + 1

        return {
            "year": display_year,
            "day_of_year": day_of_year,
            "hours": hours,
            "minutes": minutes,
            "timeline_fraction": seconds_in_day / self.DAY_SECONDS,
        }

    def _build_knowledge_layout(self, app_width, app_height):
        """
        Build the static Knowledge Layer shell rectangles.
        """
        outer_margin = 16
        header_h = 54
        inner_gap = 14
        left_ratio = 0.30

        content_x = outer_margin
        content_y = outer_margin + header_h
        content_w = app_width - outer_margin * 2
        content_h = app_height - content_y - outer_margin

        left_w = int(content_w * left_ratio)
        right_w = content_w - left_w - inner_gap

        left_rect = pygame.Rect(content_x, content_y, left_w, content_h)
        right_rect = pygame.Rect(content_x + left_w + inner_gap, content_y, right_w, content_h)

        return {
            "header_rect": pygame.Rect(outer_margin, outer_margin, content_w, header_h),
            "left_rect": left_rect,
            "right_rect": right_rect,
        }

    def _build_knowledge_browser_items(self, world_model):
        """
        Build selectable browser rows from actual repository entries.
        """
        items = [
            {"kind": "label", "text": "Grouping: dataset preview"},
            {"kind": "spacer"},
            {"kind": "section", "text": "Locations"},
        ]

        if world_model is not None:
            location_entities = sorted(
                world_model.get_entities_by_dataset("locations"),
                key=lambda entity: entity.get("name", entity.get("id", ""))
            )

            for entity in location_entities:
                label = entity.get("name", entity.get("id", "unknown"))
                entity_class = entity.get("location_class", entity.get("type", "entity"))

                items.append(
                    {
                        "kind": "entity",
                        "entity_id": entity.get("id"),
                        "text": f"  {label} [{entity_class}]",
                    }
                )

            items.append({"kind": "spacer"})
            items.append({"kind": "section", "text": "Star Systems"})

            system_entities = sorted(
                world_model.get_entities_by_dataset("systems"),
                key=lambda entity: entity.get("name", entity.get("id", ""))
            )

            for entity in system_entities:
                if entity.get("system_role") != "star_system":
                    continue

                entity_class = entity.get("system_class", entity.get("type", "entity"))
                label = entity.get("name", entity.get("id", "unknown"))

                items.append(
                    {
                        "kind": "entity",
                        "entity_id": entity.get("id"),
                        "text": f"  {label} [{entity_class}]",
                    }
                )

            items.append({"kind": "spacer"})
            items.append({"kind": "section", "text": "Orbital Bodies"})

            for entity in system_entities:
                if entity.get("system_role") != "orbital_body":
                    continue

                entity_class = entity.get("body_class", entity.get("type", "entity"))
                label = entity.get("name", entity.get("id", "unknown"))

                items.append(
                    {
                        "kind": "entity",
                        "entity_id": entity.get("id"),
                        "text": f"  {label} [{entity_class}]",
                    }
                )

        return items

    def _build_card_from_entity(self, entity):
        """
        Build one repository entry card from an actual world-model entity.
        """
        if entity is None or self.knowledge_layout is None:
            return None

        right_rect = self.knowledge_layout["right_rect"]
        card_index = len(self.knowledge_cards)

        card_w = 250
        card_h = 230
        x_gap = 30
        y_gap = 26
        start_x = right_rect.x + 24
        start_y = right_rect.y + 84

        available_w = max(1, right_rect.width - 48)
        col_count = max(1, available_w // (card_w + x_gap))

        col = card_index % col_count
        row = card_index // col_count

        rect_x = start_x + col * (card_w + x_gap)
        rect_y = start_y + row * (card_h + y_gap)

        dataset_name = entity.get("_dataset", entity.get("type", "entity"))

        if dataset_name == "locations":
            display_group = "location"
            subtype = entity.get("location_class", entity.get("type", "entity"))

        elif dataset_name == "systems":
            system_role = entity.get("system_role")

            if system_role == "star_system":
                display_group = "star system"
                subtype = entity.get("system_class", entity.get("type", "entity"))
            elif system_role == "orbital_body":
                display_group = "orbital body"
                subtype = entity.get("body_class", entity.get("type", "entity"))
            else:
                display_group = "system"
                subtype = entity.get("type", "entity")

        else:
            display_group = dataset_name
            subtype = entity.get("type", "entity")

        start_year = entity.get("start_year", 0)

        return {
            "entity_id": entity.get("id"),
            "title": entity.get("name", entity.get("id", "unknown")),
            "subtitle": f"{display_group} | {subtype}",
            "rect": pygame.Rect(rect_x, rect_y, card_w, card_h),
            "years": [start_year],
            "selected_year": start_year,
        }

    def _ensure_knowledge_card(self, entity):
        """
        Add a card for the given entity if it is not already open.
        """
        if entity is None:
            return

        entity_id = entity.get("id")
        if entity_id is None:
            return

        for card in self.knowledge_cards:
            if card.get("entity_id") == entity_id:
                self.knowledge_selected_entity_id = entity_id
                return

        new_card = self._build_card_from_entity(entity)
        if new_card is not None:
            self.knowledge_cards.append(new_card)
            self.knowledge_selected_entity_id = entity_id

    def rebuild_for_state(
            self,
            active_sim,
            app_width,
            app_height,
            tab_manager=None,
            camera=None,
            menu_active=False,
            world_model=None,
            repository_scope_entity_id=None
    ):
        """
        Rebuild the current widget set for the active application state.
        """
        self.buttons = []
        self.scope_label = None
        self.breadcrumb_label = None
        self.hover_tooltip_lines = []
        self.hover_tooltip_pos = None
        self.tab_labels = []
        self.active_tab_index = 0
        self.tab_hitboxes = []
        self.time_lines = []
        self.timeline_fraction = 0.0
        self.mouse_world_label = None

        self.menu_active = menu_active
        self.knowledge_layout = None
        self.knowledge_browser_items = []
        self.knowledge_browser_hitboxes = []
        self.knowledge_world_model = world_model
        self.repository_scope_entity_id = repository_scope_entity_id
        self.repository_scope_label = None

        if tab_manager is not None:
            self.tab_labels = [tab.name for tab in tab_manager.tabs]
            self.active_tab_index = tab_manager.active_index

        if menu_active:
            self.knowledge_layout = self._build_knowledge_layout(app_width, app_height)
            self.knowledge_browser_items = self._build_knowledge_browser_items(world_model)

            scope_entity = None
            if world_model is not None and repository_scope_entity_id:
                scope_entity = world_model.get_entity(repository_scope_entity_id)

            if scope_entity is not None:
                scope_name = scope_entity.get("name", repository_scope_entity_id)
                scope_kind = scope_entity.get(
                    "location_class",
                    scope_entity.get("system_role", scope_entity.get("type", "entity"))
                )
                self.repository_scope_label = f"Scope stub: {scope_name} [{scope_kind}]"
                self._ensure_knowledge_card(scope_entity)
                self.knowledge_selected_entity_id = scope_entity.get("id")

            elif not self.knowledge_cards and world_model is not None:
                self._ensure_knowledge_card(world_model.get_entity("planet_earth"))
                self._ensure_knowledge_card(world_model.get_entity("system_sol"))

            return

        if active_sim is None:
            return

        time_info = self._format_sim_time(active_sim)
        self.timeline_fraction = time_info["timeline_fraction"]

        self.time_lines = [
            f"Year {time_info['year']} | Day {time_info['day_of_year']}",
            f"{time_info['hours']:02d}:{time_info['minutes']:02d} | Tick {active_sim.sim_clock.tick}",
            f"Time Scale x{active_sim.sim_clock.time_scale:.2f}",
        ]

        if camera is not None:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            world_x = int((mouse_x - app_width / 2) / camera.zoom + camera.x)
            world_y = int((mouse_y - app_height / 2) / camera.zoom + camera.y)
            self.mouse_world_label = f"Mouse World: {world_x} , {world_y}"

        button_width = 180
        button_height = 32
        button_x = app_width - button_width - 20
        button_y = 42

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

            self.buttons.append(
                UIButton(
                    button_id="open_repository",
                    label="Open Repository",
                    rect=pygame.Rect(button_x, button_y, button_width, button_height),
                    visible=True,
                    enabled=True,
                )
            )

            selected_entity_id = getattr(active_sim, "selected_entity_id", None)
            root_entity_id = getattr(active_sim.context, "root_entity_id", None)

            if selected_entity_id is not None and selected_entity_id != root_entity_id:
                self.buttons.append(
                    UIButton(
                        button_id="open_region_map",
                        label="Open Region Map",
                        rect=pygame.Rect(button_x, button_y + 40, button_width, button_height),
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
                        rect=pygame.Rect(button_x, button_y + 80, button_width, button_height),
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

        if getattr(active_sim, "render_mode", None) == "space":
            self.buttons.append(
                UIButton(
                    button_id="open_repository",
                    label="Open Repository",
                    rect=pygame.Rect(button_x, button_y, button_width, button_height),
                    visible=True,
                    enabled=True,
                )
            )

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
                        rect=pygame.Rect(button_x, button_y + 40, button_width, button_height),
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

    def _draw_multiline_text(self, screen, font, lines, x, y, color=(220, 220, 220), line_gap=4):
        current_y = y
        for line in lines:
            text_surface = font.render(line, True, color)
            screen.blit(text_surface, (x, current_y))
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

    def _draw_tab_strip(self, screen, font):
        x_offset = 20
        y_offset = 5
        padding = 10

        self.tab_hitboxes = []

        for i, label in enumerate(self.tab_labels):
            text_surface = font.render(label, True, (255, 255, 255))
            text_rect = text_surface.get_rect()

            rect = pygame.Rect(
                x_offset,
                y_offset,
                text_rect.width + padding * 2,
                text_rect.height + padding
            )

            if i == self.active_tab_index:
                pygame.draw.rect(screen, (80, 80, 120), rect)
            else:
                pygame.draw.rect(screen, (40, 40, 40), rect)

            pygame.draw.rect(screen, (200, 200, 200), rect, 1)
            screen.blit(text_surface, (rect.x + padding, rect.y + padding // 2))

            self.tab_hitboxes.append((i, rect))
            x_offset += rect.width + 5

    def _draw_time_panel(self, screen, font):
        lines = list(self.time_lines)

        if self.mouse_world_label:
            lines.append(self.mouse_world_label)

        if not lines:
            return

        self._draw_info_panel(screen, font, 20, 40, lines)

    def _draw_timeline_bar(self, screen, x, y, w, h):
        pygame.draw.rect(screen, (30, 30, 34), (x, y, w, h))
        pygame.draw.rect(screen, (200, 200, 200), (x, y, w, h), 1)

        filled_w = max(0, min(w, int(round(w * self.timeline_fraction))))
        if filled_w > 0:
            pygame.draw.rect(screen, (120, 170, 255), (x, y, filled_w, h))

        tick_positions = [0.0, 0.25, 0.5, 0.75, 1.0]
        for frac in tick_positions:
            tick_x = x + int(round(w * frac))
            pygame.draw.line(screen, (180, 180, 180), (tick_x, y), (tick_x, y + h), 1)

    def _draw_timeline_labels(self, screen, font, x, y, w):
        labels = ["00:00", "06:00", "12:00", "18:00", "24:00"]

        for i, label in enumerate(labels):
            frac = i / 4
            lx = x + int(round(w * frac))
            text_surface = font.render(label, True, (220, 220, 220))

            if i == 0:
                draw_x = lx
            elif i == len(labels) - 1:
                draw_x = lx - text_surface.get_width()
            else:
                draw_x = lx - text_surface.get_width() // 2

            screen.blit(text_surface, (draw_x, y))

    def _draw_knowledge_card(self, screen, font, card):
        """
        Draw a compact repository entry card.
        """
        rect = card["rect"]

        pygame.draw.rect(screen, (28, 30, 38), rect)
        pygame.draw.rect(screen, (170, 170, 170), rect, 1)

        title_surface = font.render(card["title"], True, (245, 245, 245))
        subtitle_surface = font.render(card["subtitle"], True, (170, 170, 170))
        screen.blit(title_surface, (rect.x + 12, rect.y + 10))
        screen.blit(subtitle_surface, (rect.x + 12, rect.y + 32))

        image_rect = pygame.Rect(rect.x + 12, rect.y + 58, rect.width - 24, 82)
        pygame.draw.rect(screen, (40, 42, 52), image_rect)
        pygame.draw.rect(screen, (120, 120, 120), image_rect, 1)
        image_text = font.render("Image / layered view placeholder", True, (195, 195, 195))
        screen.blit(image_text, (image_rect.x + 10, image_rect.y + 30))

        timeline_y = rect.y + 160
        left_x = rect.x + 16
        right_x = rect.right - 16
        center_y = timeline_y + 10

        pygame.draw.line(screen, (170, 170, 170), (left_x, center_y), (right_x, center_y), 1)

        year_positions = []
        years = card["years"]
        for index, year in enumerate(years):
            if len(years) == 1:
                frac = 0.5
            else:
                frac = index / (len(years) - 1)

            year_x = int(left_x + (right_x - left_x) * frac)
            year_positions.append((year, year_x))

            marker_rect = pygame.Rect(year_x - 5, center_y - 5, 10, 10)
            selected = year == card["selected_year"]

            fill = (210, 210, 210) if selected else (70, 70, 70)
            border = (240, 240, 240) if selected else (170, 170, 170)
            pygame.draw.rect(screen, fill, marker_rect)
            pygame.draw.rect(screen, border, marker_rect, 1)

            year_surface = font.render(str(year), True, (230, 230, 230))
            year_rect = year_surface.get_rect(center=(year_x, center_y + 22))
            screen.blit(year_surface, year_rect)

        launch_rect = pygame.Rect(rect.x + 12, rect.bottom - 36, rect.width - 24, 24)
        pygame.draw.rect(screen, (55, 55, 55), launch_rect)
        pygame.draw.rect(screen, (210, 210, 210), launch_rect, 1)
        launch_text = font.render(f"Launch [{card['selected_year']}]", True, (245, 245, 245))
        launch_text_rect = launch_text.get_rect(center=launch_rect.center)
        screen.blit(launch_text, launch_text_rect)

        card["image_rect"] = image_rect
        card["launch_rect"] = launch_rect
        card["year_hitboxes"] = []

        for year, year_x in year_positions:
            hitbox = pygame.Rect(year_x - 12, center_y - 12, 24, 48)
            card["year_hitboxes"].append((year, hitbox))

    def _draw_knowledge_layer(self, screen, font):
        """
        Draw the two-pane Knowledge Layer shell.
        """
        if self.knowledge_layout is None:
            return

        header_rect = self.knowledge_layout["header_rect"]
        left_rect = self.knowledge_layout["left_rect"]
        right_rect = self.knowledge_layout["right_rect"]

        pygame.draw.rect(screen, (18, 20, 26), header_rect)
        pygame.draw.rect(screen, (200, 200, 200), header_rect, 1)

        title_surface = font.render("Knowledge Layer", True, (245, 245, 245))

        subtitle_text = "Pre-simulation repository workspace"
        if self.repository_scope_label:
            subtitle_text = self.repository_scope_label

        subtitle_surface = font.render(subtitle_text, True, (180, 180, 180))
        screen.blit(title_surface, (header_rect.x + 14, header_rect.y + 10))
        screen.blit(subtitle_surface, (header_rect.x + 14, header_rect.y + 30))

        pygame.draw.rect(screen, (12, 12, 20), left_rect)
        pygame.draw.rect(screen, (200, 200, 200), left_rect, 1)

        pygame.draw.rect(screen, (12, 16, 28), right_rect)
        pygame.draw.rect(screen, (200, 200, 200), right_rect, 1)

        left_title = font.render("Repository Browser", True, (240, 240, 240))
        right_title = font.render("Card Canvas", True, (240, 240, 240))
        screen.blit(left_title, (left_rect.x + 12, left_rect.y + 10))
        screen.blit(right_title, (right_rect.x + 12, right_rect.y + 10))

        self.knowledge_browser_hitboxes = []

        line_y = left_rect.y + 48
        line_h = font.get_height() + 4
        max_y = left_rect.bottom - 10

        for item in self.knowledge_browser_items:
            if line_y + line_h > max_y:
                break

            if item["kind"] == "spacer":
                line_y += line_h
                continue

            if item["kind"] == "section":
                color = (235, 235, 235)
                text_x = left_rect.x + 12
                row_rect = None
            elif item["kind"] == "label":
                color = (220, 220, 220)
                text_x = left_rect.x + 12
                row_rect = None
            else:
                row_rect = pygame.Rect(left_rect.x + 10, line_y - 1, left_rect.width - 20, line_h)
                is_selected = item["entity_id"] == self.knowledge_selected_entity_id

                if is_selected:
                    pygame.draw.rect(screen, (42, 46, 62), row_rect)
                    pygame.draw.rect(screen, (150, 150, 170), row_rect, 1)

                color = (245, 245, 245) if is_selected else (220, 220, 220)
                text_x = left_rect.x + 12
                self.knowledge_browser_hitboxes.append((item["entity_id"], row_rect))

            text_surface = font.render(item["text"], True, color)
            screen.blit(text_surface, (text_x, line_y))

            line_y += line_h

        for card in self.knowledge_cards:
            self._draw_knowledge_card(screen, font, card)

    def draw(self, screen, font):
        """
        Draw all visible UI widgets and info overlays.
        """
        self._draw_tab_strip(screen, font)

        if self.menu_active:
            self._draw_knowledge_layer(screen, font)
            return

        self._draw_time_panel(screen, font)

        if self.time_lines:
            timeline_x = 20
            timeline_y = 135
            timeline_w = 320
            timeline_h = 12
            self._draw_timeline_bar(screen, timeline_x, timeline_y, timeline_w, timeline_h)
            self._draw_timeline_labels(screen, font, timeline_x, timeline_y + 18, timeline_w)

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
            self._draw_info_panel(screen, font, 20, 170, info_lines)

        self._draw_hover_tooltip(screen, font)

    def handle_event(self, event):
        """
        Handle UI events.

        Returns:
            action payload if a UI element consumed the click, otherwise None.
        """
        if event.type != pygame.MOUSEBUTTONDOWN:
            return None

        if event.button != 1:
            return None

        mouse_pos = event.pos

        for tab_index, hitbox in self.tab_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                return {
                    "id": "activate_tab",
                    "tab_index": tab_index,
                }

        if self.menu_active:
            for entity_id, hitbox in self.knowledge_browser_hitboxes:
                if hitbox.collidepoint(mouse_pos):
                    self.knowledge_selected_entity_id = entity_id

                    if self.knowledge_world_model is not None:
                        entity = self.knowledge_world_model.get_entity(entity_id)
                        self._ensure_knowledge_card(entity)

                    return None

            for card in self.knowledge_cards:
                for year, hitbox in card.get("year_hitboxes", []):
                    if hitbox.collidepoint(mouse_pos):
                        card["selected_year"] = year
                        return None

                launch_rect = card.get("launch_rect")
                if launch_rect is not None and launch_rect.collidepoint(mouse_pos):
                    return {
                        "id": "knowledge_launch_entry",
                        "entity_id": card.get("entity_id"),
                        "year": card.get("selected_year"),
                    }

            return None

        for button in self.buttons:
            if not button.visible or not button.enabled:
                continue

            if button.rect.collidepoint(mouse_pos):
                return button.id

        return None