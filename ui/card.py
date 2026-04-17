import os

import pygame

from engine.scaler import ScaleHelper
from ui.card_wiki import CardWikiRenderer
from world.schema_loader import SchemaLoader


class EntityCard:
    """
    Reusable renderer + interaction helper for one repository entity card.
    """

    HEADER_H = 50
    TAB_H = 24
    SECTION_HEADER_H = 22
    IMAGE_TOP = 86
    IMAGE_H = 110
    MEDIA_IMAGE_H = 176
    LAUNCH_H = 24
    RESIZE_HANDLE = 14
    RESIZE_BORDER = 6
    TEXT_LINE_H = 16
    IMAGE_TEXT_LINE_H = 18
    SECTION_GAP = 4
    TABLE_ROW_PAD_Y = 3
    TABLE_COLUMN_GAP = 14
    TABLE_MIN_KEY_W = 96
    TABLE_MAX_KEY_W = 168

    SECTION_ORDER = [
        "Identity",
        "Classification",
        "Dimensions / Scale",
        "Relations",
        "State / Layout",
        "Metadata",
    ]

    TAB_ORDER = ["general", "overview", "relations", "state", "media"]
    TAB_LABELS = {
        "general": "General",
        "overview": "Overview",
        "relations": "Relations",
        "state": "State",
        "media": "Media",
    }
    TAB_SECTIONS = {
        "general": [],
        "overview": ["Identity", "Classification", "Dimensions / Scale", "Metadata"],
        "relations": ["Relations"],
        "state": ["State / Layout"],
        "media": [],
    }
    TEMPORAL_FIELDS = {"year", "start_year", "end_year"}
    SCHEMA_LOADER = SchemaLoader()

    def __init__(self, entity, dataset_name=None, world_model=None):
        self.entity = entity or {}
        self.dataset_name = dataset_name or self.entity.get("_dataset", self.entity.get("type", "entity"))
        self.world_model = world_model
        self.active_tab = "general"
        self.collapsed_sections = {
            "Identity": False,
            "Classification": False,
            "Dimensions / Scale": False,
            "Relations": True,
            "State / Layout": True,
            "Metadata": False,
        }

    def toggle_section(self, section_name):
        if section_name in self.collapsed_sections:
            self.collapsed_sections[section_name] = not self.collapsed_sections[section_name]

    def set_active_tab(self, tab_name):
        if tab_name in self.TAB_ORDER:
            self.active_tab = tab_name

    def _visible_sections(self):
        return self.TAB_SECTIONS.get(self.active_tab, self.TAB_SECTIONS["general"])

    def _is_media_mode(self):
        return self.active_tab == "media"

    def _is_general_mode(self):
        return self.active_tab == "general"

    def _image_block_height(self):
        if self._is_media_mode():
            return self.MEDIA_IMAGE_H
        return self.IMAGE_H

    def _role_field_name(self, role_name):
        role_name = (role_name or "card").lower()
        if role_name == "card":
            return "card_image"
        return f"card_image_{role_name}"

    def _resolve_role_image_reference(self, role_name):
        field_name = self._role_field_name(role_name)
        value = self.entity.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _get_general_wiki_text(self, card=None):
        if card is not None and card.get("is_edit_mode", False) and card.get("active_edit_field") == "wiki_entry":
            return card.get("edit_buffer", "")

        wiki_text = self.entity.get("wiki_entry")
        if isinstance(wiki_text, str) and wiki_text.strip():
            return wiki_text

        fallback_parts = []
        description = self.entity.get("description")
        notes = self.entity.get("notes")
        image_ref = self._resolve_image_reference()

        if description:
            fallback_parts.append(str(description).strip())
        if image_ref:
            fallback_parts.append(f"![Primary image]({image_ref})")
        if notes:
            fallback_parts.append(str(notes).strip())

        return "\n\n".join(part for part in fallback_parts if part)

    def _resolve_wiki_link_label(self, entity_ref):
        if self.world_model is None:
            return entity_ref

        entity = self.world_model.get_entity(entity_ref)
        if entity is None:
            return entity_ref

        return entity.get("pretty_name") or entity.get("name") or entity_ref

    def _schema_name_candidates(self):
        candidates = []
        entity_type = self.entity.get("type")
        dataset_name = self.dataset_name

        for name in (entity_type, dataset_name):
            if not name:
                continue
            normalized = str(name).strip().lower()
            if normalized and normalized not in candidates:
                candidates.append(normalized)
            if normalized.endswith("s"):
                singular = normalized[:-1]
                if singular and singular not in candidates:
                    candidates.append(singular)
            else:
                plural = f"{normalized}s"
                if plural not in candidates:
                    candidates.append(plural)

        return candidates

    def _resolve_schema(self):
        for schema_name in self._schema_name_candidates():
            schema = self.SCHEMA_LOADER.get_schema(schema_name)
            if schema:
                return schema
        return None

    def _collect_schema_fields(self, schema, seen=None):
        if not schema:
            return {}

        if seen is None:
            seen = set()

        schema_name = schema.get("schema")
        if schema_name in seen:
            return {}
        if schema_name:
            seen.add(schema_name)

        combined = {}
        extends_name = schema.get("extends")
        if extends_name:
            parent_schema = self.SCHEMA_LOADER.get_schema(extends_name)
            combined.update(self._collect_schema_fields(parent_schema, seen=seen))

        combined.update(schema.get("fields", {}))
        return combined

    def _get_schema_field_specs(self):
        schema = self._resolve_schema()
        return self._collect_schema_fields(schema)

    def _is_scalar_schema_type(self, field_type):
        return field_type in {None, "string", "number", "text"}

    def _is_field_editable(self, field_key, value, schema_field_specs):
        spec = schema_field_specs.get(field_key, {})
        field_type = spec.get("type")

        if value is None:
            return self._is_scalar_schema_type(field_type)

        if field_type is not None and not self._is_scalar_schema_type(field_type):
            return False

        return isinstance(value, (str, int, float)) and not isinstance(value, bool)

    def _sectioned_fields(self):
        entity = self.entity
        schema_field_specs = self._get_schema_field_specs()
        schema_field_order = list(schema_field_specs.keys())

        identity = [
            ("id", entity.get("id")),
            ("pretty_name", entity.get("pretty_name")),
            ("name", entity.get("name")),
            ("type", entity.get("type")),
            ("dataset", entity.get("_dataset")),
        ]

        classification_keys = [
            "vehicle_class",
            "component_class",
            "location_class",
            "system_role",
            "system_class",
            "body_class",
        ]
        classification = []
        for key in classification_keys:
            if key in entity or key in schema_field_specs:
                classification.append((key, entity.get(key)))

        dims = [
            ("dimension_x_m", entity.get("dimension_x_m")),
            ("dimension_y_m", entity.get("dimension_y_m")),
            ("dimension_z_m", entity.get("dimension_z_m")),
            ("mass_kg", entity.get("mass_kg")),
            ("power_kw", entity.get("power_kw")),
        ]
        dims = [(key, value) for key, value in dims if key in entity or key in schema_field_specs]

        relation_values = []
        state_values = []
        metadata_values = []

        media_keys = {
            "card_image",
            "design_image",
            "image_path",
            "image",
        }

        for role_info in ScaleHelper.suggest_media_canvases(entity):
            role = role_info.get("role")
            if role:
                media_keys.add(self._role_field_name(role))

        handled_keys = {
            "id", "pretty_name", "name", "type", "_dataset",
            "vehicle_class", "component_class", "location_class",
            "system_role", "system_class", "body_class",
            "dimension_x_m", "dimension_y_m", "dimension_z_m",
            "mass_kg", "power_kw",
        }

        ordered_keys = []
        for key in schema_field_order:
            if key not in handled_keys:
                ordered_keys.append(key)

        for key in entity.keys():
            if key in handled_keys or key in ordered_keys:
                continue
            ordered_keys.append(key)

        for key in ordered_keys:
            value = entity.get(key)

            if key in {
                "id", "pretty_name", "name", "type", "_dataset",
                "vehicle_class", "component_class", "location_class",
                "system_role", "system_class", "body_class",
                "dimension_x_m", "dimension_y_m", "dimension_z_m",
                "mass_kg", "power_kw",
            }:
                continue

            if key in {"description", "notes", "tags", "start_year", "end_year", "entry_status"}:
                metadata_values.append((key, value))
                continue

            if key in media_keys:
                metadata_values.append((key, value))
                continue

            if isinstance(value, list):
                if value and all(not isinstance(item, dict) for item in value):
                    relation_values.append((key, value))
                else:
                    state_values.append((key, value))
                continue

            if isinstance(value, dict):
                state_values.append((key, value))
                continue

            spec = schema_field_specs.get(key, {})
            field_type = spec.get("type")

            if field_type in {"entity", "entity_list"}:
                relation_values.append((key, value))
                continue

            if field_type in {"dict", "object", "object_list"}:
                state_values.append((key, value))
                continue

            metadata_values.append((key, value))

        return {
            "Identity": identity,
            "Classification": classification,
            "Dimensions / Scale": dims,
            "Relations": relation_values,
            "State / Layout": state_values,
            "Metadata": metadata_values,
        }

    def _format_value(self, value):
        if value is None:
            return ""
        if isinstance(value, dict):
            return "\n".join(f"{k}: {v}" for k, v in value.items())
        if isinstance(value, list):
            return "\n".join(f"- {item}" for item in value) if value else "[]"
        return str(value)

    def _is_scalar_editable_value(self, value):
        return value is None or isinstance(value, (str, int, float))

    def _serialize_edit_value(self, value):
        if value is None:
            return ""
        return str(value)

    def _coerce_edit_buffer(self, original_value, buffer_text):
        text = str(buffer_text or "")

        if isinstance(original_value, int) and not isinstance(original_value, bool):
            try:
                return int(text)
            except ValueError:
                return original_value

        if isinstance(original_value, float):
            try:
                return float(text)
            except ValueError:
                return original_value

        lowered = text.strip().lower()
        if original_value is None:
            if lowered in {"", "none", "null"}:
                return None
            try:
                if "." in text:
                    return float(text)
                return int(text)
            except ValueError:
                return text

        return text

    def toggle_edit_mode(self, card):
        currently_enabled = bool(card.get("is_edit_mode", False))
        card["is_edit_mode"] = not currently_enabled

        if not card["is_edit_mode"]:
            card["active_edit_field"] = None
            card["edit_buffer"] = ""
            card["edit_original_value"] = None

    def _editable_field_order(self, card):
        return [field_key for field_key, _ in card.get("editable_field_hitboxes", [])]

    def _cycle_edit_field(self, card, direction=1):
        field_order = self._editable_field_order(card)
        if not field_order:
            return False

        active_field = card.get("active_edit_field")
        if active_field not in field_order:
            target_index = 0 if direction >= 0 else len(field_order) - 1
        else:
            current_index = field_order.index(active_field)
            target_index = (current_index + direction) % len(field_order)

        return self.begin_edit_field(card, field_order[target_index])

    def begin_edit_field(self, card, field_key):
        if not card.get("is_edit_mode", False):
            return False

        value = self.entity.get(field_key)
        schema_field_specs = self._get_schema_field_specs()
        if not self._is_field_editable(field_key, value, schema_field_specs):
            return False

        active_field = card.get("active_edit_field")
        if active_field and active_field != field_key:
            self.commit_edit_field(card)
        elif active_field == field_key:
            return True

        card["active_edit_field"] = field_key
        card["edit_original_value"] = value
        card["edit_buffer"] = self._serialize_edit_value(value)
        return True

    def commit_edit_field(self, card):
        field_key = card.get("active_edit_field")
        if not field_key:
            return False

        original_value = card.get("edit_original_value", self.entity.get(field_key))
        new_value = self._coerce_edit_buffer(original_value, card.get("edit_buffer", ""))
        self.entity[field_key] = new_value

        card["active_edit_field"] = None
        card["edit_buffer"] = ""
        card["edit_original_value"] = None
        return True

    def cancel_edit_field(self, card):
        if not card.get("active_edit_field"):
            return False

        card["active_edit_field"] = None
        card["edit_buffer"] = ""
        card["edit_original_value"] = None
        return True

    def handle_keydown(self, card, event):
        if not card.get("is_edit_mode", False):
            return False

        active_field = card.get("active_edit_field")
        if not active_field:
            if event.key == pygame.K_TAB:
                direction = -1 if (event.mod & pygame.KMOD_SHIFT) else 1
                return self._cycle_edit_field(card, direction=direction)
            if event.key == pygame.K_ESCAPE:
                card["is_edit_mode"] = False
                return True
            return False

        if active_field == "wiki_entry" and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if event.mod & (pygame.KMOD_CTRL | pygame.KMOD_SHIFT):
                card["edit_buffer"] = card.get("edit_buffer", "") + "\n"
                return True
            return self.commit_edit_field(card)

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self.commit_edit_field(card)

        if event.key == pygame.K_ESCAPE:
            return self.cancel_edit_field(card)

        if event.key == pygame.K_TAB:
            direction = -1 if (event.mod & pygame.KMOD_SHIFT) else 1
            self.commit_edit_field(card)
            return self._cycle_edit_field(card, direction=direction)

        if event.key == pygame.K_BACKSPACE:
            card["edit_buffer"] = card.get("edit_buffer", "")[:-1]
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            card["edit_buffer"] = card.get("edit_buffer", "") + text
            return True

        return False

    def _wrap_text_lines(self, text, font, max_width):
        """
        Wrap text into multiple rendered lines that fit the given width.
        Preserves explicit newline breaks.
        """
        if text is None:
            return [""]

        max_width = max(20, int(max_width))
        wrapped_lines = []

        for paragraph in str(text).splitlines() or [""]:
            words = paragraph.split(" ")

            if not words:
                wrapped_lines.append("")
                continue

            current_line = ""
            for word in words:
                candidate = word if not current_line else f"{current_line} {word}"

                if font.size(candidate)[0] <= max_width:
                    current_line = candidate
                    continue

                if current_line:
                    wrapped_lines.append(current_line)
                    current_line = word
                else:
                    split_word = word
                    while split_word:
                        chunk = split_word
                        while chunk and font.size(chunk)[0] > max_width:
                            chunk = chunk[:-1]

                        if not chunk:
                            break

                        wrapped_lines.append(chunk)
                        split_word = split_word[len(chunk):]

                    current_line = ""

            if current_line or paragraph == "":
                wrapped_lines.append(current_line)

        return wrapped_lines or [""]

    def _resolve_image_reference(self):
        """
        Resolve the active preview image using shared fallback order.

        Preferred order:
        1. card_image
        2. design_image
        3. card_image_front
        4. card_image_side
        5. card_image_top
        6. any other role-specific card image fields suggested for the entity
        7. image_path
        8. image
        """
        explicit_order = [
            "card_image",
            "design_image",
            "card_image_front",
            "card_image_side",
            "card_image_top",
        ]

        seen = set()

        for key in explicit_order:
            seen.add(key)
            value = self.entity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for role_info in ScaleHelper.suggest_media_canvases(self.entity):
            role = role_info.get("role")
            if not role:
                continue

            field_name = self._role_field_name(role)
            if field_name in seen:
                continue

            seen.add(field_name)
            value = self.entity.get(field_name)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for key in ("image_path", "image"):
            value = self.entity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        return None

    def _load_card_image_surface(self, image_path):
        if not image_path:
            return None

        normalized_path = os.path.normpath(image_path)

        candidate_paths = [normalized_path]
        if not os.path.isabs(normalized_path):
            candidate_paths.append(os.path.normpath(os.path.join(os.getcwd(), normalized_path)))

        for candidate in candidate_paths:
            if not os.path.exists(candidate):
                continue
            try:
                return pygame.image.load(candidate).convert_alpha()
            except Exception:
                return None

        return None

    def _get_table_column_widths(self, font, rect, section_map):
        available_w = max(180, rect.width - 24)
        max_key_w = self.TABLE_MIN_KEY_W

        if font is not None:
            for section_name in self._visible_sections():
                for key, _ in section_map.get(section_name, []):
                    max_key_w = max(max_key_w, font.size(f"{key}:")[0] + 14)

        key_w = max(self.TABLE_MIN_KEY_W, min(self.TABLE_MAX_KEY_W, max_key_w))
        value_w = max(120, available_w - key_w - self.TABLE_COLUMN_GAP)
        return key_w, value_w

    def _measure_table_row(self, font, value, value_column_w):
        rendered_value = self._format_value(value)
        wrapped_lines = self._wrap_text_lines(rendered_value, font, value_column_w)
        content_h = max(1, len(wrapped_lines)) * self.TEXT_LINE_H
        row_h = content_h + self.TABLE_ROW_PAD_Y * 2
        return wrapped_lines, row_h

    def layout_card(self, card, rect):
        section_hitboxes = []
        tab_hitboxes = []
        media_import_hitboxes = []
        editable_field_hitboxes = []
        field_rows = []
        general_content_rect = None
        schema_field_specs = self._get_schema_field_specs()

        tab_y = rect.y + self.HEADER_H + 6
        tab_x = rect.x + 12
        tab_gap = 6
        tab_widths = {
            "general": 82,
            "overview": 88,
            "relations": 82,
            "state": 62,
            "media": 62,
        }

        for tab_name in self.TAB_ORDER:
            tab_rect = pygame.Rect(tab_x, tab_y, tab_widths[tab_name], self.TAB_H)
            tab_hitboxes.append((tab_name, tab_rect))
            tab_x = tab_rect.right + tab_gap

        edit_toggle_rect = pygame.Rect(rect.right - 34, rect.y + 12, 20, 20)

        image_rect = pygame.Rect(
            rect.x + 12,
            rect.y + self.IMAGE_TOP,
            rect.width - 24,
            self._image_block_height(),
        )

        if self._is_media_mode():
            row_y = image_rect.y + 104
            button_w = 68
            button_h = 18
            row_gap = 20
            button_x = image_rect.right - button_w - 10

            for media_info in ScaleHelper.suggest_media_canvases(self.entity):
                role_name = media_info["role"]
                button_rect = pygame.Rect(button_x, row_y - 1, button_w, button_h)
                media_import_hitboxes.append((role_name, button_rect))
                row_y += row_gap

        current_y = image_rect.bottom + 12
        content_left = rect.x + 12
        content_right = rect.right - 12
        text_width = content_right - content_left
        top_content_y = tab_y + self.TAB_H + 10

        section_map = self._sectioned_fields()
        key_column_w, value_column_w = self._get_table_column_widths(card["layout_font"], rect, section_map)
        value_column_x = content_left + key_column_w + self.TABLE_COLUMN_GAP

        if self._is_general_mode():
            image_rect = None
            handle_bottom = rect.bottom - 8
            resize_handle_rect = pygame.Rect(
                rect.right - 18,
                handle_bottom - self.RESIZE_HANDLE,
                self.RESIZE_HANDLE,
                self.RESIZE_HANDLE,
            )
            launch_rect = pygame.Rect(
                rect.x + 12,
                resize_handle_rect.y - 8 - self.LAUNCH_H,
                rect.width - 24,
                self.LAUNCH_H,
            )
            center_y = launch_rect.y - 14
            left_x = rect.x + 20
            right_x = rect.right - 20
            timeline_y = center_y - 10
            timeline_label_y = max(top_content_y + 8, timeline_y - 18)
            general_bottom = timeline_label_y - 10
            general_height = max(140, general_bottom - top_content_y)
            general_content_rect = pygame.Rect(content_left, top_content_y, text_width, general_height)
            if card.get("is_edit_mode", False):
                editable_field_hitboxes.append(("wiki_entry", general_content_rect))
            content_end_y = general_content_rect.bottom
        else:
            content_end_y = current_y

            for section_name in self._visible_sections():
                section_rect = pygame.Rect(content_left, current_y, text_width, self.SECTION_HEADER_H)
                section_hitboxes.append((section_name, section_rect))
                current_y += self.SECTION_HEADER_H + self.SECTION_GAP

                if not self.collapsed_sections.get(section_name, False):
                    for key, value in section_map.get(section_name, []):
                        wrapped_lines, row_h = self._measure_table_row(card["layout_font"], value, value_column_w)
                        row_rect = pygame.Rect(content_left, current_y, text_width, row_h)
                        key_rect = pygame.Rect(content_left, current_y, key_column_w, row_h)
                        value_rect = pygame.Rect(value_column_x, current_y, value_column_w, row_h)

                        if card.get("is_edit_mode", False) and self._is_field_editable(key, value, schema_field_specs):
                            editable_field_hitboxes.append((key, row_rect))

                        field_rows.append(
                            {
                                "section": section_name,
                                "key": key,
                                "row_rect": row_rect,
                                "key_rect": key_rect,
                                "value_rect": value_rect,
                                "wrapped_lines": wrapped_lines,
                            }
                        )

                        current_y = row_rect.bottom + self.SECTION_GAP

                    current_y += self.SECTION_GAP

            content_end_y = current_y
            handle_bottom = rect.bottom - 8
            resize_handle_rect = pygame.Rect(
                rect.right - 18,
                handle_bottom - self.RESIZE_HANDLE,
                self.RESIZE_HANDLE,
                self.RESIZE_HANDLE,
            )
            launch_rect = pygame.Rect(
                rect.x + 12,
                resize_handle_rect.y - 8 - self.LAUNCH_H,
                rect.width - 24,
                self.LAUNCH_H,
            )
            center_y = launch_rect.y - 14
            left_x = rect.x + 20
            right_x = rect.right - 20
            timeline_y = center_y - 10
            timeline_label_y = max(content_end_y + 8, timeline_y - 18)

        year_positions = []
        years = card["years"]
        for index, year in enumerate(years):
            frac = 0.5 if len(years) == 1 else index / (len(years) - 1)
            year_x = int(left_x + (right_x - left_x) * frac)
            year_positions.append((year, year_x))

        header_drag_rect = pygame.Rect(rect.x + 1, rect.y + 1, rect.width - 2, self.HEADER_H)
        resize_hitboxes = [
            ("left", pygame.Rect(rect.x - self.RESIZE_BORDER, rect.y + self.HEADER_H, self.RESIZE_BORDER * 2, rect.height - self.HEADER_H)),
            ("right", pygame.Rect(rect.right - self.RESIZE_BORDER, rect.y + self.HEADER_H, self.RESIZE_BORDER * 2, rect.height - self.HEADER_H)),
            ("top", pygame.Rect(rect.x, rect.y - self.RESIZE_BORDER, rect.width, self.RESIZE_BORDER * 2)),
            ("bottom", pygame.Rect(rect.x, rect.bottom - self.RESIZE_BORDER, rect.width, self.RESIZE_BORDER * 2)),
            ("top_left", pygame.Rect(rect.x - self.RESIZE_BORDER, rect.y - self.RESIZE_BORDER, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
            ("top_right", pygame.Rect(rect.right - self.RESIZE_BORDER * 2, rect.y - self.RESIZE_BORDER, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
            ("bottom_left", pygame.Rect(rect.x - self.RESIZE_BORDER, rect.bottom - self.RESIZE_BORDER * 2, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
            ("bottom_right", pygame.Rect(rect.right - self.RESIZE_BORDER * 2, rect.bottom - self.RESIZE_BORDER * 2, self.RESIZE_BORDER * 3, self.RESIZE_BORDER * 3)),
        ]

        final_rect = pygame.Rect(rect.x, rect.y, rect.width, rect.height)

        card["rect"] = final_rect
        card["tab_hitboxes"] = tab_hitboxes
        card["image_rect"] = image_rect
        card["general_content_rect"] = general_content_rect
        card["timeline_label_y"] = timeline_label_y
        card["timeline_y"] = timeline_y
        card["launch_rect"] = launch_rect
        card["header_drag_rect"] = header_drag_rect
        card["resize_handle_rect"] = resize_handle_rect
        card["section_hitboxes"] = section_hitboxes
        card["media_import_hitboxes"] = media_import_hitboxes
        card["editable_field_hitboxes"] = editable_field_hitboxes
        card["field_rows"] = field_rows
        card["resize_hitboxes"] = resize_hitboxes
        card["edit_toggle_rect"] = edit_toggle_rect
        card["year_hitboxes"] = [
            (year, pygame.Rect(year_x - 12, center_y - 12, 24, 48))
            for year, year_x in year_positions
        ]

    def get_minimum_height(self, card, font):
        """
        Estimate the minimum card height needed for currently visible content,
        including wrapped text.
        """
        section_map = self._sectioned_fields()

        if self._is_general_mode():
            content_rect = pygame.Rect(0, 0, int(card.get("canvas_w", 420)) - 24, 0)
            general_h = CardWikiRenderer.measure_content(
                self._get_general_wiki_text(card),
                font,
                content_rect,
                resolve_link_label=self._resolve_wiki_link_label,
            )
            timeline_label_y = self.HEADER_H + self.TAB_H + 20 + general_h + 8
            timeline_y = timeline_label_y + 18
            center_y = timeline_y + 10
            launch_top = center_y + 24
            resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE
            return max(320, resize_bottom + 8)

        current_y = self.IMAGE_TOP + self._image_block_height() + 12
        probe_rect = pygame.Rect(0, 0, int(card.get("canvas_w", 420)), 0)
        _, value_column_w = self._get_table_column_widths(font, probe_rect, section_map)

        for section_name in self._visible_sections():
            current_y += self.SECTION_HEADER_H + self.SECTION_GAP

            if not self.collapsed_sections.get(section_name, False):
                for _, value in section_map.get(section_name, []):
                    _, row_h = self._measure_table_row(font, value, value_column_w)
                    current_y += row_h + self.SECTION_GAP

                current_y += self.SECTION_GAP

        timeline_label_y = current_y + 8
        timeline_y = timeline_label_y + 18
        center_y = timeline_y + 10
        launch_top = center_y + 24
        resize_bottom = launch_top + self.LAUNCH_H + 8 + self.RESIZE_HANDLE

        return max(260, resize_bottom + 8)

    def draw_card(self, screen, font, card):
        rect = card["rect"]

        pygame.draw.rect(screen, (28, 30, 38), rect)
        pygame.draw.rect(screen, (170, 170, 170), rect, 1)

        header_rect = card["header_drag_rect"]
        pygame.draw.rect(screen, (34, 38, 48), header_rect)
        pygame.draw.line(
            screen,
            (110, 110, 120),
            (header_rect.x, header_rect.bottom),
            (header_rect.right, header_rect.bottom),
            1,
        )

        title_surface = font.render(card["title"], True, (245, 245, 245))
        subtitle_surface = font.render(card["subtitle"], True, (170, 170, 170))
        screen.blit(title_surface, (rect.x + 12, rect.y + 10))
        screen.blit(subtitle_surface, (rect.x + 12, rect.y + 30))

        edit_toggle_rect = card.get("edit_toggle_rect")
        if edit_toggle_rect is not None:
            edit_enabled = bool(card.get("is_edit_mode", False))
            edit_fill = (70, 96, 140) if edit_enabled else (46, 50, 60)
            edit_border = (210, 220, 240) if edit_enabled else (140, 140, 150)
            edit_text_color = (245, 245, 245) if edit_enabled else (210, 210, 210)

            pygame.draw.rect(screen, edit_fill, edit_toggle_rect)
            pygame.draw.rect(screen, edit_border, edit_toggle_rect, 1)
            edit_text = font.render("E", True, edit_text_color)
            edit_text_rect = edit_text.get_rect(center=edit_toggle_rect.center)
            screen.blit(edit_text, edit_text_rect)

        if card.get("is_edit_mode", False):
            active_field = card.get("active_edit_field")
            if active_field:
                if active_field in self.TEMPORAL_FIELDS:
                    edit_status = f"Editing {active_field} | Click timeline to set | Enter save | Esc cancel"
                elif active_field == "wiki_entry":
                    edit_status = "Editing wiki_entry | Ctrl+L link | Ctrl+Enter newline | Enter save"
                else:
                    edit_status = f"Editing {active_field} | Enter save | Esc cancel | Tab next"
            else:
                edit_status = "Edit mode | Click a highlighted row or press Tab to begin"
            status_surface = font.render(edit_status, True, (190, 205, 230))
            status_x = rect.right - 44 - status_surface.get_width()
            status_x = max(rect.x + 150, status_x)
            screen.blit(status_surface, (status_x, rect.y + 30))

        self._draw_tabs(screen, font, card)
        if self._is_general_mode():
            self._draw_general_content(screen, font, card)
        else:
            self._draw_image_block(screen, font, card)
            self._draw_sections(screen, font, card)

        timeline_label_y = card.get("timeline_label_y", card["timeline_y"] - 18)
        timeline_y = card["timeline_y"]
        left_x = rect.x + 20
        right_x = rect.right - 20
        center_y = timeline_y + 10

        years = card.get("years", [])
        if len(years) >= 2:
            timeline_label = f"Range: {years[0]}-{years[-1]}"
        elif len(years) == 1:
            timeline_label = f"Year: {years[0]}"
        else:
            timeline_label = "Year: 0"

        timeline_label_surface = font.render(timeline_label, True, (200, 200, 200))
        screen.blit(timeline_label_surface, (rect.x + 12, timeline_label_y))

        pygame.draw.line(screen, (170, 170, 170), (left_x, center_y), (right_x, center_y), 1)

        for year, hitbox in card["year_hitboxes"]:
            marker_rect = pygame.Rect(hitbox.centerx - 5, center_y - 5, 10, 10)
            selected = year == card["selected_year"]

            fill = (210, 210, 210) if selected else (70, 70, 70)
            border = (240, 240, 240) if selected else (170, 170, 170)
            pygame.draw.rect(screen, fill, marker_rect)
            pygame.draw.rect(screen, border, marker_rect, 1)

            year_surface = font.render(str(year), True, (230, 230, 230))
            year_rect = year_surface.get_rect(center=(hitbox.centerx, center_y + 22))
            screen.blit(year_surface, year_rect)

        launch_rect = card["launch_rect"]
        pygame.draw.rect(screen, (55, 55, 55), launch_rect)
        pygame.draw.rect(screen, (210, 210, 210), launch_rect, 1)
        launch_text = font.render(f"Launch [{card['selected_year']}]", True, (245, 245, 245))
        launch_text_rect = launch_text.get_rect(center=launch_rect.center)
        screen.blit(launch_text, launch_text_rect)

        handle_rect = card["resize_handle_rect"]
        pygame.draw.rect(screen, (120, 120, 120), handle_rect)
        pygame.draw.rect(screen, (220, 220, 220), handle_rect, 1)

    def _draw_tabs(self, screen, font, card):
        for tab_name, tab_rect in card.get("tab_hitboxes", []):
            selected = tab_name == self.active_tab
            fill = (58, 64, 78) if selected else (36, 40, 50)
            border = (200, 200, 210) if selected else (110, 110, 120)
            text_color = (245, 245, 245) if selected else (195, 195, 195)

            pygame.draw.rect(screen, fill, tab_rect)
            pygame.draw.rect(screen, border, tab_rect, 1)

            label = self.TAB_LABELS.get(tab_name, tab_name.title())
            text_surface = font.render(label, True, text_color)
            text_rect = text_surface.get_rect(center=tab_rect.center)
            screen.blit(text_surface, text_rect)

    def _draw_scaled_preview(self, screen, image_surface, target_rect):
        inner_rect = target_rect.inflate(-8, -8)
        src_w = max(1, image_surface.get_width())
        src_h = max(1, image_surface.get_height())
        scale = min(inner_rect.width / src_w, inner_rect.height / src_h)

        target_w = max(1, int(src_w * scale))
        target_h = max(1, int(src_h * scale))
        scaled = pygame.transform.smoothscale(image_surface, (target_w, target_h))
        scaled_rect = scaled.get_rect(center=inner_rect.center)
        screen.blit(scaled, scaled_rect)

    def _draw_media_block(self, screen, font, card, image_rect):
        preview_rect = pygame.Rect(image_rect.x + 8, image_rect.y + 8, image_rect.width - 16, 88)
        pygame.draw.rect(screen, (32, 34, 44), preview_rect)
        pygame.draw.rect(screen, (100, 100, 110), preview_rect, 1)

        image_ref = self._resolve_image_reference()
        image_surface = self._load_card_image_surface(image_ref)

        if image_surface is not None:
            self._draw_scaled_preview(screen, image_surface, preview_rect)
            label_text = os.path.basename(image_ref)
        else:
            no_image = font.render("No active preview image", True, (195, 195, 195))
            no_image_rect = no_image.get_rect(center=preview_rect.center)
            screen.blit(no_image, no_image_rect)
            label_text = ScaleHelper.format_dimensions_label(self.entity)

        label_surface = font.render(label_text, True, (195, 195, 195))
        screen.blit(label_surface, (preview_rect.x + 6, preview_rect.y + 6))

        divider_y = image_rect.y + 102
        pygame.draw.line(screen, (90, 90, 100), (image_rect.x + 8, divider_y), (image_rect.right - 8, divider_y), 1)

        row_y = divider_y + 8
        text_x = image_rect.x + 10

        buttons_by_role = {role_name: rect for role_name, rect in card.get("media_import_hitboxes", [])}

        for media_info in ScaleHelper.suggest_media_canvases(self.entity):
            role_name = media_info["role"]
            width_px = media_info["width"]
            height_px = media_info["height"]
            role_ref = self._resolve_role_image_reference(role_name)
            status = "set" if role_ref else "empty"

            line = f"{role_name.title()}: {width_px} x {height_px} [{status}]"
            surf = font.render(line, True, (195, 195, 195))
            screen.blit(surf, (text_x, row_y))

            button_rect = buttons_by_role.get(role_name)
            if button_rect is not None:
                pygame.draw.rect(screen, (58, 64, 78), button_rect)
                pygame.draw.rect(screen, (200, 200, 210), button_rect, 1)
                button_text = font.render("Import", True, (245, 245, 245))
                button_text_rect = button_text.get_rect(center=button_rect.center)
                screen.blit(button_text, button_text_rect)

            row_y += 20

    def _draw_image_block(self, screen, font, card):
        if self._is_general_mode():
            return

        image_rect = card["image_rect"]
        pygame.draw.rect(screen, (40, 42, 52), image_rect)
        pygame.draw.rect(screen, (120, 120, 120), image_rect, 1)

        if self._is_media_mode():
            self._draw_media_block(screen, font, card, image_rect)
            return

        image_ref = self._resolve_image_reference()
        image_surface = self._load_card_image_surface(image_ref)

        if image_surface is not None:
            self._draw_scaled_preview(screen, image_surface, image_rect)
            path_label = font.render(os.path.basename(image_ref), True, (195, 195, 195))
            screen.blit(path_label, (image_rect.x + 10, image_rect.bottom - self.IMAGE_TEXT_LINE_H - 4))
            return

        dims_label = ScaleHelper.format_dimensions_label(self.entity)
        current_y = image_rect.y + 8

        if ScaleHelper.suggest_default_media_roles(self.entity):
            lines = [
                "No image",
                dims_label,
            ]

            for line in lines:
                surf = font.render(line, True, (195, 195, 195))
                screen.blit(surf, (image_rect.x + 10, current_y))
                current_y += self.IMAGE_TEXT_LINE_H

            for media_info in ScaleHelper.suggest_media_canvases(self.entity):
                role_name = media_info["role"].title()
                width_px = media_info["width"]
                height_px = media_info["height"]
                line = f"{role_name}: {width_px} x {height_px}"
                surf = font.render(line, True, (195, 195, 195))
                screen.blit(surf, (image_rect.x + 10, current_y))
                current_y += self.IMAGE_TEXT_LINE_H

            footer = font.render("Open Media tab to import views", True, (195, 195, 195))
            screen.blit(footer, (image_rect.x + 10, current_y))
            return

        canvas = ScaleHelper.suggest_canvas_from_dimensions(self.entity)
        lines = [
            "No image",
            dims_label,
            f"Suggested canvas: {canvas['width']} x {canvas['height']}",
            "Import image later",
        ]

        for line in lines:
            surf = font.render(line, True, (195, 195, 195))
            screen.blit(surf, (image_rect.x + 10, current_y))
            current_y += self.IMAGE_TEXT_LINE_H

    def _draw_sections(self, screen, font, card):
        if self._is_general_mode():
            return

        editable_hitboxes = {
            field_key: field_rect
            for field_key, field_rect in card.get("editable_field_hitboxes", [])
        }
        rows_by_section = {}
        for row in card.get("field_rows", []):
            rows_by_section.setdefault(row["section"], []).append(row)

        for section_name in self._visible_sections():
            header_rect = next((rect for name, rect in card["section_hitboxes"] if name == section_name), None)
            if header_rect is None:
                continue

            pygame.draw.rect(screen, (36, 40, 50), header_rect)
            pygame.draw.rect(screen, (110, 110, 120), header_rect, 1)

            expanded = not self.collapsed_sections.get(section_name, False)
            marker = "v" if expanded else ">"
            header_text = font.render(f"{marker} {section_name}", True, (235, 235, 235))
            screen.blit(header_text, (header_rect.x + 8, header_rect.y + 3))

            current_y = header_rect.bottom + 4

            if not expanded:
                continue

            for row_index, row in enumerate(rows_by_section.get(section_name, [])):
                key = row["key"]
                row_rect = row["row_rect"]
                is_active_field = key == card.get("active_edit_field")
                is_editable = key in editable_hitboxes

                row_fill = (33, 36, 46) if row_index % 2 == 0 else (29, 32, 42)
                row_border = (78, 84, 100)
                if is_editable:
                    row_fill = (42, 47, 58)
                if is_active_field:
                    row_fill = (54, 62, 76)
                    row_border = (180, 200, 240)

                pygame.draw.rect(screen, row_fill, row_rect)
                pygame.draw.rect(screen, row_border, row_rect, 1)
                pygame.draw.line(
                    screen,
                    (88, 94, 112),
                    (row["key_rect"].right + self.TABLE_COLUMN_GAP // 2, row_rect.y + 1),
                    (row["key_rect"].right + self.TABLE_COLUMN_GAP // 2, row_rect.bottom - 1),
                    1,
                )

                key_surface = font.render(f"{key}:", True, (210, 210, 210))
                key_y = row_rect.y + self.TABLE_ROW_PAD_Y
                screen.blit(key_surface, (row["key_rect"].x + 6, key_y))

                if is_editable and not is_active_field:
                    hint_label = "timeline" if key in self.TEMPORAL_FIELDS else "editable"
                    hint_surface = font.render(hint_label, True, (130, 150, 185))
                    hint_x = row["key_rect"].right - hint_surface.get_width() - 6
                    if hint_x > row["key_rect"].x + 12:
                        screen.blit(hint_surface, (hint_x, key_y))

                if is_active_field and card.get("is_edit_mode", False):
                    wrapped_lines = self._wrap_text_lines(
                        card.get("edit_buffer", ""),
                        font,
                        row["value_rect"].width,
                    )
                    value_color = (245, 245, 245)
                else:
                    value_color = (215, 225, 245) if is_editable else (180, 180, 180)
                    wrapped_lines = row["wrapped_lines"]

                line_y = row_rect.y + self.TABLE_ROW_PAD_Y
                for line in wrapped_lines:
                    val_surface = font.render(line, True, value_color)
                    screen.blit(val_surface, (row["value_rect"].x + 2, line_y))
                    line_y += self.TEXT_LINE_H

    def _draw_general_content(self, screen, font, card):
        general_rect = card.get("general_content_rect")
        if general_rect is None:
            return

        is_editing = card.get("is_edit_mode", False) and card.get("active_edit_field") == "wiki_entry"
        wiki_text = self._get_general_wiki_text(card)
        CardWikiRenderer.draw_content(
            screen,
            font,
            general_rect,
            wiki_text,
            is_editing=is_editing,
            resolve_link_label=self._resolve_wiki_link_label,
        )

        if card.get("wiki_link_picker_open", False):
            self._draw_wiki_link_picker(screen, font, card, general_rect)

    def _draw_wiki_link_picker(self, screen, font, card, general_rect):
        matches = card.get("wiki_link_matches", [])
        picker_w = min(360, general_rect.width - 16)
        picker_h = 66 + min(6, len(matches)) * 42
        picker_rect = pygame.Rect(
            general_rect.x + 12,
            general_rect.y + 12,
            picker_w,
            picker_h,
        )
        pygame.draw.rect(screen, (22, 26, 36), picker_rect)
        pygame.draw.rect(screen, (186, 194, 210), picker_rect, 1)

        title_surface = font.render("Insert Entry Link", True, (244, 244, 244))
        screen.blit(title_surface, (picker_rect.x + 10, picker_rect.y + 8))

        query_rect = pygame.Rect(picker_rect.x + 10, picker_rect.y + 28, picker_rect.width - 20, 24)
        pygame.draw.rect(screen, (36, 42, 56), query_rect)
        pygame.draw.rect(screen, (126, 136, 154), query_rect, 1)
        query_text = card.get("wiki_link_query", "")
        query_surface = font.render(query_text or "Search entries...", True, (232, 232, 232) if query_text else (156, 164, 178))
        screen.blit(query_surface, (query_rect.x + 8, query_rect.y + 4))

        selected_index = card.get("wiki_link_selected_index", 0)
        row_y = query_rect.bottom + 8
        for index, match in enumerate(matches[:6]):
            row_rect = pygame.Rect(picker_rect.x + 10, row_y, picker_rect.width - 20, 36)
            fill = (54, 64, 82) if index == selected_index else (30, 34, 44)
            border = (194, 206, 228) if index == selected_index else (88, 96, 112)
            pygame.draw.rect(screen, fill, row_rect)
            pygame.draw.rect(screen, border, row_rect, 1)

            primary = f"{match['pretty_name']} | {match['id']}"
            start_text = "" if match["start_year"] is None else str(match["start_year"])
            end_text = "" if match["end_year"] is None else str(match["end_year"])
            secondary = f"{start_text} | {end_text}"

            primary_surface = font.render(primary, True, (242, 242, 242))
            secondary_surface = font.render(secondary, True, (186, 194, 208))
            screen.blit(primary_surface, (row_rect.x + 8, row_rect.y + 3))
            screen.blit(secondary_surface, (row_rect.x + 8, row_rect.y + 18))
            row_y += 40
