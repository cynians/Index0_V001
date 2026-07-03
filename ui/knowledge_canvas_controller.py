import pygame

from ui.card import EntityCard
from simulations.phylogeny.clade_graph import find_clade_matches


class KnowledgeCanvasController:
    MAX_CARD_CANVAS_H = 8000

    def __init__(self, host):
        object.__setattr__(self, "host", host)

    def __getattr__(self, name):
        return getattr(self.host, name)

    def __setattr__(self, name, value):
        setattr(self.host, name, value)

    def _normalize_tag_lookup_value(self, value):
        return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    def _find_tag_entity_for_value(self, tag_value):
        if self.world_model is None:
            return None
        tag_norm = self._normalize_tag_lookup_value(tag_value)
        if not tag_norm:
            return None
        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) or {}
        for entity in entities.values():
            if not isinstance(entity, dict):
                continue
            if entity.get("_dataset") != "tags" and entity.get("type") != "tag":
                continue
            candidates = {
                self._normalize_tag_lookup_value(entity.get("id")),
                self._normalize_tag_lookup_value(entity.get("name")),
                self._normalize_tag_lookup_value(entity.get("pretty_name")),
                self._normalize_tag_lookup_value(entity.get("common_name")),
            }
            candidates.update(
                self._normalize_tag_lookup_value(value)
                for value in (entity.get("tags") or [])
            )
            expanded = set(candidates)
            expanded.update(value[4:] for value in candidates if value.startswith("tag_"))
            if tag_norm in expanded:
                return entity
        return None

    def _insert_tag_suggestion_into_card(self, card, tag_value):
        tag_value = str(tag_value or "").strip()
        if not tag_value:
            return False
        card_view = card.get("card_view") if isinstance(card, dict) else None
        if card_view is not None and hasattr(card_view, "_add_tag_value"):
            return bool(card_view._add_tag_value(card, tag_value))
        raw_parts = str(card.get("edit_buffer") or "").replace(",", "\n").splitlines()
        tags = []
        for part in raw_parts:
            text = str(part or "").strip()
            if text and text.lower() not in {tag.lower() for tag in tags}:
                tags.append(text)
        if tag_value.lower() not in {tag.lower() for tag in tags}:
            tags.append(tag_value)
        card["edit_buffer"] = "\n".join(tags)
        card["edit_cursor"] = len(card["edit_buffer"])
        return True

    def _computed_tag_chip_hit_at(self, card, mouse_pos):
        card_view = card.get("card_view") if isinstance(card, dict) else None
        rect = card.get("tag_bar_rect") if isinstance(card, dict) else None
        font = card.get("layout_font") or self.font_for_layout
        if card_view is None or rect is None or font is None:
            return None
        tags = card_view._tag_values() if hasattr(card_view, "_tag_values") else []
        chip_x = rect.x + 52
        chip_y = rect.y + 6
        chip_right = rect.right - 8
        for tag in tags:
            label = card_view._ellipsize_text(tag, font, 120) if hasattr(card_view, "_ellipsize_text") else str(tag)
            chip_w = min(134, max(42, font.size(label)[0] + 14))
            if chip_x + chip_w > chip_right:
                break
            chip_rect = pygame.Rect(chip_x, chip_y, chip_w, 22)
            if chip_rect.collidepoint(mouse_pos):
                return {"tag": tag, "rect": chip_rect}
            chip_x = chip_rect.right + 6
        return None

    def _computed_tag_remove_hit_at(self, card, mouse_pos):
        card_view = card.get("card_view") if isinstance(card, dict) else None
        rect = card.get("tag_bar_rect") if isinstance(card, dict) else None
        font = card.get("layout_font") or self.font_for_layout
        if card_view is None or rect is None or font is None:
            return None
        tags = card_view._tag_values() if hasattr(card_view, "_tag_values") else []
        chip_x = rect.x + 52
        chip_y = rect.y + 6
        chip_right = rect.right - 8
        for tag in tags:
            label = card_view._ellipsize_text(tag, font, 104) if hasattr(card_view, "_ellipsize_text") else str(tag)
            chip_w = min(132, max(48, font.size(label)[0] + 30))
            if chip_x + chip_w > chip_right:
                break
            chip_rect = pygame.Rect(chip_x, chip_y, chip_w, 22)
            remove_rect = pygame.Rect(chip_rect.right - 20, chip_rect.y + 3, 16, 16)
            if remove_rect.collidepoint(mouse_pos):
                return {"tag": tag, "rect": remove_rect}
            chip_x = chip_rect.right + 6
        return None

    def _open_pending_production_site_prompt(self, card):
        action = card.pop("pending_production_action", None)
        if not isinstance(action, dict) or action.get("id") != "create_production_site":
            return False
        site_name = str(action.get("name") or "").strip()
        if not site_name:
            return False
        template = self._template_by_dataset("locations")
        if template is None:
            return False
        return self._open_entry_description_prompt(
            template,
            site_name,
            context={
                "production_create_site": True,
                "producer_card_entity_id": card.get("entity_id"),
                "production_line_index": action.get("line_index"),
            },
        )

    def _layout_all_cards(self):
        if self.layout is None:
            return

        right_rect = self.layout["right_rect"]
        zoom = max(0.001, self.canvas_zoom)
        card_font = self._card_font_for_zoom()
        compact_mode = self._is_compact_canvas_mode()
        layout_viewport = right_rect.inflate(600, 600)

        max_right = 0
        max_bottom = 0

        for card in self.cards:
            card_w = max(300, min(900, int(card.get("canvas_w", 420))))
            requested_h = int(card.get("canvas_h", 340))
            card_view = card.get("card_view")

            rect_x = right_rect.x + self.canvas_offset_x + int(card.get("canvas_x", 24) * zoom)
            rect_y = right_rect.y + self.canvas_offset_y + int(card.get("canvas_y", 84) * zoom)

            if compact_mode:
                card_h = max(260, min(self.MAX_CARD_CANVAS_H, requested_h))
                self._layout_compact_card(card, rect_x, rect_y, card_w, card_h, zoom)
                max_right = max(max_right, card.get("canvas_x", 24) + card_w)
                max_bottom = max(max_bottom, card.get("canvas_y", 84) + card_h)
                continue

            approximate_h = max(260, min(self.MAX_CARD_CANVAS_H, requested_h))
            approximate_rect = pygame.Rect(
                rect_x,
                rect_y,
                max(120, int(round(card_w * zoom))),
                max(120, int(round(approximate_h * zoom))),
            )
            if (
                not approximate_rect.colliderect(layout_viewport)
                and card.get("entity_id") != self.active_card_drag_id
                and not card.get("is_edit_mode", False)
            ):
                self._layout_offscreen_card(card, approximate_rect, approximate_h)
                max_right = max(max_right, card.get("canvas_x", 24) + card_w)
                max_bottom = max(max_bottom, card.get("canvas_y", 84) + approximate_h)
                continue

            auto_canvas_h = bool(card.get("auto_canvas_h", True))
            if card_view is not None and self.font_for_layout is not None:
                minimum_h = card_view.get_minimum_height(card, self.font_for_layout)
            else:
                minimum_h = 260

            if auto_canvas_h:
                card_h = max(260, min(self.MAX_CARD_CANVAS_H, minimum_h))
            else:
                card_h = max(260, min(self.MAX_CARD_CANVAS_H, max(requested_h, minimum_h)))
            card["canvas_h"] = card_h
            card["layout_font"] = card_font

            screen_card_w = max(120, int(round(card_w * zoom)))
            screen_card_h = max(120, int(round(card_h * zoom)))
            rect = pygame.Rect(rect_x, rect_y, screen_card_w, screen_card_h)

            if card_view is not None:
                card["is_compact_canvas_card"] = False
                card["layout_skipped_offscreen"] = False
                card_view.layout_card(card, rect)

            final_rect = card.get("rect", rect)
            toolbelt_rect = card.get("toolbelt_rect")
            visual_right = final_rect.right
            if toolbelt_rect is not None:
                visual_right = max(visual_right, toolbelt_rect.right)

            max_right = max(max_right, card.get("canvas_x", 24) + (visual_right - final_rect.x) / zoom)
            max_bottom = max(max_bottom, card.get("canvas_y", 84) + final_rect.height / zoom)

        self.canvas_content_width = max(0, max_right + 24)
        self.canvas_content_height = max(0, max_bottom + 24)
        self.timeline_ui.set_open_canvas_entity_ids(card.get("entity_id") for card in self.cards)
        self.timeline_ui.rebuild_layout()
        self._layout_canvas_relation_controls()
        self._rebuild_canvas_relation_edges()

    def _layout_offscreen_card(self, card, rect, card_h):
        card["is_compact_canvas_card"] = False
        card["layout_skipped_offscreen"] = True
        card["canvas_h"] = card_h
        card["rect"] = rect
        card["toolbelt_rect"] = None
        card["header_drag_rect"] = rect
        card["close_rect"] = None
        card["template_button_rect"] = None
        card["resize_handle_rect"] = pygame.Rect(rect.right - 12, rect.bottom - 12, 10, 10)
        card["resize_hitboxes"] = []
        card["corner_handle_rects"] = []
        card["tab_hitboxes"] = []
        card["subtab_hitboxes"] = []
        card["editable_field_hitboxes"] = []
        card["relation_hitboxes"] = []
        card["wiki_link_hitboxes"] = []
        card["wiki_section_hitboxes"] = []
        card["toolbelt_hitboxes"] = []
        card["section_hitboxes"] = []
        card["year_hitboxes"] = []
        card["media_import_hitboxes"] = []
        card["media_pixel_art_hitboxes"] = []
        card["media_illustration_link_hitboxes"] = []

    def _is_compact_canvas_mode(self):
        return self.canvas_zoom <= self.compact_canvas_zoom_threshold

    def _layout_compact_card(self, card, rect_x, rect_y, card_w, card_h, zoom):
        compact_w = max(150, min(260, int(round(card_w * zoom))))
        compact_h = 72
        rect = pygame.Rect(rect_x, rect_y, compact_w, compact_h)
        close_rect = pygame.Rect(rect.right - 22, rect.y + 6, 16, 16)
        card["is_compact_canvas_card"] = True
        card["layout_skipped_offscreen"] = False
        card["layout_font"] = self.font_for_layout or pygame.font.SysFont("consolas", 14)
        card["rect"] = rect
        card["toolbelt_rect"] = None
        card["header_drag_rect"] = rect
        card["close_rect"] = close_rect
        card["template_button_rect"] = None
        card["resize_handle_rect"] = pygame.Rect(rect.right - 12, rect.bottom - 12, 10, 10)
        card["resize_hitboxes"] = []
        card["corner_handle_rects"] = []
        card["tab_hitboxes"] = []
        card["subtab_hitboxes"] = []
        card["editable_field_hitboxes"] = []
        card["relation_hitboxes"] = []
        card["wiki_link_hitboxes"] = []
        card["wiki_section_hitboxes"] = []
        card["toolbelt_hitboxes"] = []
        card["media_import_hitboxes"] = []
        card["media_pixel_art_hitboxes"] = []
        card["media_illustration_link_hitboxes"] = []
        card["section_hitboxes"] = []
        card["year_hitboxes"] = []
        card["canvas_relation_add_rect"] = None
        card["screen_scale"] = zoom

    def _clamp_canvas_offsets(self):
        # The card canvas is intentionally unbounded. Offsets are allowed to
        # move freely so cards dragged into negative space remain recoverable by panning.
        return

    def _card_accepts_canvas_relation(self, card):
        return (
            isinstance(card, dict)
            and card.get("card_kind") != "schema"
            and not card.get("is_compact_canvas_card", False)
            and bool(card.get("is_edit_mode", False))
            and bool(card.get("entity_id"))
        )

    def _edit_field_requires_relation_sync(self, card, field_key):
        field_key = str(field_key or "").strip()
        if not field_key:
            return False
        card_view = card.get("card_view") if isinstance(card, dict) else None
        if card_view is not None and getattr(card_view, "is_relation_edit_field", lambda key: False)(field_key):
            return True
        return field_key in {
            "parents",
            "offspring",
            "related",
            "neighbours",
            "overlaps",
            "constituents",
            "parent_location",
            "parent_entity",
            "parent_body",
            "star_system",
        }

    def _card_is_cladistic_entity(self, card):
        entity = self._entity_for_card(card)
        return isinstance(entity, dict) and (
            entity.get("_dataset") == "cladistics"
            or entity.get("type") == "cladistics"
        )

    def _layout_canvas_relation_controls(self):
        for card in self.cards:
            card["canvas_relation_add_rect"] = None
            if not self._card_accepts_canvas_relation(card):
                continue

            rect = card.get("rect")
            if rect is None:
                continue

            size = 28
            card["canvas_relation_add_rect"] = pygame.Rect(
                rect.right - size - 6,
                rect.centery - size // 2,
                size,
                size,
            )

    def _relayout_cards(self):
        self._layout_all_cards()

    def _card_font_for_zoom(self):
        base_size = 16
        if self.font_for_layout is not None:
            base_size = max(8, int(round(self.font_for_layout.get_linesize() * 0.84)))
        cached_font = self.card_font_cache.get(base_size)
        if cached_font is None:
            cached_font = pygame.font.SysFont("consolas", base_size)
            self.card_font_cache[base_size] = cached_font
        return cached_font

    def _screen_to_canvas_pos(self, mouse_pos):
        if self.layout is None:
            return (0, 0)

        right_rect = self.layout["right_rect"]
        zoom = max(0.001, self.canvas_zoom)
        return (
            (mouse_pos[0] - right_rect.x - self.canvas_offset_x) / zoom,
            (mouse_pos[1] - right_rect.y - self.canvas_offset_y) / zoom,
        )

    def _set_canvas_zoom_at(self, mouse_pos, zoom_factor):
        if self.layout is None:
            return

        right_rect = self.layout["right_rect"]
        before_x, before_y = self._screen_to_canvas_pos(mouse_pos)
        new_zoom = max(self.canvas_min_zoom, min(self.canvas_max_zoom, self.canvas_zoom * zoom_factor))
        if abs(new_zoom - self.canvas_zoom) < 0.001:
            return

        self.canvas_zoom = new_zoom
        self.canvas_offset_x = mouse_pos[0] - right_rect.x - before_x * self.canvas_zoom
        self.canvas_offset_y = mouse_pos[1] - right_rect.y - before_y * self.canvas_zoom
        self._layout_all_cards()

    def _scroll_card_at(self, mouse_pos, wheel_y):
        for index in range(len(self.cards) - 1, -1, -1):
            card = self.cards[index]
            card_rect = card.get("rect")
            if card_rect is None or not card_rect.collidepoint(mouse_pos):
                continue

            max_scroll = max(0, int(card.get("scroll_max_y", 0) or 0))
            if max_scroll <= 0:
                return True

            line_step = max(24, self._font_line_height() * 2)
            old_scroll = max(0, min(max_scroll, int(card.get("scroll_y", 0) or 0)))
            new_scroll = max(0, min(max_scroll, old_scroll - int(wheel_y) * line_step))
            if new_scroll != old_scroll:
                card["scroll_y"] = new_scroll
                self._relayout_cards()
            return True

        return False

    def _scroll_phylogeny_parent_at(self, mouse_pos, wheel_y):
        for index in range(len(self.cards) - 1, -1, -1):
            card = self.cards[index]
            card_rect = card.get("rect")
            panel_rect = card.get("phylogeny_parent_panel_rect")
            card_view = card.get("card_view")
            if card_view is None or not getattr(card_view, "_is_phylogeny_mode", lambda: False)():
                continue
            if card_rect is None or panel_rect is None:
                continue
            if not card_rect.collidepoint(mouse_pos) or not panel_rect.collidepoint(mouse_pos):
                continue

            max_scroll = max(0, int(card.get("phylogeny_parent_scroll_max_y", 0) or 0))
            if max_scroll <= 0:
                return False

            line_step = max(24, self._font_line_height() * 2)
            old_scroll = max(0, min(max_scroll, int(card.get("phylogeny_parent_scroll_y", 0) or 0)))
            new_scroll = max(0, min(max_scroll, old_scroll - int(wheel_y) * line_step))
            if new_scroll != old_scroll:
                card["phylogeny_parent_scroll_y"] = new_scroll
                self._relayout_cards()
            return True

        return False

    def _scroll_type_picker_at(self, mouse_pos, wheel_y):
        for index in range(len(self.cards) - 1, -1, -1):
            card = self.cards[index]
            if not card.get("type_picker_open", False):
                continue

            picker_rect = card.get("type_picker_rect")
            if picker_rect is None or not picker_rect.collidepoint(mouse_pos):
                continue

            templates = self._conversion_templates()
            _, scroll, max_scroll = self._card_type_picker_visible_templates(card, templates)
            if max_scroll <= 0:
                return True

            new_scroll = max(0, min(max_scroll, scroll - int(wheel_y)))
            if new_scroll != scroll:
                card["type_picker_scroll"] = new_scroll
                self._relayout_cards()
            return True

        return False

    def _bring_card_to_front(self, index):
        card_obj = self.cards.pop(index)
        self.cards.append(card_obj)
        self.selected_entity_id = card_obj.get("entity_id")
        return card_obj

    def _close_card_at_index(self, index):
        if index < 0 or index >= len(self.cards):
            return False

        closing_card = self.cards.pop(index)
        closing_entity_id = closing_card.get("entity_id")

        if self.selected_entity_id == closing_entity_id:
            self.selected_entity_id = self.cards[-1].get("entity_id") if self.cards else None

        if (
            self.relation_link_target is not None
            and self.relation_link_target.get("source_entity_id") == closing_entity_id
        ):
            self.relation_link_target = None
            self.relation_link_status = ""

        if self.canvas_relation_link_source_id == closing_entity_id:
            self.canvas_relation_link_source_id = None
            self.canvas_relation_status = ""

        self._clear_timeline_edit_target()
        self._close_wiki_link_picker(closing_card)
        self._close_relation_picker(closing_card)
        self.active_card_drag_id = None
        self.active_card_resize_id = None
        self.active_card_color_slider = None
        self._relayout_cards()
        return True

    def _begin_card_resize(self, card_obj, mouse_pos, resize_edges):
        self.active_card_resize_id = card_obj["entity_id"]
        card_obj["auto_canvas_h"] = False
        self.card_resize_start_mouse = mouse_pos
        self.card_resize_start_size = (card_obj.get("canvas_w", 420), card_obj.get("canvas_h", 340))
        self.card_resize_start_position = (card_obj.get("canvas_x", 24), card_obj.get("canvas_y", 84))
        self.card_resize_edges = resize_edges


    def _card_visual_rect(self, card):
        if not isinstance(card, dict):
            return None

        card_rect = card.get("rect")
        toolbelt_rect = card.get("toolbelt_rect")
        if card_rect is not None and toolbelt_rect is not None:
            return card_rect.union(toolbelt_rect)
        return card_rect or toolbelt_rect

    def _graph_relation_entity_ids_for_card(self, card):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return []

        seen = set()
        entity_ids = []

        def append_entity_id(value):
            entity_id = str(value or "").strip()
            if entity_id and entity_id not in seen:
                seen.add(entity_id)
                entity_ids.append(entity_id)

        for entity_id in self._relation_tree_neighbor_ids(entity.get("id")):
            append_entity_id(entity_id)

        return entity_ids

    def _rect_edge_point_toward(self, rect, target_point):
        center_x, center_y = rect.center
        dx = target_point[0] - center_x
        dy = target_point[1] - center_y
        if dx == 0 and dy == 0:
            return rect.center

        x_scale = (rect.width / 2) / abs(dx) if dx else 999999
        y_scale = (rect.height / 2) / abs(dy) if dy else 999999
        scale = min(x_scale, y_scale)
        return (int(center_x + dx * scale), int(center_y + dy * scale))

    def _draw_canvas_graph_line(self, screen, source_rect, target_rect, color):
        start = self._rect_edge_point_toward(source_rect, target_rect.center)
        end = self._rect_edge_point_toward(target_rect, source_rect.center)
        pygame.draw.line(screen, (12, 16, 24), start, end, 6)
        pygame.draw.line(screen, color, start, end, 3)
        pygame.draw.circle(screen, (12, 16, 24), start, 6)
        pygame.draw.circle(screen, color, start, 4)
        pygame.draw.circle(screen, (12, 16, 24), end, 6)
        pygame.draw.circle(screen, color, end, 4)

    def _rebuild_canvas_relation_edges(self):
        cards_by_id = {
            str(card.get("entity_id")): card
            for card in self.cards
            if card.get("entity_id") and card.get("card_kind") != "schema" and card.get("rect") is not None
        }
        if len(cards_by_id) < 2:
            self.canvas_relation_edges = []
            return

        drawn_edges = set()
        edges = []
        for source_id, source_card in cards_by_id.items():
            for target_id in self._graph_relation_entity_ids_for_card(source_card):
                target_id = str(target_id)
                if target_id == source_id or target_id not in cards_by_id:
                    continue
                edge_key = tuple(sorted((source_id, target_id)))
                if edge_key in drawn_edges:
                    continue
                drawn_edges.add(edge_key)
                edges.append(edge_key)
        self.canvas_relation_edges = edges

    def _draw_canvas_relation_lines(self, screen, right_rect):
        if len(self.cards) < 2:
            return

        cards_by_id = {
            str(card.get("entity_id")): card
            for card in self.cards
            if card.get("entity_id") and card.get("card_kind") != "schema" and card.get("rect") is not None
        }
        if len(cards_by_id) < 2:
            return

        previous_clip = screen.get_clip()
        screen.set_clip(previous_clip.clip(right_rect))
        try:
            for source_id, target_id in self.canvas_relation_edges:
                source_card = cards_by_id.get(str(source_id))
                target_card = cards_by_id.get(str(target_id))
                if source_card is None or target_card is None:
                    continue
                source_rect = source_card.get("rect")
                target_rect = target_card.get("rect")
                if source_rect is None or target_rect is None:
                    continue
                self._draw_canvas_graph_line(screen, source_rect, target_rect, (232, 190, 92))

            if self.canvas_relation_link_source_id is not None:
                source_card = self._find_card_by_entity_id(self.canvas_relation_link_source_id)
                source_rect = source_card.get("rect") if source_card is not None else None
                if source_rect is not None:
                    start = self._rect_edge_point_toward(source_rect, pygame.mouse.get_pos())
                    pygame.draw.line(screen, (12, 16, 24), start, pygame.mouse.get_pos(), 4)
                    pygame.draw.line(screen, (238, 214, 128), start, pygame.mouse.get_pos(), 2)
        finally:
            screen.set_clip(previous_clip)

    def _draw_canvas_relation_target_highlights(self, screen, right_rect):
        if self.canvas_relation_link_source_id is None:
            return

        previous_clip = screen.get_clip()
        screen.set_clip(previous_clip.clip(right_rect))
        try:
            for card in self.cards:
                rect = card.get("rect")
                entity_id = card.get("entity_id")
                if (
                    rect is None
                    or card.get("card_kind") == "schema"
                    or entity_id == self.canvas_relation_link_source_id
                ):
                    continue
                pygame.draw.rect(screen, (232, 190, 92), rect.inflate(8, 8), 2)
        finally:
            screen.set_clip(previous_clip)

    def _draw_canvas_relation_control_for_card(self, screen, font, card):
        button_rect = card.get("canvas_relation_add_rect")
        if button_rect is None:
            return

        is_active = card.get("entity_id") == self.canvas_relation_link_source_id
        hovered = button_rect.collidepoint(pygame.mouse.get_pos())
        fill = (104, 88, 36) if is_active else ((62, 78, 104) if hovered else (42, 50, 68))
        border = (238, 210, 130) if is_active else ((174, 204, 238) if hovered else (112, 132, 162))
        pygame.draw.ellipse(screen, fill, button_rect)
        pygame.draw.ellipse(screen, border, button_rect, 1)
        plus_surface = font.render("+", True, (245, 245, 245))
        plus_rect = plus_surface.get_rect(center=button_rect.center)
        screen.blit(plus_surface, plus_rect)

    def _draw_card_canvas(self, screen, font, right_rect):
        """
        Central draw order for card-canvas content.

        Keep background graph/link affordances below cards, then draw each card
        with its own controls in card z order so lower-card controls cannot cut
        through cards above them.
        """
        previous_clip = screen.get_clip()
        canvas_clip = right_rect.inflate(-8, -8)
        screen.set_clip(previous_clip.clip(canvas_clip))
        try:
            self._draw_canvas_relation_lines(screen, right_rect)
            self._draw_canvas_relation_target_highlights(screen, right_rect)
            for card in self.cards:
                visual_rect = self._card_visual_rect(card)
                if visual_rect is not None and not visual_rect.colliderect(canvas_clip):
                    continue
                self._draw_card(screen, font, card)
                self._draw_canvas_relation_control_for_card(screen, font, card)
        finally:
            screen.set_clip(previous_clip)


    def _insert_relation_reference_into_card(self, card, field_key, entity_id):
        entity = self._entity_for_card(card)
        card_view = card.get("card_view") if card is not None else None
        if not isinstance(entity, dict) or not field_key or not entity_id or card_view is None:
            return False

        if hasattr(card_view, "is_location_topology_relation_field") and card_view.is_location_topology_relation_field(field_key):
            card["active_edit_field"] = field_key
            linked = card_view.insert_relation_reference(card, entity_id)
            if not linked:
                return False
            related_update_ids = list(card.pop("location_related_entity_update_ids", []) or [])
            if card.get("is_draft_entity", False):
                self._save_card_draft(card)
            else:
                self._persist_card_entity(card)
                for related_entity_id in related_update_ids:
                    related_entity = self.world_model.get_entity(related_entity_id) if self.world_model is not None else None
                    if isinstance(related_entity, dict):
                        self._persist_entity_to_repository(related_entity)
                self._sync_bidirectional_relations(persist=True)
            return True

        allows_many = field_key in EntityCard.CORE_RELATION_FIELDS or (
            card_view._relation_field_allows_many(field_key)
            if hasattr(card_view, "_relation_field_allows_many")
            else isinstance(entity.get(field_key), list)
        )

        if allows_many:
            current_value = entity.get(field_key)
            if isinstance(current_value, list):
                values = list(current_value)
            elif current_value in (None, ""):
                values = []
            else:
                values = [current_value]

            if entity_id not in [str(value) for value in values]:
                values.append(entity_id)
            entity[field_key] = values
        else:
            entity[field_key] = entity_id

        if card.get("is_draft_entity", False):
            self._save_card_draft(card)
        else:
            self._persist_card_entity(card)
        return True

    def _remove_relation_reference_from_card(self, card, field_key, entity_id):
        entity = self._entity_for_card(card)
        card_view = card.get("card_view") if card is not None else None
        entity_id = str(entity_id or "").strip()
        if not isinstance(entity, dict) or not field_key or not entity_id or card_view is None:
            return False

        allows_many = field_key in EntityCard.CORE_RELATION_FIELDS or (
            card_view._relation_field_allows_many(field_key)
            if hasattr(card_view, "_relation_field_allows_many")
            else isinstance(entity.get(field_key), list)
        )

        current_value = entity.get(field_key)
        if allows_many:
            if isinstance(current_value, list):
                values = [value for value in current_value if str(value).strip() != entity_id]
                if len(values) == len(current_value):
                    return False
            elif current_value in (None, ""):
                return False
            elif str(current_value).strip() == entity_id:
                values = []
            else:
                return False
            entity[field_key] = values
        else:
            if str(current_value or "").strip() != entity_id:
                return False
            entity[field_key] = ""

        if card.get("is_draft_entity", False):
            self._save_card_draft(card)
        else:
            self._persist_card_entity(card)
        return True

    def _find_card_by_entity_id(self, entity_id):
        entity_id = str(entity_id or "")
        for card in self.cards:
            if str(card.get("entity_id") or "") == entity_id:
                return card
            card_view = card.get("card_view")
            entity = getattr(card_view, "entity", None) if card_view is not None else None
            if isinstance(entity, dict) and str(entity.get("id") or "") == entity_id:
                return card
        return None

    def _begin_canvas_relation_link(self, card):
        if card is None or card.get("card_kind") == "schema" or not card.get("entity_id"):
            return False

        if not card.get("is_edit_mode", False):
            return False

        self.canvas_relation_link_source_id = card.get("entity_id")
        entity = self._entity_for_card(card)
        label = (
            self._entity_display_label(entity, fallback=card.get("entity_id", "entry"))
            if isinstance(entity, dict)
            else str(card.get("entity_id") or "entry")
        )
        self.canvas_relation_status = f"Linking from {label}: click a second card"
        self._close_wiki_link_picker(card)
        self._close_relation_picker(card)
        self._relayout_cards()
        return True

    def _clear_canvas_relation_link(self):
        self.canvas_relation_link_source_id = None
        self.canvas_relation_status = ""

    def _link_canvas_relation_cards(self, target_card):
        source_card = self._find_card_by_entity_id(self.canvas_relation_link_source_id)
        target_id = target_card.get("entity_id") if isinstance(target_card, dict) else None
        if source_card is None or not target_id:
            self._clear_canvas_relation_link()
            return False

        if target_id == source_card.get("entity_id") or target_card.get("card_kind") == "schema":
            self._clear_canvas_relation_link()
            self._relayout_cards()
            return False

        linked_related = self._insert_relation_reference_into_card(source_card, "related", target_id)
        linked_parent = self._insert_relation_reference_into_card(source_card, "parents", target_id)
        linked = linked_related or linked_parent
        if linked:
            self._clear_canvas_relation_link()
            self.browser_items = self._build_browser_items(self.world_model)
            self._rebuild_browser_hitboxes()
            self._relayout_cards()
            return True

        self.canvas_relation_status = "Could not link those entries"
        self._relayout_cards()
        return False

    def _handle_canvas_relation_target_click(self, mouse_pos):
        if self.canvas_relation_link_source_id is None:
            return None

        for index in range(len(self.cards) - 1, -1, -1):
            card = self.cards[index]
            visual_rect = self._card_visual_rect(card)
            if visual_rect is None or not visual_rect.collidepoint(mouse_pos):
                continue

            card_obj = self._bring_card_to_front(index)
            self._link_canvas_relation_cards(card_obj)
            return "__ui_consumed__"

        self._clear_canvas_relation_link()
        self._relayout_cards()
        return "__ui_consumed__"

    def _clear_relation_browser_link(self):
        target = self.relation_link_target or {}
        source_card = target.get("source_card")
        if isinstance(source_card, dict):
            source_card.pop("active_relation_link_field", None)
            source_card.pop("relation_link_status", None)

        self.relation_link_target = None
        self.relation_link_status = ""
        self.browser_search_active = False

    def _finish_relation_browser_link(self):
        if self.relation_link_target is None:
            return False

        self._clear_relation_browser_link()
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return True

    def _handle_relation_link_mode_click(self, mouse_pos, left_rect):
        if self.relation_link_target is None:
            return None

        if not left_rect.collidepoint(mouse_pos):
            self._finish_relation_browser_link()
            return "__ui_consumed__"

        item = self._browser_item_at_pos(mouse_pos, left_rect)
        if item is None:
            self._finish_relation_browser_link()
            return "__ui_consumed__"

        entity_id = item.get("entity_id")
        if item.get("kind") == "schema" or self._schema_name_from_card_id(entity_id) is not None:
            self._finish_relation_browser_link()
            return "__ui_consumed__"

        if item.get("kind") not in {"entity", "tree_entity"}:
            self._finish_relation_browser_link()
            return "__ui_consumed__"

        if not self._browser_item_matches_relation_target(item):
            self._finish_relation_browser_link()
            return "__ui_consumed__"

        linked = self._link_relation_from_browser_entity(entity_id)
        if not linked:
            self._rebuild_browser_hitboxes()
            self._relayout_cards()
        return "__ui_consumed__"

    def _begin_relation_browser_link(self, card, relation_info):
        if card is None or not isinstance(relation_info, dict):
            return False

        field_key = relation_info.get("field_key")
        if not field_key:
            return False

        self.relation_link_target = {
            "source_card": card,
            "source_entity_id": card.get("entity_id"),
            "field_key": field_key,
            "target": relation_info.get("target", ""),
        }
        target_label = self._relation_target_label(relation_info.get("target"))
        status = f"Choose an existing {target_label} in the repository or click an open card"
        card["active_relation_link_field"] = field_key
        card["relation_link_status"] = status
        self.relation_link_status = status
        self.browser_filter_dataset = self._relation_target_dataset_filter(relation_info.get("target", ""))
        self.browser_filter_incomplete_only = False
        self.browser_collapsed = False
        self.browser_search_active = True
        self.browser_search_query = ""
        self.browser_scroll = 0
        self.browser_items = self._build_browser_items(self.world_model)
        self.show_template_picker = False
        self._build_template_picker_hitboxes()
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return True

    def _handle_relation_card_link_target_click(self, mouse_pos):
        if self.relation_link_target is None:
            return None

        source_card = self.relation_link_target.get("source_card")
        source_entity_id = self.relation_link_target.get("source_entity_id")

        for index in range(len(self.cards) - 1, -1, -1):
            card = self.cards[index]
            visual_rect = self._card_visual_rect(card)
            if visual_rect is None or not visual_rect.collidepoint(mouse_pos):
                continue

            target_entity_id = card.get("entity_id")
            if not target_entity_id or target_entity_id == source_entity_id:
                self._finish_relation_browser_link()
                return "__ui_consumed__"

            entity = self.world_model.get_entity(target_entity_id) if self.world_model is not None else None
            if entity is None or not self._entity_matches_relation_target(
                entity,
                self.relation_link_target.get("target"),
            ):
                self._finish_relation_browser_link()
                return "__ui_consumed__"

            self._bring_card_to_front(index)
            linked = self._link_relation_from_browser_entity(target_entity_id)
            if not linked:
                self._relayout_cards()
            return "__ui_consumed__"

        self._finish_relation_browser_link()
        return "__ui_consumed__"

    def _link_relation_from_browser_entity(self, entity_id):
        if self.relation_link_target is None or self.world_model is None:
            return False

        entity = self.world_model.get_entity(entity_id)
        if entity is None:
            self.relation_link_status = "That repository row is not an entry"
            return False

        source_card = self.relation_link_target.get("source_card")
        if not isinstance(source_card, dict):
            source_card = self._find_card_by_entity_id(self.relation_link_target.get("source_entity_id"))
        if source_card is None:
            self.relation_link_status = "The source card is no longer open"
            return False

        if self.relation_link_target.get("mode") == "stellar_neighbourhood":
            if not self._is_star_system_entity(entity):
                self.relation_link_status = "Pick a matching star system"
                source_card["relation_link_status"] = self.relation_link_status
                return False
            if entity_id == source_card.get("entity_id"):
                self.relation_link_status = "Pick a different star system"
                source_card["relation_link_status"] = self.relation_link_status
                return False
            return self._open_stellar_neighbour_distance_prompt(source_card, entity_id)

        linked = self._insert_relation_reference_into_card(
            source_card,
            self.relation_link_target.get("field_key"),
            entity_id,
        )
        if not linked:
            self.relation_link_status = "Could not link that entry"
            return False

        label = self._entity_display_label(entity, fallback=entity_id)
        self.relation_link_status = f"Added {label}; Enter or click away to finish"
        source_card["relation_link_status"] = self.relation_link_status
        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return True

    def _create_relation_target_entity(self, relation_info):
        target = relation_info.get("target")
        template = self._template_for_relation_target(target)
        if template is None:
            template = self._template_by_dataset("ideas")
        if template is None:
            return None

        requested_id = relation_info.get("entity_id") if relation_info.get("kind") == "missing" else None
        return self._create_and_open_template_entity(template, requested_id=requested_id)

    def _open_relation_target_template_picker(self, card, relation_info):
        if card is None or not isinstance(relation_info, dict):
            return False

        missing_ref = str(relation_info.get("entity_id") or relation_info.get("label") or "").strip()
        if not missing_ref:
            return False

        self.schema_entry_templates = self._load_schema_entry_templates()
        self.pending_new_entry_name = missing_ref
        self.template_picker_mode = "relation_create"
        self.template_picker_context = {
            "source_entity_id": card.get("entity_id"),
            "card": card,
            "field_key": relation_info.get("field_key"),
            "missing_ref": missing_ref,
            "target": relation_info.get("target"),
        }
        self.template_picker_search_query = ""
        self.template_picker_search_active = True
        self.template_picker_scroll = 0
        self.template_picker_status = f"Choose type for {missing_ref}"
        self.show_template_picker = True
        self._build_template_picker_hitboxes()
        return True

    def _replace_relation_reference_on_card(self, card, field_key, old_ref, new_ref):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict) or not field_key or not new_ref:
            return False

        old_ref = str(old_ref or "").strip()
        new_ref = str(new_ref or "").strip()
        current_value = entity.get(field_key)
        values = []
        if isinstance(current_value, list):
            values = [
                str(item.get("id") if isinstance(item, dict) else item).strip()
                for item in current_value
            ]
        elif isinstance(current_value, str) and current_value.strip():
            values = [current_value.strip()]
        elif current_value not in (None, "", []):
            values = [str(current_value).strip()]

        if not values:
            values = [new_ref]

        replaced = False
        updated_values = []
        for value in values:
            if value == old_ref:
                value = new_ref
                replaced = True
            if value and value not in updated_values:
                updated_values.append(value)

        if not replaced and new_ref not in updated_values:
            updated_values.append(new_ref)

        entity[field_key] = updated_values
        card["subtitle"] = self._card_subtitle_for_entity(entity)
        if card.get("is_draft_entity", False):
            self._save_card_draft(card)
        else:
            self._persist_card_entity(card)
        return True

    def _create_relation_target_from_template_picker(self, template):
        entry_name = str(self.pending_new_entry_name or "").strip()
        if not entry_name:
            self.template_picker_status = "Name entry first"
            return False

        context = dict(self.template_picker_context or {})
        context["relation_create"] = True

        self.pending_new_entry_name = None
        self.show_template_picker = False
        self.template_picker_search_query = ""
        self.template_picker_search_active = False
        self.template_picker_mode = "create"
        self.template_picker_context = {}
        self.template_picker_status = ""
        self._build_template_picker_hitboxes()
        return self._open_entry_description_prompt(template, entry_name, context=context)


    def _handle_card_canvas_click(self, mouse_pos, right_rect):
        if not right_rect.collidepoint(mouse_pos):
            return None

        for index in range(len(self.cards) - 1, -1, -1):
            card = self.cards[index]
            card_view = card.get("card_view")

            close_rect = card.get("close_rect")
            if close_rect is not None and close_rect.collidepoint(mouse_pos):
                self._close_card_at_index(index)
                return "__ui_consumed__"

            if card.get("is_compact_canvas_card", False):
                rect = card.get("rect")
                if rect is not None and rect.collidepoint(mouse_pos):
                    card_obj = self._bring_card_to_front(index)
                    self.active_card_drag_id = card_obj["entity_id"]
                    canvas_x, canvas_y = self._screen_to_canvas_pos(mouse_pos)
                    self.card_drag_mouse_offset = (
                        canvas_x - card_obj.get("canvas_x", 24),
                        canvas_y - card_obj.get("canvas_y", 84),
                    )
                    self._layout_all_cards()
                    return "__ui_consumed__"
                continue

            if card.get("card_kind") == "schema":
                schema_result = self._handle_schema_card_click(card, index, mouse_pos)
                if schema_result is not None:
                    return schema_result

            relation_add_rect = card.get("canvas_relation_add_rect")
            if relation_add_rect is not None and relation_add_rect.collidepoint(mouse_pos):
                card_obj = self._bring_card_to_front(index)
                if self._begin_canvas_relation_link(card_obj):
                    return "__ui_consumed__"

            idea_button_rect = card.get("idea_button_rect")
            if idea_button_rect is not None and idea_button_rect.collidepoint(mouse_pos) and card_view is not None:
                card_obj = self._bring_card_to_front(index)
                self._open_idea_name_prompt(card_obj)
                self._relayout_cards()
                return "__ui_consumed__"

            template_button_rect = card.get("template_button_rect")
            if template_button_rect is not None and template_button_rect.collidepoint(mouse_pos) and card_view is not None:
                card_obj = self._bring_card_to_front(index)
                if self._open_card_class_template_picker(card_obj):
                    self._relayout_cards()
                return "__ui_consumed__"

            relation_tree_rect = card.get("relation_tree_rect")
            if (
                relation_tree_rect is not None
                and relation_tree_rect.collidepoint(mouse_pos)
                and card_view is not None
                and not card.get("is_edit_mode", False)
            ):
                card_obj = self._bring_card_to_front(index)
                if self._open_relation_tree_for_card(card_obj):
                    return "__ui_consumed__"
                self._relayout_cards()
                return "__ui_consumed__"

            for template, type_rect in card.get("type_picker_hitboxes", []):
                if type_rect.collidepoint(mouse_pos):
                    card_obj = self._bring_card_to_front(index)
                    self._convert_card_to_template(card_obj, template)
                    return "__ui_consumed__"

            type_label_rect = card.get("type_label_rect")
            if type_label_rect is not None and type_label_rect.collidepoint(mouse_pos) and card_view is not None:
                card_obj = self._bring_card_to_front(index)
                if self._open_card_class_template_picker(card_obj):
                    self._relayout_cards()
                    return "__ui_consumed__"

            time_anchor_rect = card.get("time_anchor_rect")
            if (
                time_anchor_rect is not None
                and time_anchor_rect.collidepoint(mouse_pos)
                and card.get("is_edit_mode", False)
                and card_view is not None
            ):
                card_obj = self._bring_card_to_front(index)
                if card_obj.get("active_edit_field"):
                    card_obj["card_view"].commit_edit_field(card_obj)
                    if card_obj.get("last_edit_action") == "commit":
                        self._persist_card_entity(card_obj)
                    else:
                        self._save_card_draft(card_obj)
                    card_obj["last_edit_action"] = None

                self._close_wiki_link_picker(card_obj)
                self._close_relation_picker(card_obj)
                self._set_timeline_reanchor_target(card_obj)
                self._relayout_cards()
                return "__ui_consumed__"

            delete_rect = card.get("delete_rect")
            if (
                delete_rect is not None
                and delete_rect.collidepoint(mouse_pos)
                and card.get("is_edit_mode", False)
                and card_view is not None
            ):
                card_obj = self._bring_card_to_front(index)
                if not card_obj.get("delete_confirm_active", False):
                    card_obj["delete_confirm_active"] = True
                    card_obj["active_edit_field"] = None
                    card_obj["edit_buffer"] = ""
                    card_obj["edit_original_value"] = None
                    self._clear_timeline_edit_target()
                    self._close_wiki_link_picker(card_obj)
                    self._close_relation_picker(card_obj)
                    self._relayout_cards()
                    return "__ui_consumed__"

                self._delete_card_entry(card_obj)
                return "__ui_consumed__"

            edit_toggle_rect = card.get("edit_toggle_rect")
            if edit_toggle_rect is not None and edit_toggle_rect.collidepoint(mouse_pos) and card_view is not None:
                card_obj = self._bring_card_to_front(index)
                if card_obj.get("is_temporary", False):
                    self._relayout_cards()
                    return "__ui_consumed__"
                relation_sync_field = card_obj.get("last_committed_field")
                persisted_on_commit = False
                had_active_edit = bool(card_obj.get("is_edit_mode", False) and card_obj.get("active_edit_field"))
                if card_obj.get("is_edit_mode", False) and card_obj.get("active_edit_field"):
                    relation_sync_field = card_obj.get("active_edit_field")
                    card_obj["card_view"].commit_edit_field(card_obj)
                    if card_obj.get("last_edit_action") == "commit":
                        relation_sync_field = card_obj.get("last_committed_field") or relation_sync_field
                        persisted_on_commit = bool(self._persist_card_entity(card_obj))
                    else:
                        self._save_card_draft(card_obj)
                    card_obj["last_edit_action"] = None
                card_obj["card_view"].toggle_edit_mode(card_obj)
                if card_obj.get("is_edit_mode", False):
                    if self._card_is_cladistic_entity(card_obj):
                        self._update_derived_clade_color(card_obj.get("entity_id"), persist=True, force=True)
                else:
                    if not persisted_on_commit and (had_active_edit or card_obj.get("pending_color_persist", False)):
                        self._persist_card_entity(card_obj)
                    if self._edit_field_requires_relation_sync(card_obj, relation_sync_field):
                        self._sync_bidirectional_relations(persist=True)
                    if self.canvas_relation_link_source_id == card_obj.get("entity_id"):
                        self._clear_canvas_relation_link()
                    self._clear_timeline_edit_target()
                    self._close_wiki_link_picker(card_obj)
                    self._close_relation_picker(card_obj)
                self._relayout_cards()
                return "__ui_consumed__"

            for match_index, match_rect in card.get("relation_picker_hitboxes", []):
                if match_rect.collidepoint(mouse_pos) and card_view is not None:
                    card_obj = self._bring_card_to_front(index)
                    if match_index == "note":
                        self._open_relation_note_prompt(
                            card_obj,
                            {"field_key": card_obj.get("active_edit_field")},
                            initial_text=card_obj.get("relation_picker_query", ""),
                        )
                    elif match_index == "create_target":
                        opened = self._open_entry_name_prompt(
                            None,
                            mode="new_entry",
                            context={
                                "link_source_entity_id": card_obj.get("entity_id"),
                                "link_field_key": card_obj.get("active_edit_field"),
                                "target": card_obj.get("relation_picker_target"),
                            },
                        )
                        if not opened:
                            self._open_relation_target_template_picker(
                                card_obj,
                                {
                                    "kind": "create",
                                    "field_key": card_obj.get("active_edit_field"),
                                    "target": card_obj.get("relation_picker_target") or "locations",
                                    "entity_id": card_obj.get("relation_picker_query", ""),
                                    "label": card_obj.get("relation_picker_query", ""),
                                },
                            )
                    else:
                        if self._insert_relation_from_picker(card_obj, match_index=match_index):
                            self._finalize_relation_picker_edit(card_obj)
                            self._sync_card_years_from_entity(card_obj)
                            self._refresh_timeline_items()
                    self._relayout_cards()
                    return "__ui_consumed__"

            for relation_info, relation_rect in card.get("relation_hitboxes", []):
                if relation_rect.collidepoint(mouse_pos) and card_view is not None:
                    card_obj = self._bring_card_to_front(index)
                    if self._handle_relation_chip_click(card_obj, relation_info, mouse_pos=mouse_pos):
                        return "__ui_consumed__"

            for link_info in card.get("wiki_link_hitboxes", []):
                link_rect = link_info.get("rect")
                if link_rect is not None and link_rect.collidepoint(mouse_pos) and card_view is not None:
                    card_obj = self._bring_card_to_front(index)
                    if self._handle_wiki_link_click(card_obj, link_info):
                        self._relayout_cards()
                        return "__ui_consumed__"

            if card_view is not None and card_view.handle_location_click(card, mouse_pos):
                card_obj = self._bring_card_to_front(index)
                pending_location_action = card_obj.pop("pending_location_action", None)
                if card_obj.get("relation_picker_open") and card_obj.get("relation_picker_target"):
                    self._open_relation_picker(card_obj)
                if card_obj.get("last_edit_action") == "commit":
                    self._persist_card_entity(card_obj)
                    related_update_ids = list(card_obj.pop("location_related_entity_update_ids", []) or [])
                    for related_entity_id in related_update_ids:
                        related_entity = self.world_model.get_entity(related_entity_id) if self.world_model is not None else None
                        if isinstance(related_entity, dict):
                            self._persist_entity_to_repository(related_entity)
                    self._sync_bidirectional_relations(persist=True)
                    self._refresh_timeline_items()
                elif card_obj.get("last_edit_action") == "draft":
                    self._save_card_draft(card_obj)
                card_obj["last_edit_action"] = None
                self._relayout_cards()
                if isinstance(pending_location_action, dict):
                    return pending_location_action
                return "__ui_consumed__"

            if card_view is not None and card_view.handle_production_click(card, mouse_pos):
                card_obj = self._bring_card_to_front(index)
                pending_production_action_opened = self._open_pending_production_site_prompt(card_obj)
                if card_obj.get("last_edit_action") == "commit":
                    removed_ids = list(card_obj.pop("production_removed_entity_ids", []) or [])
                    for production_id in removed_ids:
                        self._remove_entity_from_repository("production", production_id)
                    related_update_ids = list(card_obj.pop("production_related_entity_update_ids", []) or [])
                    for related_entity_id in related_update_ids:
                        related_entity = self.world_model.get_entity(related_entity_id) if self.world_model is not None else None
                        if isinstance(related_entity, dict):
                            self._persist_entity_to_repository(related_entity)
                    if not related_update_ids and not removed_ids:
                        self._persist_card_entity(card_obj)
                    self._sync_card_years_from_entity(card_obj)
                    self._refresh_timeline_items()
                elif card_obj.get("last_edit_action") == "draft":
                    self._save_card_draft(card_obj)
                card_obj["last_edit_action"] = None
                self._relayout_cards()
                if pending_production_action_opened:
                    return "__ui_consumed__"
                return "__ui_consumed__"

            phylogeny_click_active = (
                card_view is not None
                and getattr(card_view, "_is_phylogeny_mode", lambda: False)()
            )
            phylogeny_input_rect = card.get("phylogeny_parent_input_rect")
            if phylogeny_click_active and phylogeny_input_rect is not None and phylogeny_input_rect.collidepoint(mouse_pos):
                card_obj = self._bring_card_to_front(index)
                for open_card in self.cards:
                    open_card["phylogeny_parent_input_active"] = open_card is card_obj
                    open_card["phylogeny_child_input_active"] = False
                card_obj.setdefault("phylogeny_parent_query", "")
                card_obj["phylogeny_parent_matches"] = find_clade_matches(
                    self.world_model,
                    card_obj.get("phylogeny_parent_query", ""),
                )
                card_obj["phylogeny_parent_selected_index"] = 0
                self.browser_search_active = False
                self._relayout_cards()
                return "__ui_consumed__"

            if phylogeny_click_active:
                for match_row in card.get("phylogeny_parent_match_rows", []):
                    match_rect = match_row.get("rect")
                    if match_rect is not None and match_rect.collidepoint(mouse_pos):
                        card_obj = self._bring_card_to_front(index)
                        match_index = match_row.get("index")
                        if match_index == "create":
                            match_index = None
                            card_obj["phylogeny_parent_matches"] = []
                        self._confirm_phylogeny_parent_input(card_obj, match_index=match_index)
                        return "__ui_consumed__"

            phylogeny_child_input_rect = card.get("phylogeny_child_input_rect")
            if phylogeny_click_active and phylogeny_child_input_rect is not None and phylogeny_child_input_rect.collidepoint(mouse_pos):
                card_obj = self._bring_card_to_front(index)
                for open_card in self.cards:
                    open_card["phylogeny_parent_input_active"] = False
                    open_card["phylogeny_child_input_active"] = open_card is card_obj
                card_obj.setdefault("phylogeny_child_query", "")
                card_obj["phylogeny_child_matches"] = self._phylogeny_child_matches_for_card(
                    card_obj,
                    card_obj.get("phylogeny_child_query", ""),
                )
                card_obj["phylogeny_child_selected_index"] = 0
                self.browser_search_active = False
                self._relayout_cards()
                return "__ui_consumed__"

            if phylogeny_click_active:
                for match_row in card.get("phylogeny_child_match_rows", []):
                    match_rect = match_row.get("rect")
                    if match_rect is not None and match_rect.collidepoint(mouse_pos):
                        card_obj = self._bring_card_to_front(index)
                        match_index = match_row.get("index")
                        if match_index == "create":
                            match_index = None
                            card_obj["phylogeny_child_matches"] = []
                        self._confirm_phylogeny_child_input(card_obj, match_index=match_index)
                        return "__ui_consumed__"

                for clade_id, node_rect in card.get("phylogeny_node_hitboxes", []):
                    if node_rect is not None and node_rect.collidepoint(mouse_pos):
                        self._bring_card_to_front(index)
                        clade = self.world_model.get_entity(clade_id) if self.world_model is not None else None
                        if clade is not None:
                            self._ensure_card(clade)
                            self._relayout_cards()
                        return "__ui_consumed__"

                for phylogeny_row in (
                    list(card.get("phylogeny_parent_tree_rows", []))
                    + list(card.get("phylogeny_local_tree_rows", []))
                ):
                    row_rect = phylogeny_row.get("rect")
                    target_id = phylogeny_row.get("id")
                    if row_rect is not None and target_id and row_rect.collidepoint(mouse_pos):
                        self._bring_card_to_front(index)
                        target = self.world_model.get_entity(target_id) if self.world_model is not None else None
                        if target is not None:
                            self._ensure_card(target)
                            self._relayout_cards()
                        return "__ui_consumed__"

            if card_view is not None:
                remove_hitboxes = list(card.get("tag_remove_hitboxes", []))
                computed_remove_hit = self._computed_tag_remove_hit_at(card, mouse_pos)
                if computed_remove_hit is not None and not any(
                    info.get("rect") is not None and info.get("rect").collidepoint(mouse_pos)
                    for info in remove_hitboxes
                ):
                    remove_hitboxes.append(computed_remove_hit)
                for remove_info in remove_hitboxes:
                    remove_rect = remove_info.get("rect")
                    if (
                        remove_rect is not None
                        and remove_rect.collidepoint(mouse_pos)
                        and card.get("is_edit_mode", False)
                        and card.get("active_edit_field") == "tags"
                    ):
                        card_obj = self._bring_card_to_front(index)
                        if hasattr(card_obj.get("card_view"), "remove_tag_value"):
                            card_obj["card_view"].remove_tag_value(card_obj, remove_info.get("tag"))
                            if card_obj.get("last_edit_action") == "commit":
                                self._persist_card_entity(card_obj)
                                card_obj["last_edit_action"] = None
                        self._relayout_cards()
                        return "__ui_consumed__"

                for suggestion_info in card.get("tag_suggestion_hitboxes", []):
                    suggestion_rect = suggestion_info.get("rect")
                    if (
                        suggestion_rect is not None
                        and suggestion_rect.collidepoint(mouse_pos)
                        and card.get("is_edit_mode", False)
                        and card.get("active_edit_field") == "tags"
                    ):
                        card_obj = self._bring_card_to_front(index)
                        if self._insert_tag_suggestion_into_card(card_obj, suggestion_info.get("tag")):
                            if card_obj.get("last_edit_action") == "commit":
                                self._persist_card_entity(card_obj)
                                card_obj["last_edit_action"] = None
                            self._relayout_cards()
                        return "__ui_consumed__"

                tag_hitboxes = list(card.get("tag_chip_hitboxes", []))
                computed_tag_hit = self._computed_tag_chip_hit_at(card, mouse_pos)
                if computed_tag_hit is not None and not any(
                    info.get("rect") is not None and info.get("rect").collidepoint(mouse_pos)
                    for info in tag_hitboxes
                ):
                    tag_hitboxes.append(computed_tag_hit)
                for tag_info in tag_hitboxes:
                    tag_rect = tag_info.get("rect")
                    if tag_rect is None or not tag_rect.collidepoint(mouse_pos):
                        continue
                    card_obj = self._bring_card_to_front(index)
                    if card_obj.get("is_edit_mode", False):
                        card_obj["card_view"].begin_edit_field(card_obj, "tags")
                        self._close_relation_picker(card_obj)
                        self._relayout_cards()
                        return "__ui_consumed__"
                    tag_entity = self._find_tag_entity_for_value(tag_info.get("tag"))
                    if tag_entity is not None:
                        self._ensure_card(tag_entity)
                    self._relayout_cards()
                    return "__ui_consumed__"

            editable_result = self._handle_editable_field_click(card, index, mouse_pos)
            if editable_result is not None:
                return editable_result

            for section_info in card.get("wiki_section_hitboxes", []):
                section_rect = section_info.get("rect")
                if (
                    section_rect is not None
                    and section_rect.collidepoint(mouse_pos)
                    and card_view is not None
                    and card.get("is_edit_mode", False)
                ):
                    card_obj = self._bring_card_to_front(index)
                    card_obj["active_color_role"] = "wiki"
                    card_obj["active_wiki_section_id"] = section_info.get("section_id")
                    self._layout_all_cards()
                    return "__ui_consumed__"

            if self._handle_task_checklist_click(card, mouse_pos):
                self._bring_card_to_front(index)
                return "__ui_consumed__"

            for tool_info, tool_rect in card.get("toolbelt_hitboxes", []):
                if tool_rect.collidepoint(mouse_pos) and card_view is not None:
                    card_obj = self._bring_card_to_front(index)
                    if tool_info.get("kind") == "color_picker":
                        if tool_info.get("control") == "role":
                            card_obj["active_color_role"] = tool_info.get("role", "body")
                            if card_obj["active_color_role"] == "wiki" and not card_obj.get("active_wiki_section_id"):
                                first_section = next(iter(card_obj.get("wiki_section_hitboxes", [])), None)
                                if isinstance(first_section, dict):
                                    card_obj["active_wiki_section_id"] = first_section.get("section_id")
                            self._layout_all_cards()
                            return "__ui_consumed__"

                        channel = tool_info.get("channel")
                        slider_rect = tool_info.get("slider_rect")
                        role = card_obj.get("active_color_role", "body")
                        section_id = card_obj.get("active_wiki_section_id")
                        self._set_card_color_from_slider(
                            card_obj,
                            channel,
                            slider_rect,
                            mouse_pos[0],
                            persist=False,
                            role=role,
                            section_id=section_id,
                        )
                        self.active_card_color_slider = {
                            "entity_id": card_obj.get("entity_id"),
                            "channel": channel,
                            "slider_rect": slider_rect,
                            "role": role,
                            "section_id": section_id,
                        }
                        return "__ui_consumed__"
                    action_id = tool_info.get("action_id")
                    if action_id:
                        if action_id == "knowledge_define_stellar_neighbourhood":
                            self._begin_stellar_neighbourhood_link(card_obj)
                            return "__ui_consumed__"
                        self._layout_all_cards()
                        return {
                            "id": action_id,
                            "entity_id": card_obj.get("entity_id"),
                        }
                    self._open_toolbelt_name_prompt(card_obj, tool_info)
                    return "__ui_consumed__"

            for resize_edges, hitbox in card.get("resize_hitboxes", []):
                if hitbox.collidepoint(mouse_pos):
                    card_obj = self._bring_card_to_front(index)
                    self._begin_card_resize(card_obj, mouse_pos, resize_edges)
                    self._layout_all_cards()
                    return "__ui_consumed__"

            if card["resize_handle_rect"].collidepoint(mouse_pos):
                card_obj = self._bring_card_to_front(index)
                self._begin_card_resize(card_obj, mouse_pos, "bottom_right")
                self._layout_all_cards()
                return "__ui_consumed__"

            if card["header_drag_rect"].collidepoint(mouse_pos):
                card_obj = self._bring_card_to_front(index)
                self.active_card_drag_id = card_obj["entity_id"]
                canvas_x, canvas_y = self._screen_to_canvas_pos(mouse_pos)
                self.card_drag_mouse_offset = (
                    canvas_x - card_obj.get("canvas_x", 24),
                    canvas_y - card_obj.get("canvas_y", 84),
                )
                self._layout_all_cards()
                return "__ui_consumed__"

            for tab_name, tab_rect in card.get("tab_hitboxes", []):
                if tab_rect.collidepoint(mouse_pos) and card_view is not None:
                    card_obj = self._bring_card_to_front(index)
                    card_obj["card_view"].set_active_tab(tab_name)
                    self._relayout_cards()
                    return "__ui_consumed__"

            for tab_name, subtab_name, subtab_rect in card.get("subtab_hitboxes", []):
                if subtab_rect.collidepoint(mouse_pos) and card_view is not None:
                    card_obj = self._bring_card_to_front(index)
                    card_obj["card_view"].set_active_subtab(tab_name, subtab_name)
                    self._relayout_cards()
                    return "__ui_consumed__"

            add_illustration_rect = card.get("media_add_illustration_rect")
            if add_illustration_rect is not None and add_illustration_rect.collidepoint(mouse_pos):
                card_obj = self._bring_card_to_front(index)
                self._open_illustration_prompt(card_obj)
                self._relayout_cards()
                return "__ui_consumed__"

            for illustration_id, title_rect in card.get("media_illustration_link_hitboxes", []):
                if title_rect.collidepoint(mouse_pos):
                    self._bring_card_to_front(index)
                    illustration = self.world_model.get_entity(illustration_id) if self.world_model is not None else None
                    if illustration is not None:
                        self._ensure_card(illustration)
                        self._relayout_cards()
                    return "__ui_consumed__"

            for illustration_id, button_rect in card.get("media_pixel_art_hitboxes", []):
                if button_rect.collidepoint(mouse_pos):
                    self._bring_card_to_front(index)
                    self._open_pixel_art_editor(illustration_id)
                    self._relayout_cards()
                    return "__ui_consumed__"

            for illustration_id, button_rect in card.get("media_import_hitboxes", []):
                if button_rect.collidepoint(mouse_pos):
                    card_obj = self._bring_card_to_front(index)
                    self.choose_and_assign_illustration_image(illustration_id)
                    self._relayout_cards()
                    return "__ui_consumed__"

            for section_name, section_rect in card.get("section_hitboxes", []):
                if section_rect.collidepoint(mouse_pos) and card_view is not None:
                    card_obj = self._bring_card_to_front(index)
                    card_obj["card_view"].toggle_section(section_name)
                    self._relayout_cards()
                    return "__ui_consumed__"

            for year, hitbox in card.get("year_hitboxes", []):
                if hitbox.collidepoint(mouse_pos):
                    card_obj = self._bring_card_to_front(index)
                    card_obj["selected_year"] = year
                    card_obj["active_timeline_snapshot_range"] = (year, year)
                    self._focus_timeline_year(year)
                    self._layout_all_cards()
                    return "__ui_consumed__"

            if card_view is not None:
                period_action = card_view.handle_temporal_period_timeline_click(card, mouse_pos)
                if period_action is not None:
                    card_obj = self._bring_card_to_front(index)
                    if period_action == "commit":
                        if card_obj.get("is_draft_entity", False):
                            self._save_card_draft(card_obj)
                        else:
                            self._persist_card_entity(card_obj)
                        self._sync_card_years_from_entity(card_obj)
                        self._refresh_timeline_items()
                    self._layout_all_cards()
                    return "__ui_consumed__"

            launch_rect = card.get("launch_rect")
            if launch_rect is not None and launch_rect.collidepoint(mouse_pos):
                card_obj = self._bring_card_to_front(index)
                self._layout_all_cards()
                return {
                    "id": "knowledge_launch_entry",
                    "entity_id": card_obj.get("entity_id"),
                    "year": card_obj.get("selected_year"),
                }

            toolbelt_rect = card.get("toolbelt_rect")
            if toolbelt_rect is not None and toolbelt_rect.collidepoint(mouse_pos):
                for open_card in self.cards:
                    if open_card is not card:
                        self._close_type_picker(open_card)
                self._bring_card_to_front(index)
                self._layout_all_cards()
                return "__ui_consumed__"

            if card["rect"].collidepoint(mouse_pos):
                for open_card in self.cards:
                    if open_card is not card:
                        self._close_type_picker(open_card)
                self._bring_card_to_front(index)
                self._layout_all_cards()
                return "__ui_consumed__"

        for card in self.cards:
            self._close_type_picker(card)
        self.active_canvas_pan = True
        self.canvas_pan_start_mouse = mouse_pos
        self.canvas_pan_start_offset = (self.canvas_offset_x, self.canvas_offset_y)
        return "__ui_consumed__"
