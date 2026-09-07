"""Screen-space renderer for the Formation Sim prototype."""

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
        screen.blit(self._text("Display scale", self.MUTED, size=13), (rect.x + 16, scale_y + 5))
        x = rect.x + 135
        for scale in sim.DISPLAY_SCALES:
            button = pygame.Rect(x, scale_y, 112, 28)
            active = sim.display_scale == scale
            pygame.draw.rect(screen, (61, 69, 48) if active else self.PANEL, button)
            pygame.draw.rect(screen, self.BORDER_ACTIVE if active else self.BORDER, button, 1)
            surface = self._text(scale.title(), self.TEXT if active else self.MUTED, size=13, bold=active)
            screen.blit(surface, surface.get_rect(center=button.center))
            hitboxes[f"scale:{scale}"] = button
            x += 118

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
