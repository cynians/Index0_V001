import os

import pygame

from engine.scaler import ScaleHelper


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
    TEXT_LINE_H = 16
    IMAGE_TEXT_LINE_H = 18
    SECTION_GAP = 4

    SECTION_ORDER = [
        "Identity",
        "Classification",
        "Dimensions / Scale",
        "Relations",
        "State / Layout",
        "Metadata",
    ]

    TAB_ORDER = ["overview", "relations", "state", "media"]
    TAB_LABELS = {
        "overview": "Overview",
        "relations": "Relations",
        "state": "State",
        "media": "Media",
    }
    TAB_SECTIONS = {
        "overview": ["Identity", "Classification", "Dimensions / Scale", "Metadata"],
        "relations": ["Relations"],
        "state": ["State / Layout"],
        "media": [],
    }

    def __init__(self, entity, dataset_name=None):
        self.entity = entity or {}
        self.dataset_name = dataset_name or self.entity.get("_dataset", self.entity.get("type", "entity"))
        self.active_tab = "overview"
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
        return self.TAB_SECTIONS.get(self.active_tab, self.TAB_SECTIONS["overview"])

    def _is_media_mode(self):
        return self.active_tab == "media"

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

    def _sectioned_fields(self):
        entity = self.entity

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
        classification = [(key, entity.get(key)) for key in classification_keys if key in entity]

        dims = [
            ("dimension_x_m", entity.get("dimension_x_m")),
            ("dimension_y_m", entity.get("dimension_y_m")),
            ("dimension_z_m", entity.get("dimension_z_m")),
            ("mass_kg", entity.get("mass_kg")),
            ("power_kw", entity.get("power_kw")),
        ]

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

        for key, value in entity.items():
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

            metadata_values.append((key, value))

        return {
            "Identity": [(k, v) for k, v in identity if v is not None],
            "Classification": [(k, v) for k, v in classification if v is not None],
            "Dimensions / Scale": [(k, v) for k, v in dims if v is not None],
            "Relations": relation_values,
            "State / Layout": state_values,
            "Metadata": metadata_values,
        }

    def _format_value(self, value):
        if isinstance(value, dict):
            return "\n".join(f"{k}: {v}" for k, v in value.items())
        if isinstance(value, list):
            return "\n".join(f"- {item}" for item in value) if value else "[]"
        return str(value)

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

    def layout_card(self, card, rect):
        section_hitboxes = []
        tab_hitboxes = []
        media_import_hitboxes = []

        tab_y = rect.y + self.HEADER_H + 6
        tab_x = rect.x + 12
        tab_gap = 6
        tab_widths = {
            "overview": 82,
            "relations": 82,
            "state": 62,
            "media": 62,
        }

        for tab_name in self.TAB_ORDER:
            tab_rect = pygame.Rect(tab_x, tab_y, tab_widths[tab_name], self.TAB_H)
            tab_hitboxes.append((tab_name, tab_rect))
            tab_x = tab_rect.right + tab_gap

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

        section_map = self._sectioned_fields()

        for section_name in self._visible_sections():
            section_rect = pygame.Rect(content_left, current_y, text_width, self.SECTION_HEADER_H)
            section_hitboxes.append((section_name, section_rect))
            current_y += self.SECTION_HEADER_H + self.SECTION_GAP

            if not self.collapsed_sections.get(section_name, False):
                value_column_x = content_left + 120
                value_column_w = max(80, rect.right - value_column_x - 12)

                for _, value in section_map.get(section_name, []):
                    rendered_value = self._format_value(value)
                    wrapped_lines = self._wrap_text_lines(rendered_value, card["layout_font"], value_column_w)
                    line_count = max(1, len(wrapped_lines))
                    current_y += line_count * self.TEXT_LINE_H + self.SECTION_GAP

                current_y += self.SECTION_GAP

        timeline_label_y = current_y + 8
        timeline_y = timeline_label_y + 18
        left_x = rect.x + 20
        right_x = rect.right - 20
        center_y = timeline_y + 10

        year_positions = []
        years = card["years"]
        for index, year in enumerate(years):
            frac = 0.5 if len(years) == 1 else index / (len(years) - 1)
            year_x = int(left_x + (right_x - left_x) * frac)
            year_positions.append((year, year_x))

        launch_rect = pygame.Rect(
            rect.x + 12,
            center_y + 24,
            rect.width - 24,
            self.LAUNCH_H,
        )

        header_drag_rect = pygame.Rect(rect.x + 1, rect.y + 1, rect.width - 2, self.HEADER_H)
        resize_handle_rect = pygame.Rect(
            rect.right - 18,
            launch_rect.bottom + 8,
            self.RESIZE_HANDLE,
            self.RESIZE_HANDLE,
        )

        final_bottom = resize_handle_rect.bottom + 4
        final_rect = pygame.Rect(rect.x, rect.y, rect.width, final_bottom - rect.y)

        card["rect"] = final_rect
        card["tab_hitboxes"] = tab_hitboxes
        card["image_rect"] = image_rect
        card["timeline_label_y"] = timeline_label_y
        card["timeline_y"] = timeline_y
        card["launch_rect"] = launch_rect
        card["header_drag_rect"] = header_drag_rect
        card["resize_handle_rect"] = resize_handle_rect
        card["section_hitboxes"] = section_hitboxes
        card["media_import_hitboxes"] = media_import_hitboxes
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

        current_y = self.IMAGE_TOP + self._image_block_height() + 12
        content_left = 12
        value_column_x = content_left + 120
        value_column_w = max(80, int(card.get("canvas_w", 420)) - value_column_x - 12)

        for section_name in self._visible_sections():
            current_y += self.SECTION_HEADER_H + self.SECTION_GAP

            if not self.collapsed_sections.get(section_name, False):
                for _, value in section_map.get(section_name, []):
                    rendered_value = self._format_value(value)
                    wrapped_lines = self._wrap_text_lines(rendered_value, font, value_column_w)
                    line_count = max(1, len(wrapped_lines))
                    current_y += line_count * self.TEXT_LINE_H + self.SECTION_GAP

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

        self._draw_tabs(screen, font, card)
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
        section_map = self._sectioned_fields()
        content_left = card["rect"].x + 12
        value_column_x = content_left + 120
        value_column_w = max(80, card["rect"].right - value_column_x - 12)

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

            for key, value in section_map.get(section_name, []):
                key_surface = font.render(f"{key}:", True, (210, 210, 210))
                screen.blit(key_surface, (content_left + 6, current_y))

                rendered_value = self._format_value(value)
                wrapped_lines = self._wrap_text_lines(rendered_value, font, value_column_w)

                line_y = current_y
                for line in wrapped_lines:
                    val_surface = font.render(line, True, (180, 180, 180))
                    screen.blit(val_surface, (value_column_x, line_y))
                    line_y += self.TEXT_LINE_H

                current_y = line_y + self.SECTION_GAP