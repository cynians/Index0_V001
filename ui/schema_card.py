import copy

import pygame


class SchemaCard:
    """
    Card renderer/editor for one schema definition.

    The schema file is not written by this view. It edits the card's draft
    schema state; the owning browser persists that draft when Save is clicked.
    """

    HEADER_H = 50
    FOOTER_H = 42
    ROW_PAD_Y = 5
    ROW_GAP = 4
    RESIZE_HANDLE = 14
    RESIZE_BORDER = 6

    def __init__(self, schema_name, schema, schema_path=None, usage_by_field=None):
        self.schema_name = schema_name
        self.schema = schema or {}
        self.schema_path = schema_path
        self.usage_by_field = usage_by_field or {}

    def _line_h(self, font):
        return max(16, int(font.get_linesize())) if font is not None else 18

    def _wrap_text(self, text, font, max_width):
        text = str(text or "")
        if font is None or max_width <= 20:
            return [text]

        lines = []
        for raw_line in text.splitlines() or [""]:
            words = raw_line.split(" ")
            current = ""

            for word in words:
                candidate = word if not current else f"{current} {word}"
                if font.size(candidate)[0] <= max_width:
                    current = candidate
                    continue

                if current:
                    lines.append(current)
                current = word

            lines.append(current)

        return lines or [""]

    def _field_summary(self, spec):
        if isinstance(spec, str):
            return spec

        if not isinstance(spec, dict):
            return ""

        parts = []
        for key in ("type", "target", "section", "optional"):
            if key in spec:
                parts.append(f"{key}: {spec[key]}")

        for key, value in spec.items():
            if key in {"type", "target", "section", "optional"}:
                continue
            parts.append(f"{key}: {value}")

        return " | ".join(parts)

    def _spec_to_edit_text(self, spec):
        if isinstance(spec, str):
            return f"type: {spec}"

        if not isinstance(spec, dict):
            return ""

        return " | ".join(f"{key}: {value}" for key, value in spec.items())

    def _coerce_spec_value(self, text):
        stripped = str(text).strip()
        lowered = stripped.lower()

        if lowered in {"true", "false"}:
            return lowered == "true"

        if lowered in {"none", "null"}:
            return None

        if stripped.startswith("[") and stripped.endswith("]"):
            inner = stripped[1:-1].strip()
            if not inner:
                return []
            return [part.strip().strip("'\"") for part in inner.split(",")]

        try:
            if "." in stripped:
                return float(stripped)
            return int(stripped)
        except ValueError:
            return stripped

    def _parse_spec_text(self, text):
        spec = {}
        normalized = str(text or "").replace("|", "\n")

        for raw_line in normalized.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if ":" not in line:
                spec["type"] = line
                continue

            key, value = line.split(":", 1)
            key = key.strip()
            if not key:
                continue

            spec[key] = self._coerce_spec_value(value)

        return spec or {"type": "string", "optional": True}

    def begin_edit_field(self, card, field_name):
        fields = card.setdefault("schema_draft_fields", {})
        if field_name not in fields:
            return False

        active_field = card.get("schema_active_field")
        if active_field and active_field != field_name:
            self.commit_edit_field(card)

        card["schema_active_field"] = field_name
        card["schema_edit_buffer"] = self._spec_to_edit_text(fields.get(field_name, {}))
        return True

    def commit_edit_field(self, card):
        field_name = card.get("schema_active_field")
        if not field_name:
            return False

        fields = card.setdefault("schema_draft_fields", {})
        fields[field_name] = self._parse_spec_text(card.get("schema_edit_buffer", ""))
        card["schema_active_field"] = None
        card["schema_edit_buffer"] = ""
        card["schema_dirty"] = True
        card["schema_status"] = "Unsaved changes"
        return True

    def cancel_edit_field(self, card):
        if not card.get("schema_active_field"):
            return False

        card["schema_active_field"] = None
        card["schema_edit_buffer"] = ""
        card["schema_status"] = "Edit cancelled"
        return True

    def handle_keydown(self, card, event):
        if not card.get("schema_active_field"):
            return False

        if event.key == pygame.K_ESCAPE:
            return self.cancel_edit_field(card)

        if event.key == pygame.K_RETURN and (event.mod & pygame.KMOD_CTRL):
            return self.commit_edit_field(card)

        if event.key == pygame.K_RETURN:
            return self.commit_edit_field(card)

        if event.key == pygame.K_BACKSPACE:
            card["schema_edit_buffer"] = card.get("schema_edit_buffer", "")[:-1]
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            card["schema_edit_buffer"] = card.get("schema_edit_buffer", "") + text
            return True

        return False

    def layout_card(self, card, rect):
        fields = card.setdefault("schema_draft_fields", copy.deepcopy(self.schema.get("fields", {})))
        rows = []
        line_h = self._line_h(card.get("layout_font"))

        close_rect = pygame.Rect(rect.right - 24, rect.y + 12, 18, 18)
        header_drag_rect = pygame.Rect(rect.x + 1, rect.y + 1, rect.width - 2, self.HEADER_H)

        content_left = rect.x + 12
        content_right = rect.right - 12
        usage_w = 52
        field_w = max(110, int((content_right - content_left - usage_w) * 0.36))
        value_w = max(140, content_right - content_left - field_w - usage_w - 18)

        current_y = rect.y + self.HEADER_H + 12
        meta_lines = [
            f"schema: {card.get('schema_schema_name', self.schema_name)}",
            f"extends: {card.get('schema_extends') or '-'}",
        ]
        for meta_line in meta_lines:
            current_y += line_h
        current_y += 8

        header_row = pygame.Rect(content_left, current_y, content_right - content_left, line_h + 8)
        card["schema_header_row_rect"] = header_row
        current_y = header_row.bottom + self.ROW_GAP
        content_start_y = current_y
        footer_top = rect.bottom - self.FOOTER_H
        content_viewport_rect = pygame.Rect(
            content_left,
            content_start_y,
            content_right - content_left,
            max(24, footer_top - content_start_y),
        )

        for field_name, spec in fields.items():
            active = field_name == card.get("schema_active_field")
            value_text = card.get("schema_edit_buffer", "") if active else self._field_summary(spec)
            field_lines = self._wrap_text(field_name, card.get("layout_font"), field_w - 10)
            value_lines = self._wrap_text(value_text, card.get("layout_font"), value_w - 10)
            row_h = max(len(field_lines), len(value_lines), 1) * line_h + self.ROW_PAD_Y * 2
            row_rect = pygame.Rect(content_left, current_y, content_right - content_left, row_h)
            field_rect = pygame.Rect(content_left, current_y, field_w, row_h)
            value_rect = pygame.Rect(field_rect.right + 8, current_y, value_w, row_h)
            usage_rect = pygame.Rect(value_rect.right + 8, current_y, usage_w, row_h)

            usage = self.usage_by_field.get(field_name, {})
            rows.append(
                {
                    "field_name": field_name,
                    "row_rect": row_rect,
                    "field_rect": field_rect,
                    "value_rect": value_rect,
                    "usage_rect": usage_rect,
                    "field_lines": field_lines,
                    "value_lines": value_lines,
                    "usage_count": int(usage.get("count", 0)),
                    "usage_modules": list(usage.get("modules", [])),
                    "active": active,
                }
            )
            current_y = row_rect.bottom + self.ROW_GAP

        content_end_y = current_y
        scroll_max_y = max(0, int(content_end_y - content_viewport_rect.bottom))
        scroll_y = max(0, min(scroll_max_y, int(card.get("scroll_y", 0) or 0)))
        card["scroll_y"] = scroll_y
        card["scroll_max_y"] = scroll_max_y
        card["content_viewport_rect"] = content_viewport_rect

        field_hitboxes = []
        for row in rows:
            for rect_key in ("row_rect", "field_rect", "value_rect", "usage_rect"):
                row[rect_key] = row[rect_key].move(0, -scroll_y)

            clipped_rect = row["row_rect"].clip(content_viewport_rect)
            if clipped_rect.height > 0:
                field_hitboxes.append((row["field_name"], clipped_rect))

        save_rect = pygame.Rect(rect.right - 92, rect.bottom - 32, 68, 22)
        resize_handle_rect = pygame.Rect(
            rect.right - 18,
            rect.bottom - 8 - self.RESIZE_HANDLE,
            self.RESIZE_HANDLE,
            self.RESIZE_HANDLE,
        )
        corner_resize_hitboxes = [
            ("top_left", pygame.Rect(rect.x - self.RESIZE_BORDER, rect.y - self.RESIZE_BORDER, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
            ("top_right", pygame.Rect(rect.right - self.RESIZE_BORDER * 2, rect.y - self.RESIZE_BORDER, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
            ("bottom_left", pygame.Rect(rect.x - self.RESIZE_BORDER, rect.bottom - self.RESIZE_BORDER * 2, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
            ("bottom_right", pygame.Rect(rect.right - self.RESIZE_BORDER * 2, rect.bottom - self.RESIZE_BORDER * 2, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
        ]
        edge_resize_hitboxes = [
            ("left", pygame.Rect(rect.x - self.RESIZE_BORDER, rect.y + self.HEADER_H, self.RESIZE_BORDER * 2, rect.height - self.HEADER_H)),
            ("right", pygame.Rect(rect.right - self.RESIZE_BORDER, rect.y + self.HEADER_H, self.RESIZE_BORDER * 2, rect.height - self.HEADER_H)),
            ("top", pygame.Rect(rect.x, rect.y - self.RESIZE_BORDER, rect.width, self.RESIZE_BORDER * 2)),
            ("bottom", pygame.Rect(rect.x, rect.bottom - self.RESIZE_BORDER, rect.width, self.RESIZE_BORDER * 2)),
        ]
        resize_hitboxes = corner_resize_hitboxes + edge_resize_hitboxes
        corner_handle_size = max(8, min(12, self.RESIZE_HANDLE))
        corner_handle_rects = [
            pygame.Rect(rect.x, rect.y, corner_handle_size, corner_handle_size),
            pygame.Rect(rect.right - corner_handle_size, rect.y, corner_handle_size, corner_handle_size),
            pygame.Rect(rect.x, rect.bottom - corner_handle_size, corner_handle_size, corner_handle_size),
            pygame.Rect(rect.right - corner_handle_size, rect.bottom - corner_handle_size, corner_handle_size, corner_handle_size),
        ]

        card["rect"] = pygame.Rect(rect.x, rect.y, rect.width, rect.height)
        card["close_rect"] = close_rect
        card["header_drag_rect"] = header_drag_rect
        card["schema_field_rows"] = rows
        card["schema_field_hitboxes"] = field_hitboxes
        card["schema_save_rect"] = save_rect
        card["resize_handle_rect"] = resize_handle_rect
        card["corner_handle_rects"] = corner_handle_rects
        card["resize_hitboxes"] = resize_hitboxes
        card["tab_hitboxes"] = []
        card["year_hitboxes"] = []

    def get_minimum_height(self, card, font):
        fields = card.setdefault("schema_draft_fields", copy.deepcopy(self.schema.get("fields", {})))
        line_h = self._line_h(font)
        probe_w = max(300, int(card.get("canvas_w", 520)))
        content_w = probe_w - 24
        field_w = max(110, int((content_w - 52) * 0.36))
        value_w = max(140, content_w - field_w - 52 - 18)
        total = self.HEADER_H + 12 + line_h * 2 + 8 + line_h + 8

        for field_name, spec in fields.items():
            active = field_name == card.get("schema_active_field")
            value_text = card.get("schema_edit_buffer", "") if active else self._field_summary(spec)
            field_lines = self._wrap_text(field_name, font, field_w - 10)
            value_lines = self._wrap_text(value_text, font, value_w - 10)
            total += max(len(field_lines), len(value_lines), 1) * line_h + self.ROW_PAD_Y * 2 + self.ROW_GAP

        return max(360, total + self.FOOTER_H + 10)

    def draw_card(self, screen, font, card):
        rect = card["rect"]
        pygame.draw.rect(screen, (26, 30, 38), rect)
        pygame.draw.rect(screen, (172, 182, 198), rect, 1)

        # See ui/card.py draw_card for why this can legitimately be None:
        # ui_manager.scrub_floating_card_hitboxes() clears it every frame
        # the floating entity card is open.
        header_rect = card.get("header_drag_rect") or pygame.Rect(
            rect.x + 1, rect.y + 1, rect.width - 2, self.HEADER_H,
        )
        pygame.draw.rect(screen, (34, 42, 52), header_rect)
        pygame.draw.line(screen, (112, 124, 144), (header_rect.x, header_rect.bottom), (header_rect.right, header_rect.bottom), 1)

        title_surface = font.render(card.get("title", self.schema_name), True, (246, 246, 246))
        subtitle_surface = font.render(card.get("subtitle", "schema"), True, (176, 184, 198))
        screen.blit(title_surface, (rect.x + 12, rect.y + 10))
        screen.blit(subtitle_surface, (rect.x + 12, rect.y + 30))

        close_rect = card.get("close_rect")
        if close_rect is not None:
            pygame.draw.rect(screen, (58, 44, 48), close_rect)
            pygame.draw.rect(screen, (178, 132, 140), close_rect, 1)
            close_text = font.render("X", True, (244, 218, 222))
            screen.blit(close_text, close_text.get_rect(center=close_rect.center))

        line_h = self._line_h(font)
        meta_y = rect.y + self.HEADER_H + 12
        for meta_line in (
            f"schema: {card.get('schema_schema_name', self.schema_name)}",
            f"extends: {card.get('schema_extends') or '-'}",
        ):
            meta_surface = font.render(meta_line, True, (190, 198, 214))
            screen.blit(meta_surface, (rect.x + 12, meta_y))
            meta_y += line_h

        header_row = card.get("schema_header_row_rect")
        if header_row is not None:
            pygame.draw.rect(screen, (38, 44, 58), header_row)
            pygame.draw.rect(screen, (112, 124, 146), header_row, 1)
            labels = [
                ("Field", rect.x + 20),
                ("Current Value", rect.x + 174),
                ("Used", header_row.right - 48),
            ]
            for label, x in labels:
                screen.blit(font.render(label, True, (232, 236, 244)), (x, header_row.y + 4))

        previous_clip = screen.get_clip()
        content_viewport_rect = card.get("content_viewport_rect")
        if content_viewport_rect is not None:
            screen.set_clip(previous_clip.clip(content_viewport_rect))
        try:
            for index, row in enumerate(card.get("schema_field_rows", [])):
                row_rect = row["row_rect"]
                fill = (32, 36, 46) if index % 2 == 0 else (28, 32, 42)
                border = (78, 88, 106)

                if row.get("active"):
                    fill = (54, 62, 78)
                    border = (184, 204, 238)
                elif row_rect.collidepoint(pygame.mouse.get_pos()):
                    fill = (42, 48, 62)

                pygame.draw.rect(screen, fill, row_rect)
                pygame.draw.rect(screen, border, row_rect, 1)
                for divider_x in (row["field_rect"].right + 4, row["value_rect"].right + 4):
                    pygame.draw.line(screen, (86, 96, 116), (divider_x, row_rect.y + 1), (divider_x, row_rect.bottom - 1), 1)

                line_y = row_rect.y + self.ROW_PAD_Y
                for line in row["field_lines"]:
                    screen.blit(font.render(line, True, (226, 226, 226)), (row["field_rect"].x + 6, line_y))
                    line_y += line_h

                line_y = row_rect.y + self.ROW_PAD_Y
                value_color = (246, 246, 246) if row.get("active") else (206, 218, 236)
                for line in row["value_lines"]:
                    screen.blit(font.render(line, True, value_color), (row["value_rect"].x + 2, line_y))
                    line_y += line_h

                usage_text = f"({row['usage_count']})"
                usage_color = (232, 210, 148) if row["usage_count"] else (142, 150, 164)
                usage_surface = font.render(usage_text, True, usage_color)
                screen.blit(usage_surface, usage_surface.get_rect(center=row["usage_rect"].center))
        finally:
            screen.set_clip(previous_clip)

        status = card.get("schema_status", "Click a field row to edit")
        status_color = (232, 210, 148) if card.get("schema_dirty") else (160, 168, 182)
        screen.blit(font.render(status, True, status_color), (rect.x + 12, rect.bottom - 28))

        save_rect = card.get("schema_save_rect")
        if save_rect is not None:
            enabled = bool(card.get("schema_dirty") or card.get("schema_active_field"))
            fill = (72, 102, 84) if enabled else (48, 54, 58)
            border = (190, 222, 194) if enabled else (118, 124, 132)
            pygame.draw.rect(screen, fill, save_rect)
            pygame.draw.rect(screen, border, save_rect, 1)
            save_surface = font.render("Save", True, (244, 248, 244))
            screen.blit(save_surface, save_surface.get_rect(center=save_rect.center))

        for handle_rect in card.get("corner_handle_rects", []):
            pygame.draw.rect(screen, (105, 112, 126), handle_rect)
            pygame.draw.rect(screen, (220, 224, 232), handle_rect, 1)

        handle_rect = card.get("resize_handle_rect")
        if handle_rect is not None:
            pygame.draw.rect(screen, (120, 120, 120), handle_rect)
            pygame.draw.rect(screen, (220, 220, 220), handle_rect, 1)
