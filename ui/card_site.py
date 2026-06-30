import pygame

from world.requirement_resolver import RequirementResolver


class CardSiteMixin:
    def _is_site_card(self):
        return (
            self.entity.get("location_class") == "site"
            or bool(str(self.entity.get("site_class") or "").strip())
        )

    def _is_site_mode(self):
        return self.active_tab == "site" and self._is_site_card()

    def _site_requirement_report(self):
        return RequirementResolver(self.world_model).site_report(self.entity)

    def _layout_site_content(self, card, content_left, current_y, text_width):
        font = card["layout_font"]
        line_h = self._table_line_height(font)
        card["site_section_rects"] = {}
        card["site_rows"] = []
        card["site_editable_field_hitboxes"] = []

        def add_section(label):
            nonlocal current_y
            rect = pygame.Rect(content_left, current_y, text_width, self.SECTION_HEADER_H)
            card["site_section_rects"][label] = rect
            current_y = rect.bottom + self.SECTION_GAP + 4
            return rect

        def add_row(kind, label, detail="", indent=0, satisfied=None, field_key=None):
            nonlocal current_y
            row_h = max(24, line_h + 8)
            rect = pygame.Rect(content_left + indent, current_y, max(60, text_width - indent), row_h)
            card["site_rows"].append({
                "kind": kind,
                "label": label,
                "detail": detail,
                "indent": indent,
                "satisfied": satisfied,
                "rect": rect,
                "field_key": field_key,
            })
            if field_key:
                card["site_editable_field_hitboxes"].append((field_key, rect))
            current_y = rect.bottom + 4

        add_section("Site")
        site_class = str(self.entity.get("site_class") or "site").strip()
        add_row("summary", f"Class: {site_class}")
        operators = self._relation_entity_ids(self.entity.get("operated_by"))
        if operators:
            add_row("summary", "Operated by", field_key="operated_by")
            for operator_id in operators:
                add_row("operator", self._entity_label_for_id(operator_id), operator_id, indent=18, field_key="operated_by")
        else:
            add_row("empty", "No operator assigned", field_key="operated_by")

        conditions = [str(value) for value in self.entity.get("site_conditions") or [] if str(value).strip()]
        if conditions:
            add_row("summary", "Conditions", field_key="site_conditions")
            for condition in conditions:
                add_row("condition", condition, indent=18, field_key="site_conditions")
        else:
            add_row("empty", "No site conditions assigned", field_key="site_conditions")

        add_section("Production Requirements")
        production_reports = (self._site_requirement_report() or {}).get("production", [])
        if not production_reports:
            add_row("empty", "No active production technology selected", field_key="active_production_technologies")
            return current_y

        for report in production_reports:
            status = "complete" if report.get("complete") else "missing requirements"
            add_row("technology", report.get("label", "Technology"), status, field_key="active_production_technologies")
            checks = report.get("checks") or []
            if not checks:
                add_row("check", "No requirements defined", indent=18, satisfied=True)
            for check in checks:
                add_row(
                    "check",
                    check.get("label", "Requirement"),
                    "ok" if check.get("satisfied") else "missing",
                    indent=18,
                    satisfied=bool(check.get("satisfied")),
                    field_key="assigned_vehicles" if "Vehicle tag:" in str(check.get("label", "")) else None,
                )

        return current_y + 4

    def _draw_site_content(self, screen, font, card):
        for label, rect in (card.get("site_section_rects") or {}).items():
            if rect is None:
                continue
            pygame.draw.rect(screen, (34, 38, 48), rect)
            pygame.draw.rect(screen, (86, 96, 116), rect, 1)
            screen.blit(font.render(label, True, (232, 236, 244)), (rect.x + 8, rect.y + 3))

        for row in card.get("site_rows", []):
            rect = row.get("rect")
            if rect is None:
                continue
            satisfied = row.get("satisfied")
            if satisfied is True:
                fill = (28, 50, 44)
                border = (94, 156, 132)
                marker = "OK"
            elif satisfied is False:
                fill = (58, 42, 42)
                border = (176, 116, 116)
                marker = "MISS"
            else:
                fill = (30, 34, 44)
                border = (82, 92, 112)
                marker = ""
            pygame.draw.rect(screen, fill, rect)
            pygame.draw.rect(screen, border, rect, 1)

            label_x = rect.x + 8
            if marker:
                marker_surface = font.render(marker, True, (230, 236, 238))
                screen.blit(marker_surface, (rect.x + 8, rect.y + 5))
                label_x += 46
            label = self._ellipsize_text(str(row.get("label") or ""), font, rect.width - 90)
            screen.blit(font.render(label, True, (236, 240, 248)), (label_x, rect.y + 5))
            detail = str(row.get("detail") or "").strip()
            if detail:
                detail_surface = font.render(
                    self._ellipsize_text(detail, font, 112),
                    True,
                    (166, 178, 198),
                )
                screen.blit(detail_surface, (rect.right - detail_surface.get_width() - 8, rect.y + 5))
