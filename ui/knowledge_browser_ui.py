import pygame

from ui.ui_types import UIButton
from ui.card import EntityCard


class KnowledgeBrowserUI:
    """
    Knowledge-layer workspace UI.

    Responsibilities:
    * build repository browser rows
    * build card canvas cards
    * track knowledge-layer hitboxes
    * draw the knowledge-layer shell
    * handle knowledge-layer specific clicks
    * provide a scrollable / navigable card canvas
    """

    LINE_HEIGHT = 20

    def __init__(self):
        self.layout = None
        self.browser_items = []
        self.browser_hitboxes = []
        self.browser_toggle_hitboxes = []
        self.cards = []

        self.world_model = None
        self.selected_entity_id = None
        self.repository_scope_entity_id = None
        self.repository_scope_label = None
        self.header_button = None
        self.browser_scroll = 0

        self.canvas_offset_x = 0
        self.canvas_offset_y = 0
        self.canvas_content_width = 0
        self.canvas_content_height = 0

        self.active_card_drag_id = None
        self.active_card_resize_id = None
        self.card_drag_mouse_offset = (0, 0)
        self.card_resize_start_mouse = None
        self.card_resize_start_size = None

        self.browser_tree_state = {
            "systems": {
                "system_sol": True,
                "body_sol": True,
            }
        }

    def reset(self):
        """
        Reset transient rebuild state, but keep persistent browser/card state.
        """
        self.layout = None
        self.browser_items = []
        self.browser_hitboxes = []
        self.browser_toggle_hitboxes = []
        self.world_model = None
        self.repository_scope_entity_id = None
        self.repository_scope_label = None
        self.header_button = None

    def _build_layout(self, app_width, app_height):
        outer_margin = 16
        header_h = 54
        inner_gap = 14
        left_ratio = 0.30

        content_x = outer_margin
        content_y = outer_margin + header_h
        content_w = app_width - outer_margin * 2
        content_h = app_height - content_y - outer_margin

        left_w = int(content_w * left_ratio)
        right_w = content_w - left_w - inner_gap

        left_rect = pygame.Rect(content_x, content_y, left_w, content_h)
        right_rect = pygame.Rect(content_x + left_w + inner_gap, content_y, right_w, content_h)

        return {
            "header_rect": pygame.Rect(outer_margin, outer_margin, content_w, header_h),
            "left_rect": left_rect,
            "right_rect": right_rect,
        }

    def _build_header_button(self):
        if self.layout is None:
            self.header_button = None
            return

        header_rect = self.layout["header_rect"]
        self.header_button = UIButton(
            button_id="launch_vehicle_test",
            label="Launch Vehicle Test",
            rect=pygame.Rect(header_rect.right - 220, header_rect.y + 11, 200, 30),
            visible=True,
            enabled=True,
        )

    def _is_expanded(self, entity_id):
        return self.browser_tree_state["systems"].get(entity_id, False)

    def _set_expanded(self, entity_id, expanded):
        self.browser_tree_state["systems"][entity_id] = expanded

    def _build_system_browser_items(self, world_model):
        items = []

        if world_model is None:
            return items

        system_entities = world_model.get_entities_by_dataset("systems")

        star_systems = sorted(
            [
                entity for entity in system_entities
                if entity.get("system_role") == "star_system"
            ],
            key=lambda entity: entity.get("name", entity.get("id", ""))
        )

        bodies = [
            entity for entity in system_entities
            if entity.get("system_role") == "orbital_body"
        ]

        bodies_by_parent = {}
        roots_by_system = {}

        for body in bodies:
            parent_body = body.get("parent_body")
            star_system_id = body.get("star_system")

            if parent_body:
                bodies_by_parent.setdefault(parent_body, []).append(body)
            else:
                roots_by_system.setdefault(star_system_id, []).append(body)

        for child_list in bodies_by_parent.values():
            child_list.sort(key=lambda entity: entity.get("name", entity.get("id", "")))

        for child_list in roots_by_system.values():
            child_list.sort(key=lambda entity: entity.get("name", entity.get("id", "")))

        def add_body_subtree(body_entity, depth):
            body_id = body_entity.get("id")
            body_name = body_entity.get("name", body_id or "unknown")
            body_class = body_entity.get("body_class", body_entity.get("type", "entity"))
            children = bodies_by_parent.get(body_id, [])
            expandable = len(children) > 0

            items.append(
                {
                    "kind": "tree_entity",
                    "entity_id": body_id,
                    "text": body_name,
                    "meta_text": f"[{body_class}]",
                    "depth": depth,
                    "expandable": expandable,
                    "expanded": self._is_expanded(body_id),
                }
            )

            if expandable and self._is_expanded(body_id):
                for child in children:
                    add_body_subtree(child, depth + 1)

        for system_entity in star_systems:
            system_id = system_entity.get("id")
            system_name = system_entity.get("name", system_id or "unknown")
            system_class = system_entity.get("system_class", system_entity.get("type", "entity"))
            root_bodies = roots_by_system.get(system_id, [])

            items.append(
                {
                    "kind": "tree_entity",
                    "entity_id": system_id,
                    "text": system_name,
                    "meta_text": f"[{system_class}]",
                    "depth": 0,
                    "expandable": len(root_bodies) > 0,
                    "expanded": self._is_expanded(system_id),
                }
            )

            if self._is_expanded(system_id):
                for root_body in root_bodies:
                    add_body_subtree(root_body, 1)

        return items

    def _dataset_display_label(self, dataset_name):
        return dataset_name.replace("_", " ").title()

    def _entity_class_label(self, dataset_name, entity):
        if dataset_name == "locations":
            return entity.get("location_class", entity.get("type", "entity"))
        if dataset_name == "vehicles":
            return entity.get("vehicle_class", entity.get("type", "entity"))
        if dataset_name == "components":
            return entity.get("component_class", entity.get("type", "entity"))
        if dataset_name == "systems":
            if entity.get("system_role") == "star_system":
                return entity.get("system_class", entity.get("type", "entity"))
            if entity.get("system_role") == "orbital_body":
                return entity.get("body_class", entity.get("type", "entity"))
        return entity.get("type", "entity")

    def _build_browser_items(self, world_model):
        items = [
            {"kind": "label", "text": "Grouping: dataset preview"},
            {"kind": "spacer"},
        ]

        if world_model is None:
            return items

        dataset_names = sorted(world_model.get_dataset_names())

        preferred_order = [
            "locations",
            "vehicles",
            "components",
            "systems",
        ]
        ordered_names = [name for name in preferred_order if name in dataset_names]
        ordered_names += [name for name in dataset_names if name not in ordered_names]

        for dataset_name in ordered_names:
            items.append({"kind": "section", "text": self._dataset_display_label(dataset_name)})

            if dataset_name == "systems":
                items.extend(self._build_system_browser_items(world_model))
                items.append({"kind": "spacer"})
                continue

            entities = sorted(
                world_model.get_entities_by_dataset(dataset_name),
                key=lambda entity: entity.get("name", entity.get("id", ""))
            )

            for entity in entities:
                label = entity.get("name", entity.get("id", "unknown"))
                entity_class = self._entity_class_label(dataset_name, entity)

                items.append(
                    {
                        "kind": "entity",
                        "entity_id": entity.get("id"),
                        "text": f"  {label} [{entity_class}]",
                    }
                )

            items.append({"kind": "spacer"})

        return items

    def _build_card_from_entity(self, entity):
        if entity is None or self.layout is None:
            return None

        dataset_name = entity.get("_dataset", entity.get("type", "entity"))
        card_view = EntityCard(entity, dataset_name=dataset_name)

        if dataset_name == "locations":
            display_group = "location"
            subtype = entity.get("location_class", entity.get("type", "entity"))
        elif dataset_name == "systems":
            system_role = entity.get("system_role")
            if system_role == "star_system":
                display_group = "star system"
                subtype = entity.get("system_class", entity.get("type", "entity"))
            elif system_role == "orbital_body":
                display_group = "orbital body"
                subtype = entity.get("body_class", entity.get("type", "entity"))
            else:
                display_group = "system"
                subtype = entity.get("type", "entity")
        else:
            display_group = dataset_name
            subtype = entity.get("type", "entity")

        start_year = entity.get("start_year", 0)

        card_index = len(self.cards)
        spawn_x = 24 + (card_index % 3) * 40
        spawn_y = 84 + (card_index % 5) * 32

        card = {
            "entity_id": entity.get("id"),
            "title": entity.get("name", entity.get("id", "unknown")),
            "subtitle": f"{display_group} | {subtype}",
            "years": [start_year],
            "selected_year": start_year,
            "canvas_x": spawn_x,
            "canvas_y": spawn_y,
            "canvas_w": 420,
            "canvas_h": 340,
            "card_view": card_view,
        }
        return card

    def _layout_card_interaction(self, card, rect):
        timeline_y = rect.y + max(170, int(rect.height * 0.62))
        left_x = rect.x + 20
        right_x = rect.right - 20
        center_y = timeline_y + 10

        year_positions = []
        years = card["years"]
        for index, year in enumerate(years):
            if len(years) == 1:
                frac = 0.5
            else:
                frac = index / (len(years) - 1)
            year_x = int(left_x + (right_x - left_x) * frac)
            year_positions.append((year, year_x))

        image_rect = pygame.Rect(
            rect.x + 12,
            rect.y + 58,
            rect.width - 24,
            max(90, int(rect.height * 0.30)),
        )
        launch_rect = pygame.Rect(
            rect.x + 12,
            rect.bottom - 36,
            rect.width - 24,
            24,
        )
        header_drag_rect = pygame.Rect(
            rect.x + 1,
            rect.y + 1,
            rect.width - 2,
            50,
        )
        resize_handle_rect = pygame.Rect(
            rect.right - 18,
            rect.bottom - 18,
            14,
            14,
        )

        card["rect"] = rect
        card["image_rect"] = image_rect
        card["launch_rect"] = launch_rect
        card["timeline_y"] = timeline_y
        card["header_drag_rect"] = header_drag_rect
        card["resize_handle_rect"] = resize_handle_rect
        card["year_hitboxes"] = [
            (year, pygame.Rect(year_x - 12, center_y - 12, 24, 48))
            for year, year_x in year_positions
        ]

    def _layout_all_cards(self):
        if self.layout is None:
            return

        right_rect = self.layout["right_rect"]

        max_right = 0
        max_bottom = 0

        for card in self.cards:
            card_w = max(300, min(900, int(card.get("canvas_w", 420))))
            card_h = max(260, min(900, int(card.get("canvas_h", 340))))

            rect_x = right_rect.x + int(card.get("canvas_x", 24)) + self.canvas_offset_x
            rect_y = right_rect.y + int(card.get("canvas_y", 84)) + self.canvas_offset_y

            rect = pygame.Rect(rect_x, rect_y, card_w, card_h)

            card_view = card.get("card_view")
            if card_view is not None:
                card_view.layout_card(card, rect)

            max_right = max(max_right, card.get("canvas_x", 24) + card_w)
            max_bottom = max(max_bottom, card.get("canvas_y", 84) + card_h)

        self.canvas_content_width = max(0, max_right + 24)
        self.canvas_content_height = max(0, max_bottom + 24)

    def _clamp_canvas_offsets(self):
        if self.layout is None:
            return

        right_rect = self.layout["right_rect"]
        visible_width = max(1, right_rect.width - 48)
        visible_height = max(1, right_rect.height - 108)

        min_x = min(0, visible_width - self.canvas_content_width)
        min_y = min(0, visible_height - self.canvas_content_height)

        self.canvas_offset_x = max(min_x, min(0, self.canvas_offset_x))
        self.canvas_offset_y = max(min_y, min(0, self.canvas_offset_y))

    def _ensure_card(self, entity):
        if entity is None:
            return

        entity_id = entity.get("id")
        if entity_id is None:
            return

        for index, card in enumerate(self.cards):
            if card.get("entity_id") == entity_id:
                self.selected_entity_id = entity_id
                card_obj = self.cards.pop(index)
                self.cards.append(card_obj)
                self._layout_all_cards()
                return

        new_card = self._build_card_from_entity(entity)
        if new_card is not None:
            self.cards.append(new_card)
            self.selected_entity_id = entity_id
            self._layout_all_cards()
            self._clamp_canvas_offsets()
            self._layout_all_cards()

    def _rebuild_browser_hitboxes(self):
        self.browser_hitboxes = []
        self.browser_toggle_hitboxes = []

        if self.layout is None:
            return

        left_rect = self.layout["left_rect"]
        content_top = left_rect.y + 48
        content_bottom = left_rect.bottom - 10
        visible_h = content_bottom - content_top

        total_h = len(self.browser_items) * self.LINE_HEIGHT
        max_scroll = max(0, total_h - visible_h)
        self.browser_scroll = max(0, min(self.browser_scroll, max_scroll))

        line_y = content_top - self.browser_scroll

        for item in self.browser_items:
            row_top = line_y
            row_bottom = line_y + self.LINE_HEIGHT

            if item["kind"] == "spacer":
                line_y += self.LINE_HEIGHT
                continue

            if row_bottom < content_top:
                line_y += self.LINE_HEIGHT
                continue

            if row_top > content_bottom:
                break

            if item["kind"] in ("entity", "tree_entity"):
                row_rect = pygame.Rect(left_rect.x + 10, line_y - 1, left_rect.width - 20, self.LINE_HEIGHT)
                self.browser_hitboxes.append((item["entity_id"], row_rect))

                if item["kind"] == "tree_entity" and item.get("expandable", False):
                    depth = item.get("depth", 0)
                    indent_px = depth * 18
                    base_x = left_rect.x + 12 + indent_px
                    caret_rect = pygame.Rect(base_x, line_y + 2, 14, 14)
                    self.browser_toggle_hitboxes.append((item["entity_id"], caret_rect))

            line_y += self.LINE_HEIGHT

    def rebuild(self, app_width, app_height, world_model, repository_scope_entity_id):
        self.reset()

        self.world_model = world_model
        self.repository_scope_entity_id = repository_scope_entity_id
        self.layout = self._build_layout(app_width, app_height)
        self.browser_items = self._build_browser_items(world_model)
        self._build_header_button()
        self._rebuild_browser_hitboxes()

        scope_entity = None
        if world_model is not None and repository_scope_entity_id:
            scope_entity = world_model.get_entity(repository_scope_entity_id)

        if scope_entity is not None:
            scope_name = scope_entity.get("name", repository_scope_entity_id)
            scope_kind = scope_entity.get(
                "location_class",
                scope_entity.get("system_role", scope_entity.get("type", "entity"))
            )
            self.repository_scope_label = f"Scope stub: {scope_name} [{scope_kind}]"
            self._ensure_card(scope_entity)
            self.selected_entity_id = scope_entity.get("id")

        elif not self.cards and world_model is not None:
            self._ensure_card(world_model.get_entity("planet_earth"))
            self._ensure_card(world_model.get_entity("system_sol"))

        self._layout_all_cards()
        self._clamp_canvas_offsets()
        self._layout_all_cards()

    def _draw_card(self, screen, font, card):
        card_view = card.get("card_view")
        if card_view is None:
            return

        card_view.draw_card(screen, font, card)

    def draw(self, screen, font, draw_button_fn):
        if self.layout is None:
            return

        header_rect = self.layout["header_rect"]
        left_rect = self.layout["left_rect"]
        right_rect = self.layout["right_rect"]

        pygame.draw.rect(screen, (18, 20, 26), header_rect)
        pygame.draw.rect(screen, (200, 200, 200), header_rect, 1)

        title_surface = font.render("Knowledge Layer", True, (245, 245, 245))
        subtitle_text = "Pre-simulation repository workspace"
        if self.repository_scope_label:
            subtitle_text = self.repository_scope_label
        subtitle_surface = font.render(subtitle_text, True, (180, 180, 180))
        screen.blit(title_surface, (header_rect.x + 14, header_rect.y + 10))
        screen.blit(subtitle_surface, (header_rect.x + 14, header_rect.y + 30))

        if self.header_button is not None:
            draw_button_fn(screen, font, self.header_button)

        pygame.draw.rect(screen, (12, 12, 20), left_rect)
        pygame.draw.rect(screen, (200, 200, 200), left_rect, 1)

        pygame.draw.rect(screen, (12, 16, 28), right_rect)
        pygame.draw.rect(screen, (200, 200, 200), right_rect, 1)

        left_title = font.render("Repository Browser", True, (240, 240, 240))
        right_title = font.render("Card Canvas", True, (240, 240, 240))
        screen.blit(left_title, (left_rect.x + 12, left_rect.y + 10))
        screen.blit(right_title, (right_rect.x + 12, right_rect.y + 10))

        content_top = left_rect.y + 48
        content_bottom = left_rect.bottom - 10

        row_hitboxes = {entity_id: rect for entity_id, rect in self.browser_hitboxes}
        toggle_hitboxes = {entity_id: rect for entity_id, rect in self.browser_toggle_hitboxes}

        line_y = content_top - self.browser_scroll

        for item in self.browser_items:
            row_top = line_y
            row_bottom = line_y + self.LINE_HEIGHT

            if item["kind"] == "spacer":
                line_y += self.LINE_HEIGHT
                continue

            if row_bottom < content_top:
                line_y += self.LINE_HEIGHT
                continue

            if row_top > content_bottom:
                break

            if item["kind"] == "section":
                color = (235, 235, 235)
                text_surface = font.render(item["text"], True, color)
                screen.blit(text_surface, (left_rect.x + 12, line_y))

            elif item["kind"] == "label":
                color = (220, 220, 220)
                text_surface = font.render(item["text"], True, color)
                screen.blit(text_surface, (left_rect.x + 12, line_y))

            else:
                entity_id = item["entity_id"]
                row_rect = row_hitboxes.get(entity_id)
                is_selected = entity_id == self.selected_entity_id
                color = (245, 245, 245) if is_selected else (220, 220, 220)

                if row_rect is not None and is_selected:
                    pygame.draw.rect(screen, (42, 46, 62), row_rect)
                    pygame.draw.rect(screen, (150, 150, 170), row_rect, 1)

                depth = item.get("depth", 0)
                indent_px = depth * 18
                base_x = left_rect.x + 12 + indent_px

                if item["kind"] == "tree_entity":
                    if item.get("expandable", False):
                        caret_rect = toggle_hitboxes.get(entity_id)
                        if caret_rect is not None:
                            if item.get("expanded", False):
                                pygame.draw.polygon(
                                    screen,
                                    color,
                                    [
                                        (caret_rect.x + 2, caret_rect.y + 4),
                                        (caret_rect.x + 12, caret_rect.y + 4),
                                        (caret_rect.x + 7, caret_rect.y + 11),
                                    ],
                                )
                            else:
                                pygame.draw.polygon(
                                    screen,
                                    color,
                                    [
                                        (caret_rect.x + 4, caret_rect.y + 2),
                                        (caret_rect.x + 11, caret_rect.y + 7),
                                        (caret_rect.x + 4, caret_rect.y + 12),
                                    ],
                                )
                        text_x = base_x + 20
                    else:
                        text_x = base_x + 20

                    text_surface = font.render(item["text"], True, color)
                    screen.blit(text_surface, (text_x, line_y))

                    meta_text = item.get("meta_text")
                    if meta_text:
                        meta_surface = font.render(meta_text, True, (170, 170, 170))
                        screen.blit(meta_surface, (text_x + text_surface.get_width() + 8, line_y))
                else:
                    text_surface = font.render(item["text"], True, color)
                    screen.blit(text_surface, (left_rect.x + 12, line_y))

            line_y += self.LINE_HEIGHT

        previous_clip = screen.get_clip()
        screen.set_clip(right_rect.inflate(-8, -8))
        for card in self.cards:
            self._draw_card(screen, font, card)
        screen.set_clip(previous_clip)

    def handle_event(self, event):
        if self.layout is None:
            return None

        left_rect = self.layout["left_rect"]
        right_rect = self.layout["right_rect"]

        if event.type == pygame.MOUSEWHEEL:
            mouse_pos = pygame.mouse.get_pos()

            if left_rect.collidepoint(mouse_pos):
                line_step = 24
                self.browser_scroll = max(0, self.browser_scroll - event.y * line_step)
                self._rebuild_browser_hitboxes()
                return "__ui_consumed__"

            if right_rect.collidepoint(mouse_pos):
                canvas_step = 48
                self.canvas_offset_y += event.y * canvas_step
                self._clamp_canvas_offsets()
                self._layout_all_cards()
                return "__ui_consumed__"

        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.active_card_drag_id = None
            self.active_card_resize_id = None
            self.card_drag_mouse_offset = (0, 0)
            self.card_resize_start_mouse = None
            self.card_resize_start_size = None
            return "__ui_consumed__"

        if event.type == pygame.MOUSEMOTION:
            if self.active_card_drag_id is not None:
                for card in self.cards:
                    if card.get("entity_id") == self.active_card_drag_id:
                        card["canvas_x"] = event.pos[0] - self.layout["right_rect"].x - self.canvas_offset_x - \
                                           self.card_drag_mouse_offset[0]
                        card["canvas_y"] = event.pos[1] - self.layout["right_rect"].y - self.canvas_offset_y - \
                                           self.card_drag_mouse_offset[1]
                        self._layout_all_cards()
                        self._clamp_canvas_offsets()
                        self._layout_all_cards()
                        return "__ui_consumed__"

            if self.active_card_resize_id is not None:
                for card in self.cards:
                    if card.get("entity_id") == self.active_card_resize_id:
                        dx = event.pos[0] - self.card_resize_start_mouse[0]
                        dy = event.pos[1] - self.card_resize_start_mouse[1]
                        card["canvas_w"] = max(300, self.card_resize_start_size[0] + dx)
                        card["canvas_h"] = max(260, self.card_resize_start_size[1] + dy)
                        self._layout_all_cards()
                        self._clamp_canvas_offsets()
                        self._layout_all_cards()
                        return "__ui_consumed__"

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        mouse_pos = event.pos

        if self.header_button is not None and self.header_button.rect.collidepoint(mouse_pos):
            return self.header_button.id

        for entity_id, hitbox in self.browser_toggle_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                self._set_expanded(entity_id, not self._is_expanded(entity_id))
                self.browser_items = self._build_browser_items(self.world_model)
                self._rebuild_browser_hitboxes()
                return None

        for entity_id, hitbox in self.browser_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                self.selected_entity_id = entity_id

                if self.world_model is not None:
                    entity = self.world_model.get_entity(entity_id)
                    self._ensure_card(entity)

                return None

        for index in range(len(self.cards) - 1, -1, -1):
            card = self.cards[index]
            card_view = card.get("card_view")

            if card["resize_handle_rect"].collidepoint(mouse_pos):
                self.selected_entity_id = card["entity_id"]
                card_obj = self.cards.pop(index)
                self.cards.append(card_obj)
                self.active_card_resize_id = card_obj["entity_id"]
                self.card_resize_start_mouse = mouse_pos
                self.card_resize_start_size = (card_obj.get("canvas_w", 420), card_obj.get("canvas_h", 340))
                self._layout_all_cards()
                return "__ui_consumed__"

            if card["header_drag_rect"].collidepoint(mouse_pos):
                self.selected_entity_id = card["entity_id"]
                card_obj = self.cards.pop(index)
                self.cards.append(card_obj)
                self.active_card_drag_id = card_obj["entity_id"]
                self.card_drag_mouse_offset = (
                    mouse_pos[0] - card_obj["rect"].x,
                    mouse_pos[1] - card_obj["rect"].y,
                )
                self._layout_all_cards()
                return "__ui_consumed__"

            for section_name, section_rect in card.get("section_hitboxes", []):
                if section_rect.collidepoint(mouse_pos) and card_view is not None:
                    self.selected_entity_id = card["entity_id"]
                    card_obj = self.cards.pop(index)
                    self.cards.append(card_obj)
                    card_obj["card_view"].toggle_section(section_name)
                    self._layout_all_cards()
                    self._clamp_canvas_offsets()
                    self._layout_all_cards()
                    return "__ui_consumed__"

            for year, hitbox in card.get("year_hitboxes", []):
                if hitbox.collidepoint(mouse_pos):
                    self.selected_entity_id = card["entity_id"]
                    card_obj = self.cards.pop(index)
                    self.cards.append(card_obj)
                    card_obj["selected_year"] = year
                    self._layout_all_cards()
                    return None

            launch_rect = card.get("launch_rect")
            if launch_rect is not None and launch_rect.collidepoint(mouse_pos):
                self.selected_entity_id = card["entity_id"]
                card_obj = self.cards.pop(index)
                self.cards.append(card_obj)
                self._layout_all_cards()
                return {
                    "id": "knowledge_launch_entry",
                    "entity_id": card_obj.get("entity_id"),
                    "year": card_obj.get("selected_year"),
                }

            if card["rect"].collidepoint(mouse_pos):
                self.selected_entity_id = card["entity_id"]
                card_obj = self.cards.pop(index)
                self.cards.append(card_obj)
                self._layout_all_cards()
                return "__ui_consumed__"

        return None