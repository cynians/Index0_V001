import pygame

from simulations.phylogeny.clade_graph import (
    clade_label,
    find_clade_matches,
    get_clade_entities,
    is_species_entity,
    phylogeny_graph_context,
)


class CardPhylogenyMixin:
    def _is_species_card(self):
        return self.dataset_name == "species" or self.entity.get("type") == "species"

    def _is_cladistics_card(self):
        return self.dataset_name == "cladistics" or self.entity.get("type") == "cladistics"

    def _species_name_parts(self):
        common_name = str(self.entity.get("common_name") or "").strip()
        binomial_name = str(self.entity.get("binomial_name") or "").strip()

        if not common_name:
            pretty_name = str(self.entity.get("pretty_name") or "").strip()
            if " - " in pretty_name:
                common_name = pretty_name.split(" - ", 1)[0].strip()
            elif pretty_name and pretty_name != self.entity.get("id"):
                common_name = pretty_name

        if not binomial_name:
            legacy_name = str(self.entity.get("name") or "").strip()
            if legacy_name and legacy_name != common_name:
                binomial_name = legacy_name
            else:
                pretty_name = str(self.entity.get("pretty_name") or "").strip()
                if " - " in pretty_name:
                    binomial_name = pretty_name.split(" - ", 1)[1].strip()

        return common_name, binomial_name

    def _is_phylogeny_mode(self):
        return self.active_tab == "phylogeny" and (self._is_cladistics_card() or self._is_species_card())

    def _phylogeny_row_colors(self, row, muted=False):
        if row.get("summary"):
            return (30, 34, 44), (76, 86, 106), (178, 188, 204)

        palette = self._phylogeny_row_palette(row, muted=muted)
        if palette is not None:
            return palette["fill"], palette["border"], palette["text"]

        if row.get("highlight"):
            return (58, 66, 88), (190, 210, 246), (244, 246, 250)
        if row.get("neighbor"):
            return (46, 54, 42), (164, 188, 124), (226, 238, 202)
        if row.get("species"):
            return (38, 42, 50), (118, 132, 156), (210, 220, 236)
        return (32, 36, 46), (72, 82, 100), (184, 192, 208) if muted else (216, 224, 238)

    def _phylogeny_row_palette(self, row, muted=False):
        if row.get("summary"):
            return {"fill": (30, 34, 44), "border": (76, 86, 106), "text": (178, 188, 204), "band": None}

        palette = self._entity_link_palette(row.get("id"), fallback_body=None)
        if palette is None and isinstance(row.get("entity"), dict):
            palette = self._entity_link_palette(row.get("entity"), fallback_body=None)
        if palette is not None:
            base = palette["body"]
            fill = self._mix_color(base, (18, 22, 30), 0.60)
            border_source = palette["header"] if palette.get("header") is not None else base
            border = self._mix_color(border_source, (234, 240, 250), 0.26)
            if row.get("highlight"):
                fill = self._mix_color(base, (58, 66, 88), 0.35)
                border = self._mix_color(border_source, (244, 246, 250), 0.12)
            elif row.get("neighbor"):
                fill = self._mix_color(base, (46, 54, 42), 0.35)
                border = self._mix_color(border_source, (230, 242, 204), 0.24)
            text = self._readable_text_color(fill, light=(238, 244, 252), dark=(20, 24, 32))
            if muted:
                text = self._mix_color(text, fill, 0.18)
            palette.update({"fill": fill, "border": border, "text": text})
            return palette
        return None

    def _phylogeny_line_height(self, font):
        return max(16, int(font.get_linesize())) if font is not None else 18

    def _phylogeny_children_count(self, entity_id):
        world_model = self.world_model
        clades = get_clade_entities(world_model)
        entity = clades.get(entity_id)
        if not isinstance(entity, dict):
            return 0
        children = entity.get("offspring") or []
        if isinstance(children, str):
            return 1 if children.strip() else 0
        if isinstance(children, list):
            return len(children)
        return 0

    def _layout_phylogeny_tree_rows(self, root, font, x, y, max_width, depth=0, rows=None):
        rows = rows if rows is not None else []
        if not isinstance(root, dict):
            return rows, y

        line_h = self._phylogeny_line_height(font)
        row_h = line_h + 8
        indent = depth * 18
        label = str(root.get("label") or root.get("id") or "Unknown")
        row_rect = pygame.Rect(x + indent, y, max(40, max_width - indent), row_h)
        rows.append(
            {
                "id": root.get("id"),
                "label": label,
                "rect": row_rect,
                "depth": depth,
                "highlight": bool(root.get("highlight")),
                "neighbor": bool(root.get("neighbor")),
                "species": bool(root.get("species")),
            }
        )
        y = row_rect.bottom + 3
        for child in root.get("children", []) or []:
            rows, y = self._layout_phylogeny_tree_rows(child, font, x, y, max_width, depth + 1, rows)
        return rows, y

    def _summarized_phylogeny_chain_ids(self, chain_ids, top_count=3, tail_count=5):
        chain_ids = [str(chain_id) for chain_id in chain_ids if chain_id]
        if len(chain_ids) <= top_count + tail_count + 1:
            return [(chain_id, False) for chain_id in chain_ids]

        top_ids = chain_ids[:top_count]
        tail_ids = chain_ids[-tail_count:]
        return (
            [(chain_id, False) for chain_id in top_ids]
            + [(None, True)]
            + [(chain_id, False) for chain_id in tail_ids]
        )

    def _layout_phylogeny_chain_rows(self, graph, entity_id, font, x, y, max_width):
        line_h = self._phylogeny_line_height(font)
        row_h = max(18, line_h + 2)
        row_gap = 1
        rows = []
        chain_ids = graph.ancestor_chain(entity_id)
        if not chain_ids and entity_id in graph.phylogeny_entities:
            chain_ids = [entity_id]

        for display_depth, (chain_id, is_summary) in enumerate(self._summarized_phylogeny_chain_ids(chain_ids)):
            indent = display_depth * 14
            row_rect = pygame.Rect(x + indent, y, max(40, max_width - indent), row_h)
            if is_summary:
                rows.append(
                    {
                        "id": None,
                        "label": "(...)",
                        "rect": row_rect,
                        "depth": display_depth,
                        "summary": True,
                    }
                )
            else:
                entity = graph.phylogeny_entities.get(chain_id)
                rows.append(
                    {
                        "id": chain_id,
                        "label": clade_label(entity, chain_id),
                        "rect": row_rect,
                        "depth": display_depth,
                        "highlight": chain_id == entity_id,
                        "species": bool(is_species_entity(entity)),
                    }
                )
            y = row_rect.bottom + row_gap
        return rows, y

    def _clip_phylogeny_rect_to_panel(self, rect, panel_rect):
        if rect is None or panel_rect is None or not rect.colliderect(panel_rect):
            return None
        clipped = rect.clip(panel_rect)
        if clipped.width <= 0 or clipped.height <= 0:
            return None
        return clipped

    def _shift_clip_phylogeny_row(self, row, scroll_y, panel_rect):
        row_rect = row.get("rect")
        if row_rect is None:
            return None
        shifted_rect = row_rect.move(0, -scroll_y)
        clipped_rect = self._clip_phylogeny_rect_to_panel(shifted_rect, panel_rect)
        if clipped_rect is None:
            return None
        visible_row = dict(row)
        visible_row["rect"] = clipped_rect
        return visible_row

    def _shift_clip_phylogeny_match_rows(self, rows, scroll_y, panel_rect):
        visible_rows = []
        for row in rows:
            shifted = self._shift_clip_phylogeny_row(row, scroll_y, panel_rect)
            if shifted is not None:
                visible_rows.append(shifted)
        return visible_rows

    def _layout_phylogeny_content(self, card, content_left, current_y, text_width):
        font = card.get("layout_font")
        line_h = self._phylogeny_line_height(font)
        entity_id = str(self.entity.get("id") or "")
        is_clade = self._is_cladistics_card()
        section_h = self.SECTION_HEADER_H
        graph = phylogeny_graph_context(self.world_model)

        parent_section_rect = pygame.Rect(content_left, current_y, text_width, section_h)
        current_y = parent_section_rect.bottom + self.SECTION_GAP

        input_rect = None
        match_rows = []
        child_input_rect = None
        child_match_rows = []
        parent_tree_rows = []
        child_tree_rows = []
        member_rows = []
        local_node_hitboxes = []
        parent_panel_rect = None
        parent_panel_content_rect = None
        parent_target_id = entity_id
        child_target_id = entity_id if is_clade else ""
        child_sibling_id = ""

        if not self.collapsed_sections.get("Phylogeny Parents", False):
            parent_panel_rect = pygame.Rect(
                content_left + 4,
                current_y,
                max(80, text_width - 8),
                self.PHYLOGENY_PARENT_PANEL_H,
            )
            parent_panel_content_rect = parent_panel_rect.inflate(-14, -14)
            panel_content_y = parent_panel_content_rect.y

            input_rect = pygame.Rect(
                parent_panel_content_rect.x,
                panel_content_y,
                parent_panel_content_rect.width,
                26,
            )
            panel_content_y = input_rect.bottom + 5

            query = str(card.get("phylogeny_parent_query") or "").strip()
            matches = card.get("phylogeny_parent_matches")
            if matches is None:
                matches = find_clade_matches(self.world_model, query)
                card["phylogeny_parent_matches"] = matches

            if query:
                if matches:
                    for index, match in enumerate(matches[:4]):
                        row_rect = pygame.Rect(
                            parent_panel_content_rect.x,
                            panel_content_y,
                            parent_panel_content_rect.width,
                            28,
                        )
                        match_rows.append({"index": index, "entity": match, "rect": row_rect})
                        panel_content_y = row_rect.bottom + 4
                else:
                    row_rect = pygame.Rect(
                        parent_panel_content_rect.x,
                        panel_content_y,
                        parent_panel_content_rect.width,
                        28,
                    )
                    match_rows.append({"index": "create", "entity": None, "rect": row_rect})
                    panel_content_y = row_rect.bottom + 4

            tree = graph.context_tree(entity_id)
            if tree is not None:
                parent_tree_rows, panel_content_y = self._layout_phylogeny_chain_rows(
                    graph,
                    entity_id,
                    font,
                    parent_panel_content_rect.x,
                    panel_content_y + 4,
                    parent_panel_content_rect.width,
                )
            else:
                panel_content_y += line_h + 8

            if parent_tree_rows:
                parent_target_id = str(parent_tree_rows[0].get("id") or entity_id)
                child_target_id = ""
                bottom_entry_id = ""
                for row in reversed(parent_tree_rows):
                    if row.get("summary"):
                        continue
                    row_id = str(row.get("id") or "").strip()
                    if row_id:
                        bottom_entry_id = row_id
                        break
                if bottom_entry_id:
                    child_sibling_id = bottom_entry_id
                    for candidate_parent_id in graph.parents_by_child.get(bottom_entry_id, []):
                        if candidate_parent_id in graph.clades:
                            child_target_id = candidate_parent_id
                            break

            if is_clade and child_target_id:
                child_input_rect = pygame.Rect(
                    parent_panel_content_rect.x,
                    panel_content_y + 2,
                    parent_panel_content_rect.width,
                    26,
                )
                panel_content_y = child_input_rect.bottom + 5

                child_query = str(card.get("phylogeny_child_query") or "").strip()
                child_matches = card.get("phylogeny_child_matches")
                if child_matches is None:
                    child_matches = find_clade_matches(self.world_model, child_query)
                    card["phylogeny_child_matches"] = child_matches

                if child_query:
                    excluded_child_match_ids = {
                        entity_id,
                        str(child_target_id or "").strip(),
                        str(child_sibling_id or "").strip(),
                    }
                    visible_child_matches = [
                        (index, match)
                        for index, match in enumerate(child_matches)
                        if str(match.get("id") or "").strip() not in excluded_child_match_ids
                    ]
                    for index, match in visible_child_matches[:5]:
                        row_rect = pygame.Rect(
                            parent_panel_content_rect.x,
                            panel_content_y,
                            parent_panel_content_rect.width,
                            28,
                        )
                        child_match_rows.append({"index": index, "entity": match, "rect": row_rect})
                        panel_content_y = row_rect.bottom + 4
                    if not child_match_rows:
                        row_rect = pygame.Rect(
                            parent_panel_content_rect.x,
                            panel_content_y,
                            parent_panel_content_rect.width,
                            28,
                        )
                        child_match_rows.append({"index": "create", "entity": None, "rect": row_rect})
                        panel_content_y = row_rect.bottom + 4

            parent_content_h = max(0, panel_content_y - parent_panel_content_rect.y)
            parent_visible_h = max(1, parent_panel_content_rect.height)
            parent_scroll_max = max(0, int(parent_content_h - parent_visible_h))
            parent_scroll_y = max(0, min(parent_scroll_max, int(card.get("phylogeny_parent_scroll_y", 0) or 0)))
            card["phylogeny_parent_scroll_y"] = parent_scroll_y
            card["phylogeny_parent_scroll_max_y"] = parent_scroll_max

            input_rect = self._clip_phylogeny_rect_to_panel(input_rect.move(0, -parent_scroll_y), parent_panel_content_rect)
            child_input_rect = (
                self._clip_phylogeny_rect_to_panel(child_input_rect.move(0, -parent_scroll_y), parent_panel_content_rect)
                if child_input_rect is not None
                else None
            )
            match_rows = self._shift_clip_phylogeny_match_rows(match_rows, parent_scroll_y, parent_panel_content_rect)
            child_match_rows = self._shift_clip_phylogeny_match_rows(child_match_rows, parent_scroll_y, parent_panel_content_rect)
            parent_tree_rows = [
                visible_row
                for row in parent_tree_rows
                for visible_row in [self._shift_clip_phylogeny_row(row, parent_scroll_y, parent_panel_content_rect)]
                if visible_row is not None
            ]
            current_y = parent_panel_rect.bottom + 8
        else:
            card["phylogeny_parent_scroll_y"] = 0
            card["phylogeny_parent_scroll_max_y"] = 0

        current_y += 8
        child_section_rect = pygame.Rect(
            content_left,
            current_y,
            text_width,
            section_h,
        )
        current_y = child_section_rect.bottom + self.SECTION_GAP

        if not self.collapsed_sections.get("Phylogeny Children", False):
            child_ids = graph.children_by_parent.get(entity_id, [])

            for child_id in child_ids:
                child = graph.phylogeny_entities.get(child_id)
                row_rect = pygame.Rect(
                    content_left + 10,
                    current_y + 3,
                    text_width - 20,
                    line_h + 10,
                )
                child_tree_rows.append(
                    {
                        "id": child_id,
                        "label": clade_label(child, child_id),
                        "rect": row_rect,
                        "depth": 0,
                        "species": bool(is_species_entity(child)),
                    }
                )
                local_node_hitboxes.append((child_id, row_rect))
                current_y = row_rect.bottom + 3

            if not child_ids:
                current_y += line_h + 10

        current_y += 8
        members_section_rect = pygame.Rect(
            content_left,
            current_y,
            text_width,
            section_h,
        )
        current_y = members_section_rect.bottom + self.SECTION_GAP
        if not self.collapsed_sections.get("Members", False):
            if is_clade:
                limit = int(card.get("phylogeny_clade_member_limit", 3) or 3)
                member_ids = graph.distant_species_members(entity_id, limit=max(1, limit))
            else:
                limit = int(card.get("phylogeny_species_relative_limit", 4) or 4)
                member_ids = graph.closest_species_relatives(entity_id, limit=max(1, limit))

            for member_id in member_ids:
                member = graph.phylogeny_entities.get(member_id)
                row_rect = pygame.Rect(
                    content_left + 10,
                    current_y + 3,
                    text_width - 20,
                    line_h + 10,
                )
                member_rows.append(
                    {
                        "id": member_id,
                        "label": clade_label(member, member_id),
                        "rect": row_rect,
                        "depth": 0,
                        "species": bool(is_species_entity(member)),
                    }
                )
                local_node_hitboxes.append((member_id, row_rect))
                current_y = row_rect.bottom + 3

            if not member_ids:
                current_y += line_h + 10

        card["phylogeny_parent_section_rect"] = parent_section_rect
        card["phylogeny_parent_panel_rect"] = parent_panel_rect
        card["phylogeny_parent_panel_content_rect"] = parent_panel_content_rect
        card["phylogeny_child_section_rect"] = child_section_rect
        card["phylogeny_diagram_section_rect"] = members_section_rect
        card["phylogeny_parent_input_rect"] = input_rect
        card["phylogeny_child_input_rect"] = child_input_rect
        card["phylogeny_parent_match_rows"] = match_rows
        card["phylogeny_child_match_rows"] = child_match_rows
        card["phylogeny_parent_tree_rows"] = parent_tree_rows
        card["phylogeny_child_tree_rows"] = child_tree_rows
        card["phylogeny_local_tree_rows"] = member_rows
        card["phylogeny_node_hitboxes"] = local_node_hitboxes
        card["phylogeny_members_label"] = "Members" if is_clade else "Relatives"
        card["phylogeny_parent_target_id"] = parent_target_id
        card["phylogeny_child_target_id"] = child_target_id
        card["phylogeny_child_sibling_id"] = child_sibling_id
        return current_y

    def _draw_phylogeny_section_header(self, screen, font, rect, label, expanded):
        if rect is None:
            return
        pygame.draw.rect(screen, (36, 40, 50), rect)
        pygame.draw.rect(screen, (110, 110, 120), rect, 1)
        marker = "v" if expanded else ">"
        screen.blit(font.render(f"{marker} {label}", True, (235, 235, 235)), (rect.x + 8, rect.y + 3))

    def _draw_phylogeny_rows(self, screen, font, rows, muted=False):
        line_h = self._phylogeny_line_height(font)
        for row in rows:
            row_rect = row.get("rect")
            if row_rect is None:
                continue
            palette = self._phylogeny_row_palette(row, muted=muted)
            if palette is None:
                fill, border, text_color = self._phylogeny_row_colors(row, muted=muted)
                band = None
            else:
                fill, border, text_color = palette["fill"], palette["border"], palette["text"]
                band = palette.get("band")
            pygame.draw.rect(screen, fill, row_rect)
            if band is not None:
                band_rect = pygame.Rect(row_rect.x, row_rect.y, min(5, row_rect.width), row_rect.height)
                pygame.draw.rect(screen, band, band_rect)
            pygame.draw.rect(screen, border, row_rect, 1)
            text_x = row_rect.x + (11 if band is not None else 8)
            available_w = row_rect.right - text_x - 8
            distance_label = str(row.get("distance_label") or "").strip()
            if distance_label:
                badge_w = min(64, max(42, row_rect.width // 3))
                badge_rect = pygame.Rect(row_rect.x + 5, row_rect.y + 4, badge_w, max(14, row_rect.height - 8))
                pygame.draw.rect(screen, (24, 28, 36), badge_rect)
                pygame.draw.rect(screen, (132, 148, 174), badge_rect, 1)
                badge_text = self._ellipsize_text(distance_label, font, badge_rect.width - 8)
                badge_surface = font.render(badge_text, True, (232, 238, 248))
                screen.blit(badge_surface, badge_surface.get_rect(center=badge_rect.center))
                text_x = badge_rect.right + 8
                available_w = max(20, row_rect.right - text_x - 8)
            label = self._ellipsize_text(str(row.get("label") or row.get("id") or ""), font, available_w)
            screen.blit(font.render(label, True, text_color), (text_x, row_rect.y + max(3, (row_rect.height - line_h) // 2)))

    def _draw_phylogeny_parent_scrollbar(self, screen, card):
        panel_rect = card.get("phylogeny_parent_panel_rect")
        content_rect = card.get("phylogeny_parent_panel_content_rect")
        max_scroll = max(0, int(card.get("phylogeny_parent_scroll_max_y", 0) or 0))
        if panel_rect is None or content_rect is None or max_scroll <= 0:
            return

        track_rect = pygame.Rect(panel_rect.right - 7, content_rect.y, 3, content_rect.height)
        pygame.draw.rect(screen, (44, 50, 62), track_rect)
        visible_h = max(1, content_rect.height)
        content_h = visible_h + max_scroll
        thumb_h = max(18, int(round(track_rect.height * visible_h / max(1, content_h))))
        scroll_y = max(0, min(max_scroll, int(card.get("phylogeny_parent_scroll_y", 0) or 0)))
        thumb_y = track_rect.y + int(round((track_rect.height - thumb_h) * scroll_y / max(1, max_scroll)))
        pygame.draw.rect(screen, (132, 146, 170), pygame.Rect(track_rect.x, thumb_y, track_rect.width, thumb_h))

    def _draw_phylogeny_content(self, screen, font, card):
        parent_expanded = not self.collapsed_sections.get(
            "Phylogeny Parents",
            False,
        )
        child_expanded = not self.collapsed_sections.get(
            "Phylogeny Children",
            False,
        )
        diagram_expanded = not self.collapsed_sections.get(
            "Members",
            False,
        )
        self._draw_phylogeny_section_header(
            screen,
            font,
            card.get("phylogeny_parent_section_rect"),
            "Phylogeny Parents",
            parent_expanded,
        )

        panel_rect = card.get("phylogeny_parent_panel_rect")
        panel_content_rect = card.get("phylogeny_parent_panel_content_rect")
        previous_clip = screen.get_clip()
        if parent_expanded and panel_rect is not None:
            pygame.draw.rect(screen, (24, 28, 36), panel_rect)
            pygame.draw.rect(screen, (94, 108, 132), panel_rect, 1)
            if panel_content_rect is not None:
                screen.set_clip(previous_clip.clip(panel_content_rect))

        input_rect = card.get("phylogeny_parent_input_rect")
        try:
            if parent_expanded and input_rect is not None:
                active = bool(card.get("phylogeny_parent_input_active"))
                fill = (40, 48, 64) if active else (30, 35, 44)
                border = (184, 204, 236) if active else (92, 104, 126)
                pygame.draw.rect(screen, fill, input_rect)
                pygame.draw.rect(screen, border, input_rect, 1)
                query = str(card.get("phylogeny_parent_query") or "")
                target = self.world_model.get_entity(card.get("phylogeny_parent_target_id")) if self.world_model is not None else None
                target_label = clade_label(target, card.get("phylogeny_parent_target_id"))
                placeholder = f"+ parent of {target_label}..."
                text = query or placeholder
                color = (238, 240, 246) if query else (144, 154, 172)
                text = self._ellipsize_text(text, font, input_rect.width - 14)
                screen.blit(font.render(text, True, color), (input_rect.x + 7, input_rect.y + 4))

                for row in card.get("phylogeny_parent_match_rows", []):
                    row_rect = row.get("rect")
                    if row_rect is None:
                        continue
                    selected = row.get("index") == card.get("phylogeny_parent_selected_index", 0)
                    is_create = row.get("index") == "create"
                    row_palette = self._phylogeny_row_palette(
                        {
                            "id": (row.get("entity") or {}).get("id") if isinstance(row.get("entity"), dict) else "",
                            "entity": row.get("entity"),
                            "highlight": selected,
                        }
                    )
                    if row_palette is None:
                        fill, border, text_color = self._phylogeny_row_colors(
                            {
                                "id": (row.get("entity") or {}).get("id") if isinstance(row.get("entity"), dict) else "",
                                "entity": row.get("entity"),
                                "highlight": selected,
                            }
                        )
                        band = None
                    else:
                        fill, border, text_color = row_palette["fill"], row_palette["border"], row_palette["text"]
                        band = row_palette.get("band")
                    if is_create:
                        fill = (48, 58, 42) if selected else (36, 44, 34)
                        border = (168, 196, 128)
                        text_color = (238, 242, 246)
                        band = None
                    pygame.draw.rect(screen, fill, row_rect)
                    if band is not None:
                        pygame.draw.rect(screen, band, pygame.Rect(row_rect.x, row_rect.y, min(5, row_rect.width), row_rect.height))
                    pygame.draw.rect(screen, border, row_rect, 1)
                    if is_create:
                        label = f"Create clade: {query}"
                    else:
                        label = clade_label(row.get("entity"), "")
                    text_x = row_rect.x + (11 if band is not None else 7)
                    label = self._ellipsize_text(label, font, row_rect.right - text_x - 7)
                    screen.blit(font.render(label, True, text_color), (text_x, row_rect.y + 6))

            if parent_expanded:
                self._draw_phylogeny_rows(screen, font, card.get("phylogeny_parent_tree_rows", []))
                status = str(card.get("phylogeny_status") or "").strip()
                if status and input_rect is not None:
                    status_surface = font.render(status, True, (220, 196, 132))
                    screen.blit(status_surface, (input_rect.x, input_rect.bottom + 2))

            child_input_rect = card.get("phylogeny_child_input_rect")
            if parent_expanded and child_input_rect is not None:
                active = bool(card.get("phylogeny_child_input_active"))
                fill = (40, 48, 64) if active else (30, 35, 44)
                border = (184, 204, 236) if active else (92, 104, 126)
                pygame.draw.rect(screen, fill, child_input_rect)
                pygame.draw.rect(screen, border, child_input_rect, 1)
                query = str(card.get("phylogeny_child_query") or "")
                sibling = self.world_model.get_entity(card.get("phylogeny_child_sibling_id")) if self.world_model is not None else None
                sibling_label = clade_label(sibling, card.get("phylogeny_child_sibling_id"))
                placeholder = f"+ sister of {sibling_label}..."
                text = self._ellipsize_text(query or placeholder, font, child_input_rect.width - 14)
                color = (238, 240, 246) if query else (144, 154, 172)
                screen.blit(font.render(text, True, color), (child_input_rect.x + 7, child_input_rect.y + 4))

                for row in card.get("phylogeny_child_match_rows", []):
                    row_rect = row.get("rect")
                    if row_rect is None:
                        continue
                    selected = row.get("index") == card.get("phylogeny_child_selected_index", 0)
                    is_create = row.get("index") == "create"
                    row_palette = self._phylogeny_row_palette(
                        {
                            "id": (row.get("entity") or {}).get("id") if isinstance(row.get("entity"), dict) else "",
                            "entity": row.get("entity"),
                            "highlight": selected,
                        }
                    )
                    if row_palette is None:
                        fill, border, text_color = self._phylogeny_row_colors(
                            {
                                "id": (row.get("entity") or {}).get("id") if isinstance(row.get("entity"), dict) else "",
                                "entity": row.get("entity"),
                                "highlight": selected,
                            }
                        )
                        band = None
                    else:
                        fill, border, text_color = row_palette["fill"], row_palette["border"], row_palette["text"]
                        band = row_palette.get("band")
                    if is_create:
                        fill = (48, 58, 42) if selected else (36, 44, 34)
                        border = (168, 196, 128)
                        text_color = (238, 242, 246)
                        band = None
                    pygame.draw.rect(screen, fill, row_rect)
                    if band is not None:
                        pygame.draw.rect(screen, band, pygame.Rect(row_rect.x, row_rect.y, min(5, row_rect.width), row_rect.height))
                    pygame.draw.rect(screen, border, row_rect, 1)
                    if is_create:
                        label = f"Create clade: {query}"
                    else:
                        entity = row.get("entity")
                        label = clade_label(entity, "")
                    text_x = row_rect.x + (11 if band is not None else 7)
                    label = self._ellipsize_text(label, font, row_rect.right - text_x - 7)
                    screen.blit(font.render(label, True, text_color), (text_x, row_rect.y + 6))
        finally:
            screen.set_clip(previous_clip)

        if parent_expanded:
            self._draw_phylogeny_parent_scrollbar(screen, card)

        self._draw_phylogeny_section_header(
            screen,
            font,
            card.get("phylogeny_child_section_rect"),
            "Phylogeny Children",
            child_expanded,
        )

        if child_expanded:
            rows = card.get("phylogeny_child_tree_rows", [])
            if rows:
                self._draw_phylogeny_rows(screen, font, rows)
            else:
                rect = card.get("phylogeny_child_section_rect")
                if rect is not None:
                    empty_surface = font.render(
                        "No direct offspring found",
                        True,
                        (150, 160, 178),
                    )
                    screen.blit(
                        empty_surface,
                        (rect.x + 8, rect.bottom + 8),
                    )

        self._draw_phylogeny_section_header(
            screen,
            font,
            card.get("phylogeny_diagram_section_rect"),
            card.get("phylogeny_members_label", "Members"),
            diagram_expanded,
        )
        if diagram_expanded:
            rows = card.get("phylogeny_local_tree_rows", [])
            if rows:
                self._draw_phylogeny_rows(screen, font, rows)
            else:
                rect = card.get("phylogeny_diagram_section_rect")
                if rect is not None:
                    screen.blit(font.render("No species entries found yet", True, (150, 160, 178)), (rect.x + 8, rect.bottom + 8))
