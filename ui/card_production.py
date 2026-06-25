import pygame


class CardProductionMixin:
    def _is_producer_card(self):
        return self.dataset_name == "producers" or self.entity.get("type") == "producer"

    def _is_production_mode(self):
        return self.active_tab == "production" and self._is_producer_card()

    def _production_product_field_for_id(self, product_id):
        entity = self.world_model.get_entity(product_id) if self.world_model is not None and product_id else None
        dataset = str((entity or {}).get("_dataset") or "").strip().lower()
        entity_type = str((entity or {}).get("type") or "").strip().lower()
        if dataset == "vehicles" or entity_type == "vehicle":
            return "produced_vehicles"
        if dataset == "components" or entity_type in {"component", "assembly"}:
            return "produced_components"
        return "produced_items"

    def _production_output_field_for_id(self, product_id):
        field_key = self._production_product_field_for_id(product_id)
        return {
            "produced_vehicles": "output_vehicles",
            "produced_components": "output_components",
            "produced_items": "output_items",
        }.get(field_key, "output_items")

    def _producer_entity_id(self):
        return str(self.entity.get("id") or "").strip()

    def _production_slug(self, value):
        text = str(value or "").strip().lower()
        return "".join(char if char.isalnum() else "_" for char in text).strip("_") or "entry"

    def _production_line_entity_id(self, product_id, location_id=""):
        producer_id = self._producer_entity_id()
        base = "_".join(
            part
            for part in (
                "prodline",
                self._production_slug(producer_id),
                self._production_slug(product_id),
                self._production_slug(location_id) if location_id else "",
            )
            if part
        )
        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) if self.world_model is not None else {}
        if base not in entities:
            return base
        index = 2
        while f"{base}_{index}" in entities:
            index += 1
        return f"{base}_{index}"

    def _production_product_id_from_entity(self, entity):
        if not isinstance(entity, dict):
            return ""
        for field_key in ("output_vehicles", "output_components", "output_items", "output_materials"):
            ids = self._relation_entity_ids(entity.get(field_key))
            if ids:
                return ids[0]
        return ""

    def _production_line_from_entity(self, entity):
        if not isinstance(entity, dict):
            return None
        product_id = self._production_product_id_from_entity(entity)
        if not product_id:
            return None
        period = str(entity.get("production_rate_period") or entity.get("rate_period") or "month").strip().lower()
        if period not in {"year", "month", "week"}:
            period = "month"
        return {
            "production_id": str(entity.get("id") or "").strip(),
            "product_id": product_id,
            "location_id": str(entity.get("production_location") or entity.get("location_id") or "").strip(),
            "rate_value": "" if entity.get("production_rate_value") is None else str(entity.get("production_rate_value")),
            "rate_period": period,
            "start_year": "" if entity.get("start_year") is None else str(entity.get("start_year")),
            "end_year": "" if entity.get("end_year") is None else str(entity.get("end_year")),
        }

    def _production_lines(self):
        lines = []
        seen = set()
        producer_id = self._producer_entity_id()
        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) if self.world_model is not None else {}
        for entity in entities.values():
            if not isinstance(entity, dict):
                continue
            if entity.get("_dataset") != "production" and entity.get("type") != "production":
                continue
            if producer_id not in self._relation_entity_ids(entity.get("produced_by")):
                continue
            line = self._production_line_from_entity(entity)
            if not line:
                continue
            key = line.get("production_id") or (line["product_id"], line.get("location_id", ""))
            if key in seen:
                continue
            seen.add(key)
            lines.append(line)

        for raw_line in self.entity.get("production_lines") or []:
            if not isinstance(raw_line, dict):
                continue
            product_id = str(raw_line.get("product_id") or raw_line.get("product") or raw_line.get("id") or "").strip()
            if not product_id:
                continue
            location_id = str(raw_line.get("location_id") or raw_line.get("production_location") or "").strip()
            key = ("legacy", product_id, location_id)
            if key in seen:
                continue
            seen.add(key)
            lines.append(
                {
                    "production_id": "",
                    "product_id": product_id,
                    "location_id": location_id,
                    "rate_value": "" if raw_line.get("rate_value") is None else str(raw_line.get("rate_value")),
                    "rate_period": str(raw_line.get("rate_period") or "month"),
                    "start_year": "" if raw_line.get("start_year") is None else str(raw_line.get("start_year")),
                    "end_year": "" if raw_line.get("end_year") is None else str(raw_line.get("end_year")),
                }
            )
        for field_key in ("produced_vehicles", "produced_components", "produced_items"):
            for product_id in self._relation_entity_ids(self.entity.get(field_key)):
                key = (product_id, "")
                if product_id and key not in seen:
                    seen.add(key)
                    lines.append({"production_id": "", "product_id": product_id, "location_id": "", "rate_value": "", "rate_period": "month", "start_year": "", "end_year": ""})
        return lines

    def _production_requirements_for_product(self, product_id):
        product = self.world_model.get_entity(product_id) if self.world_model is not None and product_id else None
        groups = {"materials": [], "components": [], "items": []}
        if not isinstance(product, dict):
            return groups

        def add_unique(group_key, value):
            for entity_id in self._relation_entity_ids(value):
                if entity_id and entity_id not in groups[group_key]:
                    groups[group_key].append(entity_id)

        add_unique("materials", product.get("production_materials_needed"))
        add_unique("materials", product.get("required_materials"))
        add_unique("materials", product.get("input_materials"))
        add_unique("materials", product.get("primary_material"))
        add_unique("materials", product.get("secondary_materials"))
        add_unique("components", product.get("production_components_needed"))
        add_unique("components", product.get("required_components"))
        add_unique("components", product.get("input_components"))
        add_unique("items", product.get("production_items_needed"))
        add_unique("items", product.get("required_items"))
        add_unique("items", product.get("input_items"))
        add_unique("items", product.get("component_equivalent"))
        add_unique("items", product.get("represented_item"))
        return groups

    def _production_requirement_items(self, product_id):
        groups = self._production_requirements_for_product(product_id)
        items = []
        for group_key, label in (("materials", "Material"), ("components", "Component"), ("items", "Item")):
            for entity_id in groups.get(group_key, []):
                items.append({"id": entity_id, "group": group_key, "label": label})
        return items

    def _production_line_entity_for_line(self, line):
        production_id = str((line or {}).get("production_id") or "").strip()
        entity = self.world_model.get_entity(production_id) if self.world_model is not None and production_id else None
        return entity if isinstance(entity, dict) else None

    def _mark_production_entity_update(self, card, entity_id):
        entity_id = str(entity_id or "").strip()
        if not entity_id:
            return
        updates = list(card.get("production_related_entity_update_ids") or [])
        if entity_id not in updates:
            updates.append(entity_id)
        card["production_related_entity_update_ids"] = updates

    def _build_production_line_entity(self, product_id, location_id=""):
        producer_id = self._producer_entity_id()
        product_label = self._entity_label_for_id(product_id)
        producer_label = self._entity_label_for_id(producer_id)
        entity_id = self._production_line_entity_id(product_id, location_id)
        output_field = self._production_output_field_for_id(product_id)
        entity = {
            "id": entity_id,
            "pretty_name": f"{producer_label} - {product_label} Production",
            "name": f"{producer_label} - {product_label} Production",
            "type": "production",
            "_dataset": "production",
            "production_class": "production_line",
            "produced_by": [producer_id] if producer_id else [],
            "production_location": str(location_id or "").strip(),
            "production_rate_value": "",
            "production_rate_period": "month",
            "start_year": "",
            "end_year": "",
            "input_materials": [],
            "input_items": [],
            "input_components": [],
            "output_materials": [],
            "output_items": [],
            "output_components": [],
            "output_vehicles": [],
        }
        entity[output_field] = [product_id]
        return entity

    def _ensure_production_line_entity(self, card, line):
        entity = self._production_line_entity_for_line(line)
        if entity is not None:
            return entity
        product_id = str((line or {}).get("product_id") or "").strip()
        if not product_id or self.world_model is None:
            return None
        entity = self._build_production_line_entity(product_id, (line or {}).get("location_id", ""))
        entity["production_rate_value"] = str((line or {}).get("rate_value") or "")
        entity["production_rate_period"] = str((line or {}).get("rate_period") or "month")
        entity["start_year"] = str((line or {}).get("start_year") or "")
        entity["end_year"] = str((line or {}).get("end_year") or "")
        loader = getattr(self.world_model, "loader", None)
        if loader is not None:
            loader.datasets.setdefault("production", []).append(entity)
            loader.entities[entity["id"]] = entity
        self._mark_production_entity_update(card, entity.get("id"))
        return entity

    def _production_entity_matches(self, query_text, target):
        query = str(query_text or "").strip().lower()
        target = str(target or "product").strip().lower()
        allowed_datasets = {"locations"} if target == "location" else {"vehicles", "components", "items"}
        allowed_types = {"location"} if target == "location" else {"vehicle", "component", "assembly", "item"}
        matches = []
        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) if self.world_model is not None else {}
        for entity_id, entity in entities.items():
            if not isinstance(entity, dict):
                continue
            dataset = str(entity.get("_dataset") or "").strip().lower()
            entity_type = str(entity.get("type") or "").strip().lower()
            if dataset not in allowed_datasets and entity_type not in allowed_types:
                continue
            label = self._entity_display_label(entity)
            haystack = " ".join([str(entity_id), label, str(entity.get("pretty_name") or ""), str(entity.get("name") or "")]).lower()
            if query and query not in haystack:
                continue
            matches.append({"id": entity_id, "label": label, "subtitle": dataset or entity_type})
            if len(matches) >= 8:
                break
        return matches

    def _refresh_production_matches(self, card):
        if not card.get("production_input_active"):
            card["production_matches"] = []
            card["production_match_rows"] = []
            card["production_selected_index"] = 0
            return
        if card.get("production_active_field") in {"rate", "start_year", "end_year"}:
            card["production_matches"] = []
            card["production_match_rows"] = []
            card["production_selected_index"] = 0
            return
        target = "location" if card.get("production_active_field") == "location" else "product"
        card["production_matches"] = self._production_entity_matches(card.get("production_query", ""), target)
        card["production_match_rows"] = []
        if card["production_matches"]:
            card["production_selected_index"] = max(0, min(int(card.get("production_selected_index", 0) or 0), len(card["production_matches"]) - 1))
        else:
            card["production_selected_index"] = 0

    def _production_period_label(self, period):
        return {"year": "Year", "month": "Month", "week": "Week"}.get(str(period or "month").lower(), "Month")

    def _production_rate_label(self, line):
        value = str(line.get("rate_value") or "").strip()
        if not value:
            return "Production rate missing"
        return f"Produces {value} a {self._production_period_label(line.get('rate_period')).lower()}"

    def _mark_production_commit(self, card):
        if "production_lines" in self.entity:
            self.entity.pop("production_lines", None)
            self._mark_production_entity_update(card, self._producer_entity_id())
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = "production"
        return True

    def _add_production_line(self, card, product_id=None):
        if not product_id:
            matches = card.get("production_matches") or []
            if not matches:
                return False
            index = max(0, min(int(card.get("production_selected_index", 0) or 0), len(matches) - 1))
            product_id = matches[index].get("id")
        product_id = str(product_id or "").strip()
        if not product_id:
            return False
        if self.world_model is None:
            return False
        entity = self._build_production_line_entity(product_id)
        loader = getattr(self.world_model, "loader", None)
        if loader is not None:
            loader.datasets.setdefault("production", []).append(entity)
            loader.entities[entity["id"]] = entity
        self._mark_production_entity_update(card, entity.get("id"))
        card["production_query"] = ""
        card["production_input_active"] = False
        card["production_matches"] = []
        return self._mark_production_commit(card)

    def _update_production_line(self, card, line_index, **updates):
        lines = self._production_lines()
        try:
            line_index = int(line_index)
        except (TypeError, ValueError):
            return False
        if line_index < 0 or line_index >= len(lines):
            return False
        line = dict(lines[line_index])
        line.update(updates)
        entity = self._ensure_production_line_entity(card, line)
        if entity is None:
            return False
        if "location_id" in updates:
            entity["production_location"] = str(updates.get("location_id") or "").strip()
        if "rate_value" in updates:
            entity["production_rate_value"] = str(updates.get("rate_value") or "").strip()
        if "rate_period" in updates:
            period = str(updates.get("rate_period") or "month").strip().lower()
            entity["production_rate_period"] = period if period in {"week", "month", "year"} else "month"
        if "start_year" in updates:
            entity["start_year"] = str(updates.get("start_year") or "").strip()
        if "end_year" in updates:
            entity["end_year"] = str(updates.get("end_year") or "").strip()
        self._mark_production_entity_update(card, entity.get("id"))
        return self._mark_production_commit(card)

    def _remove_production_line(self, card, line_index):
        lines = self._production_lines()
        try:
            line_index = int(line_index)
        except (TypeError, ValueError):
            return False
        if line_index < 0 or line_index >= len(lines):
            return False
        production_id = str(lines[line_index].get("production_id") or "").strip()
        if production_id:
            removed = list(card.get("production_removed_entity_ids") or [])
            if production_id not in removed:
                removed.append(production_id)
            card["production_removed_entity_ids"] = removed
        else:
            product_id = str(lines[line_index].get("product_id") or "").strip()
            changed = False
            for field_key in ("produced_vehicles", "produced_components", "produced_items"):
                values = self._relation_entity_ids(self.entity.get(field_key))
                if product_id in values:
                    self.entity[field_key] = [value for value in values if value != product_id]
                    changed = True
            if changed:
                self._mark_production_entity_update(card, self._producer_entity_id())
        return self._mark_production_commit(card)

    def _set_production_input(self, card, field_name, line_index=None):
        card["production_input_active"] = True
        card["production_active_field"] = field_name
        card["production_active_line"] = line_index
        card["production_query"] = ""
        if field_name in {"rate", "start_year", "end_year"} and line_index is not None:
            lines = self._production_lines()
            try:
                line_index_value = int(line_index)
            except (TypeError, ValueError):
                line_index_value = -1
            if 0 <= line_index_value < len(lines):
                value_key = "rate_value" if field_name == "rate" else field_name
                card["production_query"] = str(lines[line_index_value].get(value_key) or "")
        self._refresh_production_matches(card)
        return True

    def _handle_production_keydown(self, card, event):
        if not self._is_production_mode() or not card.get("production_input_active"):
            return False

        field_name = card.get("production_active_field") or "product"
        line_index = card.get("production_active_line")
        if event.key == pygame.K_ESCAPE:
            card["production_input_active"] = False
            card["production_matches"] = []
            card["last_edit_action"] = "cancel"
            return True

        matches = card.get("production_matches") or []
        if event.key == pygame.K_UP and matches:
            card["production_selected_index"] = max(0, int(card.get("production_selected_index", 0) or 0) - 1)
            return True
        if event.key == pygame.K_DOWN and matches:
            card["production_selected_index"] = min(len(matches) - 1, int(card.get("production_selected_index", 0) or 0) + 1)
            return True

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if field_name == "product":
                return self._add_production_line(card)
            if field_name == "location":
                if not matches:
                    return False
                index = max(0, min(int(card.get("production_selected_index", 0) or 0), len(matches) - 1))
                card["production_input_active"] = False
                return self._update_production_line(card, line_index, location_id=matches[index].get("id"))
            if field_name == "rate":
                card["production_input_active"] = False
                return self._update_production_line(card, line_index, rate_value=str(card.get("production_query") or "").strip())
            if field_name in {"start_year", "end_year"}:
                card["production_input_active"] = False
                return self._update_production_line(card, line_index, **{field_name: str(card.get("production_query") or "").strip()})

        if event.key == pygame.K_BACKSPACE:
            card["production_query"] = str(card.get("production_query", ""))[:-1]
            self._refresh_production_matches(card)
            card["last_edit_action"] = "draft"
            return True
        if event.key == pygame.K_DELETE:
            card["production_query"] = ""
            self._refresh_production_matches(card)
            card["last_edit_action"] = "draft"
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            if field_name == "rate" and not (text.isdigit() or text in {".", ","}):
                return True
            if field_name in {"start_year", "end_year"} and not (text.isdigit() or text in {"-", "+"}):
                return True
            card["production_query"] = str(card.get("production_query", "")) + text
            self._refresh_production_matches(card)
            card["last_edit_action"] = "draft"
            return True
        return False

    def handle_production_click(self, card, mouse_pos):
        if not self._is_production_mode() or not card.get("is_edit_mode", False):
            return False

        for info in card.get("production_hitboxes", []):
            rect = info.get("rect")
            if rect is None or not rect.collidepoint(mouse_pos):
                continue
            kind = info.get("kind")
            line_index = info.get("line_index")
            if kind == "product_input":
                return self._set_production_input(card, "product")
            if kind == "product_add":
                if card.get("production_input_active") and card.get("production_active_field") == "product" and card.get("production_matches"):
                    return self._add_production_line(card)
                return self._set_production_input(card, "product")
            if kind == "location_input":
                return self._set_production_input(card, "location", line_index=line_index)
            if kind == "rate_input":
                return self._set_production_input(card, "rate", line_index=line_index)
            if kind == "start_year_input":
                return self._set_production_input(card, "start_year", line_index=line_index)
            if kind == "end_year_input":
                return self._set_production_input(card, "end_year", line_index=line_index)
            if kind == "period":
                lines = self._production_lines()
                periods = ["week", "month", "year"]
                current = lines[int(line_index)].get("rate_period", "month") if line_index is not None and 0 <= int(line_index) < len(lines) else "month"
                next_period = periods[(periods.index(current) + 1) % len(periods)] if current in periods else "month"
                return self._update_production_line(card, line_index, rate_period=next_period)
            if kind == "remove_line":
                return self._remove_production_line(card, line_index)

        for row in card.get("production_match_rows", []):
            rect = row.get("rect")
            if rect is None or not rect.collidepoint(mouse_pos):
                continue
            match = row.get("match") or {}
            field_name = card.get("production_active_field")
            line_index = card.get("production_active_line")
            if field_name == "product":
                return self._add_production_line(card, match.get("id"))
            if field_name == "location":
                card["production_input_active"] = False
                return self._update_production_line(card, line_index, location_id=match.get("id"))

        return False

    def _layout_production_content(self, card, content_left, current_y, text_width):
        font = card["layout_font"]
        row_gap = 8
        card["production_hitboxes"] = []
        card["production_match_rows"] = []
        card["production_line_rows"] = []
        header_rect = pygame.Rect(content_left, current_y, text_width, self.SECTION_HEADER_H)
        card["production_section_rect"] = header_rect
        current_y = header_rect.bottom + self.SECTION_GAP + 6

        if card.get("is_edit_mode", False):
            input_rect = pygame.Rect(content_left, current_y, max(120, text_width - 78), 24)
            add_rect = pygame.Rect(input_rect.right + 6, current_y, 72, 24)
            card["production_hitboxes"].append({"kind": "product_input", "rect": input_rect})
            card["production_hitboxes"].append({"kind": "product_add", "rect": add_rect})
            card["production_product_input_rect"] = input_rect
            card["production_product_add_rect"] = add_rect
            current_y = input_rect.bottom + 4
            if card.get("production_input_active") and card.get("production_active_field") == "product":
                for index, match in enumerate((card.get("production_matches") or [])[:5]):
                    row_rect = pygame.Rect(content_left, current_y, min(text_width, input_rect.width + 150), 22)
                    card["production_match_rows"].append({"index": index, "match": match, "rect": row_rect})
                    current_y = row_rect.bottom + 2
            current_y += row_gap
        else:
            card["production_product_input_rect"] = None
            card["production_product_add_rect"] = None

        lines = self._production_lines()
        if not lines:
            empty_rect = pygame.Rect(content_left, current_y, text_width, 34)
            card["production_empty_rect"] = empty_rect
            current_y = empty_rect.bottom + row_gap
            return current_y
        card["production_empty_rect"] = None

        for line_index, line in enumerate(lines):
            section_rect = pygame.Rect(content_left, current_y, text_width, 30)
            current_y = section_rect.bottom + 4
            location_rect = pygame.Rect(content_left + 18, current_y, max(120, text_width - 36), 26)
            current_y = location_rect.bottom + 4
            rate_w = max(84, min(120, int(text_width * 0.28)))
            period_w = 82
            rate_rect = pygame.Rect(content_left + 18, current_y, rate_w, 24)
            period_rect = pygame.Rect(rate_rect.right + 6, current_y, period_w, 24)
            current_y = rate_rect.bottom + 4
            year_w = max(72, min(96, int(text_width * 0.24)))
            start_year_rect = pygame.Rect(content_left + 58, current_y, year_w, 24)
            end_year_rect = pygame.Rect(start_year_rect.right + 42, current_y, year_w, 24)
            current_y = start_year_rect.bottom + 4
            requirements_rect = pygame.Rect(content_left + 34, current_y, max(120, text_width - 52), 24)
            current_y = requirements_rect.bottom + row_gap
            remove_rect = None
            requirement_chips = []
            if card.get("is_edit_mode", False):
                remove_rect = pygame.Rect(section_rect.right - 24, section_rect.y + 6, 18, 18)
                card["production_hitboxes"].extend(
                    [
                        {"kind": "remove_line", "line_index": line_index, "rect": remove_rect},
                        {"kind": "location_input", "line_index": line_index, "rect": location_rect},
                        {"kind": "rate_input", "line_index": line_index, "rect": rate_rect},
                        {"kind": "period", "line_index": line_index, "rect": period_rect},
                        {"kind": "start_year_input", "line_index": line_index, "rect": start_year_rect},
                        {"kind": "end_year_input", "line_index": line_index, "rect": end_year_rect},
                    ]
                )
            chip_x = content_left + 52
            chip_y = requirements_rect.bottom + 2
            chip_right = content_left + text_width - 6
            for requirement in self._production_requirement_items(line.get("product_id")):
                chip_label = f"{requirement.get('label')}: {self._entity_label_for_id(requirement.get('id'))}"
                label_w = min(210, max(82, font.size(chip_label)[0] + 14))
                if chip_x + label_w > chip_right and chip_x > content_left + 52:
                    chip_x = content_left + 52
                    chip_y += 24
                chip_rect = pygame.Rect(chip_x, chip_y, label_w, 22)
                requirement_chips.append({"id": requirement.get("id"), "group": requirement.get("group"), "label": requirement.get("label"), "rect": chip_rect})
                chip_x = chip_rect.right + 6
            if requirement_chips:
                current_y = max(current_y, chip_y + 24 + row_gap)
            if card.get("production_input_active") and card.get("production_active_line") == line_index and card.get("production_active_field") == "location":
                anchor = location_rect
                for index, match in enumerate((card.get("production_matches") or [])[:5]):
                    row_rect = pygame.Rect(anchor.x, current_y, min(text_width - 18, anchor.width + 150), 22)
                    card["production_match_rows"].append({"index": index, "match": match, "rect": row_rect})
                    current_y = row_rect.bottom + 2
                current_y += 4
            card["production_line_rows"].append(
                {
                    "line_index": line_index,
                    "line": line,
                    "section_rect": section_rect,
                    "location_rect": location_rect,
                    "rate_rect": rate_rect,
                    "period_rect": period_rect,
                    "start_year_rect": start_year_rect,
                    "end_year_rect": end_year_rect,
                    "requirements_rect": requirements_rect,
                    "remove_rect": remove_rect,
                    "requirement_chips": requirement_chips,
                }
            )
        return current_y

    def _draw_production_match_rows(self, screen, font, card):
        selected_index = int(card.get("production_selected_index", 0) or 0)
        for row in card.get("production_match_rows", []):
            row_rect = row.get("rect")
            if row_rect is None:
                continue
            index = int(row.get("index", 0) or 0)
            match = row.get("match") or {}
            selected = index == selected_index
            pygame.draw.rect(screen, (52, 64, 86) if selected else (31, 36, 48), row_rect)
            pygame.draw.rect(screen, (138, 164, 206) if selected else (72, 82, 104), row_rect, 1)
            label = self._ellipsize_text(match.get("label", ""), font, row_rect.width - 110)
            subtitle = self._ellipsize_text(match.get("subtitle", ""), font, 96)
            screen.blit(font.render(label, True, (240, 244, 250) if selected else (188, 198, 216)), (row_rect.x + 6, row_rect.y + 3))
            if subtitle:
                subtitle_surface = font.render(subtitle, True, (176, 188, 208))
                screen.blit(subtitle_surface, (row_rect.right - subtitle_surface.get_width() - 6, row_rect.y + 3))

    def _draw_production_content(self, screen, font, card):
        section_rect = card.get("production_section_rect")
        if section_rect is not None:
            pygame.draw.rect(screen, (34, 38, 48), section_rect)
            pygame.draw.rect(screen, (86, 96, 116), section_rect, 1)
            screen.blit(font.render("Production", True, (232, 236, 244)), (section_rect.x + 8, section_rect.y + 3))

        if card.get("is_edit_mode", False):
            input_rect = card.get("production_product_input_rect")
            add_rect = card.get("production_product_add_rect")
            active = bool(card.get("production_input_active")) and card.get("production_active_field") == "product"
            if input_rect is not None:
                pygame.draw.rect(screen, (40, 46, 60) if active else (30, 34, 44), input_rect)
                pygame.draw.rect(screen, (190, 208, 236) if active else (94, 104, 124), input_rect, 1)
                query = str(card.get("production_query", "")) if active else ""
                display = query if query else "Search item, component, or vehicle"
                color = (238, 240, 246) if query else (132, 142, 160)
                screen.blit(font.render(self._ellipsize_text(display, font, input_rect.width - 12), True, color), (input_rect.x + 6, input_rect.y + 4))
            if add_rect is not None:
                pygame.draw.rect(screen, (54, 70, 98), add_rect)
                pygame.draw.rect(screen, (150, 172, 210), add_rect, 1)
                add_text = font.render("Add", True, (244, 246, 250))
                screen.blit(add_text, add_text.get_rect(center=add_rect.center))

        empty_rect = card.get("production_empty_rect")
        if empty_rect is not None:
            pygame.draw.rect(screen, (30, 34, 44), empty_rect)
            pygame.draw.rect(screen, (82, 92, 112), empty_rect, 1)
            screen.blit(font.render("No production lines yet", True, (150, 160, 178)), (empty_rect.x + 8, empty_rect.y + 8))

        for row in card.get("production_line_rows", []):
            line = row.get("line") or {}
            section_rect = row.get("section_rect")
            if section_rect is None:
                continue
            pygame.draw.rect(screen, (36, 42, 56), section_rect)
            pygame.draw.rect(screen, (96, 112, 142), section_rect, 1)
            product_label = self._ellipsize_text(self._entity_label_for_id(line.get("product_id")), font, section_rect.width - 46)
            screen.blit(font.render(product_label, True, (238, 242, 250)), (section_rect.x + 8, section_rect.y + 7))
            remove_rect = row.get("remove_rect")
            if remove_rect is not None:
                pygame.draw.rect(screen, (70, 40, 46), remove_rect)
                pygame.draw.rect(screen, (178, 116, 124), remove_rect, 1)
                remove_surface = font.render("x", True, (250, 220, 224))
                screen.blit(remove_surface, remove_surface.get_rect(center=remove_rect.center))

            location_rect = row.get("location_rect")
            location_id = line.get("location_id", "")
            if location_rect is not None:
                pygame.draw.rect(screen, (30, 34, 44), location_rect)
                pygame.draw.rect(screen, (94, 104, 124), location_rect, 1)
                location_label = self._entity_label_for_id(location_id) if location_id else "Select production location"
                screen.blit(font.render(self._ellipsize_text(location_label, font, location_rect.width - 12), True, (232, 236, 244) if location_id else (132, 142, 160)), (location_rect.x + 6, location_rect.y + 5))

            rate_rect = row.get("rate_rect")
            period_rect = row.get("period_rect")
            if rate_rect is not None:
                rate_active = bool(card.get("production_input_active")) and card.get("production_active_field") == "rate" and card.get("production_active_line") == row.get("line_index")
                pygame.draw.rect(screen, (40, 46, 60) if rate_active else (30, 34, 44), rate_rect)
                pygame.draw.rect(screen, (190, 208, 236) if rate_active else (94, 104, 124), rate_rect, 1)
                rate_text = str(card.get("production_query", "")) if rate_active else str(line.get("rate_value") or "")
                screen.blit(font.render(rate_text or "amount", True, (238, 240, 246) if rate_text else (132, 142, 160)), (rate_rect.x + 6, rate_rect.y + 4))
            if period_rect is not None:
                pygame.draw.rect(screen, (42, 52, 70), period_rect)
                pygame.draw.rect(screen, (126, 150, 190), period_rect, 1)
                period_text = font.render(f"/ {self._production_period_label(line.get('rate_period'))}", True, (238, 242, 250))
                screen.blit(period_text, period_text.get_rect(center=period_rect.center))
                if rate_rect is not None:
                    rate_label = self._production_rate_label(line)
                    screen.blit(font.render(rate_label, True, (176, 188, 208)), (period_rect.right + 8, rate_rect.y + 4))

            start_year_rect = row.get("start_year_rect")
            end_year_rect = row.get("end_year_rect")
            if start_year_rect is not None:
                screen.blit(font.render("From", True, (176, 188, 208)), (start_year_rect.x - 40, start_year_rect.y + 4))
                start_active = bool(card.get("production_input_active")) and card.get("production_active_field") == "start_year" and card.get("production_active_line") == row.get("line_index")
                pygame.draw.rect(screen, (40, 46, 60) if start_active else (30, 34, 44), start_year_rect)
                pygame.draw.rect(screen, (190, 208, 236) if start_active else (94, 104, 124), start_year_rect, 1)
                start_text = str(card.get("production_query", "")) if start_active else str(line.get("start_year") or "")
                screen.blit(font.render(start_text or "year", True, (238, 240, 246) if start_text else (132, 142, 160)), (start_year_rect.x + 6, start_year_rect.y + 4))
            if end_year_rect is not None:
                screen.blit(font.render("To", True, (176, 188, 208)), (end_year_rect.x - 24, end_year_rect.y + 4))
                end_active = bool(card.get("production_input_active")) and card.get("production_active_field") == "end_year" and card.get("production_active_line") == row.get("line_index")
                pygame.draw.rect(screen, (40, 46, 60) if end_active else (30, 34, 44), end_year_rect)
                pygame.draw.rect(screen, (190, 208, 236) if end_active else (94, 104, 124), end_year_rect, 1)
                end_text = str(card.get("production_query", "")) if end_active else str(line.get("end_year") or "")
                screen.blit(font.render(end_text or "year", True, (238, 240, 246) if end_text else (132, 142, 160)), (end_year_rect.x + 6, end_year_rect.y + 4))

            requirements_rect = row.get("requirements_rect")
            if requirements_rect is not None:
                pygame.draw.rect(screen, (30, 34, 44), requirements_rect)
                pygame.draw.rect(screen, (94, 104, 124), requirements_rect, 1)
                requirement_label = "Requires from product card" if row.get("requirement_chips") else "No product requirements set"
                screen.blit(font.render(self._ellipsize_text(requirement_label, font, requirements_rect.width - 12), True, (176, 188, 208)), (requirements_rect.x + 6, requirements_rect.y + 4))
            for chip in row.get("requirement_chips", []):
                chip_rect = chip.get("rect")
                if chip_rect is None:
                    continue
                chip_color = {
                    "materials": (56, 50, 38),
                    "components": (38, 52, 64),
                    "items": (38, 58, 54),
                }.get(chip.get("group"), (42, 48, 58))
                border_color = {
                    "materials": (190, 166, 104),
                    "components": (116, 166, 210),
                    "items": (122, 190, 170),
                }.get(chip.get("group"), (126, 138, 160))
                pygame.draw.rect(screen, chip_color, chip_rect)
                pygame.draw.rect(screen, border_color, chip_rect, 1)
                chip_label = f"{chip.get('label')}: {self._entity_label_for_id(chip.get('id'))}"
                screen.blit(font.render(self._ellipsize_text(chip_label, font, chip_rect.width - 10), True, (232, 240, 238)), (chip_rect.x + 5, chip_rect.y + 3))

        self._draw_production_match_rows(screen, font, card)
