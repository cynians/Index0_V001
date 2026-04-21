import pygame


class SelectionInspectorUI:
    """
    Reusable lower-left inspector for simulation-selected objects.

    Current target support:
    * spatial_feature records

    The component owns only transient UI state. Persistence is routed back to
    the active simulation via action payloads.
    """

    WIDTH = 420
    HEIGHT = 260
    MARGIN = 20
    HEADER_H = 34
    FIELD_LABEL_H = 18
    NAME_FIELD_H = 28
    NOTES_FIELD_H = 92
    BUTTON_W = 78
    EDIT_BUTTON_W = 118
    BUTTON_H = 28

    def __init__(self):
        self.is_open = False
        self.target_kind = None
        self.target_id = None
        self.title = ""
        self.name_buffer = ""
        self.notes_buffer = ""
        self.active_field = None

        self.rect = None
        self.name_rect = None
        self.notes_rect = None
        self.save_rect = None
        self.cancel_rect = None
        self.edit_rect = None
        self.close_rect = None

    def open(self, target_kind, target_id, record):
        self.is_open = True
        self.target_kind = target_kind
        self.target_id = target_id
        self.title = self._title_for_target(target_kind, target_id, record)
        self.name_buffer = str(record.get("name") or record.get("pretty_name") or "")
        self.notes_buffer = str(record.get("notes") or "")
        self.active_field = "name"

    def close(self):
        self.is_open = False
        self.target_kind = None
        self.target_id = None
        self.title = ""
        self.name_buffer = ""
        self.notes_buffer = ""
        self.active_field = None
        self.edit_rect = None

    def is_text_input_active(self):
        return self.is_open and self.active_field in {"name", "notes"}

    def _title_for_target(self, target_kind, target_id, record):
        if target_kind == "spatial_feature":
            layer_kind = record.get("layer_kind", "spatial")
            return f"Spatial Feature | {layer_kind}"

        if target_kind == "location":
            location_class = record.get("location_class", "location")
            return f"Location | {location_class}"

        return str(target_id or "Selection")

    def rebuild(self, app_width, app_height):
        if not self.is_open:
            self.rect = None
            return

        width = min(self.WIDTH, max(320, app_width - self.MARGIN * 2))
        height = self.HEIGHT

        x = self.MARGIN
        y = app_height - height - self.MARGIN
        self.rect = pygame.Rect(x, y, width, height)

        content_x = self.rect.x + 14
        content_w = self.rect.width - 28

        self.close_rect = pygame.Rect(self.rect.right - 30, self.rect.y + 8, 20, 20)

        name_y = self.rect.y + self.HEADER_H + 26
        self.name_rect = pygame.Rect(content_x, name_y, content_w, self.NAME_FIELD_H)

        notes_y = self.name_rect.bottom + self.FIELD_LABEL_H + 24
        self.notes_rect = pygame.Rect(content_x, notes_y, content_w, self.NOTES_FIELD_H)

        button_y = self.rect.bottom - self.BUTTON_H - 12
        self.edit_rect = pygame.Rect(
            content_x,
            button_y,
            self.EDIT_BUTTON_W,
            self.BUTTON_H,
        )
        self.save_rect = pygame.Rect(
            self.rect.right - self.BUTTON_W * 2 - 26,
            button_y,
            self.BUTTON_W,
            self.BUTTON_H,
        )
        self.cancel_rect = pygame.Rect(
            self.rect.right - self.BUTTON_W - 14,
            button_y,
            self.BUTTON_W,
            self.BUTTON_H,
        )

    def draw(self, screen, font):
        if not self.is_open or self.rect is None:
            return

        pygame.draw.rect(screen, (24, 27, 34), self.rect)
        pygame.draw.rect(screen, (205, 210, 220), self.rect, 1)

        header_rect = pygame.Rect(self.rect.x, self.rect.y, self.rect.width, self.HEADER_H)
        pygame.draw.rect(screen, (34, 39, 50), header_rect)
        pygame.draw.line(
            screen,
            (92, 100, 118),
            (self.rect.x, header_rect.bottom),
            (self.rect.right, header_rect.bottom),
            1,
        )

        title_surface = font.render(self.title, True, (242, 242, 242))
        screen.blit(title_surface, (self.rect.x + 12, self.rect.y + 9))

        self._draw_close_button(screen, font)
        self._draw_labeled_field(screen, font, "name", self.name_rect, self.name_buffer)
        self._draw_labeled_field(screen, font, "notes", self.notes_rect, self.notes_buffer)
        if self.target_kind == "spatial_feature":
            self._draw_button(screen, font, self.edit_rect, "Edit Polygon", True)
        elif self.target_kind == "location":
            self._draw_button(screen, font, self.edit_rect, "Edit Rectangle", True)
        self._draw_button(screen, font, self.save_rect, "Save", True)
        self._draw_button(screen, font, self.cancel_rect, "Cancel", True)

    def _draw_close_button(self, screen, font):
        pygame.draw.rect(screen, (48, 52, 62), self.close_rect)
        pygame.draw.rect(screen, (156, 164, 180), self.close_rect, 1)
        text = font.render("X", True, (235, 235, 235))
        text_rect = text.get_rect(center=self.close_rect.center)
        screen.blit(text, text_rect)

    def _draw_labeled_field(self, screen, font, label, rect, value):
        label_y = rect.y - self.FIELD_LABEL_H
        label_surface = font.render(label, True, (202, 208, 218))
        screen.blit(label_surface, (rect.x, label_y))

        is_active = self.active_field == label
        fill = (38, 43, 54) if is_active else (30, 34, 43)
        border = (206, 218, 244) if is_active else (106, 114, 130)

        pygame.draw.rect(screen, fill, rect)
        pygame.draw.rect(screen, border, rect, 1)

        lines = self._wrap_text(value, font, rect.width - 12)
        if label == "name":
            lines = lines[:1]

        current_y = rect.y + 6
        max_y = rect.bottom - 4
        for line in lines:
            if current_y + font.get_height() > max_y:
                break
            surface = font.render(line, True, (238, 240, 244))
            screen.blit(surface, (rect.x + 6, current_y))
            current_y += font.get_height() + 2

        if is_active:
            cursor_x = rect.x + 7
            cursor_y = rect.y + 6
            if label == "name":
                visible_text = lines[0] if lines else ""
                cursor_x += font.size(visible_text)[0]
            else:
                visible_text = lines[-1] if lines else ""
                cursor_y += (font.get_height() + 2) * max(0, len(lines) - 1)
                cursor_x += font.size(visible_text)[0]
            pygame.draw.line(screen, (240, 240, 240), (cursor_x, cursor_y), (cursor_x, cursor_y + font.get_height()), 1)

    def _draw_button(self, screen, font, rect, label, enabled):
        fill = (58, 66, 82) if enabled else (42, 44, 50)
        border = (210, 218, 232) if enabled else (112, 116, 124)
        text_color = (245, 245, 245) if enabled else (150, 150, 150)

        pygame.draw.rect(screen, fill, rect)
        pygame.draw.rect(screen, border, rect, 1)
        text = font.render(label, True, text_color)
        text_rect = text.get_rect(center=rect.center)
        screen.blit(text, text_rect)

    def _wrap_text(self, text, font, max_width):
        text = str(text or "")
        if not text:
            return [""]

        lines = []
        for paragraph in text.splitlines() or [""]:
            words = paragraph.split(" ")
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

        return lines

    def handle_event(self, event):
        if not self.is_open:
            return None

        if event.type == pygame.KEYDOWN and self.is_text_input_active():
            self._handle_keydown(event)
            return "ui_consumed"

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        mouse_pos = event.pos

        if self.close_rect and self.close_rect.collidepoint(mouse_pos):
            self.close()
            return "ui_consumed"

        if self.name_rect and self.name_rect.collidepoint(mouse_pos):
            self.active_field = "name"
            return "ui_consumed"

        if self.notes_rect and self.notes_rect.collidepoint(mouse_pos):
            self.active_field = "notes"
            return "ui_consumed"

        if (
            self.target_kind in {"spatial_feature", "location"}
            and self.edit_rect
            and self.edit_rect.collidepoint(mouse_pos)
        ):
            action_id = "selection_inspector_edit_polygon"
            if self.target_kind == "location":
                action_id = "selection_inspector_edit_rectangle"

            action = {
                "id": action_id,
                "target_kind": self.target_kind,
                "target_id": self.target_id,
            }
            self.close()
            return action

        if self.save_rect and self.save_rect.collidepoint(mouse_pos):
            action = {
                "id": "selection_inspector_save",
                "target_kind": self.target_kind,
                "target_id": self.target_id,
                "updates": {
                    "name": self.name_buffer.strip(),
                    "notes": self.notes_buffer.strip(),
                },
            }
            self.close()
            return action

        if self.cancel_rect and self.cancel_rect.collidepoint(mouse_pos):
            self.close()
            return "ui_consumed"

        if self.rect and self.rect.collidepoint(mouse_pos):
            return "ui_consumed"

        return None

    def _handle_keydown(self, event):
        if event.key == pygame.K_ESCAPE:
            self.close()
            return

        if event.key == pygame.K_TAB:
            self.active_field = "notes" if self.active_field == "name" else "name"
            return

        if event.key == pygame.K_BACKSPACE:
            self._delete_character()
            return

        if event.key == pygame.K_RETURN:
            if self.active_field == "notes":
                self._insert_text("\n")
            return

        text = getattr(event, "unicode", "")
        if text:
            self._insert_text(text)

    def _delete_character(self):
        if self.active_field == "name":
            self.name_buffer = self.name_buffer[:-1]
        elif self.active_field == "notes":
            self.notes_buffer = self.notes_buffer[:-1]

    def _insert_text(self, text):
        if self.active_field == "name":
            clean_text = str(text).replace("\n", " ")
            self.name_buffer += clean_text
        elif self.active_field == "notes":
            self.notes_buffer += str(text)
