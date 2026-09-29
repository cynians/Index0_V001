"""Screen-space renderer for Formation Sim and its visual structure editor."""

from pathlib import Path

import pygame


class FormationRenderer:
    BACKGROUND = (10, 14, 20)
    PANEL = (18, 25, 34)
    PANEL_ALT = (22, 31, 42)
    BORDER = (92, 113, 132)
    BORDER_ACTIVE = (208, 185, 104)
    TEXT = (231, 235, 237)
    MUTED = (155, 170, 182)
    ACCENT = (145, 158, 91)
    GRID = (24, 37, 47)
    MANNEQUIN = (169, 178, 142)

    def __init__(self, app_view):
        self.app_view = app_view
        self._text_cache = {}
        self._image_cache = {}

    def _font(self, size=16, bold=False):
        return pygame.font.SysFont("consolas", size, bold=bold)

    def _text(self, value, color=None, size=16, bold=False):
        color = tuple(color or self.TEXT)
        key = (str(value), color, size, bold)
        surface = self._text_cache.get(key)
        if surface is None:
            surface = self._font(size, bold).render(str(value), True, color)
            self._text_cache[key] = surface
        return surface

    def draw(self, screen, sim):
        width, height = screen.get_size()
        sim.set_viewport(width, height)
        screen.fill(self.BACKGROUND)
        self._draw_grid(screen, pygame.Rect(0, 52, width, max(1, height - 52)))
        hitboxes = {}
        self._draw_header(screen, sim, width, hitboxes)

        margin = 20
        top = 135
        bottom = height - 20
        tree_rect = pygame.Rect(margin, top, 270, max(180, bottom - top))
        workspace_rect = pygame.Rect(
            tree_rect.right + 16,
            top,
            max(260, width - tree_rect.right - 36),
            max(180, bottom - top),
        )

        self._draw_tree(screen, sim, tree_rect, hitboxes)
        self._draw_workspace(screen, sim, workspace_rect, hitboxes)
        sim.set_hitboxes(hitboxes)

    def _draw_grid(self, screen, rect):
        for x in range(rect.left, rect.right, 24):
            pygame.draw.line(screen, self.GRID, (x, rect.top), (x, rect.bottom), 1)
        for y in range(rect.top, rect.bottom, 24):
            pygame.draw.line(screen, self.GRID, (rect.left, y), (rect.right, y), 1)

    def _draw_header(self, screen, sim, width, hitboxes):
        header = pygame.Rect(0, 52, width, 66)
        pygame.draw.rect(screen, (14, 20, 27), header)
        pygame.draw.line(screen, self.BORDER, (20, header.bottom), (width - 20, header.bottom), 1)
        screen.blit(self._text("FORMATION SIM", self.TEXT, size=25, bold=True), (28, 64))
        screen.blit(self._text(sim.root_name, self.MUTED, size=17), (30, 96))

        year_label = self._text("VIEW YEAR", self.MUTED, size=11, bold=True)
        year_x = max(300, width - 190)
        screen.blit(year_label, (year_x, 62))
        previous = pygame.Rect(year_x, 82, 28, 24)
        current = pygame.Rect(year_x + 32, 82, 86, 24)
        following = pygame.Rect(year_x + 122, 82, 28, 24)
        for button, label, active in (
            (previous, "−", False),
            (current, sim.year_buffer if sim.year_editing and sim.year_buffer else ("Type year" if sim.year_editing else str(sim.year)), True),
            (following, "+", False),
        ):
            pygame.draw.rect(screen, (61, 69, 48) if active else self.PANEL, button)
            pygame.draw.rect(screen, self.BORDER_ACTIVE if active else self.BORDER, button, 1)
            surface = self._text(label, self.TEXT if active else self.MUTED, size=13, bold=active)
            screen.blit(surface, surface.get_rect(center=button.center))
        hitboxes["year:previous"] = previous
        hitboxes["year:current"] = current
        hitboxes["year:next"] = following

    def _draw_tree(self, screen, sim, rect, hitboxes):
        pygame.draw.rect(screen, self.PANEL, rect)
        pygame.draw.rect(screen, self.BORDER, rect, 1)
        screen.blit(self._text("FORMATION", self.MUTED, size=13, bold=True), (rect.x + 14, rect.y + 12))

        row_h = 32
        parent_id = sim.get_parent_formation_id()
        y = rect.y + 40
        if parent_id:
            parent_button = pygame.Rect(rect.x + 8, y, rect.width - 16, 28)
            pygame.draw.rect(screen, self.PANEL_ALT, parent_button)
            pygame.draw.rect(screen, self.BORDER, parent_button, 1)
            parent_label = self._text("← To parent", self.TEXT, size=13, bold=True)
            screen.blit(parent_label, parent_label.get_rect(center=parent_button.center))
            hitboxes["parent"] = parent_button
            y += 36
        for node in sim._walk(sim.structure):
            if y + row_h > rect.bottom - 8:
                break
            depth = self._node_depth(sim.structure, node.get("id"))
            row = pygame.Rect(rect.x + 8 + depth * 18, y, rect.width - 16 - depth * 18, row_h)
            self._tree_row(
                screen,
                node,
                row,
                selected=sim.selected_node_id == node.get("id"),
                hovered=sim.hover_node_id == node.get("id"),
            )
            hitboxes[f"tree:{node['id']}"] = row
            y += row_h + (2 if depth == 0 else 0)

    def _node_depth(self, root, node_id, depth=0):
        if root.get("id") == node_id:
            return depth
        for child in root.get("children", []):
            found = self._node_depth(child, node_id, depth + 1)
            if found is not None:
                return found
        return None

    def _tree_row(self, screen, node, rect, selected, hovered):
        fill = self.PANEL_ALT if not selected else (63, 70, 49)
        if hovered and not selected:
            fill = (35, 53, 60)
        pygame.draw.rect(screen, fill, rect)
        pygame.draw.rect(screen, self.BORDER_ACTIVE if selected else self.BORDER, rect, 1)
        marker_x = rect.x + 10
        pygame.draw.rect(screen, self.ACCENT, (marker_x, rect.centery - 6, 12, 12), 1)
        label = self._text(node.get("label", "Formation"), self.TEXT, size=14, bold=selected)
        screen.blit(label, (marker_x + 22, rect.y + 7))

    def _draw_workspace(self, screen, sim, rect, hitboxes):
        pygame.draw.rect(screen, (13, 21, 29), rect)
        pygame.draw.rect(screen, self.BORDER, rect, 1)

        scale_y = rect.y + 14
        design_mode = getattr(sim, "workspace_mode", "inspect") == "design"

        # Inspect / Design workspace toggle (far left of the control row).
        mode_x = rect.x + 16
        for mode_key, label in (("inspect", "Inspect"), ("design", "Design")):
            button = pygame.Rect(mode_x, scale_y, 78, 28)
            active = design_mode == (mode_key == "design")
            pygame.draw.rect(screen, (61, 69, 48) if active else self.PANEL, button)
            pygame.draw.rect(screen, self.BORDER_ACTIVE if active else self.BORDER, button, 1)
            surface = self._text(label, self.TEXT if active else self.MUTED, size=13, bold=active)
            screen.blit(surface, surface.get_rect(center=button.center))
            hitboxes[f"workspace:{mode_key}"] = button
            mode_x = button.right + 8

        if design_mode:
            self._draw_design_view(screen, sim, rect, scale_y, hitboxes)
            if sim.creation_menu_active:
                self._draw_creation_menu(screen, sim, rect, scale_y, hitboxes)
            elif sim.faction_selection_active:
                self._draw_faction_picker(screen, sim, rect, scale_y, hitboxes)
            elif sim.blueprint_selection_active:
                self._draw_blueprint_picker(screen, sim, rect, scale_y, hitboxes)
            elif sim.creation_active:
                self._draw_visual_creation_prompt(screen, sim, rect, hitboxes)
            return

        screen.blit(self._text("Display scale", self.MUTED, size=13), (mode_x + 12, scale_y + 5))
        x = mode_x + 120
        for scale in sim.DISPLAY_SCALES:
            button = pygame.Rect(x, scale_y, 108, 28)
            active = sim.display_scale == scale
            pygame.draw.rect(screen, (61, 69, 48) if active else self.PANEL, button)
            pygame.draw.rect(screen, self.BORDER_ACTIVE if active else self.BORDER, button, 1)
            surface = self._text(scale.title(), self.TEXT if active else self.MUTED, size=13, bold=active)
            screen.blit(surface, surface.get_rect(center=button.center))
            hitboxes[f"scale:{scale}"] = button
            x += 114

        create_button = pygame.Rect(rect.right - 160, scale_y, 144, 28)
        pygame.draw.rect(screen, (61, 69, 48), create_button)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, create_button, 1)
        create_label = self._text("+ Add formation", self.TEXT, size=13, bold=True)
        screen.blit(create_label, create_label.get_rect(center=create_button.center))
        hitboxes["create"] = create_button

        content = rect.inflate(-32, -86)
        creation_offset = 0
        if sim.creation_active:
            creation_offset = 48
        elif sim.creation_menu_active:
            creation_offset = 174
        elif sim.faction_selection_active:
            creation_offset = 190
        elif sim.blueprint_selection_active:
            creation_offset = 210
        content.top += 56 + creation_offset
        if sim.display_scale == "personnel":
            self._draw_personnel_view(screen, sim, content)
        elif sim.display_scale == "formation":
            self._draw_formation_view(screen, sim, content)
        else:
            self._draw_aggregate_view(screen, sim, content, hitboxes)

        # Creation controls are transient overlays. Paint them after the
        # workspace so long faction/blueprint pickers remain visible over the
        # underlying overview cards.
        if sim.creation_menu_active:
            self._draw_creation_menu(screen, sim, rect, scale_y, hitboxes)
        elif sim.faction_selection_active:
            self._draw_faction_picker(screen, sim, rect, scale_y, hitboxes)
        elif sim.blueprint_selection_active:
            self._draw_blueprint_picker(screen, sim, rect, scale_y, hitboxes)
        elif sim.creation_active:
            prompt = pygame.Rect(rect.x + 16, scale_y + 28 + 12, rect.width - 32, 32)
            pygame.draw.rect(screen, self.PANEL, prompt)
            pygame.draw.rect(screen, self.BORDER_ACTIVE, prompt, 1)
            screen.blit(self._text("Name · click to place cursor", self.MUTED, size=11), (prompt.x, prompt.y - 16))
            faction_label = sim._faction_label(sim.creation_faction_id)
            if faction_label:
                screen.blit(self._text("Faction · " + faction_label, self.MUTED, size=11), (prompt.x + 210, prompt.y - 16))
            value = sim.creation_buffer or "Type a name, then press Enter"
            color = self.TEXT if sim.creation_buffer else self.MUTED
            screen.blit(self._text(value, color, size=14), (prompt.x + 10, prompt.y + 7))
            if sim.name_field_focused:
                prefix = self._text(sim.creation_buffer[:sim.creation_cursor], color, size=14)
                cursor_x = prompt.x + 10 + prefix.get_width()
                pygame.draw.line(screen, self.BORDER_ACTIVE, (cursor_x, prompt.y + 5), (cursor_x, prompt.bottom - 5), 2)
            screen.blit(self._text("Esc cancels", self.MUTED, size=12), (prompt.right - 82, prompt.y + 8))
            hitboxes["creation:name"] = prompt

    def _draw_design_view(self, screen, sim, rect, scale_y, hitboxes):
        self._draw_visual_designer(screen, sim, rect, scale_y, hitboxes)

    def _design_button(self, screen, hitboxes, key, label, x, y, width=None, active=True):
        width = width or self._text(label, size=11).get_width() + 16
        button = pygame.Rect(x, y, width, 24)
        pygame.draw.rect(screen, (55, 65, 48) if active else self.PANEL_ALT, button)
        pygame.draw.rect(screen, self.BORDER_ACTIVE if active else self.BORDER, button, 1)
        surface = self._text(label, self.TEXT, size=11)
        screen.blit(surface, surface.get_rect(center=button.center))
        if key:
            hitboxes[key] = button
        return button

    def _fit_design_text(self, value, width, size=12):
        original = str(value or "")
        value = original
        if self._text(value, size=size).get_width() <= width:
            return value
        while value and self._text(value + "…", size=size).get_width() > width:
            value = value[:-1]
        return value + "…"

    def _draw_visual_designer(self, screen, sim, rect, scale_y, hitboxes):
        model = sim.get_design_model()
        x = rect.x + 16
        tx = rect.x + 180
        for key, label in (
            ("design:add_personnel", "+ Role"),
            ("design:add_vehicle", "+ Vehicle"),
            ("design:add_child", "+ Child"),
            ("design:group", "Group selection"),
            ("design:delete_slots", "Delete selected"),
        ):
            if tx + 90 > rect.right - 15:
                break
            enabled = key not in ("design:group", "design:delete_slots") or bool(model["selection"])
            button = self._design_button(screen, hitboxes, key if enabled else None, label, tx, scale_y,
                                         active=enabled)
            tx = button.right + 7

        top = scale_y + 40
        screen.blit(self._text("FORMATION DESIGNER", self.TEXT, size=17, bold=True), (x, top))
        target = sim._find_node(model["action_target_id"]) or model["tree"]
        target_note = "ADD TO  " + (target.get("label") or "Formation")
        target_surface = self._text(self._fit_design_text(target_note, min(390, rect.width // 3), 10),
                                    self.ACCENT, size=10, bold=True)
        screen.blit(target_surface, (rect.right - target_surface.get_width() - 16, top + 6))
        screen.blit(self._text("Click a symbol to select · click its label or count to edit · click a formation to fold it",
                               self.MUTED, size=11), (x, top + 25))
        canvas = pygame.Rect(rect.x + 12, top + 49, rect.width - 24, rect.bottom - top - 61)
        pygame.draw.rect(screen, (11, 18, 25), canvas)
        pygame.draw.rect(screen, self.BORDER, canvas, 1)
        hitboxes["design:canvas"] = canvas
        clip = screen.get_clip()
        screen.set_clip(canvas.inflate(-2, -2))
        y = canvas.y + 15 - model["scroll"]

        def hit(key, area):
            visible = area.clip(canvas)
            if visible.width > 0 and visible.height > 0:
                hitboxes[key] = visible

        def visual_slot(slot, fid, area):
            if area.bottom < canvas.top or area.top > canvas.bottom:
                return
            key = f"slot:{fid}:{slot['id']}"
            selected = key in model["selection"]
            hovered = key == model["hover"]
            kind = slot["kind"]
            fill = (43, 53, 42) if selected else ((30, 48, 56) if hovered else (20, 31, 41))
            pygame.draw.rect(screen, fill, area, border_radius=3)
            pygame.draw.rect(screen, self.BORDER_ACTIVE if selected else (118, 150, 159) if hovered else self.BORDER,
                             area, 2 if selected else 1, border_radius=3)
            hit(key, area)
            label = self._fit_design_text(slot["role"], area.width - 57, 11)
            screen.blit(self._text(label, self.TEXT, size=11, bold=True), (area.x + 9, area.y + 8))
            badge = self._text(f"×{slot['count']}", self.BORDER_ACTIVE, size=12, bold=True)
            screen.blit(badge, (area.right - badge.get_width() - 9, area.y + 8))
            hit(f"design:edit:{fid}:role:{slot['id']}", pygame.Rect(area.x + 7, area.y + 5, area.width - 63, 23))
            hit(f"design:edit:{fid}:count:{slot['id']}", pygame.Rect(area.right - 60, area.y + 4, 55, 25))

            if kind == "vehicle":
                vehicle = sim._vehicle_node(slot.get("vehicle_id")) if slot.get("vehicle_id") else None
                image = self._load_side_image(vehicle.get("side_image")) if vehicle else None
                count = slot["count"]
                shown = min(3, max(1, count))
                icon_w = min(73, (area.width - 24) // shown)
                start = area.centerx - (shown * icon_w + (shown - 1) * 5) // 2
                for index in range(shown):
                    icon = pygame.Rect(start + index * (icon_w + 5), area.y + 33, icon_w, 48)
                    if image is not None:
                        factor = min(icon.width / max(1, image.get_width()), icon.height / max(1, image.get_height()))
                        scaled = pygame.transform.smoothscale(image, (max(1, int(image.get_width() * factor)),
                                                               max(1, int(image.get_height() * factor))))
                        screen.blit(scaled, scaled.get_rect(center=icon.center))
                    else:
                        vehicle_type = (vehicle.get("vehicle_class") if vehicle else slot["role"]).casefold()
                        self._draw_vehicle_silhouette(screen, icon, vehicle_type)
                crew_roles = sim.design_vehicle_crew(slot)
                crew_per_vehicle = sum(int(role.get("count", 0)) for role in crew_roles)
                for index in range(min(6, crew_per_vehicle)):
                    self._draw_person_silhouette(screen, area.x + 12 + index * 18, area.y + 96,
                                                 scale=0.60, color=self.MANNEQUIN)
                crew_text = ", ".join(f"{role['role']} {role['count']}" for role in crew_roles) or "Set crew roles…"
                screen.blit(self._text(self._fit_design_text("CREW  " + crew_text, area.width - 18, 10),
                                       self.MUTED, size=10), (area.x + 9, area.bottom - 24))
                hit(f"design:edit:{fid}:crew_roles:{slot['id']}", pygame.Rect(area.x + 7, area.bottom - 28,
                                                                             area.width - 14, 24))
            else:
                count = slot["count"]
                shown = min(5, count)
                if shown:
                    spacing = min(31, (area.width - 30) // shown)
                    start = area.centerx - (shown - 1) * spacing // 2 - 10
                    for index in range(shown):
                        self._draw_person_silhouette(screen, start + index * spacing, area.y + 56,
                                                     scale=1.05, color=self.MANNEQUIN,
                                                     command=bool(slot.get("is_command")) and index == 0)
                if count > shown:
                    remainder = self._text(f"+{count - shown}", self.ACCENT, size=11, bold=True)
                    screen.blit(remainder, (area.right - remainder.get_width() - 10, area.y + 91))
                rank = slot.get("rank") or "Set rank…"
                screen.blit(self._text(self._fit_design_text(rank, area.width - 18, 10), self.MUTED, size=10),
                            (area.x + 9, area.bottom - 24))
                hit(f"design:edit:{fid}:rank:{slot['id']}", pygame.Rect(area.x + 7, area.bottom - 28,
                                                                       area.width - 14, 24))

        sizes = {}
        support_cache = {}
        coverage_cache = {}

        def measure_node(node, depth):
            fid = node.get("entity_id") or node.get("id")
            width = canvas.right - 12 - (canvas.x + 12 + min(depth * 29, 112))
            support_cache[fid] = sim.design_parent_support(fid, node)
            coverage_cache[fid] = sim.design_crew_coverage(node)
            height = 106 if support_cache[fid] else 91
            if fid in model["collapsed"]:
                sizes[fid] = height + 13
                return height + 13
            height += 24
            slots = sorted(node.get("roster_slots") or [], key=lambda item: 0 if item["kind"] == "vehicle" else 1)
            if slots:
                available = width - 23
                used = 0
                rows = 1
                for slot in slots:
                    card_w = min(227 if slot["kind"] == "vehicle" else 190, available)
                    if used and used + card_w > available:
                        rows += 1
                        used = 0
                    used += card_w + 10
                height += rows * 164 + (rows - 1) * 10 + 8
            else:
                height += 98
            if coverage_cache[fid]:
                height += 24
            items = node.get("blueprint_items") if node.get("formation_kind") == "blueprint" else []
            if items or node.get("equipment"):
                height += 32
            height += 12
            for child in node.get("children") or []:
                height += measure_node(child, depth + 1)
            height += 9
            sizes[fid] = height
            return height

        measure_node(model["tree"], 0)

        def draw_node(node, depth=0):
            nonlocal y
            fid = node.get("entity_id") or node.get("id")
            if not fid:
                return
            subtree_height = sizes.get(fid, 0)
            if y + subtree_height < canvas.top or y > canvas.bottom:
                y += subtree_height
                return
            left = canvas.x + 12 + min(depth * 29, 112)
            right = canvas.right - 12
            width = right - left
            personnel, vehicles, crew = sim.design_direct_totals(node)
            coverage = coverage_cache.get(fid, [])
            filled = sum(role["assigned"] for role in coverage)
            children = node.get("children") or []
            support = support_cache.get(fid)
            header_h = 106 if support else 91
            header = pygame.Rect(left, y, width, header_h)
            pygame.draw.rect(screen, (37, 48, 43) if depth == 0 else (30, 43, 52), header)
            group_key = f"group:{fid}"
            group_selected = group_key in model["selection"]
            pygame.draw.rect(screen, self.BORDER_ACTIVE if depth == 0 or group_selected else self.BORDER,
                             header, 2 if group_selected else 1)
            symbol = pygame.Rect(left + 10, y + 11, 36, 31)
            pygame.draw.rect(screen, (128, 151, 140), symbol)
            pygame.draw.rect(screen, self.BORDER_ACTIVE if group_selected else (16, 35, 46), symbol,
                             2 if group_selected else 1)
            pygame.draw.line(screen, (16, 35, 46), symbol.topleft, symbol.bottomright, 2)
            pygame.draw.line(screen, (16, 35, 46), symbol.topright, symbol.bottomleft, 2)
            if depth:
                hit(group_key, pygame.Rect(symbol.x - 4, symbol.y - 5, symbol.width + 8, symbol.height + 10))
            marker = "▸" if fid in model["collapsed"] else "▾"
            title = self._fit_design_text(node.get("label", "Formation"), max(120, width - 350), 15)
            screen.blit(self._text(marker + "  " + title, self.TEXT, size=15, bold=True), (left + 55, y + 9))
            owner = node.get("faction_label") or "Unassigned"
            summary = f"{personnel} personnel  ·  {vehicles} vehicles  ·  crew {filled}/{crew}  ·  owner {owner}"
            screen.blit(self._text(self._fit_design_text(summary, width - 315, 11), self.MUTED, size=11),
                        (left + 55, y + 32))
            doctrine = node.get("doctrine") or "Add doctrine…"
            screen.blit(self._text(self._fit_design_text("DOCTRINE  " + doctrine, width - 300, 10),
                                   self.ACCENT if node.get("doctrine") else self.MUTED, size=10),
                        (left + 55, y + 51))
            hit(f"design:collapse:{fid}", pygame.Rect(left + 50, y + 1, max(50, width - 318), 41))
            hit(f"design:edit:{fid}:doctrine:_", pygame.Rect(left + 53, y + 47, max(80, width - 360), 23))
            action_x = right - 258
            for action, label, button_w in (("role", "+ Role", 76), ("vehicle", "+ Vehicle", 82),
                                             ("equipment", "+ Equipment", 91)):
                button = self._design_button(screen, {}, None, label, action_x, y + 10, button_w)
                hit(f"design:add:{action}:{fid}", button)
                action_x = button.right + 4
            child = self._design_button(screen, {}, None, "+ Formation", right - 203, y + 41, 99)
            hit(f"design:add:child:{fid}", child)
            structure = self._design_button(screen, {}, None, "Structure ▾", right - 99, y + 41, 91,
                                            active=model["structure_menu"] == fid)
            hit(f"design:structure:button:{fid}", structure)
            if model["selection"]:
                place = self._design_button(screen, {}, None, "Place selected here", right - 332, y + 41, 125)
                hit(f"design:place_here:{fid}", place)
            if support:
                source, roles = support
                note = f"SUPPORT VIA {source}: {', '.join(roles)}"
                screen.blit(self._text(self._fit_design_text(note, width - 65, 10), self.ACCENT, size=10),
                            (left + 55, y + 68))
            y += header_h
            if fid in model["collapsed"]:
                y += 13
                return

            # A bracket ties the local visual roster to its formation header.
            bracket_y = y + 14
            pygame.draw.line(screen, self.BORDER, (left + 28, y), (left + 28, bracket_y), 2)
            pygame.draw.line(screen, self.BORDER, (left + 28, bracket_y), (right - 8, bracket_y), 2)
            y += 24
            slots = node.get("roster_slots") or []
            card_left = left + 15
            card_right = right - 8
            cx = card_left
            row_top = y
            row_h = 164
            for slot in sorted(slots, key=lambda item: 0 if item["kind"] == "vehicle" else 1):
                card_w = min(227 if slot["kind"] == "vehicle" else 190, card_right - card_left)
                if cx + card_w > card_right and cx > card_left:
                    cx = card_left
                    row_top += row_h + 10
                card = pygame.Rect(cx, row_top, card_w, row_h)
                pygame.draw.line(screen, self.BORDER, (card.centerx, bracket_y), (card.centerx, card.y), 1)
                visual_slot(slot, fid, card)
                cx = card.right + 10
            if not slots:
                ghost = pygame.Rect(card_left, row_top, min(320, card_right - card_left), 90)
                pygame.draw.rect(screen, self.GRID, ghost, 1, border_radius=3)
                screen.blit(self._text("No personnel or vehicles yet", self.MUTED, size=11),
                            (ghost.x + 12, ghost.y + 20))
                screen.blit(self._text("Use + Role or + Vehicle above", self.MUTED, size=10),
                            (ghost.x + 12, ghost.y + 44))
                y = ghost.bottom + 8
            else:
                y = row_top + row_h + 8

            if coverage:
                need = ", ".join(f"{role['role']} {role['assigned']}/{role['required']}"
                                 for role in coverage)
                screen.blit(self._text(self._fit_design_text("CREW REQUIRED  " + need, width - 35, 10),
                                       self.ACCENT, size=10), (left + 16, y + 3))
                y += 24
            item_nodes = node.get("blueprint_items") if node.get("formation_kind") == "blueprint" else []
            equipment = [item.get("label") for item in item_nodes or []] + list(node.get("equipment") or [])
            if equipment:
                ex = left + 15
                screen.blit(self._text("EQUIPMENT", self.MUTED, size=10, bold=True), (ex, y + 7))
                ex += 93
                for label in equipment[:6]:
                    badge_w = min(self._text(label, size=10).get_width() + 17, 155)
                    if ex + badge_w > right - 9:
                        break
                    badge = pygame.Rect(ex, y + 1, badge_w, 24)
                    pygame.draw.rect(screen, (40, 48, 44), badge, border_radius=3)
                    pygame.draw.rect(screen, self.BORDER, badge, 1, border_radius=3)
                    screen.blit(self._text(self._fit_design_text(label, badge_w - 12, 10), self.TEXT, size=10),
                                (badge.x + 6, badge.y + 6))
                    ex = badge.right + 5
                y += 32
            y += 12

            if children:
                branch_x = left + 12
                first_y = y + 24
                last_y = first_y
                for child in children:
                    child_y = y
                    child_left = canvas.x + 12 + min((depth + 1) * 29, 112)
                    pygame.draw.line(screen, self.BORDER, (branch_x, child_y + 26),
                                     (child_left, child_y + 26), 2)
                    last_y = child_y + 26
                    draw_node(child, depth + 1)
                pygame.draw.line(screen, self.BORDER, (branch_x, first_y), (branch_x, last_y), 2)
            y += 9

        draw_node(model["tree"])
        sim.design_content_height = max(0, y + model["scroll"] - canvas.y + 8)
        screen.set_clip(clip)
        if model["structure_menu"]:
            self._draw_visual_structure_menu(screen, sim, model["structure_menu"], canvas, hitboxes)
        if model["notice"]:
            notice = pygame.Rect(canvas.x + 12, canvas.bottom - 31, canvas.width - 24, 22)
            pygame.draw.rect(screen, (43, 49, 39), notice)
            screen.blit(self._text(self._fit_design_text(model["notice"], notice.width - 12, 11),
                                   self.ACCENT, size=11), (notice.x + 6, notice.y + 4))
        if model["edit"]:
            edit_rect = pygame.Rect(canvas.x + 14, canvas.bottom - 43, canvas.width - 28, 32)
            pygame.draw.rect(screen, (51, 57, 43), edit_rect)
            pygame.draw.rect(screen, self.BORDER_ACTIVE, edit_rect, 1)
            field = model["edit"][1].replace("_", " ")
            hint = "  (Role:count, Role:count)" if field == "crew roles" else ""
            content = f"{field.upper()}: {model['edit_buffer']}{hint}  ↵ save · Esc cancel"
            screen.blit(self._text(self._fit_design_text(content, edit_rect.width - 18, 12), self.TEXT, size=12),
                        (edit_rect.x + 9, edit_rect.y + 8))
        if model["catalog"]:
            self._draw_design_catalog(screen, sim, canvas, hitboxes)
        if model["group_naming"]:
            self._draw_visual_group_prompt(screen, model, canvas, hitboxes)
        if model["target_picker"]:
            self._draw_visual_target_picker(screen, sim, canvas, hitboxes)
        if model["owner_picker"]:
            self._draw_visual_owner_picker(screen, sim, canvas, hitboxes)
        if model["attach_target"]:
            self._draw_visual_attach_picker(screen, sim, canvas, hitboxes)

    def _draw_visual_structure_menu(self, screen, sim, formation_id, canvas, hitboxes):
        anchor = hitboxes.get(f"design:structure:button:{formation_id}")
        if anchor is None:
            return
        node = sim._find_node(formation_id)
        if node is None:
            return
        parent = sim._find_parent(formation_id)
        grandparent = sim._find_parent(parent["id"]) if parent else None
        siblings = parent.get("children", []) if parent else []
        index = next((i for i, child in enumerate(siblings) if child["id"] == formation_id), -1)
        options = [
            ("rename", "Rename formation", True),
            ("child", "Add subordinate", True),
            ("attach", "Attach existing formation…", True),
            ("owner", "Change faction owner…", bool(sim._faction_options())),
            ("place", "Place selection here", bool(sim.canvas_selection)),
            ("choose", "Choose parent for selection…", bool(sim.canvas_selection)),
            ("move", "Change command parent…", bool(parent)),
            ("promote", "Move one level up", bool(grandparent)),
            ("up", "Move earlier", index > 0),
            ("down", "Move later", index >= 0 and index < len(siblings) - 1),
            ("fold", "Fold descendants", bool(node.get("children"))),
            ("open", "Open descendants", bool(node.get("children"))),
        ]
        menu_h = 12 + len(options) * 29
        menu_x = min(max(canvas.x + 8, anchor.right - 220), canvas.right - 236)
        menu_y = anchor.bottom + 3
        if menu_y + menu_h > canvas.bottom - 6:
            menu_y = max(canvas.y + 6, anchor.y - menu_h - 3)
        menu = pygame.Rect(menu_x, menu_y, 230, menu_h)
        pygame.draw.rect(screen, self.PANEL, menu)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, menu, 2)
        for index, (action, label, enabled) in enumerate(options):
            row = pygame.Rect(menu.x + 6, menu.y + 6 + index * 29, menu.width - 12, 26)
            pygame.draw.rect(screen, self.PANEL_ALT if enabled else (16, 23, 30), row)
            text_color = self.TEXT if enabled else self.MUTED
            screen.blit(self._text(label, text_color, size=11), (row.x + 8, row.y + 6))
            if enabled:
                hitboxes[f"design:structure:action:{action}:{formation_id}"] = row

    def _draw_visual_group_prompt(self, screen, model, canvas, hitboxes):
        prompt = pygame.Rect(canvas.centerx - 250, canvas.centery - 74, 500, 148)
        pygame.draw.rect(screen, self.PANEL, prompt)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, prompt, 2)
        screen.blit(self._text("NAME THE NEW FORMATION", self.TEXT, size=15, bold=True),
                    (prompt.x + 14, prompt.y + 12))
        screen.blit(self._text("Selected elements will share this command parent.", self.MUTED, size=11),
                    (prompt.x + 14, prompt.y + 39))
        field = pygame.Rect(prompt.x + 14, prompt.y + 62, prompt.width - 28, 31)
        pygame.draw.rect(screen, (11, 18, 25), field)
        pygame.draw.rect(screen, self.BORDER, field, 1)
        screen.blit(self._text(model["group_name"] or "Type a formation name…",
                               self.TEXT if model["group_name"] else self.MUTED, size=12),
                    (field.x + 8, field.y + 7))
        if model["notice"]:
            screen.blit(self._text(self._fit_design_text(model["notice"], prompt.width - 30, 10),
                                   self.ACCENT, size=10), (prompt.x + 14, prompt.y + 100))
        self._design_button(screen, hitboxes, "design:group:cancel", "Cancel", prompt.right - 180,
                            prompt.bottom - 31, 76)
        self._design_button(screen, hitboxes, "design:group:create", "Create", prompt.right - 96,
                            prompt.bottom - 31, 82)

    def _draw_visual_target_picker(self, screen, sim, canvas, hitboxes):
        options = sim.design_target_options()
        picker_w = min(540, canvas.width - 40)
        picker_h = min(440, canvas.height - 40, max(190, 128 + min(9, len(options)) * 34))
        picker = pygame.Rect(canvas.centerx - picker_w // 2, canvas.centery - picker_h // 2,
                             picker_w, picker_h)
        pygame.draw.rect(screen, self.PANEL, picker)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, picker, 2)
        action = sim.design_target_picker[0]
        title = "CHOOSE A COMMAND PARENT" if action == "move_group" else "PLACE SELECTED ELEMENTS UNDER…"
        screen.blit(self._text(title, self.TEXT, size=15, bold=True), (picker.x + 14, picker.y + 12))
        screen.blit(self._text("Structural parent only; faction owner is retained.", self.MUTED, size=11),
                    (picker.x + 14, picker.y + 38))
        close = self._design_button(screen, hitboxes, "design:target:close", "Close", picker.right - 70,
                                    picker.y + 8, 57)
        query = pygame.Rect(picker.x + 14, picker.y + 65, picker.width - 28, 30)
        pygame.draw.rect(screen, (11, 18, 25), query)
        pygame.draw.rect(screen, self.BORDER, query, 1)
        screen.blit(self._text(sim.design_target_query or "Search formations or ancestors…",
                               self.TEXT if sim.design_target_query else self.MUTED, size=12),
                    (query.x + 8, query.y + 7))
        screen.blit(self._text(f"{len(options)} possible parents", self.MUTED, size=10),
                    (picker.x + 14, query.bottom + 7))
        y = query.bottom + 24
        for option in options[:9]:
            row = pygame.Rect(picker.x + 14, y, picker.width - 28, 31)
            if row.bottom > picker.bottom - 12:
                break
            pygame.draw.rect(screen, self.PANEL_ALT, row)
            pygame.draw.rect(screen, self.BORDER, row, 1)
            indent = min(option["depth"] * 13, 65)
            label = self._fit_design_text(option["label"], row.width - indent - 25, 11)
            screen.blit(self._text(label, self.TEXT, size=11, bold=True), (row.x + 8 + indent, row.y + 3))
            if option["path"]:
                path = self._fit_design_text(option["path"], row.width - indent - 25, 9)
                screen.blit(self._text(path, self.MUTED, size=9), (row.x + 8 + indent, row.y + 17))
            hitboxes[f"design:target:item:{option['id']}"] = row
            y += 34
        if not options:
            screen.blit(self._text("No eligible command parents. Try another search.", self.MUTED, size=11),
                        (picker.x + 14, y + 6))

    def _draw_visual_owner_picker(self, screen, sim, canvas, hitboxes):
        options = sim.design_owner_options()
        picker_w = min(500, canvas.width - 40)
        picker_h = min(380, canvas.height - 40, max(190, 116 + min(8, len(options)) * 31))
        picker = pygame.Rect(canvas.centerx - picker_w // 2, canvas.centery - picker_h // 2,
                             picker_w, picker_h)
        pygame.draw.rect(screen, self.PANEL, picker)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, picker, 2)
        formation = sim._find_node(sim.design_owner_picker_id) or {}
        screen.blit(self._text("CHANGE FACTION OWNER", self.TEXT, size=15, bold=True),
                    (picker.x + 14, picker.y + 12))
        screen.blit(self._text(self._fit_design_text(formation.get("label"), picker.width - 90, 11),
                               self.MUTED, size=11), (picker.x + 14, picker.y + 38))
        self._design_button(screen, hitboxes, "design:owner:close", "Close", picker.right - 70,
                            picker.y + 8, 57)
        query = pygame.Rect(picker.x + 14, picker.y + 65, picker.width - 28, 30)
        pygame.draw.rect(screen, (11, 18, 25), query)
        pygame.draw.rect(screen, self.BORDER, query, 1)
        screen.blit(self._text(sim.design_owner_query or "Search factions…",
                               self.TEXT if sim.design_owner_query else self.MUTED, size=12),
                    (query.x + 8, query.y + 7))
        y = query.bottom + 12
        for option in options[:8]:
            row = pygame.Rect(picker.x + 14, y, picker.width - 28, 28)
            if row.bottom > picker.bottom - 10:
                break
            pygame.draw.rect(screen, self.PANEL_ALT, row)
            pygame.draw.rect(screen, self.BORDER, row, 1)
            selected = option["id"] == formation.get("faction_id")
            marker = "✓ " if selected else ""
            screen.blit(self._text(self._fit_design_text(marker + option["label"], row.width - 20, 11),
                                   self.TEXT, size=11), (row.x + 9, row.y + 6))
            hitboxes[f"design:owner:item:{option['id']}"] = row
            y += 31

    def _draw_visual_attach_picker(self, screen, sim, canvas, hitboxes):
        options = sim.design_attach_options()
        picker_w = min(540, canvas.width - 40)
        picker_h = min(430, canvas.height - 40, max(190, 128 + min(8, len(options)) * 36))
        picker = pygame.Rect(canvas.centerx - picker_w // 2, canvas.centery - picker_h // 2,
                             picker_w, picker_h)
        pygame.draw.rect(screen, self.PANEL, picker)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, picker, 2)
        target = sim._find_node(sim.design_attach_target_id) or {}
        screen.blit(self._text("ATTACH EXISTING FORMATION", self.TEXT, size=15, bold=True),
                    (picker.x + 14, picker.y + 12))
        label = self._fit_design_text("COMMAND PARENT  " + (target.get("label") or "Formation"),
                                      picker.width - 100, 11)
        screen.blit(self._text(label, self.MUTED, size=11), (picker.x + 14, picker.y + 38))
        self._design_button(screen, hitboxes, "design:attach:close", "Close", picker.right - 70,
                            picker.y + 8, 57)
        query = pygame.Rect(picker.x + 14, picker.y + 65, picker.width - 28, 30)
        pygame.draw.rect(screen, (11, 18, 25), query)
        pygame.draw.rect(screen, self.BORDER, query, 1)
        screen.blit(self._text(sim.design_attach_query or "Search formations or faction owners…",
                               self.TEXT if sim.design_attach_query else self.MUTED, size=12),
                    (query.x + 8, query.y + 7))
        screen.blit(self._text(f"{len(options)} available formations", self.MUTED, size=10),
                    (picker.x + 14, query.bottom + 7))
        y = query.bottom + 24
        for option in options[:8]:
            row = pygame.Rect(picker.x + 14, y, picker.width - 28, 32)
            if row.bottom > picker.bottom - 10:
                break
            pygame.draw.rect(screen, self.PANEL_ALT, row)
            pygame.draw.rect(screen, self.BORDER, row, 1)
            screen.blit(self._text(self._fit_design_text(option["label"], row.width - 20, 11),
                                   self.TEXT, size=11, bold=True), (row.x + 8, row.y + 3))
            screen.blit(self._text(self._fit_design_text("Owner: " + option["owner"], row.width - 20, 9),
                                   self.MUTED, size=9), (row.x + 8, row.y + 18))
            hitboxes[f"design:attach:item:{option['id']}"] = row
            y += 36
        if not options:
            screen.blit(self._text("No eligible formations. Try another search.", self.MUTED, size=11),
                        (picker.x + 14, y + 5))

    def _draw_visual_creation_prompt(self, screen, sim, rect, hitboxes):
        prompt = pygame.Rect(rect.centerx - min(280, rect.width // 2 - 18),
                             rect.centery - 94, min(560, rect.width - 36), 188)
        pygame.draw.rect(screen, self.PANEL, prompt)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, prompt, 2)
        parent = sim._find_node(sim.creation_parent_id) or {}
        owner = sim._faction_label(sim.creation_faction_id) or "Choose an owner"
        screen.blit(self._text("CREATE SUBORDINATE FORMATION", self.TEXT, size=15, bold=True),
                    (prompt.x + 16, prompt.y + 14))
        screen.blit(self._text(self._fit_design_text("COMMAND PARENT  " + parent.get("label", "Formation"),
                                                   prompt.width - 32, 11), self.MUTED, size=11),
                    (prompt.x + 16, prompt.y + 44))
        screen.blit(self._text(self._fit_design_text("FACTION OWNER  " + owner, prompt.width - 32, 11),
                               self.ACCENT, size=11), (prompt.x + 16, prompt.y + 64))
        name = pygame.Rect(prompt.x + 16, prompt.y + 94, prompt.width - 32, 33)
        pygame.draw.rect(screen, (11, 18, 25), name)
        pygame.draw.rect(screen, self.BORDER, name, 1)
        screen.blit(self._text(sim.creation_buffer or "Type any name: flotilla, convoy, regiment, section…",
                               self.TEXT if sim.creation_buffer else self.MUTED, size=12),
                    (name.x + 9, name.y + 8))
        hitboxes["creation:name"] = name
        screen.blit(self._text("Enter creates · Esc cancels", self.MUTED, size=11),
                    (prompt.x + 16, prompt.bottom - 38))

    def _draw_vehicle_silhouette(self, screen, area, vehicle_type):
        color = (133, 166, 171)
        dark = (31, 48, 55)
        cx, cy = area.center
        if any(word in vehicle_type for word in ("helicopter", "rotor", "chopper")):
            pygame.draw.ellipse(screen, color, (cx - 26, cy - 7, 43, 18))
            pygame.draw.polygon(screen, color, [(cx + 12, cy), (cx + 31, cy - 4), (cx + 31, cy + 3)])
            pygame.draw.line(screen, color, (cx - 29, cy - 13), (cx + 24, cy - 13), 3)
            pygame.draw.line(screen, color, (cx - 4, cy - 12), (cx - 4, cy - 6), 2)
            pygame.draw.line(screen, color, (cx - 22, cy + 13), (cx + 16, cy + 13), 2)
            pygame.draw.line(screen, color, (cx - 18, cy + 5), (cx - 15, cy + 13), 2)
            pygame.draw.line(screen, color, (cx + 11, cy + 5), (cx + 13, cy + 13), 2)
        elif any(word in vehicle_type for word in ("tank", "armored", "armoured", "apc")):
            pygame.draw.ellipse(screen, dark, (cx - 28, cy + 4, 56, 13))
            pygame.draw.polygon(screen, color, [(cx - 27, cy + 6), (cx - 21, cy - 7),
                                                (cx + 18, cy - 7), (cx + 29, cy + 6)])
            pygame.draw.ellipse(screen, color, (cx - 11, cy - 15, 24, 13))
            pygame.draw.line(screen, color, (cx + 8, cy - 11), (cx + 34, cy - 11), 3)
            for dx in (-19, -8, 4, 16):
                pygame.draw.circle(screen, color, (cx + dx, cy + 10), 3)
        elif any(word in vehicle_type for word in ("ship", "boat", "vessel")):
            pygame.draw.polygon(screen, color, [(cx - 31, cy + 1), (cx + 30, cy + 1),
                                                (cx + 19, cy + 14), (cx - 23, cy + 14)])
            pygame.draw.rect(screen, color, (cx - 12, cy - 10, 26, 11))
            pygame.draw.line(screen, color, (cx, cy - 19), (cx, cy - 10), 2)
        else:
            pygame.draw.rect(screen, color, (cx - 27, cy - 9, 47, 19), border_radius=4)
            pygame.draw.polygon(screen, color, [(cx + 20, cy - 8), (cx + 32, cy - 3),
                                                (cx + 32, cy + 10), (cx + 20, cy + 10)])
            for dx in (-17, 21):
                pygame.draw.circle(screen, dark, (cx + dx, cy + 11), 5)

    def _draw_person_silhouette(self, screen, x, y, scale=1.0, color=None, command=False):
        """Readable, reusable personnel symbol for roster counts on the map."""
        color = tuple(color or self.MANNEQUIN)
        trim = (80, 95, 82)
        x, y = int(x), int(y)

        def pt(dx, dy):
            return x + int(dx * scale), y + int(dy * scale)

        head = pt(10, 6)
        pygame.draw.circle(screen, color, head, max(3, int(5 * scale)))
        pygame.draw.polygon(screen, color, [pt(4, 13), pt(16, 13), pt(20, 22), pt(0, 22)])
        pygame.draw.rect(screen, color, (*pt(5, 17), max(2, int(10 * scale)), max(2, int(15 * scale))))
        pygame.draw.line(screen, trim, pt(5, 29), pt(15, 29), max(1, int(scale)))
        pygame.draw.line(screen, color, pt(8, 31), pt(6, 43), max(2, int(3 * scale)))
        pygame.draw.line(screen, color, pt(13, 31), pt(15, 43), max(2, int(3 * scale)))
        if command:
            pygame.draw.polygon(screen, self.BORDER_ACTIVE,
                                [pt(10, -5), pt(15, 0), pt(10, 3), pt(5, 0)], 1)

    def _draw_design_catalog(self, screen, sim, canvas, hitboxes):
        catalog = pygame.Rect(canvas.x + 20, canvas.y + 20, min(600, canvas.width - 40), min(370, canvas.height - 40))
        pygame.draw.rect(screen, self.PANEL, catalog)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, catalog, 2)
        kind = sim.design_catalog[1]
        screen.blit(self._text(f"ADD {kind.upper()}  ·  type to search", self.TEXT, size=14, bold=True),
                    (catalog.x + 12, catalog.y + 12))
        close = self._design_button(screen, hitboxes, "design:catalog:close", "Close", catalog.right - 70, catalog.y + 7, 58)
        query = pygame.Rect(catalog.x + 12, catalog.y + 42, catalog.width - 24, 30)
        pygame.draw.rect(screen, (10, 17, 23), query)
        pygame.draw.rect(screen, self.BORDER, query, 1)
        screen.blit(self._text(sim.design_catalog_query or "Search the catalog…", self.TEXT if sim.design_catalog_query else self.MUTED, size=12),
                    (query.x + 9, query.y + 7))
        y = query.bottom + 9
        if kind == "vehicle":
            custom = self._design_button(screen, hitboxes, "design:catalog:custom", "+ Custom vehicle", catalog.x + 12, y, 145)
            y = custom.bottom + 7
        options = sim.design_catalog_options()
        for option in options[:8]:
            row = pygame.Rect(catalog.x + 12, y, catalog.width - 24, 26)
            if row.bottom > catalog.bottom - 10:
                break
            pygame.draw.rect(screen, self.PANEL_ALT, row)
            pygame.draw.rect(screen, self.BORDER, row, 1)
            screen.blit(self._text(self._fit_design_text(option["label"], row.width - 20, 12), self.TEXT, size=12),
                        (row.x + 8, row.y + 5))
            hitboxes[f"design:catalog:item:{option['id']}"] = row
            y += 29
        if not options:
            screen.blit(self._text("No matches", self.MUTED, size=12), (catalog.x + 12, y + 6))

    def _selected_node(self, sim):
        return sim._find_node(sim.selected_node_id) or sim.structure

    def _draw_aggregate_view(self, screen, sim, rect, hitboxes=None):
        self._section_title(screen, "Formation overview", rect)
        self._draw_metadata(screen, sim, rect)
        children = sim.structure.get("children", [])
        vehicles = sim.structure.get("vehicles", [])
        blueprints = sim.structure.get("blueprints", [])
        blueprint_items = sim.structure.get("blueprint_items", [])
        is_blueprint = sim.structure.get("formation_kind") == "blueprint"
        if not children and not vehicles and not blueprints and not blueprint_items:
            self._draw_empty_state(screen, rect, "No subordinate formations recorded yet.")
            return
        next_y = rect.y + 82
        if children:
            columns = max(1, len(children))
            card_w = max(180, (rect.width - (columns - 1) * 14) // columns)
            card_h = min(174, max(150, rect.height // 3))
            for index, node in enumerate(children):
                card = pygame.Rect(rect.x + index * (card_w + 14), next_y, card_w, card_h)
                self._aggregate_card(screen, card, node)
            next_y += card_h + 28
        if vehicles and next_y + 70 < rect.bottom:
            self._draw_vehicle_section(screen, vehicles, rect, next_y)
            next_y += 210
        if blueprints and next_y + 70 < rect.bottom:
            self._draw_blueprint_section(screen, sim, blueprints, rect, next_y, hitboxes or {})
        if is_blueprint and next_y + 70 < rect.bottom:
            self._draw_blueprint_design(screen, sim, blueprint_items, rect, next_y, hitboxes or {})

    def _draw_formation_view(self, screen, sim, rect):
        selected = self._selected_node(sim)
        self._section_title(screen, selected.get("label", "Formation"), rect)
        children = selected.get("children", [])
        vehicles = selected.get("vehicles", [])
        if not children and not vehicles:
            self._draw_empty_state(screen, rect, "No subordinate formations recorded; personnel view available.")
            self._draw_personnel_rows(screen, rect.move(0, 76), selected, rows=3)
            return

        next_y = rect.y + 46
        if children:
            gap = 14
            card_h = max(120, min(170, (rect.height - 54 - gap * 2) // max(1, min(3, len(children)))))
            for index, child in enumerate(children[:3]):
                card = pygame.Rect(rect.x, next_y + index * (card_h + gap), rect.width, card_h)
                self._formation_card(screen, card, child)
            next_y += min(3, len(children)) * (card_h + gap) + 12
        if vehicles and next_y + 70 < rect.bottom:
            self._draw_vehicle_section(screen, vehicles, rect, next_y)

    def _draw_personnel_view(self, screen, sim, rect):
        selected = self._selected_node(sim)
        self._section_title(screen, selected.get("label", "Formation"), rect)
        self._draw_personnel_rows(screen, rect.move(0, 46), selected, rows=4)
        if selected.get("vehicles"):
            self._draw_vehicle_section(screen, selected["vehicles"], rect, rect.y + 190)

    def _section_title(self, screen, title, rect):
        screen.blit(self._text(title, self.TEXT, size=18, bold=True), (rect.x, rect.y + 8))
        pygame.draw.line(screen, self.BORDER, (rect.x, rect.y + 36), (rect.right, rect.y + 36), 1)

    def _draw_metadata(self, screen, sim, rect):
        root = sim.structure
        start = root.get("start_year")
        end = root.get("end_year")
        years = ""
        if start is not None or end is not None:
            years = f"{start if start is not None else '?'}–{end if end is not None else '?'}"
        parent_names = []
        for parent_id in root.get("parents", []):
            parent = sim.world_model.get_entity(parent_id) if sim.world_model else None
            if isinstance(parent, dict):
                parent_names.append(parent.get("pretty_name") or parent.get("name") or parent_id)
        context = " · ".join(part for part in (years, ", ".join(parent_names)) if part)
        if context:
            screen.blit(self._text(context, self.MUTED, size=13), (rect.x, rect.y + 46))
        equipment = root.get("equipment", [])
        faction = root.get("faction_label")
        if faction:
            screen.blit(self._text("Faction: " + faction, self.MUTED, size=13), (rect.x, rect.y + 62))
        if equipment:
            equipment_y = rect.y + (78 if faction else 62)
            screen.blit(self._text("Equipment: " + ", ".join(equipment), self.MUTED, size=13), (rect.x, equipment_y))

    def _draw_empty_state(self, screen, rect, message):
        screen.blit(self._text(message, self.MUTED, size=14), (rect.x, rect.y + 54))

    def _draw_vehicle_section(self, screen, vehicles, rect, top):
        screen.blit(self._text("Assigned vehicles", self.MUTED, size=13, bold=True), (rect.x, top))
        gap = 14
        columns = max(1, min(4, len(vehicles)))
        if rect.width < columns * 190:
            columns = min(2, len(vehicles))
        card_w = max(180, (rect.width - (columns - 1) * gap) // columns)
        rows = (min(4, len(vehicles)) + columns - 1) // columns
        available_height = rect.height - (top - rect.y) - 28
        card_h = min(230, max(110, (available_height - (rows - 1) * gap) // max(1, rows)))
        for index, vehicle in enumerate(vehicles[:4]):
            column = index % columns
            row = index // columns
            card = pygame.Rect(
                rect.x + column * (card_w + gap),
                top + 24 + row * (card_h + gap),
                card_w,
                card_h,
            )
            self._vehicle_card(screen, card, vehicle)

    def _draw_blueprint_section(self, screen, sim, blueprints, rect, top, hitboxes):
        screen.blit(self._text("Formation blueprints", self.MUTED, size=13, bold=True), (rect.x, top))
        gap = 14
        columns = max(1, min(3, len(blueprints)))
        card_w = max(210, (rect.width - (columns - 1) * gap) // columns)
        card_h = min(154, max(112, rect.height - (top - rect.y) - 28))
        for index, blueprint in enumerate(blueprints[:3]):
            card = pygame.Rect(
                rect.x + index * (card_w + gap),
                top + 24,
                card_w,
                card_h,
            )
            self._blueprint_card(screen, card, blueprint)
            hitboxes[f"blueprint:{blueprint.get('id')}"] = card

    def _blueprint_card(self, screen, rect, blueprint):
        available = blueprint.get("is_available", True)
        border = self.BORDER_ACTIVE if available else self.BORDER
        pygame.draw.rect(screen, self.PANEL, rect)
        pygame.draw.rect(screen, border, rect, 1)
        title_color = self.TEXT if available else self.MUTED
        screen.blit(self._text(blueprint.get("label", "Blueprint"), title_color, size=16, bold=True), (rect.x + 12, rect.y + 10))
        screen.blit(self._text("Blueprint", self.ACCENT if available else self.MUTED, size=12), (rect.x + 12, rect.y + 35))
        if blueprint.get("faction_label"):
            screen.blit(self._text(blueprint["faction_label"], self.MUTED, size=11), (rect.x + 12, rect.y + 50))
        if not available:
            screen.blit(self._text("Outside view year", (197, 153, 96), size=11), (rect.x + 100, rect.y + 35))
        item_y = rect.y + (68 if blueprint.get("faction_label") else 62)
        items = [item for item in blueprint.get("items", []) if item.get("is_available", True)]
        if not items:
            screen.blit(self._text("No equipment selected", self.MUTED, size=12), (rect.x + 12, item_y))
            return
        for item in items[:4]:
            item_color = self.TEXT if item.get("is_available", True) else (197, 153, 96)
            marker = "•" if item.get("is_available", True) else "!"
            screen.blit(self._text(f"{marker} {item.get('label', 'Item')}", item_color, size=12), (rect.x + 12, item_y))
            item_y += 18

    def _draw_creation_menu(self, screen, sim, rect, top, hitboxes):
        menu = pygame.Rect(rect.x + 16, top + 42, min(470, rect.width - 32), 126)
        pygame.draw.rect(screen, self.PANEL, menu)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, menu, 1)
        screen.blit(self._text("Create", self.TEXT, size=14, bold=True), (menu.x + 12, menu.y + 10))
        options = (
            ("creation:new_formation", "Create new formation"),
            ("creation:from_blueprint", "Create from blueprint"),
            ("creation:new_blueprint", "Create new blueprint"),
        )
        for index, (key, label) in enumerate(options):
            button = pygame.Rect(menu.x + 12 + index * 148, menu.y + 44, 138, 52)
            pygame.draw.rect(screen, self.PANEL_ALT, button)
            pygame.draw.rect(screen, self.BORDER, button, 1)
            surface = self._text(label, self.TEXT, size=11)
            screen.blit(surface, surface.get_rect(center=button.center))
            hitboxes[key] = button

    def _draw_faction_picker(self, screen, sim, rect, top, hitboxes):
        options = sim._filtered_faction_options()
        visible_count = 13
        maximum_offset = max(0, len(options) - visible_count)
        offset = max(0, min(maximum_offset, getattr(sim, "faction_picker_offset", 0)))
        visible = options[offset:offset + visible_count]
        menu = pygame.Rect(rect.x + 16, top + 42, min(520, rect.width - 32), 84 + max(1, len(visible)) * 30)
        pygame.draw.rect(screen, self.PANEL, menu)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, menu, 1)
        title = "Choose the formation faction"
        if sim.creation_mode == "blueprint":
            title = "Choose the blueprint faction"
        if len(options) > visible_count:
            title += f"  ({offset + 1}–{min(offset + visible_count, len(options))} of {len(options)})"
        screen.blit(self._text(title, self.TEXT, size=14, bold=True), (menu.x + 12, menu.y + 10))
        search = pygame.Rect(menu.x + 12, menu.y + 36, menu.width - 24, 25)
        pygame.draw.rect(screen, self.PANEL_ALT, search)
        pygame.draw.rect(screen, self.BORDER_ACTIVE if sim.faction_search_active else self.BORDER, search, 1)
        search_label = sim.faction_search_buffer or "Search factions..."
        search_color = self.TEXT if sim.faction_search_buffer else self.MUTED
        screen.blit(self._text(search_label, search_color, size=12), (search.x + 8, search.y + 5))
        hitboxes["creation:faction:search"] = search
        if not options:
            screen.blit(self._text("No matching factions.", self.MUTED, size=12), (menu.x + 12, menu.y + 70))
            return
        for index, faction in enumerate(visible):
            button = pygame.Rect(menu.x + 12, menu.y + 70 + index * 30, menu.width - 24, 25)
            pygame.draw.rect(screen, self.PANEL_ALT, button)
            pygame.draw.rect(screen, self.BORDER, button, 1)
            label = faction.get("pretty_name") or faction.get("name") or faction.get("id")
            screen.blit(self._text(label, self.TEXT, size=12), (button.x + 8, button.y + 5))
            hitboxes[f"creation:faction:{faction.get('id')}"] = button

    def _draw_blueprint_picker(self, screen, sim, rect, top, hitboxes):
        options = sim._blueprint_options(sim.creation_parent_id)
        menu = pygame.Rect(rect.x + 16, top + 42, min(620, rect.width - 32), 72 + max(1, len(options)) * 30)
        pygame.draw.rect(screen, self.PANEL, menu)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, menu, 1)
        screen.blit(self._text("Choose a blueprint", self.TEXT, size=14, bold=True), (menu.x + 12, menu.y + 10))
        if not options:
            screen.blit(self._text("No Formation Blueprints available yet.", self.MUTED, size=12), (menu.x + 12, menu.y + 40))
            return
        for index, blueprint in enumerate(options):
            button = pygame.Rect(menu.x + 12, menu.y + 38 + index * 30, menu.width - 24, 25)
            pygame.draw.rect(screen, self.PANEL_ALT, button)
            pygame.draw.rect(screen, self.BORDER, button, 1)
            screen.blit(self._text(blueprint.get("label", "Blueprint"), self.TEXT, size=12), (button.x + 8, button.y + 5))
            hitboxes[f"creation:blueprint:{blueprint.get('id')}"] = button

    def _draw_blueprint_design(self, screen, sim, items, rect, top, hitboxes):
        screen.blit(self._text("Blueprint editor", self.MUTED, size=13, bold=True), (rect.x, top))
        personnel = sim.structure.get("personnel")
        personnel_label = "—" if personnel is None else str(personnel)
        screen.blit(self._text("Personnel", self.TEXT, size=14, bold=True), (rect.x, top + 25))
        screen.blit(self._text(personnel_label if not sim.personnel_editing else (sim.personnel_buffer or "Type a number"), self.TEXT, size=15), (rect.x + 82, top + 24))
        for key, label, offset, width in (
            ("blueprint:personnel:minus", "−100", 150, 58),
            ("blueprint:personnel:plus", "+100", 214, 58),
            ("blueprint:personnel:set", "Set", 278, 58),
        ):
            button = pygame.Rect(rect.x + offset, top + 20, width, 26)
            pygame.draw.rect(screen, self.PANEL_ALT, button)
            pygame.draw.rect(screen, self.BORDER, button, 1)
            surface = self._text(label, self.TEXT, size=11)
            screen.blit(surface, surface.get_rect(center=button.center))
            hitboxes[key] = button

        tab_top = top + 62
        for key, label, offset in (
            ("blueprint:section:organization", "Organization", 0),
            ("blueprint:section:equipment", "Equipment", 118),
        ):
            tab = pygame.Rect(rect.x + offset, tab_top, 108, 25)
            active = (
                sim.blueprint_editor_section == "organization"
                and key.endswith("organization")
            ) or (
                sim.blueprint_editor_section == "equipment"
                and key.endswith("equipment")
            )
            pygame.draw.rect(screen, (61, 69, 48) if active else self.PANEL_ALT, tab)
            pygame.draw.rect(screen, self.BORDER_ACTIVE if active else self.BORDER, tab, 1)
            surface = self._text(label, self.TEXT if active else self.MUTED, size=11, bold=active)
            screen.blit(surface, surface.get_rect(center=tab.center))
            hitboxes[key] = tab

        section_top = tab_top + 38
        if sim.blueprint_editor_section == "organization":
            self._draw_blueprint_organization(screen, sim, rect, section_top, hitboxes)
            return

        item_top = section_top
        screen.blit(self._text("Selected equipment", self.MUTED, size=12, bold=True), (rect.x, item_top))
        gap = 14
        columns = max(1, min(3, len(items) or 1))
        card_w = max(210, (rect.width - (columns - 1) * gap) // columns)
        card_h = 72
        visible_items = [item for item in items if item.get("is_available", True)]
        for index, item in enumerate(visible_items[:6]):
            card = pygame.Rect(rect.x + index * (card_w + gap), item_top + 22, card_w, card_h)
            pygame.draw.rect(screen, self.PANEL, card)
            pygame.draw.rect(screen, self.BORDER_ACTIVE, card, 1)
            screen.blit(self._text(f"• {item.get('label', 'Item')}", self.TEXT, size=14, bold=True), (card.x + 12, card.y + 12))
            category_label = str(item.get("category_label") or item.get("kind") or "item").replace("_", " ")
            screen.blit(self._text(category_label, self.MUTED, size=12), (card.x + 12, card.y + 38))
        if not visible_items:
            screen.blit(self._text("No equipment selected for this view.", self.MUTED, size=12), (rect.x, item_top + 28))

        catalog_top = item_top + 106
        screen.blit(self._text("Available equipment", self.MUTED, size=12, bold=True), (rect.x, catalog_top))
        catalog = []
        for entity in sim._item_entities():
            item = sim._item_node(entity.get("id"))
            if item is not None and item.get("is_available", True):
                catalog.append(item)
        for index, item in enumerate(catalog[:12]):
            column = index % 3
            row = index // 3
            button = pygame.Rect(rect.x + column * (card_w + gap), catalog_top + 22 + row * 28, card_w, 24)
            selected = any(existing.get("id") == item.get("id") for existing in visible_items)
            pygame.draw.rect(screen, (61, 69, 48) if selected else self.PANEL_ALT, button)
            pygame.draw.rect(screen, self.BORDER_ACTIVE if selected else self.BORDER, button, 1)
            marker = "✓ " if selected else "+ "
            screen.blit(self._text(marker + item.get("label", "Item"), self.TEXT, size=11), (button.x + 7, button.y + 5))
            hitboxes[f"blueprint:item:{item.get('id')}"] = button

    def _draw_blueprint_organization(self, screen, sim, rect, top, hitboxes):
        """Draw the generic child-formation manager for a blueprint."""
        add = pygame.Rect(rect.right - 170, top - 4, 154, 26)
        pygame.draw.rect(screen, (61, 69, 48), add)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, add, 1)
        label = self._text("+ Add child blueprint", self.TEXT, size=11, bold=True)
        screen.blit(label, label.get_rect(center=add.center))
        hitboxes["blueprint:organization:add"] = add

        screen.blit(self._text("Organization", self.TEXT, size=14, bold=True), (rect.x, top))
        screen.blit(
            self._text("Child formations in this design; labels remain flexible.", self.MUTED, size=11),
            (rect.x, top + 23),
        )
        children = sim.structure.get("children", [])
        if not children:
            screen.blit(self._text("No subordinate blueprint formations yet.", self.MUTED, size=13), (rect.x, top + 65))
            return

        row_top = top + 52
        row_h = 54
        for index, child in enumerate(children[:8]):
            row = pygame.Rect(rect.x, row_top + index * (row_h + 8), rect.width, row_h)
            pygame.draw.rect(screen, self.PANEL, row)
            pygame.draw.rect(screen, self.BORDER, row, 1)
            child_label = child.get("label", "Formation")
            pygame.draw.rect(screen, self.ACCENT, pygame.Rect(row.x + 10, row.y + 17, 8, 8))
            screen.blit(self._text(child_label, self.TEXT, size=14, bold=True), (row.x + 28, row.y + 8))
            child_faction = child.get("faction_label") or "Faction not recorded"
            details = (
                f"{child_faction} · "
                f"{child.get('personnel') if child.get('personnel') is not None else '—'} personnel · "
                f"{len(child.get('blueprint_items', []))} equipment"
            )
            screen.blit(self._text(details, self.MUTED, size=11), (row.x + 28, row.y + 30))
            if child.get("entity_id"):
                hitboxes[f"blueprint:organization:{child.get('id')}"] = row

    def _vehicle_card(self, screen, rect, vehicle):
        pygame.draw.rect(screen, self.PANEL, rect)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, rect, 1)
        label = vehicle.get("label", "Vehicle")
        screen.blit(self._text(label, self.TEXT, size=16, bold=True), (rect.x + 12, rect.y + 10))
        vehicle_class = str(vehicle.get("vehicle_class") or "vehicle").replace("_", " ")
        screen.blit(self._text(vehicle_class, self.MUTED, size=12), (rect.x + 12, rect.y + 34))
        if not vehicle.get("is_available", True):
            screen.blit(self._text("Outside view year", (197, 153, 96), size=11), (rect.x + 12, rect.y + 48))

        image_rect = pygame.Rect(rect.x + 12, rect.y + 58, min(170, rect.width // 3), rect.height - 70)
        pygame.draw.rect(screen, (12, 18, 24), image_rect)
        pygame.draw.rect(screen, self.BORDER, image_rect, 1)
        side_image = self._load_side_image(vehicle.get("side_image"))
        if side_image is None:
            missing = self._text("No side image", self.MUTED, size=11)
            screen.blit(missing, missing.get_rect(center=image_rect.center))
        else:
            source_w, source_h = side_image.get_size()
            scale = min(image_rect.width / max(1, source_w), image_rect.height / max(1, source_h))
            scaled = pygame.transform.smoothscale(
                side_image,
                (max(1, int(source_w * scale)), max(1, int(source_h * scale))),
            )
            screen.blit(scaled, scaled.get_rect(center=image_rect.center))

        crew_x = image_rect.right + 16
        crew_y = rect.y + 62
        screen.blit(self._text("Crew by role", self.MUTED, size=12, bold=True), (crew_x, crew_y))
        crew_y += 22
        for role in vehicle.get("crew_roles", []):
            if crew_y + 30 > rect.bottom:
                break
            role_label = str(role.get("role") or "Crew")
            count = role.get("count", 0)
            screen.blit(self._text(f"{role_label}: {count}", self.TEXT, size=12), (crew_x, crew_y))
            for sample in range(min(6, max(0, int(count or 0)))):
                self._draw_mannequin(screen, (crew_x + sample * 16 + 6, crew_y + 22), scale=0.45)
            crew_y += 34

    def _load_side_image(self, image_reference):
        """Load a vehicle-provided side image; never synthesize a replacement."""
        reference = str(image_reference or "").strip()
        if not reference or reference.startswith("placeholder:"):
            return None
        path = Path(reference)
        candidates = [path] if path.is_absolute() else [Path.cwd() / path, path]
        for candidate in candidates:
            key = str(candidate.resolve())
            if key in self._image_cache:
                return self._image_cache[key]
            if not candidate.exists():
                continue
            try:
                surface = pygame.image.load(str(candidate)).convert_alpha()
            except (OSError, pygame.error):
                return None
            self._image_cache[key] = surface
            return surface
        return None

    def _personnel_count(self, node):
        value = node.get("personnel")
        try:
            if value is not None:
                return max(0, int(value))
        except (TypeError, ValueError):
            pass
        child_counts = [self._personnel_count(child) for child in node.get("children", [])]
        known_counts = [count for count in child_counts if count is not None]
        return sum(known_counts) if known_counts else None

    def _aggregate_card(self, screen, rect, node):
        pygame.draw.rect(screen, self.PANEL, rect)
        pygame.draw.rect(screen, self.BORDER_ACTIVE, rect, 1)
        screen.blit(self._text(node.get("label", "Formation"), self.TEXT, size=18, bold=True), (rect.x + 16, rect.y + 16))
        screen.blit(self._text("Aggregated personnel", self.MUTED, size=13), (rect.x + 16, rect.y + 52))
        count = self._personnel_count(node)
        screen.blit(self._text(str(count) if count is not None else "—", self.TEXT, size=30, bold=True), (rect.x + 16, rect.y + 78))
        child_count = len(node.get("children", []))
        descriptor = "subordinate formation" if child_count == 1 else "subordinate formations"
        screen.blit(self._text(f"{child_count} {descriptor}", self.MUTED, size=13), (rect.x + 16, rect.y + 120))
        if node.get("is_unlinked"):
            screen.blit(self._text("Unlinked card reference", (197, 153, 96), size=12), (rect.x + 16, rect.y + 148))

    def _formation_card(self, screen, rect, node):
        pygame.draw.rect(screen, self.PANEL, rect)
        pygame.draw.rect(screen, self.BORDER, rect, 1)
        screen.blit(self._text(node.get("label", "Formation"), self.TEXT, size=16, bold=True), (rect.x + 14, rect.y + 12))
        screen.blit(self._text(f"Personnel: {self._personnel_count(node)}", self.MUTED, size=12), (rect.x + 14, rect.y + 38))
        self._draw_personnel_rows(screen, rect.move(0, 52), node, rows=2)

    def _draw_personnel_rows(self, screen, rect, node, rows=3):
        count = self._personnel_count(node)
        # No source card currently carries individual strength. Keep the
        # requested mannequin language visible without presenting a made-up
        # headcount as fact.
        if count is None:
            count = min(6, max(1, len(node.get("children", [])) * 2))
        count = min(count, 72)
        columns = max(1, min(12, (rect.width - 24) // 30))
        for index in range(count):
            row = index // columns
            if row >= rows:
                break
            column = index % columns
            self._draw_mannequin(screen, (rect.x + 16 + column * 30, rect.y + 26 + row * 38), scale=0.75)

    def _draw_mannequin(self, screen, center, scale=1.0):
        """Draw a deliberately simple placeholder for future person images."""
        x, y = int(center[0]), int(center[1])
        head_r = max(2, int(round(3 * scale)))
        body_w = max(4, int(round(7 * scale)))
        body_h = max(7, int(round(11 * scale)))
        leg_h = max(4, int(round(7 * scale)))
        pygame.draw.circle(screen, self.MANNEQUIN, (x, y - body_h // 2 - head_r - 1), head_r)
        body = pygame.Rect(x - body_w // 2, y - body_h // 2, body_w, body_h)
        pygame.draw.rect(screen, self.MANNEQUIN, body)
        width = max(1, int(round(scale)))
        pygame.draw.line(screen, self.MANNEQUIN, (x, body.bottom), (x - max(1, body_w // 3), body.bottom + leg_h), width)
        pygame.draw.line(screen, self.MANNEQUIN, (x, body.bottom), (x + max(1, body_w // 3), body.bottom + leg_h), width)
