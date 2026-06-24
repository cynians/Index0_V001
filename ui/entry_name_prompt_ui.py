import pygame

from ui.card import EntityCard


class EntryNamePromptUI:
    def __init__(self, host):
        object.__setattr__(self, "host", host)

    def __getattr__(self, name):
        return getattr(self.host, name)

    def __setattr__(self, name, value):
        setattr(self.host, name, value)

    def _open_entry_name_prompt(self, template, mode="template", context=None, label=None, initial_buffer=""):
        label = label or "Entry"
        if isinstance(template, dict):
            label = template.get("label") or self._schema_display_label(template.get("entity_type"))
        elif mode == "idea_from_parent":
            label = "Idea"

        self.entry_name_prompt = {
            "template": template,
            "mode": mode,
            "context": context or {},
            "label": label,
            "buffer": str(initial_buffer or ""),
            "cursor": len(str(initial_buffer or "")),
            "description_buffer": "",
            "description_cursor": 0,
            "active_prompt_field": "name",
            "rect": None,
            "input_rect": None,
            "description_rect": None,
            "suggestion_hitboxes": [],
            "suggestion_selected_index": 0,
            "suggestion_keyboard_active": False,
            "create_rect": None,
            "cancel_rect": None,
            "status": "",
        }
        self._refresh_entry_name_prompt_suggestions()
        self.show_template_picker = False
        self.template_picker_status = ""
        self._build_template_picker_hitboxes()
        return True

    def _open_new_entry_name_prompt(self):
        self.pending_new_entry_name = None
        return self._open_entry_name_prompt(
            None,
            mode="new_entry",
            context=self._relation_tab_new_entry_context(),
        )

    def _relation_tab_new_entry_context(self):
        for card in reversed(self.cards):
            card_view = card.get("card_view") if isinstance(card, dict) else None
            if card_view is None or getattr(card_view, "active_tab", "") != "relations":
                continue
            entity_id = str(card.get("entity_id") or "").strip()
            if not entity_id or card.get("card_kind") == "schema":
                continue

            field_key = str(card.get("active_relation_link_field") or card.get("active_edit_field") or "").strip()
            if not field_key or not hasattr(card_view, "is_relation_edit_field") or not card_view.is_relation_edit_field(field_key):
                field_key = "related"
            return {
                "link_source_entity_id": entity_id,
                "link_field_key": field_key,
            }
        return {}

    def _entry_name_prompt_uses_suggestions(self, prompt=None):
        prompt = prompt or self.entry_name_prompt
        return isinstance(prompt, dict) and prompt.get("mode") in {"new_entry", "entry_description"}

    def _entry_description_prompt_matches(self, query_text, limit=7, prompt=None):
        prompt = prompt or self.entry_name_prompt
        if self.world_model is None or getattr(self.world_model, "loader", None) is None:
            return []
        if not isinstance(prompt, dict):
            return []

        normalized_query = str(query_text or "").strip().lower()
        if not normalized_query:
            return []

        template = prompt.get("template")
        if not isinstance(template, dict):
            return []

        dataset_name = str(template.get("dataset_name") or "").strip()
        initial_fields = self._template_initial_fields(template)
        subclass_field = str(template.get("subclass_field") or "").strip()
        subclass_value = initial_fields.get(subclass_field) if subclass_field else None
        normalized_subclass = self._normalize_schema_name(subclass_value) if subclass_field else ""

        if dataset_name and hasattr(self.world_model, "get_entities_by_dataset"):
            entities = self.world_model.get_entities_by_dataset(dataset_name)
        else:
            datasets = getattr(getattr(self.world_model, "loader", None), "datasets", {}) or {}
            entities = datasets.get(dataset_name, []) if dataset_name else []
        matches_by_description = {}
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            if subclass_field:
                entity_subclass = self._normalize_schema_name(entity.get(subclass_field))
                if entity_subclass != normalized_subclass:
                    continue

            description = str(entity.get("three_word_description") or "").strip()
            if not description or normalized_query not in description.lower():
                continue

            key = description.lower()
            if key in matches_by_description:
                continue

            label = self._entity_display_label(entity, fallback=entity.get("id", ""))
            class_label = self._schema_display_label(subclass_value) if subclass_field else self._schema_display_label(dataset_name)
            matches_by_description[key] = {
                "id": description,
                "label": description,
                "subtitle": " | ".join(part for part in (class_label, str(label)) if part),
                "card_color": entity.get("card_color") or entity.get("wiki_link_color") or "",
                "rank": 0 if description.lower() == normalized_query else (1 if description.lower().startswith(normalized_query) else 2),
            }

        matches = list(matches_by_description.values())
        matches.sort(key=lambda item: (item["rank"], item["label"].lower()))
        return matches[:limit]

    def _entry_name_prompt_matches(self, query_text, limit=7, prompt=None):
        prompt = prompt or self.entry_name_prompt
        if isinstance(prompt, dict) and prompt.get("mode") == "entry_description":
            return self._entry_description_prompt_matches(query_text, limit=limit, prompt=prompt)

        if self.world_model is None or getattr(self.world_model, "loader", None) is None:
            return []

        normalized_query = str(query_text or "").strip().lower()
        if not normalized_query:
            return []

        entities = getattr(self.world_model.loader, "entities", {}) or {}
        matches = []
        for entity in entities.values():
            if not isinstance(entity, dict):
                continue
            entity_id = str(entity.get("id") or "").strip()
            if not entity_id:
                continue

            label = self._entity_display_label(entity, fallback=entity_id)
            dataset = str(entity.get("_dataset") or entity.get("dataset") or "")
            entity_type = str(entity.get("type") or "entry")
            haystack = " ".join(
                [
                    str(label),
                    entity_id,
                    str(entity.get("common_name", "")),
                    str(entity.get("binomial_name", "")),
                    str(entity.get("pretty_name", "")),
                    str(entity.get("name", "")),
                    entity_type,
                    dataset,
                ]
            ).lower()
            if normalized_query not in haystack:
                continue

            label_l = str(label).lower()
            id_l = entity_id.lower()
            if label_l == normalized_query or id_l == normalized_query:
                rank = 0
            elif label_l.startswith(normalized_query) or id_l.startswith(normalized_query):
                rank = 1
            else:
                rank = 2
            matches.append(
                {
                    "id": entity_id,
                    "label": str(label),
                    "subtitle": " | ".join(part for part in (dataset, entity_type) if part),
                    "card_color": entity.get("card_color") or entity.get("wiki_link_color") or "",
                    "rank": rank,
                }
            )

        matches.sort(key=lambda item: (item["rank"], item["label"].lower(), item["id"]))
        return matches[:limit]

    def _refresh_entry_name_prompt_suggestions(self):
        prompt = self.entry_name_prompt
        if not self._entry_name_prompt_uses_suggestions(prompt):
            return

        matches = self._entry_name_prompt_matches(prompt.get("buffer", ""), prompt=prompt)
        prompt["suggestion_matches"] = matches
        prompt["suggestion_hitboxes"] = []
        if not matches:
            prompt["suggestion_selected_index"] = 0
            prompt["suggestion_keyboard_active"] = False
            return

        selected = max(0, min(int(prompt.get("suggestion_selected_index", 0)), len(matches) - 1))
        prompt["suggestion_selected_index"] = selected

    def _select_entry_name_prompt_suggestion(self, index=None, link_from_context=True):
        prompt = self.entry_name_prompt
        if not self._entry_name_prompt_uses_suggestions(prompt):
            return False

        matches = prompt.get("suggestion_matches") or []
        if not matches:
            return False

        if index is None:
            index = int(prompt.get("suggestion_selected_index", 0))
        index = max(0, min(int(index), len(matches) - 1))
        if prompt.get("mode") == "entry_description":
            description = str(matches[index].get("label") or matches[index].get("id") or "").strip()
            prompt["buffer"] = description
            prompt["cursor"] = len(description)
            prompt["suggestion_keyboard_active"] = False
            self._refresh_entry_name_prompt_suggestions()
            return True

        entity_id = str(matches[index].get("id") or "").strip()
        if not entity_id or self.world_model is None:
            return False

        context = dict(prompt.get("context") or {})
        entity = self.world_model.get_entity(entity_id)
        self._close_entry_name_prompt()
        if entity is not None:
            if link_from_context:
                self._link_entry_name_prompt_result(entity_id, context)
            self._ensure_card(entity)
            return True
        return False


    def _close_entry_name_prompt(self):
        self.entry_name_prompt = None


    def _open_relation_note_prompt(self, source_card, relation_info, initial_text=""):
        if source_card is None or not isinstance(relation_info, dict):
            return False
        return self._open_entry_name_prompt(
            None,
            mode="relation_note",
            context={
                "source_entity_id": source_card.get("entity_id"),
                "card": source_card,
                "field_key": relation_info.get("field_key"),
            },
            label="Note",
            initial_buffer=initial_text,
        )


    def _handle_entry_name_prompt_keydown(self, event):
        prompt = self.entry_name_prompt
        if not isinstance(prompt, dict):
            return False

        active_field = "description" if (
            prompt.get("mode") in {"illustration_from_parent"}
            and prompt.get("active_prompt_field") == "description"
        ) else "name"
        buffer_key = "description_buffer" if active_field == "description" else "buffer"
        cursor_key = "description_cursor" if active_field == "description" else "cursor"
        buffer_text = str(prompt.get(buffer_key, ""))
        cursor = max(0, min(int(prompt.get(cursor_key, len(buffer_text))), len(buffer_text)))

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if (
                active_field == "name"
                and self._entry_name_prompt_uses_suggestions(prompt)
                and prompt.get("suggestion_keyboard_active")
                and prompt.get("suggestion_matches")
            ):
                return self._select_entry_name_prompt_suggestion()
            return self._submit_entry_name_prompt()
        if (
            active_field == "name"
            and self._entry_name_prompt_uses_suggestions(prompt)
            and event.key in (pygame.K_UP, pygame.K_DOWN)
        ):
            matches = prompt.get("suggestion_matches") or []
            if matches:
                selected = int(prompt.get("suggestion_selected_index", 0))
                selected += -1 if event.key == pygame.K_UP else 1
                prompt["suggestion_selected_index"] = selected % len(matches)
                prompt["suggestion_keyboard_active"] = True
            return True
        if event.key == pygame.K_TAB and prompt.get("mode") == "illustration_from_parent":
            prompt["active_prompt_field"] = "name" if active_field == "description" else "description"
            return True
        if event.key == pygame.K_ESCAPE:
            self._close_entry_name_prompt()
            return True
        if event.key == pygame.K_BACKSPACE:
            if cursor > 0:
                prompt[buffer_key] = buffer_text[:cursor - 1] + buffer_text[cursor:]
                prompt[cursor_key] = cursor - 1
                prompt["status"] = ""
                prompt["suggestion_keyboard_active"] = False
                self._refresh_entry_name_prompt_suggestions()
            return True
        if event.key == pygame.K_DELETE:
            if cursor < len(buffer_text):
                prompt[buffer_key] = buffer_text[:cursor] + buffer_text[cursor + 1:]
                prompt["status"] = ""
                prompt["suggestion_keyboard_active"] = False
                self._refresh_entry_name_prompt_suggestions()
            return True
        if event.key == pygame.K_LEFT:
            prompt[cursor_key] = max(0, cursor - 1)
            return True
        if event.key == pygame.K_RIGHT:
            prompt[cursor_key] = min(len(buffer_text), cursor + 1)
            return True
        if event.key == pygame.K_HOME:
            prompt[cursor_key] = 0
            return True
        if event.key == pygame.K_END:
            prompt[cursor_key] = len(buffer_text)
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            prompt[buffer_key] = buffer_text[:cursor] + text + buffer_text[cursor:]
            prompt[cursor_key] = cursor + len(text)
            prompt["status"] = ""
            prompt["suggestion_keyboard_active"] = False
            self._refresh_entry_name_prompt_suggestions()
            return True

        return True

    def _handle_entry_name_prompt_click(self, mouse_pos):
        prompt = self.entry_name_prompt
        if not isinstance(prompt, dict):
            return False

        for index, hitbox in prompt.get("suggestion_hitboxes", []):
            if hitbox.collidepoint(mouse_pos):
                prompt["suggestion_selected_index"] = index
                prompt["suggestion_keyboard_active"] = True
                return self._select_entry_name_prompt_suggestion(index)

        cancel_rect = prompt.get("cancel_rect")
        if cancel_rect is not None and cancel_rect.collidepoint(mouse_pos):
            self._close_entry_name_prompt()
            return True

        create_rect = prompt.get("create_rect")
        if create_rect is not None and create_rect.collidepoint(mouse_pos):
            return self._submit_entry_name_prompt()

        input_rect = prompt.get("input_rect")
        if input_rect is not None and input_rect.collidepoint(mouse_pos):
            prompt["active_prompt_field"] = "name"
            return True

        description_rect = prompt.get("description_rect")
        if description_rect is not None and description_rect.collidepoint(mouse_pos):
            prompt["active_prompt_field"] = "description"
            return True

        return True


    def _draw_entry_name_prompt(self, screen, font):
        prompt = self.entry_name_prompt
        if not isinstance(prompt, dict) or self.layout is None:
            return

        right_rect = self.layout["right_rect"]
        prompt_w = min(420, max(300, right_rect.width - 48))
        is_illustration_prompt = prompt.get("mode") == "illustration_from_parent"
        is_star_class_prompt = prompt.get("mode") == "star_system_class"
        suggestion_matches = prompt.get("suggestion_matches") or []
        suggestion_count = len(suggestion_matches) if self._entry_name_prompt_uses_suggestions(prompt) else 0
        suggestion_h = suggestion_count * 30 + (10 if suggestion_count else 0)
        prompt_h = 194 if is_illustration_prompt else (196 if is_star_class_prompt else 148 + suggestion_h)
        prompt_x = right_rect.right - prompt_w - 12
        prompt_y = right_rect.y + 44
        prompt_rect = pygame.Rect(prompt_x, prompt_y, prompt_w, prompt_h)
        header_rect = pygame.Rect(prompt_rect.x, prompt_rect.y, prompt_rect.width, 48)
        input_rect = pygame.Rect(prompt_rect.x + 18, prompt_rect.y + 72, prompt_rect.width - 36, 30)
        description_rect = None
        if is_illustration_prompt:
            description_rect = pygame.Rect(prompt_rect.x + 18, input_rect.bottom + 28, prompt_rect.width - 36, 30)
        cancel_rect = pygame.Rect(prompt_rect.right - 198, prompt_rect.bottom - 42, 86, 28)
        create_rect = pygame.Rect(prompt_rect.right - 104, prompt_rect.bottom - 42, 86, 28)

        prompt["rect"] = prompt_rect
        prompt["input_rect"] = input_rect
        prompt["description_rect"] = description_rect
        prompt["cancel_rect"] = cancel_rect
        prompt["create_rect"] = create_rect
        prompt["suggestion_hitboxes"] = []

        pygame.draw.rect(screen, (28, 30, 38), prompt_rect)
        pygame.draw.rect(screen, (170, 170, 170), prompt_rect, 1)
        pygame.draw.rect(screen, (34, 38, 48), header_rect)
        pygame.draw.line(
            screen,
            (110, 110, 120),
            (header_rect.x, header_rect.bottom),
            (header_rect.right, header_rect.bottom),
            1,
        )

        if prompt.get("mode") == "idea_from_parent":
            prompt_title = "Name New Idea"
        elif prompt.get("mode") == "illustration_from_parent":
            prompt_title = "Add Illustration"
        elif prompt.get("mode") == "toolbelt":
            prompt_title = f"Name New {prompt.get('label') or 'Entry'}"
        elif prompt.get("mode") == "star_system_class":
            prompt_title = "Choose Star Class"
        elif prompt.get("mode") == "entry_description":
            prompt_title = "Add Short Description"
        else:
            prompt_title = "Name New Entry"
        title = font.render(prompt_title, True, (244, 244, 244))
        detail = font.render(str(prompt.get("label") or "Entry"), True, (166, 176, 194))
        screen.blit(title, (prompt_rect.x + 12, prompt_rect.y + 8))
        screen.blit(detail, (prompt_rect.x + 12, prompt_rect.y + 28))

        if prompt.get("mode") == "star_system_class":
            name_label_text = "star class"
        elif prompt.get("mode") == "entry_description":
            name_label_text = "short description (optional)"
        else:
            name_label_text = "name"
        name_label = font.render(name_label_text, True, (188, 196, 212))
        screen.blit(name_label, (input_rect.x, input_rect.y - 18))

        def draw_prompt_input(field_rect, buffer_key, cursor_key, placeholder, active_field_name):
            active = prompt.get("active_prompt_field") == active_field_name
            border = (210, 224, 248) if active else (150, 162, 186)
            pygame.draw.rect(screen, (38, 43, 56), field_rect)
            pygame.draw.rect(screen, border, field_rect, 1)
            buffer_text = str(prompt.get(buffer_key, ""))
            cursor = max(0, min(int(prompt.get(cursor_key, len(buffer_text))), len(buffer_text)))
            visible_text = buffer_text
            max_input_text_w = field_rect.width - 18
            while visible_text and font.size(visible_text)[0] > max_input_text_w:
                visible_text = visible_text[1:]

            hidden_prefix_len = len(buffer_text) - len(visible_text)
            display_text = visible_text if buffer_text else placeholder
            text_color = (238, 238, 238) if buffer_text else (126, 136, 154)
            text_surface = font.render(display_text, True, text_color)
            screen.blit(text_surface, (field_rect.x + 8, field_rect.y + 6))

            if active:
                visible_cursor = max(0, cursor - hidden_prefix_len)
                cursor_x = field_rect.x + 8 + font.size(visible_text[:visible_cursor])[0]
                pygame.draw.line(
                    screen,
                    (236, 236, 236),
                    (cursor_x, field_rect.y + 6),
                    (cursor_x, field_rect.bottom - 6),
                    1,
                )

        if prompt.get("mode") == "star_system_class":
            name_placeholder = "G2V, K5V, M3V, or O/B/A/F/G/K/M"
        elif prompt.get("mode") == "entry_description":
            name_placeholder = "Optional"
        else:
            name_placeholder = "Entry name"
        draw_prompt_input(input_rect, "buffer", "cursor", name_placeholder, "name")

        if suggestion_matches:
            selected_index = max(0, min(int(prompt.get("suggestion_selected_index", 0)), len(suggestion_matches) - 1))
            row_y = input_rect.bottom + 8
            for index, match in enumerate(suggestion_matches):
                row_rect = pygame.Rect(input_rect.x, row_y, input_rect.width, 26)
                color = self._coerce_hex_rgb(match.get("card_color"), fallback=(54, 70, 96))
                fill = EntityCard._mix_color(color, (22, 25, 34), 0.68)
                border = EntityCard._mix_color(color, (228, 234, 246), 0.35)
                if index == selected_index and prompt.get("suggestion_keyboard_active"):
                    fill = EntityCard._mix_color(color, (64, 92, 134), 0.36)
                    border = EntityCard._mix_color(color, (238, 242, 250), 0.18)
                pygame.draw.rect(screen, fill, row_rect)
                pygame.draw.rect(screen, border, row_rect, 1)

                label = self._ellipsize_text(match.get("label", ""), font, row_rect.width - 124)
                subtitle = self._ellipsize_text(match.get("subtitle", ""), font, 104)
                text_color = (246, 248, 252)
                muted_color = (176, 188, 208)
                screen.blit(font.render(label, True, text_color), (row_rect.x + 8, row_rect.y + 5))
                if subtitle:
                    subtitle_surface = font.render(subtitle, True, muted_color)
                    screen.blit(subtitle_surface, (row_rect.right - subtitle_surface.get_width() - 8, row_rect.y + 5))
                prompt["suggestion_hitboxes"].append((index, row_rect))
                row_y += 30

        if is_star_class_prompt:
            help_text = "Valid: OBAFGKM + 0-9 + Ia/Ib/II/III/IV/V/VI/VII. Example: G2V."
            help_surface = font.render(help_text, True, (158, 170, 190))
            screen.blit(help_surface, (input_rect.x, input_rect.bottom + 6))

        if description_rect is not None:
            description_label = font.render("description", True, (188, 196, 212))
            screen.blit(description_label, (description_rect.x, description_rect.y - 18))
            draw_prompt_input(
                description_rect,
                "description_buffer",
                "description_cursor",
                "Illustration description",
                "description",
            )

        status = str(prompt.get("status") or "")
        if status:
            status_surface = font.render(status, True, (230, 154, 132))
            status_y = (description_rect.bottom if description_rect is not None else input_rect.bottom) + (24 if is_star_class_prompt else 6)
            screen.blit(status_surface, (prompt_rect.x + 18, status_y))

        mouse_pos = pygame.mouse.get_pos()
        for rect, label, primary in (
            (cancel_rect, "Cancel", False),
            (create_rect, "Create", True),
        ):
            hovered = rect.collidepoint(mouse_pos)
            fill = (72, 92, 132) if primary else (42, 48, 62)
            if hovered:
                fill = (88, 108, 150) if primary else (56, 64, 82)
            pygame.draw.rect(screen, fill, rect)
            pygame.draw.rect(screen, (164, 176, 198), rect, 1)
            label_surface = font.render(label, True, (244, 244, 244))
            screen.blit(label_surface, label_surface.get_rect(center=rect.center))
