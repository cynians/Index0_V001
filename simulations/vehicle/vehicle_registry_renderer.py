import pygame


class VehicleRegistryRenderer:
    """Draws the Vehicle Registry screen (see VehicleRegistrySimulation)."""

    COLUMNS = (
        ("serial_number", "SERIAL", 0.08),
        ("version_label", "VERSION", 0.08),
        ("produced_by", "PRODUCER", 0.11),
        ("production_line_id", "LINE", 0.08),
        ("batch_label", "BATCH LABEL", 0.09),
        ("year_constructed", "BUILT", 0.06),
        ("year_destroyed", "LOST", 0.06),
        ("status", "STATUS", 0.10),
        ("fate_notes", "FATE", 0.15),
        ("assigned_faction", "FACTION", 0.09),
        ("current_link_entity_id", "LINK", 0.10),
    )

    RELATION_FIELDS = {"produced_by", "assigned_faction"}

    ROW_HEIGHT = 30
    GROUP_HEADER_HEIGHT = 24
    VERSION_HEADER_HEIGHT = 28
    HEADER_HEIGHT = 24
    PLACEHOLDER_ROW_HEIGHT = 28

    def __init__(self, app_view):
        self.app_view = app_view
        self._text_surface_cache = {}
        self._text_surface_cache_limit = 512

    def _render_text(self, text, color):
        font = self.app_view.default_font
        color = tuple(color)
        cache_key = (id(font), str(text), color)
        cached = self._text_surface_cache.get(cache_key)
        if cached is not None:
            return cached
        surface = font.render(str(text), True, color)
        self._text_surface_cache[cache_key] = surface
        while len(self._text_surface_cache) > self._text_surface_cache_limit:
            self._text_surface_cache.pop(next(iter(self._text_surface_cache)))
        return surface

    def _column_rects(self, row_rect):
        rects = []
        x = row_rect.x
        remaining = row_rect.width
        for index, (field_name, label, fraction) in enumerate(self.COLUMNS):
            width = remaining if index == len(self.COLUMNS) - 1 else int(row_rect.width * fraction)
            rects.append((field_name, label, pygame.Rect(x, row_rect.y, width, row_rect.height)))
            x += width
            remaining -= width
        return rects

    def _draw_button(self, screen, rect, label, primary=False):
        fill = (74, 92, 132) if primary else (40, 46, 60)
        border = (178, 196, 228) if primary else (118, 130, 154)
        pygame.draw.rect(screen, fill, rect, border_radius=4)
        pygame.draw.rect(screen, border, rect, 1, border_radius=4)
        text = self._render_text(label, (238, 242, 248))
        screen.blit(text, text.get_rect(center=rect.center))

    def _status_for_unit(self, sim, unit):
        if unit.get("year_destroyed"):
            return "Destroyed", (222, 150, 150)
        if unit.get("current_link_entity_id"):
            return "Active", (156, 222, 168)
        faction_value = unit.get("assigned_faction")
        if faction_value:
            label = None
            if sim.world_model is not None:
                entity = sim.world_model.get_entity(faction_value)
                if isinstance(entity, dict):
                    label = entity.get("name") or entity.get("pretty_name")
            return f"Assigned: {label or faction_value}", (182, 194, 224)
        return "Unknown", (122, 130, 148)

    def _cell_is_unresolved(self, sim, field_name, value):
        if field_name not in self.RELATION_FIELDS or not value:
            return False
        if sim.world_model is None:
            return True
        entity = sim.world_model.get_entity(value)
        return not isinstance(entity, dict)

    def draw(self, screen, sim):
        screen.fill((16, 18, 24))
        payload = sim.get_registry_payload()

        title = self._render_text(f"VEHICLE REGISTRY  |  {payload['vehicle_name']}", (244, 244, 244))
        screen.blit(title, (34, 20))
        subtitle = self._render_text(
            "Click a cell to edit · producer/faction cells search as you type · + Add Unit creates a quick placeholder",
            (158, 170, 190),
        )
        screen.blit(subtitle, (34, 44))

        panel = pygame.Rect(34, 74, max(600, screen.get_width() - 68), max(300, screen.get_height() - 220))
        pygame.draw.rect(screen, (20, 23, 32), panel)
        pygame.draw.rect(screen, (96, 108, 132), panel, 1)

        header_rect = pygame.Rect(panel.x, panel.y, panel.width, self.HEADER_HEIGHT)
        pygame.draw.rect(screen, (28, 33, 44), header_rect)
        for field_name, label, rect in self._column_rects(header_rect):
            screen.blit(self._render_text(label, (170, 180, 200)), (rect.x + 6, rect.y + 4))

        active_cell = payload.get("active_cell")
        active_buffer = payload.get("active_cell_buffer", "")
        selected_unit_id = payload.get("selected_unit_id")
        picker = payload.get("picker")

        cell_hitboxes = []
        y = header_rect.bottom

        content_bottom = panel.bottom - 8
        clip_rect = pygame.Rect(panel.x, header_rect.bottom, panel.width, max(0, content_bottom - header_rect.bottom))
        previous_clip = screen.get_clip()
        screen.set_clip(clip_rect)

        version_groups = payload.get("version_groups") or []
        picker_anchor_rect = None

        if not version_groups:
            if y + 20 <= content_bottom:
                screen.blit(
                    self._render_text("No units yet -- click + Add Unit below to create the first one.", (150, 160, 178)),
                    (panel.x + 12, y + 10),
                )
            y += 40

        for version_group in version_groups:
            if y + self.VERSION_HEADER_HEIGHT > content_bottom:
                break
            version_rect = pygame.Rect(panel.x, y, panel.width, self.VERSION_HEADER_HEIGHT)
            pygame.draw.rect(screen, (40, 48, 66), version_rect)
            pygame.draw.rect(screen, (86, 100, 128), version_rect, 1)
            screen.blit(
                self._render_text(version_group["version_label"].upper(), (226, 234, 246)),
                (version_rect.x + 8, version_rect.y + 5),
            )
            y += self.VERSION_HEADER_HEIGHT

            inner_x = panel.x + 12
            inner_width = panel.width - 12

            for batch in version_group.get("batches", []):
                if y + self.GROUP_HEADER_HEIGHT > content_bottom:
                    break
                group_rect = pygame.Rect(inner_x, y, inner_width, self.GROUP_HEADER_HEIGHT)
                pygame.draw.rect(screen, (30, 36, 48), group_rect)
                pygame.draw.rect(screen, (66, 78, 98), group_rect, 1)
                screen.blit(
                    self._render_text(f"{batch['label']}  ({len(batch['units'])})", (200, 210, 228)),
                    (group_rect.x + 8, group_rect.y + 3),
                )
                y += self.GROUP_HEADER_HEIGHT

                for unit in batch["units"]:
                    if y + self.ROW_HEIGHT > content_bottom:
                        break
                    row_rect = pygame.Rect(inner_x, y, inner_width, self.ROW_HEIGHT)
                    unit_id = unit.get("id")
                    if unit_id == selected_unit_id:
                        pygame.draw.rect(screen, (36, 44, 58), row_rect)
                    pygame.draw.rect(screen, (52, 60, 76), row_rect, 1)

                    for field_name, _label, cell_rect in self._column_rects(row_rect):
                        if field_name == "status":
                            status_text, status_color = self._status_for_unit(sim, unit)
                            while status_text and self._render_text(status_text, status_color).get_width() > cell_rect.width - 10:
                                status_text = status_text[:-2] + "…" if len(status_text) > 2 else ""
                            screen.blit(self._render_text(status_text, status_color), (cell_rect.x + 6, cell_rect.y + 6))
                            continue

                        is_active = active_cell == (unit_id, field_name)
                        is_picker_open = bool(picker) and picker["unit_id"] == unit_id and picker["field_name"] == field_name
                        if is_active or is_picker_open:
                            pygame.draw.rect(screen, (43, 54, 68), cell_rect.inflate(-2, -2))
                            pygame.draw.rect(screen, (121, 197, 224), cell_rect.inflate(-2, -2), 1)
                            if is_picker_open:
                                picker_anchor_rect = cell_rect
                        raw_value = active_buffer if is_active else unit.get(field_name)
                        shown = "" if raw_value is None else str(raw_value)
                        display = shown + ("|" if is_active else "")
                        if not display:
                            display = "—"
                        unresolved = self._cell_is_unresolved(sim, field_name, shown) and not is_active
                        if unresolved:
                            suffix = " ?"
                            color = (214, 182, 120)
                        elif shown or is_active:
                            suffix = ""
                            color = (224, 230, 240)
                        else:
                            suffix = ""
                            color = (95, 106, 124)
                        # Shrink the value first so a trailing marker (the
                        # unresolved-link "?") always survives truncation
                        # instead of being the first thing clipped off.
                        while display and self._render_text(display + suffix, color).get_width() > cell_rect.width - 10:
                            display = display[:-2] + "…" if len(display) > 2 else ""
                        display += suffix
                        screen.blit(self._render_text(display, color), (cell_rect.x + 6, cell_rect.y + 6))
                        cell_hitboxes.append((unit_id, field_name, cell_rect))

                    y += self.ROW_HEIGHT

        placeholders = payload.get("placeholders") or []
        placeholder_hitboxes = []
        if placeholders:
            if y + 20 <= content_bottom:
                y += 6
                screen.blit(
                    self._render_text(f"NOT YET CATALOGUED ({len(placeholders)})", (170, 176, 190)),
                    (panel.x + 8, y),
                )
                y += 20
            for index, placeholder in enumerate(placeholders):
                if y + self.PLACEHOLDER_ROW_HEIGHT > content_bottom:
                    break
                row_rect = pygame.Rect(panel.x, y, panel.width, self.PLACEHOLDER_ROW_HEIGHT)
                pygame.draw.rect(screen, (26, 29, 38), row_rect)
                pygame.draw.rect(screen, (56, 62, 76), row_rect, 1, border_radius=3)
                name = placeholder.get("name") or "(unnamed)"
                screen.blit(self._render_text(name, (176, 184, 200)), (row_rect.x + 10, row_rect.y + 6))
                create_rect = pygame.Rect(row_rect.right - 130, row_rect.y + 3, 122, row_rect.height - 6)
                self._draw_button(screen, create_rect, "Create Unit →")
                placeholder_hitboxes.append((index, create_rect))
                y += self.PLACEHOLDER_ROW_HEIGHT + 4

        screen.set_clip(previous_clip)

        sim.set_cell_hitboxes(cell_hitboxes)
        sim.set_placeholder_hitboxes(placeholder_hitboxes)

        picker_row_hitboxes = []
        if picker is not None:
            anchor_rect = picker_anchor_rect or pygame.Rect(panel.x + 12, panel.y + 40, 240, self.ROW_HEIGHT)
            picker_row_hitboxes = self._draw_picker(screen, picker, anchor_rect)
        sim.set_picker_row_hitboxes(picker_row_hitboxes)

        add_placeholder_rect = pygame.Rect(panel.x, panel.bottom + 12, 140, 32)
        back_rect = pygame.Rect(add_placeholder_rect.right + 12, panel.bottom + 12, 92, 32)
        self._draw_button(screen, add_placeholder_rect, "+ Add Unit", primary=True)
        self._draw_button(screen, back_rect, "Back")
        sim.set_registry_button_rects(add_placeholder_rect=add_placeholder_rect, back_rect=back_rect)

    def _draw_picker(self, screen, picker, anchor_rect):
        matches = picker.get("matches") or []
        visible_rows = min(6, len(matches) + 1)
        picker_w = max(260, anchor_rect.width + 60)
        picker_h = 32 + visible_rows * 28 + 8
        picker_rect = pygame.Rect(anchor_rect.x, anchor_rect.bottom + 4, picker_w, picker_h)
        screen_rect = screen.get_rect()
        picker_rect.x = max(8, min(picker_rect.x, screen_rect.right - picker_rect.width - 8))
        if picker_rect.bottom > screen_rect.bottom - 8:
            picker_rect.y = max(8, anchor_rect.y - picker_rect.height - 4)

        pygame.draw.rect(screen, (22, 26, 36), picker_rect)
        pygame.draw.rect(screen, (186, 194, 210), picker_rect, 1)

        query_rect = pygame.Rect(picker_rect.x + 8, picker_rect.y + 6, picker_rect.width - 16, 22)
        pygame.draw.rect(screen, (30, 34, 44), query_rect)
        query_text = picker.get("query", "")
        screen.blit(self._render_text(query_text + "|", (224, 230, 240)), (query_rect.x + 6, query_rect.y + 3))

        hitboxes = []
        selected_index = picker.get("selected_index", 0)
        row_y = query_rect.bottom + 4
        for index, match in enumerate(matches):
            row_rect = pygame.Rect(picker_rect.x + 6, row_y, picker_rect.width - 12, 26)
            if index == selected_index:
                pygame.draw.rect(screen, (52, 66, 88), row_rect, border_radius=3)
            screen.blit(self._render_text(match["label"], (220, 226, 236)), (row_rect.x + 6, row_rect.y + 4))
            hitboxes.append((index, row_rect))
            row_y += 28

        use_index = len(matches)
        use_row_rect = pygame.Rect(picker_rect.x + 6, row_y, picker_rect.width - 12, 26)
        if selected_index == use_index:
            pygame.draw.rect(screen, (52, 66, 88), use_row_rect, border_radius=3)
        use_label = f'Use "{query_text}"' if query_text else "Type a name to add an unresolved link"
        use_color = (214, 182, 120) if query_text else (120, 128, 144)
        screen.blit(self._render_text(use_label, use_color), (use_row_rect.x + 6, use_row_rect.y + 4))
        hitboxes.append((use_index, use_row_rect))

        return hitboxes
