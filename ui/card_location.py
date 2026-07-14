import pygame

from world.year_utils import parse_year


def _query_matches_text(query, text):
    terms = [term for term in str(query or "").strip().casefold().split() if term]
    if not terms:
        return True
    haystack = str(text or "").casefold()
    return all(term in haystack for term in terms)


class CardLocationMixin:
    def _is_location_mode(self):
        return self.active_tab == "location"

    def _is_location_entity(self, entity):
        return isinstance(entity, dict) and (
            entity.get("_dataset") == "locations"
            or entity.get("type") == "location"
        )

    def _location_display_label(self, entity, fallback=None):
        if not isinstance(entity, dict):
            return str(fallback or "")
        return str(
            entity.get("pretty_name")
            or entity.get("name")
            or entity.get("common_name")
            or entity.get("label")
            or fallback
            or entity.get("id")
            or ""
        )

    def _default_location_mode(self):
        dataset = str(self.dataset_name or self.entity.get("_dataset") or "").lower()
        entity_type = str(self.entity.get("type") or "").lower()
        if dataset in {"people", "pops"} or entity_type in {"person", "character", "individual", "pop"}:
            return "exclusive"
        return "multiple"

    def _location_mode_value(self):
        mode = str(self.entity.get("location_mode") or "").strip().lower()
        return mode if mode in {"exclusive", "multiple"} else self._default_location_mode()

    def _coerce_location_year(self, value):
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            parsed = parse_year(value)
            return parsed

    def _normalize_location_history_entry(self, value):
        if isinstance(value, str):
            location_id = value.strip()
            return {"location_id": location_id} if location_id else None
        if not isinstance(value, dict):
            return None

        location_id = (
            value.get("location_id")
            or value.get("id")
            or value.get("entity_id")
            or value.get("location")
        )
        location_id = str(location_id or "").strip()
        if not location_id:
            return None

        normalized = {"location_id": location_id}
        start_year = self._coerce_location_year(value.get("start_year"))
        end_year = self._coerce_location_year(value.get("end_year"))
        if start_year is not None:
            normalized["start_year"] = start_year
        if end_year is not None:
            normalized["end_year"] = end_year
        note = str(value.get("note") or "").strip()
        if note:
            normalized["note"] = note
        return normalized

    def _location_history_entries(self):
        entries = []
        seen = set()

        for raw_entry in self.entity.get("location_history") or []:
            entry = self._normalize_location_history_entry(raw_entry)
            if not entry:
                continue
            key = (
                entry.get("location_id"),
                entry.get("start_year"),
                entry.get("end_year"),
                entry.get("note", ""),
            )
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)

        for legacy_key in ("location_entity", "associated_locations", "locations"):
            for location_id in self._relation_entity_ids(self.entity.get(legacy_key)):
                key = (location_id, None, None, "")
                if key in seen:
                    continue
                seen.add(key)
                entries.append({"location_id": location_id})

        return entries

    def _sync_location_relation_fields(self):
        entries = self._location_history_entries()
        self.entity["location_history"] = entries
        location_ids = []
        for entry in entries:
            location_id = str(entry.get("location_id") or "").strip()
            if location_id and location_id not in location_ids:
                location_ids.append(location_id)
        self.entity["associated_locations"] = location_ids
        return location_ids

    def _is_location_card(self):
        return self._is_location_entity(self.entity)

    def _location_topology_ids(self, entity=None, field_key=None):
        entity = entity if isinstance(entity, dict) else self.entity
        field_key = str(field_key or "")
        ids = []
        for location_id in self._relation_entity_ids(entity.get(field_key)):
            if location_id and location_id not in ids:
                ids.append(location_id)
        return ids

    def _set_location_topology_ids(self, entity, field_key, ids):
        if not isinstance(entity, dict) or field_key not in self.LOCATION_TOPOLOGY_FIELDS:
            return False
        normalized = []
        entity_id = str(entity.get("id") or "")
        for location_id in ids or []:
            location_id = str(location_id or "").strip()
            if not location_id or location_id == entity_id or location_id in normalized:
                continue
            normalized.append(location_id)
        if normalized:
            entity[field_key] = normalized
        elif field_key in entity:
            entity[field_key] = []
        return True

    def _mark_related_location_update(self, card, location_id):
        location_id = str(location_id or "").strip()
        if not location_id:
            return
        update_ids = card.setdefault("location_related_entity_update_ids", [])
        if location_id not in update_ids:
            update_ids.append(location_id)

    def _location_topology_match_field(self, card):
        active = str(card.get("location_topology_active_field") or "").strip()
        return active if active in self.LOCATION_TOPOLOGY_EDITABLE_FIELDS else "constituents"

    def _location_topology_virtual_field(self, field_key):
        field_key = str(field_key or "").strip()
        if field_key not in self.LOCATION_TOPOLOGY_FIELDS:
            return ""
        return f"{self.LOCATION_TOPOLOGY_FIELD_PREFIX}{field_key}"

    def _location_topology_field_from_virtual(self, field_key):
        field_key = str(field_key or "")
        if not field_key.startswith(self.LOCATION_TOPOLOGY_FIELD_PREFIX):
            return ""
        topology_field = field_key[len(self.LOCATION_TOPOLOGY_FIELD_PREFIX):]
        return topology_field if topology_field in self.LOCATION_TOPOLOGY_FIELDS else ""

    def is_location_topology_relation_field(self, field_key):
        return bool(self._location_topology_field_from_virtual(field_key))

    def _build_location_topology_matches(self, card, field_key=None, query_text=None, limit=7):
        field_key = field_key or self._location_topology_match_field(card)
        query_text = card.get("location_topology_query", "") if query_text is None else query_text
        existing = set(self._location_topology_ids(self.entity, field_key))
        current_id = str(self.entity.get("id") or "")
        matches = []
        for match in self._build_location_matches(query_text, limit=50):
            match_id = str(match.get("id") or "")
            if not match_id or match_id == current_id or match_id in existing:
                continue
            matches.append(match)
            if len(matches) >= limit:
                break
        return matches

    def refresh_location_topology_matches(self, card):
        if not card.get("location_topology_input_active"):
            card["location_topology_matches"] = []
            card["location_topology_match_rows"] = []
            card["location_topology_selected_index"] = 0
            return
        matches = self._build_location_topology_matches(card)
        card["location_topology_matches"] = matches
        card["location_topology_match_rows"] = []
        if not matches:
            card["location_topology_selected_index"] = 0
            return
        card["location_topology_selected_index"] = max(
            0,
            min(int(card.get("location_topology_selected_index", 0) or 0), len(matches) - 1),
        )

    def _sync_added_location_topology_relation(self, card, field_key, target_id):
        if self.world_model is None:
            return
        current_id = str(self.entity.get("id") or "").strip()
        if not current_id or not target_id:
            return
        target = self.world_model.get_entity(target_id)
        if not self._is_location_entity(target):
            return

        if field_key in self.LOCATION_TOPOLOGY_SYMMETRIC_FIELDS:
            target_ids = self._location_topology_ids(target, field_key)
            if current_id not in target_ids:
                target_ids.append(current_id)
                self._set_location_topology_ids(target, field_key, target_ids)
                self._mark_related_location_update(card, target_id)
            return

        if field_key == "parents":
            constituent_ids = self._relation_entity_ids(target.get("constituents"))
            if current_id not in constituent_ids:
                constituent_ids.append(current_id)
                target["constituents"] = constituent_ids
                self._mark_related_location_update(card, target_id)
            self.entity["parent_location"] = target_id
            return

        if field_key == "constituents":
            parent_ids = self._relation_entity_ids(target.get("parents"))
            if current_id not in parent_ids:
                parent_ids.append(current_id)
                target["parents"] = parent_ids
                self._mark_related_location_update(card, target_id)
            if not target.get("parent_location"):
                target["parent_location"] = current_id
                self._mark_related_location_update(card, target_id)
            return

    def _sync_removed_location_topology_relation(self, card, field_key, target_id):
        if self.world_model is None:
            return
        current_id = str(self.entity.get("id") or "").strip()
        if not current_id or not target_id:
            return
        target = self.world_model.get_entity(target_id)
        if not self._is_location_entity(target):
            return

        if field_key in self.LOCATION_TOPOLOGY_SYMMETRIC_FIELDS:
            target_ids = self._location_topology_ids(target, field_key)
            if current_id in target_ids:
                self._set_location_topology_ids(target, field_key, [item for item in target_ids if item != current_id])
                self._mark_related_location_update(card, target_id)
            return

        if field_key == "parents":
            constituent_ids = self._relation_entity_ids(target.get("constituents"))
            if current_id in constituent_ids:
                target["constituents"] = [item for item in constituent_ids if item != current_id]
                self._mark_related_location_update(card, target_id)
            if self.entity.get("parent_location") == target_id:
                remaining = [item for item in self._location_topology_ids(self.entity, "parents") if item != target_id]
                self.entity["parent_location"] = remaining[0] if remaining else ""
            return

        if field_key == "constituents":
            parent_ids = self._relation_entity_ids(target.get("parents"))
            if current_id in parent_ids:
                target["parents"] = [item for item in parent_ids if item != current_id]
                self._mark_related_location_update(card, target_id)
            if target.get("parent_location") == current_id:
                target["parent_location"] = ""
                self._mark_related_location_update(card, target_id)
            return

    def add_location_topology_relation(self, card, field_key=None, location_id=None):
        field_key = field_key or self._location_topology_match_field(card)
        if field_key not in self.LOCATION_TOPOLOGY_FIELDS:
            return False
        location_id = str(location_id or "").strip()
        if not location_id:
            matches = card.get("location_topology_matches") or []
            if matches:
                index = max(0, min(int(card.get("location_topology_selected_index", 0) or 0), len(matches) - 1))
                location_id = str(matches[index].get("id") or "").strip()
        if not location_id or location_id == str(self.entity.get("id") or ""):
            return False
        if self.world_model is not None and not self._is_location_entity(self.world_model.get_entity(location_id)):
            return False

        values = self._location_topology_ids(self.entity, field_key)
        if location_id not in values:
            values.append(location_id)
            self._set_location_topology_ids(self.entity, field_key, values)
            self._sync_added_location_topology_relation(card, field_key, location_id)

        card["location_topology_query"] = ""
        card["location_topology_matches"] = []
        card["location_topology_match_rows"] = []
        card["location_topology_selected_index"] = 0
        card["location_topology_input_active"] = False
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = field_key
        return True

    def remove_location_topology_relation(self, card, field_key, location_id):
        field_key = str(field_key or "")
        location_id = str(location_id or "").strip()
        if field_key not in self.LOCATION_TOPOLOGY_FIELDS or not location_id:
            return False
        values = self._location_topology_ids(self.entity, field_key)
        if location_id not in values:
            return False
        self._set_location_topology_ids(self.entity, field_key, [item for item in values if item != location_id])
        self._sync_removed_location_topology_relation(card, field_key, location_id)
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = field_key
        return True

    def _set_location_topology_input_field(self, card, field_key):
        if field_key not in self.LOCATION_TOPOLOGY_FIELDS:
            return False
        virtual_field = self._location_topology_virtual_field(field_key)
        card["location_topology_input_active"] = False
        card["location_topology_active_field"] = field_key
        card["active_edit_field"] = virtual_field
        card["relation_picker_target"] = "locations"
        card["relation_picker_anchor_field"] = virtual_field
        card["relation_picker_open"] = True
        card["relation_picker_query"] = ""
        card["relation_picker_matches"] = []
        card["relation_picker_selected_index"] = 0
        card["relation_picker_hitboxes"] = []
        card["last_edit_action"] = None
        return True

    def _location_entry_label(self, location_id):
        entity = self.world_model.get_entity(location_id) if self.world_model is not None else None
        return self._location_display_label(entity, fallback=location_id)

    def _format_location_period(self, entry):
        start_year = entry.get("start_year")
        end_year = entry.get("end_year")
        if start_year is None and end_year is None:
            return "any period"
        if start_year is None:
            return f"until {end_year}"
        if end_year is None:
            return f"from {start_year}"
        if start_year == end_year:
            return str(start_year)
        return f"{start_year} - {end_year}"

    def _build_location_matches(self, query_text, limit=7):
        if self.world_model is None:
            return []
        query = str(query_text or "").strip().casefold()
        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) or {}
        matches = []
        for entity_id, entity in entities.items():
            if not self._is_location_entity(entity):
                continue
            label = self._location_display_label(entity, fallback=entity_id)
            location_class = str(entity.get("location_class") or entity.get("type") or "location")
            haystack = " ".join(
                [
                    str(entity_id),
                    str(label),
                    str(entity.get("pretty_name", "")),
                    str(entity.get("name", "")),
                    str(location_class),
                ]
            ).casefold()
            if query and not _query_matches_text(query, haystack):
                continue
            label_folded = str(label).casefold()
            id_folded = str(entity_id).casefold()
            if query and (label_folded == query or id_folded == query):
                rank = 0
            elif query and (label_folded.startswith(query) or id_folded.startswith(query)):
                rank = 1
            elif query:
                rank = 2
            else:
                rank = 3
            matches.append(
                {
                    "id": str(entity_id),
                    "label": str(label),
                    "subtitle": f"{location_class.replace('_', ' ').title()} | {entity_id}",
                    "rank": rank,
                }
            )
        matches.sort(key=lambda item: (item["rank"], item["label"].casefold(), item["id"]))
        return matches[:limit]

    def refresh_location_matches(self, card):
        if not card.get("location_input_active"):
            card["location_matches"] = []
            card["location_match_hitboxes"] = []
            card["location_selected_index"] = 0
            return
        matches = self._build_location_matches(card.get("location_query", ""))
        card["location_matches"] = matches
        card["location_match_hitboxes"] = []
        if not matches:
            card["location_selected_index"] = 0
            return
        card["location_selected_index"] = max(0, min(int(card.get("location_selected_index", 0) or 0), len(matches) - 1))

    def add_location_history_entry(self, card, location_id=None):
        location_id = str(location_id or "").strip()
        if not location_id:
            matches = card.get("location_matches") or []
            if matches:
                index = max(0, min(int(card.get("location_selected_index", 0) or 0), len(matches) - 1))
                location_id = str(matches[index].get("id") or "").strip()
        if not location_id:
            return False

        entry = {"location_id": location_id}
        start_year = self._coerce_location_year(card.get("location_start_buffer"))
        end_year = self._coerce_location_year(card.get("location_end_buffer"))
        if start_year is not None:
            entry["start_year"] = start_year
        if end_year is not None:
            entry["end_year"] = end_year
        if (
            entry.get("start_year") is not None
            and entry.get("end_year") is not None
            and entry["end_year"] < entry["start_year"]
        ):
            entry["start_year"], entry["end_year"] = entry["end_year"], entry["start_year"]

        entries = self._location_history_entries()
        key = (entry.get("location_id"), entry.get("start_year"), entry.get("end_year"))
        if not any((row.get("location_id"), row.get("start_year"), row.get("end_year")) == key for row in entries):
            entries.append(entry)
        self.entity["location_history"] = entries
        self._sync_location_relation_fields()
        card["location_query"] = ""
        card["location_start_buffer"] = ""
        card["location_end_buffer"] = ""
        card["location_matches"] = []
        card["location_match_hitboxes"] = []
        card["location_selected_index"] = 0
        card["location_input_active"] = False
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = "location_history"
        return True

    def remove_location_history_entry(self, card, index):
        entries = self._location_history_entries()
        try:
            index = int(index)
        except (TypeError, ValueError):
            return False
        if index < 0 or index >= len(entries):
            return False
        entries.pop(index)
        self.entity["location_history"] = entries
        self._sync_location_relation_fields()
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = "location_history"
        return True

    def toggle_location_mode(self, card):
        mode = self._location_mode_value()
        self.entity["location_mode"] = "multiple" if mode == "exclusive" else "exclusive"
        card["last_edit_action"] = "commit"
        card["last_committed_field"] = "location_mode"
        return True

    def _set_location_input_field(self, card, field_name):
        card["location_input_active"] = True
        card["location_active_field"] = field_name
        card.setdefault("location_query", "")
        card.setdefault("location_start_buffer", "")
        card.setdefault("location_end_buffer", "")
        self.refresh_location_matches(card)
        return True

    def _handle_location_keydown(self, card, event):
        if self._is_location_mode() and self._is_location_card():
            return self._handle_location_topology_keydown(card, event)

        if not self._is_location_mode() or not card.get("location_input_active"):
            return False

        active_field = card.get("location_active_field") or "query"
        if event.key == pygame.K_ESCAPE:
            card["location_input_active"] = False
            card["location_active_field"] = None
            card["location_matches"] = []
            card["location_match_hitboxes"] = []
            card["last_edit_action"] = "cancel"
            return True

        if event.key == pygame.K_TAB:
            order = ["query", "start", "end"]
            direction = -1 if (event.mod & pygame.KMOD_SHIFT) else 1
            current_index = order.index(active_field) if active_field in order else 0
            card["location_active_field"] = order[(current_index + direction) % len(order)]
            return True

        matches = card.get("location_matches") or []
        if active_field == "query" and event.key == pygame.K_UP and matches:
            card["location_selected_index"] = max(0, int(card.get("location_selected_index", 0) or 0) - 1)
            return True
        if active_field == "query" and event.key == pygame.K_DOWN and matches:
            card["location_selected_index"] = min(len(matches) - 1, int(card.get("location_selected_index", 0) or 0) + 1)
            return True

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if active_field == "query" and matches and not (event.mod & pygame.KMOD_SHIFT):
                index = max(0, min(int(card.get("location_selected_index", 0) or 0), len(matches) - 1))
                card["location_query"] = matches[index].get("label", matches[index].get("id", ""))
                card["location_selected_id"] = matches[index].get("id")
                card["location_active_field"] = "start"
                return True
            selected_id = card.get("location_selected_id")
            if not selected_id and matches:
                index = max(0, min(int(card.get("location_selected_index", 0) or 0), len(matches) - 1))
                selected_id = matches[index].get("id")
            return self.add_location_history_entry(card, selected_id)

        if event.key == pygame.K_BACKSPACE:
            if active_field == "query":
                card["location_query"] = str(card.get("location_query", ""))[:-1]
                card.pop("location_selected_id", None)
                self.refresh_location_matches(card)
            elif active_field == "start":
                card["location_start_buffer"] = str(card.get("location_start_buffer", ""))[:-1]
            elif active_field == "end":
                card["location_end_buffer"] = str(card.get("location_end_buffer", ""))[:-1]
            card["last_edit_action"] = "draft"
            return True

        if event.key == pygame.K_DELETE:
            if active_field == "query":
                card["location_query"] = ""
                card.pop("location_selected_id", None)
                self.refresh_location_matches(card)
            elif active_field == "start":
                card["location_start_buffer"] = ""
            elif active_field == "end":
                card["location_end_buffer"] = ""
            card["last_edit_action"] = "draft"
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            if active_field == "query":
                card["location_query"] = str(card.get("location_query", "")) + text
                card.pop("location_selected_id", None)
                self.refresh_location_matches(card)
            elif active_field == "start":
                if text.isdigit() or text in {"-", "+"}:
                    card["location_start_buffer"] = str(card.get("location_start_buffer", "")) + text
            elif active_field == "end":
                if text.isdigit() or text in {"-", "+"}:
                    card["location_end_buffer"] = str(card.get("location_end_buffer", "")) + text
            card["last_edit_action"] = "draft"
            return True

        return False

    def _handle_location_topology_keydown(self, card, event):
        if not card.get("location_topology_input_active"):
            return False

        if event.key == pygame.K_ESCAPE:
            card["location_topology_input_active"] = False
            card["location_topology_active_field"] = None
            card["location_topology_matches"] = []
            card["location_topology_match_rows"] = []
            card["last_edit_action"] = "cancel"
            return True

        matches = card.get("location_topology_matches") or []
        if event.key == pygame.K_UP and matches:
            card["location_topology_selected_index"] = max(
                0,
                int(card.get("location_topology_selected_index", 0) or 0) - 1,
            )
            return True
        if event.key == pygame.K_DOWN and matches:
            card["location_topology_selected_index"] = min(
                len(matches) - 1,
                int(card.get("location_topology_selected_index", 0) or 0) + 1,
            )
            return True

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            selected_id = card.get("location_topology_selected_id")
            if not selected_id and matches:
                index = max(0, min(int(card.get("location_topology_selected_index", 0) or 0), len(matches) - 1))
                selected_id = matches[index].get("id")
            return self.add_location_topology_relation(
                card,
                self._location_topology_match_field(card),
                selected_id,
            )

        if event.key == pygame.K_BACKSPACE:
            card["location_topology_query"] = str(card.get("location_topology_query", ""))[:-1]
            card.pop("location_topology_selected_id", None)
            self.refresh_location_topology_matches(card)
            card["last_edit_action"] = None
            return True

        if event.key == pygame.K_DELETE:
            card["location_topology_query"] = ""
            card.pop("location_topology_selected_id", None)
            self.refresh_location_topology_matches(card)
            card["last_edit_action"] = None
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            card["location_topology_query"] = str(card.get("location_topology_query", "")) + text
            card.pop("location_topology_selected_id", None)
            self.refresh_location_topology_matches(card)
            card["last_edit_action"] = None
            return True

        return False

    def handle_location_click(self, card, mouse_pos):
        if not self._is_location_mode():
            return False

        if self._is_location_card():
            return self.handle_location_topology_click(card, mouse_pos)

        if card.get("is_edit_mode", False):
            mode_rect = card.get("location_mode_rect")
            if mode_rect is not None and mode_rect.collidepoint(mouse_pos):
                return self.toggle_location_mode(card)

            for row in card.get("location_rows", []):
                remove_rect = row.get("remove_rect")
                if remove_rect is not None and remove_rect.collidepoint(mouse_pos):
                    return self.remove_location_history_entry(card, row.get("index"))

            for row in card.get("location_match_rows", []):
                row_rect = row.get("rect")
                if row_rect is not None and row_rect.collidepoint(mouse_pos):
                    index = int(row.get("index", 0) or 0)
                    matches = card.get("location_matches") or []
                    if 0 <= index < len(matches):
                        card["location_selected_index"] = index
                        card["location_selected_id"] = matches[index].get("id")
                        card["location_query"] = matches[index].get("label", matches[index].get("id", ""))
                        card["location_active_field"] = "start"
                        card["location_input_active"] = True
                        return True

            if card.get("location_query_rect") is not None and card["location_query_rect"].collidepoint(mouse_pos):
                return self._set_location_input_field(card, "query")
            if card.get("location_start_rect") is not None and card["location_start_rect"].collidepoint(mouse_pos):
                return self._set_location_input_field(card, "start")
            if card.get("location_end_rect") is not None and card["location_end_rect"].collidepoint(mouse_pos):
                return self._set_location_input_field(card, "end")
            if card.get("location_add_rect") is not None and card["location_add_rect"].collidepoint(mouse_pos):
                selected_id = card.get("location_selected_id")
                matches = card.get("location_matches") or []
                if not selected_id and matches:
                    index = max(0, min(int(card.get("location_selected_index", 0) or 0), len(matches) - 1))
                    selected_id = matches[index].get("id")
                return self.add_location_history_entry(card, selected_id)

        return False

    def handle_location_topology_click(self, card, mouse_pos):
        if not card.get("is_edit_mode", False):
            return False

        place_rect = card.get("location_topology_place_rect")
        if place_rect is not None and place_rect.collidepoint(mouse_pos):
            card["pending_location_action"] = {
                "id": "knowledge_place_location_on_parent",
                "entity_id": card.get("entity_id") or self.entity.get("id"),
            }
            card["last_edit_action"] = None
            return True

        for row in card.get("location_topology_rows", []):
            remove_rect = row.get("remove_rect")
            if remove_rect is not None and remove_rect.collidepoint(mouse_pos):
                if row.get("field_key") not in self.LOCATION_TOPOLOGY_EDITABLE_FIELDS:
                    return False
                return self.remove_location_topology_relation(
                    card,
                    row.get("field_key"),
                    row.get("location_id"),
                )

        for row in card.get("location_topology_match_rows", []):
            row_rect = row.get("rect")
            if row_rect is not None and row_rect.collidepoint(mouse_pos):
                index = int(row.get("index", 0) or 0)
                matches = card.get("location_topology_matches") or []
                if 0 <= index < len(matches):
                    card["location_topology_selected_index"] = index
                    card["location_topology_selected_id"] = matches[index].get("id")
                    card["location_topology_query"] = matches[index].get("label", matches[index].get("id", ""))
                    card["location_topology_input_active"] = True
                    card["location_topology_active_field"] = row.get("field_key") or self._location_topology_match_field(card)
                    card["last_edit_action"] = None
                    return True

        for field_key, input_rect in (card.get("location_topology_input_rects") or {}).items():
            if field_key not in self.LOCATION_TOPOLOGY_EDITABLE_FIELDS:
                continue
            if input_rect is not None and input_rect.collidepoint(mouse_pos):
                return self._set_location_topology_input_field(card, field_key)

        for field_key, add_rect in (card.get("location_topology_add_rects") or {}).items():
            if field_key not in self.LOCATION_TOPOLOGY_EDITABLE_FIELDS:
                continue
            if add_rect is not None and add_rect.collidepoint(mouse_pos):
                selected_id = card.get("location_topology_selected_id")
                matches = card.get("location_topology_matches") or []
                if not selected_id and matches:
                    index = max(0, min(int(card.get("location_topology_selected_index", 0) or 0), len(matches) - 1))
                    selected_id = matches[index].get("id")
                return self.add_location_topology_relation(card, field_key, selected_id)

        return False

    def _layout_location_topology_content(self, card, content_left, current_y, text_width):
        row_gap = 6
        card["location_topology_rows"] = []
        card["location_topology_section_rects"] = {}
        card["location_topology_input_rects"] = {}
        card["location_topology_add_rects"] = {}
        card["location_topology_match_rows"] = []
        card["location_topology_place_rect"] = None

        if card.get("is_edit_mode", False):
            place_rect = pygame.Rect(content_left, current_y, min(172, text_width), 24)
            card["location_topology_place_rect"] = place_rect
            current_y = place_rect.bottom + row_gap + 4

        for field_key in self.LOCATION_TOPOLOGY_FIELDS:
            section_rect = pygame.Rect(content_left, current_y, text_width, self.SECTION_HEADER_H)
            card["location_topology_section_rects"][field_key] = section_rect
            current_y = section_rect.bottom + self.SECTION_GAP + 4

            ids = self._location_topology_ids(self.entity, field_key)
            if not ids:
                empty_rect = pygame.Rect(content_left, current_y, text_width, 30)
                card["location_topology_rows"].append(
                    {
                        "kind": "empty",
                        "field_key": field_key,
                        "rect": empty_rect,
                    }
                )
                current_y = empty_rect.bottom + row_gap
            else:
                for location_id in ids:
                    row_rect = pygame.Rect(content_left, current_y, text_width, 34)
                    remove_rect = None
                    if card.get("is_edit_mode", False) and field_key in self.LOCATION_TOPOLOGY_EDITABLE_FIELDS:
                        remove_rect = pygame.Rect(row_rect.right - 24, row_rect.y + 8, 18, 18)
                    card["location_topology_rows"].append(
                        {
                            "kind": "entry",
                            "field_key": field_key,
                            "location_id": location_id,
                            "rect": row_rect,
                            "remove_rect": remove_rect,
                        }
                    )
                    current_y = row_rect.bottom + row_gap

            if card.get("is_edit_mode", False) and field_key in self.LOCATION_TOPOLOGY_EDITABLE_FIELDS:
                input_h = 24
                add_w = 44
                gap = 6
                input_rect = pygame.Rect(content_left, current_y, max(100, text_width - add_w - gap), input_h)
                add_rect = pygame.Rect(input_rect.right + gap, current_y, add_w, input_h)
                card["location_topology_input_rects"][field_key] = input_rect
                card["location_topology_add_rects"][field_key] = add_rect
                current_y = input_rect.bottom + 4

                if (
                    card.get("location_topology_input_active")
                    and self._location_topology_match_field(card) == field_key
                ):
                    for index, match in enumerate((card.get("location_topology_matches") or [])[:5]):
                        row_rect = pygame.Rect(input_rect.x, current_y, min(text_width, input_rect.width + 160), 22)
                        card["location_topology_match_rows"].append(
                            {
                                "index": index,
                                "field_key": field_key,
                                "match": match,
                                "rect": row_rect,
                            }
                        )
                        current_y = row_rect.bottom + 2
                current_y += row_gap

            current_y += 6

        return current_y

    def _layout_location_content(self, card, content_left, current_y, text_width):
        if self._is_location_card():
            return self._layout_location_topology_content(card, content_left, current_y, text_width)

        font = card["layout_font"]
        line_h = self._table_line_height(font)
        row_gap = 6
        card["location_rows"] = []
        card["location_mode_rect"] = None
        card["location_query_rect"] = None
        card["location_start_rect"] = None
        card["location_end_rect"] = None
        card["location_add_rect"] = None
        card["location_match_rows"] = []

        header_rect = pygame.Rect(content_left, current_y, text_width, self.SECTION_HEADER_H)
        card["location_section_rect"] = header_rect
        current_y = header_rect.bottom + self.SECTION_GAP + 4

        mode_rect = pygame.Rect(content_left, current_y, min(260, text_width), 24)
        card["location_mode_rect"] = mode_rect
        current_y = mode_rect.bottom + row_gap

        entries = self._location_history_entries()
        if not entries:
            empty_rect = pygame.Rect(content_left, current_y, text_width, 34)
            card["location_rows"].append({"kind": "empty", "rect": empty_rect})
            current_y = empty_rect.bottom + row_gap
        else:
            for index, entry in enumerate(entries):
                row_rect = pygame.Rect(content_left, current_y, text_width, 38)
                remove_rect = None
                if card.get("is_edit_mode", False):
                    remove_rect = pygame.Rect(row_rect.right - 24, row_rect.y + 8, 18, 18)
                card["location_rows"].append(
                    {
                        "kind": "entry",
                        "index": index,
                        "entry": entry,
                        "rect": row_rect,
                        "remove_rect": remove_rect,
                    }
                )
                current_y = row_rect.bottom + row_gap

        if card.get("is_edit_mode", False):
            current_y += 2
            query_w = max(120, int(text_width * 0.46))
            year_w = max(58, min(76, int(text_width * 0.17)))
            add_w = 44
            gap = 6
            total_w = query_w + year_w * 2 + add_w + gap * 3
            if total_w > text_width:
                query_w = max(90, text_width - year_w * 2 - add_w - gap * 3)
            input_h = 24
            query_rect = pygame.Rect(content_left, current_y, query_w, input_h)
            start_rect = pygame.Rect(query_rect.right + gap, current_y, year_w, input_h)
            end_rect = pygame.Rect(start_rect.right + gap, current_y, year_w, input_h)
            add_rect = pygame.Rect(end_rect.right + gap, current_y, add_w, input_h)
            card["location_query_rect"] = query_rect
            card["location_start_rect"] = start_rect
            card["location_end_rect"] = end_rect
            card["location_add_rect"] = add_rect
            current_y = query_rect.bottom + 4

            matches = card.get("location_matches") or []
            for index, match in enumerate(matches[:5]):
                row_rect = pygame.Rect(query_rect.x, current_y, min(text_width, query_rect.width + 180), 22)
                card["location_match_rows"].append({"index": index, "match": match, "rect": row_rect})
                current_y = row_rect.bottom + 2

            current_y += row_gap

        return current_y

    def _draw_location_content(self, screen, font, card):
        if self._is_location_card():
            self._draw_location_topology_content(screen, font, card)
            return

        content_clip = card.get("content_viewport_rect")
        section_rect = card.get("location_section_rect")
        if section_rect is not None:
            pygame.draw.rect(screen, (34, 38, 48), section_rect)
            pygame.draw.rect(screen, (86, 96, 116), section_rect, 1)
            title = font.render("Location History", True, (232, 236, 244))
            screen.blit(title, (section_rect.x + 8, section_rect.y + 3))

        mode_rect = card.get("location_mode_rect")
        if mode_rect is not None:
            mode = self._location_mode_value()
            mode_label = "Exclusive location" if mode == "exclusive" else "Multiple locations"
            pygame.draw.rect(screen, (38, 44, 58), mode_rect)
            pygame.draw.rect(screen, (116, 132, 160), mode_rect, 1)
            screen.blit(font.render(mode_label, True, (230, 234, 242)), (mode_rect.x + 8, mode_rect.y + 4))

        for row in card.get("location_rows", []):
            row_rect = row.get("rect")
            if row_rect is None or (content_clip is not None and not row_rect.colliderect(content_clip)):
                continue
            pygame.draw.rect(screen, (30, 34, 44), row_rect)
            pygame.draw.rect(screen, (82, 92, 112), row_rect, 1)
            if row.get("kind") == "empty":
                screen.blit(font.render("No related locations yet", True, (150, 160, 178)), (row_rect.x + 8, row_rect.y + 9))
                continue

            entry = row.get("entry") or {}
            location_id = str(entry.get("location_id") or "")
            label = self._ellipsize_text(self._location_entry_label(location_id), font, row_rect.width - 150)
            period = self._format_location_period(entry)
            screen.blit(font.render(label, True, (238, 240, 246)), (row_rect.x + 8, row_rect.y + 5))
            screen.blit(font.render(period, True, (176, 188, 208)), (row_rect.x + 8, row_rect.y + 20))
            remove_rect = row.get("remove_rect")
            if remove_rect is not None:
                pygame.draw.rect(screen, (70, 40, 46), remove_rect)
                pygame.draw.rect(screen, (178, 116, 124), remove_rect, 1)
                remove_text = font.render("x", True, (250, 220, 224))
                screen.blit(remove_text, remove_text.get_rect(center=remove_rect.center))

        if not card.get("is_edit_mode", False):
            return

        active_field = card.get("location_active_field")

        def draw_input(rect, value, placeholder, field_name):
            if rect is None:
                return
            active = bool(card.get("location_input_active")) and active_field == field_name
            pygame.draw.rect(screen, (40, 46, 60) if active else (30, 34, 44), rect)
            pygame.draw.rect(screen, (190, 208, 236) if active else (94, 104, 124), rect, 1)
            text = str(value or "")
            display = text if text else placeholder
            color = (238, 240, 246) if text else (132, 142, 160)
            display = self._ellipsize_text(display, font, rect.width - 12)
            screen.blit(font.render(display, True, color), (rect.x + 6, rect.y + 4))

        draw_input(card.get("location_query_rect"), card.get("location_query", ""), "Search location", "query")
        draw_input(card.get("location_start_rect"), card.get("location_start_buffer", ""), "start", "start")
        draw_input(card.get("location_end_rect"), card.get("location_end_buffer", ""), "end", "end")

        add_rect = card.get("location_add_rect")
        if add_rect is not None:
            pygame.draw.rect(screen, (54, 70, 98), add_rect)
            pygame.draw.rect(screen, (150, 172, 210), add_rect, 1)
            add_text = font.render("Add", True, (244, 246, 250))
            screen.blit(add_text, add_text.get_rect(center=add_rect.center))

        selected_index = int(card.get("location_selected_index", 0) or 0)
        for row in card.get("location_match_rows", []):
            row_rect = row.get("rect")
            if row_rect is None:
                continue
            index = int(row.get("index", 0))
            match = row.get("match") or {}
            selected = index == selected_index
            pygame.draw.rect(screen, (52, 64, 86) if selected else (31, 36, 48), row_rect)
            pygame.draw.rect(screen, (138, 164, 206) if selected else (72, 82, 104), row_rect, 1)
            label = self._ellipsize_text(match.get("label", ""), font, row_rect.width - 120)
            subtitle = self._ellipsize_text(match.get("subtitle", ""), font, 110)
            screen.blit(font.render(label, True, (240, 244, 250) if selected else (188, 198, 216)), (row_rect.x + 6, row_rect.y + 3))
            if subtitle:
                subtitle_surface = font.render(subtitle, True, (176, 188, 208))
                screen.blit(subtitle_surface, (row_rect.right - subtitle_surface.get_width() - 6, row_rect.y + 3))

    def _draw_location_topology_content(self, screen, font, card):
        content_clip = card.get("content_viewport_rect")

        place_rect = card.get("location_topology_place_rect")
        if place_rect is not None:
            pygame.draw.rect(screen, (46, 60, 84), place_rect)
            pygame.draw.rect(screen, (148, 170, 210), place_rect, 1)
            has_parent = bool(self._location_topology_ids(self.entity, "parents"))
            place_label = "Place On Parent Map" if has_parent else "Choose Parent"
            place_text = font.render(place_label, True, (242, 246, 252))
            screen.blit(place_text, place_text.get_rect(center=place_rect.center))

        for field_key in self.LOCATION_TOPOLOGY_FIELDS:
            section_rect = (card.get("location_topology_section_rects") or {}).get(field_key)
            if section_rect is not None:
                pygame.draw.rect(screen, (34, 38, 48), section_rect)
                pygame.draw.rect(screen, (86, 96, 116), section_rect, 1)
                title = self.LOCATION_TOPOLOGY_LABELS.get(field_key, field_key.title())
                screen.blit(font.render(title, True, (232, 236, 244)), (section_rect.x + 8, section_rect.y + 3))
                help_text = self.LOCATION_TOPOLOGY_HELP.get(field_key, "")
                if help_text:
                    help_surface = font.render(
                        self._ellipsize_text(help_text, font, max(20, section_rect.width - 140)),
                        True,
                        (158, 170, 190),
                    )
                    screen.blit(help_surface, (section_rect.right - help_surface.get_width() - 8, section_rect.y + 3))

        for row in card.get("location_topology_rows", []):
            row_rect = row.get("rect")
            if row_rect is None or (content_clip is not None and not row_rect.colliderect(content_clip)):
                continue
            pygame.draw.rect(screen, (30, 34, 44), row_rect)
            pygame.draw.rect(screen, (82, 92, 112), row_rect, 1)
            if row.get("kind") == "empty":
                label = f"No {self.LOCATION_TOPOLOGY_LABELS.get(row.get('field_key'), 'locations').lower()} yet"
                screen.blit(font.render(label, True, (150, 160, 178)), (row_rect.x + 8, row_rect.y + 7))
                continue

            location_id = str(row.get("location_id") or "")
            label = self._ellipsize_text(self._location_entry_label(location_id), font, row_rect.width - 120)
            subtitle = self._ellipsize_text(location_id, font, 100)
            screen.blit(font.render(label, True, (238, 240, 246)), (row_rect.x + 8, row_rect.y + 8))
            subtitle_surface = font.render(subtitle, True, (176, 188, 208))
            screen.blit(subtitle_surface, (row_rect.right - subtitle_surface.get_width() - 34, row_rect.y + 8))
            remove_rect = row.get("remove_rect")
            if remove_rect is not None:
                pygame.draw.rect(screen, (70, 40, 46), remove_rect)
                pygame.draw.rect(screen, (178, 116, 124), remove_rect, 1)
                remove_text = font.render("x", True, (250, 220, 224))
                screen.blit(remove_text, remove_text.get_rect(center=remove_rect.center))

        if not card.get("is_edit_mode", False):
            return

        active_field = self._location_topology_match_field(card)
        for field_key, input_rect in (card.get("location_topology_input_rects") or {}).items():
            active = bool(card.get("location_topology_input_active")) and active_field == field_key
            pygame.draw.rect(screen, (40, 46, 60) if active else (30, 34, 44), input_rect)
            pygame.draw.rect(screen, (190, 208, 236) if active else (94, 104, 124), input_rect, 1)
            query = str(card.get("location_topology_query", "")) if active else ""
            display = query if query else "Search location"
            color = (238, 240, 246) if query else (132, 142, 160)
            screen.blit(
                font.render(self._ellipsize_text(display, font, input_rect.width - 12), True, color),
                (input_rect.x + 6, input_rect.y + 4),
            )

        for add_rect in (card.get("location_topology_add_rects") or {}).values():
            pygame.draw.rect(screen, (54, 70, 98), add_rect)
            pygame.draw.rect(screen, (150, 172, 210), add_rect, 1)
            add_text = font.render("Add", True, (244, 246, 250))
            screen.blit(add_text, add_text.get_rect(center=add_rect.center))

        active_virtual_field = str(card.get("active_edit_field") or "")
        active_topology_field = self._location_topology_field_from_virtual(active_virtual_field)
        if active_topology_field:
            anchor_rect = (card.get("location_topology_input_rects") or {}).get(active_topology_field)
            if anchor_rect is not None and card.get("relation_picker_open", False):
                self._draw_relation_picker(screen, font, card, anchor_rect)

        selected_index = int(card.get("location_topology_selected_index", 0) or 0)
        for row in card.get("location_topology_match_rows", []):
            row_rect = row.get("rect")
            if row_rect is None:
                continue
            index = int(row.get("index", 0))
            match = row.get("match") or {}
            selected = index == selected_index
            pygame.draw.rect(screen, (52, 64, 86) if selected else (31, 36, 48), row_rect)
            pygame.draw.rect(screen, (138, 164, 206) if selected else (72, 82, 104), row_rect, 1)
            label = self._ellipsize_text(match.get("label", ""), font, row_rect.width - 120)
            subtitle = self._ellipsize_text(match.get("subtitle", ""), font, 110)
            screen.blit(font.render(label, True, (240, 244, 250) if selected else (188, 198, 216)), (row_rect.x + 6, row_rect.y + 3))
            if subtitle:
                subtitle_surface = font.render(subtitle, True, (176, 188, 208))
                screen.blit(subtitle_surface, (row_rect.right - subtitle_surface.get_width() - 6, row_rect.y + 3))
