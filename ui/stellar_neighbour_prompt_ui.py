import math

import pygame


class StellarNeighbourPromptUI:
    def __init__(self, host):
        object.__setattr__(self, "host", host)

    def __getattr__(self, name):
        return getattr(self.host, name)

    def __setattr__(self, name, value):
        setattr(self.host, name, value)

    def _is_star_system_entity(self, entity):
        if not isinstance(entity, dict):
            return False
        class_key = str(entity.get("location_class") or entity.get("system_class") or "").strip().lower()
        return (
            class_key in {"star_system", "stellar_system"}
            or entity.get("system_role") == "star_system"
        )

    def _build_stellar_system_matches(self, query_text, exclude_entity_id=None):
        if self.world_model is None:
            return []

        normalized_query = str(query_text or "").strip().lower()
        matches = []
        for entity in self.world_model.get_entities_by_dataset("locations"):
            if not self._is_star_system_entity(entity):
                continue
            entity_id = entity.get("id")
            if not entity_id or entity_id == exclude_entity_id:
                continue
            label = self._entity_display_label(entity, fallback=entity_id)
            haystack = f"{label} {entity_id} {entity.get('name', '')}".lower()
            if normalized_query and normalized_query not in haystack:
                continue
            matches.append({
                "id": entity_id,
                "pretty_name": label,
                "entity": entity,
            })
        matches.sort(key=lambda item: (item["pretty_name"].lower(), item["id"]))
        return matches[:12]

    def _open_stellar_neighbourhood_prompt(self, card):
        entity = self._entity_for_card(card)
        if not self._is_star_system_entity(entity):
            return False

        self.stellar_neighbourhood_prompt = {
            "source_entity_id": entity.get("id"),
            "query": "",
            "distance": "",
            "active_field": "system",
            "matches": self._build_stellar_system_matches("", exclude_entity_id=entity.get("id")),
            "selected_index": 0,
            "selected_system_id": None,
            "status": "",
            "rect": None,
            "system_rect": None,
            "distance_rect": None,
            "create_rect": None,
            "cancel_rect": None,
            "match_hitboxes": [],
        }
        self.show_template_picker = False
        self.entry_name_prompt = None
        self._build_template_picker_hitboxes()
        self._relayout_cards()
        return True

    def _open_stellar_neighbour_distance_prompt(self, source_card, target_id):
        source_entity = self._entity_for_card(source_card)
        target = self.world_model.get_entity(target_id) if self.world_model is not None else None
        if not self._is_star_system_entity(source_entity) or not self._is_star_system_entity(target):
            return False

        self._clear_relation_browser_link()
        self.stellar_neighbourhood_prompt = {
            "mode": "distance",
            "source_card": source_card,
            "source_entity_id": source_entity.get("id"),
            "target_entity_id": target_id,
            "query": self._entity_display_label(target, fallback=target_id),
            "distance": "",
            "active_field": "distance",
            "matches": [],
            "selected_index": 0,
            "selected_system_id": target_id,
            "status": "",
            "rect": None,
            "system_rect": None,
            "distance_rect": None,
            "create_rect": None,
            "cancel_rect": None,
            "match_hitboxes": [],
        }
        self.show_template_picker = False
        self.entry_name_prompt = None
        self.browser_search_active = False
        self._build_template_picker_hitboxes()
        self._relayout_cards()
        return True

    def _close_stellar_neighbourhood_prompt(self):
        self.stellar_neighbourhood_prompt = None

    def _set_stellar_prompt_query(self, text):
        prompt = self.stellar_neighbourhood_prompt
        if not isinstance(prompt, dict):
            return
        prompt["query"] = str(text or "")
        prompt["matches"] = self._build_stellar_system_matches(
            prompt["query"],
            exclude_entity_id=prompt.get("source_entity_id"),
        )
        prompt["selected_index"] = 0
        prompt["selected_system_id"] = None
        prompt["status"] = ""

    def _select_stellar_prompt_match(self, match_index=None):
        prompt = self.stellar_neighbourhood_prompt
        if not isinstance(prompt, dict):
            return False
        matches = prompt.get("matches") or []
        if not matches:
            return False
        if match_index is None:
            match_index = prompt.get("selected_index", 0)
        match_index = max(0, min(int(match_index), len(matches) - 1))
        match = matches[match_index]
        prompt["selected_index"] = match_index
        prompt["selected_system_id"] = match.get("id")
        prompt["query"] = match.get("pretty_name") or match.get("id") or ""
        prompt["active_field"] = "distance"
        prompt["status"] = ""
        return True

    def _upsert_stellar_neighbour(self, entity, target_id, distance_ly):
        rows = entity.get("stellar_neighbours")
        if not isinstance(rows, list):
            rows = []
        updated = False
        for row in rows:
            if isinstance(row, dict) and row.get("system") == target_id:
                row["distance_ly"] = distance_ly
                updated = True
                break
        if not updated:
            rows.append({"system": target_id, "distance_ly": distance_ly})
        rows.sort(key=lambda row: str(row.get("system", "")) if isinstance(row, dict) else "")
        entity["stellar_neighbours"] = rows

    def _arrange_stellar_neighbour_cards(self, source_id):
        source_card = self._find_card_by_entity_id(source_id)
        source_entity = self.world_model.get_entity(source_id) if self.world_model is not None else None
        if source_card is None or not isinstance(source_entity, dict):
            return
        rows = [
            row for row in source_entity.get("stellar_neighbours", []) or []
            if isinstance(row, dict) and row.get("system")
        ]
        count = max(1, len(rows))
        radius = 520
        for index, row in enumerate(rows):
            target_entity = self.world_model.get_entity(row.get("system")) if self.world_model is not None else None
            if not isinstance(target_entity, dict):
                continue
            target_card = self._ensure_card(target_entity, relayout=False, bring_to_front=False)
            if target_card is None:
                continue
            distance = 1.0
            try:
                distance = max(0.2, float(row.get("distance_ly") or 1.0))
            except (TypeError, ValueError):
                pass
            angle = (index / count) * 6.283185307179586
            scaled_radius = radius * min(2.2, max(0.55, distance / 5.0))
            target_card["canvas_x"] = source_card.get("canvas_x", 24) + math.cos(angle) * scaled_radius
            target_card["canvas_y"] = source_card.get("canvas_y", 84) + math.sin(angle) * scaled_radius

    def _confirm_stellar_neighbourhood_prompt(self):
        prompt = self.stellar_neighbourhood_prompt
        if not isinstance(prompt, dict) or self.world_model is None:
            return False
        source_id = prompt.get("source_entity_id")
        source_card = prompt.get("source_card")
        if not isinstance(source_card, dict):
            source_card = self._find_card_by_entity_id(source_id)
        source = self._entity_for_card(source_card) if source_card is not None else self.world_model.get_entity(source_id)
        target_id = prompt.get("selected_system_id")
        if not target_id:
            if not self._select_stellar_prompt_match():
                prompt["status"] = "Choose an existing star system"
                return True
            target_id = prompt.get("selected_system_id")
        target = self.world_model.get_entity(target_id)
        if not self._is_star_system_entity(source) or not self._is_star_system_entity(target):
            prompt["status"] = "Choose an existing star system"
            return True
        try:
            distance_ly = float(str(prompt.get("distance") or "").strip())
        except ValueError:
            prompt["status"] = "Enter distance in light years"
            return True
        if distance_ly <= 0:
            prompt["status"] = "Distance must be greater than 0"
            return True

        self._upsert_stellar_neighbour(source, target_id, distance_ly)
        self._upsert_stellar_neighbour(target, source_id, distance_ly)
        self._save_or_persist_card_for_entity_id(source_id)
        target_card = self._find_card_by_entity_id(target_id)
        if target_card is not None:
            self._save_or_persist_card_for_entity_id(target_id)
        else:
            self._persist_entity_to_repository(target)
        self._arrange_stellar_neighbour_cards(source_id)
        self._refresh_timeline_items()
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        self._close_stellar_neighbourhood_prompt()
        return True

    def _begin_stellar_neighbourhood_link(self, card):
        entity = self._entity_for_card(card)
        if not self._is_star_system_entity(entity):
            return False

        self.relation_link_target = {
            "mode": "stellar_neighbourhood",
            "source_card": card,
            "source_entity_id": card.get("entity_id"),
            "field_key": "stellar_neighbours",
            "target": "star_system",
        }
        status = "Choose an existing star system, then enter distance"
        card["active_relation_link_field"] = "stellar_neighbours"
        card["relation_link_status"] = status
        self.relation_link_status = status
        self.browser_filter_dataset = "locations"
        self.browser_filter_incomplete_only = False
        self.browser_collapsed = False
        self.browser_search_active = True
        self.browser_search_query = ""
        self.browser_scroll = 0
        self.browser_items = self._build_browser_items(self.world_model)
        self.show_template_picker = False
        self.entry_name_prompt = None
        self._build_template_picker_hitboxes()
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return True

    def _handle_stellar_neighbourhood_prompt_keydown(self, event):
        prompt = self.stellar_neighbourhood_prompt
        if not isinstance(prompt, dict):
            return False
        distance_only = prompt.get("mode") == "distance"
        active_field = prompt.get("active_field", "system")
        if event.key == pygame.K_ESCAPE:
            self._close_stellar_neighbourhood_prompt()
            self._relayout_cards()
            return True
        if event.key == pygame.K_TAB:
            prompt["active_field"] = "distance" if distance_only else ("distance" if active_field == "system" else "system")
            self._relayout_cards()
            return True
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if active_field == "system" and prompt.get("selected_system_id") is None:
                self._select_stellar_prompt_match()
                self._relayout_cards()
                return True
            return self._confirm_stellar_neighbourhood_prompt()
        if active_field == "system":
            matches = prompt.get("matches") or []
            if event.key == pygame.K_UP and matches:
                prompt["selected_index"] = max(0, int(prompt.get("selected_index", 0)) - 1)
                self._relayout_cards()
                return True
            if event.key == pygame.K_DOWN and matches:
                prompt["selected_index"] = min(len(matches) - 1, int(prompt.get("selected_index", 0)) + 1)
                self._relayout_cards()
                return True
            if event.key == pygame.K_BACKSPACE:
                self._set_stellar_prompt_query(str(prompt.get("query") or "")[:-1])
                self._relayout_cards()
                return True
            text = getattr(event, "unicode", "")
            if text and text.isprintable():
                self._set_stellar_prompt_query(str(prompt.get("query") or "") + text)
                self._relayout_cards()
                return True
            return True

        if event.key == pygame.K_BACKSPACE:
            prompt["distance"] = str(prompt.get("distance") or "")[:-1]
            prompt["status"] = ""
            self._relayout_cards()
            return True
        text = getattr(event, "unicode", "")
        if text and text in "0123456789.":
            prompt["distance"] = str(prompt.get("distance") or "") + text
            prompt["status"] = ""
            self._relayout_cards()
            return True
        return True


    def _draw_stellar_neighbourhood_prompt(self, screen, font):
        prompt = getattr(self, "stellar_neighbourhood_prompt", None)
        if not isinstance(prompt, dict) or self.layout is None:
            return

        right_rect = self.layout["right_rect"]
        prompt_w = min(460, max(340, right_rect.width - 48))
        distance_only = prompt.get("mode") == "distance"
        prompt_h = 212 if distance_only else 292
        prompt_rect = pygame.Rect(right_rect.right - prompt_w - 12, right_rect.y + 44, prompt_w, prompt_h)
        header_rect = pygame.Rect(prompt_rect.x, prompt_rect.y, prompt_rect.width, 48)
        system_rect = pygame.Rect(prompt_rect.x + 18, prompt_rect.y + 78, prompt_rect.width - 36, 30)
        distance_rect_y = system_rect.bottom + (32 if distance_only else 122)
        distance_rect = pygame.Rect(prompt_rect.x + 18, distance_rect_y, prompt_rect.width - 36, 30)
        cancel_rect = pygame.Rect(prompt_rect.right - 198, prompt_rect.bottom - 42, 86, 28)
        create_rect = pygame.Rect(prompt_rect.right - 104, prompt_rect.bottom - 42, 86, 28)

        prompt["rect"] = prompt_rect
        prompt["system_rect"] = system_rect
        prompt["distance_rect"] = distance_rect
        prompt["cancel_rect"] = cancel_rect
        prompt["create_rect"] = create_rect
        prompt["match_hitboxes"] = []

        pygame.draw.rect(screen, (28, 30, 38), prompt_rect)
        pygame.draw.rect(screen, (170, 170, 170), prompt_rect, 1)
        pygame.draw.rect(screen, (34, 38, 48), header_rect)
        pygame.draw.line(screen, (110, 110, 120), (header_rect.x, header_rect.bottom), (header_rect.right, header_rect.bottom), 1)

        source = self.world_model.get_entity(prompt.get("source_entity_id")) if self.world_model is not None else None
        source_name = self._entity_display_label(source, fallback=prompt.get("source_entity_id")) if source else "Star System"
        title = font.render("Define Neighbourhood", True, (244, 244, 244))
        detail = font.render(source_name, True, (166, 176, 194))
        screen.blit(title, (prompt_rect.x + 12, prompt_rect.y + 8))
        screen.blit(detail, (prompt_rect.x + 12, prompt_rect.y + 28))

        def draw_input(rect, label_text, value, placeholder, active):
            label = font.render(label_text, True, (188, 196, 212))
            screen.blit(label, (rect.x, rect.y - 18))
            border = (210, 224, 248) if active else (150, 162, 186)
            pygame.draw.rect(screen, (38, 43, 56), rect)
            pygame.draw.rect(screen, border, rect, 1)
            text = str(value or "")
            display = text if text else placeholder
            color = (238, 238, 238) if text else (126, 136, 154)
            surface = font.render(self._ellipsize_text(display, font, rect.width - 16), True, color)
            screen.blit(surface, (rect.x + 8, rect.y + 6))

        target = self.world_model.get_entity(prompt.get("target_entity_id")) if self.world_model is not None else None
        system_label = "selected system" if distance_only else "star system"
        draw_input(
            system_rect,
            system_label,
            self._entity_display_label(target, fallback=prompt.get("target_entity_id")) if target else prompt.get("query"),
            "Search existing systems",
            prompt.get("active_field") == "system" and not distance_only,
        )

        matches = prompt.get("matches") or []
        selected_index = int(prompt.get("selected_index", 0))
        match_y = system_rect.bottom + 4
        for index, match in enumerate([] if distance_only else matches[:5]):
            row_rect = pygame.Rect(system_rect.x, match_y + index * 20, system_rect.width, 19)
            prompt["match_hitboxes"].append((index, row_rect))
            selected = index == selected_index
            pygame.draw.rect(screen, (52, 64, 86) if selected else (31, 36, 48), row_rect)
            pygame.draw.rect(screen, (138, 164, 206) if selected else (72, 82, 104), row_rect, 1)
            label = self._ellipsize_text(match.get("pretty_name", match.get("id", "")), font, row_rect.width - 12)
            surface = font.render(label, True, (240, 244, 250) if selected else (188, 198, 216))
            screen.blit(surface, (row_rect.x + 6, row_rect.y + 2))

        draw_input(
            distance_rect,
            "distance (ly)",
            prompt.get("distance"),
            "Light years",
            prompt.get("active_field") == "distance",
        )

        status = str(prompt.get("status") or "")
        if status:
            status_surface = font.render(status, True, (230, 154, 132))
            screen.blit(status_surface, (prompt_rect.x + 18, distance_rect.bottom + 6))

        mouse_pos = pygame.mouse.get_pos()
        for rect, label, primary in (
            (cancel_rect, "Cancel", False),
            (create_rect, "Save", True),
        ):
            hovered = rect.collidepoint(mouse_pos)
            fill = (72, 92, 132) if primary else (42, 48, 62)
            if hovered:
                fill = (88, 108, 150) if primary else (56, 64, 82)
            pygame.draw.rect(screen, fill, rect)
            pygame.draw.rect(screen, (164, 176, 198), rect, 1)
            label_surface = font.render(label, True, (244, 244, 244))
            screen.blit(label_surface, label_surface.get_rect(center=rect.center))

    def _handle_stellar_neighbourhood_prompt_click(self, mouse_pos):
        prompt = getattr(self, "stellar_neighbourhood_prompt", None)
        if not isinstance(prompt, dict):
            return False
        cancel_rect = prompt.get("cancel_rect")
        if cancel_rect is not None and cancel_rect.collidepoint(mouse_pos):
            self._close_stellar_neighbourhood_prompt()
            self._relayout_cards()
            return True
        create_rect = prompt.get("create_rect")
        if create_rect is not None and create_rect.collidepoint(mouse_pos):
            self._confirm_stellar_neighbourhood_prompt()
            return True
        system_rect = prompt.get("system_rect")
        if system_rect is not None and system_rect.collidepoint(mouse_pos):
            if prompt.get("mode") != "distance":
                prompt["active_field"] = "system"
            return True
        distance_rect = prompt.get("distance_rect")
        if distance_rect is not None and distance_rect.collidepoint(mouse_pos):
            prompt["active_field"] = "distance"
            return True
        for match_index, match_rect in prompt.get("match_hitboxes", []):
            if match_rect.collidepoint(mouse_pos):
                self._select_stellar_prompt_match(match_index)
                self._relayout_cards()
                return True
        return True

