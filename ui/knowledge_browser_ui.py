import json
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
        self.new_entry_button = None
        self.template_picker_rect = None
        self.template_button_hitboxes = []
        self.show_template_picker = False
        self.template_picker_scroll = 0
        self.schema_entry_templates = self._load_schema_entry_templates()
        self.browser_scroll = 0
        self.browser_search_query = ""
        self.browser_search_active = False
        self.browser_filter_dataset = "all"
        self.browser_filter_incomplete_only = False

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
        self.card_drag_mouse_offset = (0, 0)
        self.card_resize_start_mouse = None
        self.card_resize_start_size = None
        self.card_resize_start_position = None
        self.card_resize_edges = None

        self.browser_tree_state = {
            "systems": {
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
        self.new_entry_button = None
        self.template_picker_rect = None
        self.template_button_hitboxes = []

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

            pretty_name = entity.get("pretty_name") or entity.get("name") or entity_id
            haystack = " ".join([str(pretty_name), str(entity_id), str(entity.get("name", ""))]).lower()
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

    def _close_relation_picker(self, card):
        card["relation_picker_open"] = False
        card["relation_picker_query"] = ""
        card["relation_picker_matches"] = []
        card["relation_picker_selected_index"] = 0
        card["relation_picker_hitboxes"] = []

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
            self.new_entry_button = None
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
        self.random_entry_button = UIButton(
            button_id="knowledge_random_entry",
            label="Random Entry",
            rect=pygame.Rect(right_rect.right - 232, button_y, 104, 28),
            visible=True,
            enabled=True,
        )
        self.new_entry_button = UIButton(
            button_id="knowledge_new_entry",
            label="New Entry",
            rect=pygame.Rect(right_rect.right - 118, button_y, 96, 28),
            visible=True,
            enabled=True,
        )
        self._build_template_picker_hitboxes()

    def _font_line_height(self, font=None):
        font = font or self.font_for_layout
        if font is None:
            return self.LINE_HEIGHT
        return max(self.LINE_HEIGHT, int(font.get_linesize()) + 4)

    def _template_picker_row_height(self):
        line_h = self._font_line_height()
        return max(self.TEMPLATE_PICKER_ROW_H, line_h * 2 + 8)

    def _template_picker_header_height(self):
        return max(42, self._font_line_height() + 22)

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
            "species": "sp",
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

        templates.sort(key=lambda item: (item["label"].lower(), item["dataset_name"]))
        return templates

    def _template_by_dataset(self, dataset_name):
        for template in self.schema_entry_templates:
            if template.get("dataset_name") == dataset_name:
                return template
        return None

    def _build_template_picker_hitboxes(self):
        self.template_button_hitboxes = []
        self.template_picker_rect = None

        if self.layout is None or not self.show_template_picker:
            return

        right_rect = self.layout["right_rect"]
        picker_w = min(360, right_rect.width - 24)
        template_count = len(self.schema_entry_templates)
        max_picker_h = max(96, right_rect.height - 70)
        header_h = self._template_picker_header_height()
        row_h = self._template_picker_row_height()
        picker_h = min(max_picker_h, header_h + template_count * row_h + 8)
        picker_x = right_rect.right - picker_w - 12
        picker_y = right_rect.y + 44
        self.template_picker_rect = pygame.Rect(picker_x, picker_y, picker_w, picker_h)

        visible_rows = max(1, (picker_h - header_h - 8) // row_h)
        max_scroll = max(0, template_count - visible_rows)
        self.template_picker_scroll = max(0, min(max_scroll, self.template_picker_scroll))

        button_y = picker_y + header_h
        visible_templates = self.schema_entry_templates[
            self.template_picker_scroll:self.template_picker_scroll + visible_rows
        ]
        for template in visible_templates:
            button_rect = pygame.Rect(picker_x + 12, button_y, picker_w - 24, row_h - 6)
            self.template_button_hitboxes.append((template, template["label"], button_rect))
            button_y += row_h

    def _is_expanded(self, entity_id):
        return self.browser_tree_state["systems"].get(entity_id, False)

    def _set_expanded(self, entity_id, expanded):
        self.browser_tree_state["systems"][entity_id] = expanded

    def _browser_dataset_filters(self):
        if self.world_model is None:
            return ["all"]
        preferred = ["all", "locations", "systems", "vehicles", "components", "events"]
        names = ["all"] + sorted(name for name in self.world_model.get_dataset_names() if name != "all")
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
                    str(entity.get("pretty_name", "")),
                    str(entity.get("name", "")),
                    str(entity.get("id", "")),
                    str(entity.get("type", "")),
                ]
            ).lower()
            if query not in haystack:
                return False

        return True

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
        missing = 0
        for field_key, spec in field_specs.items():
            field_type = spec.get("type")
            if field_type not in {None, "string", "number", "text"}:
                continue
            value = entity.get(field_key)
            if value is None:
                missing += 1
            elif isinstance(value, str) and not value.strip():
                missing += 1
        return missing

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
            if not self._matches_browser_filters(body_entity, "systems"):
                if not any(self._matches_browser_filters(child, "systems") for child in children):
                    return

            items.append(
                {
                    "kind": "tree_entity",
                    "entity_id": body_id,
                    "text": body_name,
                    "meta_text": f"[{body_class}]",
                    "missing_count": self._entity_missing_scalar_count(body_entity, "systems"),
                    "is_incomplete": self._entity_missing_scalar_count(body_entity, "systems") > 0,
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
            if not self._matches_browser_filters(system_entity, "systems"):
                if not any(self._matches_browser_filters(body, "systems") for body in root_bodies):
                    continue

            items.append(
                {
                    "kind": "tree_entity",
                    "entity_id": system_id,
                    "text": system_name,
                    "meta_text": f"[{system_class}]",
                    "missing_count": self._entity_missing_scalar_count(system_entity, "systems"),
                    "is_incomplete": self._entity_missing_scalar_count(system_entity, "systems") > 0,
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
        if dataset_name == "ideas":
            return entity.get("idea_class", entity.get("type", "entity"))
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
            "ideas",
            "locations",
            "vehicles",
            "components",
            "systems",
        ]
        ordered_names = [name for name in preferred_order if name in dataset_names]
        ordered_names += [name for name in dataset_names if name not in ordered_names]

        for dataset_name in ordered_names:
            if self.browser_filter_dataset != "all" and dataset_name != self.browser_filter_dataset:
                continue

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
                if not self._matches_browser_filters(entity, dataset_name):
                    continue

                label = entity.get("name", entity.get("id", "unknown"))
                entity_class = self._entity_class_label(dataset_name, entity)
                missing_count = self._entity_missing_scalar_count(entity, dataset_name)

                items.append(
                    {
                        "kind": "entity",
                        "entity_id": entity.get("id"),
                        "text": f"  {label} [{entity_class}]",
                        "missing_count": missing_count,
                        "is_incomplete": missing_count > 0,
                    }
                )

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
            subtype = entity.get("idea_class", entity.get("type", "entity"))
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

        start_year = entity.get("start_year")
        end_year = entity.get("end_year")

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

        if start_year is not None and end_year is not None and end_year >= start_year and end_year != start_year:
            years = [start_year, end_year]
        elif start_year is not None:
            years = [start_year]
        elif end_year is not None:
            years = [end_year]
        else:
            years = [0]

        selected_year = years[0]

        card_index = len(self.cards)
        spawn_x = 24 + (card_index % 3) * 40
        spawn_y = 84 + (card_index % 5) * 32

        card = {
            "entity_id": entity.get("id"),
            "title": entity.get("name", entity.get("id", "unknown")),
            "subtitle": f"{display_group} | {subtype}",
            "years": years,
            "selected_year": selected_year,
            "canvas_x": spawn_x,
            "canvas_y": spawn_y,
            "canvas_w": 420,
            "canvas_h": 340,
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
            "draft_edit_buffers": {},
            "is_draft_entity": False,
            "last_edit_action": None,
        }
        self._apply_cached_draft_to_card(card)
        return card


    def _layout_all_cards(self):
        if self.layout is None:
            return

        right_rect = self.layout["right_rect"]

        max_right = 0
        max_bottom = 0

        for card in self.cards:
            card_w = max(300, min(900, int(card.get("canvas_w", 420))))

            card_view = card.get("card_view")
            requested_h = int(card.get("canvas_h", 340))

            if card_view is not None and self.font_for_layout is not None:
                minimum_h = card_view.get_minimum_height(card, self.font_for_layout)
            else:
                minimum_h = 260

            card_h = max(minimum_h, min(1200, requested_h))
            card["canvas_h"] = card_h
            card["layout_font"] = self.font_for_layout

            rect_x = right_rect.x + self.canvas_offset_x + int(card.get("canvas_x", 24) * self.canvas_zoom)
            rect_y = right_rect.y + self.canvas_offset_y + int(card.get("canvas_y", 84) * self.canvas_zoom)

            rect = pygame.Rect(rect_x, rect_y, card_w, card_h)

            if card_view is not None:
                card_view.layout_card(card, rect)

            final_rect = card.get("rect", rect)

            max_right = max(max_right, card.get("canvas_x", 24) + final_rect.width / self.canvas_zoom)
            max_bottom = max(max_bottom, card.get("canvas_y", 84) + final_rect.height / self.canvas_zoom)

        self.canvas_content_width = max(0, max_right + 24)
        self.canvas_content_height = max(0, max_bottom + 24)

    def _clamp_canvas_offsets(self):
        # The card canvas is intentionally unbounded. Offsets are allowed to
        # move freely so cards dragged into negative space remain recoverable by panning.
        return

    def _relayout_cards(self):
        self._layout_all_cards()

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

    def _bring_card_to_front(self, index):
        card_obj = self.cards.pop(index)
        self.cards.append(card_obj)
        self.selected_entity_id = card_obj.get("entity_id")
        return card_obj

    def _begin_card_resize(self, card_obj, mouse_pos, resize_edges):
        self.active_card_resize_id = card_obj["entity_id"]
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

    def _create_template_entity(self, template):
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
        entity_id = self._next_template_entity_id(dataset_name, template=template)
        label = f"New {entity_type.replace('_', ' ').title()}"

        entity = {
            "id": entity_id,
            "pretty_name": label,
            "name": label,
            "type": entity_type,
            "_dataset": dataset_name,
            "wiki_entry": "",
        }
        self._populate_required_schema_fields(entity, template)

        self.world_model.loader.datasets.setdefault(dataset_name, []).append(entity)
        self.world_model.loader.entities[entity_id] = entity
        return entity

    def _create_new_entry_from_template(self, template):
        entity = self._create_template_entity(template)
        if entity is None:
            return False

        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        self.show_template_picker = False
        self._build_template_picker_hitboxes()
        card = self._ensure_card(entity)
        if card is not None:
            card["is_draft_entity"] = True
            self._save_card_draft(card)
        return True

    def _create_idea_from_parent_card(self, parent_card):
        if self.world_model is None or parent_card is None:
            return False

        parent_entity_id = parent_card.get("entity_id")
        if not parent_entity_id:
            return False

        parent_entity = self.world_model.get_entity(parent_entity_id)
        parent_label = parent_card.get("title") or parent_entity_id
        if parent_entity is not None:
            parent_label = parent_entity.get("pretty_name") or parent_entity.get("name") or parent_label

        idea = self._create_template_entity("ideas")
        if idea is None:
            return False

        label = f"Idea from {parent_label}"
        idea["pretty_name"] = label
        idea["name"] = label
        idea["idea_class"] = "note"
        idea["parent_entity"] = parent_entity_id
        idea["related_entities"] = [parent_entity_id]

        if parent_entity is not None and parent_entity.get("_dataset") == "ideas":
            idea["parent_ideas"] = [parent_entity_id]

        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        card = self._ensure_card(idea)
        if card is not None:
            card["is_draft_entity"] = True
            self._save_card_draft(card)
        return True

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

        if start_year is not None and end_year is not None and end_year >= start_year and end_year != start_year:
            years = [start_year, end_year]
        elif start_year is not None:
            years = [start_year]
        elif end_year is not None:
            years = [end_year]
        elif point_year is not None:
            years = [point_year]
        else:
            years = [0]

        card["years"] = years
        if card.get("selected_year") not in years:
            card["selected_year"] = years[0]

    def _set_timeline_edit_target(self, card_obj, field_key):
        preview_year = None
        card_view = card_obj.get("card_view")
        if card_view is not None and getattr(card_view, "entity", None) is not None:
            preview_year = self._coerce_card_year(card_view.entity.get(field_key))

        self.timeline_edit_target = {
            "entity_id": card_obj.get("entity_id"),
            "field_key": field_key,
        }
        self.timeline_ui.set_picker_target(field_key, preview_year=preview_year)

    def _clear_timeline_edit_target(self):
        self.timeline_edit_target = None
        self.timeline_ui.clear_picker_target()

    def _apply_timeline_year_pick(self, year):
        if self.timeline_edit_target is None:
            return False

        entity_id = self.timeline_edit_target.get("entity_id")
        field_key = self.timeline_edit_target.get("field_key")
        if entity_id is None or field_key is None:
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

            card_view.begin_edit_field(card_obj, field_key)
            card_obj["edit_buffer"] = str(int(year))
            card_view.commit_edit_field(card_obj)
            self._persist_card_entity(card_obj)
            self._sync_card_years_from_entity(card_obj)
            self._focus_timeline_year(year)
            self._clear_timeline_edit_target()
            self._refresh_timeline_items()
            self._relayout_cards()
            return True

        self._clear_timeline_edit_target()
        return False

    def _ensure_card(self, entity):
        if entity is None:
            return None

        entity_id = entity.get("id")
        if entity_id is None:
            return None

        for index, card in enumerate(self.cards):
            if card.get("entity_id") == entity_id:
                self.selected_entity_id = entity_id
                card_obj = self._bring_card_to_front(index)
                self._layout_all_cards()
                return card_obj

        new_card = self._build_card_from_entity(entity)
        if new_card is not None:
            self.cards.append(new_card)
            self.selected_entity_id = entity_id
            self._relayout_cards()
            return new_card
        return None

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

    def _save_card_draft(self, card):
        entity = self._entity_for_card(card)
        if not isinstance(entity, dict) or not entity.get("id"):
            return False

        entity_id = str(entity["id"])
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

    def _format_yaml_entity_block(self, entity):
        ordered_keys = ["id", "pretty_name", "name", "type"]
        keys = [key for key in ordered_keys if key in entity]
        keys.extend(key for key in entity.keys() if key not in keys and not key.startswith("_"))

        lines = []
        for index, key in enumerate(keys):
            value = entity.get(key)
            prefix = "- " if index == 0 else "  "

            if isinstance(value, list):
                lines.append(f"{prefix}{key}:")
                if value:
                    for item in value:
                        lines.append(f"  - {self._format_yaml_scalar(item)}")
                else:
                    lines[-1] = f"{prefix}{key}: []"
                continue

            if isinstance(value, dict):
                lines.append(f"{prefix}{key}:")
                if value:
                    for child_key, child_value in value.items():
                        lines.append(f"    {child_key}: {self._format_yaml_scalar(child_value)}")
                else:
                    lines[-1] = f"{prefix}{key}: {{}}"
                continue

            scalar = self._format_yaml_scalar(value)
            if scalar.startswith("|\n"):
                lines.append(f"{prefix}{key}: {scalar}")
            else:
                lines.append(f"{prefix}{key}: {scalar}")

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

    def _persist_entity_to_repository(self, entity):
        if not isinstance(entity, dict):
            return False

        entity_id = entity.get("id")
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
        found = self._find_yaml_entity_block(text, entity_id)
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

        entity = self._entity_for_card(card)
        persisted = self._persist_entity_to_repository(entity)
        if persisted and isinstance(entity, dict):
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
        search_y = left_rect.y + 38
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

            if item["kind"] in ("entity", "tree_entity"):
                row_rect = pygame.Rect(left_rect.x + 10, line_y - 1, left_rect.width - 20, line_height)
                self.browser_hitboxes.append((item["entity_id"], row_rect))

                if item["kind"] == "tree_entity" and item.get("expandable", False):
                    depth = item.get("depth", 0)
                    indent_px = depth * 18
                    base_x = left_rect.x + 12 + indent_px
                    caret_rect = pygame.Rect(base_x, line_y + max(2, (line_height - 14) // 2), 14, 14)
                    self.browser_toggle_hitboxes.append((item["entity_id"], caret_rect))

            line_y += line_height

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
        card_rect = card.get("rect")
        if card_rect is not None:
            screen.set_clip(previous_clip.clip(card_rect))
        try:
            card_view.draw_card(screen, font, card)
        finally:
            screen.set_clip(previous_clip)

    def _handle_keydown_event(self, event):
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

            if card.get("is_edit_mode", False):
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
            self.template_picker_scroll = max(0, self.template_picker_scroll - event.y)
            self._build_template_picker_hitboxes()
            return "__ui_consumed__"

        if right_rect.collidepoint(mouse_pos):
            key_mods = pygame.key.get_mods()
            if key_mods & pygame.KMOD_CTRL:
                zoom_factor = 1.12 if event.y > 0 else 1 / 1.12
                self._set_canvas_zoom_at(mouse_pos, zoom_factor)
                return "__ui_consumed__"

            canvas_step = 64
            if key_mods & pygame.KMOD_SHIFT:
                self.canvas_offset_x += event.y * canvas_step
            else:
                self.canvas_offset_y += event.y * canvas_step
            self._layout_all_cards()
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
        self.active_card_drag_id = None
        self.active_card_resize_id = None
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
                    dx = event.pos[0] - self.card_resize_start_mouse[0]
                    dy = event.pos[1] - self.card_resize_start_mouse[1]
                    minimum_h = (
                        card.get("card_view").get_minimum_height(card, self.font_for_layout)
                        if card.get("card_view")
                        else 260
                    )
                    min_w = 300
                    start_x, start_y = self.card_resize_start_position
                    start_w, start_h = self.card_resize_start_size
                    resize_edges = self.card_resize_edges or "bottom_right"

                    new_x = start_x
                    new_y = start_y
                    new_w = start_w
                    new_h = start_h

                    if "left" in resize_edges:
                        new_x = start_x + dx / max(0.001, self.canvas_zoom)
                        new_w = start_w - dx
                        if new_w < min_w:
                            new_x = start_x + (start_w - min_w) / max(0.001, self.canvas_zoom)
                            new_w = min_w

                    if "right" in resize_edges:
                        new_w = max(min_w, start_w + dx)

                    if "top" in resize_edges:
                        new_y = start_y + dy / max(0.001, self.canvas_zoom)
                        new_h = start_h - dy
                        if new_h < minimum_h:
                            new_y = start_y + (start_h - minimum_h) / max(0.001, self.canvas_zoom)
                            new_h = minimum_h

                    if "bottom" in resize_edges:
                        new_h = max(minimum_h, start_h + dy)

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

        for entity_id, hitbox in self.browser_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                self.selected_entity_id = entity_id

                if self.world_model is not None:
                    entity = self.world_model.get_entity(entity_id)
                    self._ensure_card(entity)

                return "__ui_consumed__"

        return None

    def _handle_card_canvas_click(self, mouse_pos, right_rect):
        if not right_rect.collidepoint(mouse_pos):
            return None

        for index in range(len(self.cards) - 1, -1, -1):
            card = self.cards[index]
            card_view = card.get("card_view")

            idea_button_rect = card.get("idea_button_rect")
            if idea_button_rect is not None and idea_button_rect.collidepoint(mouse_pos) and card_view is not None:
                card_obj = self._bring_card_to_front(index)
                self._create_idea_from_parent_card(card_obj)
                self._relayout_cards()
                return "__ui_consumed__"

            edit_toggle_rect = card.get("edit_toggle_rect")
            if edit_toggle_rect is not None and edit_toggle_rect.collidepoint(mouse_pos) and card_view is not None:
                card_obj = self._bring_card_to_front(index)
                if card_obj.get("is_edit_mode", False) and card_obj.get("active_edit_field"):
                    self._save_card_draft(card_obj)
                card_obj["card_view"].toggle_edit_mode(card_obj)
                if not card_obj.get("is_edit_mode", False):
                    self._clear_timeline_edit_target()
                    self._close_wiki_link_picker(card_obj)
                    self._close_relation_picker(card_obj)
                self._relayout_cards()
                return "__ui_consumed__"

            for match_index, match_rect in card.get("relation_picker_hitboxes", []):
                if match_rect.collidepoint(mouse_pos) and card_view is not None:
                    card_obj = self._bring_card_to_front(index)
                    self._insert_relation_from_picker(card_obj, match_index=match_index)
                    self._relayout_cards()
                    return "__ui_consumed__"

            for field_key, field_rect in card.get("editable_field_hitboxes", []):
                if field_rect.collidepoint(mouse_pos) and card_view is not None:
                    card_obj = self._bring_card_to_front(index)
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

            if card["rect"].collidepoint(mouse_pos):
                self._bring_card_to_front(index)
                self._layout_all_cards()
                return "__ui_consumed__"

        self.active_canvas_pan = True
        self.canvas_pan_start_mouse = mouse_pos
        self.canvas_pan_start_offset = (self.canvas_offset_x, self.canvas_offset_y)
        return "__ui_consumed__"

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
        zoom_label = font.render(f"{int(self.canvas_zoom * 100)}%", True, (170, 180, 200))
        screen.blit(zoom_label, (right_rect.x + 118, right_rect.y + 10))

        if self.browser_search_rect is not None:
            search_fill = (38, 44, 58) if self.browser_search_active else (28, 32, 42)
            search_border = (186, 198, 220) if self.browser_search_active else (102, 110, 126)
            pygame.draw.rect(screen, search_fill, self.browser_search_rect)
            pygame.draw.rect(screen, search_border, self.browser_search_rect, 1)
            search_text = self.browser_search_query if self.browser_search_query else "Search by pretty name, id, or type"
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
        if self.new_entry_button is not None:
            draw_button_fn(screen, font, self.new_entry_button)

        if self.show_template_picker and self.template_picker_rect is not None:
            pygame.draw.rect(screen, (24, 28, 40), self.template_picker_rect)
            pygame.draw.rect(screen, (160, 168, 186), self.template_picker_rect, 1)
            picker_title = font.render("Create New Entry From Schema", True, (236, 236, 236))
            title_y = self.template_picker_rect.y + max(6, (self._template_picker_header_height() - font.get_linesize()) // 2)
            screen.blit(picker_title, (self.template_picker_rect.x + 12, title_y))

            for template, label, button_rect in self.template_button_hitboxes:
                pygame.draw.rect(screen, (44, 50, 64), button_rect)
                pygame.draw.rect(screen, (132, 142, 160), button_rect, 1)
                detail = template.get("dataset_name", "")
                button_text = font.render(label, True, (242, 242, 242))
                detail_text = font.render(detail, True, (166, 174, 190))
                line_h = font.get_linesize()
                text_block_h = line_h * 2
                text_y = button_rect.y + max(3, (button_rect.height - text_block_h) // 2)
                screen.blit(button_text, (button_rect.x + 8, text_y))
                screen.blit(detail_text, (button_rect.x + 8, text_y + line_h))

            if len(self.schema_entry_templates) > len(self.template_button_hitboxes):
                visible_count = max(1, len(self.template_button_hitboxes))
                scroll_label = f"{self.template_picker_scroll + 1}-{self.template_picker_scroll + visible_count} / {len(self.schema_entry_templates)}"
                scroll_surface = font.render(scroll_label, True, (166, 174, 190))
                screen.blit(
                    scroll_surface,
                    (
                        self.template_picker_rect.right - scroll_surface.get_width() - 10,
                        title_y,
                    ),
                )

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
                color = (245, 245, 245) if is_selected else (220, 220, 220)

                if row_rect is not None:
                    if item.get("is_incomplete", False):
                        pygame.draw.rect(screen, (58, 46, 38), row_rect)
                        pygame.draw.rect(screen, (166, 126, 88), row_rect, 1)
                    if is_selected:
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

        previous_clip = screen.get_clip()
        screen.set_clip(right_rect.inflate(-8, -8))
        for card in self.cards:
            self._draw_card(screen, font, card)
        screen.set_clip(previous_clip)

    def handle_event(self, event):
        if self.layout is None:
            return None

        timeline_rect = self.layout["timeline_rect"]
        timeline_splitter_rect = self.layout["timeline_splitter_rect"]
        left_rect = self.layout["left_rect"]
        right_rect = self.layout["right_rect"]

        if event.type == pygame.KEYDOWN:
            return self._handle_keydown_event(event)

        if event.type == pygame.MOUSEWHEEL:
            return self._handle_mousewheel_event(event, timeline_rect, left_rect, right_rect)

        if event.type == pygame.MOUSEBUTTONUP:
            return self._handle_mousebuttonup_event(event)

        if event.type == pygame.MOUSEMOTION:
            return self._handle_mousemotion_event(event)

        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None

        mouse_pos = event.pos

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

        if self.new_entry_button is not None and self.new_entry_button.rect.collidepoint(mouse_pos):
            self.schema_entry_templates = self._load_schema_entry_templates()
            self.show_template_picker = not self.show_template_picker
            self.template_picker_scroll = 0
            self._build_template_picker_hitboxes()
            return "__ui_consumed__"

        if self.show_template_picker:
            if self.template_picker_rect is not None and self.template_picker_rect.collidepoint(mouse_pos):
                for template, _, button_rect in self.template_button_hitboxes:
                    if button_rect.collidepoint(mouse_pos):
                        self._create_new_entry_from_template(template)
                        return "__ui_consumed__"
            else:
                self.show_template_picker = False
                self._build_template_picker_hitboxes()

        if timeline_splitter_rect.collidepoint(mouse_pos):
            self.active_timeline_resize = True
            self.timeline_resize_start_mouse_y = mouse_pos[1]
            self.timeline_resize_start_height = self.timeline_panel_height
            return "__ui_consumed__"

        left_result = self._handle_left_panel_click(mouse_pos, left_rect)
        if left_result is not None:
            return left_result

        return self._handle_card_canvas_click(mouse_pos, right_rect)
