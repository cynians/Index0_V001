import pygame

from engine.scaler import ScaleHelper


class EntityCard:
    """
    Reusable renderer + interaction helper for one repository entity card.
    """

    HEADER_H = 50
    SECTION_HEADER_H = 22
    IMAGE_TOP = 58
    IMAGE_H = 110
    LAUNCH_H = 24
    RESIZE_HANDLE = 14

    SECTION_ORDER = [
        "Identity",
        "Classification",
        "Dimensions / Scale",
        "Relations",
        "State / Layout",
        "Metadata",
    ]

    def __init__(self, entity, dataset_name=None):
        self.entity = entity or {}
        self.dataset_name = dataset_name or self.entity.get("_dataset", self.entity.get("type", "entity"))
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

        for key, value in entity.items():
            if key in {
                "id", "pretty_name", "name", "type", "_dataset",
                "vehicle_class", "component_class", "location_class",
                "system_role", "system_class", "body_class",
                "dimension_x_m", "dimension_y_m", "dimension_z_m",
                "mass_kg", "power_kw",
            }:
                continue

            if key in {"description", "notes", "tags", "start_year", "entry_status"}:
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

    def layout_card(self, card, rect):
        section_hitboxes = []

        image_rect = pygame.Rect(
            rect.x + 12,
            rect.y + self.IMAGE_TOP,
            rect.width - 24,
            self.IMAGE_H,
        )

        current_y = image_rect.bottom + 12
        content_left = rect.x + 12
        content_right = rect.right - 12
        text_width = content_right - content_left

        section_map = self._sectioned_fields()

        for section_name in self.SECTION_ORDER:
            section_rect = pygame.Rect(content_left, current_y, text_width, self.SECTION_HEADER_H)
            section_hitboxes.append((section_name, section_rect))
            current_y += self.SECTION_HEADER_H + 4

            if not self.collapsed_sections.get(section_name, False):
                for key, value in section_map.get(section_name, []):
                    rendered_value = self._format_value(value)
                    line_count = max(1, rendered_value.count("\n") + 1)
                    current_y += line_count * 16 + 4

                current_y += 4

        timeline_y = max(current_y + 8, rect.bottom - 68)
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
            rect.bottom - 36,
            rect.width - 24,
            self.LAUNCH_H,
        )
        header_drag_rect = pygame.Rect(rect.x + 1, rect.y + 1, rect.width - 2, self.HEADER_H)
        resize_handle_rect = pygame.Rect(rect.right - 18, rect.bottom - 18, self.RESIZE_HANDLE, self.RESIZE_HANDLE)

        card["rect"] = rect
        card["image_rect"] = image_rect
        card["timeline_y"] = timeline_y
        card["launch_rect"] = launch_rect
        card["header_drag_rect"] = header_drag_rect
        card["resize_handle_rect"] = resize_handle_rect
        card["section_hitboxes"] = section_hitboxes
        card["year_hitboxes"] = [
            (year, pygame.Rect(year_x - 12, center_y - 12, 24, 48))
            for year, year_x in year_positions
        ]

    def _format_value(self, value):
        if isinstance(value, dict):
            return "\n".join(f"{k}: {v}" for k, v in value.items())
        if isinstance(value, list):
            return "\n".join(f"- {item}" for item in value) if value else "[]"
        return str(value)

    def draw_card(self, screen, font, card):
        rect = card["rect"]

        pygame.draw.rect(screen, (28, 30, 38), rect)
        pygame.draw.rect(screen, (170, 170, 170), rect, 1)

        header_rect = card["header_drag_rect"]
        pygame.draw.rect(screen, (34, 38, 48), header_rect)
        pygame.draw.line(screen, (110, 110, 120), (header_rect.x, header_rect.bottom), (header_rect.right, header_rect.bottom), 1)

        title_surface = font.render(card["title"], True, (245, 245, 245))
        subtitle_surface = font.render(card["subtitle"], True, (170, 170, 170))
        screen.blit(title_surface, (rect.x + 12, rect.y + 10))
        screen.blit(subtitle_surface, (rect.x + 12, rect.y + 30))

        self._draw_image_block(screen, font, card)
        self._draw_sections(screen, font, card)

        timeline_y = card["timeline_y"]
        left_x = rect.x + 20
        right_x = rect.right - 20
        center_y = timeline_y + 10
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

    def _draw_image_block(self, screen, font, card):
        image_rect = card["image_rect"]
        pygame.draw.rect(screen, (40, 42, 52), image_rect)
        pygame.draw.rect(screen, (120, 120, 120), image_rect, 1)

        canvas = ScaleHelper.suggest_canvas_from_dimensions(self.entity)
        dims_label = ScaleHelper.format_dimensions_label(self.entity)

        lines = [
            "No image",
            dims_label,
            f"Suggested canvas: {canvas['width']} x {canvas['height']}",
            "Import image later",
        ]

        current_y = image_rect.y + 8
        for line in lines:
            surf = font.render(line, True, (195, 195, 195))
            screen.blit(surf, (image_rect.x + 10, current_y))
            current_y += 18

    def _draw_sections(self, screen, font, card):
        section_map = self._sectioned_fields()

        current_y = card["image_rect"].bottom + 12
        content_left = card["rect"].x + 12
        text_width = card["rect"].width - 24

        for section_name in self.SECTION_ORDER:
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
                for line in rendered_value.splitlines() or [""]:
                    val_surface = font.render(line, True, (180, 180, 180))
                    screen.blit(val_surface, (content_left + 120, current_y))
                    current_y += 16

                current_y += 4