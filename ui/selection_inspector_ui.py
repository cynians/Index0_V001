import pygame

from ui.text_editing import TextEditing


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
    EVOLVE_BUTTON_W = 86
    DELETE_BUTTON_W = 72
    BUTTON_H = 28
    KEY_REPEAT_DELAY_MS = 320
    KEY_REPEAT_INTERVAL_MS = 38

    def __init__(self):
        self.is_open = False
        self.target_kind = None
        self.target_id = None
        self.title = ""
        self.name_buffer = ""
        self.notes_buffer = ""
        self.name_cursor = 0
        self.notes_cursor = 0
        self.active_field = None
        self.target_can_edit_geometry = False
        self.time_anchor_preview_year = None
        self.time_anchor_active = False
        self.layout_font = None
        self.repeat_key = None
        self.repeat_mod = 0
        self.next_repeat_ms = 0

        self.rect = None
        self.name_rect = None
        self.notes_rect = None
        self.save_rect = None
        self.cancel_rect = None
        self.edit_rect = None
        self.evolve_rect = None
        self.time_anchor_rect = None
        self.close_rect = None
        self.delete_rect = None
        self.delete_confirm_active = False

    def open(self, target_kind, target_id, record):
        self.is_open = True
        self.target_kind = target_kind
        self.target_id = target_id
        self.title = self._title_for_target(target_kind, target_id, record)
        self.name_buffer = str(record.get("name") or record.get("pretty_name") or "")
        self.notes_buffer = str(record.get("notes") or "")
        self.name_cursor = len(self.name_buffer)
        self.notes_cursor = len(self.notes_buffer)
        self.active_field = "name"
        self.target_can_edit_geometry = self._can_edit_target_geometry(target_kind, record)
        self.time_anchor_preview_year = self._time_anchor_preview_year(record)
        self.time_anchor_active = False
        self.delete_confirm_active = False
        self._reset_key_repeat()

    def close(self):
        self.is_open = False
        self.target_kind = None
        self.target_id = None
        self.title = ""
        self.name_buffer = ""
        self.notes_buffer = ""
        self.name_cursor = 0
        self.notes_cursor = 0
        self.active_field = None
        self.target_can_edit_geometry = False
        self.time_anchor_preview_year = None
        self.time_anchor_active = False
        self.edit_rect = None
        self.evolve_rect = None
        self.time_anchor_rect = None
        self.delete_rect = None
        self.delete_confirm_active = False
        self._reset_key_repeat()

    def set_time_anchor_active(self, active, target_kind=None, target_id=None):
        if active:
            if not self.is_open:
                return False
            if target_kind is not None and target_kind != self.target_kind:
                return False
            if target_id is not None and target_id != self.target_id:
                return False

        self.time_anchor_active = bool(active)
        return True

    def _can_edit_target_geometry(self, target_kind, record):
        if target_kind == "spatial_feature":
            geometry = record.get("geometry") or {}
            return geometry.get("type") == "polygon"

        if target_kind == "location":
            bounds = record.get("bounds") or {}
            return bounds.get("type") == "bbox"

        return False

    def _time_anchor_preview_year(self, record):
        for key in (
            "birth_year",
            "year",
            "year_number",
            "active_year",
            "start_year",
            "effective_year",
            "death_year",
            "end_year",
        ):
            value = record.get(key)
            if value in (None, ""):
                continue

            try:
                return int(float(value))
            except (TypeError, ValueError):
                continue

        return None

    def is_text_input_active(self):
        return self.is_open and self.active_field in {"name", "notes"}

    def _title_for_target(self, target_kind, target_id, record):
        if target_kind == "spatial_feature":
            region_class = record.get("region_class") or record.get("layer_kind", "region")
            return f"Region | {region_class}"

        if target_kind == "location":
            location_class = record.get("location_class", "location")
            return f"Location | {location_class}"

        if target_kind == "person":
            person_class = record.get("person_class", "person")
            return f"Person | {person_class}"

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
        if self.target_kind in {"spatial_feature", "location", "person"}:
            self.time_anchor_rect = pygame.Rect(self.close_rect.x - 28, self.rect.y + 8, 20, 20)
        else:
            self.time_anchor_rect = None

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
        self.evolve_rect = pygame.Rect(
            self.edit_rect.right + 8,
            button_y,
            self.EVOLVE_BUTTON_W,
            self.BUTTON_H,
        )
        next_button_x = self.evolve_rect.right + 8
        self.delete_rect = None
        if self.target_kind == "spatial_feature":
            self.delete_rect = pygame.Rect(
                next_button_x,
                button_y,
                self.DELETE_BUTTON_W,
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
        if self.delete_rect is not None and self.delete_rect.right > self.save_rect.x - 8:
            self.evolve_rect = None
            self.delete_rect.x = self.edit_rect.right + 8
        if self.evolve_rect is not None and self.evolve_rect.right > self.save_rect.x - 8:
            self.evolve_rect = None
        if self.delete_rect is not None and self.delete_rect.right > self.save_rect.x - 8:
            self.delete_rect = None

    def draw(self, screen, font):
        if not self.is_open or self.rect is None:
            return

        self.layout_font = font
        self._update_key_repeat()

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
        if self.time_anchor_rect is not None:
            self._draw_time_anchor_button(screen, font)
        self._draw_labeled_field(screen, font, "name", self.name_rect, self.name_buffer)
        self._draw_labeled_field(screen, font, "notes", self.notes_rect, self.notes_buffer)
        if self.target_kind == "spatial_feature" and self.target_can_edit_geometry:
            self._draw_button(screen, font, self.edit_rect, "Edit Polygon", True)
            if self.evolve_rect is not None:
                self._draw_button(screen, font, self.evolve_rect, "Evolve", True)
            if self.delete_rect is not None:
                delete_label = "Confirm" if self.delete_confirm_active else "Delete"
                self._draw_button(
                    screen,
                    font,
                    self.delete_rect,
                    delete_label,
                    True,
                    danger=True,
                )
        elif self.target_kind == "location" and self.target_can_edit_geometry:
            self._draw_button(screen, font, self.edit_rect, "Edit Rectangle", True)
        if self.delete_confirm_active:
            warning = font.render("Delete region?", True, (240, 176, 152))
            screen.blit(warning, (self.rect.x + 12, self.save_rect.y - font.get_height() - 2))
        self._draw_button(screen, font, self.save_rect, "Save", True)
        self._draw_button(screen, font, self.cancel_rect, "Cancel", True)

    def _draw_close_button(self, screen, font):
        pygame.draw.rect(screen, (48, 52, 62), self.close_rect)
        pygame.draw.rect(screen, (156, 164, 180), self.close_rect, 1)
        text = font.render("X", True, (235, 235, 235))
        text_rect = text.get_rect(center=self.close_rect.center)
        screen.blit(text, text_rect)

    def _draw_time_anchor_button(self, screen, font):
        if self.time_anchor_active:
            fill = (94, 78, 38)
            border = (232, 210, 148)
            text_color = (255, 238, 178)
        else:
            fill = (48, 52, 62)
            border = (156, 164, 180)
            text_color = (235, 235, 235)

        pygame.draw.rect(screen, fill, self.time_anchor_rect)
        pygame.draw.rect(screen, border, self.time_anchor_rect, 1)
        text = font.render("T", True, text_color)
        text_rect = text.get_rect(center=self.time_anchor_rect.center)
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

        lines = self._wrap_edit_lines(value, font, rect.width - 12)
        if label == "name":
            lines = lines[:1]

        current_y = rect.y + 6
        max_y = rect.bottom - 4
        cursor_index = self._get_field_cursor(label)
        cursor_drawn = False

        for line_info in lines:
            if current_y + font.get_height() > max_y:
                break
            line_text = line_info["text"]
            surface = font.render(line_text, True, (238, 240, 244))
            screen.blit(surface, (rect.x + 6, current_y))

            if (
                is_active
                and line_info["start"] <= cursor_index <= line_info["end"]
                and not cursor_drawn
            ):
                cursor_text = line_text[:max(0, cursor_index - line_info["start"])]
                cursor_x = rect.x + 7 + font.size(cursor_text)[0]
                pygame.draw.line(
                    screen,
                    (240, 240, 240),
                    (cursor_x, current_y),
                    (cursor_x, current_y + font.get_height()),
                    1,
                )
                cursor_drawn = True

            current_y += font.get_height() + 2

        if is_active and not cursor_drawn:
            cursor_y = min(max_y, max(rect.y + 6, current_y - font.get_height() - 2))
            pygame.draw.line(
                screen,
                (240, 240, 240),
                (rect.x + 7, cursor_y),
                (rect.x + 7, cursor_y + font.get_height()),
                1,
            )

    def _draw_button(self, screen, font, rect, label, enabled, danger=False):
        if danger and enabled:
            fill = (88, 42, 48)
            border = (232, 154, 164)
        else:
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

    def _wrap_edit_lines(self, text, font, max_width):
        text = str(text or "")
        if not text:
            return [{"text": "", "start": 0, "end": 0}]

        max_width = max(1, int(max_width))
        lines = []
        line = ""
        line_start = 0

        for index, char in enumerate(text):
            if char == "\n":
                lines.append({"text": line, "start": line_start, "end": index})
                line = ""
                line_start = index + 1
                continue

            candidate = line + char
            if line and font.size(candidate)[0] > max_width:
                lines.append({"text": line, "start": line_start, "end": index})
                line = char
                line_start = index
            else:
                line = candidate

        lines.append({"text": line, "start": line_start, "end": len(text)})
        return lines

    def handle_event(self, event):
        if not self.is_open:
            return None

        if event.type == pygame.KEYDOWN and self.is_text_input_active():
            self._handle_keydown(event)
            return "ui_consumed"

        if event.type == pygame.KEYUP:
            if event.key == self.repeat_key:
                self._reset_key_repeat()
            if self.is_text_input_active():
                return "ui_consumed"
            return None

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        mouse_pos = event.pos

        if self.close_rect and self.close_rect.collidepoint(mouse_pos):
            self.close()
            return "ui_consumed"

        if self.time_anchor_rect and self.time_anchor_rect.collidepoint(mouse_pos):
            self.active_field = None
            self.delete_confirm_active = False
            self.time_anchor_active = True
            return {
                "id": "selection_inspector_reanchor_time_start",
                "target_kind": self.target_kind,
                "target_id": self.target_id,
                "preview_year": self.time_anchor_preview_year,
            }

        if self.name_rect and self.name_rect.collidepoint(mouse_pos):
            self.active_field = "name"
            self.delete_confirm_active = False
            self._set_cursor_from_mouse("name", mouse_pos)
            self._reset_key_repeat()
            return "ui_consumed"

        if self.notes_rect and self.notes_rect.collidepoint(mouse_pos):
            self.active_field = "notes"
            self.delete_confirm_active = False
            self._set_cursor_from_mouse("notes", mouse_pos)
            self._reset_key_repeat()
            return "ui_consumed"

        if (
            self.target_kind in {"spatial_feature", "location"}
            and self.target_can_edit_geometry
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

        if (
            self.target_kind == "spatial_feature"
            and self.delete_rect
            and self.delete_rect.collidepoint(mouse_pos)
        ):
            if not self.delete_confirm_active:
                self.active_field = None
                self.delete_confirm_active = True
                return "ui_consumed"

            action = {
                "id": "selection_inspector_delete_region",
                "target_kind": self.target_kind,
                "target_id": self.target_id,
            }
            self.close()
            return action

        if (
            self.target_kind == "spatial_feature"
            and self.target_can_edit_geometry
            and self.evolve_rect
            and self.evolve_rect.collidepoint(mouse_pos)
        ):
            action = {
                "id": "selection_inspector_evolve_region",
                "target_kind": self.target_kind,
                "target_id": self.target_id,
            }
            self.close()
            return action

        if self.save_rect and self.save_rect.collidepoint(mouse_pos):
            self.delete_confirm_active = False
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
            if self.delete_confirm_active:
                self.delete_confirm_active = False
                return "ui_consumed"
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
            self._reset_key_repeat()
            return

        if event.key == pygame.K_LEFT:
            cursor = self._get_active_cursor()
            if event.mod & pygame.KMOD_CTRL:
                self._set_active_cursor(
                    self._word_start_before_cursor(self._get_active_buffer(), cursor)
                )
            else:
                self._set_active_cursor(cursor - 1)
            self._start_key_repeat(event)
            return

        if event.key == pygame.K_RIGHT:
            cursor = self._get_active_cursor()
            if event.mod & pygame.KMOD_CTRL:
                self._set_active_cursor(
                    self._word_end_after_cursor(self._get_active_buffer(), cursor)
                )
            else:
                self._set_active_cursor(cursor + 1)
            self._start_key_repeat(event)
            return

        if event.key == pygame.K_HOME:
            if self.active_field == "notes" and not (event.mod & pygame.KMOD_CTRL):
                self._set_active_cursor(
                    self._line_start_before_cursor(
                        self._get_active_buffer(),
                        self._get_active_cursor(),
                    )
                )
            else:
                self._set_active_cursor(0)
            return

        if event.key == pygame.K_END:
            if self.active_field == "notes" and not (event.mod & pygame.KMOD_CTRL):
                self._set_active_cursor(
                    self._line_end_after_cursor(
                        self._get_active_buffer(),
                        self._get_active_cursor(),
                    )
                )
            else:
                self._set_active_cursor(len(self._get_active_buffer()))
            return

        if event.key == pygame.K_BACKSPACE:
            if event.mod & pygame.KMOD_CTRL:
                self._delete_word_before_cursor()
            else:
                self._delete_before_cursor()
            self._start_key_repeat(event)
            return

        if event.key == pygame.K_DELETE:
            if event.mod & pygame.KMOD_CTRL:
                self._delete_word_after_cursor()
            else:
                self._delete_after_cursor()
            self._start_key_repeat(event)
            return

        if event.key == pygame.K_RETURN:
            if self.active_field == "notes":
                self._insert_text("\n")
            return

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            self._insert_text(text)

    def _get_field_buffer(self, field):
        if field == "name":
            return self.name_buffer
        if field == "notes":
            return self.notes_buffer
        return ""

    def _set_field_buffer(self, field, value):
        value = str(value or "")
        if field == "name":
            self.name_buffer = value.replace("\n", " ")
            self.name_cursor = max(0, min(self.name_cursor, len(self.name_buffer)))
        elif field == "notes":
            self.notes_buffer = value
            self.notes_cursor = max(0, min(self.notes_cursor, len(self.notes_buffer)))

    def _get_field_cursor(self, field):
        buffer_text = self._get_field_buffer(field)
        if field == "name":
            self.name_cursor = max(0, min(self.name_cursor, len(buffer_text)))
            return self.name_cursor
        if field == "notes":
            self.notes_cursor = max(0, min(self.notes_cursor, len(buffer_text)))
            return self.notes_cursor
        return 0

    def _set_field_cursor(self, field, cursor):
        buffer_text = self._get_field_buffer(field)
        cursor = TextEditing.clamp_cursor(buffer_text, cursor)
        if field == "name":
            self.name_cursor = cursor
        elif field == "notes":
            self.notes_cursor = cursor

    def _get_active_buffer(self):
        return self._get_field_buffer(self.active_field)

    def _set_active_buffer(self, value):
        self._set_field_buffer(self.active_field, value)

    def _get_active_cursor(self):
        return self._get_field_cursor(self.active_field)

    def _set_active_cursor(self, cursor):
        self._set_field_cursor(self.active_field, cursor)

    def _insert_text(self, text):
        if self.active_field not in {"name", "notes"}:
            return False

        text = str(text)
        if self.active_field == "name":
            text = text.replace("\n", " ")

        buffer_text = self._get_active_buffer()
        cursor = self._get_active_cursor()
        buffer_text, cursor = TextEditing.insert_text(buffer_text, cursor, text)
        self._set_active_buffer(buffer_text)
        self._set_active_cursor(cursor)
        return True

    def _delete_before_cursor(self):
        buffer_text = self._get_active_buffer()
        cursor = self._get_active_cursor()
        buffer_text, cursor = TextEditing.delete_before_cursor(buffer_text, cursor)
        self._set_active_buffer(buffer_text)
        self._set_active_cursor(cursor)
        return True

    def _delete_after_cursor(self):
        buffer_text = self._get_active_buffer()
        cursor = self._get_active_cursor()
        buffer_text, cursor = TextEditing.delete_after_cursor(buffer_text, cursor)
        self._set_active_buffer(buffer_text)
        self._set_active_cursor(cursor)
        return True

    def _word_start_before_cursor(self, buffer_text, cursor):
        return TextEditing.word_start_before_cursor(buffer_text, cursor)

    def _word_end_after_cursor(self, buffer_text, cursor):
        return TextEditing.word_end_after_cursor(buffer_text, cursor)

    def _delete_word_before_cursor(self):
        buffer_text = self._get_active_buffer()
        cursor = self._get_active_cursor()
        buffer_text, cursor = TextEditing.delete_word_before_cursor(buffer_text, cursor)
        self._set_active_buffer(buffer_text)
        self._set_active_cursor(cursor)
        return True

    def _delete_word_after_cursor(self):
        buffer_text = self._get_active_buffer()
        cursor = self._get_active_cursor()
        buffer_text, cursor = TextEditing.delete_word_after_cursor(buffer_text, cursor)
        self._set_active_buffer(buffer_text)
        self._set_active_cursor(cursor)
        return True

    def _line_start_before_cursor(self, buffer_text, cursor):
        return TextEditing.line_start_before_cursor(buffer_text, cursor)

    def _line_end_after_cursor(self, buffer_text, cursor):
        return TextEditing.line_end_after_cursor(buffer_text, cursor)

    def _set_cursor_from_mouse(self, field, mouse_pos):
        font = self.layout_font
        rect = self.name_rect if field == "name" else self.notes_rect
        if font is None or rect is None:
            self._set_field_cursor(field, len(self._get_field_buffer(field)))
            return

        lines = self._wrap_edit_lines(
            self._get_field_buffer(field),
            font,
            rect.width - 12,
        )
        if field == "name":
            lines = lines[:1]

        line_h = font.get_height() + 2
        line_index = int((mouse_pos[1] - (rect.y + 6)) // max(1, line_h))
        line_index = max(0, min(line_index, len(lines) - 1))
        line_info = lines[line_index]
        line_text = line_info["text"]
        local_x = max(0, mouse_pos[0] - (rect.x + 6))

        best_offset = 0
        best_distance = None
        for offset in range(len(line_text) + 1):
            candidate_x = font.size(line_text[:offset])[0]
            distance = abs(candidate_x - local_x)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_offset = offset

        self._set_field_cursor(field, line_info["start"] + best_offset)

    def _start_key_repeat(self, event):
        if event.key not in {
            pygame.K_BACKSPACE,
            pygame.K_DELETE,
            pygame.K_LEFT,
            pygame.K_RIGHT,
        }:
            self._reset_key_repeat()
            return

        self.repeat_key = event.key
        self.repeat_mod = int(getattr(event, "mod", 0))
        self.next_repeat_ms = pygame.time.get_ticks() + self.KEY_REPEAT_DELAY_MS

    def _reset_key_repeat(self):
        self.repeat_key = None
        self.repeat_mod = 0
        self.next_repeat_ms = 0

    def _handle_repeat_key(self):
        if self.repeat_key == pygame.K_BACKSPACE:
            if self.repeat_mod & pygame.KMOD_CTRL:
                return self._delete_word_before_cursor()
            return self._delete_before_cursor()

        if self.repeat_key == pygame.K_DELETE:
            if self.repeat_mod & pygame.KMOD_CTRL:
                return self._delete_word_after_cursor()
            return self._delete_after_cursor()

        if self.repeat_key == pygame.K_LEFT:
            cursor = self._get_active_cursor()
            if self.repeat_mod & pygame.KMOD_CTRL:
                self._set_active_cursor(
                    self._word_start_before_cursor(self._get_active_buffer(), cursor)
                )
            else:
                self._set_active_cursor(cursor - 1)
            return True

        if self.repeat_key == pygame.K_RIGHT:
            cursor = self._get_active_cursor()
            if self.repeat_mod & pygame.KMOD_CTRL:
                self._set_active_cursor(
                    self._word_end_after_cursor(self._get_active_buffer(), cursor)
                )
            else:
                self._set_active_cursor(cursor + 1)
            return True

        return False

    def _update_key_repeat(self):
        if not self.is_text_input_active() or self.repeat_key is None:
            return

        pressed = pygame.key.get_pressed()
        if self.repeat_key >= len(pressed) or not pressed[self.repeat_key]:
            self._reset_key_repeat()
            return

        now_ms = pygame.time.get_ticks()
        while self.repeat_key is not None and now_ms >= self.next_repeat_ms:
            if not self._handle_repeat_key():
                self._reset_key_repeat()
                return
            self.next_repeat_ms += self.KEY_REPEAT_INTERVAL_MS
