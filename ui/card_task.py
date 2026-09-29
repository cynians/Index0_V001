import pygame


class CardTaskMixin:
    def _is_task_card(self):
        return self.dataset_name == "tasks" or self.entity.get("type") == "task"

    def _task_is_finished(self):
        return str(self.entity.get("entry_status") or "").strip().lower() in {
            "finished",
            "complete",
            "completed",
            "done",
        }

    def _task_checklist_items(self):
        raw_items = self.entity.get("checklist")
        if not isinstance(raw_items, list):
            return []

        items = []
        for item in raw_items:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("label") or item.get("name") or "").strip()
                done = bool(item.get("done", item.get("checked", False)))
            else:
                text = str(item or "").strip()
                done = False
            if text:
                items.append({"text": text, "done": done})
        return items

    def _task_checklist_completion(self):
        items = self._task_checklist_items()
        if not items:
            return 0
        done_count = sum(1 for item in items if item.get("done"))
        return int(round((done_count / len(items)) * 100))

    def _measure_task_checklist_height(self, font, width, card=None):
        if not self._is_task_card():
            return 0

        line_h = self._table_line_height(font)
        items = self._task_checklist_items()
        input_active = bool(card and card.get("task_checklist_input_active"))
        height = line_h + 8
        height += 24
        height += 4
        height += max(1, len(items)) * (line_h + 6)
        height += 8
        height += 26 if input_active else 22
        return max(92, height)

    def _draw_checkbox(self, screen, font, rect, checked):
        pygame.draw.rect(screen, (24, 28, 36), rect)
        pygame.draw.rect(screen, (202, 208, 222), rect, 1)
        if checked:
            mark = font.render("x", True, (236, 240, 248))
            screen.blit(mark, mark.get_rect(center=rect.center))

    def _draw_task_checklist(self, screen, font, card):
        checklist_rect = card.get("task_checklist_rect")
        if checklist_rect is None or not self._is_task_card():
            return

        pygame.draw.rect(screen, (26, 30, 40), checklist_rect)
        pygame.draw.rect(screen, (92, 102, 124), checklist_rect, 1)

        line_h = self._table_line_height(font)
        text_x = checklist_rect.x + 24
        finish_rect = card.get("task_finish_checkbox_rect")
        finished = self._task_is_finished()
        if finish_rect is not None:
            self._draw_checkbox(screen, font, finish_rect, finished)
        finish_text = font.render("Finish Task", True, (236, 238, 244))
        screen.blit(finish_text, (text_x, checklist_rect.y + 2))

        completion = self._task_checklist_completion()
        header_y = checklist_rect.y + line_h + 8
        header_text = font.render(f"[Checklist] ({completion}% Complete)", True, (202, 210, 226))
        screen.blit(header_text, (checklist_rect.x + 4, header_y))

        items = self._task_checklist_items()
        row_y = header_y + line_h + 8
        checkbox_by_index = {
            index: rect
            for index, rect in card.get("task_checklist_hitboxes", [])
        }
        if items:
            for index, item in enumerate(items):
                checkbox_rect = checkbox_by_index.get(index)
                if checkbox_rect is not None:
                    self._draw_checkbox(screen, font, checkbox_rect, bool(item.get("done")))
                text_color = (178, 188, 206) if item.get("done") else (232, 234, 240)
                label = self._ellipsize_text(
                    item.get("text", ""),
                    font,
                    checklist_rect.width - 58,
                )
                item_surface = font.render(label, True, text_color)
                screen.blit(item_surface, (checklist_rect.x + 40, row_y))
                row_y += line_h + 6
        else:
            empty_surface = font.render("No checklist items", True, (142, 152, 170))
            screen.blit(empty_surface, (checklist_rect.x + 18, row_y))
            row_y += line_h + 6

        input_rect = card.get("task_checklist_input_rect")
        if input_rect is None:
            return

        input_active = bool(card.get("task_checklist_input_active"))
        fill = (40, 48, 64) if input_active else (30, 34, 44)
        border = (180, 202, 236) if input_active else (88, 98, 118)
        pygame.draw.rect(screen, fill, input_rect)
        pygame.draw.rect(screen, border, input_rect, 1)
        buffer_text = str(card.get("task_checklist_input_buffer") or "")
        placeholder = "Add checklist item..."
        text_color = (238, 238, 238) if buffer_text else (138, 148, 166)
        visible_text = buffer_text or placeholder
        visible_text = self._ellipsize_text(visible_text, font, input_rect.width - 14)
        input_surface = font.render(visible_text, True, text_color)
        screen.blit(input_surface, (input_rect.x + 6, input_rect.y + 3))
