import json
import copy
import colorsys
import os
import random
import re
import shutil
from pathlib import Path

import pygame
import tkinter as tk
import yaml
from tkinter import filedialog

from ui.ui_types import UIButton
from ui.card import EntityCard
from ui.card_wiki import CardWikiRenderer
from ui.schema_card import SchemaCard
from ui.timeline_ui import TimelineUI
from world.schema_loader import SchemaLoader


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

    CANONICAL_LOCATION_CLASSES = (
        "cluster",
        "star_system",
        "star",
        "planet",
        "moon",
        "continent",
        "country",
        "region",
        "city",
        "site",
        "building",
        "room",
    )

    LINE_HEIGHT = 20
    OUTER_MARGIN = 16
    HEADER_H = 54
    TIMELINE_DEFAULT_H = 132
    TIMELINE_GAP = 10
    TIMELINE_SPLITTER_H = 8
    INNER_GAP = 14
    LEFT_RATIO = 0.30
    MIN_TIMELINE_PANEL_H = 96
    MIN_CONTENT_H = 180
    BROWSER_SEARCH_H = 24
    BROWSER_FILTER_H = 20
    BROWSER_CONTROL_GAP = 6
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    DRAFT_CACHE_PATH = PROJECT_ROOT / ".cache" / "card_drafts.json"
    ABSTRACT_SCHEMA_NAMES = {"entity_core", "entity_base", "core", "base"}
    TEMPLATE_PICKER_ROW_H = 34
    CARD_TYPE_PICKER_ROW_H = 26
    IDEA_GENERIC_FIELDS = {
        "pretty_name",
        "name",
        "description",
        "notes",
        "wiki_entry",
        "card_color",
        "card_header_color",
        "wiki_field_colors",
        "tags",
        "start_year",
        "start_event",
        "end_year",
        "end_event",
        "derived_from",
        "parents",
        "related",
        "wiki_mentions",
        "offspring",
        "placeholders",
        "entry_status",
    }
    LEGACY_IDEA_FIELDS = {
        "idea_class",
        "related_entities",
        "parent_entity",
        "source",
        "decision_status",
        "card_image",
        "design_image",
        "card_image_front",
        "card_image_side",
        "card_image_top",
        "image_path",
        "image",
        "derived_from_ideas",
        "parent_ideas",
        "related_ideas",
        "media_layers",
    }

    def __init__(self):
        self.layout = None
        self.browser_items = []
        self.browser_hitboxes = []
        self.browser_toggle_hitboxes = []
        self.browser_search_rect = None
        self.browser_filter_hitboxes = []
        self.cards = []

        self.world_model = None
        self.selected_entity_id = None
        self.repository_scope_entity_id = None
        self.repository_scope_label = None
        self.header_button = None
        self.random_entry_button = None
        self.random_unfinished_button = None
        self.random_task_button = None
        self.new_entry_button = None
        self.relation_touch_decrease_button = None
        self.relation_touch_value_button = None
        self.relation_touch_increase_button = None
        self.template_picker_rect = None
        self.template_button_hitboxes = []
        self.template_quick_button_hitboxes = []
        self.template_picker_visible_rows = []
        self.template_picker_total_rows = 0
        self.template_picker_status = ""
        self.show_template_picker = False
        self.template_picker_scroll = 0
        self.template_picker_search_rect = None
        self.template_picker_search_query = ""
        self.template_picker_search_active = False
        self.template_picker_mode = "create"
        self.template_picker_context = {}
        self.entry_name_prompt = None
        self.pending_new_entry_name = None
        self.schema_entry_templates = self._load_schema_entry_templates()
        self.browser_scroll = 0
        self.browser_search_query = ""
        self.browser_search_active = False
        self.browser_filter_dataset = "all"
        self.browser_filter_incomplete_only = False
        self.relation_link_target = None
        self.relation_link_status = ""
        self.canvas_relation_link_source_id = None
        self.canvas_relation_status = ""
        self.relation_tree_touch_degree = 2
        self.relation_tree_min_touch_degree = 1
        self.relation_tree_max_touch_degree = 6
        self.relation_tree_neighbor_cache = {}
        self.canvas_relation_edges = []

        self.canvas_offset_x = 0
        self.canvas_offset_y = 0
        self.canvas_content_width = 0
        self.canvas_content_height = 0
        self.canvas_zoom = 1.0
        self.canvas_min_zoom = 0.35
        self.canvas_max_zoom = 2.5
        self.active_canvas_pan = False
        self.canvas_pan_start_mouse = None
        self.canvas_pan_start_offset = None

        self.active_card_drag_id = None
        self.active_card_resize_id = None
        self.active_card_color_slider = None
        self.card_drag_mouse_offset = (0, 0)
        self.card_resize_start_mouse = None
        self.card_resize_start_size = None
        self.card_resize_start_position = None
        self.card_resize_edges = None

        self.browser_tree_state = {
            "locations": {
                "system_sol": True,
                "body_sol": True,
            }
        }

        self.font_for_layout = None
        self.timeline_ui = TimelineUI()
        self.timeline_panel_height = self.TIMELINE_DEFAULT_H
        self.timeline_splitter_rect = pygame.Rect(0, 0, 0, 0)
        self.active_timeline_resize = False
        self.timeline_resize_start_mouse_y = None
        self.timeline_resize_start_height = None
        self.timeline_edit_target = None
        self.active_timeline_pan = False
        self.timeline_pan_last_mouse_x = None
        self.app_width = 0
        self.app_height = 0
        self.schema_loader = SchemaLoader()
        self.schema_field_usage = self._build_schema_field_usage()
        self.card_drafts = self._load_card_drafts()

    def reset(self):
        """
        Reset transient rebuild state, but keep persistent browser/card state.
        """
        self.layout = None
        self.browser_items = []
        self.browser_hitboxes = []
        self.browser_toggle_hitboxes = []
        self.browser_search_rect = None
        self.browser_filter_hitboxes = []
        self.world_model = None
        self.repository_scope_entity_id = None
        self.repository_scope_label = None
        self.header_button = None
        self.random_entry_button = None
        self.random_unfinished_button = None
        self.random_task_button = None
        self.new_entry_button = None
        self.relation_touch_decrease_button = None
        self.relation_touch_value_button = None
        self.relation_touch_increase_button = None
        self.relation_tree_neighbor_cache = {}
        self.canvas_relation_edges = []
        self.template_picker_rect = None
        self.template_button_hitboxes = []
        self.template_quick_button_hitboxes = []
        self.template_picker_visible_rows = []
        self.template_picker_total_rows = 0
        self.template_picker_search_rect = None
        self.template_picker_search_active = False

    def _clamp_timeline_panel_height(self, app_height, timeline_h=None):
        if timeline_h is None:
            timeline_h = self.timeline_panel_height

        max_timeline_h = max(
            self.MIN_TIMELINE_PANEL_H,
            app_height - self.OUTER_MARGIN * 2 - self.HEADER_H - self.MIN_CONTENT_H,
        )
        return max(self.MIN_TIMELINE_PANEL_H, min(max_timeline_h, int(timeline_h)))

    def _refresh_layout_geometry(self):
        if self.app_width <= 0 or self.app_height <= 0:
            return

        self.layout = self._build_layout(self.app_width, self.app_height)
        self._build_header_button()
        self._rebuild_browser_hitboxes()

        self._refresh_timeline_items()
        self._relayout_cards()

    def _refresh_timeline_items(self):
        if self.layout is None:
            return

        timeline_rect = self.layout["timeline_rect"]
        self.timeline_ui.set_rect(timeline_rect)
        self.timeline_ui.set_font(self.font_for_layout)
        timeline_items = self.world_model.get_timeline_items() if self.world_model is not None else []
        self.timeline_ui.set_open_canvas_entity_ids(card.get("entity_id") for card in self.cards)
        self.timeline_ui.set_items(timeline_items)
        self.timeline_ui.rebuild_layout()

    def _close_wiki_link_picker(self, card):
        card["wiki_link_picker_open"] = False
        card["wiki_link_query"] = ""
        card["wiki_link_matches"] = []
        card["wiki_link_selected_index"] = 0
        card["wiki_link_replace_range"] = None

    def _build_wiki_link_matches(self, query_text):
        if self.world_model is None:
            return []

        normalized_query = (query_text or "").strip().lower()
        matches = []

        for entity in self.world_model.loader.entities.values():
            entity_id = entity.get("id")
            if not entity_id:
                continue

            pretty_name = self._entity_display_label(entity, fallback=entity_id)
            haystack = " ".join(
                [
                    str(pretty_name),
                    str(entity_id),
                    str(entity.get("common_name", "")),
                    str(entity.get("binomial_name", "")),
                    str(entity.get("name", "")),
                ]
            ).lower()
            if normalized_query and normalized_query not in haystack:
                continue

            matches.append(
                {
                    "id": entity_id,
                    "pretty_name": str(pretty_name),
                    "dataset": entity.get("_dataset", ""),
                    "entity_type": entity.get("type", "entity"),
                    "start_year": self._coerce_card_year(entity.get("start_year") if entity.get("start_year") is not None else entity.get("year")),
                    "end_year": self._coerce_card_year(entity.get("end_year")),
                }
            )

        matches.sort(key=lambda item: (item["pretty_name"].lower(), item["id"]))
        return matches[:12]

    def _known_entities_for_matching(self):
        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        entities = getattr(loader, "entities", None)
        if isinstance(entities, dict):
            return [
                entity for entity in entities.values()
                if isinstance(entity, dict)
            ]
        return []

    def _entity_match_tokens(self, entity):
        tokens = []
        for value in (
            entity.get("id"),
            self._entity_display_label(entity, fallback=entity.get("id")),
            entity.get("pretty_name"),
            entity.get("name"),
            entity.get("common_name"),
            entity.get("binomial_name"),
        ):
            text = str(value or "").strip()
            if text and text.lower() not in tokens:
                tokens.append(text.lower())
        return tokens

    def _resolve_wiki_mention_ref(self, link_text):
        raw_text = str(link_text or "").strip()
        if not raw_text:
            return ""

        if self.world_model is not None:
            entity = self.world_model.get_entity(raw_text)
            if isinstance(entity, dict) and entity.get("id"):
                return str(entity["id"])

        normalized = raw_text.lower()
        for entity in self._known_entities_for_matching():
            if normalized in self._entity_match_tokens(entity):
                entity_id = entity.get("id")
                if entity_id:
                    return str(entity_id)

        return raw_text

    def _wiki_mentions_from_text(self, wiki_text):
        mentions = []
        seen = set()
        for link_text in CardWikiRenderer.extract_link_refs(wiki_text):
            mention = self._resolve_wiki_mention_ref(link_text)
            if not mention or mention in seen:
                continue
            seen.add(mention)
            mentions.append(mention)
        return mentions

    def _sync_card_wiki_mentions(self, card, wiki_text=None):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return False

        if wiki_text is None:
            if (
                card is not None
                and card.get("active_edit_field") == "wiki_entry"
                and "edit_buffer" in card
            ):
                wiki_text = card.get("edit_buffer", "")
            else:
                wiki_text = entity.get("wiki_entry", "")

        mentions = self._wiki_mentions_from_text(wiki_text)
        if entity.get("wiki_mentions") == mentions:
            return False
        entity["wiki_mentions"] = mentions
        return True

    def _close_relation_picker(self, card):
        card["relation_picker_open"] = False
        card["relation_picker_query"] = ""
        card["relation_picker_matches"] = []
        card["relation_picker_selected_index"] = 0
        card["relation_picker_hitboxes"] = []

    def _is_species_entity(self, entity, dataset_name=None):
        if not isinstance(entity, dict):
            return False
        dataset = dataset_name or entity.get("_dataset")
        return dataset == "species" or entity.get("type") == "species"

    def _species_name_parts(self, entity):
        common_name = str(entity.get("common_name") or "").strip()
        binomial_name = str(entity.get("binomial_name") or "").strip()

        if not common_name:
            pretty_name = str(entity.get("pretty_name") or "").strip()
            if " - " in pretty_name:
                common_name = pretty_name.split(" - ", 1)[0].strip()
            elif pretty_name and pretty_name != entity.get("id"):
                common_name = pretty_name

        if not binomial_name:
            legacy_name = str(entity.get("name") or "").strip()
            if legacy_name and legacy_name != common_name:
                binomial_name = legacy_name
            else:
                pretty_name = str(entity.get("pretty_name") or "").strip()
                if " - " in pretty_name:
                    binomial_name = pretty_name.split(" - ", 1)[1].strip()

        return common_name, binomial_name

    def _species_display_label(self, entity):
        common_name, binomial_name = self._species_name_parts(entity)
        if common_name and binomial_name:
            return f"{common_name} - {binomial_name}"
        if common_name:
            return common_name
        if binomial_name:
            return binomial_name
        return str(entity.get("id") or "Unknown Species")

    def _entity_display_label(self, entity, fallback=None):
        if self._is_species_entity(entity):
            return self._species_display_label(entity)
        return str(
            entity.get("pretty_name")
            or entity.get("name")
            or fallback
            or entity.get("id")
            or "unknown"
        )

    def _species_id_from_binomial(self, binomial_name):
        slug_source = str(binomial_name or "").strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "_", slug_source).strip("_")
        return f"spec_{slug}" if slug else ""

    def _slug_from_text(self, text):
        slug_source = str(text or "").strip().lower()
        return re.sub(r"[^a-z0-9]+", "_", slug_source).strip("_")

    def _sanitize_entity_id(self, entity_id):
        return self._slug_from_text(entity_id)

    def _entity_id_from_name(self, dataset_name, entity_type, name, template=None):
        slug = self._slug_from_text(name)
        if not slug:
            return ""

        prefix = (
            template.get("id_prefix")
            if isinstance(template, dict) and template.get("id_prefix")
            else self._template_id_prefix(dataset_name, entity_type=entity_type)
        )
        prefix = self._sanitize_entity_id(prefix)
        if prefix and not slug.startswith(f"{prefix}_"):
            return f"{prefix}_{slug}"
        return slug

    def _entity_id_from_entity_name(self, entity, template=None):
        if not isinstance(entity, dict):
            return ""
        dataset_name = entity.get("_dataset", entity.get("type"))
        entity_type = entity.get("type") or self._template_entity_type(dataset_name, template)
        name = (
            entity.get("binomial_name")
            or entity.get("pretty_name")
            or entity.get("name")
            or entity.get("common_name")
        )
        return self._entity_id_from_name(dataset_name, entity_type, name, template=template)

    def _unique_entity_id(self, requested_id, current_id=None):
        requested_id = self._sanitize_entity_id(requested_id)
        if not requested_id:
            return ""

        existing_ids = set(self.world_model.loader.entities.keys()) if self.world_model is not None else set()
        existing_ids.update(self.card_drafts.keys())
        if current_id:
            existing_ids.discard(str(current_id))

        if requested_id not in existing_ids:
            return requested_id

        index = 2
        while True:
            candidate = f"{requested_id}_{index}"
            if candidate not in existing_ids:
                return candidate
            index += 1

    def _normalize_entity_id_for_save(self, entity, current_id=None, template=None):
        if not isinstance(entity, dict):
            return ""

        requested_id = self._sanitize_entity_id(entity.get("id"))
        if not requested_id:
            requested_id = self._entity_id_from_entity_name(entity, template=template)
        if not requested_id:
            return ""

        return self._unique_entity_id(requested_id, current_id=current_id)

    def _normalize_species_entity(self, entity):
        if not self._is_species_entity(entity):
            return "", ""
        common_name, binomial_name = self._species_name_parts(entity)
        entity["common_name"] = common_name
        entity["binomial_name"] = binomial_name
        entity["type"] = "species"
        entity["_dataset"] = "species"
        entity.pop("pretty_name", None)
        entity.pop("name", None)
        return common_name, binomial_name

    def _sync_species_identity(self, card):
        entity = self._entity_for_card(card)
        if not self._is_species_entity(entity):
            return False

        common_name, binomial_name = self._normalize_species_entity(entity)

        old_id = str(entity.get("id") or card.get("entity_id") or "")
        generated_id = self._species_id_from_binomial(binomial_name)
        if generated_id:
            new_id = self._unique_entity_id(generated_id, current_id=old_id)
            if new_id and new_id != old_id:
                pending = card.get("pending_entity_id_change")
                previous_id = pending.get("old") if isinstance(pending, dict) else old_id
                card["pending_entity_id_change"] = {
                    "old": previous_id,
                    "new": new_id,
                }
                entity["id"] = new_id

        card["title"] = common_name or binomial_name or entity.get("id", "Unknown Species")
        card["subtitle"] = self._card_subtitle_for_entity(entity)
        return True

    def _open_relation_picker(self, card):
        card["relation_picker_open"] = True
        card["relation_picker_query"] = ""
        card["relation_picker_matches"] = self._build_wiki_link_matches("")
        card["relation_picker_selected_index"] = 0
        card["relation_picker_hitboxes"] = []

    def _insert_relation_from_picker(self, card, match_index=None):
        matches = card.get("relation_picker_matches", [])
        if not matches:
            return False

        if match_index is None:
            match_index = card.get("relation_picker_selected_index", 0)
        match_index = max(0, min(match_index, len(matches) - 1))

        card_view = card.get("card_view")
        if card_view is None:
            return False

        inserted = card_view.insert_relation_reference(card, matches[match_index]["id"])
        if inserted:
            card["relation_picker_query"] = ""
            card["relation_picker_matches"] = self._build_wiki_link_matches("")
            card["relation_picker_selected_index"] = 0
        return inserted

    def _handle_relation_picker_keydown(self, card, event):
        if not card.get("relation_picker_open", False):
            return False

        card_view = card.get("card_view")
        active_field = card.get("active_edit_field")
        if card_view is None or not card_view.is_relation_edit_field(active_field):
            self._close_relation_picker(card)
            return False

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and (event.mod & (pygame.KMOD_CTRL | pygame.KMOD_SHIFT)):
            self._close_relation_picker(card)
            return card_view.commit_edit_field(card)

        if event.key == pygame.K_ESCAPE:
            self._close_relation_picker(card)
            return True

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self._insert_relation_from_picker(card)

        matches = card.get("relation_picker_matches", [])
        if event.key == pygame.K_UP and matches:
            card["relation_picker_selected_index"] = max(0, card.get("relation_picker_selected_index", 0) - 1)
            return True

        if event.key == pygame.K_DOWN and matches:
            card["relation_picker_selected_index"] = min(len(matches) - 1, card.get("relation_picker_selected_index", 0) + 1)
            return True

        if event.key == pygame.K_BACKSPACE:
            card["relation_picker_query"] = card.get("relation_picker_query", "")[:-1]
            card["relation_picker_matches"] = self._build_wiki_link_matches(card["relation_picker_query"])
            card["relation_picker_selected_index"] = 0
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            card["relation_picker_query"] = card.get("relation_picker_query", "") + text
            card["relation_picker_matches"] = self._build_wiki_link_matches(card["relation_picker_query"])
            card["relation_picker_selected_index"] = 0
            return True

        return False

    def _open_wiki_link_picker(self, card):
        query_text, replace_start, replace_end = self._wiki_link_seed_from_cursor(card)
        card["wiki_link_picker_open"] = True
        card["wiki_link_query"] = query_text
        card["wiki_link_replace_range"] = (replace_start, replace_end)
        card["wiki_link_matches"] = self._build_wiki_link_matches(query_text)
        card["wiki_link_selected_index"] = 0

    def _wiki_link_seed_from_cursor(self, card):
        buffer_text = str(card.get("edit_buffer", ""))
        cursor = max(0, min(len(buffer_text), int(card.get("edit_cursor", len(buffer_text)))))
        start = cursor
        while start > 0 and (buffer_text[start - 1].isalnum() or buffer_text[start - 1] in {"_", "-"}):
            start -= 1
        end = cursor
        while end < len(buffer_text) and (buffer_text[end].isalnum() or buffer_text[end] in {"_", "-"}):
            end += 1

        query = buffer_text[start:end].strip()
        if not query:
            start = cursor
            end = cursor
        return query, start, end

    def _insert_wiki_link_from_picker(self, card):
        matches = card.get("wiki_link_matches", [])
        if not matches:
            return False

        selected_index = max(0, min(card.get("wiki_link_selected_index", 0), len(matches) - 1))
        entity_id = matches[selected_index]["id"]
        insertion = f"[[{entity_id}]]"
        current_buffer = str(card.get("edit_buffer", ""))
        cursor = max(0, min(len(current_buffer), int(card.get("edit_cursor", len(current_buffer)))))
        replace_range = card.get("wiki_link_replace_range", (cursor, cursor))
        try:
            replace_start, replace_end = replace_range
        except (TypeError, ValueError):
            replace_start, replace_end = cursor, cursor
        replace_start = max(0, min(len(current_buffer), int(replace_start)))
        replace_end = max(replace_start, min(len(current_buffer), int(replace_end)))

        before = current_buffer[:replace_start]
        after = current_buffer[replace_end:]
        leading_space = " " if before and not before.endswith((" ", "\n")) else ""
        trailing_space = " " if after and not after.startswith((" ", "\n", ".", ",", ";", ":", ")", "]")) else ""
        card["edit_buffer"] = f"{before}{leading_space}{insertion}{trailing_space}{after}"
        card["edit_cursor"] = len(before) + len(leading_space) + len(insertion) + len(trailing_space)
        card["last_edit_action"] = "draft"
        self._save_card_draft(card)
        self._close_wiki_link_picker(card)
        return True

    def _handle_wiki_link_picker_keydown(self, card, event):
        if not card.get("wiki_link_picker_open", False):
            return False

        if event.key == pygame.K_ESCAPE:
            self._close_wiki_link_picker(card)
            return True

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self._insert_wiki_link_from_picker(card)

        matches = card.get("wiki_link_matches", [])
        if event.key == pygame.K_UP and matches:
            card["wiki_link_selected_index"] = max(0, card.get("wiki_link_selected_index", 0) - 1)
            return True

        if event.key == pygame.K_DOWN and matches:
            card["wiki_link_selected_index"] = min(len(matches) - 1, card.get("wiki_link_selected_index", 0) + 1)
            return True

        if event.key == pygame.K_BACKSPACE:
            card["wiki_link_query"] = card.get("wiki_link_query", "")[:-1]
            card["wiki_link_matches"] = self._build_wiki_link_matches(card["wiki_link_query"])
            card["wiki_link_selected_index"] = 0
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            card["wiki_link_query"] = card.get("wiki_link_query", "") + text
            card["wiki_link_matches"] = self._build_wiki_link_matches(card["wiki_link_query"])
            card["wiki_link_selected_index"] = 0
            return True

        return False

    def _build_layout(self, app_width, app_height):
        timeline_h = self._clamp_timeline_panel_height(app_height)
        self.timeline_panel_height = timeline_h

        content_x = self.OUTER_MARGIN
        content_y = self.OUTER_MARGIN + self.HEADER_H + timeline_h
        content_w = app_width - self.OUTER_MARGIN * 2
        content_h = app_height - content_y - self.OUTER_MARGIN

        left_w = int(content_w * self.LEFT_RATIO)
        right_w = content_w - left_w - self.INNER_GAP

        left_rect = pygame.Rect(content_x, content_y, left_w, content_h)
        right_rect = pygame.Rect(content_x + left_w + self.INNER_GAP, content_y, right_w, content_h)

        timeline_rect = pygame.Rect(
            self.OUTER_MARGIN,
            self.OUTER_MARGIN + self.HEADER_H,
            content_w,
            max(1, timeline_h - self.TIMELINE_GAP),
        )

        splitter_y = timeline_rect.bottom + max(1, (self.TIMELINE_GAP - self.TIMELINE_SPLITTER_H) // 2)
        self.timeline_splitter_rect = pygame.Rect(
            self.OUTER_MARGIN,
            splitter_y,
            content_w,
            self.TIMELINE_SPLITTER_H,
        )

        return {
            "header_rect": pygame.Rect(self.OUTER_MARGIN, self.OUTER_MARGIN, content_w, self.HEADER_H),
            "timeline_rect": timeline_rect,
            "timeline_splitter_rect": self.timeline_splitter_rect,
            "left_rect": left_rect,
            "right_rect": right_rect,
        }

    def _build_header_button(self):
        if self.layout is None:
            self.header_button = None
            self.random_entry_button = None
            self.random_unfinished_button = None
            self.random_task_button = None
            self.new_entry_button = None
            self.relation_touch_decrease_button = None
            self.relation_touch_value_button = None
            self.relation_touch_increase_button = None
            return

        header_rect = self.layout["header_rect"]
        self.header_button = UIButton(
            button_id="launch_vehicle_test",
            label="Launch Vehicle Test",
            rect=pygame.Rect(header_rect.right - 220, header_rect.y + 11, 200, 30),
            visible=True,
            enabled=True,
        )

        right_rect = self.layout["right_rect"]
        button_y = right_rect.y + 8
        button_gap = 8
        button_right = right_rect.right - 22
        self.new_entry_button = UIButton(
            button_id="knowledge_new_entry",
            label="New Entry",
            rect=pygame.Rect(button_right - 96, button_y, 96, 28),
            visible=True,
            enabled=True,
        )
        button_right = self.new_entry_button.rect.x - button_gap
        self.random_task_button = UIButton(
            button_id="knowledge_random_task",
            label="Random Task",
            rect=pygame.Rect(button_right - 106, button_y, 106, 28),
            visible=True,
            enabled=True,
        )
        button_right = self.random_task_button.rect.x - button_gap
        self.random_unfinished_button = UIButton(
            button_id="knowledge_random_unfinished",
            label="Random Unfinished",
            rect=pygame.Rect(button_right - 136, button_y, 136, 28),
            visible=True,
            enabled=True,
        )
        button_right = self.random_unfinished_button.rect.x - button_gap
        self.random_entry_button = UIButton(
            button_id="knowledge_random_entry",
            label="Random Entry",
            rect=pygame.Rect(button_right - 104, button_y, 104, 28),
            visible=True,
            enabled=True,
        )
        button_right = self.random_entry_button.rect.x - button_gap
        touch_value_w = 76
        touch_step_w = 28
        self.relation_touch_increase_button = UIButton(
            button_id="knowledge_relation_touch_increase",
            label="+",
            rect=pygame.Rect(button_right - touch_step_w, button_y, touch_step_w, 28),
            visible=True,
            enabled=self.relation_tree_touch_degree < self.relation_tree_max_touch_degree,
        )
        button_right = self.relation_touch_increase_button.rect.x - 4
        self.relation_touch_value_button = UIButton(
            button_id="knowledge_relation_touch_value",
            label=f"Touch {self.relation_tree_touch_degree}",
            rect=pygame.Rect(button_right - touch_value_w, button_y, touch_value_w, 28),
            visible=True,
            enabled=False,
        )
        button_right = self.relation_touch_value_button.rect.x - 4
        self.relation_touch_decrease_button = UIButton(
            button_id="knowledge_relation_touch_decrease",
            label="-",
            rect=pygame.Rect(button_right - touch_step_w, button_y, touch_step_w, 28),
            visible=True,
            enabled=self.relation_tree_touch_degree > self.relation_tree_min_touch_degree,
        )
        self._build_template_picker_hitboxes()

    def _set_relation_tree_touch_degree(self, value):
        try:
            degree = int(value)
        except (TypeError, ValueError):
            degree = self.relation_tree_touch_degree
        degree = max(self.relation_tree_min_touch_degree, min(self.relation_tree_max_touch_degree, degree))
        if degree == self.relation_tree_touch_degree:
            return False
        self.relation_tree_touch_degree = degree
        self._build_header_button()
        return True

    def _font_line_height(self, font=None):
        font = font or self.font_for_layout
        if font is None:
            return self.LINE_HEIGHT
        return max(self.LINE_HEIGHT, int(font.get_linesize()) + 4)

    def _ellipsize_text(self, text, font, max_width):
        text = str(text or "")
        if font is None or font.size(text)[0] <= max_width:
            return text

        suffix = "..."
        suffix_w = font.size(suffix)[0]
        available_w = max(0, max_width - suffix_w)
        trimmed = text
        while trimmed and font.size(trimmed)[0] > available_w:
            trimmed = trimmed[:-1]
        return f"{trimmed}{suffix}" if trimmed else suffix

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
        return [
            by_dataset[dataset_name]
            for dataset_name in ("tasks", "ideas")
            if dataset_name in by_dataset
        ]

    def _schema_display_label(self, name):
        text = str(name or "entry").replace(".yaml", "")
        text = text.replace("_", " ").strip()
        return text.title() if text else "Entry"

    def _normalize_schema_name(self, name):
        text = str(name or "").strip().lower()
        if text.endswith(".yaml") or text.endswith(".yml"):
            text = os.path.splitext(text)[0]
        text = text.replace("-", "_").replace(" ", "_")
        if text.startswith("index0_"):
            text = text[len("index0_"):]
        if text.endswith("_schema"):
            text = text[:-len("_schema")]
        return text

    def _schema_file_base(self, schema_path):
        stem = Path(schema_path).stem
        if stem.startswith("schema_"):
            stem = stem[len("schema_"):]
        return self._normalize_schema_name(stem)

    def _build_schema_field_usage(self):
        """
        Count schema field references in simulation modules.

        Counts are grouped by top-level simulation package, so a field used by
        multiple files in simulations/vehicle still reads as one simulation use.
        """
        if not hasattr(self, "schema_loader"):
            return {}

        simulation_dir = self.PROJECT_ROOT / "simulations"
        if not simulation_dir.exists():
            return {}

        field_names = set()
        for schema in self.schema_loader.schemas.values():
            fields = schema.get("fields", {}) if isinstance(schema, dict) else {}
            field_names.update(str(field_name) for field_name in fields.keys())

        usage_modules_by_field = {field_name: set() for field_name in field_names}

        for path in simulation_dir.rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue

            rel_parts = path.relative_to(simulation_dir).parts
            simulation_name = rel_parts[0] if rel_parts else path.stem

            for field_name in field_names:
                pattern = rf"(?<![A-Za-z0-9_]){re.escape(field_name)}(?![A-Za-z0-9_])"
                if re.search(pattern, text):
                    usage_modules_by_field[field_name].add(simulation_name)

        return {
            field_name: {
                "count": len(modules),
                "modules": sorted(modules),
            }
            for field_name, modules in usage_modules_by_field.items()
        }

    def _schema_card_id(self, schema_name):
        return f"schema::{schema_name}"

    def _schema_name_from_card_id(self, card_id):
        prefix = "schema::"
        if isinstance(card_id, str) and card_id.startswith(prefix):
            return card_id[len(prefix):]
        return None

    def _singularize_name(self, name):
        text = self._normalize_schema_name(name)
        if text in {"species", "logistics", "production"}:
            return text
        if text.endswith("ies") and len(text) > 3:
            return f"{text[:-3]}y"
        if text.endswith("s") and not text.endswith("ss"):
            return text[:-1]
        return text

    def _pluralize_name(self, name):
        text = self._normalize_schema_name(name)
        if text in {"species", "logistics", "production"}:
            return text
        if text.endswith("y") and len(text) > 1:
            return f"{text[:-1]}ies"
        if text.endswith("s"):
            return text
        return f"{text}s"

    def _entry_dataset_names(self):
        entry_dir = self.PROJECT_ROOT / "entries"
        if not entry_dir.exists():
            return set()
        return {
            path.stem
            for path in entry_dir.glob("*.yml")
        } | {
            path.stem
            for path in entry_dir.glob("*.yaml")
        }

    def _dataset_name_for_schema(self, schema_name, file_base, existing_datasets):
        candidates = []
        for name in (schema_name, file_base):
            normalized = self._normalize_schema_name(name)
            if not normalized:
                continue
            for candidate in (
                normalized,
                self._pluralize_name(normalized),
                self._singularize_name(normalized),
            ):
                if candidate and candidate not in candidates:
                    candidates.append(candidate)

        for candidate in candidates:
            if candidate in existing_datasets:
                return candidate

        return file_base or self._pluralize_name(schema_name)

    def _entity_type_for_schema(self, schema_name, dataset_name):
        schema_type = self._normalize_schema_name(schema_name)
        dataset_type = self._singularize_name(dataset_name)
        if schema_type and schema_type not in self.ABSTRACT_SCHEMA_NAMES:
            if schema_type in {"behaviors", "cities", "components", "locations", "materials", "systems", "vehicles"}:
                return self._singularize_name(schema_type)
            return schema_type
        return dataset_type

    def _template_id_prefix(self, dataset_name, entity_type=None):
        mapping = {
            "behaviors": "beh",
            "cities": "city",
            "components": "comp",
            "conflicts": "conf",
            "cultural_aspects": "cultasp",
            "cultures": "cult",
            "events": "evt",
            "factions": "fac",
            "formations": "form",
            "ideas": "idea",
            "institutions": "inst",
            "items": "item",
            "locations": "loc",
            "logistics": "log",
            "markets": "mkt",
            "materials": "mat",
            "people": "person",
            "pops": "pop",
            "producers": "prod",
            "production": "prod",
            "spatial_features": "spat",
            "species": "spec",
            "systems": "sys",
            "technologies": "tech",
            "vehicles": "veh",
            "years": "year",
        }
        if dataset_name in mapping:
            return mapping[dataset_name]
        source = self._normalize_schema_name(entity_type or dataset_name)
        parts = [part for part in source.split("_") if part]
        if len(parts) > 1:
            return "".join(part[:3] for part in parts)[:10]
        return source[:6] or "entry"

    def _load_schema_entry_templates(self):
        schema_dir = self.PROJECT_ROOT / "schemas"
        if not schema_dir.exists():
            return []

        existing_datasets = self._entry_dataset_names()
        templates = []
        for schema_path in sorted(schema_dir.glob("*.y*ml")):
            try:
                with open(schema_path, "r", encoding="utf-8") as f:
                    schema = yaml.safe_load(f) or {}
            except (OSError, yaml.YAMLError):
                continue

            file_base = self._schema_file_base(schema_path)
            metadata_name = (schema.get("metadata") or {}).get("name")
            raw_schema_name = schema.get("schema") or metadata_name or file_base
            schema_name = self._normalize_schema_name(raw_schema_name)
            if schema_name in self.ABSTRACT_SCHEMA_NAMES or file_base == "core":
                continue

            dataset_name = self._dataset_name_for_schema(schema_name, file_base, existing_datasets)
            if dataset_name == "spatial_features":
                continue
            entity_type = self._entity_type_for_schema(schema_name, dataset_name)
            label = self._schema_display_label(entity_type)
            templates.append(
                {
                    "schema_name": schema_name,
                    "schema_path": str(schema_path),
                    "schema": schema,
                    "dataset_name": dataset_name,
                    "entity_type": entity_type,
                    "label": label,
                    "id_prefix": self._template_id_prefix(dataset_name, entity_type=entity_type),
                }
            )

        preferred = {"tasks": 0, "ideas": 1}
        templates.sort(
            key=lambda item: (
                preferred.get(item.get("dataset_name"), 10),
                item["label"].lower(),
                item["dataset_name"],
            )
        )
        return templates

    def _template_by_dataset(self, dataset_name):
        for template in self.schema_entry_templates:
            if template.get("dataset_name") == dataset_name:
                return template
        return None

    def _template_for_relation_target(self, target):
        normalized = self._normalize_schema_name(target)
        if not normalized:
            return None

        if normalized in {"entity", "entity_core", "core", "any"}:
            normalized = "ideas"

        candidates = []
        for candidate in (
            normalized,
            self._pluralize_name(normalized),
            self._singularize_name(normalized),
        ):
            if candidate and candidate not in candidates:
                candidates.append(candidate)

        for template in self.schema_entry_templates:
            template_names = {
                self._normalize_schema_name(template.get("dataset_name")),
                self._normalize_schema_name(template.get("entity_type")),
                self._normalize_schema_name(template.get("schema_name")),
            }
            template_names.update(self._pluralize_name(name) for name in list(template_names) if name)
            template_names.update(self._singularize_name(name) for name in list(template_names) if name)
            if any(candidate in template_names for candidate in candidates):
                return template

        return self._template_by_dataset(self._pluralize_name(normalized)) or self._template_by_dataset(normalized)

    def _browser_header_extra_height(self):
        return 24 if self.relation_link_target is not None else 0

    def _relation_target_dataset_filter(self, target):
        if self.world_model is None:
            return "all"

        candidates = self._relation_target_candidates(target)
        if not candidates:
            return "all"

        dataset_names = set(self.world_model.get_dataset_names())
        for candidate in candidates:
            if candidate in dataset_names:
                return candidate
        return "all"

    def _relation_target_label(self, target):
        normalized = self._normalize_schema_name(target)
        if not normalized or normalized in {"entity", "entity_core", "core", "any"}:
            return "entry"
        return normalized.replace("_", " ")

    def _relation_target_candidates(self, target):
        normalized = self._normalize_schema_name(target)
        if not normalized or normalized in {"entity", "entity_core", "core", "any"}:
            return set()

        candidates = set()
        for candidate in (
            normalized,
            self._pluralize_name(normalized),
            self._singularize_name(normalized),
        ):
            if candidate:
                candidates.add(candidate)
        return candidates

    def _entity_matches_relation_target(self, entity, target):
        if not isinstance(entity, dict):
            return False

        candidates = self._relation_target_candidates(target)
        if not candidates:
            return True

        entity_names = set()
        for value in (
            entity.get("_dataset"),
            entity.get("type"),
            entity.get("system_role"),
            entity.get("body_class"),
            entity.get("location_class"),
            entity.get("vehicle_class"),
        ):
            normalized = self._normalize_schema_name(value)
            if not normalized:
                continue
            entity_names.add(normalized)
            entity_names.add(self._pluralize_name(normalized))
            entity_names.add(self._singularize_name(normalized))

        return bool(candidates & entity_names)

    def _browser_item_matches_relation_target(self, item):
        if self.relation_link_target is None or item.get("kind") not in {"entity", "tree_entity"}:
            return False
        if self.world_model is None:
            return False
        entity = self.world_model.get_entity(item.get("entity_id"))
        return self._entity_matches_relation_target(entity, self.relation_link_target.get("target"))

    def _conversion_templates(self):
        templates = [
            template
            for template in self.schema_entry_templates
            if template.get("dataset_name")
        ]
        templates.extend(self._existing_subclass_templates(templates))
        preferred = [
            "ideas",
            "vehicles",
            "locations",
            "systems",
            "components",
            "events",
            "factions",
            "technologies",
            "materials",
        ]
        preferred_index = {name: index for index, name in enumerate(preferred)}
        templates.sort(
            key=lambda template: (
                preferred_index.get(template.get("dataset_name"), len(preferred)),
                str(template.get("label", "")).lower(),
            )
        )
        return templates

    def _template_identity(self, template):
        return (
            template.get("dataset_name"),
            template.get("entity_type"),
            template.get("subclass_field"),
            template.get("subclass_value"),
        )

    def _subclass_fields_for_template(self, template):
        dataset_name = template.get("dataset_name")
        entity_type = template.get("entity_type")
        if dataset_name == "locations":
            return ["location_class"]
        if dataset_name == "systems":
            return ["system_class", "body_class"]

        fields = [
            f"{self._singularize_name(dataset_name)}_class",
            f"{entity_type}_class",
            "vehicle_class",
            "component_class",
            "idea_class",
            "faction_class",
            "producer_class",
            "institution_class",
            "city_class",
            "event_class",
            "item_class",
            "material_class",
            "species_class",
        ]
        deduped = []
        for field in fields:
            if field and field != "_class" and field not in deduped:
                deduped.append(field)
        return deduped

    def _existing_subclass_templates(self, base_templates):
        by_dataset = {
            template.get("dataset_name"): template
            for template in base_templates
            if template.get("dataset_name")
        }
        variants = []
        seen = set()

        for dataset_name, template in by_dataset.items():
            fields = self._subclass_fields_for_template(template)
            for field_key, subclass_value in self._canonical_subclass_values_for_template(template):
                identity = (dataset_name, template.get("entity_type"), subclass_value)
                if identity in seen:
                    continue
                seen.add(identity)
                variants.append(self._subclass_template_variant(template, field_key, subclass_value))

            if self.world_model is None:
                continue

            entities = self.world_model.get_entities_by_dataset(dataset_name)
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                for field_key in fields:
                    raw_value = entity.get(field_key)
                    if not isinstance(raw_value, str) or not raw_value.strip():
                        continue
                    subclass_value = raw_value.strip()
                    identity = (dataset_name, template.get("entity_type"), subclass_value)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    variants.append(self._subclass_template_variant(template, field_key, subclass_value))

        return variants

    def _canonical_subclass_values_for_template(self, template):
        if template.get("dataset_name") == "locations":
            return [
                ("location_class", location_class)
                for location_class in self.CANONICAL_LOCATION_CLASSES
            ]

        return []

    def _subclass_template_variant(self, template, field_key, subclass_value):
        variant = dict(template)
        variant["label"] = self._schema_display_label(subclass_value)
        variant["subclass_field"] = field_key
        variant["subclass_value"] = subclass_value
        variant["initial_fields"] = {
            **dict(template.get("initial_fields", {})),
            field_key: subclass_value,
        }
        return variant

    def _template_initial_fields(self, template, extra_fields=None):
        fields = {}
        if isinstance(template, dict):
            fields.update(dict(template.get("initial_fields", {})))
            subclass_field = template.get("subclass_field")
            subclass_value = template.get("subclass_value")
            if subclass_field and subclass_value not in (None, ""):
                fields[subclass_field] = subclass_value
        if isinstance(extra_fields, dict):
            fields.update(extra_fields)
        return fields

    def _template_picker_source_templates(self):
        return self._conversion_templates()

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
                option_w = self._template_picker_option_width(label, available_width, font=font)
                item = {
                    "label": label,
                    "template": template,
                    "width": option_w,
                }
                is_full_width = option_w >= available_width
                next_width = option_w if not current_items else current_width + gap + option_w
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
        quick_template_ids = {self._template_identity(template) for template in quick_templates}
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
        picker_h = min(max_picker_h, header_h + self.template_picker_total_rows * row_h + 8)
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
            button_w = min(96, (picker_w - 24 - button_gap) // max(1, len(quick_templates)))
            button_x = picker_x + 12
            for template in quick_templates:
                button_rect = pygame.Rect(button_x, quick_y, button_w, 24)
                self.template_quick_button_hitboxes.append((template, template["label"], button_rect))
                button_x += button_w + button_gap

        visible_rows = max(1, (picker_h - header_h - 8) // row_h)
        max_scroll = max(0, self.template_picker_total_rows - visible_rows)
        self.template_picker_scroll = max(0, min(max_scroll, self.template_picker_scroll))

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
                    item_w = max(40, min(button_rect.width - (item_x - button_rect.x), int(item.get("width", button_rect.width))))
                    item_rect = pygame.Rect(item_x, button_rect.y, item_w, button_rect.height)
                    item["rect"] = item_rect
                    template = item.get("template")
                    if template is not None:
                        self.template_button_hitboxes.append((template, item.get("label", ""), item_rect))
                    item_x = item_rect.right + 6
            button_y += row_h

    def _is_expanded(self, entity_id):
        location_state = self.browser_tree_state.setdefault("locations", {})
        legacy_state = self.browser_tree_state.get("systems", {})
        if entity_id in legacy_state and entity_id not in location_state:
            location_state[entity_id] = legacy_state[entity_id]
        return location_state.get(entity_id, False)

    def _set_expanded(self, entity_id, expanded):
        self.browser_tree_state.setdefault("locations", {})[entity_id] = expanded

    def _browser_dataset_filters(self):
        if self.world_model is None:
            return ["all", "schemas"]
        preferred = ["all", "schemas", "locations", "systems", "vehicles", "components", "events"]
        names = ["all"] + sorted(name for name in self.world_model.get_dataset_names() if name != "all")
        if "schemas" not in names:
            names.append("schemas")
        ordered = [name for name in preferred if name in names]
        ordered.extend(name for name in names if name not in ordered)
        return ordered

    def _format_browser_filter_label(self, filter_name):
        if filter_name == "all":
            return "All"
        return str(filter_name).replace("_", " ").title()

    def _matches_browser_filters(self, entity, dataset_name):
        if entity is None:
            return False

        if self.browser_filter_dataset != "all" and dataset_name != self.browser_filter_dataset:
            return False

        if self.browser_filter_incomplete_only and not self._entity_missing_scalar_count(entity, dataset_name):
            return False

        query = self.browser_search_query.strip().lower()
        if query:
            haystack = " ".join(
                [
                    self._entity_display_label(entity),
                    str(entity.get("common_name", "")),
                    str(entity.get("binomial_name", "")),
                    str(entity.get("pretty_name", "")),
                    str(entity.get("name", "")),
                    str(entity.get("id", "")),
                    str(entity.get("type", "")),
                ]
            ).lower()
            if query not in haystack:
                return False

        return True

    def _matches_schema_browser_filters(self, schema_name, schema):
        if self.browser_filter_dataset not in {"all", "schemas"}:
            return False

        query = self.browser_search_query.strip().lower()
        if not query:
            return True

        fields = schema.get("fields", {}) if isinstance(schema, dict) else {}
        haystack = " ".join(
            [
                str(schema_name),
                str(schema.get("schema", "")) if isinstance(schema, dict) else "",
                str(schema.get("extends", "")) if isinstance(schema, dict) else "",
                " ".join(str(field_name) for field_name in fields.keys()),
            ]
        ).lower()
        return query in haystack

    def _build_schema_browser_items(self):
        items = []

        for schema_name, schema in sorted(self.schema_loader.schemas.items()):
            if not self._matches_schema_browser_filters(schema_name, schema):
                continue

            field_count = len(schema.get("fields", {}) if isinstance(schema, dict) else {})
            items.append(
                {
                    "kind": "schema",
                    "entity_id": self._schema_card_id(schema_name),
                    "schema_name": schema_name,
                    "text": f"  {schema_name} [{field_count} fields]",
                    "missing_count": 0,
                    "is_incomplete": False,
                }
            )

        return items

    def _resolve_schema_for_entity(self, entity, dataset_name):
        candidates = []
        entity_type = entity.get("type")
        for name in (entity_type, dataset_name):
            if not name:
                continue
            normalized = str(name).strip().lower()
            if normalized and normalized not in candidates:
                candidates.append(normalized)
            if normalized.endswith("s"):
                singular = normalized[:-1]
                if singular and singular not in candidates:
                    candidates.append(singular)
            else:
                plural = f"{normalized}s"
                if plural not in candidates:
                    candidates.append(plural)

        for candidate in candidates:
            schema = self.schema_loader.get_schema(candidate)
            if schema:
                return schema
        return None

    def _collect_schema_fields(self, schema, seen=None):
        if not schema:
            return {}
        if seen is None:
            seen = set()
        schema_name = schema.get("schema")
        if schema_name in seen:
            return {}
        if schema_name:
            seen.add(schema_name)
        fields = {}
        extends_name = schema.get("extends")
        if extends_name:
            fields.update(self._collect_schema_fields(self.schema_loader.get_schema(extends_name), seen=seen))
        fields.update(schema.get("fields", {}))
        return fields

    def _entity_missing_scalar_count(self, entity, dataset_name):
        schema = self._resolve_schema_for_entity(entity, dataset_name)
        field_specs = self._collect_schema_fields(schema)
        if dataset_name == "ideas":
            field_specs = {
                key: value
                for key, value in field_specs.items()
                if key in self.IDEA_GENERIC_FIELDS or key in {"id", "type"}
            }
        if dataset_name == "species":
            field_specs = {
                key: value
                for key, value in field_specs.items()
                if key not in {"pretty_name", "name"}
            }
        missing = 0
        for field_key, spec in field_specs.items():
            if field_key in {"card_color", "card_header_color", "wiki_field_colors", "wiki_link_color"}:
                continue
            field_type = spec.get("type")
            if field_type not in {None, "string", "number", "text"}:
                continue
            value = entity.get(field_key)
            if value is None:
                missing += 1
            elif isinstance(value, str) and not value.strip():
                missing += 1
        return missing

    def _location_tree_entity_matches(self, entity, dataset_name):
        if entity is None:
            return False

        is_system_like = bool(entity.get("system_role"))
        if self.browser_filter_dataset == "systems" and not is_system_like:
            return False

        if self.browser_filter_dataset not in {"all", "locations", "systems"}:
            return False

        if self.browser_filter_incomplete_only and not self._entity_missing_scalar_count(entity, dataset_name):
            return False

        query = self.browser_search_query.strip().lower()
        if query:
            haystack = " ".join(
                [
                    self._entity_display_label(entity),
                    str(entity.get("common_name", "")),
                    str(entity.get("binomial_name", "")),
                    str(entity.get("pretty_name", "")),
                    str(entity.get("name", "")),
                    str(entity.get("id", "")),
                    str(entity.get("type", "")),
                    str(entity.get("system_role", "")),
                    str(entity.get("system_class", "")),
                    str(entity.get("body_class", "")),
                    str(entity.get("location_class", "")),
                    str(entity.get("location_role", "")),
                ]
            ).lower()
            if query not in haystack:
                return False

        return True

    def _location_tree_auto_reveal_descendants(self):
        return bool(self.browser_search_query.strip() or self.browser_filter_incomplete_only)

    def _location_tree_item(self, entity, dataset_name, depth, expandable, expanded, meta_label=None):
        label = self._entity_display_label(entity, fallback=entity.get("id", "unknown"))
        entity_class = meta_label or self._entity_class_label(dataset_name, entity)
        missing_count = self._entity_missing_scalar_count(entity, dataset_name)
        return {
            "kind": "tree_entity",
            "entity_id": entity.get("id"),
            "dataset_name": dataset_name,
            "text": label,
            "meta_text": f"[{entity_class}]",
            "missing_count": missing_count,
            "is_incomplete": missing_count > 0,
            "depth": depth,
            "expandable": expandable,
            "expanded": expanded,
        }

    def _canonical_location_class_key(self, entity):
        if not isinstance(entity, dict):
            return "entity"

        system_role = str(entity.get("system_role") or "").strip().lower()
        if system_role == "star_system":
            return "star_system"
        if system_role == "orbital_body":
            raw_class = entity.get("body_class") or entity.get("location_class") or "orbital_body"
        else:
            raw_class = (
                entity.get("location_class")
                or entity.get("system_class")
                or entity.get("body_class")
                or entity.get("type")
                or "entity"
            )

        class_key = str(raw_class or "entity").strip().lower().replace(" ", "_").replace("-", "_")
        class_aliases = {
            "stellar_system": "star_system",
            "starsystem": "star_system",
            "star_system": "star_system",
            "solar_system": "star_system",
            "orbital_body": "orbital_body",
            "celestial_body": "orbital_body",
        }
        return class_aliases.get(class_key, class_key)

    def _location_class_display_label(self, entity):
        class_key = self._canonical_location_class_key(entity)
        display_labels = {
            "star_system": "Star System",
            "orbital_body": "Orbital Body",
            "dwarf_planet": "Dwarf Planet",
            "island_chain": "Island Chain",
            "macro_site": "Macro Site",
            "internal_passage": "Internal Passage",
            "stellar_cluster": "Stellar Cluster",
            "galaxy_cluster": "Galaxy Cluster",
        }
        return display_labels.get(class_key, class_key.replace("_", " ").title())

    def _location_hierarchy_sort_key(self, entity):
        class_key = self._canonical_location_class_key(entity)
        class_rank = {
            "supercluster": 0,
            "galaxy_cluster": 5,
            "cluster": 8,
            "stellar_cluster": 10,
            "galaxy": 15,
            "star_system": 20,
            "system": 20,
            "star": 30,
            "orbital_body": 35,
            "planet": 40,
            "dwarf_planet": 41,
            "moon": 45,
            "asteroid": 46,
            "continent": 50,
            "ocean": 51,
            "sea": 52,
            "country": 60,
            "state": 61,
            "province": 62,
            "region": 65,
            "island_chain": 66,
            "atoll": 67,
            "city": 70,
            "settlement": 71,
            "site": 80,
            "macro_site": 80,
            "internal_passage": 82,
            "building": 90,
            "room": 100,
        }.get(class_key, 75)
        label = self._entity_display_label(entity, fallback=entity.get("id", "")).lower()
        return (class_rank, label, str(entity.get("id", "")))

    def _build_location_browser_items(self, world_model):
        items = []

        if world_model is None:
            return items

        raw_location_entities = world_model.get_entities_by_dataset("locations")
        location_by_id = {
            entity.get("id"): entity
            for entity in raw_location_entities
            if isinstance(entity, dict) and entity.get("id")
        }
        alias_to_location_id = {
            str(alias): str(canonical_id)
            for alias, canonical_id in getattr(world_model.loader, "entity_aliases", {}).items()
        }

        def canonical_location_id(entity_id):
            if not entity_id:
                return entity_id
            return alias_to_location_id.get(str(entity_id), str(entity_id))

        location_entities = list(location_by_id.values())
        children_by_parent = {}
        parent_ids_by_child = {}

        def append_unique(target, value):
            if value and value not in target:
                target.append(value)

        def relation_values(value):
            if value is None:
                return []
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                candidate = value.get("id") or value.get("entity_id") or value.get("target")
                return [candidate] if candidate else []
            if isinstance(value, (list, tuple, set)):
                values = []
                for item in value:
                    values.extend(relation_values(item))
                return values
            return []

        def structural_parent_ids(entity):
            entity_id = canonical_location_id(entity.get("id"))
            parent_ids = []
            for field_key in ("parent_cluster", "parent_location", "parent_entity", "parent_body"):
                for parent_id in relation_values(entity.get(field_key)):
                    parent_id = canonical_location_id(parent_id)
                    if parent_id and parent_id != entity_id and parent_id in location_by_id:
                        append_unique(parent_ids, parent_id)

            if not parent_ids and entity.get("system_role") == "orbital_body":
                for parent_id in relation_values(entity.get("star_system")):
                    parent_id = canonical_location_id(parent_id)
                    if parent_id and parent_id != entity_id and parent_id in location_by_id:
                        append_unique(parent_ids, parent_id)

            if not parent_ids:
                for parent_id in relation_values(entity.get("parents")):
                    parent_id = canonical_location_id(parent_id)
                    if parent_id and parent_id != entity_id and parent_id in location_by_id:
                        append_unique(parent_ids, parent_id)

            return parent_ids

        for entity in location_entities:
            entity_id = canonical_location_id(entity.get("id"))
            if not entity_id:
                continue
            parent_ids = structural_parent_ids(entity)
            if parent_ids:
                parent_ids_by_child[entity_id] = parent_ids
                for parent_id in parent_ids:
                    children_by_parent.setdefault(parent_id, []).append(entity)

        for parent_entity in location_entities:
            parent_id = canonical_location_id(parent_entity.get("id"))
            if not parent_id:
                continue
            for child_field in ("children", "offspring"):
                for child_id in relation_values(parent_entity.get(child_field)):
                    child_id = canonical_location_id(child_id)
                    child_entity = location_by_id.get(child_id)
                    if not child_entity or child_id == parent_id:
                        continue
                    children = children_by_parent.setdefault(parent_id, [])
                    if child_entity not in children:
                        children.append(child_entity)
                    parent_ids_by_child.setdefault(child_id, [])
                    append_unique(parent_ids_by_child[child_id], parent_id)

        for child_list in children_by_parent.values():
            unique_children = {}
            for child in child_list:
                child_id = canonical_location_id(child.get("id"))
                if child_id:
                    unique_children[child_id] = child
            child_list[:] = sorted(unique_children.values(), key=self._location_hierarchy_sort_key)

        auto_reveal = self._location_tree_auto_reveal_descendants()
        emitted_ids = set()

        def location_subtree_matches(location_entity, seen=None):
            if seen is None:
                seen = set()
            location_id = canonical_location_id(location_entity.get("id"))
            if not location_id or location_id in seen:
                return False
            seen.add(location_id)

            if self._location_tree_entity_matches(location_entity, "locations"):
                return True

            for child in children_by_parent.get(location_id, []):
                if location_subtree_matches(child, seen=seen):
                    return True
            return False

        def add_location_subtree(location_entity, depth):
            location_id = canonical_location_id(location_entity.get("id"))
            if not location_id or location_id in emitted_ids:
                return

            children = children_by_parent.get(location_id, [])
            descendant_match = any(location_subtree_matches(child) for child in children)
            if not self._location_tree_entity_matches(location_entity, "locations") and not descendant_match:
                return

            expandable = len(children) > 0
            expanded = self._is_expanded(location_id)
            items.append(
                self._location_tree_item(
                    location_entity,
                    "locations",
                    depth,
                    expandable,
                    expanded,
                    meta_label=self._location_class_display_label(location_entity),
                )
            )
            emitted_ids.add(location_id)

            if expandable and (expanded or (auto_reveal and descendant_match)):
                for child in children:
                    add_location_subtree(child, depth + 1)

        root_locations = sorted(
            [
                location for location in location_entities
                if canonical_location_id(location.get("id"))
                and canonical_location_id(location.get("id")) not in parent_ids_by_child
            ],
            key=self._location_hierarchy_sort_key,
        )
        for location_entity in root_locations:
            add_location_subtree(location_entity, 0)

        for location_entity in sorted(location_entities, key=self._location_hierarchy_sort_key):
            if canonical_location_id(location_entity.get("id")) not in emitted_ids:
                add_location_subtree(location_entity, 0)

        return items

    def _dataset_display_label(self, dataset_name):
        return dataset_name.replace("_", " ").title()

    def _entity_class_label(self, dataset_name, entity):
        if dataset_name == "locations":
            return self._location_class_display_label(entity)
        if dataset_name == "vehicles":
            return entity.get("vehicle_class", entity.get("type", "entity"))
        if dataset_name == "components":
            return entity.get("component_class", entity.get("type", "entity"))
        if dataset_name == "ideas":
            return entity.get("idea_class", entity.get("type", "entity"))
        if dataset_name == "species":
            return entity.get("species_class", entity.get("type", "entity"))
        if dataset_name == "systems":
            if entity.get("system_role") == "star_system":
                return entity.get("system_class", entity.get("type", "entity"))
            if entity.get("system_role") == "orbital_body":
                return entity.get("body_class", entity.get("type", "entity"))
        return entity.get("type", "entity")

    def _build_browser_items(self, world_model):
        items = [
            {"kind": "label", "text": "Grouping: hierarchy preview"},
            {"kind": "spacer"},
        ]

        if world_model is None:
            return items

        schema_items = self._build_schema_browser_items()
        if schema_items:
            items.append({"kind": "section", "text": "Schemas"})
            items.extend(schema_items)
            items.append({"kind": "spacer"})

        if self.browser_filter_dataset == "schemas":
            return items

        dataset_names = sorted(world_model.get_dataset_names())

        preferred_order = [
            "ideas",
            "locations",
            "vehicles",
            "components",
        ]
        ordered_names = [name for name in preferred_order if name in dataset_names]
        ordered_names += [name for name in dataset_names if name not in ordered_names]
        hide_empty_sections = bool(self.browser_search_query.strip())

        for dataset_name in ordered_names:
            if dataset_name == "systems":
                continue

            if dataset_name == "locations":
                if self.browser_filter_dataset not in {"all", "locations", "systems"}:
                    continue
                dataset_items = self._build_location_browser_items(world_model)
                if hide_empty_sections and not dataset_items:
                    continue
                items.append({"kind": "section", "text": "Locations / Systems"})
                items.extend(dataset_items)
                items.append({"kind": "spacer"})
                continue

            if self.browser_filter_dataset != "all" and dataset_name != self.browser_filter_dataset:
                continue

            dataset_items = []
            entities = sorted(
                world_model.get_entities_by_dataset(dataset_name),
                key=lambda entity: self._entity_display_label(entity, fallback=entity.get("id", "")).lower()
            )

            for entity in entities:
                if not self._matches_browser_filters(entity, dataset_name):
                    continue

                label = self._entity_display_label(entity, fallback=entity.get("id", "unknown"))
                entity_class = self._entity_class_label(dataset_name, entity)
                missing_count = self._entity_missing_scalar_count(entity, dataset_name)

                dataset_items.append(
                    {
                        "kind": "entity",
                        "entity_id": entity.get("id"),
                        "dataset_name": dataset_name,
                        "text": f"  {label} [{entity_class}]",
                        "missing_count": missing_count,
                        "is_incomplete": missing_count > 0,
                    }
                )

            if hide_empty_sections and not dataset_items:
                continue

            items.append({"kind": "section", "text": self._dataset_display_label(dataset_name)})
            items.extend(dataset_items)
            items.append({"kind": "spacer"})

        return items

    def _build_card_from_entity(self, entity):
        if entity is None or self.layout is None:
            return None

        dataset_name = entity.get("_dataset", entity.get("type", "entity"))
        card_view = EntityCard(entity, dataset_name=dataset_name, world_model=self.world_model)

        if dataset_name == "locations":
            display_group = "location"
            subtype = entity.get("location_class", entity.get("type", "entity"))
        elif dataset_name == "ideas":
            display_group = "idea"
            subtype = entity.get("entry_status") or "generic"
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
        elif dataset_name == "species":
            display_group = "species"
            subtype = entity.get("species_class", entity.get("type", "entity"))
        else:
            display_group = dataset_name
            subtype = entity.get("type", "entity")

        start_year = entity.get("start_year")
        end_year = entity.get("end_year")
        point_year = entity.get("year")
        if point_year is None:
            point_year = entity.get("year_number")

        def _coerce_year(value):
            if value is None:
                return None
            if isinstance(value, bool):
                return None
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped or stripped.lower() in {"none", "null"}:
                    return None
                try:
                    return int(float(stripped))
                except ValueError:
                    return None
            return None

        start_year = _coerce_year(start_year)
        end_year = _coerce_year(end_year)
        point_year = _coerce_year(point_year)

        if start_year is not None and end_year is not None and end_year >= start_year and end_year != start_year:
            years = [start_year, end_year]
        elif start_year is not None:
            years = [start_year]
        elif point_year is not None:
            years = [point_year]
        else:
            years = []

        selected_year = years[0] if years else None

        card_index = len(self.cards)
        spawn_x = 24 + (card_index % 3) * 40
        spawn_y = 84 + (card_index % 5) * 32

        card_title = self._entity_display_label(entity, fallback=entity.get("id", "unknown"))
        if dataset_name == "species":
            common_name, binomial_name = self._species_name_parts(entity)
            card_title = common_name or binomial_name or entity.get("id", "Unknown Species")

        card = {
            "entity_id": entity.get("id"),
            "title": card_title,
            "subtitle": self._card_subtitle_for_entity(entity) if dataset_name == "species" else f"{display_group} | {subtype}",
            "years": years,
            "selected_year": selected_year,
            "canvas_x": spawn_x,
            "canvas_y": spawn_y,
            "canvas_w": 420,
            "canvas_h": 340,
            "auto_canvas_h": True,
            "scroll_y": 0,
            "card_view": card_view,
            "is_edit_mode": False,
            "active_edit_field": None,
            "edit_buffer": "",
            "edit_original_value": None,
            "wiki_link_picker_open": False,
            "wiki_link_query": "",
            "wiki_link_matches": [],
            "wiki_link_selected_index": 0,
            "wiki_link_replace_range": None,
            "relation_picker_open": False,
            "relation_picker_query": "",
            "relation_picker_matches": [],
            "relation_picker_selected_index": 0,
            "relation_picker_hitboxes": [],
            "wiki_link_hitboxes": [],
            "wiki_section_hitboxes": [],
            "toolbelt_hitboxes": [],
            "task_checklist_hitboxes": [],
            "task_checklist_input_active": False,
            "task_checklist_input_buffer": "",
            "type_picker_open": False,
            "type_picker_hitboxes": [],
            "type_picker_scroll": 0,
            "type_picker_rect": None,
            "draft_edit_buffers": {},
            "is_draft_entity": False,
            "delete_confirm_active": False,
            "last_edit_action": None,
        }
        self._apply_cached_draft_to_card(card)
        return card

    def _build_card_from_schema(self, schema_name):
        if not schema_name or self.layout is None:
            return None

        schema = self.schema_loader.schemas.get(schema_name)
        if not isinstance(schema, dict):
            return None

        schema_path = self.schema_loader.get_schema_file(schema_name)
        card_index = len(self.cards)
        spawn_x = 24 + (card_index % 3) * 40
        spawn_y = 84 + (card_index % 5) * 32
        card_id = self._schema_card_id(schema_name)
        schema_fields = copy.deepcopy(schema.get("fields", {}))

        return {
            "entity_id": card_id,
            "card_kind": "schema",
            "title": schema_name,
            "subtitle": f"schema | {schema.get('extends') or 'root'}",
            "canvas_x": spawn_x,
            "canvas_y": spawn_y,
            "canvas_w": 560,
            "canvas_h": 520,
            "auto_canvas_h": True,
            "scroll_y": 0,
            "card_view": SchemaCard(
                schema_name=schema_name,
                schema=schema,
                schema_path=schema_path,
                usage_by_field=self.schema_field_usage,
            ),
            "schema_name": schema_name,
            "schema_schema_name": schema.get("schema", schema_name),
            "schema_extends": schema.get("extends"),
            "schema_path": schema_path,
            "schema_original": copy.deepcopy(schema),
            "schema_draft_fields": schema_fields,
            "schema_active_field": None,
            "schema_edit_buffer": "",
            "schema_dirty": False,
            "schema_status": "Click a field row to edit",
            "is_edit_mode": False,
            "active_edit_field": None,
            "wiki_link_picker_open": False,
            "wiki_link_query": "",
            "wiki_link_matches": [],
            "wiki_link_selected_index": 0,
            "wiki_link_replace_range": None,
            "relation_picker_open": False,
            "relation_picker_query": "",
            "relation_picker_matches": [],
            "relation_picker_selected_index": 0,
            "relation_picker_hitboxes": [],
            "wiki_link_hitboxes": [],
            "wiki_section_hitboxes": [],
            "toolbelt_hitboxes": [],
            "task_checklist_hitboxes": [],
            "task_checklist_input_active": False,
            "task_checklist_input_buffer": "",
            "type_picker_open": False,
            "type_picker_hitboxes": [],
            "type_picker_scroll": 0,
            "type_picker_rect": None,
        }


    def _layout_all_cards(self):
        if self.layout is None:
            return

        right_rect = self.layout["right_rect"]
        zoom = max(0.001, self.canvas_zoom)
        card_font = self._card_font_for_zoom()

        max_right = 0
        max_bottom = 0

        for card in self.cards:
            card_w = max(300, min(900, int(card.get("canvas_w", 420))))

            card_view = card.get("card_view")
            requested_h = int(card.get("canvas_h", 340))
            auto_canvas_h = bool(card.get("auto_canvas_h", True))

            if card_view is not None and self.font_for_layout is not None:
                minimum_h = card_view.get_minimum_height(card, self.font_for_layout)
            else:
                minimum_h = 260

            if auto_canvas_h:
                card_h = max(260, min(2400, minimum_h))
            else:
                card_h = max(260, min(2400, max(requested_h, minimum_h)))
            card["canvas_h"] = card_h
            card["layout_font"] = card_font

            screen_card_w = max(120, int(round(card_w * zoom)))
            screen_card_h = max(120, int(round(card_h * zoom)))

            rect_x = right_rect.x + self.canvas_offset_x + int(card.get("canvas_x", 24) * zoom)
            rect_y = right_rect.y + self.canvas_offset_y + int(card.get("canvas_y", 84) * zoom)

            rect = pygame.Rect(rect_x, rect_y, screen_card_w, screen_card_h)

            if card_view is not None:
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

    def _clamp_canvas_offsets(self):
        # The card canvas is intentionally unbounded. Offsets are allowed to
        # move freely so cards dragged into negative space remain recoverable by panning.
        return

    def _card_accepts_canvas_relation(self, card):
        return (
            isinstance(card, dict)
            and card.get("card_kind") != "schema"
            and bool(card.get("is_edit_mode", False))
            and bool(card.get("entity_id"))
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

        scaled_size = max(8, min(32, int(round(base_size * self.canvas_zoom))))
        return pygame.font.SysFont("consolas", scaled_size)

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

    def _focus_timeline_year(self, year):
        return self.timeline_ui.focus_year(year)

    def _random_entity(self):
        if self.world_model is None or not self.world_model.loader.entities:
            return None
        return random.choice(list(self.world_model.loader.entities.values()))

    def _random_unfinished_entity(self):
        if self.world_model is None:
            return None

        unfinished = []
        for entity in self.world_model.loader.entities.values():
            if not isinstance(entity, dict) or not entity.get("id"):
                continue
            dataset_name = entity.get("_dataset", entity.get("type", ""))
            if self._entity_missing_scalar_count(entity, dataset_name) > 0:
                unfinished.append(entity)

        if not unfinished:
            return None
        return random.choice(unfinished)

    def _startup_entity(self):
        if self.world_model is None:
            return None

        entities = [
            entity
            for entity in self.world_model.loader.entities.values()
            if isinstance(entity, dict) and entity.get("id")
        ]
        if not entities:
            return None

        return random.choice(entities)

    def _create_random_entry_card(self):
        entity = self._random_entity()
        if entity is None:
            return False
        self._ensure_card(entity)
        return True

    def _create_random_unfinished_entry_card(self):
        entity = self._random_unfinished_entity()
        if entity is None:
            return False
        self._ensure_card(entity)
        return True

    def _random_task_entity(self):
        if self.world_model is None:
            return None

        tasks = [
            entity
            for entity in self.world_model.get_entities_by_dataset("tasks")
            if isinstance(entity, dict)
            and entity.get("id")
            and not self._is_finished_task_entity(entity)
        ]
        if not tasks:
            tasks = [
                entity
                for entity in self.world_model.loader.entities.values()
                if isinstance(entity, dict)
                and entity.get("id")
                and (entity.get("_dataset") == "tasks" or entity.get("type") == "task")
                and not self._is_finished_task_entity(entity)
            ]
        if not tasks:
            return None

        return random.choice(tasks)

    def _is_finished_task_entity(self, entity):
        return str(entity.get("entry_status") or "").strip().lower() in {
            "finished",
            "complete",
            "completed",
            "done",
        }

    def _create_random_task_card(self):
        if self.world_model is None:
            return False

        entity = self._random_task_entity()
        if entity is None:
            return False

        self._ensure_card(entity)
        return True

    def _template_entity_type(self, dataset_name, template=None):
        if isinstance(template, dict) and template.get("entity_type"):
            return template["entity_type"]
        template = self._template_by_dataset(dataset_name)
        if template is not None:
            return template.get("entity_type", self._singularize_name(dataset_name))
        return self._singularize_name(dataset_name)

    def _next_template_entity_id(self, dataset_name, template=None):
        prefix = (
            template.get("id_prefix")
            if isinstance(template, dict) and template.get("id_prefix")
            else self._template_id_prefix(dataset_name, entity_type=self._template_entity_type(dataset_name, template))
        )
        existing_ids = set(self.world_model.loader.entities.keys()) if self.world_model is not None else set()
        existing_ids.update(self.card_drafts.keys())
        index = 1
        while True:
            candidate = f"{prefix}_new_{index:03d}"
            if candidate not in existing_ids:
                return candidate
            index += 1

    def _requested_template_entity_id_from_name(self, template, entry_name):
        if not isinstance(template, dict):
            return ""
        dataset_name = template.get("dataset_name")
        entity_type = template.get("entity_type") or self._template_entity_type(dataset_name, template)
        return self._unique_entity_id(
            self._entity_id_from_name(dataset_name, entity_type, entry_name, template=template)
        )

    def _default_value_for_schema_field(self, field_type):
        field_type = str(field_type or "").lower()
        if "list" in field_type:
            return []
        if field_type in {"dict", "object"} or "object" in field_type:
            return {}
        if "entity" in field_type or "null" in field_type:
            return None
        if "number" in field_type or "int" in field_type or "float" in field_type:
            return None
        if "bool" in field_type:
            return False
        return ""

    def _normalize_schema_field_spec(self, spec):
        if isinstance(spec, dict):
            return spec
        if isinstance(spec, str):
            return {"type": spec}
        return {}

    def _populate_required_schema_fields(self, entity, template):
        if not isinstance(template, dict):
            return
        schema = template.get("schema") or {}
        field_specs = self._collect_schema_fields(schema)
        for field_key, raw_spec in field_specs.items():
            if field_key in entity or field_key in {"id", "pretty_name", "name", "type", "wiki_entry"}:
                continue
            spec = self._normalize_schema_field_spec(raw_spec)
            if spec.get("optional", False):
                continue
            entity[field_key] = self._default_value_for_schema_field(spec.get("type"))

    def _label_from_requested_entity_id(self, entity_id, entity_type=None):
        text = str(entity_id or "").strip()
        if not text:
            return f"New {str(entity_type or 'Entry').replace('_', ' ').title()}"

        parts = [part for part in text.replace("-", "_").split("_") if part]
        if len(parts) > 1 and entity_type and parts[0] == str(entity_type).lower():
            parts = parts[1:]
        label = " ".join(parts).strip()
        return label.title() if label else text

    def _create_template_entity(self, template, requested_id=None, initial_fields=None, label=None):
        if self.world_model is None:
            return None

        if isinstance(template, str):
            template = self._template_by_dataset(template) or {
                "dataset_name": template,
                "entity_type": self._template_entity_type(template),
                "label": self._schema_display_label(self._template_entity_type(template)),
            }

        dataset_name = template.get("dataset_name")
        entity_type = template.get("entity_type") or self._template_entity_type(dataset_name, template)
        initial_fields = self._template_initial_fields(template, initial_fields)
        requested_id = self._sanitize_entity_id(requested_id)
        if not requested_id:
            name_source = label
            name_source = (
                initial_fields.get("binomial_name")
                or initial_fields.get("pretty_name")
                or initial_fields.get("name")
                or initial_fields.get("common_name")
                or name_source
            )
            requested_id = self._entity_id_from_name(dataset_name, entity_type, name_source, template=template)
        species_binomial = ""
        if dataset_name == "species":
            species_binomial = str(initial_fields.get("binomial_name") or "").strip()
        species_requested_id = self._species_id_from_binomial(species_binomial) if dataset_name == "species" else ""
        if species_requested_id:
            requested_id = self._unique_entity_id(species_requested_id)

        entity_id = self._unique_entity_id(requested_id) if requested_id else self._next_template_entity_id(dataset_name, template=template)
        label = label or (
            self._label_from_requested_entity_id(entity_id, entity_type=entity_type)
            if requested_id
            else f"New {entity_type.replace('_', ' ').title()}"
        )

        if dataset_name == "species":
            entity = {
                "id": entity_id,
                "common_name": label,
                "binomial_name": species_binomial,
                "type": "species",
                "_dataset": dataset_name,
                "wiki_entry": "",
            }
        else:
            entity = {
                "id": entity_id,
                "pretty_name": label,
                "name": label,
                "type": entity_type,
                "_dataset": dataset_name,
                "wiki_entry": "",
            }
        self._populate_required_schema_fields(entity, template)
        for field_key, value in initial_fields.items():
            if field_key not in {"id", "_dataset"}:
                entity[field_key] = value
        if dataset_name == "tasks":
            entity.setdefault("entry_status", "incomplete")
            entity.setdefault("checklist", [])
        if dataset_name == "species":
            common_name, binomial_name = self._normalize_species_entity(entity)
            generated_id = self._species_id_from_binomial(binomial_name)
            if generated_id and not requested_id:
                entity["id"] = self._unique_entity_id(generated_id, current_id=entity_id)
                entity_id = entity["id"]

        self.world_model.loader.datasets.setdefault(dataset_name, []).append(entity)
        self.world_model.loader.entities[entity_id] = entity
        return entity

    def _create_and_open_template_entity(self, template, requested_id=None, initial_fields=None, label=None, place_in_view=False):
        entity = self._create_template_entity(
            template,
            requested_id=requested_id,
            initial_fields=initial_fields,
            label=label,
        )
        if entity is None:
            return None

        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        card = self._ensure_card(entity)
        if card is not None:
            card["is_draft_entity"] = True
            if place_in_view:
                self._place_new_card_in_canvas_view(card)
            self._save_card_draft(card)
        return entity

    def _open_entry_name_prompt(self, template, mode="template", context=None, label=None, initial_buffer=""):
        label = label or "Entry"
        if isinstance(template, dict):
            label = template.get("label") or self._schema_display_label(template.get("entity_type"))
        elif mode == "idea_from_parent":
            label = "Idea"

        self.entry_name_prompt = {
            "template": template,
            "mode": mode,
            "context": context or {},
            "label": label,
            "buffer": str(initial_buffer or ""),
            "cursor": len(str(initial_buffer or "")),
            "rect": None,
            "input_rect": None,
            "create_rect": None,
            "cancel_rect": None,
            "status": "",
        }
        self.show_template_picker = False
        self.template_picker_status = ""
        self._build_template_picker_hitboxes()
        return True

    def _open_new_entry_name_prompt(self):
        self.pending_new_entry_name = None
        return self._open_entry_name_prompt(None, mode="new_entry")

    def _open_idea_name_prompt(self, parent_card):
        if parent_card is None:
            return False

        parent_entity_id = parent_card.get("entity_id")
        if not parent_entity_id:
            return False

        parent_label = parent_card.get("title") or parent_entity_id
        parent_entity = self.world_model.get_entity(parent_entity_id) if self.world_model is not None else None
        if parent_entity is not None:
            parent_label = self._entity_display_label(parent_entity, fallback=parent_label)

        return self._open_entry_name_prompt(
            None,
            mode="idea_from_parent",
            context={
                "parent_entity_id": parent_entity_id,
                "parent_label": parent_label,
            },
        )

    def _open_toolbelt_name_prompt(self, source_card, tool):
        if source_card is None or not isinstance(tool, dict):
            return False

        source_entity_id = source_card.get("entity_id")
        if not source_entity_id:
            return False

        label = tool.get("prompt_label") or tool.get("label") or "Entry"
        return self._open_entry_name_prompt(
            None,
            mode="toolbelt",
            context={
                "source_entity_id": source_entity_id,
                "tool": dict(tool),
            },
            label=label,
        )

    @staticmethod
    def _coerce_hex_rgb(value, fallback=(28, 30, 38)):
        text = str(value or "").strip()
        if text.startswith("#") and len(text) == 7:
            try:
                return (
                    int(text[1:3], 16),
                    int(text[3:5], 16),
                    int(text[5:7], 16),
                )
            except ValueError:
                pass
        return fallback

    @staticmethod
    def _rgb_to_hex(color):
        red, green, blue = [max(0, min(255, int(part))) for part in color[:3]]
        return f"#{red:02x}{green:02x}{blue:02x}"

    def _card_color_value(self, entity, role="body", section_id=None):
        role = str(role or "body").strip().lower()
        if role == "header":
            return entity.get("card_header_color") or entity.get("card_color") or EntityCard.CARD_COLOR_DEFAULT
        if role == "wiki":
            colors = entity.get("wiki_field_colors")
            if not isinstance(colors, dict):
                colors = {}
            section_id = str(section_id or "").strip()
            return colors.get(section_id) or colors.get("default") or "#222632"
        return entity.get("card_color") or entity.get("wiki_link_color") or EntityCard.CARD_COLOR_DEFAULT

    def _card_color_hsv(self, entity, role="body", section_id=None):
        rgb = self._coerce_hex_rgb(self._card_color_value(entity, role=role, section_id=section_id))
        return colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)

    def _set_card_color(self, card, color_hex, persist=True, role=None, section_id=None):
        entity = self._entity_for_card(card)
        color_hex = str(color_hex or "").strip()
        if not isinstance(entity, dict) or not color_hex:
            return False

        if role is None:
            role = card.get("active_color_role", "body") if card is not None else "body"
        role = str(role or "body").strip().lower()
        if role == "header":
            entity["card_header_color"] = color_hex
        elif role == "wiki":
            section_id = str(section_id or (card or {}).get("active_wiki_section_id") or "default").strip() or "default"
            colors = entity.get("wiki_field_colors")
            if not isinstance(colors, dict):
                colors = {}
            colors[section_id] = color_hex
            entity["wiki_field_colors"] = colors
        else:
            entity["card_color"] = color_hex
        entity.pop("wiki_link_color", None)
        if card is None:
            return True

        card_view = card.get("card_view")
        if card_view is not None:
            card_view.entity = entity

        if persist and not card.get("is_temporary", False):
            self._save_card_draft(card)
            if not card.get("is_draft_entity", False):
                self._persist_card_entity(card)
            self._refresh_timeline_items()
        return True

    def _set_card_color_from_slider(self, card, channel, slider_rect, mouse_x, persist=True, role=None, section_id=None):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict) or slider_rect is None:
            return False

        slider_w = max(1, int(slider_rect.width))
        value = (mouse_x - slider_rect.x) / slider_w
        value = max(0.0, min(1.0, value))
        role = role or (card or {}).get("active_color_role", "body")
        section_id = section_id or (card or {}).get("active_wiki_section_id")
        hue, saturation, brightness = self._card_color_hsv(entity, role=role, section_id=section_id)
        if channel == "h":
            hue = value
        elif channel == "s":
            saturation = value
        elif channel == "v":
            brightness = value
        else:
            return False

        red, green, blue = colorsys.hsv_to_rgb(hue, saturation, brightness)
        color_hex = self._rgb_to_hex((round(red * 255), round(green * 255), round(blue * 255)))
        return self._set_card_color(card, color_hex, persist=persist, role=role, section_id=section_id)

    def _close_entry_name_prompt(self):
        self.entry_name_prompt = None

    def _create_named_template_entity(self, template, entry_name):
        entity = self._create_and_open_template_entity(
            template,
            requested_id=self._requested_template_entity_id_from_name(template, entry_name),
            initial_fields={
                "pretty_name": entry_name,
                "name": entry_name,
            },
            label=entry_name,
            place_in_view=True,
        )
        if entity is None:
            return None

        entity["pretty_name"] = entry_name
        entity["name"] = entry_name
        card = self._find_card_by_entity_id(entity.get("id"))
        if card is not None:
            card["title"] = entry_name
            self._save_card_draft(card)

        return entity

    def _create_named_idea_from_parent(self, parent_entity_id, entry_name):
        if self.world_model is None or not parent_entity_id:
            return None

        parent_entity = self.world_model.get_entity(parent_entity_id)
        idea = self._create_template_entity(
            "ideas",
            requested_id=self._requested_template_entity_id_from_name(self._template_by_dataset("ideas"), entry_name),
            initial_fields={
                "pretty_name": entry_name,
                "name": entry_name,
            },
            label=entry_name,
        )
        if idea is None:
            return None

        idea["pretty_name"] = entry_name
        idea["name"] = entry_name
        if parent_entity is not None:
            idea["parents"] = [parent_entity_id]
        else:
            idea["related"] = []

        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        card = self._ensure_card(idea)
        if card is not None:
            card["title"] = entry_name
            card["is_draft_entity"] = True
            self._place_new_card_in_canvas_view(card)
            self._save_card_draft(card)
        return idea

    def _open_relation_note_prompt(self, source_card, relation_info, initial_text=""):
        if source_card is None or not isinstance(relation_info, dict):
            return False
        return self._open_entry_name_prompt(
            None,
            mode="relation_note",
            context={
                "source_entity_id": source_card.get("entity_id"),
                "card": source_card,
                "field_key": relation_info.get("field_key"),
            },
            label="Note",
            initial_buffer=initial_text,
        )

    def _create_relation_note(self, source_card, field_key, note_text):
        if self.world_model is None:
            return None
        note_text = str(note_text or "").strip()
        if not note_text:
            return None

        template = self._template_by_dataset("ideas") or {
            "dataset_name": "ideas",
            "entity_type": "idea",
            "schema_name": "idea",
        }
        source_entity_id = source_card.get("entity_id") if source_card is not None else ""
        note = self._create_and_open_template_entity(
            template,
            requested_id=self._requested_template_entity_id_from_name(template, note_text),
            initial_fields={
                "pretty_name": note_text,
                "name": note_text,
                "idea_class": "note",
                "wiki_entry": note_text,
                "related": [source_entity_id] if source_entity_id else [],
            },
            label=note_text,
            place_in_view=True,
        )
        if note is None:
            return None

        note["pretty_name"] = note_text
        note["name"] = note_text
        note["idea_class"] = "note"
        note["wiki_entry"] = note_text

        note_id = str(note.get("id") or "").strip()
        if source_card is not None and field_key and note_id:
            self._insert_relation_reference_into_card(source_card, field_key, note_id)
            if source_card.get("is_draft_entity", False):
                self._save_card_draft(source_card)
            else:
                self._persist_card_entity(source_card)

        self.browser_items = self._build_browser_items(self.world_model)
        self._refresh_timeline_items()
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return note

    def _submit_entry_name_prompt(self):
        prompt = self.entry_name_prompt
        if not isinstance(prompt, dict):
            return False

        entry_name = str(prompt.get("buffer", "")).strip()
        if not entry_name:
            prompt["status"] = "Name required"
            return True

        mode = prompt.get("mode", "template")
        template = prompt.get("template")
        if mode == "relation_note":
            context = prompt.get("context", {})
            source_card = context.get("card")
            if source_card not in self.cards:
                source_card = self._find_card_by_entity_id(context.get("source_entity_id"))
            note = self._create_relation_note(source_card, context.get("field_key"), entry_name)
            if note is None:
                prompt["status"] = "Could not create note"
                return True
            self._close_entry_name_prompt()
            return True

        if mode == "idea_from_parent":
            context = prompt.get("context", {})
            idea = self._create_named_idea_from_parent(context.get("parent_entity_id"), entry_name)
            if idea is None:
                prompt["status"] = "Could not create idea"
                return True
            self._close_entry_name_prompt()
            return True

        if mode == "toolbelt":
            context = prompt.get("context", {})
            created = self._create_named_toolbelt_entity(
                context.get("source_entity_id"),
                context.get("tool"),
                entry_name,
            )
            if created is None:
                prompt["status"] = "Could not create linked card"
                return True
            self._close_entry_name_prompt()
            return True

        if mode == "new_entry" or template is None:
            self.pending_new_entry_name = entry_name
            self._close_entry_name_prompt()
            self.schema_entry_templates = self._load_schema_entry_templates()
            self.template_picker_mode = "create"
            self.template_picker_context = {}
            self.template_picker_search_query = ""
            self.template_picker_search_active = True
            self.show_template_picker = True
            self.template_picker_scroll = 0
            self.template_picker_status = f"Choose type for {entry_name}"
            self._build_template_picker_hitboxes()
            return True

        entity = self._create_named_template_entity(template, entry_name)
        if entity is None:
            prompt["status"] = "Could not create entry"
            return True

        self._close_entry_name_prompt()
        return True

    def _handle_entry_name_prompt_keydown(self, event):
        prompt = self.entry_name_prompt
        if not isinstance(prompt, dict):
            return False

        buffer_text = str(prompt.get("buffer", ""))
        cursor = max(0, min(int(prompt.get("cursor", len(buffer_text))), len(buffer_text)))

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self._submit_entry_name_prompt()
        if event.key == pygame.K_ESCAPE:
            self._close_entry_name_prompt()
            return True
        if event.key == pygame.K_BACKSPACE:
            if cursor > 0:
                prompt["buffer"] = buffer_text[:cursor - 1] + buffer_text[cursor:]
                prompt["cursor"] = cursor - 1
                prompt["status"] = ""
            return True
        if event.key == pygame.K_DELETE:
            if cursor < len(buffer_text):
                prompt["buffer"] = buffer_text[:cursor] + buffer_text[cursor + 1:]
                prompt["status"] = ""
            return True
        if event.key == pygame.K_LEFT:
            prompt["cursor"] = max(0, cursor - 1)
            return True
        if event.key == pygame.K_RIGHT:
            prompt["cursor"] = min(len(buffer_text), cursor + 1)
            return True
        if event.key == pygame.K_HOME:
            prompt["cursor"] = 0
            return True
        if event.key == pygame.K_END:
            prompt["cursor"] = len(buffer_text)
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            prompt["buffer"] = buffer_text[:cursor] + text + buffer_text[cursor:]
            prompt["cursor"] = cursor + len(text)
            prompt["status"] = ""
            return True

        return True

    def _handle_entry_name_prompt_click(self, mouse_pos):
        prompt = self.entry_name_prompt
        if not isinstance(prompt, dict):
            return False

        cancel_rect = prompt.get("cancel_rect")
        if cancel_rect is not None and cancel_rect.collidepoint(mouse_pos):
            self._close_entry_name_prompt()
            return True

        create_rect = prompt.get("create_rect")
        if create_rect is not None and create_rect.collidepoint(mouse_pos):
            return self._submit_entry_name_prompt()

        return True

    def _create_new_entry_from_template(self, template):
        entry_name = str(self.pending_new_entry_name or "").strip()
        if entry_name:
            self.pending_new_entry_name = None
            entity = self._create_named_template_entity(template, entry_name)
            if entity is None:
                self.template_picker_status = "Could not create entry"
                return False
            self.show_template_picker = False
            self.template_picker_status = ""
            self.template_picker_mode = "create"
            self.template_picker_context = {}
            self._build_template_picker_hitboxes()
            return True
        return self._open_entry_name_prompt(template)

    def _open_card_class_template_picker(self, card):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return False

        for open_card in self.cards:
            self._close_type_picker(open_card)

        self.schema_entry_templates = self._load_schema_entry_templates()
        self.pending_new_entry_name = None
        self.template_picker_mode = "convert"
        self.template_picker_context = {
            "entity_id": card.get("entity_id"),
            "card": card,
        }
        self.template_picker_search_query = ""
        self.template_picker_search_active = True
        self.template_picker_scroll = 0
        self.template_picker_status = f"Choose class for {card.get('title') or entity.get('id')}"
        self.show_template_picker = True
        self._build_template_picker_hitboxes()
        return True

    def _select_template_picker_template(self, template):
        if self.template_picker_mode == "convert":
            entity_id = self.template_picker_context.get("entity_id")
            card = self.template_picker_context.get("card")
            if card not in self.cards:
                card = self._find_card_by_entity_id(entity_id)
            if card is None:
                self.template_picker_status = "Card no longer open"
                return False
            if not self._convert_card_to_template(card, template):
                self.template_picker_status = "Could not change class"
                return False
            self.show_template_picker = False
            self.template_picker_search_query = ""
            self.template_picker_search_active = False
            self.template_picker_mode = "create"
            self.template_picker_context = {}
            self.template_picker_status = ""
            self._build_template_picker_hitboxes()
            return True

        if self.template_picker_mode == "relation_create":
            return self._create_relation_target_from_template_picker(template)

        return self._create_new_entry_from_template(template)

    def _handle_template_picker_click(self, mouse_pos):
        if not self.show_template_picker:
            return None

        if self.template_picker_rect is None or not self.template_picker_rect.collidepoint(mouse_pos):
            self.show_template_picker = False
            self.template_picker_status = ""
            self._build_template_picker_hitboxes()
            return "__ui_consumed__"

        if self.template_picker_search_rect is not None and self.template_picker_search_rect.collidepoint(mouse_pos):
            self.template_picker_search_active = True
            return "__ui_consumed__"

        self.template_picker_search_active = False

        for template, _, button_rect in self.template_quick_button_hitboxes:
            if button_rect.collidepoint(mouse_pos):
                created = self._select_template_picker_template(template)
                if not created and self.template_picker_mode != "convert":
                    self.template_picker_status = "Name entry first"
                    self._open_entry_name_prompt(template)
                return "__ui_consumed__"

        for template, _, button_rect in self.template_button_hitboxes:
            if not button_rect.collidepoint(mouse_pos):
                continue

            created = self._select_template_picker_template(template)
            if not created and self.template_picker_mode != "convert":
                self.template_picker_status = "Name entry first"
                self._open_entry_name_prompt(template)
            return "__ui_consumed__"

        return "__ui_consumed__"

    def _create_idea_from_parent_card(self, parent_card):
        if self.world_model is None or parent_card is None:
            return False

        parent_entity_id = parent_card.get("entity_id")
        if not parent_entity_id:
            return False

        parent_entity = self.world_model.get_entity(parent_entity_id)
        parent_label = parent_card.get("title") or parent_entity_id
        if parent_entity is not None:
            parent_label = self._entity_display_label(parent_entity, fallback=parent_label)

        idea = self._create_template_entity("ideas")
        if idea is None:
            return False

        label = f"Idea from {parent_label}"
        idea["pretty_name"] = label
        idea["name"] = label

        if parent_entity is not None:
            idea["parents"] = [parent_entity_id]
        else:
            idea["related"] = []

        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        card = self._ensure_card(idea)
        if card is not None:
            card["is_draft_entity"] = True
            self._save_card_draft(card)
        return True

    def _append_unique_relation_value(self, entity, field_key, entity_id):
        if not isinstance(entity, dict) or not field_key or not entity_id:
            return False

        current_value = entity.get(field_key)
        if isinstance(current_value, list):
            values = list(current_value)
        elif current_value in (None, ""):
            values = []
        else:
            values = [current_value]

        existing = {str(value).strip() for value in values}
        if entity_id in existing:
            entity[field_key] = values
            return False

        values.append(entity_id)
        entity[field_key] = values
        return True

    def _append_offspring_reference(self, entity, child_entity_id):
        if not isinstance(entity, dict) or not child_entity_id:
            return False

        current_value = entity.get("offspring")
        if isinstance(current_value, list):
            values = list(current_value)
        elif current_value in (None, ""):
            values = []
        else:
            values = [current_value]

        for value in values:
            if isinstance(value, dict) and str(value.get("id", "")).strip() == child_entity_id:
                entity["offspring"] = values
                return False
            if str(value).strip() == child_entity_id:
                entity["offspring"] = values
                return False

        values.append({"id": child_entity_id})
        entity["offspring"] = values
        return True

    def _save_or_persist_card_for_entity_id(self, entity_id):
        card = self._find_card_by_entity_id(entity_id)
        if card is None:
            return False
        if card.get("is_draft_entity", False):
            return self._save_card_draft(card)
        return self._persist_card_entity(card)

    def _create_named_toolbelt_entity(self, source_entity_id, tool, entry_name):
        if self.world_model is None or not isinstance(tool, dict):
            return None

        source_entity = self.world_model.get_entity(source_entity_id)
        source_card = self._find_card_by_entity_id(source_entity_id)
        if not isinstance(source_entity, dict) or source_card is None:
            return None

        target_dataset = tool.get("target_dataset")
        template = self._template_by_dataset(target_dataset)
        if template is None:
            return None

        initial_fields = {
            "pretty_name": entry_name,
            "name": entry_name,
        }
        tool_id = tool.get("id")
        if tool_id == "person_add_child":
            initial_fields["parents"] = [source_entity_id]
        elif tool_id in {"producer_add_product_item", "producer_add_product_vehicle"}:
            initial_fields["produced_by"] = [source_entity_id]
        elif tool_id == "person_add_parent":
            initial_fields["offspring"] = [{"id": source_entity_id}]

        created_entity = self._create_and_open_template_entity(
            template,
            requested_id=self._requested_template_entity_id_from_name(template, entry_name),
            initial_fields=initial_fields,
            label=entry_name,
            place_in_view=True,
        )
        if created_entity is None:
            return None

        created_entity_id = created_entity.get("id")
        created_card = self._find_card_by_entity_id(created_entity_id)

        if tool_id == "person_add_parent":
            self._append_unique_relation_value(source_entity, "parents", created_entity_id)
            self._append_offspring_reference(created_entity, source_entity_id)
        elif tool_id == "person_add_child":
            self._append_offspring_reference(source_entity, created_entity_id)
            self._append_unique_relation_value(created_entity, "parents", source_entity_id)
        elif tool_id == "producer_add_product_item":
            self._append_unique_relation_value(source_entity, "produced_items", created_entity_id)
            self._append_unique_relation_value(created_entity, "produced_by", source_entity_id)
        elif tool_id == "producer_add_product_vehicle":
            self._append_unique_relation_value(source_entity, "produced_vehicles", created_entity_id)
            self._append_unique_relation_value(created_entity, "produced_by", source_entity_id)
        elif tool_id == "producer_add_product_component":
            self._append_unique_relation_value(source_entity, "produced_components", created_entity_id)
            self._append_unique_relation_value(created_entity, "related", source_entity_id)

        self._save_or_persist_card_for_entity_id(source_entity_id)
        if created_card is not None:
            created_card["is_draft_entity"] = True
            self._save_card_draft(created_card)

        self.browser_items = self._build_browser_items(self.world_model)
        self._refresh_timeline_items()
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return created_entity

    def _card_subtitle_for_entity(self, entity):
        if not isinstance(entity, dict):
            return "entity"

        dataset_name = entity.get("_dataset", entity.get("type", "entity"))
        if dataset_name == "locations":
            return f"location | {entity.get('location_class', entity.get('type', 'entity'))}"
        if dataset_name == "ideas":
            return f"idea | {entity.get('entry_status') or 'generic'}"
        if dataset_name == "species":
            common_name, binomial_name = self._species_name_parts(entity)
            if binomial_name:
                return f"species | {binomial_name}"
            return f"species | {entity.get('species_class') or 'unclassified'}"
        if dataset_name == "systems":
            system_role = entity.get("system_role")
            if system_role == "star_system":
                return f"star system | {entity.get('system_class', entity.get('type', 'entity'))}"
            if system_role == "orbital_body":
                return f"orbital body | {entity.get('body_class', entity.get('type', 'entity'))}"
            return f"system | {entity.get('type', 'entity')}"
        return f"{dataset_name} | {entity.get('type', 'entity')}"

    def _close_type_picker(self, card):
        card["type_picker_open"] = False
        card["type_picker_hitboxes"] = []
        card["type_picker_rect"] = None

    def _toggle_type_picker(self, card):
        if card is None:
            return False
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return False
        card["type_picker_open"] = not bool(card.get("type_picker_open", False))
        card["type_picker_hitboxes"] = []
        card["type_picker_rect"] = None
        if card["type_picker_open"]:
            card["type_picker_scroll"] = 0
        return True

    def _remove_entity_from_dataset_index(self, dataset_name, entity_id, entity_obj):
        if self.world_model is None or not dataset_name:
            return
        dataset = self.world_model.loader.datasets.get(dataset_name, [])
        self.world_model.loader.datasets[dataset_name] = [
            item
            for item in dataset
            if item is not entity_obj and item.get("id") != entity_id
        ]

    def _remove_entity_from_repository(self, dataset_name, entity_id):
        entry_path = self._entry_file_path_for_dataset(dataset_name)
        if not entry_path or not os.path.exists(entry_path):
            return False

        with open(entry_path, "r", encoding="utf-8") as f:
            text = f.read()

        found = self._find_yaml_entity_block(text, entity_id)
        if found is None:
            return False

        block_start, block_end = found
        updated_text = text[:block_start] + text[block_end:].lstrip("\n")
        with open(entry_path, "w", encoding="utf-8") as f:
            f.write(updated_text)
        return True

    def _delete_card_entry(self, card):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return False

        entity_id = str(entity.get("id") or card.get("entity_id") or "").strip()
        dataset_name = entity.get("_dataset", entity.get("type", ""))
        if not entity_id or not dataset_name:
            return False

        removed = False
        if card.get("is_draft_entity", False):
            removed = True
        else:
            removed = self._remove_entity_from_repository(dataset_name, entity_id)
            if not removed:
                return False

        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        if loader is not None:
            self._remove_entity_from_dataset_index(dataset_name, entity_id, entity)
            if getattr(loader, "entities", None) is not None:
                loader.entities.pop(entity_id, None)
            aliases = getattr(loader, "entity_aliases", None)
            if isinstance(aliases, dict):
                aliases.pop(entity_id, None)
                for alias, target in list(aliases.items()):
                    if target == entity_id:
                        aliases.pop(alias, None)

        self._remove_card_draft(entity_id)
        self.cards = [open_card for open_card in self.cards if open_card is not card]
        if self.selected_entity_id == entity_id:
            self.selected_entity_id = self.cards[-1].get("entity_id") if self.cards else None
        if self.active_card_drag_id == entity_id:
            self.active_card_drag_id = None
        if self.active_card_resize_id == entity_id:
            self.active_card_resize_id = None
        if self.canvas_relation_link_source_id == entity_id:
            self._clear_canvas_relation_link()
        if (
            self.relation_link_target is not None
            and self.relation_link_target.get("source_entity_id") == entity_id
        ):
            self.relation_link_target = None
            self.relation_link_status = ""

        if not card.get("is_draft_entity", False) and self.world_model is not None:
            refresh = getattr(self.world_model, "refresh", None)
            if callable(refresh):
                refresh()
            else:
                touch_degrees = getattr(self.world_model, "touch_degrees", None)
                if hasattr(touch_degrees, "refresh"):
                    touch_degrees.refresh()
                if loader is not None and hasattr(loader, "build_reference_graph"):
                    loader.build_reference_graph()

        self.browser_items = self._build_browser_items(self.world_model)
        self._refresh_timeline_items()
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return removed

    def _convert_card_to_template(self, card, template):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict) or not isinstance(template, dict):
            return False

        old_id = str(entity.get("id", ""))
        old_dataset = entity.get("_dataset", entity.get("type", "entity"))
        new_dataset = template.get("dataset_name")
        new_type = template.get("entity_type") or self._template_entity_type(new_dataset, template)
        if not old_id or not new_dataset:
            return False

        name_source = (
            entity.get("pretty_name")
            or entity.get("name")
            or entity.get("common_name")
            or old_id
        )
        new_id = self._unique_entity_id(
            self._entity_id_from_name(new_dataset, new_type, name_source, template=template),
            current_id=old_id,
        ) or self._next_template_entity_id(new_dataset, template=template)
        if new_dataset == "species":
            converted = {
                "id": new_id,
                "common_name": entity.get("pretty_name") or entity.get("name") or "New Species",
                "binomial_name": "",
                "type": "species",
                "_dataset": new_dataset,
            }
        else:
            converted = {
                "id": new_id,
                "pretty_name": entity.get("pretty_name") or entity.get("name") or new_id,
                "name": entity.get("name") or entity.get("pretty_name") or new_id,
                "type": new_type,
                "_dataset": new_dataset,
            }
        for field_key in self.IDEA_GENERIC_FIELDS:
            if new_dataset == "species" and field_key in {"pretty_name", "name"}:
                continue
            if field_key in entity:
                converted[field_key] = entity[field_key]

        derived_from = converted.get("derived_from")
        if not isinstance(derived_from, list):
            derived_from = []
        if old_id not in derived_from:
            derived_from.append(old_id)
        converted["derived_from"] = derived_from

        self._populate_required_schema_fields(converted, template)
        for field_key, value in self._template_initial_fields(template).items():
            if field_key not in {"id", "_dataset", "pretty_name", "name", "type"}:
                converted[field_key] = value

        entity.clear()
        entity.update(converted)
        self._remove_entity_from_dataset_index(old_dataset, old_id, entity)
        self.world_model.loader.datasets.setdefault(new_dataset, []).append(entity)
        self.world_model.loader.entities.pop(old_id, None)
        self.world_model.loader.entities[new_id] = entity

        old_draft = self.card_drafts.pop(old_id, None)
        card["entity_id"] = new_id
        if new_dataset == "species":
            self._normalize_species_entity(converted)
            card["title"] = converted.get("common_name") or converted.get("binomial_name") or new_id
        else:
            card["title"] = converted.get("name", new_id)
        card["subtitle"] = self._card_subtitle_for_entity(converted)
        card["is_draft_entity"] = bool(card.get("is_draft_entity", False) or (isinstance(old_draft, dict) and old_draft.get("is_new_entry", False)))
        card.pop("pending_entity_id_change", None)
        card["card_view"] = EntityCard(converted, dataset_name=new_dataset, world_model=self.world_model)
        self.selected_entity_id = new_id
        self._close_type_picker(card)

        if card.get("is_draft_entity", False):
            self._save_card_draft(card)
        else:
            self._persist_entity_to_repository(converted)
            self._remove_entity_from_repository(old_dataset, old_id)
            self._remove_card_draft(new_id)

        self.browser_items = self._build_browser_items(self.world_model)
        self._refresh_timeline_items()
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return True

    def _convert_idea_card_to_template(self, card, template):
        return self._convert_card_to_template(card, template)

    def _is_temporal_field(self, field_key):
        return field_key in {"year", "year_number", "start_year", "end_year", "effective_year"}

    def _coerce_card_year(self, value):
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped.lower() in {"none", "null"}:
                return None
            try:
                return int(float(stripped))
            except ValueError:
                return None
        return None

    def _sync_card_years_from_entity(self, card):
        card_view = card.get("card_view")
        entity = getattr(card_view, "entity", None) if card_view is not None else None
        if entity is None:
            return

        start_year = self._coerce_card_year(entity.get("start_year"))
        end_year = self._coerce_card_year(entity.get("end_year"))
        point_year = self._coerce_card_year(entity.get("year"))
        if point_year is None:
            point_year = self._coerce_card_year(entity.get("year_number"))
        if point_year is None:
            point_year = self._coerce_card_year(entity.get("effective_year"))

        if start_year is not None and end_year is not None and end_year >= start_year and end_year != start_year:
            years = [start_year, end_year]
        elif start_year is not None:
            years = [start_year]
        elif point_year is not None:
            years = [point_year]
        else:
            years = []

        card["years"] = years
        if not years:
            card["selected_year"] = None
        elif card.get("selected_year") not in years:
            card["selected_year"] = years[0]

    def _set_timeline_edit_target(self, card_obj, field_key):
        preview_year = None
        card_view = card_obj.get("card_view")
        if card_view is not None and getattr(card_view, "entity", None) is not None:
            preview_year = self._coerce_card_year(card_view.entity.get(field_key))

        self.timeline_edit_target = {
            "entity_id": card_obj.get("entity_id"),
            "field_key": field_key,
            "mode": "field",
        }
        for card in self.cards:
            card.pop("timeline_reanchor_active", None)
        self.timeline_ui.set_picker_target(field_key, preview_year=preview_year)

    def _card_anchor_preview_year(self, card):
        entity = self._entity_for_card(card)
        if isinstance(entity, dict):
            for key in ("year", "year_number", "start_year", "effective_year", "end_year"):
                year = self._coerce_card_year(entity.get(key))
                if year is not None:
                    return year

        selected_year = self._coerce_card_year(card.get("selected_year"))
        if selected_year is not None:
            return selected_year

        years = card.get("years", [])
        if years:
            return self._coerce_card_year(years[0])

        return None

    def _set_timeline_reanchor_target(self, card_obj):
        preview_year = self._card_anchor_preview_year(card_obj)
        self.timeline_edit_target = {
            "entity_id": card_obj.get("entity_id"),
            "field_key": None,
            "mode": "reanchor",
        }
        for card in self.cards:
            card["timeline_reanchor_active"] = card is card_obj
        self.timeline_ui.set_picker_target("card anchor", preview_year=preview_year)

    def _clear_timeline_edit_target(self):
        self.timeline_edit_target = None
        for card in self.cards:
            card.pop("timeline_reanchor_active", None)
        self.timeline_ui.clear_picker_target()

    def _reanchor_card_entity(self, card, year):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return False

        try:
            year = int(year)
        except (TypeError, ValueError):
            return False

        old_start_year = self._coerce_card_year(entity.get("start_year"))
        old_end_year = self._coerce_card_year(entity.get("end_year"))

        if "year" in entity:
            old_anchor_year = self._coerce_card_year(entity.get("year"))
            entity["year"] = year
        elif "year_number" in entity:
            old_anchor_year = self._coerce_card_year(entity.get("year_number"))
            entity["year_number"] = year
        elif "start_year" in entity:
            old_anchor_year = old_start_year
            entity["start_year"] = year

            if old_start_year is not None and old_end_year is not None:
                if old_end_year >= old_start_year and old_end_year != old_start_year:
                    entity["end_year"] = old_end_year + (year - old_start_year)
                elif old_end_year == old_start_year:
                    entity["end_year"] = year
        elif "effective_year" in entity:
            old_anchor_year = self._coerce_card_year(entity.get("effective_year"))
            entity["effective_year"] = year
        elif "end_year" in entity:
            old_anchor_year = old_end_year
            entity["end_year"] = year
        else:
            old_anchor_year = None
            entity["start_year"] = year

        if "effective_year" in entity:
            old_effective_year = self._coerce_card_year(entity.get("effective_year"))
            if old_effective_year is None or old_effective_year == old_anchor_year:
                entity["effective_year"] = year

        return True

    def _apply_timeline_year_pick(self, year):
        if self.timeline_edit_target is None:
            return False

        entity_id = self.timeline_edit_target.get("entity_id")
        field_key = self.timeline_edit_target.get("field_key")
        mode = self.timeline_edit_target.get("mode", "field")
        if entity_id is None or (mode == "field" and field_key is None):
            self._clear_timeline_edit_target()
            return False

        for index in range(len(self.cards) - 1, -1, -1):
            card = self.cards[index]
            if card.get("entity_id") != entity_id:
                continue

            card_obj = self._bring_card_to_front(index)
            card_view = card_obj.get("card_view")
            if card_view is None:
                self._clear_timeline_edit_target()
                return False

            if mode == "reanchor":
                if not self._reanchor_card_entity(card_obj, year):
                    self._clear_timeline_edit_target()
                    return False
            else:
                card_view.begin_edit_field(card_obj, field_key)
                card_obj["edit_buffer"] = str(int(year))
                card_view.commit_edit_field(card_obj)

            self._persist_card_entity(card_obj)
            self._sync_card_years_from_entity(card_obj)
            card_obj["selected_year"] = int(year)
            self._focus_timeline_year(year)
            self._clear_timeline_edit_target()
            self._refresh_timeline_items()
            self._relayout_cards()
            return True

        self._clear_timeline_edit_target()
        return False

    def _ensure_card(self, entity, relayout=True, bring_to_front=True):
        if entity is None:
            return None

        entity_id = entity.get("id")
        if entity_id is None:
            return None

        for index, card in enumerate(self.cards):
            if card.get("entity_id") == entity_id:
                self.selected_entity_id = entity_id
                card_obj = self._bring_card_to_front(index) if bring_to_front else card
                if relayout:
                    self._layout_all_cards()
                return card_obj

        new_card = self._build_card_from_entity(entity)
        if new_card is not None:
            self.cards.append(new_card)
            self.selected_entity_id = entity_id
            if relayout:
                self._relayout_cards()
            return new_card
        return None

    def _relation_tree_neighbor_ids(self, entity_id):
        if self.world_model is None or not entity_id:
            return []

        entity_id = str(entity_id)
        cached_neighbors = self.relation_tree_neighbor_cache.get(entity_id)
        if cached_neighbors is not None:
            return list(cached_neighbors)

        neighbor_ids = set()

        graph = getattr(self.world_model, "graph", None) or getattr(self.world_model, "touch_degrees", None)
        if graph is not None and hasattr(graph, "get_neighbors"):
            for neighbor_id in graph.get_neighbors(entity_id):
                if neighbor_id and str(neighbor_id) != entity_id:
                    neighbor_ids.add(str(neighbor_id))

        entity = self.world_model.get_entity(entity_id)
        if isinstance(entity, dict):
            entities = getattr(getattr(self.world_model, "loader", None), "entities", {})

            def collect_refs(value):
                if isinstance(value, str):
                    stripped = value.strip()
                    if stripped and stripped in entities and stripped != entity_id:
                        neighbor_ids.add(stripped)
                elif isinstance(value, dict):
                    for nested_value in value.values():
                        collect_refs(nested_value)
                elif isinstance(value, (list, tuple, set)):
                    for item in value:
                        collect_refs(item)

            for field_key, field_value in entity.items():
                if field_key in {"id", "pretty_name", "name", "description", "notes", "wiki_entry"}:
                    continue
                collect_refs(field_value)

        def sort_key(neighbor_id):
            entity = self.world_model.get_entity(neighbor_id) if self.world_model is not None else None
            if isinstance(entity, dict):
                return self._entity_display_label(entity, fallback=neighbor_id).lower()
            return str(neighbor_id).lower()

        sorted_neighbors = sorted(neighbor_ids, key=sort_key)
        self.relation_tree_neighbor_cache[entity_id] = tuple(sorted_neighbors)
        return sorted_neighbors

    def _entity_temporal_range(self, entity):
        if not isinstance(entity, dict):
            return None

        start_year = self._coerce_card_year(entity.get("start_year"))
        end_year = self._coerce_card_year(entity.get("end_year"))
        point_year = self._coerce_card_year(entity.get("year"))
        if point_year is None:
            point_year = self._coerce_card_year(entity.get("year_number"))

        if start_year is not None and end_year is not None:
            return (min(start_year, end_year), max(start_year, end_year))
        if start_year is not None:
            return (start_year, start_year)
        if point_year is not None:
            return (point_year, point_year)
        return None

    def _contemporary_entity_ids(self, root_id, existing_ids=None, limit=4):
        if self.world_model is None or not root_id:
            return []

        root_entity = self.world_model.get_entity(root_id)
        root_range = self._entity_temporal_range(root_entity)
        if root_range is None:
            return []

        existing_ids = set(existing_ids or [])
        root_start, root_end = root_range
        root_mid = (root_start + root_end) / 2
        candidates = []
        entities = getattr(getattr(self.world_model, "loader", None), "entities", {})
        for entity_id, entity in entities.items():
            entity_id = str(entity_id)
            if entity_id == root_id or entity_id in existing_ids:
                continue
            candidate_range = self._entity_temporal_range(entity)
            if candidate_range is None:
                continue
            candidate_start, candidate_end = candidate_range
            if candidate_start > root_end or candidate_end < root_start:
                continue

            overlap = min(root_end, candidate_end) - max(root_start, candidate_start)
            candidate_mid = (candidate_start + candidate_end) / 2
            label = self._entity_display_label(entity, fallback=entity_id).lower()
            candidates.append((-overlap, abs(candidate_mid - root_mid), label, entity_id))

        candidates.sort()
        return [entity_id for _, _, _, entity_id in candidates[:max(0, int(limit))]]

    def _open_relation_tree_for_card(self, source_card):
        if self.world_model is None or source_card is None or source_card.get("card_kind") == "schema":
            return False

        root_id = str(source_card.get("entity_id") or "").strip()
        if not root_id or self.world_model.get_entity(root_id) is None:
            return False

        card_limit = 72
        max_depth = max(
            self.relation_tree_min_touch_degree,
            min(self.relation_tree_max_touch_degree, int(self.relation_tree_touch_degree)),
        )
        queue = [(root_id, 0)]
        visited = {root_id}
        ordered_ids = [root_id]
        levels = {0: [root_id]}

        while queue and len(visited) < card_limit:
            current_id, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for neighbor_id in self._relation_tree_neighbor_ids(current_id):
                if neighbor_id in visited or self.world_model.get_entity(neighbor_id) is None:
                    continue
                visited.add(neighbor_id)
                ordered_ids.append(neighbor_id)
                levels.setdefault(depth + 1, []).append(neighbor_id)
                queue.append((neighbor_id, depth + 1))
                if len(visited) >= card_limit:
                    break

        for contemporary_id in self._contemporary_entity_ids(root_id, existing_ids=visited, limit=4):
            if len(visited) >= card_limit:
                break
            visited.add(contemporary_id)
            ordered_ids.append(contemporary_id)
            levels.setdefault(1, []).append(contemporary_id)

        if len(ordered_ids) <= 1:
            self._ensure_card(self.world_model.get_entity(root_id))
            return True

        root_x = float(source_card.get("canvas_x", 24))
        root_y = float(source_card.get("canvas_y", 84))
        horizontal_gap = 470
        vertical_gap = 38

        cards_by_id = {}
        for entity_id in ordered_ids:
            entity = self.world_model.get_entity(entity_id)
            if entity is None:
                continue
            card = self._ensure_card(entity, relayout=False, bring_to_front=False)
            if card is not None:
                cards_by_id[entity_id] = card

        for depth in sorted(levels):
            level_ids = [entity_id for entity_id in levels[depth] if entity_id in cards_by_id]
            current_y = root_y
            if depth > 0 and len(level_ids) > 1:
                current_y = root_y - ((len(level_ids) - 1) * 0.5 * 148)
                current_y = max(0, current_y)
            for entity_id in level_ids:
                card = cards_by_id[entity_id]
                card["canvas_x"] = max(0, root_x + depth * horizontal_gap)
                card["canvas_y"] = max(0, current_y)
                card["relation_tree_root_id"] = root_id
                card["relation_tree_depth"] = depth
                current_y += max(148, float(card.get("canvas_h", 340)) + vertical_gap)

        self.selected_entity_id = root_id
        self._layout_all_cards()
        return True

    def _place_new_card_in_canvas_view(self, card):
        if card is None or self.layout is None:
            return

        zoom = max(0.001, self.canvas_zoom)
        visible_x = (24 - self.canvas_offset_x) / zoom
        visible_y = (54 - self.canvas_offset_y) / zoom

        offset = max(0, len(self.cards) - 1) * 18
        card["canvas_x"] = max(0, visible_x + offset)
        card["canvas_y"] = max(0, visible_y + offset)
        self.selected_entity_id = card.get("entity_id")
        self._relayout_cards()

    def _ensure_schema_card(self, schema_name):
        if not schema_name:
            return None

        card_id = self._schema_card_id(schema_name)
        for index, card in enumerate(self.cards):
            if card.get("entity_id") == card_id:
                self.selected_entity_id = card_id
                card_obj = self._bring_card_to_front(index)
                self._layout_all_cards()
                return card_obj

        new_card = self._build_card_from_schema(schema_name)
        if new_card is not None:
            self.cards.append(new_card)
            self.selected_entity_id = card_id
            self._relayout_cards()
            return new_card
        return None

    def _format_schema_scalar(self, value):
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)

        text = str(value)
        if text == "":
            return "''"
        if re.match(r"^[A-Za-z0-9_./:-]+$", text):
            return text
        return "'" + text.replace("'", "''") + "'"

    def _format_schema_value_lines(self, key, value, indent):
        pad = " " * indent
        child_pad = " " * (indent + 2)

        if isinstance(value, dict):
            lines = [f"{pad}{key}:"]
            for child_key, child_value in value.items():
                lines.extend(self._format_schema_value_lines(child_key, child_value, indent + 2))
            return lines

        if isinstance(value, list):
            lines = [f"{pad}{key}:"]
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"{child_pad}-")
                    for child_key, child_value in item.items():
                        lines.extend(self._format_schema_value_lines(child_key, child_value, indent + 4))
                else:
                    lines.append(f"{child_pad}- {self._format_schema_scalar(item)}")
            return lines

        return [f"{pad}{key}: {self._format_schema_scalar(value)}"]

    def _schema_comment_suffix(self, schema_path):
        if not schema_path:
            return ""

        try:
            text = Path(schema_path).read_text(encoding="utf-8")
        except OSError:
            return ""

        match = re.search(r"(?m)^# -{5,}\s*$", text)
        if not match:
            return ""

        return text[match.start():].strip("\n")

    def _format_schema_file_text(self, schema, schema_path=None):
        lines = []

        for key in ("schema", "extends"):
            value = schema.get(key)
            if value is not None:
                lines.append(f"{key}: {self._format_schema_scalar(value)}")
                lines.append("")

        required = schema.get("required")
        if isinstance(required, list) and required:
            lines.append("required:")
            for item in required:
                lines.append(f"  - {self._format_schema_scalar(item)}")
            lines.append("")

        for key, value in schema.items():
            if key in {"schema", "extends", "required", "fields"}:
                continue
            lines.extend(self._format_schema_value_lines(key, value, 0))
            lines.append("")

        lines.append("fields:")
        lines.append("")

        fields = schema.get("fields", {})
        for field_name, spec in fields.items():
            lines.append(f"  {field_name}:")
            if isinstance(spec, dict):
                for key, value in spec.items():
                    lines.extend(self._format_schema_value_lines(key, value, 4))
            else:
                lines.append(f"    type: {self._format_schema_scalar(spec)}")
            lines.append("")

        suffix = self._schema_comment_suffix(schema_path)
        if suffix:
            lines.append(suffix)
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def _persist_schema_card(self, card):
        if card.get("card_kind") != "schema":
            return False

        card_view = card.get("card_view")
        if card_view is not None and card.get("schema_active_field"):
            card_view.commit_edit_field(card)

        schema_name = card.get("schema_name")
        schema_path = card.get("schema_path") or self.schema_loader.get_schema_file(schema_name)
        if not schema_name or schema_path is None:
            card["schema_status"] = "No schema file found"
            return False

        updated_schema = copy.deepcopy(card.get("schema_original", {}))
        updated_schema["schema"] = card.get("schema_schema_name") or updated_schema.get("schema") or schema_name
        if card.get("schema_extends") is not None:
            updated_schema["extends"] = card.get("schema_extends")
        updated_schema["fields"] = copy.deepcopy(card.get("schema_draft_fields", {}))

        schema_path = Path(schema_path)
        schema_path.write_text(
            self._format_schema_file_text(updated_schema, schema_path=schema_path),
            encoding="utf-8",
        )

        self.schema_loader.load_schemas()
        self.schema_field_usage = self._build_schema_field_usage()

        refreshed_schema = self.schema_loader.schemas.get(schema_name, updated_schema)
        refreshed_path = self.schema_loader.get_schema_file(schema_name) or schema_path
        card["schema_original"] = copy.deepcopy(refreshed_schema)
        card["schema_draft_fields"] = copy.deepcopy(refreshed_schema.get("fields", {}))
        card["schema_schema_name"] = refreshed_schema.get("schema", schema_name)
        card["schema_extends"] = refreshed_schema.get("extends")
        card["schema_path"] = refreshed_path
        card["schema_dirty"] = False
        card["schema_status"] = "Saved"
        card["subtitle"] = f"schema | {card.get('schema_extends') or 'root'}"
        card["card_view"] = SchemaCard(
            schema_name=schema_name,
            schema=refreshed_schema,
            schema_path=refreshed_path,
            usage_by_field=self.schema_field_usage,
        )
        return True

    def _open_image_file_dialog(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            selected = filedialog.askopenfilename(
                title="Select image",
                filetypes=[
                    ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"),
                    ("All files", "*.*"),
                ],
            )
        finally:
            root.destroy()
        return selected

    def _role_field_name(self, role_name):
        role_name = (role_name or "card").lower()
        if role_name == "card":
            return "card_image"
        if role_name == "design":
            return "design_image"
        return f"card_image_{role_name}"

    def _dataset_asset_folder(self, dataset_name):
        if not dataset_name:
            return "misc"
        return dataset_name.replace("\\", "_").replace("/", "_")

    def _entry_file_path_for_dataset(self, dataset_name):
        if not dataset_name:
            return None
        return str(self.PROJECT_ROOT / "entries" / f"{dataset_name}.yaml")

    def _load_card_drafts(self):
        try:
            with open(self.DRAFT_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

        if not isinstance(data, dict):
            return {}
        drafts = data.get("drafts", data)
        return drafts if isinstance(drafts, dict) else {}

    def _write_card_drafts(self):
        os.makedirs(os.path.dirname(str(self.DRAFT_CACHE_PATH)), exist_ok=True)
        payload = {"drafts": self.card_drafts}
        with open(self.DRAFT_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)

    def _entity_for_card(self, card):
        if card is None:
            return None

        card_view = card.get("card_view")
        if card_view is not None:
            entity = getattr(card_view, "entity", None)
            if entity is not None:
                return entity

        if self.world_model is not None:
            return self.world_model.get_entity(card.get("entity_id"))
        return None

    def _draft_entity_snapshot(self, entity):
        if not isinstance(entity, dict):
            return {}
        return {key: value for key, value in entity.items() if not key.startswith("_")}

    def _replace_entity_id_reference_value(self, value, old_entity_id, new_entity_id):
        if isinstance(value, str):
            if value.strip() == old_entity_id:
                return new_entity_id, True
            return value, False

        if isinstance(value, list):
            changed = False
            replaced = []
            for item in value:
                new_item, item_changed = self._replace_entity_id_reference_value(
                    item,
                    old_entity_id,
                    new_entity_id,
                )
                replaced.append(new_item)
                changed = changed or item_changed
            return replaced, changed

        if isinstance(value, dict):
            changed = False
            replaced = {}
            for key, item in value.items():
                new_key = new_entity_id if isinstance(key, str) and key.strip() == old_entity_id else key
                new_item, item_changed = self._replace_entity_id_reference_value(
                    item,
                    old_entity_id,
                    new_entity_id,
                )
                replaced[new_key] = new_item
                changed = changed or item_changed or new_key != key
            return replaced, changed

        return value, False

    def _replace_entity_references(self, entity, old_entity_id, new_entity_id):
        if not isinstance(entity, dict) or not old_entity_id or not new_entity_id:
            return False

        changed = False
        for field_key, value in list(entity.items()):
            if field_key in {"id", "_dataset"}:
                continue
            new_value, value_changed = self._replace_entity_id_reference_value(
                value,
                old_entity_id,
                new_entity_id,
            )
            if value_changed:
                entity[field_key] = new_value
                changed = True
        return changed

    def _replace_draft_references(self, old_entity_id, new_entity_id):
        changed = False
        for draft in self.card_drafts.values():
            if not isinstance(draft, dict):
                continue
            draft_entity = draft.get("entity")
            if self._replace_entity_references(draft_entity, old_entity_id, new_entity_id):
                changed = True
        if changed:
            self._write_card_drafts()
        return changed

    def _rewrite_entity_id_references(self, old_entity_id, new_entity_id, renamed_entity_id=None):
        if (
            self.world_model is None
            or not old_entity_id
            or not new_entity_id
            or old_entity_id == new_entity_id
        ):
            return []

        changed_entities = []
        for entity in list(self.world_model.loader.entities.values()):
            if not isinstance(entity, dict):
                continue
            if self._replace_entity_references(entity, old_entity_id, new_entity_id):
                changed_entities.append(entity)

        self._replace_draft_references(old_entity_id, new_entity_id)

        changed_ids = {str(entity.get("id")) for entity in changed_entities if entity.get("id")}
        for card in self.cards:
            card_entity = self._entity_for_card(card)
            if isinstance(card_entity, dict) and str(card_entity.get("id")) in changed_ids:
                card["subtitle"] = self._card_subtitle_for_entity(card_entity)
                if card.get("is_draft_entity", False):
                    self._save_card_draft(card)

        for entity in changed_entities:
            entity_id = str(entity.get("id") or "")
            if entity_id:
                card = self._find_card_by_entity_id(entity_id)
                if card is not None and card.get("is_draft_entity", False):
                    continue
                self._persist_entity_to_repository(entity)

        if hasattr(self.world_model, "touch_degrees"):
            self.world_model.touch_degrees.refresh()
        if hasattr(self.world_model.loader, "build_reference_graph"):
            self.world_model.loader.build_reference_graph()

        return changed_entities

    def _save_card_draft(self, card):
        self._sync_species_identity(card)
        self._sync_card_wiki_mentions(card)
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict) or not entity.get("id"):
            return False

        entity_id = str(entity["id"])
        id_change = card.get("pending_entity_id_change")
        if isinstance(id_change, dict):
            old_entity_id = id_change.get("old")
            if old_entity_id and old_entity_id != entity_id:
                self.card_drafts.pop(old_entity_id, None)
                if self.world_model is not None:
                    self.world_model.loader.entities.pop(old_entity_id, None)
                    self.world_model.loader.entities[entity_id] = entity
                card["entity_id"] = entity_id
                card.pop("pending_entity_id_change", None)

        active_field = card.get("active_edit_field")
        draft = dict(self.card_drafts.get(entity_id, {}))
        draft["entity"] = self._draft_entity_snapshot(entity)
        draft["dataset"] = entity.get("_dataset", entity.get("type", ""))
        draft["is_new_entry"] = bool(card.get("is_draft_entity", False) or draft.get("is_new_entry", False))

        edit_buffers = dict(draft.get("edit_buffers", {}))
        if active_field:
            edit_buffers[active_field] = {
                "text": card.get("edit_buffer", ""),
                "cursor": int(card.get("edit_cursor", 0)),
            }
        card["draft_edit_buffers"] = edit_buffers
        draft["edit_buffers"] = edit_buffers
        self.card_drafts[entity_id] = draft
        self._write_card_drafts()
        return True

    def _remove_card_draft(self, entity_id):
        if not entity_id or entity_id not in self.card_drafts:
            return False
        del self.card_drafts[entity_id]
        self._write_card_drafts()
        return True

    def _apply_cached_draft_to_card(self, card):
        entity_id = card.get("entity_id")
        draft = self.card_drafts.get(entity_id)
        if not isinstance(draft, dict):
            return False

        edit_buffers = draft.get("edit_buffers", {})
        card["draft_edit_buffers"] = edit_buffers if isinstance(edit_buffers, dict) else {}
        card["is_draft_entity"] = bool(draft.get("is_new_entry", False))
        return True

    def _hydrate_draft_entities(self, world_model):
        if world_model is None:
            return

        for entity_id, draft in self.card_drafts.items():
            if not isinstance(draft, dict) or not draft.get("is_new_entry", False):
                continue
            if world_model.get_entity(entity_id) is not None:
                continue

            entity = dict(draft.get("entity", {}))
            if not entity:
                continue
            entity["id"] = entity_id
            dataset_name = draft.get("dataset") or entity.get("type")
            if dataset_name == "ideas":
                for field_key in self.LEGACY_IDEA_FIELDS:
                    entity.pop(field_key, None)
            if dataset_name:
                entity["_dataset"] = dataset_name
                world_model.loader.datasets.setdefault(dataset_name, []).append(entity)
            world_model.loader.entities[entity_id] = entity

    def _format_yaml_scalar(self, value):
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)

        text = str(value)
        if "\n" in text:
            lines = text.splitlines()
            if not lines:
                return "''"
            return "|\n" + "\n".join(f"    {line}" for line in lines)

        if text == "":
            return "''"

        needs_quote = (
            text.strip() != text
            or text.lower() in {"null", "none", "true", "false", "yes", "no"}
            or any(ch in text for ch in [":", "#", "{", "}", "[", "]", ","])
        )
        if needs_quote:
            return "'" + text.replace("'", "''") + "'"
        return text

    def _format_yaml_value_lines(self, key, value, prefix):
        if isinstance(value, list):
            if not value:
                return [f"{prefix}{key}: []"]

            lines = [f"{prefix}{key}:"]
            for item in value:
                if isinstance(item, dict):
                    item_keys = list(item.keys())
                    if not item_keys:
                        lines.append("  - {}")
                        continue

                    first_key = item_keys[0]
                    lines.append(f"  - {first_key}: {self._format_yaml_scalar(item.get(first_key))}")
                    for child_key in item_keys[1:]:
                        child_value = item.get(child_key)
                        if isinstance(child_value, list):
                            if not child_value:
                                lines.append(f"    {child_key}: []")
                            else:
                                lines.append(f"    {child_key}:")
                                for child_item in child_value:
                                    if isinstance(child_item, dict):
                                        nested_keys = list(child_item.keys())
                                        if not nested_keys:
                                            lines.append("      - {}")
                                            continue
                                        nested_first = nested_keys[0]
                                        lines.append(f"      - {nested_first}: {self._format_yaml_scalar(child_item.get(nested_first))}")
                                        for nested_key in nested_keys[1:]:
                                            lines.append(f"        {nested_key}: {self._format_yaml_scalar(child_item.get(nested_key))}")
                                    else:
                                        lines.append(f"      - {self._format_yaml_scalar(child_item)}")
                            continue
                        if isinstance(child_value, dict):
                            if not child_value:
                                lines.append(f"    {child_key}: {{}}")
                            else:
                                lines.append(f"    {child_key}:")
                                for nested_key, nested_value in child_value.items():
                                    lines.append(f"      {nested_key}: {self._format_yaml_scalar(nested_value)}")
                            continue
                        lines.append(f"    {child_key}: {self._format_yaml_scalar(child_value)}")
                else:
                    lines.append(f"  - {self._format_yaml_scalar(item)}")
            return lines

        if isinstance(value, dict):
            if not value:
                return [f"{prefix}{key}: {{}}"]

            lines = [f"{prefix}{key}:"]
            for child_key, child_value in value.items():
                if isinstance(child_value, list):
                    if not child_value:
                        lines.append(f"    {child_key}: []")
                    else:
                        lines.append(f"    {child_key}:")
                        for item in child_value:
                            lines.append(f"      - {self._format_yaml_scalar(item)}")
                    continue
                lines.append(f"    {child_key}: {self._format_yaml_scalar(child_value)}")
            return lines

        scalar = self._format_yaml_scalar(value)
        return [f"{prefix}{key}: {scalar}"]

    def _format_yaml_entity_block(self, entity):
        if self._is_species_entity(entity):
            self._normalize_species_entity(entity)
            ordered_keys = ["id", "common_name", "binomial_name", "type"]
        else:
            ordered_keys = ["id", "pretty_name", "name", "type"]
        keys = [key for key in ordered_keys if key in entity]
        keys.extend(key for key in entity.keys() if key not in keys and not key.startswith("_"))

        lines = []
        for index, key in enumerate(keys):
            value = entity.get(key)
            prefix = "- " if index == 0 else "  "
            lines.extend(self._format_yaml_value_lines(key, value, prefix))

        return "\n".join(lines).rstrip() + "\n"

    def _find_yaml_entity_block(self, text, entity_id):
        start_pattern = rf"(?m)^- id: {re.escape(str(entity_id))}\s*$"
        start_match = re.search(start_pattern, text)
        if not start_match:
            return None

        next_match = re.search(r"(?m)^- id: ", text[start_match.end():])
        block_start = start_match.start()
        block_end = start_match.end() + next_match.start() if next_match else len(text)
        return block_start, block_end

    def _persist_entity_to_repository(self, entity, previous_entity_id=None):
        if not isinstance(entity, dict):
            return False

        entity_id = entity.get("id")
        lookup_entity_id = previous_entity_id or entity_id
        dataset_name = entity.get("_dataset", entity.get("type"))
        entry_path = self._entry_file_path_for_dataset(dataset_name)
        if not entity_id or entry_path is None:
            return False

        os.makedirs(os.path.dirname(entry_path), exist_ok=True)
        if os.path.exists(entry_path):
            with open(entry_path, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            text = ""

        if text.strip() == "[]":
            text = ""

        block = self._format_yaml_entity_block(entity)
        found = self._find_yaml_entity_block(text, lookup_entity_id)
        if found is None:
            separator = "" if not text.strip() else "\n"
            updated_text = text.rstrip() + separator + block
        else:
            block_start, block_end = found
            updated_text = text[:block_start] + block + text[block_end:].lstrip("\n")

        with open(entry_path, "w", encoding="utf-8") as f:
            f.write(updated_text)

        return True

    def _persist_card_entity(self, card):
        if card is None:
            return False

        self._sync_species_identity(card)
        self._sync_card_wiki_mentions(card)
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return False

        id_change = card.get("pending_entity_id_change")
        previous_entity_id = None
        if isinstance(id_change, dict):
            previous_entity_id = id_change.get("old") or None

        current_entity_id = str(card.get("entity_id") or entity.get("id") or "")
        if previous_entity_id or not str(entity.get("id") or "").strip():
            normalized_entity_id = self._normalize_entity_id_for_save(
                entity,
                current_id=previous_entity_id or current_entity_id,
            )
            if normalized_entity_id and normalized_entity_id != str(entity.get("id") or ""):
                previous_entity_id = previous_entity_id or current_entity_id
                entity["id"] = normalized_entity_id
                card["pending_entity_id_change"] = {
                    "old": previous_entity_id,
                    "new": normalized_entity_id,
                }

        persisted = self._persist_entity_to_repository(entity, previous_entity_id=previous_entity_id)
        if persisted and isinstance(entity, dict):
            self.relation_tree_neighbor_cache = {}
            self.canvas_relation_edges = []
            new_entity_id = str(entity.get("id"))
            old_entity_id = previous_entity_id

            if old_entity_id and old_entity_id != new_entity_id:
                if self.world_model is not None:
                    self.world_model.loader.entities.pop(old_entity_id, None)
                    self.world_model.loader.entities[new_entity_id] = entity

                card["entity_id"] = new_entity_id
                self.selected_entity_id = new_entity_id
                self.active_card_drag_id = new_entity_id if self.active_card_drag_id == old_entity_id else self.active_card_drag_id
                self.active_card_resize_id = new_entity_id if self.active_card_resize_id == old_entity_id else self.active_card_resize_id
                self._rewrite_entity_id_references(
                    old_entity_id,
                    new_entity_id,
                    renamed_entity_id=new_entity_id,
                )
                self._remove_card_draft(old_entity_id)

            card.pop("pending_entity_id_change", None)
            card["is_draft_entity"] = False
            remaining_buffers = card.get("draft_edit_buffers", {})
            if isinstance(remaining_buffers, dict) and remaining_buffers:
                entity_id = str(entity.get("id"))
                draft = dict(self.card_drafts.get(entity_id, {}))
                draft["entity"] = self._draft_entity_snapshot(entity)
                draft["dataset"] = entity.get("_dataset", entity.get("type", ""))
                draft["is_new_entry"] = False
                draft["edit_buffers"] = remaining_buffers
                self.card_drafts[entity_id] = draft
                self._write_card_drafts()
            else:
                card["draft_edit_buffers"] = {}
                self._remove_card_draft(entity.get("id"))
        return persisted

    def _build_canonical_image_path(self, entity_id, dataset_name, role_name, source_path):
        _, ext = os.path.splitext(source_path)
        ext = ext.lower() if ext else ".png"

        asset_folder = self._dataset_asset_folder(dataset_name)
        filename = f"{entity_id}_{role_name}{ext}"
        rel_path = os.path.join("assets", "cards", asset_folder, filename)
        return rel_path.replace("\\", "/")

    def _copy_to_canonical_asset(self, entity_id, dataset_name, role_name, source_path):
        canonical_rel_path = self._build_canonical_image_path(entity_id, dataset_name, role_name, source_path)
        canonical_abs_path = os.path.normpath(str(self.PROJECT_ROOT / canonical_rel_path))
        os.makedirs(os.path.dirname(canonical_abs_path), exist_ok=True)
        shutil.copy2(source_path, canonical_abs_path)
        return canonical_rel_path

    def _upsert_yaml_scalar_in_block(self, block_text, key, value):
        pattern = rf"(?m)^  {re.escape(key)}:.*$"
        replacement = f"  {key}: {value}"

        if re.search(pattern, block_text):
            return re.sub(pattern, replacement, block_text)

        insert_before_keys = [
            "tags",
            "start_year",
            "end_year",
            "entry_status",
        ]

        for anchor_key in insert_before_keys:
            anchor_pattern = rf"(?m)^  {re.escape(anchor_key)}:"
            match = re.search(anchor_pattern, block_text)
            if match:
                return block_text[:match.start()] + replacement + "\n" + block_text[match.start():]

        if not block_text.endswith("\n"):
            block_text += "\n"
        return block_text + replacement + "\n"

    def _write_image_fields_to_repository(self, entity_id, dataset_name, canonical_path, role_name):
        field_name = self._role_field_name(role_name)
        entry_path = self._entry_file_path_for_dataset(dataset_name)

        if entry_path is None or not os.path.exists(entry_path):
            return False

        with open(entry_path, "r", encoding="utf-8") as f:
            text = f.read()

        start_pattern = rf"(?m)^- id: {re.escape(entity_id)}\s*$"
        start_match = re.search(start_pattern, text)
        if not start_match:
            return False

        next_match = re.search(r"(?m)^- id: ", text[start_match.end():])
        block_start = start_match.start()
        block_end = start_match.end() + next_match.start() if next_match else len(text)

        block = text[block_start:block_end]
        updated_block = block
        updated_block = self._upsert_yaml_scalar_in_block(updated_block, field_name, canonical_path)

        existing_card_match = re.search(r"(?m)^  card_image:\s*(.+?)\s*$", block)
        has_card_image = bool(existing_card_match and existing_card_match.group(1).strip())

        if role_name != "design":
            updated_block = self._upsert_yaml_scalar_in_block(updated_block, "card_image", canonical_path)
        elif not has_card_image:
            updated_block = self._upsert_yaml_scalar_in_block(updated_block, "card_image", canonical_path)

        if updated_block == block:
            return True

        updated_text = text[:block_start] + updated_block + text[block_end:]

        with open(entry_path, "w", encoding="utf-8") as f:
            f.write(updated_text)

        return True

    def assign_card_image(self, entity_id, image_path, role_name=None):
        """
        Assign an image path to an entity/card currently visible in the
        Knowledge Layer.

        Behavior:
        * card role updates card_image
        * design role updates design_image and only fills card_image if empty
        * all other roles update their role-specific image field and also set
          card_image as the active preview
        """
        if not entity_id or not image_path:
            return False

        updated = False
        normalized_role = (role_name or "card").lower()
        field_name = self._role_field_name(role_name) if role_name else None

        def _apply_to_entity(entity_obj):
            nonlocal updated
            if entity_obj is None:
                return

            if field_name is not None:
                entity_obj[field_name] = image_path

            if normalized_role == "design":
                existing_card = entity_obj.get("card_image")
                if not (isinstance(existing_card, str) and existing_card.strip()):
                    entity_obj["card_image"] = image_path
            else:
                entity_obj["card_image"] = image_path

            updated = True

        if self.world_model is not None:
            entity = self.world_model.get_entity(entity_id)
            _apply_to_entity(entity)

        for card in self.cards:
            if card.get("entity_id") != entity_id:
                continue

            card_view = card.get("card_view")
            if card_view is not None and getattr(card_view, "entity", None) is not None:
                _apply_to_entity(card_view.entity)

        if updated:
            self._relayout_cards()

        return updated

    def choose_and_assign_card_image(self, entity_id, role_name=None):
        image_path = self._open_image_file_dialog()
        if not image_path:
            return False

        dataset_name = None
        if self.world_model is not None:
            entity = self.world_model.get_entity(entity_id)
            if entity is not None:
                dataset_name = entity.get("_dataset", entity.get("type", "entity"))

        canonical_path = image_path
        if dataset_name is not None and role_name is not None:
            canonical_path = self._copy_to_canonical_asset(entity_id, dataset_name, role_name, image_path)

        assigned = self.assign_card_image(entity_id, canonical_path, role_name=role_name)
        if not assigned:
            return False

        if dataset_name is not None and role_name is not None:
            self._write_image_fields_to_repository(entity_id, dataset_name, canonical_path, role_name)

        return True

    def _rebuild_browser_hitboxes(self):
        self.browser_hitboxes = []
        self.browser_toggle_hitboxes = []
        self.browser_filter_hitboxes = []

        if self.layout is None:
            return

        left_rect = self.layout["left_rect"]
        search_y = left_rect.y + 38 + self._browser_header_extra_height()
        self.browser_search_rect = pygame.Rect(left_rect.x + 12, search_y, left_rect.width - 24, self.BROWSER_SEARCH_H)

        chip_y = self.browser_search_rect.bottom + self.BROWSER_CONTROL_GAP
        chip_x = left_rect.x + 12
        for filter_name in self._browser_dataset_filters():
            label = self._format_browser_filter_label(filter_name)
            chip_w = self.font_for_layout.size(label)[0] + 16 if self.font_for_layout is not None else max(48, len(label) * 8 + 16)
            chip_rect = pygame.Rect(chip_x, chip_y, chip_w, self.BROWSER_FILTER_H)
            if chip_rect.right > left_rect.right - 12:
                break
            self.browser_filter_hitboxes.append(("dataset", filter_name, chip_rect))
            chip_x = chip_rect.right + 6

        incomplete_label = "Incomplete"
        incomplete_w = self.font_for_layout.size(incomplete_label)[0] + 18 if self.font_for_layout is not None else 92
        incomplete_rect = pygame.Rect(chip_x, chip_y, incomplete_w, self.BROWSER_FILTER_H)
        if incomplete_rect.right <= left_rect.right - 12:
            self.browser_filter_hitboxes.append(("incomplete", "incomplete", incomplete_rect))

        content_top = chip_y + self.BROWSER_FILTER_H + 8
        content_bottom = left_rect.bottom - 10
        visible_h = content_bottom - content_top

        line_height = self._font_line_height()
        total_h = len(self.browser_items) * line_height
        max_scroll = max(0, total_h - visible_h)
        self.browser_scroll = max(0, min(self.browser_scroll, max_scroll))

        line_y = content_top - self.browser_scroll

        for item in self.browser_items:
            row_top = line_y
            row_bottom = line_y + line_height

            if item["kind"] == "spacer":
                line_y += line_height
                continue

            if row_bottom < content_top:
                line_y += line_height
                continue

            if row_top > content_bottom:
                break

            if item["kind"] in ("entity", "tree_entity", "schema"):
                row_rect = pygame.Rect(left_rect.x + 10, line_y - 1, left_rect.width - 20, line_height)
                self.browser_hitboxes.append((item["entity_id"], row_rect))

                if item["kind"] == "tree_entity" and item.get("expandable", False):
                    depth = item.get("depth", 0)
                    indent_px = depth * 18
                    base_x = left_rect.x + 12 + indent_px
                    caret_rect = pygame.Rect(base_x, line_y + max(2, (line_height - 14) // 2), 14, 14)
                    self.browser_toggle_hitboxes.append((item["entity_id"], caret_rect))

            line_y += line_height

    def _browser_content_bounds(self, left_rect):
        if self.browser_search_rect is not None:
            content_top = (
                self.browser_search_rect.bottom
                + self.BROWSER_CONTROL_GAP
                + self.BROWSER_FILTER_H
                + 8
            )
        else:
            content_top = left_rect.y + 48
        return content_top, left_rect.bottom - 10

    def _browser_item_at_pos(self, mouse_pos, left_rect):
        content_top, content_bottom = self._browser_content_bounds(left_rect)
        if mouse_pos[1] < content_top or mouse_pos[1] > content_bottom:
            return None

        line_height = self._font_line_height()
        if line_height <= 0:
            return None

        line_y = content_top - self.browser_scroll
        for item in self.browser_items:
            row_top = line_y
            row_bottom = line_y + line_height

            if item.get("kind") == "spacer":
                line_y += line_height
                continue

            if row_bottom < content_top:
                line_y += line_height
                continue

            if row_top > content_bottom:
                break

            row_rect = pygame.Rect(left_rect.x + 10, line_y - 1, left_rect.width - 20, line_height)
            if row_rect.collidepoint(mouse_pos):
                return item

            line_y += line_height

        return None

    def rebuild(self, app_width, app_height, world_model, repository_scope_entity_id, font):
        self.reset()

        self.app_width = app_width
        self.app_height = app_height
        self.font_for_layout = font
        self.world_model = world_model
        self._hydrate_draft_entities(world_model)
        self.repository_scope_entity_id = repository_scope_entity_id
        self.browser_items = self._build_browser_items(world_model)
        self._refresh_layout_geometry()

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
            self._ensure_card(self._startup_entity())
            self.browser_items = self._build_browser_items(world_model)
            self._rebuild_browser_hitboxes()

        self._relayout_cards()

    def _draw_card(self, screen, font, card):
        card_view = card.get("card_view")
        if card_view is None:
            return

        previous_clip = screen.get_clip()
        visual_rect = self._card_visual_rect(card)
        if visual_rect is not None:
            screen.set_clip(previous_clip.clip(visual_rect))
        try:
            card_view.draw_card(screen, card.get("layout_font", font), card)
            self._draw_card_type_picker(screen, card.get("layout_font", font), card)
        finally:
            screen.set_clip(previous_clip)

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

    def _draw_card_type_picker(self, screen, font, card):
        if not card.get("type_picker_open", False):
            card["type_picker_hitboxes"] = []
            card["type_picker_rect"] = None
            return

        type_label_rect = card.get("type_label_rect")
        card_rect = card.get("rect")
        if type_label_rect is None or card_rect is None:
            card["type_picker_hitboxes"] = []
            card["type_picker_rect"] = None
            return

        templates = self._conversion_templates()
        if not templates:
            card["type_picker_hitboxes"] = []
            card["type_picker_rect"] = None
            return

        visible_templates, scroll, max_scroll = self._card_type_picker_visible_templates(card, templates)
        picker_w = min(300, max(180, card_rect.width - 24))
        picker_h = 30 + len(visible_templates) * self.CARD_TYPE_PICKER_ROW_H + 8
        picker_x = type_label_rect.x
        picker_y = type_label_rect.bottom + 4
        if picker_x + picker_w > card_rect.right - 8:
            picker_x = card_rect.right - picker_w - 8
        picker_rect = pygame.Rect(picker_x, picker_y, picker_w, picker_h)
        card["type_picker_rect"] = picker_rect

        pygame.draw.rect(screen, (22, 26, 36), picker_rect)
        pygame.draw.rect(screen, (174, 184, 204), picker_rect, 1)
        title_surface = font.render("Change Class To", True, (238, 238, 238))
        screen.blit(title_surface, (picker_rect.x + 8, picker_rect.y + 7))
        if max_scroll > 0:
            range_text = f"{scroll + 1}-{scroll + len(visible_templates)} / {len(templates)}"
            range_surface = font.render(range_text, True, (172, 184, 204))
            screen.blit(range_surface, (picker_rect.right - range_surface.get_width() - 8, picker_rect.y + 7))

        card["type_picker_hitboxes"] = []
        row_y = picker_rect.y + 30
        for template in visible_templates:
            row_rect = pygame.Rect(picker_rect.x + 8, row_y, picker_rect.width - 16, self.CARD_TYPE_PICKER_ROW_H - 4)
            hovered = row_rect.collidepoint(pygame.mouse.get_pos())
            fill = (52, 62, 82) if hovered else (34, 38, 50)
            pygame.draw.rect(screen, fill, row_rect)
            pygame.draw.rect(screen, (104, 116, 138), row_rect, 1)
            label = template.get("label") or template.get("entity_type") or "Entry"
            dataset = template.get("dataset_name", "")
            text_surface = font.render(f"{label} [{dataset}]", True, (238, 238, 238))
            screen.blit(text_surface, (row_rect.x + 6, row_rect.y + 3))
            card["type_picker_hitboxes"].append((template, row_rect))
            row_y += self.CARD_TYPE_PICKER_ROW_H

    def _handle_template_picker_keydown(self, event):
        if not self.show_template_picker:
            return False

        if event.key == pygame.K_ESCAPE:
            if self.template_picker_search_active and self.template_picker_search_query:
                self.template_picker_search_query = ""
                self.template_picker_scroll = 0
                self._build_template_picker_hitboxes()
                return True
            self.show_template_picker = False
            self.template_picker_search_active = False
            self.template_picker_mode = "create"
            self.template_picker_context = {}
            self.template_picker_status = ""
            self._build_template_picker_hitboxes()
            return True

        if not self.template_picker_search_active:
            return False

        if event.key == pygame.K_BACKSPACE:
            self.template_picker_search_query = self.template_picker_search_query[:-1]
            self.template_picker_scroll = 0
            self._build_template_picker_hitboxes()
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            self.template_picker_search_query += text
            self.template_picker_scroll = 0
            self._build_template_picker_hitboxes()
            return True

        return False

    def _handle_keydown_event(self, event):
        if self.entry_name_prompt is not None:
            if self._handle_entry_name_prompt_keydown(event):
                return "__ui_consumed__"
            return None

        if self._handle_task_checklist_keydown(event):
            return "__ui_consumed__"

        if self._handle_template_picker_keydown(event):
            return "__ui_consumed__"

        if self.canvas_relation_link_source_id is not None and event.key == pygame.K_ESCAPE:
            self._clear_canvas_relation_link()
            self._relayout_cards()
            return "__ui_consumed__"

        if self.relation_link_target is not None:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._finish_relation_browser_link()
                return "__ui_consumed__"

            if event.key == pygame.K_ESCAPE:
                self._finish_relation_browser_link()
                return "__ui_consumed__"

        if (
            self.timeline_edit_target is not None
            and self.timeline_edit_target.get("mode") == "reanchor"
            and event.key == pygame.K_ESCAPE
        ):
            self._clear_timeline_edit_target()
            self._relayout_cards()
            return "__ui_consumed__"

        for index in range(len(self.cards) - 1, -1, -1):
            card = self.cards[index]
            card_view = card.get("card_view")
            if card_view is None or not card.get("is_edit_mode", False):
                continue
            if not card.get("active_edit_field"):
                continue

            if card.get("delete_confirm_active", False) and event.key == pygame.K_ESCAPE:
                card["delete_confirm_active"] = False
                self._bring_card_to_front(index)
                self._relayout_cards()
                return "__ui_consumed__"

            if (
                card.get("active_edit_field") == "wiki_entry"
                and event.key == pygame.K_l
                and (event.mod & pygame.KMOD_CTRL)
            ):
                self._bring_card_to_front(index)
                self._open_wiki_link_picker(card)
                self._relayout_cards()
                return "__ui_consumed__"

            if self._handle_wiki_link_picker_keydown(card, event):
                self._bring_card_to_front(index)
                self._relayout_cards()
                return "__ui_consumed__"

            if self._handle_relation_picker_keydown(card, event):
                self._bring_card_to_front(index)
                if card.get("last_edit_action") == "commit":
                    self._persist_card_entity(card)
                else:
                    self._save_card_draft(card)
                card["last_edit_action"] = None
                self._sync_card_years_from_entity(card)
                self._refresh_timeline_items()
                self._relayout_cards()
                return "__ui_consumed__"

            if card_view.handle_keydown(card, event):
                self._bring_card_to_front(index)
                if not card_view.is_relation_edit_field(card.get("active_edit_field")):
                    self._close_relation_picker(card)
                if card.get("last_edit_action") == "commit":
                    self._persist_card_entity(card)
                elif card.get("last_edit_action") == "cancel":
                    card["last_edit_action"] = None
                else:
                    self._save_card_draft(card)
                card["last_edit_action"] = None
                self._sync_card_years_from_entity(card)
                self._refresh_timeline_items()
                self._relayout_cards()
                return "__ui_consumed__"

            return "__ui_consumed__"

        if self.browser_search_active:
            if event.key == pygame.K_ESCAPE:
                self.browser_search_active = False
                self.browser_items = self._build_browser_items(self.world_model)
                self._rebuild_browser_hitboxes()
                return "__ui_consumed__"
            if event.key == pygame.K_BACKSPACE:
                self.browser_search_query = self.browser_search_query[:-1]
                self.browser_items = self._build_browser_items(self.world_model)
                self._rebuild_browser_hitboxes()
                return "__ui_consumed__"
            text = getattr(event, "unicode", "")
            if text and text.isprintable():
                self.browser_search_query += text
                self.browser_items = self._build_browser_items(self.world_model)
                self._rebuild_browser_hitboxes()
                return "__ui_consumed__"

        for index in range(len(self.cards) - 1, -1, -1):
            card = self.cards[index]
            card_view = card.get("card_view")
            if card_view is None:
                continue

            if card.get("card_kind") == "schema":
                if card_view.handle_keydown(card, event):
                    self._bring_card_to_front(index)
                    self._relayout_cards()
                    return "__ui_consumed__"
                continue

            if card.get("is_edit_mode", False):
                if card.get("delete_confirm_active", False) and event.key == pygame.K_ESCAPE:
                    card["delete_confirm_active"] = False
                    self._bring_card_to_front(index)
                    self._relayout_cards()
                    return "__ui_consumed__"

                if (
                    card.get("active_edit_field") == "wiki_entry"
                    and event.key == pygame.K_l
                    and (event.mod & pygame.KMOD_CTRL)
                ):
                    self._bring_card_to_front(index)
                    self._open_wiki_link_picker(card)
                    self._relayout_cards()
                    return "__ui_consumed__"

                if self._handle_wiki_link_picker_keydown(card, event):
                    self._bring_card_to_front(index)
                    self._relayout_cards()
                    return "__ui_consumed__"

                if self._handle_relation_picker_keydown(card, event):
                    self._bring_card_to_front(index)
                    if card.get("last_edit_action") == "commit":
                        self._persist_card_entity(card)
                    else:
                        self._save_card_draft(card)
                    card["last_edit_action"] = None
                    self._sync_card_years_from_entity(card)
                    self._refresh_timeline_items()
                    self._relayout_cards()
                    return "__ui_consumed__"

                if card_view.handle_keydown(card, event):
                    self._bring_card_to_front(index)
                    if not card_view.is_relation_edit_field(card.get("active_edit_field")):
                        self._close_relation_picker(card)
                    if card.get("last_edit_action") == "commit":
                        self._persist_card_entity(card)
                    elif card.get("last_edit_action") == "cancel":
                        card["last_edit_action"] = None
                    else:
                        self._save_card_draft(card)
                    card["last_edit_action"] = None
                    self._sync_card_years_from_entity(card)
                    self._refresh_timeline_items()
                    self._relayout_cards()
                    return "__ui_consumed__"

        return None

    def _handle_mousewheel_event(self, event, timeline_rect, left_rect, right_rect):
        mouse_pos = pygame.mouse.get_pos()

        if timeline_rect.collidepoint(mouse_pos):
            if self.timeline_ui.handle_event(event):
                return "__ui_consumed__"

        if left_rect.collidepoint(mouse_pos):
            line_step = self._font_line_height()
            self.browser_scroll = max(0, self.browser_scroll - event.y * line_step)
            self._rebuild_browser_hitboxes()
            return "__ui_consumed__"

        if (
            self.show_template_picker
            and self.template_picker_rect is not None
            and self.template_picker_rect.collidepoint(mouse_pos)
        ):
            visible_count = max(1, len(self.template_picker_visible_rows))
            max_scroll = max(0, self.template_picker_total_rows - visible_count)
            self.template_picker_scroll = max(0, min(max_scroll, self.template_picker_scroll - event.y))
            self._build_template_picker_hitboxes()
            return "__ui_consumed__"

        if right_rect.collidepoint(mouse_pos):
            if self._scroll_type_picker_at(mouse_pos, event.y):
                return "__ui_consumed__"
            if self._scroll_card_at(mouse_pos, event.y):
                return "__ui_consumed__"
            zoom_factor = 1.12 if event.y > 0 else 1 / 1.12
            self._set_canvas_zoom_at(mouse_pos, zoom_factor)
            return "__ui_consumed__"

        return None

    def _handle_mousebuttonup_event(self, event):
        if event.button != 1:
            return None

        self.active_timeline_resize = False
        self.active_timeline_pan = False
        self.timeline_resize_start_mouse_y = None
        self.timeline_resize_start_height = None
        self.timeline_pan_last_mouse_x = None
        active_color_slider = self.active_card_color_slider
        if active_color_slider is not None:
            card = self._find_card_by_entity_id(active_color_slider.get("entity_id"))
            if card is not None:
                self._save_card_draft(card)
                if not card.get("is_draft_entity", False):
                    self._persist_card_entity(card)
        self.active_card_drag_id = None
        self.active_card_resize_id = None
        self.active_card_color_slider = None
        self.active_canvas_pan = False
        self.card_drag_mouse_offset = (0, 0)
        self.card_resize_start_mouse = None
        self.card_resize_start_size = None
        self.card_resize_start_position = None
        self.card_resize_edges = None
        self.canvas_pan_start_mouse = None
        self.canvas_pan_start_offset = None
        return "__ui_consumed__"

    def _handle_mousemotion_event(self, event):
        if self.active_timeline_resize:
            dy = event.pos[1] - self.timeline_resize_start_mouse_y
            self.timeline_panel_height = self._clamp_timeline_panel_height(
                self.app_height,
                self.timeline_resize_start_height + dy,
            )
            self._refresh_layout_geometry()
            return "__ui_consumed__"

        if self.active_timeline_pan:
            if self.timeline_pan_last_mouse_x is None:
                self.timeline_pan_last_mouse_x = event.pos[0]
                return "__ui_consumed__"

            dx = event.pos[0] - self.timeline_pan_last_mouse_x
            self.timeline_pan_last_mouse_x = event.pos[0]
            if dx:
                self.timeline_ui.pan_by_pixels(-dx)
            return "__ui_consumed__"

        if self.active_card_color_slider is not None:
            slider = self.active_card_color_slider
            card = self._find_card_by_entity_id(slider.get("entity_id"))
            if card is not None:
                self._set_card_color_from_slider(
                    card,
                    slider.get("channel"),
                    slider.get("slider_rect"),
                    event.pos[0],
                    persist=False,
                    role=slider.get("role"),
                    section_id=slider.get("section_id"),
                )
                self._relayout_cards()
            return "__ui_consumed__"

        if self.active_card_drag_id is not None:
            for card in self.cards:
                if card.get("entity_id") == self.active_card_drag_id:
                    canvas_x, canvas_y = self._screen_to_canvas_pos(event.pos)
                    card["canvas_x"] = canvas_x - self.card_drag_mouse_offset[0]
                    card["canvas_y"] = canvas_y - self.card_drag_mouse_offset[1]
                    self._relayout_cards()
                    return "__ui_consumed__"

        if self.active_card_resize_id is not None:
            for card in self.cards:
                if card.get("entity_id") == self.active_card_resize_id:
                    zoom = max(0.001, self.canvas_zoom)
                    dx = (event.pos[0] - self.card_resize_start_mouse[0]) / zoom
                    dy = (event.pos[1] - self.card_resize_start_mouse[1]) / zoom
                    min_w = 300
                    min_h = 260
                    start_x, start_y = self.card_resize_start_position
                    start_w, start_h = self.card_resize_start_size
                    resize_edges = self.card_resize_edges or "bottom_right"

                    new_x = start_x
                    new_y = start_y
                    new_w = start_w
                    new_h = start_h

                    if "left" in resize_edges:
                        new_x = start_x + dx
                        new_w = start_w - dx
                        if new_w < min_w:
                            new_x = start_x + (start_w - min_w)
                            new_w = min_w

                    if "right" in resize_edges:
                        new_w = max(min_w, start_w + dx)

                    if "top" in resize_edges:
                        new_y = start_y + dy
                        new_h = start_h - dy
                        if new_h < min_h:
                            new_y = start_y + (start_h - min_h)
                            new_h = min_h

                    if "bottom" in resize_edges:
                        new_h = max(min_h, start_h + dy)

                    card["canvas_x"] = int(new_x)
                    card["canvas_y"] = int(new_y)
                    card["canvas_w"] = int(new_w)
                    card["canvas_h"] = int(new_h)
                    self._relayout_cards()
                    return "__ui_consumed__"

        if self.active_canvas_pan:
            if self.canvas_pan_start_mouse is None or self.canvas_pan_start_offset is None:
                return None

            dx = event.pos[0] - self.canvas_pan_start_mouse[0]
            dy = event.pos[1] - self.canvas_pan_start_mouse[1]
            self.canvas_offset_x = self.canvas_pan_start_offset[0] + dx
            self.canvas_offset_y = self.canvas_pan_start_offset[1] + dy
            self._layout_all_cards()
            return "__ui_consumed__"

        return None

    def _handle_left_panel_click(self, mouse_pos, left_rect):
        if not left_rect.collidepoint(mouse_pos):
            return None

        if self.browser_search_rect is not None and self.browser_search_rect.collidepoint(mouse_pos):
            self.browser_search_active = True
            return "__ui_consumed__"
        self.browser_search_active = False

        for filter_kind, filter_value, hitbox in self.browser_filter_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                if filter_kind == "dataset":
                    self.browser_filter_dataset = filter_value
                else:
                    self.browser_filter_incomplete_only = not self.browser_filter_incomplete_only
                self.browser_items = self._build_browser_items(self.world_model)
                self._rebuild_browser_hitboxes()
                return "__ui_consumed__"

        for entity_id, hitbox in self.browser_toggle_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                self._set_expanded(entity_id, not self._is_expanded(entity_id))
                self.browser_items = self._build_browser_items(self.world_model)
                self._rebuild_browser_hitboxes()
                return "__ui_consumed__"

        if self.relation_link_target is not None:
            return self._handle_relation_link_mode_click(mouse_pos, left_rect)

        for entity_id, hitbox in self.browser_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                self.selected_entity_id = entity_id

                schema_name = self._schema_name_from_card_id(entity_id)
                if schema_name is not None:
                    self._ensure_schema_card(schema_name)
                    return "__ui_consumed__"

                if self.world_model is not None:
                    entity = self.world_model.get_entity(entity_id)
                    self._ensure_card(entity)

                return "__ui_consumed__"

        return None

    def _insert_relation_reference_into_card(self, card, field_key, entity_id):
        entity = self._entity_for_card(card)
        card_view = card.get("card_view") if card is not None else None
        if not isinstance(entity, dict) or not field_key or not entity_id or card_view is None:
            return False

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
            return "__ui_consumed__"

        entity_id = item.get("entity_id")
        if item.get("kind") == "schema" or self._schema_name_from_card_id(entity_id) is not None:
            self.relation_link_status = "Pick an entry, not a schema"
            source_card = self.relation_link_target.get("source_card")
            if isinstance(source_card, dict):
                source_card["relation_link_status"] = self.relation_link_status
            self._rebuild_browser_hitboxes()
            self._relayout_cards()
            return "__ui_consumed__"

        if item.get("kind") not in {"entity", "tree_entity"}:
            return "__ui_consumed__"

        if not self._browser_item_matches_relation_target(item):
            target_label = self._relation_target_label(self.relation_link_target.get("target"))
            self.relation_link_status = f"Pick a matching {target_label} entry"
            source_card = self.relation_link_target.get("source_card")
            if isinstance(source_card, dict):
                source_card["relation_link_status"] = self.relation_link_status
            self._rebuild_browser_hitboxes()
            self._relayout_cards()
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
                self.relation_link_status = "Pick a different card"
                if isinstance(source_card, dict):
                    source_card["relation_link_status"] = self.relation_link_status
                self._relayout_cards()
                return "__ui_consumed__"

            entity = self.world_model.get_entity(target_entity_id) if self.world_model is not None else None
            if entity is None or not self._entity_matches_relation_target(
                entity,
                self.relation_link_target.get("target"),
            ):
                target_label = self._relation_target_label(self.relation_link_target.get("target"))
                self.relation_link_status = f"Pick a matching {target_label} card"
                if isinstance(source_card, dict):
                    source_card["relation_link_status"] = self.relation_link_status
                self._relayout_cards()
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

        created_entity = self._create_named_template_entity(template, entry_name)
        if created_entity is None:
            self.template_picker_status = "Could not create linked entry"
            return False

        context = dict(self.template_picker_context or {})
        source_card = context.get("card")
        if source_card not in self.cards:
            source_card = self._find_card_by_entity_id(context.get("source_entity_id"))

        created_entity_id = str(created_entity.get("id") or "").strip()
        if source_card is not None and created_entity_id:
            self._replace_relation_reference_on_card(
                source_card,
                context.get("field_key"),
                context.get("missing_ref"),
                created_entity_id,
            )

        self.pending_new_entry_name = None
        self.show_template_picker = False
        self.template_picker_search_query = ""
        self.template_picker_search_active = False
        self.template_picker_mode = "create"
        self.template_picker_context = {}
        self.template_picker_status = ""
        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        self._build_template_picker_hitboxes()
        self._relayout_cards()
        return True

    def _handle_wiki_link_click(self, card, link_info):
        if self.world_model is None or card is None or not isinstance(link_info, dict):
            return False
        if card.get("is_edit_mode", False):
            return False

        link_ref = str(link_info.get("ref") or link_info.get("label") or "").strip()
        if not link_ref:
            return False

        resolved_ref = self._resolve_wiki_mention_ref(link_ref)
        entity = self.world_model.get_entity(resolved_ref) if resolved_ref else None
        if entity is not None:
            self._ensure_card(entity)
            return True

        self._sync_card_wiki_mentions(card)
        return self._open_relation_target_template_picker(
            card,
            {
                "kind": "missing",
                "field_key": "wiki_mentions",
                "entity_id": link_ref,
                "label": link_ref,
                "target": "entity_core",
            },
        )

    def _handle_relation_chip_click(self, card, relation_info, mouse_pos=None):
        if self.world_model is None or card is None or not isinstance(relation_info, dict):
            return False

        kind = relation_info.get("kind")
        entity_id = str(relation_info.get("entity_id") or "").strip()

        if not card.get("is_edit_mode", False):
            if kind == "existing" and entity_id:
                entity = self.world_model.get_entity(entity_id)
                if entity is not None:
                    self._ensure_card(entity)
                    return True
            return False

        if kind == "link_existing":
            return self._begin_relation_browser_link(card, relation_info)

        if kind == "note":
            return self._open_relation_note_prompt(card, relation_info)

        remove_rect = relation_info.get("remove_rect")
        if (
            kind in {"existing", "missing"}
            and entity_id
            and mouse_pos is not None
            and remove_rect is not None
            and remove_rect.collidepoint(mouse_pos)
        ):
            removed = self._remove_relation_reference_from_card(
                card,
                relation_info.get("field_key"),
                entity_id,
            )
            if removed:
                self._relayout_cards()
            return removed

        if kind == "existing" and entity_id:
            entity = self.world_model.get_entity(entity_id)
            if entity is not None:
                self._ensure_card(entity)
                return True

        if kind == "missing" and relation_info.get("field_key") == "wiki_mentions":
            return self._open_relation_target_template_picker(card, relation_info)

        created_entity = self._create_relation_target_entity(relation_info)
        if created_entity is None:
            return False

        created_entity_id = str(created_entity.get("id", "")).strip()
        if kind == "create" and created_entity_id:
            self._insert_relation_reference_into_card(card, relation_info.get("field_key"), created_entity_id)
            self.browser_items = self._build_browser_items(self.world_model)
            self._rebuild_browser_hitboxes()

        self._relayout_cards()
        return True

    def _is_task_card_obj(self, card):
        entity = self._entity_for_card(card)
        return (
            isinstance(entity, dict)
            and (entity.get("_dataset") == "tasks" or entity.get("type") == "task")
        )

    def _normalize_task_checklist(self, entity):
        raw_items = entity.get("checklist")
        if not isinstance(raw_items, list):
            raw_items = []

        items = []
        for item in raw_items:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("label") or item.get("name") or "").strip()
                done = bool(item.get("done", item.get("checked", False)))
            else:
                text = str(item or "").strip()
                done = False
            if text:
                items.append({"text": text, "done": done})
        entity["checklist"] = items
        return items

    def _set_task_finished(self, card, finished):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return False

        entity["entry_status"] = "finished" if finished else "incomplete"
        self._persist_card_entity(card)
        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return True

    def _handle_task_checklist_click(self, card, mouse_pos):
        if not self._is_task_card_obj(card):
            return False

        finish_rect = card.get("task_finish_checkbox_rect")
        if finish_rect is not None and finish_rect.collidepoint(mouse_pos):
            entity = self._entity_for_card(card)
            return self._set_task_finished(card, not self._is_finished_task_entity(entity))

        entity = self._entity_for_card(card)
        items = self._normalize_task_checklist(entity)
        for item_index, checkbox_rect in card.get("task_checklist_hitboxes", []):
            if checkbox_rect.collidepoint(mouse_pos) and 0 <= item_index < len(items):
                items[item_index]["done"] = not bool(items[item_index].get("done"))
                self._persist_card_entity(card)
                self._relayout_cards()
                return True

        input_rect = card.get("task_checklist_input_rect")
        if input_rect is not None and input_rect.collidepoint(mouse_pos):
            self.browser_search_active = False
            for other_card in self.cards:
                other_card["task_checklist_input_active"] = other_card is card
            card.setdefault("task_checklist_input_buffer", "")
            self._relayout_cards()
            return True

        return False

    def _active_task_checklist_card(self):
        for card in reversed(self.cards):
            if card.get("task_checklist_input_active"):
                return card
        return None

    def _submit_task_checklist_input(self, card):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict):
            return False

        text = str(card.get("task_checklist_input_buffer") or "").strip()
        if not text:
            card["task_checklist_input_active"] = False
            self._relayout_cards()
            return True

        items = self._normalize_task_checklist(entity)
        items.append({"text": text, "done": False})
        entity["checklist"] = items
        entity["entry_status"] = "incomplete"
        card["task_checklist_input_buffer"] = ""
        card["task_checklist_input_active"] = False
        self._persist_card_entity(card)
        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return True

    def _handle_task_checklist_keydown(self, event):
        card = self._active_task_checklist_card()
        if card is None:
            return False

        buffer_text = str(card.get("task_checklist_input_buffer") or "")
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self._submit_task_checklist_input(card)
        if event.key == pygame.K_ESCAPE:
            card["task_checklist_input_active"] = False
            self._relayout_cards()
            return True
        if event.key == pygame.K_BACKSPACE:
            card["task_checklist_input_buffer"] = buffer_text[:-1]
            self._relayout_cards()
            return True
        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            card["task_checklist_input_buffer"] = buffer_text + text
            self._relayout_cards()
            return True
        return True

    def _handle_schema_card_click(self, card, index, mouse_pos):
        card_view = card.get("card_view")
        if card_view is None:
            return None

        save_rect = card.get("schema_save_rect")
        if save_rect is not None and save_rect.collidepoint(mouse_pos):
            card_obj = self._bring_card_to_front(index)
            self._persist_schema_card(card_obj)
            self.browser_items = self._build_browser_items(self.world_model)
            self._rebuild_browser_hitboxes()
            self._relayout_cards()
            return "__ui_consumed__"

        for field_name, field_rect in card.get("schema_field_hitboxes", []):
            if field_rect.collidepoint(mouse_pos):
                card_obj = self._bring_card_to_front(index)
                card_obj["card_view"].begin_edit_field(card_obj, field_name)
                self._relayout_cards()
                return "__ui_consumed__"

        return None

    def _handle_editable_field_click(self, card, index, mouse_pos):
        card_view = card.get("card_view")
        if card_view is None:
            return None
        if not card.get("is_edit_mode", False):
            card["editable_field_hitboxes"] = []
            return None

        for field_key, field_rect in card.get("editable_field_hitboxes", []):
            if not field_rect.collidepoint(mouse_pos):
                continue

            card_obj = self._bring_card_to_front(index)
            self.browser_search_active = False
            card_obj["card_view"].begin_edit_field(card_obj, field_key)
            if card_obj.get("last_edit_action") == "commit":
                self._persist_card_entity(card_obj)
                card_obj["last_edit_action"] = None
            if field_key == "wiki_entry":
                card_obj["card_view"].set_edit_cursor_from_pos(card_obj, field_key, mouse_pos, self.font_for_layout)
            if self._is_temporal_field(field_key):
                self._set_timeline_edit_target(card_obj, field_key)
            else:
                self._clear_timeline_edit_target()
            if field_key != "wiki_entry":
                self._close_wiki_link_picker(card_obj)
            if card_obj["card_view"].is_relation_edit_field(field_key):
                self._open_relation_picker(card_obj)
            else:
                self._close_relation_picker(card_obj)
            self._relayout_cards()
            return "__ui_consumed__"

        return None

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
                if card_obj.get("is_edit_mode", False) and card_obj.get("active_edit_field"):
                    self._save_card_draft(card_obj)
                card_obj["card_view"].toggle_edit_mode(card_obj)
                if not card_obj.get("is_edit_mode", False):
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
                    else:
                        self._insert_relation_from_picker(card_obj, match_index=match_index)
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
                            persist=True,
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
                        self._layout_all_cards()
                        return "__ui_consumed__"
                    action_id = tool_info.get("action_id")
                    if action_id:
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

            for role_name, button_rect in card.get("media_import_hitboxes", []):
                if button_rect.collidepoint(mouse_pos):
                    card_obj = self._bring_card_to_front(index)
                    self.choose_and_assign_card_image(card_obj["entity_id"], role_name=role_name)
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
                    self._focus_timeline_year(year)
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

    def _draw_template_picker(self, screen, font):
        if not self.show_template_picker or self.template_picker_rect is None:
            return

        pygame.draw.rect(screen, (24, 28, 40), self.template_picker_rect)
        pygame.draw.rect(screen, (160, 168, 186), self.template_picker_rect, 1)
        pending_name = str(self.pending_new_entry_name or "").strip()
        if self.template_picker_mode == "convert":
            title_text = self.template_picker_status or "Choose Class"
        elif pending_name:
            title_text = f"Choose Entry Type: {pending_name}"
        else:
            title_text = "Create New Entry From Schema"
        picker_title = font.render(title_text, True, (236, 236, 236))
        max_title_w = self.template_picker_rect.width - 24
        if picker_title.get_width() > max_title_w:
            picker_title = font.render("Choose Entry Type", True, (236, 236, 236))
        title_y = self.template_picker_rect.y + max(
            6,
            (self._template_picker_header_height() - font.get_linesize()) // 2,
        )
        screen.blit(picker_title, (self.template_picker_rect.x + 12, title_y))

        if self.template_picker_search_rect is not None:
            search_fill = (38, 44, 58) if self.template_picker_search_active else (28, 32, 42)
            search_border = (186, 198, 220) if self.template_picker_search_active else (102, 110, 126)
            pygame.draw.rect(screen, search_fill, self.template_picker_search_rect)
            pygame.draw.rect(screen, search_border, self.template_picker_search_rect, 1)
            search_text = self.template_picker_search_query if self.template_picker_search_query else "Search templates or classes"
            search_color = (238, 238, 238) if self.template_picker_search_query else (150, 158, 174)
            search_surface = font.render(search_text, True, search_color)
            screen.blit(search_surface, (self.template_picker_search_rect.x + 8, self.template_picker_search_rect.y + 4))

        for template, label, button_rect in self.template_quick_button_hitboxes:
            hovered = button_rect.collidepoint(pygame.mouse.get_pos())
            fill = (66, 82, 112) if hovered else (48, 58, 78)
            pygame.draw.rect(screen, fill, button_rect)
            pygame.draw.rect(screen, (176, 190, 216), button_rect, 1)
            quick_label = font.render(label, True, (244, 246, 250))
            screen.blit(quick_label, quick_label.get_rect(center=button_rect.center))

        for row in self.template_picker_visible_rows:
            row_rect = row.get("rect")
            if row_rect is None:
                continue

            label = row.get("label", "")
            if row.get("kind") == "header":
                header_rect = pygame.Rect(row_rect.x, row_rect.y + 3, row_rect.width, max(20, row_rect.height - 10))
                pygame.draw.rect(screen, (31, 36, 48), header_rect)
                header_label = font.render(str(label), True, (188, 202, 226))
                screen.blit(header_label, (header_rect.x + 8, header_rect.y + 3))
                continue

            for item in row.get("items", []):
                item_rect = item.get("rect")
                if item_rect is None:
                    continue
                hovered = item_rect.collidepoint(pygame.mouse.get_pos())
                fill = (52, 60, 78) if hovered else (44, 50, 64)
                pygame.draw.rect(screen, fill, item_rect)
                pygame.draw.rect(screen, (132, 142, 160), item_rect, 1)

                item_label = self._ellipsize_text(str(item.get("label", "Template")), font, item_rect.width - 14)
                label_surface = font.render(item_label, True, (242, 242, 242))
                screen.blit(label_surface, (item_rect.x + 7, item_rect.y + max(3, (item_rect.height - label_surface.get_height()) // 2)))

        quick_count = len(self.template_quick_button_hitboxes)
        list_count = self.template_picker_total_rows
        if list_count > len(self.template_picker_visible_rows):
            visible_count = max(1, len(self.template_picker_visible_rows))
            scroll_label = (
                f"{self.template_picker_scroll + 1}-"
                f"{self.template_picker_scroll + visible_count} / "
                f"{list_count}"
            )
            scroll_surface = font.render(scroll_label, True, (166, 174, 190))
            screen.blit(
                scroll_surface,
                (
                    self.template_picker_rect.right - scroll_surface.get_width() - 10,
                    title_y,
                ),
            )

        status = str(self.template_picker_status or "").strip()
        if status and not pending_name and self.template_picker_mode != "convert":
            status_surface = font.render(status, True, (230, 154, 132))
            screen.blit(
                status_surface,
                (
                    self.template_picker_rect.x + 12,
                    self.template_picker_rect.bottom - status_surface.get_height() - 8,
                ),
            )

    def _draw_entry_name_prompt(self, screen, font):
        prompt = self.entry_name_prompt
        if not isinstance(prompt, dict) or self.layout is None:
            return

        right_rect = self.layout["right_rect"]
        prompt_w = min(420, max(300, right_rect.width - 48))
        prompt_h = 148
        prompt_x = right_rect.right - prompt_w - 12
        prompt_y = right_rect.y + 44
        prompt_rect = pygame.Rect(prompt_x, prompt_y, prompt_w, prompt_h)
        header_rect = pygame.Rect(prompt_rect.x, prompt_rect.y, prompt_rect.width, 48)
        input_rect = pygame.Rect(prompt_rect.x + 18, prompt_rect.y + 72, prompt_rect.width - 36, 30)
        cancel_rect = pygame.Rect(prompt_rect.right - 198, prompt_rect.bottom - 42, 86, 28)
        create_rect = pygame.Rect(prompt_rect.right - 104, prompt_rect.bottom - 42, 86, 28)

        prompt["rect"] = prompt_rect
        prompt["input_rect"] = input_rect
        prompt["cancel_rect"] = cancel_rect
        prompt["create_rect"] = create_rect

        pygame.draw.rect(screen, (28, 30, 38), prompt_rect)
        pygame.draw.rect(screen, (170, 170, 170), prompt_rect, 1)
        pygame.draw.rect(screen, (34, 38, 48), header_rect)
        pygame.draw.line(
            screen,
            (110, 110, 120),
            (header_rect.x, header_rect.bottom),
            (header_rect.right, header_rect.bottom),
            1,
        )

        if prompt.get("mode") == "idea_from_parent":
            prompt_title = "Name New Idea"
        elif prompt.get("mode") == "toolbelt":
            prompt_title = f"Name New {prompt.get('label') or 'Entry'}"
        else:
            prompt_title = "Name New Entry"
        title = font.render(prompt_title, True, (244, 244, 244))
        detail = font.render(str(prompt.get("label") or "Entry"), True, (166, 176, 194))
        screen.blit(title, (prompt_rect.x + 12, prompt_rect.y + 8))
        screen.blit(detail, (prompt_rect.x + 12, prompt_rect.y + 28))

        name_label = font.render("name", True, (188, 196, 212))
        screen.blit(name_label, (input_rect.x, input_rect.y - 18))

        pygame.draw.rect(screen, (38, 43, 56), input_rect)
        pygame.draw.rect(screen, (182, 202, 236), input_rect, 1)
        buffer_text = str(prompt.get("buffer", ""))
        cursor = max(0, min(int(prompt.get("cursor", len(buffer_text))), len(buffer_text)))
        visible_text = buffer_text
        max_input_text_w = input_rect.width - 18
        while visible_text and font.size(visible_text)[0] > max_input_text_w:
            visible_text = visible_text[1:]

        hidden_prefix_len = len(buffer_text) - len(visible_text)
        display_text = visible_text if buffer_text else "Entry name"
        text_color = (238, 238, 238) if buffer_text else (126, 136, 154)
        text_surface = font.render(display_text, True, text_color)
        screen.blit(text_surface, (input_rect.x + 8, input_rect.y + 6))

        visible_cursor = max(0, cursor - hidden_prefix_len)
        cursor_x = input_rect.x + 8 + font.size(visible_text[:visible_cursor])[0]
        pygame.draw.line(
            screen,
            (236, 236, 236),
            (cursor_x, input_rect.y + 6),
            (cursor_x, input_rect.bottom - 6),
            1,
        )

        status = str(prompt.get("status") or "")
        if status:
            status_surface = font.render(status, True, (230, 154, 132))
            screen.blit(status_surface, (prompt_rect.x + 18, input_rect.bottom + 8))

        mouse_pos = pygame.mouse.get_pos()
        for rect, label, primary in (
            (cancel_rect, "Cancel", False),
            (create_rect, "Create", True),
        ):
            hovered = rect.collidepoint(mouse_pos)
            fill = (72, 92, 132) if primary else (42, 48, 62)
            if hovered:
                fill = (88, 108, 150) if primary else (56, 64, 82)
            pygame.draw.rect(screen, fill, rect)
            pygame.draw.rect(screen, (164, 176, 198), rect, 1)
            label_surface = font.render(label, True, (244, 244, 244))
            screen.blit(label_surface, label_surface.get_rect(center=rect.center))

    def draw(self, screen, font, draw_button_fn):
        if self.layout is None:
            return

        header_rect = self.layout["header_rect"]
        timeline_rect = self.layout["timeline_rect"]
        timeline_splitter_rect = self.layout["timeline_splitter_rect"]
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

        self.timeline_ui.set_rect(timeline_rect)
        self.timeline_ui.set_font(font)
        self.timeline_ui.draw(screen, font)

        pygame.draw.rect(screen, (28, 32, 46), timeline_splitter_rect)
        pygame.draw.line(
            screen,
            (118, 126, 150),
            (timeline_splitter_rect.x, timeline_splitter_rect.centery),
            (timeline_splitter_rect.right, timeline_splitter_rect.centery),
            1,
        )

        grip_half_w = 26
        grip_center_x = timeline_splitter_rect.centerx
        for offset in (-3, 0, 3):
            pygame.draw.line(
                screen,
                (170, 176, 196),
                (grip_center_x - grip_half_w, timeline_splitter_rect.centery + offset),
                (grip_center_x + grip_half_w, timeline_splitter_rect.centery + offset),
                1,
            )

        pygame.draw.rect(screen, (12, 12, 20), left_rect)
        pygame.draw.rect(screen, (200, 200, 200), left_rect, 1)

        pygame.draw.rect(screen, (12, 16, 28), right_rect)
        pygame.draw.rect(screen, (200, 200, 200), right_rect, 1)

        left_title = font.render("Repository Browser", True, (240, 240, 240))
        right_title = font.render("Card Canvas", True, (240, 240, 240))
        screen.blit(left_title, (left_rect.x + 12, left_rect.y + 10))
        screen.blit(right_title, (right_rect.x + 12, right_rect.y + 10))
        if self.relation_link_target is not None:
            target_label = self._relation_target_label(self.relation_link_target.get("target"))
            field_label = self.relation_link_target.get("field_key") or "relation"
            banner_rect = pygame.Rect(left_rect.x + 10, left_rect.y + 32, left_rect.width - 20, 22)
            pygame.draw.rect(screen, (26, 44, 62), banner_rect)
            pygame.draw.rect(screen, (112, 166, 224), banner_rect, 1)
            status_text = self.relation_link_status or f"Choose an existing {target_label}"
            link_surface = font.render(
                f"Link {field_label}: {status_text}",
                True,
                (166, 204, 236),
            )
            max_text_w = banner_rect.width - 12
            if link_surface.get_width() > max_text_w:
                label = f"Link {field_label}: {target_label}"
                link_surface = font.render(label, True, (166, 204, 236))
            screen.blit(link_surface, (banner_rect.x + 6, banner_rect.y + 3))
        zoom_label = font.render(f"{int(self.canvas_zoom * 100)}%", True, (170, 180, 200))
        screen.blit(zoom_label, (right_rect.x + 118, right_rect.y + 10))
        if self.canvas_relation_link_source_id is not None:
            status_text = self.canvas_relation_status or "Click a second card to relate entries"
            status_surface = font.render(status_text, True, (230, 210, 150))
            max_status_w = max(40, right_rect.width - 260)
            if status_surface.get_width() > max_status_w:
                status_surface = font.render("Click a second card to relate entries", True, (230, 210, 150))
            screen.blit(status_surface, (right_rect.x + 170, right_rect.y + 10))

        if self.browser_search_rect is not None:
            search_fill = (38, 44, 58) if self.browser_search_active else (28, 32, 42)
            search_border = (186, 198, 220) if self.browser_search_active else (102, 110, 126)
            pygame.draw.rect(screen, search_fill, self.browser_search_rect)
            pygame.draw.rect(screen, search_border, self.browser_search_rect, 1)
            search_text = self.browser_search_query if self.browser_search_query else "Search by name, id, or type"
            search_color = (238, 238, 238) if self.browser_search_query else (150, 158, 174)
            search_surface = font.render(search_text, True, search_color)
            screen.blit(search_surface, (self.browser_search_rect.x + 8, self.browser_search_rect.y + 4))

        for filter_kind, filter_value, chip_rect in self.browser_filter_hitboxes:
            if filter_kind == "dataset":
                label = self._format_browser_filter_label(filter_value)
                selected = filter_value == self.browser_filter_dataset
            else:
                label = "Incomplete"
                selected = self.browser_filter_incomplete_only
            fill = (62, 82, 120) if selected else (32, 36, 48)
            border = (210, 220, 240) if selected else (100, 108, 124)
            text_color = (245, 245, 245) if selected else (194, 202, 216)
            pygame.draw.rect(screen, fill, chip_rect)
            pygame.draw.rect(screen, border, chip_rect, 1)
            chip_text = font.render(label, True, text_color)
            chip_text_rect = chip_text.get_rect(center=chip_rect.center)
            screen.blit(chip_text, chip_text_rect)

        if self.random_entry_button is not None:
            draw_button_fn(screen, font, self.random_entry_button)
        if self.random_unfinished_button is not None:
            draw_button_fn(screen, font, self.random_unfinished_button)
        if self.random_task_button is not None:
            draw_button_fn(screen, font, self.random_task_button)
        if self.new_entry_button is not None:
            draw_button_fn(screen, font, self.new_entry_button)
        if self.relation_touch_decrease_button is not None:
            draw_button_fn(screen, font, self.relation_touch_decrease_button)
        if self.relation_touch_value_button is not None:
            draw_button_fn(screen, font, self.relation_touch_value_button)
        if self.relation_touch_increase_button is not None:
            draw_button_fn(screen, font, self.relation_touch_increase_button)

        content_top = (
            self.browser_search_rect.bottom
            + self.BROWSER_CONTROL_GAP
            + self.BROWSER_FILTER_H
            + 8
        ) if self.browser_search_rect is not None else left_rect.y + 48
        content_bottom = left_rect.bottom - 10

        row_hitboxes = {entity_id: rect for entity_id, rect in self.browser_hitboxes}
        toggle_hitboxes = {entity_id: rect for entity_id, rect in self.browser_toggle_hitboxes}

        line_height = self._font_line_height(font)
        text_offset_y = max(0, (line_height - font.get_linesize()) // 2)
        line_y = content_top - self.browser_scroll

        for item in self.browser_items:
            row_top = line_y
            row_bottom = line_y + line_height

            if item["kind"] == "spacer":
                line_y += line_height
                continue

            if row_bottom < content_top:
                line_y += line_height
                continue

            if row_top > content_bottom:
                break

            if item["kind"] == "section":
                color = (235, 235, 235)
                text_surface = font.render(item["text"], True, color)
                screen.blit(text_surface, (left_rect.x + 12, line_y + text_offset_y))

            elif item["kind"] == "label":
                color = (220, 220, 220)
                text_surface = font.render(item["text"], True, color)
                screen.blit(text_surface, (left_rect.x + 12, line_y + text_offset_y))

            else:
                entity_id = item["entity_id"]
                row_rect = row_hitboxes.get(entity_id)
                is_selected = entity_id == self.selected_entity_id
                relation_linking = self.relation_link_target is not None
                relation_pickable = item.get("kind") in {"entity", "tree_entity"}
                relation_match = self._browser_item_matches_relation_target(item) if relation_linking else False
                if relation_linking and not relation_match:
                    color = (128, 136, 150)
                else:
                    color = (245, 245, 245) if is_selected or relation_match else (220, 220, 220)

                if row_rect is not None:
                    if relation_linking:
                        if relation_match:
                            pygame.draw.rect(screen, (30, 52, 54), row_rect)
                            pygame.draw.rect(screen, (116, 188, 178), row_rect, 1)
                        elif relation_pickable:
                            pygame.draw.rect(screen, (22, 24, 32), row_rect)
                            pygame.draw.rect(screen, (58, 62, 76), row_rect, 1)
                    elif item.get("is_incomplete", False):
                        pygame.draw.rect(screen, (58, 46, 38), row_rect)
                        pygame.draw.rect(screen, (166, 126, 88), row_rect, 1)
                    if is_selected and not relation_linking:
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
                    screen.blit(text_surface, (text_x, line_y + text_offset_y))

                    meta_text = item.get("meta_text")
                    if meta_text:
                        meta_surface = font.render(meta_text, True, (170, 170, 170))
                        screen.blit(meta_surface, (text_x + text_surface.get_width() + 8, line_y + text_offset_y))
                    missing_count = item.get("missing_count", 0)
                    if missing_count:
                        missing_surface = font.render(f"missing:{missing_count}", True, (220, 182, 132))
                        screen.blit(missing_surface, (left_rect.right - missing_surface.get_width() - 14, line_y + text_offset_y))
                else:
                    text_surface = font.render(item["text"], True, color)
                    screen.blit(text_surface, (left_rect.x + 12, line_y + text_offset_y))
                    missing_count = item.get("missing_count", 0)
                    if missing_count:
                        missing_surface = font.render(f"missing:{missing_count}", True, (220, 182, 132))
                        screen.blit(missing_surface, (left_rect.right - missing_surface.get_width() - 14, line_y + text_offset_y))

            line_y += line_height

        self._draw_card_canvas(screen, font, right_rect)
        self._draw_template_picker(screen, font)
        self._draw_entry_name_prompt(screen, font)

    def handle_event(self, event):
        if self.layout is None:
            return None

        timeline_rect = self.layout["timeline_rect"]
        timeline_splitter_rect = self.layout["timeline_splitter_rect"]
        left_rect = self.layout["left_rect"]
        right_rect = self.layout["right_rect"]

        if event.type == pygame.KEYDOWN:
            return self._handle_keydown_event(event)

        if self.entry_name_prompt is not None:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._handle_entry_name_prompt_click(event.pos):
                    return "__ui_consumed__"
            if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                return "__ui_consumed__"

        if event.type == pygame.MOUSEWHEEL:
            return self._handle_mousewheel_event(event, timeline_rect, left_rect, right_rect)

        if event.type == pygame.MOUSEBUTTONUP:
            return self._handle_mousebuttonup_event(event)

        if event.type == pygame.MOUSEMOTION:
            return self._handle_mousemotion_event(event)

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        mouse_pos = event.pos

        if self.canvas_relation_link_source_id is not None and right_rect.collidepoint(mouse_pos):
            return self._handle_canvas_relation_target_click(mouse_pos)

        if self.relation_link_target is not None:
            if right_rect.collidepoint(mouse_pos):
                return self._handle_relation_card_link_target_click(mouse_pos)
            if not left_rect.collidepoint(mouse_pos):
                self._finish_relation_browser_link()
                return "__ui_consumed__"

        if timeline_rect.collidepoint(mouse_pos):
            timeline_action = self.timeline_ui.handle_click(mouse_pos)
            if timeline_action is not None:
                return "__ui_consumed__"

            if self.timeline_edit_target is not None:
                picked_year = self.timeline_ui.pick_year_from_pos(mouse_pos)
                if picked_year is not None:
                    self._apply_timeline_year_pick(picked_year)
                    return "__ui_consumed__"

            self.active_timeline_pan = True
            self.timeline_pan_last_mouse_x = mouse_pos[0]
            return "__ui_consumed__"

        if self.header_button is not None and self.header_button.rect.collidepoint(mouse_pos):
            return self.header_button.id

        if self.random_entry_button is not None and self.random_entry_button.rect.collidepoint(mouse_pos):
            self._create_random_entry_card()
            return "__ui_consumed__"

        if self.random_unfinished_button is not None and self.random_unfinished_button.rect.collidepoint(mouse_pos):
            self._create_random_unfinished_entry_card()
            return "__ui_consumed__"

        if self.random_task_button is not None and self.random_task_button.rect.collidepoint(mouse_pos):
            self._create_random_task_card()
            return "__ui_consumed__"

        if self.new_entry_button is not None and self.new_entry_button.rect.collidepoint(mouse_pos):
            self._open_new_entry_name_prompt()
            return "__ui_consumed__"

        if (
            self.relation_touch_decrease_button is not None
            and self.relation_touch_decrease_button.rect.collidepoint(mouse_pos)
        ):
            self._set_relation_tree_touch_degree(self.relation_tree_touch_degree - 1)
            return "__ui_consumed__"

        if (
            self.relation_touch_increase_button is not None
            and self.relation_touch_increase_button.rect.collidepoint(mouse_pos)
        ):
            self._set_relation_tree_touch_degree(self.relation_tree_touch_degree + 1)
            return "__ui_consumed__"

        if (
            self.relation_touch_value_button is not None
            and self.relation_touch_value_button.rect.collidepoint(mouse_pos)
        ):
            return "__ui_consumed__"

        template_picker_result = self._handle_template_picker_click(mouse_pos)
        if template_picker_result is not None:
            return template_picker_result

        if timeline_splitter_rect.collidepoint(mouse_pos):
            self.active_timeline_resize = True
            self.timeline_resize_start_mouse_y = mouse_pos[1]
            self.timeline_resize_start_height = self.timeline_panel_height
            return "__ui_consumed__"

        left_result = self._handle_left_panel_click(mouse_pos, left_rect)
        if left_result is not None:
            return left_result

        return self._handle_card_canvas_click(mouse_pos, right_rect)
