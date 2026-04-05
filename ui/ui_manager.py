import pygame

from ui.knowledge_browser_ui import KnowledgeBrowserUI
from ui.ui_types import UIButton


class UIManager:
    """
    App-level UI manager.

    Responsibilities:
    * rebuild visible widgets for current app state
    * draw shared widgets
    * consume shared UI clicks and return action ids
    * delegate knowledge-layer workspace behavior
    * coordinate simulation-specific lower-panel UI
    """

    DAY_SECONDS = 24 * 60 * 60

    def __init__(self):
        self.buttons = []
        self.scope_label = None
        self.breadcrumb_label = None
        self.vehicle_requirement_lines = []
        self.hover_tooltip_lines = []
        self.hover_tooltip_pos = None

        self.simulation_bar_rect = None
        self.simulation_bar_title = None
        self.simulation_bar_hint_lines = []
        self.simulation_bar_catalog_entries = []
        self.simulation_bar_catalog_hitboxes = []
        self.simulation_bar_active_catalog_id = None
        self.simulation_bar_resize_hitbox = None
        self.simulation_bar_height = 180
        self.simulation_bar_min_height = 120
        self.simulation_bar_max_height = 420
        self.simulation_bar_is_resizing = False
        self.simulation_bar_resize_start_y = 0
        self.simulation_bar_resize_start_height = 180

        self.simulation_panel_tabs = []
        self.simulation_panel_active_tab_id = None
        self.simulation_panel_tab_hitboxes = []

        self.tab_labels = []
        self.active_tab_index = 0
        self.tab_hitboxes = []

        self.time_lines = []
        self.timeline_fraction = 0.0
        self.mouse_world_label = None

        self.menu_active = False
        self.knowledge_ui = KnowledgeBrowserUI()
        self.app_font = pygame.font.SysFont("consolas", 16)

    def _format_sim_time(self, sim):
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

    def _reset_shared_state(self):
        self.buttons = []
        self.scope_label = None
        self.breadcrumb_label = None
        self.vehicle_requirement_lines = []
        self.hover_tooltip_lines = []
        self.hover_tooltip_pos = None

        self.simulation_bar_rect = None
        self.simulation_bar_title = None
        self.simulation_bar_hint_lines = []
        self.simulation_bar_catalog_entries = []
        self.simulation_bar_catalog_hitboxes = []
        self.simulation_bar_active_catalog_id = None
        self.simulation_bar_resize_hitbox = None

        self.simulation_panel_tabs = []
        self.simulation_panel_active_tab_id = None
        self.simulation_panel_tab_hitboxes = []

        self.tab_labels = []
        self.active_tab_index = 0
        self.tab_hitboxes = []

        self.time_lines = []
        self.timeline_fraction = 0.0
        self.mouse_world_label = None

    def _rebuild_simulation_panel_tab_hitboxes(self):
        self.simulation_panel_tab_hitboxes = []

        if self.simulation_bar_rect is None or not self.simulation_panel_tabs:
            return

        x = self.simulation_bar_rect.x + 12
        y = self.simulation_bar_rect.y + 30
        h = 24
        pad_x = 10
        gap = 6

        for tab in self.simulation_panel_tabs:
            label = tab.get("label", tab.get("id", "tab"))
            tab_w = 8 * len(label) + pad_x * 2 + 4
            rect = pygame.Rect(x, y, tab_w, h)
            self.simulation_panel_tab_hitboxes.append((tab.get("id"), rect))
            x += tab_w + gap

    def _rebuild_vehicle_design_panel(self, active_sim, payload, app_width, app_height):
        blocks_by_id = {
            block.get("id"): block
            for block in payload.get("blocks", [])
        }

        selected_part_id = payload.get("selected_part_id")
        hover_part_id = payload.get("hover_part_id")
        focus_part_id = selected_part_id or hover_part_id

        bar_margin = 20
        bar_height = max(self.simulation_bar_min_height, min(self.simulation_bar_height, self.simulation_bar_max_height))
        self.simulation_bar_height = bar_height

        self.simulation_bar_rect = pygame.Rect(
            bar_margin,
            app_height - bar_height - 20,
            app_width - bar_margin * 2,
            bar_height,
        )
        self.simulation_bar_resize_hitbox = pygame.Rect(
            self.simulation_bar_rect.x,
            self.simulation_bar_rect.y - 4,
            self.simulation_bar_rect.width,
            8,
        )

        self.simulation_bar_title = "Vehicle Design"
        self.simulation_panel_tabs = active_sim.get_simulation_panel_tabs()
        self.simulation_panel_active_tab_id = active_sim.get_active_simulation_panel_tab_id()
        self._rebuild_simulation_panel_tab_hitboxes()

        if self.simulation_panel_active_tab_id == "catalog":
            self.simulation_bar_hint_lines = [
                "Drag top border to resize panel",
                "Hold a card and drag into hull",
                "Card footprint scales by placed size",
            ]
        elif self.simulation_panel_active_tab_id == "selection":
            self.simulation_bar_hint_lines = [
                "Selection panel placeholder",
                "Will show selected component details",
            ]
        elif self.simulation_panel_active_tab_id == "layout":
            self.simulation_bar_hint_lines = [
                "Layout panel placeholder",
                "Will show arrangement and placement tools",
            ]
        else:
            self.simulation_bar_hint_lines = []

        active_panel_tab_id = self.simulation_panel_active_tab_id
        grouped_catalog = payload.get("grouped_component_catalog", [])
        active_catalog_id = payload.get("active_catalog_component_id")
        self.simulation_bar_active_catalog_id = active_catalog_id

        self.simulation_bar_catalog_entries = []
        self.simulation_bar_catalog_hitboxes = []

        if active_panel_tab_id == "catalog":
            content_x = self.simulation_bar_rect.x + 14
            content_y = self.simulation_bar_rect.y + 64
            content_w = int(self.simulation_bar_rect.width * 0.62)
            section_gap_y = 10
            section_header_h = 22
            card_gap_x = 10
            card_gap_y = 10
            text_band_h = 26

            all_entries = []
            for section in grouped_catalog:
                all_entries.extend(section.get("entries", []))

            max_dim_x = 1.0
            max_dim_y = 1.0
            for entry in all_entries:
                dims = dict(entry.get("dimensions_m", {}))
                max_dim_x = max(max_dim_x, float(dims.get("x", 1.0) or 1.0))
                max_dim_y = max(max_dim_y, float(dims.get("y", 1.0) or 1.0))

            def _card_size(entry):
                dims = dict(entry.get("dimensions_m", {}))
                dim_x = float(dims.get("x", 1.0) or 1.0)
                dim_y = float(dims.get("y", 1.0) or 1.0)

                usable_max_w = 180
                usable_max_h = 90

                body_w = max(26, int((dim_x / max_dim_x) * usable_max_w))
                body_h = max(20, int((dim_y / max_dim_y) * usable_max_h))

                card_w = body_w
                card_h = body_h + text_band_h
                return card_w, card_h

            current_y = content_y

            for section in grouped_catalog:
                section_row = {
                    "kind": "section",
                    "label": section.get("title", "Section"),
                }
                section_rect = pygame.Rect(content_x, current_y, content_w, section_header_h)
                self.simulation_bar_catalog_entries.append(section_row)
                self.simulation_bar_catalog_hitboxes.append((None, section_rect, section_row))
                current_y += section_header_h + 6

                cursor_x = content_x
                row_max_h = 0

                for entry in section.get("entries", []):
                    card_w, card_h = _card_size(entry)

                    if cursor_x + card_w > content_x + content_w:
                        cursor_x = content_x
                        current_y += row_max_h + card_gap_y
                        row_max_h = 0

                    row = {
                        "kind": "entry_card",
                        "catalog_id": entry.get("id"),
                        "label": entry.get("label", entry.get("id", "component")),
                        "entry_type": entry.get("entry_type", "component"),
                        "group_name": (entry.get("operational_groups", ["General Systems"])[0] if entry.get("operational_groups") else "General Systems"),
                        "dimensions_m": dict(entry.get("dimensions_m", {})),
                        "component_type": entry.get("component_type", "component"),
                        "body_height": card_h - text_band_h,
                    }

                    card_rect = pygame.Rect(cursor_x, current_y, card_w, card_h)
                    self.simulation_bar_catalog_entries.append(row)
                    self.simulation_bar_catalog_hitboxes.append((row.get("catalog_id"), card_rect, row))

                    cursor_x += card_w + card_gap_x
                    row_max_h = max(row_max_h, card_h)

                current_y += row_max_h + section_gap_y

        mouse_pos = pygame.mouse.get_pos()
        hover_catalog_id = None
        hover_row = None
        for catalog_id, hitbox, row in self.simulation_bar_catalog_hitboxes:
            if catalog_id is None:
                continue
            if hitbox.collidepoint(mouse_pos):
                hover_catalog_id = catalog_id
                hover_row = row
                break

        if active_panel_tab_id == "catalog" and hover_row is not None:
            dims = hover_row.get("dimensions_m", {})
            self.hover_tooltip_lines = [
                "Catalog Item",
                hover_row.get("label", hover_catalog_id),
                hover_row.get("entry_type", "component"),
                hover_row.get("component_type", "component"),
                f"{dims.get('x', '?')} x {dims.get('y', '?')} x {dims.get('z', '?')} m",
            ]
            self.hover_tooltip_pos = mouse_pos

        elif active_panel_tab_id == "catalog" and active_catalog_id:
            active_row = None
            for catalog_id, _, row in self.simulation_bar_catalog_hitboxes:
                if catalog_id == active_catalog_id:
                    active_row = row
                    break

            if active_row is not None:
                dims = active_row.get("dimensions_m", {})
                self.hover_tooltip_lines = [
                    "Catalog Selection",
                    active_row.get("label", active_catalog_id),
                    active_row.get("entry_type", "component"),
                    active_row.get("component_type", "component"),
                    f"{dims.get('x', '?')} x {dims.get('y', '?')} x {dims.get('z', '?')} m",
                    "drag into hull to place",
                ]
                self.hover_tooltip_pos = pygame.mouse.get_pos()

        elif focus_part_id in blocks_by_id:
            block = blocks_by_id[focus_part_id]
            self.hover_tooltip_lines = [
                "Vehicle Design",
                block.get("label", focus_part_id),
                block.get("component_type", "component"),
            ]
            self.hover_tooltip_pos = getattr(active_sim, "hover_screen_pos", None) or pygame.mouse.get_pos()

    def _rebuild_active_simulation_ui(self, active_sim, app_width, app_height, camera):
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

        render_mode = getattr(active_sim, "render_mode", None)

        if render_mode == "vehicle":
            self.scope_label = (
                f"Vehicle: {active_sim.get_vehicle_name()} | "
                f"Mode: {active_sim.get_active_mode_label()}"
            )
            self.breadcrumb_label = f"class: {active_sim.get_vehicle_class()}"

            self.buttons.append(
                UIButton("open_repository", "Open Repository",
                         pygame.Rect(button_x, button_y, button_width, button_height))
            )
            self.buttons.append(
                UIButton("vehicle_mode_design", "Vehicle Design",
                         pygame.Rect(button_x, button_y + 40, button_width, button_height),
                         enabled=active_sim.active_view_mode != "design")
            )
            self.buttons.append(
                UIButton("vehicle_mode_interior", "Interior",
                         pygame.Rect(button_x, button_y + 80, button_width, button_height),
                         enabled=active_sim.active_view_mode != "interior")
            )
            self.buttons.append(
                UIButton("vehicle_mode_operational", "Operational",
                         pygame.Rect(button_x, button_y + 120, button_width, button_height),
                         enabled=active_sim.active_view_mode != "operational")
            )

            payload = active_sim.get_focused_render_payload()

            if active_sim.active_view_mode == "design":
                requirement_status = payload.get("requirement_status", [])
                self.vehicle_requirement_lines = [
                    f"{'[OK]' if entry.get('is_satisfied') else '[ ]'} {entry.get('category', 'requirement')} ({entry.get('source_class', 'vehicle')})"
                    for entry in requirement_status
                ]
                self._rebuild_vehicle_design_panel(active_sim, payload, app_width, app_height)
                return

            self.vehicle_requirement_lines = []

            if active_sim.active_view_mode == "interior":
                blocks_by_id = {block.get("id"): block for block in payload.get("blocks", [])}
                focus_part_id = payload.get("selected_part_id") or payload.get("hover_part_id")
                if focus_part_id in blocks_by_id:
                    block = blocks_by_id[focus_part_id]
                    self.hover_tooltip_lines = [
                        active_sim.get_active_mode_label(),
                        block.get("label", focus_part_id),
                    ]
                    self.hover_tooltip_pos = getattr(active_sim, "hover_screen_pos", None) or (24, 250)
                return

            modules_by_id = {
                module.get("id"): module
                for module in payload.get("operational_modules", [])
            }
            focus_part_id = payload.get("selected_part_id") or payload.get("hover_part_id")

            if focus_part_id in modules_by_id:
                module = modules_by_id[focus_part_id]
                self.hover_tooltip_lines = [
                    "Operational Capability",
                    module.get("group", "General"),
                    module.get("label", focus_part_id),
                    module.get("component_label", "component"),
                    module.get("status_text", "ready"),
                ]
                self.hover_tooltip_pos = getattr(active_sim, "hover_screen_pos", None) or (24, 250)
            else:
                operational_state = payload.get("operational_state", {})
                installed_components = payload.get("installed_components", [])
                self.hover_tooltip_lines = [
                    "Operational Control Center",
                    f"components: {len(installed_components)}",
                    f"task: {operational_state.get('task_state', '?')}",
                    f"power: {operational_state.get('power_state', '?')}",
                    f"crew: {operational_state.get('crew_state', '?')}",
                ]
                self.hover_tooltip_pos = (24, 250)
            return

        self.vehicle_requirement_lines = []

        if render_mode == "map":
            root_name = active_sim.get_root_name() if hasattr(active_sim, "get_root_name") else None
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
                    self.breadcrumb_label = f"{existing_status_line} | {breadcrumb_text}" if existing_status_line else breadcrumb_text
                elif existing_status_line:
                    self.breadcrumb_label = existing_status_line
            elif existing_status_line:
                self.breadcrumb_label = existing_status_line

            self.buttons.append(
                UIButton("open_repository", "Open Repository",
                         pygame.Rect(button_x, button_y, button_width, button_height))
            )

            selected_entity_id = getattr(active_sim, "selected_entity_id", None)
            root_entity_id = getattr(active_sim.context, "root_entity_id", None)

            if selected_entity_id is not None and selected_entity_id != root_entity_id:
                self.buttons.append(
                    UIButton("open_region_map", "Open Region Map",
                             pygame.Rect(button_x, button_y + 40, button_width, button_height))
                )

            parent_root_entity_id = active_sim.get_parent_root_entity_id() if hasattr(active_sim,
                                                                                      "get_parent_root_entity_id") else None
            if parent_root_entity_id is not None:
                self.buttons.append(
                    UIButton("open_parent_region_map", "Up To Parent",
                             pygame.Rect(button_x, button_y + 80, button_width, button_height))
                )

            hover_entity_id = getattr(active_sim, "hover_entity_id", None)
            hover_screen_pos = getattr(active_sim, "hover_screen_pos", None)
            if hover_entity_id and hover_screen_pos:
                entity = active_sim.world_model.get_entity(hover_entity_id)
                if entity:
                    self.hover_tooltip_lines = [
                        entity.get("name", hover_entity_id),
                        f"class: {entity.get('location_class', entity.get('type', 'entity'))}",
                    ]
                    self.hover_tooltip_pos = hover_screen_pos
            return

        if render_mode == "space":
            self.buttons.append(
                UIButton("open_repository", "Open Repository",
                         pygame.Rect(button_x, button_y, button_width, button_height))
            )

            selected_body_entity = active_sim.get_selected_body_entity() if hasattr(active_sim,
                                                                                    "get_selected_body_entity") else None
            if selected_body_entity:
                body_name = selected_body_entity.get("name", selected_body_entity.get("id"))
                body_class = selected_body_entity.get("body_class", "body")
                self.scope_label = f"Selected: {body_name}"
                self.breadcrumb_label = f"class: {body_class}"

                self.buttons.append(
                    UIButton("open_space_body_map", "Open Map",
                             pygame.Rect(button_x, button_y + 40, button_width, button_height))
                )

            hover_body_id = getattr(active_sim, "hover_system_entity_id", None)
            hover_screen_pos = getattr(active_sim, "hover_screen_pos", None)

            if hover_body_id and hover_screen_pos:
                entity = active_sim.world_model.get_entity(hover_body_id)
                if entity:
                    self.hover_tooltip_lines = [
                        entity.get("name", hover_body_id),
                        f"class: {entity.get('body_class', entity.get('type', 'entity'))}",
                    ]
                    self.hover_tooltip_pos = hover_screen_pos
            return

        if render_mode == "bioregion":
            self.scope_label = "Scope: Bioregion Test Map | 10 km x 10 km"

            avg_surface = active_sim.get_average_surface_water()
            avg_top = active_sim.get_average_top_moisture()
            avg_deep = active_sim.get_average_deep_moisture()

            rain_text = "Rain: active" if getattr(active_sim, "is_raining", False) else "Rain: dry"
            self.breadcrumb_label = (
                f"{rain_text} | Avg surf: {avg_surface:.3f} | "
                f"Avg top: {avg_top:.3f} | Avg deep: {avg_deep:.3f}"
            )

            self.buttons.append(
                UIButton("open_repository", "Open Repository",
                         pygame.Rect(button_x, button_y, button_width, button_height))
            )

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
        self._reset_shared_state()
        self.menu_active = menu_active

        if tab_manager is not None:
            self.tab_labels = [tab.name for tab in tab_manager.tabs]
            self.active_tab_index = tab_manager.active_index

        if menu_active:
            self.knowledge_ui.rebuild(
                app_width=app_width,
                app_height=app_height,
                world_model=world_model,
                repository_scope_entity_id=repository_scope_entity_id,
                font=self.app_font,
            )
            return

        self._rebuild_active_simulation_ui(active_sim, app_width, app_height, camera)

    def _draw_simulation_bar(self, screen, font):
        if self.simulation_bar_rect is None:
            return

        pygame.draw.rect(screen, (22, 24, 30), self.simulation_bar_rect)
        pygame.draw.rect(screen, (200, 200, 200), self.simulation_bar_rect, 1)

        if self.simulation_bar_resize_hitbox is not None:
            line_y = self.simulation_bar_rect.y
            pygame.draw.line(
                screen,
                (150, 150, 160),
                (self.simulation_bar_rect.x + 2, line_y),
                (self.simulation_bar_rect.right - 2, line_y),
                2,
            )

        if self.simulation_bar_title:
            title_surface = font.render(self.simulation_bar_title, True, (240, 240, 240))
            screen.blit(title_surface, (self.simulation_bar_rect.x + 12, self.simulation_bar_rect.y + 10))

        self._draw_simulation_panel_tabs(screen, font)

        if self.simulation_panel_active_tab_id == "catalog" and self.simulation_bar_catalog_entries:
            self._draw_simulation_bar_catalog(screen, font)
        elif self.simulation_panel_active_tab_id == "selection":
            self._draw_simulation_panel_placeholder(screen, font, "Selection panel placeholder")
        elif self.simulation_panel_active_tab_id == "layout":
            self._draw_simulation_panel_placeholder(screen, font, "Layout panel placeholder")
        elif self.simulation_bar_catalog_entries:
            self._draw_simulation_bar_catalog(screen, font)

        hint_x = self.simulation_bar_rect.x + int(self.simulation_bar_rect.width * 0.66)
        hint_y = self.simulation_bar_rect.y + 42
        for line in self.simulation_bar_hint_lines:
            text_surface = font.render(line, True, (185, 185, 185))
            screen.blit(text_surface, (hint_x, hint_y))
            hint_y += 18

    def _draw_simulation_panel_tabs(self, screen, font):
        if self.simulation_bar_rect is None or not self.simulation_panel_tabs:
            return

        hitbox_by_id = {
            tab_id: rect
            for tab_id, rect in self.simulation_panel_tab_hitboxes
        }

        for tab in self.simulation_panel_tabs:
            tab_id = tab.get("id")
            rect = hitbox_by_id.get(tab_id)
            if rect is None:
                continue

            label = tab.get("label", tab_id or "tab")
            text_surface = font.render(label, True, (240, 240, 240))
            active = tab_id == self.simulation_panel_active_tab_id

            fill = (70, 70, 90) if active else (36, 40, 48)
            border = (230, 230, 230) if active else (170, 170, 170)

            pygame.draw.rect(screen, fill, rect)
            pygame.draw.rect(screen, border, rect, 1)
            screen.blit(
                text_surface,
                (rect.x + 10, rect.y + (rect.height - text_surface.get_height()) // 2),
            )

    def _draw_simulation_panel_placeholder(self, screen, font, text):
        if self.simulation_bar_rect is None:
            return

        text_surface = font.render(text, True, (210, 210, 210))
        screen.blit(
            text_surface,
            (self.simulation_bar_rect.x + 14, self.simulation_bar_rect.y + 70),
        )

    def _draw_simulation_bar_catalog(self, screen, font):
        mouse_pos = pygame.mouse.get_pos()
        hovered_catalog_id = None

        for catalog_id, hitbox, row in self.simulation_bar_catalog_hitboxes:
            if catalog_id is None:
                continue
            if hitbox.collidepoint(mouse_pos):
                hovered_catalog_id = catalog_id
                break

        active_catalog_id = self.simulation_bar_active_catalog_id

        for catalog_id, hitbox, row in self.simulation_bar_catalog_hitboxes:
            kind = row.get("kind")

            if kind == "section":
                pygame.draw.rect(screen, (40, 44, 54), hitbox)
                pygame.draw.rect(screen, (130, 130, 140), hitbox, 1)
                text_surface = font.render(row.get("label", "Section"), True, (220, 220, 220))
                screen.blit(text_surface, (hitbox.x + 6, hitbox.y + 2))
                continue

            border_color = (170, 170, 170)
            fill_color = (34, 38, 46)

            if row.get("entry_type") == "assembly":
                fill_color = (46, 40, 58)

            if catalog_id == hovered_catalog_id:
                border_color = (120, 220, 255)
                fill_color = (52, 66, 82)

            if catalog_id == active_catalog_id:
                border_color = (255, 230, 120)
                fill_color = (92, 84, 50)

            pygame.draw.rect(screen, fill_color, hitbox)
            pygame.draw.rect(screen, border_color, hitbox, 2)

            body_height = int(row.get("body_height", max(20, hitbox.height - 26)))
            body_rect = pygame.Rect(hitbox.x + 4, hitbox.y + 4, max(8, hitbox.width - 8), max(8, body_height - 4))
            pygame.draw.rect(screen, (70, 74, 86), body_rect, 1)

            dims = row.get("dimensions_m", {})
            line_1 = row.get("label", catalog_id or "component")
            line_2 = row.get("entry_type", "component")
            line_3 = f"{dims.get('x', '?')} x {dims.get('y', '?')}"

            text_surface_1 = font.render(line_1, True, (240, 240, 240))
            text_surface_2 = font.render(line_2, True, (185, 185, 195))
            text_surface_3 = font.render(line_3, True, (165, 165, 175))

            text_y = hitbox.bottom - 34
            screen.blit(text_surface_1, (hitbox.x + 6, text_y))
            screen.blit(text_surface_2, (hitbox.x + 6, text_y + 14))
            screen.blit(text_surface_3, (hitbox.x + 6, text_y + 28))

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

        anchor_x, anchor_y = self.hover_tooltip_pos
        tooltip_x = anchor_x + 14
        tooltip_y = anchor_y + 14

        screen_width = screen.get_width()
        screen_height = screen.get_height()
        margin = 10

        if tooltip_x + panel_width > screen_width - margin:
            tooltip_x = anchor_x - panel_width - 14

        if tooltip_y + panel_height > screen_height - margin:
            tooltip_y = anchor_y - panel_height - 14

        tooltip_x = max(margin, min(tooltip_x, screen_width - panel_width - margin))
        tooltip_y = max(margin, min(tooltip_y, screen_height - panel_height - margin))

        tooltip_rect = pygame.Rect(int(tooltip_x), int(tooltip_y), int(panel_width), int(panel_height))
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

    def draw(self, screen, font):
        self.app_font = font
        self._draw_tab_strip(screen, font)

        if self.menu_active:
            self.knowledge_ui.draw(screen, font, self._draw_button)
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

        current_info_y = 170
        if info_lines:
            self._draw_info_panel(screen, font, 20, current_info_y, info_lines)

            padding = 8
            line_gap = 4
            rendered = [font.render(line, True, (240, 240, 240)) for line in info_lines]
            panel_height = (
                sum(text.get_height() for text in rendered)
                + line_gap * (len(rendered) - 1)
                + padding * 2
            )
            current_info_y += panel_height + 12

        if self.vehicle_requirement_lines:
            requirement_lines = ["Requirements"] + self.vehicle_requirement_lines
            self._draw_info_panel(screen, font, 20, current_info_y, requirement_lines)

        self._draw_simulation_bar(screen, font)
        self._draw_hover_tooltip(screen, font)


    def handle_event(self, event):
        if self.menu_active:
            return self.knowledge_ui.handle_event(event)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse_pos = event.pos

            if self.simulation_bar_resize_hitbox and self.simulation_bar_resize_hitbox.collidepoint(mouse_pos):
                self.simulation_bar_is_resizing = True
                self.simulation_bar_resize_start_y = mouse_pos[1]
                self.simulation_bar_resize_start_height = self.simulation_bar_height
                return "ui_consumed"

            for tab_id, hitbox in self.simulation_panel_tab_hitboxes:
                if hitbox.collidepoint(mouse_pos):
                    return {
                        "id": "simulation_panel_tab_select",
                        "tab_id": tab_id,
                    }

            for catalog_id, hitbox, row in self.simulation_bar_catalog_hitboxes:
                if catalog_id is None:
                    continue
                if hitbox.collidepoint(mouse_pos):
                    return {
                        "id": "vehicle_catalog_select",
                        "catalog_id": catalog_id,
                    }

            for tab_index, hitbox in self.tab_hitboxes:
                if hitbox.collidepoint(mouse_pos):
                    return {
                        "id": "activate_tab",
                        "tab_index": tab_index,
                    }

            for button in self.buttons:
                if not button.visible or not button.enabled:
                    continue

                if button.rect.collidepoint(mouse_pos):
                    return button.id

            return None

        if event.type == pygame.MOUSEMOTION and self.simulation_bar_is_resizing:
            delta_y = self.simulation_bar_resize_start_y - event.pos[1]
            new_height = self.simulation_bar_resize_start_height + delta_y
            self.simulation_bar_height = max(
                self.simulation_bar_min_height,
                min(self.simulation_bar_max_height, new_height),
            )
            return "ui_consumed"

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.simulation_bar_is_resizing:
            self.simulation_bar_is_resizing = False
            return "ui_consumed"

        return None