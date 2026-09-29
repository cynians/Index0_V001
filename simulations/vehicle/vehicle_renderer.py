import pygame


class VehicleRenderer:
    """
    Handles rendering for vehicle simulations.
    """

    def __init__(self, app_view):
        self.app_view = app_view
        self._text_surface_cache = {}
        self._text_surface_cache_limit = 256
        self._paint_surface_cache = {}
        self._hex_color_cache = {}

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

    def _world_rect_to_screen(self, camera, rect_data):
        top_left = camera.world_to_screen((rect_data["x"], rect_data["y"]))
        bottom_right = camera.world_to_screen(
            (rect_data["x"] + rect_data["width"], rect_data["y"] + rect_data["height"])
        )

        if top_left is None or bottom_right is None:
            return None

        left = min(top_left[0], bottom_right[0])
        right = max(top_left[0], bottom_right[0])
        top = min(top_left[1], bottom_right[1])
        bottom = max(top_left[1], bottom_right[1])

        return pygame.Rect(left, top, right - left, bottom - top)

    def _draw_design_or_interior(self, screen, sim, camera, payload):
        base_rect = self._world_rect_to_screen(camera, payload["base_rect"])
        if base_rect is None:
            return

        pygame.draw.rect(screen, (30, 34, 42), base_rect)
        pygame.draw.rect(screen, (215, 215, 215), base_rect, 3)

        for block in payload.get("blocks", []):
            block_rect = self._world_rect_to_screen(camera, block)
            if block_rect is None:
                continue

            part_id = block.get("id")
            border_color = (170, 170, 170)
            fill_color = (52, 62, 82)

            if part_id == payload.get("hover_part_id"):
                border_color = (120, 220, 255)
                fill_color = (62, 84, 108)

            if part_id == payload.get("selected_part_id"):
                border_color = (255, 230, 120)
                fill_color = (104, 96, 56)

            pygame.draw.rect(screen, fill_color, block_rect)
            pygame.draw.rect(screen, border_color, block_rect, 2)

            if block_rect.width >= 72 and block_rect.height >= 24:
                text_surface = self._render_text(
                    block.get("label", part_id or "part"),
                    (240, 240, 240),
                )
                text_rect = text_surface.get_rect(center=block_rect.center)
                screen.blit(text_surface, text_rect)

        drag_preview = payload.get("drag_preview_block")
        if drag_preview is not None:
            preview_rect = self._world_rect_to_screen(camera, drag_preview)
            if preview_rect is not None:
                preview_fill = pygame.Surface((max(1, preview_rect.width), max(1, preview_rect.height)), pygame.SRCALPHA)
                preview_fill.fill((120, 220, 255, 70))
                screen.blit(preview_fill, preview_rect.topleft)
                pygame.draw.rect(screen, (120, 220, 255), preview_rect, 2)

                if preview_rect.width >= 72 and preview_rect.height >= 24:
                    text_surface = self._render_text(
                        drag_preview.get("label", "preview"),
                        (240, 240, 240),
                    )
                    text_rect = text_surface.get_rect(center=preview_rect.center)
                    screen.blit(text_surface, text_rect)

    @staticmethod
    def _orthographic_layout(screen, sim, payload):
        right_reserved = 230
        bottom_reserved = 300
        margin = 18
        gap = 12
        usable = pygame.Rect(
            margin,
            92,
            max(420, screen.get_width() - right_reserved - margin * 2),
            max(260, screen.get_height() - bottom_reserved - 104),
        )
        design_step = payload.get("design_step", "hull")
        if design_step == "liveries":
            usable.x += 194
            usable.width = max(240, usable.width - 194)
        cell_w = max(96, (usable.width - gap * 3) // 4)
        cell_h = max(74, (usable.height - gap * 2) // 3)
        # Cube-net arrangement: projections occupy the direction they describe.
        # Rear continues past the right face so every view remains visible.
        positions = {
            "top": (1, 0),
            "left": (0, 1),
            "front": (1, 1),
            "right": (2, 1),
            "rear": (3, 1),
            "bottom": (1, 2),
        }
        view_rects = {}
        dims = payload.get("vehicle_dimensions_m", {})
        definitions = sim.design.ORTHOGRAPHIC_VIEWS
        focused_view_id = (
            payload.get("selected_hull_view_id")
            if payload.get("hull_focus_mode") or design_step in {"details", "liveries"}
            else None
        )
        if focused_view_id in definitions:
            axis_u, axis_v = definitions[focused_view_id]["axes"]
            aspect = max(0.1, float(dims.get(axis_u, 1.0))) / max(0.1, float(dims.get(axis_v, 1.0)))
            max_w = max(20, usable.width - 24)
            max_h = max(20, usable.height - 42)
            draw_w = min(max_w, int(max_h * aspect))
            draw_h = min(max_h, int(max_w / aspect))
            grid_rect = pygame.Rect(0, 0, max(20, draw_w), max(20, draw_h))
            grid_rect.center = usable.center
            return {focused_view_id: grid_rect.inflate(12, 28)}

        for view_id, (column_index, row_index) in positions.items():
            cell = pygame.Rect(
                usable.x + column_index * (cell_w + gap),
                usable.y + row_index * (cell_h + gap),
                cell_w,
                cell_h,
            )
            axis_u, axis_v = definitions[view_id]["axes"]
            aspect = max(0.1, float(dims.get(axis_u, 1.0))) / max(0.1, float(dims.get(axis_v, 1.0)))
            max_w = max(20, cell.width - 14)
            max_h = max(20, cell.height - 34)
            draw_w = min(max_w, int(max_h * aspect))
            draw_h = min(max_h, int(max_w / aspect))
            grid_rect = pygame.Rect(0, 0, max(20, draw_w), max(20, draw_h))
            grid_rect.centerx = cell.centerx
            grid_rect.centery = cell.y + 22 + max_h // 2
            view_rects[view_id] = grid_rect.inflate(12, 28)
        return view_rects

    @staticmethod
    def _projection_source_grid(definitions, primary_id, fallback_id):
        primary = definitions.get(primary_id, {}).get("grid", [])
        if primary and any(any(row) for row in primary):
            return primary
        return definitions.get(fallback_id, {}).get("grid", [])

    def _draw_assembled_projection(self, screen, sim, payload, view_rects):
        if payload.get("hull_focus_mode"):
            return
        anchor = view_rects.get("right")
        rear = view_rects.get("rear")
        top = view_rects.get("top")
        if anchor is None or rear is None or top is None:
            return
        panel = pygame.Rect(anchor.x, top.y, rear.right - anchor.x, max(100, top.height))
        pygame.draw.rect(screen, (19, 23, 30), panel, border_radius=4)
        pygame.draw.rect(screen, (70, 84, 105), panel, 1, border_radius=4)
        screen.blit(self._render_text("ASSEMBLED PROJECTION", (195, 204, 220)), (panel.x + 7, panel.y + 5))
        screen.blit(self._render_text("three intersecting silhouette planes", (115, 128, 149)), (panel.x + 7, panel.y + 23))

        definitions = payload.get("orthographic_views", {})
        dims = payload.get("vehicle_dimensions_m", {})
        length = max(0.1, float(dims.get("x", 1.0)))
        width = max(0.1, float(dims.get("y", 1.0)))
        height = max(0.1, float(dims.get("z", 1.0)))
        scale = min(
            (panel.width - 40) / max(0.1, length + width),
            (panel.height - 48) / max(0.1, height * 0.55 + (length + width) * 0.18),
        )
        origin = (panel.centerx, panel.centery + int((length + width) * scale * 0.04) + 12)

        def project(x, y, z):
            return (
                int(origin[0] + (x - y) * scale),
                int(origin[1] + (x + y) * scale * 0.18 - z * scale * 0.55),
            )

        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)

        def draw_grid_plane(grid, plane, color):
            rows = len(grid)
            columns = len(grid[0]) if rows else 0
            if not rows or not columns:
                return
            for row_index, row in enumerate(grid):
                for column_index, filled in enumerate(row):
                    if not filled:
                        continue
                    if plane == "top":
                        x0 = -length / 2.0 + column_index * length / columns
                        x1 = -length / 2.0 + (column_index + 1) * length / columns
                        y0 = width / 2.0 - (row_index + 1) * width / rows
                        y1 = width / 2.0 - row_index * width / rows
                        corners = (project(x0, y0, 0.0), project(x1, y0, 0.0), project(x1, y1, 0.0), project(x0, y1, 0.0))
                    elif plane == "side":
                        x0 = -length / 2.0 + column_index * length / columns
                        x1 = -length / 2.0 + (column_index + 1) * length / columns
                        z0 = height / 2.0 - (row_index + 1) * height / rows
                        z1 = height / 2.0 - row_index * height / rows
                        corners = (project(x0, 0.0, z0), project(x1, 0.0, z0), project(x1, 0.0, z1), project(x0, 0.0, z1))
                    else:
                        y0 = -width / 2.0 + column_index * width / columns
                        y1 = -width / 2.0 + (column_index + 1) * width / columns
                        z0 = height / 2.0 - (row_index + 1) * height / rows
                        z1 = height / 2.0 - row_index * height / rows
                        corners = (project(0.0, y0, z0), project(0.0, y1, z0), project(0.0, y1, z1), project(0.0, y0, z1))
                    pygame.draw.polygon(overlay, color, corners)

        top_grid = self._projection_source_grid(definitions, "top", "bottom")
        side_grid = self._projection_source_grid(definitions, "right", "left")
        front_grid = self._projection_source_grid(definitions, "front", "rear")
        draw_grid_plane(top_grid, "top", (96, 185, 205, 105))
        draw_grid_plane(side_grid, "side", (235, 187, 95, 130))
        draw_grid_plane(front_grid, "front", (172, 124, 218, 125))
        pygame.draw.line(overlay, (224, 232, 242, 190), project(-length / 2.0, 0.0, 0.0), project(length / 2.0, 0.0, 0.0), 1)
        pygame.draw.line(overlay, (224, 232, 242, 190), project(0.0, -width / 2.0, 0.0), project(0.0, width / 2.0, 0.0), 1)
        pygame.draw.line(overlay, (224, 232, 242, 190), project(0.0, 0.0, -height / 2.0), project(0.0, 0.0, height / 2.0), 1)
        screen.blit(overlay, (0, 0))

    @staticmethod
    def _draw_dashed_line(surface, color, start, end, dash=6, gap=5, width=1):
        x1, y1 = start
        x2, y2 = end
        length = max(1.0, ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)
        dx, dy = (x2 - x1) / length, (y2 - y1) / length
        distance = 0.0
        while distance < length:
            segment_end = min(length, distance + dash)
            pygame.draw.line(
                surface, color,
                (round(x1 + dx * distance), round(y1 + dy * distance)),
                (round(x1 + dx * segment_end), round(y1 + dy * segment_end)),
                width,
            )
            distance += dash + gap

    def _draw_blueprint_grid(self, screen, rect, dimensions, axes, focused=False):
        axis_u, axis_v = axes
        dim_u = max(0.1, float(dimensions.get(axis_u, 1.0)))
        dim_v = max(0.1, float(dimensions.get(axis_v, 1.0)))
        minor = (29, 53, 70)
        major = (38, 72, 91)
        center = (77, 126, 145)
        step_u = max(1, int(dim_u / 24) + 1)
        step_v = max(1, int(dim_v / 16) + 1)
        for meter in range(0, int(dim_u) + 1, step_u):
            x = rect.x + round(meter / dim_u * rect.width)
            pygame.draw.line(screen, major if meter % 5 == 0 else minor, (x, rect.top), (x, rect.bottom), 1)
        for meter in range(0, int(dim_v) + 1, step_v):
            y = rect.bottom - round(meter / dim_v * rect.height)
            pygame.draw.line(screen, major if meter % 5 == 0 else minor, (rect.left, y), (rect.right, y), 1)
        self._draw_dashed_line(screen, center, (rect.left, rect.centery), (rect.right, rect.centery), 8, 5)
        self._draw_dashed_line(screen, center, (rect.centerx, rect.top), (rect.centerx, rect.bottom), 8, 5)
        if focused:
            screen.blit(self._render_text(f"0", (92, 132, 151)), (rect.x + 4, rect.bottom - 18))
            extent = self._render_text(f"{dim_u:g} m", (114, 158, 177))
            screen.blit(extent, (rect.right - extent.get_width() - 5, rect.bottom - 18))

    def _draw_hull_raster(self, screen, grid_rect, grid, guide=False, stage="hull"):
        rows = len(grid)
        columns = len(grid[0]) if rows else 0
        if not rows or not columns:
            return
        if stage == "hull":
            fill_rgba = (57, 174, 203, 22) if not guide else (130, 142, 151, 10)
            edge = (101, 221, 241) if not guide else (104, 116, 126)
        elif stage == "liveries":
            fill_rgba = (78, 91, 105, 105)
            edge = (112, 143, 158)
        elif stage == "details":
            fill_rgba = (67, 111, 128, 125)
            edge = (104, 181, 202)
        else:
            fill_rgba = (62, 148, 169, 105)
            edge = (101, 205, 226)
        overlay = pygame.Surface((grid_rect.width, grid_rect.height), pygame.SRCALPHA)
        for grid_y, row in enumerate(grid):
            for grid_x, filled in enumerate(row):
                if not filled:
                    continue
                draw_x = columns - 1 - grid_x if guide else grid_x
                x1 = round(draw_x * grid_rect.width / columns)
                x2 = round((draw_x + 1) * grid_rect.width / columns)
                y1 = round(grid_y * grid_rect.height / rows)
                y2 = round((grid_y + 1) * grid_rect.height / rows)
                pygame.draw.rect(overlay, fill_rgba, pygame.Rect(x1, y1, max(1, x2 - x1), max(1, y2 - y1)))
                source_x = grid_x
                neighbors = (
                    (source_x == 0 or not row[source_x - 1], (x1, y1), (x1, y2)),
                    (source_x == columns - 1 or not row[source_x + 1], (x2, y1), (x2, y2)),
                    (grid_y == 0 or source_x >= len(grid[grid_y - 1]) or not grid[grid_y - 1][source_x], (x1, y1), (x2, y1)),
                    (grid_y == rows - 1 or source_x >= len(grid[grid_y + 1]) or not grid[grid_y + 1][source_x], (x1, y2), (x2, y2)),
                )
                for is_edge, start, end in neighbors:
                    if is_edge:
                        pygame.draw.line(overlay, (*edge, 225 if not guide else 120), start, end, 1)
        screen.blit(overlay, grid_rect.topleft)

    def _parse_hex_color(self, value):
        if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
            return None
        if value in self._hex_color_cache:
            return self._hex_color_cache[value]
        try:
            color = tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))
        except ValueError:
            return None
        self._hex_color_cache[value] = color
        return color

    def _paint_layer_surface(self, sim, payload, layer_kind, view_id, local_layer, opposite_layer):
        height = len(local_layer)
        width = len(local_layer[0]) if height else 0
        if not width or not height:
            return None
        cache_key = (
            layer_kind, view_id, payload.get("active_livery_id"),
            width, height, id(local_layer), id(opposite_layer),
        )
        cached = self._paint_surface_cache.get(cache_key)
        mask = sim.design.get_paint_mask(layer_kind, view_id)
        opposite_height = len(opposite_layer)
        opposite_width = len(opposite_layer[0]) if opposite_height else 0
        dirty_region = sim.design.consume_paint_dirty_region(layer_kind, view_id) if cached is not None else None

        def pixel_value(x, y):
            if y >= len(mask) or x >= len(mask[y]) or not mask[y][x]:
                return 0, 0, 0, 0
            color = self._parse_hex_color(local_layer[y][x] if x < len(local_layer[y]) else None)
            alpha = 255
            if color is None and y < opposite_height and opposite_width:
                mirrored_x = min(opposite_width - 1, max(0, opposite_width - 1 - round(x * opposite_width / width)))
                opposite_color = self._parse_hex_color(opposite_layer[y][mirrored_x])
                if opposite_color is not None:
                    color = tuple(int(channel * 0.34 + 34) for channel in opposite_color)
                    alpha = 118
            return (*color, alpha) if color is not None else (0, 0, 0, 0)

        if cached is not None:
            if dirty_region is not None:
                x1, y1, x2, y2 = dirty_region
                for y in range(max(0, y1), min(height - 1, y2) + 1):
                    for x in range(max(0, x1), min(width - 1, x2) + 1):
                        cached.set_at((x, y), pixel_value(x, y))
            return cached

        pixels = bytearray(width * height * 4)
        for y in range(height):
            for x in range(width):
                color = pixel_value(x, y)
                if color[3] == 0:
                    continue
                offset = (y * width + x) * 4
                pixels[offset:offset + 4] = bytes(color)
        surface = pygame.image.frombuffer(bytes(pixels), (width, height), "RGBA").copy()
        self._paint_surface_cache = {cache_key: surface}
        return surface

    def _draw_specifications(self, screen, sim, payload):
        sim.set_orthographic_view_rects({})
        screen.blit(self._render_text("1  VEHICLE SPECIFICATION", (235, 239, 247)), (20, 48))
        screen.blit(self._render_text(
            "Click any field and type · leave unknown values blank · Enter saves the current edit",
            (145, 158, 180),
        ), (20, 69))

        available = pygame.Rect(20, 104, max(620, screen.get_width() - 270), max(320, screen.get_height() - 410))
        gap = 12
        metadata_w = int(available.width * 0.27)
        characteristic_w = int(available.width * 0.34)
        panels = {
            "metadata": pygame.Rect(available.x, available.y, metadata_w, available.height),
            "characteristic": pygame.Rect(available.x + metadata_w + gap, available.y, characteristic_w, available.height),
            "requirement": pygame.Rect(
                available.x + metadata_w + characteristic_w + gap * 2,
                available.y,
                available.width - metadata_w - characteristic_w - gap * 2,
                available.height,
            ),
        }
        titles = {
            "metadata": "IDENTITY & METADATA",
            "characteristic": "CHARACTERISTICS",
            "requirement": "DESIGN REQUIREMENTS",
        }
        spec = payload.get("specifications", {})
        active_cell = payload.get("specification_active_cell")
        selected_row = payload.get("specification_selected_row")
        hitboxes = []

        def draw_panel(panel, title):
            pygame.draw.rect(screen, (21, 25, 33), panel, border_radius=4)
            pygame.draw.rect(screen, (70, 82, 102), panel, 1, border_radius=4)
            screen.blit(self._render_text(title, (195, 204, 220)), (panel.x + 10, panel.y + 10))

        def draw_field(row_kind, row_id, field_name, label, value, rect):
            is_active = active_cell == (row_kind, row_id, field_name)
            pygame.draw.rect(screen, (31, 38, 49) if not is_active else (43, 54, 68), rect, border_radius=3)
            pygame.draw.rect(screen, (75, 91, 112) if not is_active else (121, 197, 224), rect, 1, border_radius=3)
            screen.blit(self._render_text(label.upper(), (112, 125, 146)), (rect.x + 6, rect.y + 4))
            shown = str(value or "")
            clipped = False
            while shown and self._render_text(shown + (" |" if is_active else ""), (224, 230, 240)).get_width() > rect.width - 12:
                clipped = True
                shown = shown[1:] if is_active else shown[:-1]
            if clipped and not is_active and len(shown) > 2:
                shown = shown[:-2] + "…"
            display = shown + (" |" if is_active else "")
            if not display:
                display = "unknown / not set"
            screen.blit(self._render_text(display, (224, 230, 240) if value or is_active else (91, 104, 124)), (rect.x + 6, rect.y + 22))
            hitboxes.append((row_kind, row_id, field_name, rect.copy()))

        for panel_kind, panel in panels.items():
            draw_panel(panel, titles[panel_kind])

        metadata_rows = (
            ("name", "Name"),
            ("vehicle_class", "Vehicle class"),
            ("manufacturer_name", "Manufacturer"),
            ("description", "Description"),
        )
        meta_panel = panels["metadata"]
        for index, (field_name, label) in enumerate(metadata_rows):
            rect = pygame.Rect(meta_panel.x + 10, meta_panel.y + 38 + index * 64, meta_panel.width - 20, 54)
            draw_field("metadata", None, field_name, label, spec.get("metadata", {}).get(field_name, ""), rect)

        def draw_rows(row_kind, rows, fields):
            panel = panels[row_kind]
            row_h = 76
            max_rows = max(1, (panel.height - 58) // row_h)
            offset = max(0, int(payload.get("specification_page_offsets", {}).get(row_kind, 0)))
            visible_rows = rows[offset:offset + max_rows]
            for index, row in enumerate(visible_rows):
                row_id = row.get("id")
                row_rect = pygame.Rect(panel.x + 8, panel.y + 36 + index * row_h, panel.width - 16, row_h - 6)
                if selected_row == (row_kind, row_id):
                    pygame.draw.rect(screen, (57, 50, 33), row_rect, border_radius=3)
                    pygame.draw.rect(screen, (203, 169, 86), row_rect, 1, border_radius=3)
                cell_gap = 5
                widths = [max(42, int((row_rect.width - cell_gap * (len(fields) + 1)) * fraction)) for _, _, fraction in fields]
                width_delta = row_rect.width - cell_gap * (len(fields) + 1) - sum(widths)
                widths[-1] += width_delta
                x = row_rect.x + cell_gap
                for (field_name, label, _fraction), width in zip(fields, widths):
                    rect = pygame.Rect(x, row_rect.y + 7, width, row_rect.height - 14)
                    draw_field(row_kind, row_id, field_name, label, row.get(field_name, ""), rect)
                    x += width + cell_gap
            if len(rows) > max_rows:
                end = min(len(rows), offset + len(visible_rows))
                screen.blit(self._render_text(f"rows {offset + 1}–{end} of {len(rows)}", (139, 151, 170)), (panel.x + 10, panel.bottom - 22))

        draw_rows("characteristic", spec.get("characteristics", []), (
            ("label", "Field", 0.34), ("value", "Value", 0.29), ("unit", "Unit", 0.15), ("category", "Group", 0.22),
        ))
        draw_rows("requirement", spec.get("requirements", []), (
            ("label", "Requirement", 0.31), ("target", "Target", 0.25), ("unit", "Unit", 0.12), ("priority", "Pri", 0.14), ("notes", "Notes", 0.18),
        ))
        sim.set_specification_hitboxes(hitboxes)

    def _draw_orthographic_design(self, screen, sim, payload):
        if payload.get("design_step") == "specifications":
            self._draw_specifications(screen, sim, payload)
            return
        view_rects = self._orthographic_layout(screen, sim, payload)
        sim.set_orthographic_view_rects(view_rects)
        definitions = payload.get("orthographic_views", {})
        design_step = payload.get("design_step", "hull")
        selected_id = payload.get("selected_part_id")

        title_by_step = {
            "hull": "2  HULL SILHOUETTES",
            "components": "3  COMPONENT COORDINATES",
            "details": "4  STRUCTURAL DETAILS",
            "liveries": "5  LIVERIES",
        }
        title = title_by_step.get(design_step, "VEHICLE DESIGNER")
        if design_step == "hull":
            subtitle = "Draw · right-click erase · double-click a view to enlarge · opposite views appear as guides"
        elif design_step == "components":
            subtitle = "Place in any view · then use a crossing view to resolve the remaining coordinate"
        elif design_step == "details":
            subtitle = "Paint structural detail · opposite-side marks appear dimmed · component overlay is optional"
        else:
            selected_resolution = payload.get("livery_resolution", {}).get(payload.get("selected_hull_view_id"), (0, 0))
            subtitle = f"Micro-pixel paint · {selected_resolution[0]} × {selected_resolution[1]} cells · hard-clipped to the structural silhouette"
        screen.blit(self._render_text(title, (235, 239, 247)), (20, 48))
        screen.blit(self._render_text(subtitle, (145, 158, 180)), (20, 69))

        stage_labels = (("SPEC", "specifications"), ("HULL", "hull"), ("SYSTEMS", "components"), ("DETAIL", "details"), ("LIVERY", "liveries"))
        chip_x = max(420, screen.get_width() - 660)
        for index, (stage_label, stage_id) in enumerate(stage_labels):
            chip = pygame.Rect(chip_x + index * 74, 45, 68, 22)
            active = stage_id == design_step
            pygame.draw.rect(screen, (48, 94, 116) if active else (25, 31, 41), chip, border_radius=11)
            pygame.draw.rect(screen, (105, 207, 230) if active else (58, 70, 88), chip, 1, border_radius=11)
            text_surface = self._render_text(stage_label, (225, 241, 247) if active else (111, 124, 145))
            screen.blit(text_surface, text_surface.get_rect(center=chip.center))

        if design_step == "components" and payload.get("systems_view_mode") == "diagram":
            sim.set_orthographic_view_rects({})
            self._draw_system_diagram(screen, sim, payload)
            return

        for view_id, outer in view_rects.items():
            view = definitions.get(view_id, {})
            grid_rect = outer.inflate(-12, -28)
            selected_view = view_id == payload.get("selected_hull_view_id")
            pygame.draw.rect(screen, (15, 25, 34) if design_step == "hull" else (21, 25, 33), outer, border_radius=4)
            pygame.draw.rect(
                screen,
                (116, 190, 220) if selected_view else (70, 82, 102),
                outer,
                2 if selected_view else 1,
                border_radius=3,
            )
            label = view.get("label", view_id.upper())
            axes = view.get("axes", ("x", "y"))
            screen.blit(self._render_text(f"{label}   {axes[0].upper()} / {axes[1].upper()}", (195, 204, 220)), (outer.x + 6, outer.y + 4))
            canvas_color = (6, 24, 35) if design_step in {"hull", "components"} else (11, 15, 22)
            pygame.draw.rect(screen, canvas_color, grid_rect)
            self._draw_blueprint_grid(
                screen, grid_rect, payload.get("vehicle_dimensions_m", {}), axes,
                focused=len(view_rects) == 1,
            )
            pygame.draw.rect(screen, (75, 118, 137) if design_step == "hull" else (91, 105, 128), grid_rect, 1)

            grid = view.get("grid", [])
            rows = len(grid)
            columns = len(grid[0]) if rows else 0
            if rows and columns:
                opposite_id = sim.design.ORTHOGRAPHIC_VIEWS[view_id]["opposite"]
                opposite = definitions.get(opposite_id, {}).get("grid", [])
                has_local = any(any(row) for row in grid)
                show_guide = not has_local and any(any(row) for row in opposite)
                source_grid = opposite if show_guide else grid
                source_rows = len(source_grid)
                source_columns = len(source_grid[0]) if source_rows else 0
                self._draw_hull_raster(screen, grid_rect, source_grid, guide=show_guide, stage=design_step)
                if show_guide:
                    guide = self._render_text(f"REFERENCE · MIRRORED {opposite_id.upper()}", (120, 139, 150))
                    screen.blit(guide, (grid_rect.x + 5, grid_rect.bottom - 20))

                if design_step in {"details", "liveries"}:
                    if design_step == "details":
                        local_layer = payload.get("detail_layers", {}).get(view_id, [])
                        opposite_layer = payload.get("detail_layers", {}).get(opposite_id, [])
                    else:
                        local_layer = payload.get("active_livery_layers", {}).get(view_id, [])
                        opposite_layer = payload.get("active_livery_layers", {}).get(opposite_id, [])

                    paint_surface = self._paint_layer_surface(
                        sim, payload, design_step, view_id, local_layer, opposite_layer,
                    )
                    if paint_surface is not None:
                        scaled = pygame.transform.scale(paint_surface, grid_rect.size)
                        screen.blit(scaled, grid_rect.topleft)
                    pygame.draw.rect(screen, (105, 185, 202), grid_rect, 1)

            if design_step not in {"components", "details", "liveries"}:
                continue
            if design_step in {"details", "liveries"} and not payload.get("show_paint_components", True):
                continue
            axis_u, axis_v = axes
            dims = payload.get("vehicle_dimensions_m", {})
            for block in view.get("components", []):
                u = float(block.get("u", 0.0)) / max(0.01, float(dims.get(axis_u, 1.0)))
                v = float(block.get("v", 0.0)) / max(0.01, float(dims.get(axis_v, 1.0)))
                width_fraction = float(block.get("width", 1.0)) / max(0.01, float(dims.get(axis_u, 1.0)))
                height_fraction = float(block.get("height", 1.0)) / max(0.01, float(dims.get(axis_v, 1.0)))
                if sim.design.ORTHOGRAPHIC_VIEWS[view_id].get("flip_x"):
                    u = 1.0 - u
                rect = pygame.Rect(
                    grid_rect.x + int((u - width_fraction / 2.0) * grid_rect.width),
                    grid_rect.y + int((1.0 - v - height_fraction / 2.0) * grid_rect.height),
                    max(8, int(width_fraction * grid_rect.width)),
                    max(8, int(height_fraction * grid_rect.height)),
                )
                selected = block.get("id") == selected_id
                paint_screen = design_step in {"details", "liveries"}
                if paint_screen:
                    component_overlay = pygame.Surface((max(1, rect.width), max(1, rect.height)), pygame.SRCALPHA)
                    component_overlay.fill((224, 205, 129, 22) if selected else (115, 190, 220, 16))
                    screen.blit(component_overlay, rect.topleft)
                    border = (93, 84, 59) if selected else (47, 68, 78)
                    pygame.draw.rect(screen, border, rect, 1, border_radius=2)
                else:
                    fill = (118, 91, 47) if selected else (50, 91, 116)
                    border = (255, 218, 126) if selected else (124, 203, 235)
                    pygame.draw.rect(screen, fill, rect, border_radius=2)
                    pygame.draw.rect(screen, border, rect, 2 if selected else 1, border_radius=2)
                undefined_axis = block.get("undefined_axis")
                if undefined_axis in axes:
                    if axes.index(undefined_axis) == 0:
                        pygame.draw.line(screen, (164, 174, 190), (grid_rect.left, rect.centery), (grid_rect.right, rect.centery), 1)
                    else:
                        pygame.draw.line(screen, (164, 174, 190), (rect.centerx, grid_rect.top), (rect.centerx, grid_rect.bottom), 1)
                if rect.width > 52 and not paint_screen:
                    name = self._render_text(block.get("label", "component"), (242, 245, 250))
                    screen.blit(name, name.get_rect(center=rect.center))

        if design_step == "hull":
            self._draw_assembled_projection(screen, sim, payload, view_rects)

        if design_step == "liveries":
            library_rect = pygame.Rect(18, 92, 182, max(260, screen.get_height() - 404))
            pygame.draw.rect(screen, (17, 22, 30), library_rect, border_radius=6)
            pygame.draw.rect(screen, (65, 82, 104), library_rect, 1, border_radius=6)
            screen.blit(self._render_text("LIVERY LIBRARY", (224, 230, 240)), (library_rect.x + 10, library_rect.y + 10))
            lock_rect = pygame.Rect(library_rect.x + 8, library_rect.y + 32, library_rect.width - 16, 25)
            pygame.draw.rect(screen, (27, 68, 61), lock_rect, border_radius=3)
            pygame.draw.rect(screen, (67, 151, 131), lock_rect, 1, border_radius=3)
            lock_text = self._render_text("◆ SILHOUETTE LOCKED", (148, 222, 200))
            screen.blit(lock_text, lock_text.get_rect(center=lock_rect.center))
            hitboxes = []
            row_y = library_rect.y + 68
            for item in payload.get("liveries", []):
                row_rect = pygame.Rect(library_rect.x + 8, row_y, library_rect.width - 16, 54)
                selected = item.get("id") == payload.get("active_livery_id")
                pygame.draw.rect(screen, (47, 73, 96) if selected else (29, 36, 47), row_rect, border_radius=4)
                pygame.draw.rect(screen, (111, 192, 224) if selected else (62, 77, 97), row_rect, 1, border_radius=4)
                swatch = pygame.Rect(row_rect.x + 7, row_rect.y + 7, 6, row_rect.height - 14)
                pygame.draw.rect(screen, (105, 201, 222) if selected else (74, 93, 112), swatch, border_radius=3)
                name = str(item.get("name", "Livery"))
                while name and self._render_text(name, (237, 241, 247)).get_width() > row_rect.width - 28:
                    name = name[:-1]
                screen.blit(self._render_text(name, (237, 241, 247)), (row_rect.x + 20, row_rect.y + 10))
                screen.blit(self._render_text("micro-pixel surface", (119, 137, 159)), (row_rect.x + 20, row_rect.y + 30))
                hitboxes.append((item.get("id"), row_rect))
                row_y += 62
            sim.set_livery_list_hitboxes(hitboxes)
        else:
            sim.set_livery_list_hitboxes([])

    RESOURCE_TYPE_COLORS = {
        "mechanical_power": (150, 205, 235),
        "electrical_power": (235, 220, 120),
        "fuel": (230, 150, 110),
        "coolant": (140, 220, 220),
        "thrust": (240, 140, 140),
        "lift": (150, 220, 160),
        "control_signal": (200, 170, 230),
        "cargo_mass": (190, 190, 190),
        "crew_capacity": (190, 190, 190),
    }

    def _draw_system_diagram(self, screen, sim, payload):
        diagram = payload.get("system_diagram") or {}
        nodes = diagram.get("nodes", [])
        edges = diagram.get("edges", [])

        screen.blit(self._render_text("3  SYSTEM DIAGRAM", (235, 239, 247)), (20, 48))
        screen.blit(self._render_text(
            "Click a slot, then a catalog part to install/swap · right-click a slot to remove its part · "
            "click an input dot to reroute its source",
            (145, 158, 180),
        ), (20, 69))

        canvas = pygame.Rect(20, 104, max(620, screen.get_width() - 270), max(320, screen.get_height() - 410))
        pygame.draw.rect(screen, (15, 19, 26), canvas, border_radius=4)
        pygame.draw.rect(screen, (70, 82, 102), canvas, 1, border_radius=4)

        if not nodes:
            screen.blit(
                self._render_text("No slots placed yet — drag a catalog part onto the hull to create one.", (139, 151, 170)),
                (canvas.x + 14, canvas.y + 14),
            )
            sim.set_diagram_node_rects({})
            sim.set_diagram_port_rects({})
            return

        max_col = max((node["x"] for node in nodes), default=0.0) + 1.0
        max_row = max((node["y"] for node in nodes), default=0.0) + 1.0
        padding = 24
        usable = canvas.inflate(-padding * 2, -padding * 2)
        scale = min(usable.width / max(1.0, max_col), usable.height / max(1.0, max_row), 170)
        node_w = max(96, scale * 0.82)
        node_h = min(72, max(46, scale * 0.55))

        node_rects = {}
        port_rects = {}
        port_positions = {}

        for node in nodes:
            rect = pygame.Rect(
                usable.x + int(node["x"] * scale), usable.y + int(node["y"] * scale),
                int(node_w), int(node_h),
            )
            node_rects[node["id"]] = rect

            selected = node["id"] == payload.get("selected_part_id")
            if not node.get("installed"):
                border, fill = (160, 170, 182), (36, 40, 48)
            elif node.get("fully_wired", True):
                border, fill = (150, 205, 165), (34, 54, 40)
            else:
                border, fill = (225, 190, 110), (58, 50, 30)
            if selected:
                border = (255, 230, 120)

            pygame.draw.rect(screen, fill, rect, border_radius=4)
            pygame.draw.rect(screen, border, rect, 2 if selected else 1, border_radius=4)
            screen.blit(self._render_text(node.get("label", node["id"]), (235, 239, 247)), (rect.x + 6, rect.y + 4))
            if not node.get("installed"):
                screen.blit(
                    self._render_text(f"reserved: {node.get('slot_category') or 'general'}", (170, 178, 190)),
                    (rect.x + 6, rect.bottom - 18),
                )

            for index, port in enumerate(node.get("inputs", [])):
                point = (rect.x, rect.y + 22 + index * 12)
                port_positions[(node["id"], port["port_id"], "input")] = point
                port_rects[("input", node["id"], port["port_id"])] = pygame.Rect(point[0] - 5, point[1] - 5, 10, 10)
                pygame.draw.circle(screen, (140, 190, 230), point, 4)
            for index, port in enumerate(node.get("outputs", [])):
                point = (rect.right, rect.y + 22 + index * 12)
                port_positions[(node["id"], port["port_id"], "output")] = point
                port_rects[("output", node["id"], port["port_id"])] = pygame.Rect(point[0] - 5, point[1] - 5, 10, 10)
                pygame.draw.circle(screen, (230, 175, 120), point, 4)

        for edge in edges:
            start = port_positions.get((edge["from_slot_id"], edge["from_port_id"], "output"))
            end = port_positions.get((edge["to_slot_id"], edge["to_port_id"], "input"))
            if start is None or end is None:
                continue
            color = self.RESOURCE_TYPE_COLORS.get(edge.get("resource_type"), (160, 170, 182))
            pygame.draw.line(screen, color, start, end, 2 if edge.get("manual") else 1)
            if edge.get("manual"):
                pygame.draw.circle(screen, color, end, 3)

        sim.set_diagram_node_rects(node_rects)
        sim.set_diagram_port_rects(port_rects)

    def _draw_operational(self, screen, sim, camera, payload):
        base_rect = self._world_rect_to_screen(camera, payload["base_rect"])
        if base_rect is None:
            return

        pygame.draw.rect(screen, (28, 36, 30), base_rect)
        pygame.draw.rect(screen, (215, 215, 215), base_rect, 3)

        for module in payload.get("operational_modules", []):
            module_rect = self._world_rect_to_screen(camera, module)
            if module_rect is None:
                continue

            module_id = module.get("id")
            status = module.get("status", "missing")

            if status == "active":
                border_color = (150, 190, 160)
                fill_color = (48, 74, 54)
            elif status == "incomplete":
                border_color = (230, 210, 120)
                fill_color = (92, 84, 46)
            else:
                border_color = (170, 130, 130)
                fill_color = (72, 46, 46)

            if module_id == payload.get("hover_part_id"):
                border_color = (120, 220, 255)

            if module_id == payload.get("selected_part_id"):
                border_color = (255, 230, 120)

            pygame.draw.rect(screen, fill_color, module_rect)
            pygame.draw.rect(screen, border_color, module_rect, 2)

            text_x = module_rect.x + 8
            text_y = module_rect.y + 4

            group_surface = self._render_text(
                module.get("group", module.get("label", "module")),
                (240, 240, 240),
            )
            status_surface = self._render_text(
                module.get("status_text", status),
                (220, 220, 220),
            )

            screen.blit(group_surface, (text_x, text_y))
            screen.blit(status_surface, (text_x, text_y + 18))

            child_y = text_y + 38
            for child in module.get("children", []):
                if child_y + 14 > module_rect.bottom - 4:
                    break

                child_prefix = "- "
                child_label = child.get("label", child.get("category", "subsystem"))
                child_status = child.get("status", "missing")
                child_text = f"{child_prefix}{child_label}: {child_status}"

                if child_status == "active":
                    child_color = (180, 235, 180)
                elif child_status in {"incomplete", "unwired"}:
                    child_color = (255, 220, 150)
                elif child_status == "reserved":
                    child_color = (190, 200, 215)
                else:
                    child_color = (240, 200, 200)

                child_surface = self._render_text(child_text, child_color)
                screen.blit(child_surface, (text_x + 10, child_y))
                child_y += 16

    def draw(self, screen, sim):
        camera = self.app_view.camera
        payload = sim.get_focused_render_payload()

        bounds = sim.bounds
        top_left = camera.world_to_screen((bounds["min_x"], bounds["min_y"]))
        bottom_right = camera.world_to_screen((bounds["max_x"], bounds["max_y"]))

        if top_left is not None and bottom_right is not None:
            left = min(top_left[0], bottom_right[0])
            right = max(top_left[0], bottom_right[0])
            top = min(top_left[1], bottom_right[1])
            bottom = max(top_left[1], bottom_right[1])
            background_rect = pygame.Rect(left, top, right - left, bottom - top)
            pygame.draw.rect(screen, (18, 18, 22), background_rect)

        if payload.get("mode") == sim.VIEW_DESIGN:
            self._draw_orthographic_design(screen, sim, payload)
            return

        if payload.get("mode") == sim.VIEW_INTERIOR:
            self._draw_design_or_interior(screen, sim, camera, payload)
            return

        self._draw_operational(screen, sim, camera, payload)
