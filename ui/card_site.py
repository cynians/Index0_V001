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

        add_section("Layout & Access")
        structures = self._relation_entity_ids(self.entity.get("layout_structures"))
        if structures:
            add_row("summary", f"Structures ({len(structures)})", field_key="layout_structures")
            for structure_id in structures:
                add_row(
                    "structure",
                    self._entity_label_for_id(structure_id),
                    structure_id,
                    indent=18,
                    field_key="layout_structures",
                )
        else:
            building_class = str(self.entity.get("building_class") or "").strip()
            if building_class:
                add_row("summary", f"Building: {building_class}", field_key="building_class")

        openings = [value for value in self.entity.get("openings") or [] if isinstance(value, dict)]
        if openings:
            add_row("summary", f"Passable openings ({len(openings)})", field_key="openings")
            for opening in openings:
                opening_class = str(opening.get("opening_class") or "opening")
                side = str(opening.get("side") or "wall")
                width = opening.get("width")
                detail = f"{side} wall" + (f" · {width} m" if width not in (None, "") else "")
                add_row("opening", opening_class.title(), detail, indent=18, field_key="openings")

        layers = [str(value) for value in self.entity.get("representational_layers") or [] if str(value).strip()]
        if layers:
            add_row("summary", "Map layers", ", ".join(layers), field_key="representational_layers")

        residents = self._relation_entity_ids(self.entity.get("resident_people"))
        if residents:
            add_section("Residents")
            for resident_id in residents:
                resident = self.world_model.get_entity(resident_id) or {}
                sex = str(resident.get("sex") or "person").strip()
                add_row(
                    "resident",
                    self._entity_label_for_id(resident_id),
                    sex,
                    field_key="resident_people",
                )

        present_pops = self._relation_entity_ids(self.entity.get("present_pops"))
        authored_visitors = self._relation_entity_ids(self.entity.get("authored_visitors"))
        visitor_scenarios = [
            value for value in self.entity.get("visitor_scenarios") or []
            if isinstance(value, dict)
        ]
        if present_pops or authored_visitors or visitor_scenarios:
            add_section("Population & Encounters")
            for pop_id in present_pops:
                pop = self.world_model.get_entity(pop_id) or {}
                count = pop.get("population_count", pop.get("size", "?"))
                representatives = pop.get("representative_count", 3)
                add_row(
                    "population",
                    self._entity_label_for_id(pop_id),
                    f"{count} people · {representatives} full representatives",
                    field_key="present_pops",
                )
            for visitor_id in authored_visitors:
                visitor = self.world_model.get_entity(visitor_id) or {}
                add_row(
                    "resident",
                    self._entity_label_for_id(visitor_id),
                    str(visitor.get("visit_purpose") or "authored visitor"),
                    field_key="authored_visitors",
                )
            for scenario in visitor_scenarios:
                names = scenario.get("names") or [scenario.get("name") or scenario.get("id") or "Visitor"]
                add_row(
                    "population",
                    ", ".join(str(name) for name in names),
                    f"{scenario.get('person_class', 'visitor')} · {scenario.get('simulation_detail', 'lightweight')}",
                    field_key="visitor_scenarios",
                )

        inventory = [value for value in self.entity.get("inventory_items") or [] if isinstance(value, dict)]
        if inventory:
            add_section("Stored Items")
            for entry in inventory:
                item_id = str(entry.get("item") or entry.get("entity") or "").strip()
                quantity = entry.get("quantity", 0)
                unit = str(entry.get("unit") or "units").strip()
                add_row(
                    "inventory",
                    self._entity_label_for_id(item_id) if item_id else "Unspecified item",
                    f"{quantity:g} {unit}" if isinstance(quantity, (int, float)) else f"{quantity} {unit}",
                    field_key="inventory_items",
                )

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
