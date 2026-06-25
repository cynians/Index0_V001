import pygame


class KnowledgeTemplatePickerMixin:
    def _template_picker_row_height(self):
        line_h = self._font_line_height()
        return max(30, line_h + 12)

    def _template_picker_header_row_height(self):
        return max(24, self._font_line_height() + 8)

    def _template_picker_header_height(self):
        return (
            max(42, self._font_line_height() + 22)
            + self.BROWSER_SEARCH_H
            + self.BROWSER_CONTROL_GAP
            + self._template_picker_quick_row_height()
        )

    def _template_picker_quick_row_height(self):
        return 30 if self._template_picker_quick_templates() else 0

    def _template_picker_quick_templates(self):
        if self.template_picker_mode == "convert" or self.template_picker_search_query.strip():
            return []
        by_dataset = {
            template.get("dataset_name"): template
            for template in self.schema_entry_templates
        }
        templates = [
            by_dataset[dataset_name]
            for dataset_name in ("tasks", "ideas", "species", "cladistics")
            if dataset_name in by_dataset
        ]
        target = self._template_picker_relation_target()
        if target:
            templates = [
                template
                for template in templates
                if self._template_matches_relation_target(template, target)
            ]
        return templates

    def _template_picker_source_templates(self):
        return self._conversion_templates()

    def _template_picker_relation_target(self):
        if self.template_picker_mode not in {"create", "relation_create"}:
            return None
        context = self.template_picker_context if isinstance(self.template_picker_context, dict) else {}
        return context.get("target")

    def _template_matches_relation_target(self, template, target):
        if not target:
            return True
        if not hasattr(self, "_relation_target_candidates"):
            return True

        candidates = self._relation_target_candidates(target)
        if not candidates:
            return True

        names = set()
        for value in (
            template.get("dataset_name"),
            template.get("entity_type"),
            template.get("schema_name"),
            template.get("subclass_value"),
        ):
            normalized = self._normalize_schema_name(value)
            if not normalized:
                continue
            names.add(normalized)
            names.add(self._pluralize_name(normalized))
            names.add(self._singularize_name(normalized))
        return bool(candidates & names)

    def _template_search_blob(self, template):
        values = [
            template.get("label"),
            template.get("dataset_name"),
            template.get("entity_type"),
            template.get("schema_name"),
            template.get("subclass_field"),
            template.get("subclass_value"),
        ]
        return " ".join(str(value or "").lower() for value in values)

    def _filtered_template_picker_templates(self):
        templates = self._template_picker_source_templates()
        target = self._template_picker_relation_target()
        if target:
            templates = [
                template
                for template in templates
                if self._template_matches_relation_target(template, target)
            ]
        query = self.template_picker_search_query.strip().lower()
        if not query:
            return templates
        terms = [term for term in query.split() if term]
        return [
            template
            for template in templates
            if all(term in self._template_search_blob(template) for term in terms)
        ]

    def _template_picker_group_label(self, template):
        dataset_name = template.get("dataset_name")
        label = template.get("label") or self._schema_display_label(dataset_name)
        if template.get("subclass_field"):
            base = self._template_base_for(template)
            if base is not None:
                label = base.get("label") or label
            elif dataset_name:
                label = self._schema_display_label(dataset_name)
        return str(label or "Template")

    def _template_base_key(self, template):
        return (
            template.get("dataset_name"),
            template.get("entity_type"),
            template.get("schema_name"),
        )

    def _template_base_for(self, variant):
        variant_key = self._template_base_key(variant)
        for template in self.schema_entry_templates:
            if self._template_base_key(template) == variant_key:
                return template
        return None

    def _template_picker_option_width(self, label, available_width, font=None):
        label = str(label or "Template")
        if font is not None:
            label_w = font.size(label)[0]
        elif self.font_for_layout is not None:
            label_w = self.font_for_layout.size(label)[0]
        else:
            label_w = max(36, len(label) * 8)

        full_width_threshold = max(120, int(available_width * 0.58))
        if label_w > full_width_threshold:
            return available_width
        return max(84, min(available_width, label_w + 24))

    def _template_picker_hierarchical_rows(self, templates, available_width=None, font=None):
        groups = []
        by_key = {}

        for template in templates:
            key = self._template_base_key(template)
            group = by_key.get(key)
            if group is None:
                group = {
                    "label": self._template_picker_group_label(template),
                    "templates": [],
                }
                by_key[key] = group
                groups.append(group)
            if not template.get("subclass_field"):
                group["label"] = template.get("label") or group["label"]
            group["templates"].append(template)

        rows = []
        for group in groups:
            group_templates = sorted(
                group["templates"],
                key=lambda template: (
                    1 if template.get("subclass_field") else 0,
                    str(template.get("label", "")).lower(),
                    str(template.get("subclass_value", "")).lower(),
                ),
            )
            rows.append(
                {
                    "kind": "header",
                    "label": group["label"],
                    "template": None,
                }
            )
            if available_width is None:
                for template in group_templates:
                    rows.append(
                        {
                            "kind": "template_row",
                            "items": [
                                {
                                    "label": template.get("label", "Template"),
                                    "template": template,
                                }
                            ],
                        }
                    )
                continue

            current_items = []
            current_width = 0
            gap = 6
            for template in group_templates:
                label = template.get("label", "Template")
                option_w = self._template_picker_option_width(
                    label,
                    available_width,
                    font=font,
                )
                item = {
                    "label": label,
                    "template": template,
                    "width": option_w,
                }
                is_full_width = option_w >= available_width
                next_width = (
                    option_w
                    if not current_items
                    else current_width + gap + option_w
                )
                if is_full_width:
                    if current_items:
                        rows.append({"kind": "template_row", "items": current_items})
                        current_items = []
                        current_width = 0
                    rows.append({"kind": "template_row", "items": [item]})
                    continue

                if current_items and next_width > available_width:
                    rows.append({"kind": "template_row", "items": current_items})
                    current_items = [item]
                    current_width = option_w
                else:
                    current_items.append(item)
                    current_width = next_width

            if current_items:
                rows.append({"kind": "template_row", "items": current_items})

        return rows

    def _card_type_picker_visible_templates(self, card, templates):
        if not templates:
            return [], 0, 0

        card_rect = card.get("rect")
        type_label_rect = card.get("type_label_rect")
        if card_rect is None or type_label_rect is None:
            return [], 0, 0

        row_h = self.CARD_TYPE_PICKER_ROW_H
        available_below = max(row_h, card_rect.bottom - type_label_rect.bottom - 18)
        max_visible_rows = max(1, min(len(templates), (available_below - 38) // row_h))
        scroll = int(card.get("type_picker_scroll", 0) or 0)
        max_scroll = max(0, len(templates) - max_visible_rows)
        scroll = max(0, min(max_scroll, scroll))
        card["type_picker_scroll"] = scroll
        return templates[scroll:scroll + max_visible_rows], scroll, max_scroll

    def _build_template_picker_hitboxes(self):
        self.template_button_hitboxes = []
        self.template_quick_button_hitboxes = []
        self.template_picker_visible_rows = []
        self.template_picker_total_rows = 0
        self.template_picker_rect = None
        self.template_picker_search_rect = None

        if self.layout is None or not self.show_template_picker:
            return

        right_rect = self.layout["right_rect"]
        picker_w = min(360, right_rect.width - 24)
        source_templates = self._filtered_template_picker_templates()
        quick_templates = self._template_picker_quick_templates()
        quick_template_ids = {
            self._template_identity(template)
            for template in quick_templates
        }
        list_templates = [
            template
            for template in source_templates
            if self._template_identity(template) not in quick_template_ids
        ]
        content_w = picker_w - 24
        list_rows = self._template_picker_hierarchical_rows(
            list_templates,
            available_width=content_w,
            font=self.font_for_layout,
        )
        self.template_picker_total_rows = len(list_rows)
        max_picker_h = max(96, right_rect.height - 70)
        header_h = self._template_picker_header_height()
        row_h = self._template_picker_row_height()
        picker_h = min(
            max_picker_h,
            header_h + self.template_picker_total_rows * row_h + 8,
        )
        picker_x = right_rect.right - picker_w - 12
        picker_y = right_rect.y + 44
        self.template_picker_rect = pygame.Rect(picker_x, picker_y, picker_w, picker_h)
        search_y = picker_y + max(42, self._font_line_height() + 22)
        self.template_picker_search_rect = pygame.Rect(
            picker_x + 12,
            search_y,
            picker_w - 24,
            self.BROWSER_SEARCH_H,
        )

        if quick_templates:
            quick_y = self.template_picker_search_rect.bottom + self.BROWSER_CONTROL_GAP
            button_gap = 8
            button_w = min(
                96,
                (picker_w - 24 - button_gap) // max(1, len(quick_templates)),
            )
            button_x = picker_x + 12
            for template in quick_templates:
                button_rect = pygame.Rect(button_x, quick_y, button_w, 24)
                self.template_quick_button_hitboxes.append(
                    (template, template["label"], button_rect)
                )
                button_x += button_w + button_gap

        visible_rows = max(1, (picker_h - header_h - 8) // row_h)
        max_scroll = max(0, self.template_picker_total_rows - visible_rows)
        self.template_picker_scroll = max(
            0,
            min(max_scroll, self.template_picker_scroll),
        )

        button_y = picker_y + header_h
        self.template_picker_visible_rows = list_rows[
            self.template_picker_scroll:self.template_picker_scroll + visible_rows
        ]
        for row in self.template_picker_visible_rows:
            button_rect = pygame.Rect(picker_x + 12, button_y, picker_w - 24, row_h - 6)
            row["rect"] = button_rect
            if row.get("kind") == "template_row":
                item_x = button_rect.x
                for item in row.get("items", []):
                    item_w = max(
                        40,
                        min(
                            button_rect.width - (item_x - button_rect.x),
                            int(item.get("width", button_rect.width)),
                        ),
                    )
                    item_rect = pygame.Rect(
                        item_x,
                        button_rect.y,
                        item_w,
                        button_rect.height,
                    )
                    item["rect"] = item_rect
                    template = item.get("template")
                    if template is not None:
                        self.template_button_hitboxes.append(
                            (template, item.get("label", ""), item_rect)
                        )
                    item_x = item_rect.right + 6
            button_y += row_h
