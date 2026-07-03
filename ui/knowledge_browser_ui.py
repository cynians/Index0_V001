import json
import ast
import copy
import colorsys
import os
import random
import re
import shutil
from pathlib import Path

import pygame
import tkinter as tk
from tkinter import filedialog

from ui.ui_types import UIButton
from ui.card import EntityCard
from ui.card_wiki import CardWikiRenderer
from ui.entry_name_prompt_ui import EntryNamePromptUI
from ui.knowledge_browser_model import KnowledgeBrowserModel
from ui.knowledge_canvas_controller import KnowledgeCanvasController
from ui.knowledge_link_picker import KnowledgeLinkPickerMixin
from ui.knowledge_repository_service import KnowledgeRepositoryService
from ui.knowledge_template_picker import KnowledgeTemplatePickerMixin
from ui.pixel_art_editor_ui import PixelArtEditorUI
from ui.schema_card import SchemaCard
from ui.stellar_neighbour_prompt_ui import StellarNeighbourPromptUI
from ui.timeline_ui import TimelineUI
from world.schema_loader import SchemaLoader
from world.year_utils import parse_year
from simulations.phylogeny.clade_graph import (
    clade_id_from_name,
    clade_label,
    find_clade_matches,
    phylogeny_graph_context,
    relation_ids,
)


class KnowledgeBrowserUI(KnowledgeLinkPickerMixin, KnowledgeTemplatePickerMixin):
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
        "state",
        "region",
        "city",
        "quarter",
        "site",
        "building",
        "room",
    )
    CANONICAL_VEHICLE_CLASSES = (
        "ground_vehicle",
        "aircraft",
        "naval_vessel",
        "orbital_spacecraft",
        "planetary_spacecraft",
        "system_spacecraft",
        "interstellar_spacecraft",
    )
    ORBIT_LOCATION_CLASS_KEYS = {
        "asteroid",
        "celestial_body",
        "cluster",
        "comet",
        "dwarf_planet",
        "galaxy",
        "galaxy_cluster",
        "moon",
        "orbital_body",
        "planet",
        "space_station",
        "star",
        "star_system",
        "stellar_cluster",
        "station",
        "system",
    }
    SUFFICIENT_SUBCLASS_ENTRY_COUNT = 3

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
    SETTINGS_PATH = PROJECT_ROOT / ".cache" / "knowledge_settings.json"
    ABSTRACT_SCHEMA_NAMES = {"entity_core", "entity_base", "core", "base"}
    TEMPLATE_PICKER_ROW_H = 34
    CARD_TYPE_PICKER_ROW_H = 26
    IDEA_GENERIC_FIELDS = {
        "pretty_name",
        "name",
        "idea_class",
        "wiki_entry",
        "three_word_description",
        "description",
        "date",
        "media_path",
        "card_color",
        "card_header_color",
        "wiki_field_colors",
        "tags",
        "start_year",
        "start_commentary",
        "end_year",
        "end_commentary",
        "temporal_periods",
        "parents",
        "related",
        "offspring",
        "entry_status",
    }
    LEGACY_IDEA_FIELDS = {
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
        self.browser_collapsed = False
        self.browser_collapse_handle_rect = None
        self.browser_search_rect = None
        self.browser_filter_hitboxes = []
        self.cards = []

        self.world_model = None
        self.selected_entity_id = None
        self.repository_scope_entity_id = None
        self.repository_scope_label = None
        self.header_button = None
        self.random_entry_button = None
        self.random_task_button = None
        self.new_entry_button = None
        self.clear_canvas_button = None
        self.contemporary_spawn_decrease_button = None
        self.contemporary_spawn_value_button = None
        self.contemporary_spawn_increase_button = None
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
        self.stellar_neighbourhood_prompt = None
        self.pixel_art_editor = None
        self.pixel_art_painting = False
        self.pending_new_entry_name = None
        self.schema_entry_templates = self._load_schema_entry_templates()
        self.browser_scroll = 0
        self.browser_search_query = ""
        self.browser_search_active = False
        self.browser_filter_dataset = "all"
        self.browser_filter_incomplete_only = False
        self.browser_period_filter = None
        self.browser_period_filter_clear_rect = None
        self.relation_link_target = None
        self.relation_link_status = ""
        self.canvas_relation_link_source_id = None
        self.canvas_relation_status = ""
        self.relation_tree_touch_degree = 2
        self.relation_tree_min_touch_degree = 1
        self.relation_tree_max_touch_degree = 6
        self.contemporary_spawn_count = 1
        self.contemporary_spawn_min = 0
        self.contemporary_spawn_max = 12
        self.phylogeny_clade_member_count = 3
        self.phylogeny_species_relative_count = 4
        self.knowledge_settings = self._load_knowledge_settings()
        self._apply_knowledge_settings()
        self.relation_tree_neighbor_cache = {}
        self.canvas_relation_edges = []
        self.card_font_cache = {}

        self.canvas_offset_x = 0
        self.canvas_offset_y = 0
        self.canvas_content_width = 0
        self.canvas_content_height = 0
        self.canvas_zoom = 1.0
        self.canvas_min_zoom = 0.35
        self.canvas_max_zoom = 2.5
        self.compact_canvas_zoom_threshold = 0.62
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
        self.timeline_expanded_panel_height = self.TIMELINE_DEFAULT_H
        self.timeline_collapsed = False
        self.timeline_splitter_rect = pygame.Rect(0, 0, 0, 0)
        self.timeline_splitter_toggle_rect = pygame.Rect(0, 0, 0, 0)
        self.active_timeline_resize = False
        self.timeline_resize_start_mouse_y = None
        self.timeline_resize_start_height = None
        self.timeline_splitter_click_pending = False
        self.timeline_splitter_pending_toggle = False
        self.timeline_splitter_pending_mouse_pos = None
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
        self.browser_collapse_handle_rect = None
        self.browser_search_rect = None
        self.browser_filter_hitboxes = []
        self.browser_period_filter_clear_rect = None
        self.world_model = None
        self.repository_scope_entity_id = None
        self.repository_scope_label = None
        self.header_button = None
        self.random_entry_button = None
        self.random_task_button = None
        self.new_entry_button = None
        self.clear_canvas_button = None
        self.contemporary_spawn_decrease_button = None
        self.contemporary_spawn_value_button = None
        self.contemporary_spawn_increase_button = None
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

    def _load_knowledge_settings(self):
        try:
            with open(self.SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_knowledge_settings(self):
        os.makedirs(self.SETTINGS_PATH.parent, exist_ok=True)
        with open(self.SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.knowledge_settings, f, indent=2, sort_keys=True)

    def _apply_knowledge_settings(self):
        value = self.knowledge_settings.get("contemporary_spawn_count", self.contemporary_spawn_count)
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 1
        self.contemporary_spawn_count = max(
            self.contemporary_spawn_min,
            min(self.contemporary_spawn_max, value),
        )

        for setting_key, attr_name, default_value in (
            ("phylogeny_clade_member_count", "phylogeny_clade_member_count", 3),
            ("phylogeny_species_relative_count", "phylogeny_species_relative_count", 4),
        ):
            raw_value = self.knowledge_settings.get(setting_key, default_value)
            try:
                raw_value = int(raw_value)
            except (TypeError, ValueError):
                raw_value = default_value
            setattr(self, attr_name, max(1, min(24, raw_value)))

    def _set_contemporary_spawn_count(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = self.contemporary_spawn_count
        value = max(self.contemporary_spawn_min, min(self.contemporary_spawn_max, value))
        if value == self.contemporary_spawn_count:
            return False
        self.contemporary_spawn_count = value
        self.knowledge_settings["contemporary_spawn_count"] = value
        self._write_knowledge_settings()
        self._build_header_button()
        return True

    def _set_phylogeny_clade_member_count(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = self.phylogeny_clade_member_count
        value = max(1, min(24, value))
        if value == self.phylogeny_clade_member_count:
            return False
        self.phylogeny_clade_member_count = value
        self.knowledge_settings["phylogeny_clade_member_count"] = value
        self._write_knowledge_settings()
        for card in self.cards:
            card["phylogeny_clade_member_limit"] = value
        self._relayout_cards()
        return True

    def _set_phylogeny_species_relative_count(self, value):
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = self.phylogeny_species_relative_count
        value = max(1, min(24, value))
        if value == self.phylogeny_species_relative_count:
            return False
        self.phylogeny_species_relative_count = value
        self.knowledge_settings["phylogeny_species_relative_count"] = value
        self._write_knowledge_settings()
        for card in self.cards:
            card["phylogeny_species_relative_limit"] = value
        self._relayout_cards()
        return True

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
        if self.timeline_collapsed:
            return
        self.timeline_ui.set_working_year_enabled(True)
        self.timeline_ui.set_location_focus_enabled(True)
        self.timeline_ui.set_entity_lookup(
            getattr(getattr(self.world_model, "loader", None), "entities", {})
            if self.world_model is not None
            else {}
        )
        timeline_items = self.world_model.get_timeline_items() if self.world_model is not None else []
        self.timeline_ui.set_open_canvas_entity_ids(card.get("entity_id") for card in self.cards)
        if self.browser_period_filter:
            self.timeline_ui.set_period_filter(*self.browser_period_filter)
        self.timeline_ui.set_items(timeline_items)
        self.timeline_ui.rebuild_layout()

    def _toggle_timeline_collapsed(self):
        if self.timeline_collapsed:
            self.timeline_collapsed = False
            self.timeline_panel_height = self._clamp_timeline_panel_height(
                self.app_height,
                self.timeline_expanded_panel_height,
            )
        else:
            self.timeline_expanded_panel_height = self._clamp_timeline_panel_height(
                self.app_height,
                self.timeline_panel_height,
            )
            self.timeline_collapsed = True
        self.active_timeline_resize = False
        self.active_timeline_pan = False
        self._refresh_layout_geometry()
        return True

    def _begin_timeline_resize(self, mouse_pos):
        self.active_timeline_resize = True
        self.timeline_resize_start_mouse_y = mouse_pos[1]
        self.timeline_resize_start_height = self.timeline_panel_height
        self.timeline_splitter_click_pending = False
        self.timeline_splitter_pending_toggle = False
        self.timeline_splitter_pending_mouse_pos = None
        return True

    def _begin_timeline_splitter_click(self, mouse_pos, toggle=False):
        if self.timeline_collapsed:
            self.timeline_splitter_click_pending = True
            self.timeline_splitter_pending_toggle = True
            self.timeline_splitter_pending_mouse_pos = mouse_pos
            return True
        if toggle:
            self.timeline_splitter_click_pending = True
            self.timeline_splitter_pending_toggle = True
            self.timeline_splitter_pending_mouse_pos = mouse_pos
            self.timeline_resize_start_mouse_y = mouse_pos[1]
            self.timeline_resize_start_height = self.timeline_panel_height
            return True
        return self._begin_timeline_resize(mouse_pos)

    def _clear_timeline_splitter_click(self):
        self.timeline_splitter_click_pending = False
        self.timeline_splitter_pending_toggle = False
        self.timeline_splitter_pending_mouse_pos = None

    def _stellar_neighbour_prompt_controller(self):
        controller = getattr(self, "_stellar_neighbour_prompt_ui", None)
        if controller is None:
            controller = StellarNeighbourPromptUI(self)
            self._stellar_neighbour_prompt_ui = controller
        return controller

    def _is_star_system_entity(self, entity):
        return self._stellar_neighbour_prompt_controller()._is_star_system_entity(entity)

    def _build_stellar_system_matches(self, query_text, exclude_entity_id=None):
        return self._stellar_neighbour_prompt_controller()._build_stellar_system_matches(
            query_text,
            exclude_entity_id=exclude_entity_id,
        )

    def _open_stellar_neighbourhood_prompt(self, card):
        return self._stellar_neighbour_prompt_controller()._open_stellar_neighbourhood_prompt(card)

    def _open_stellar_neighbour_distance_prompt(self, source_card, target_id):
        return self._stellar_neighbour_prompt_controller()._open_stellar_neighbour_distance_prompt(
            source_card,
            target_id,
        )

    def _close_stellar_neighbourhood_prompt(self):
        return self._stellar_neighbour_prompt_controller()._close_stellar_neighbourhood_prompt()

    def _set_stellar_prompt_query(self, text):
        return self._stellar_neighbour_prompt_controller()._set_stellar_prompt_query(text)

    def _select_stellar_prompt_match(self, match_index=None):
        return self._stellar_neighbour_prompt_controller()._select_stellar_prompt_match(match_index)

    def _upsert_stellar_neighbour(self, entity, target_id, distance_ly):
        return self._stellar_neighbour_prompt_controller()._upsert_stellar_neighbour(
            entity,
            target_id,
            distance_ly,
        )

    def _arrange_stellar_neighbour_cards(self, source_id):
        return self._stellar_neighbour_prompt_controller()._arrange_stellar_neighbour_cards(source_id)

    def _confirm_stellar_neighbourhood_prompt(self):
        return self._stellar_neighbour_prompt_controller()._confirm_stellar_neighbourhood_prompt()

    def _begin_stellar_neighbourhood_link(self, card):
        return self._stellar_neighbour_prompt_controller()._begin_stellar_neighbourhood_link(card)

    def _handle_stellar_neighbourhood_prompt_keydown(self, event):
        return self._stellar_neighbour_prompt_controller()._handle_stellar_neighbourhood_prompt_keydown(
            event
        )
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
        card["relation_picker_matches"] = self._build_relation_picker_matches(card, "")
        card["relation_picker_selected_index"] = 0
        card["relation_picker_hitboxes"] = []

    def _build_relation_picker_matches(self, card, query_text):
        matches = self._build_wiki_link_matches(query_text)
        target = card.get("relation_picker_target") if isinstance(card, dict) else None
        if not target:
            return matches
        filtered = []
        for match in matches:
            entity = self.world_model.get_entity(match.get("id")) if self.world_model is not None else None
            if self._entity_matches_relation_target(entity, target):
                filtered.append(match)
        return filtered

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
            card["relation_picker_matches"] = self._build_relation_picker_matches(card, "")
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
            card["relation_picker_matches"] = self._build_relation_picker_matches(card, card["relation_picker_query"])
            card["relation_picker_selected_index"] = 0
            return True

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            card["relation_picker_query"] = card.get("relation_picker_query", "") + text
            card["relation_picker_matches"] = self._build_relation_picker_matches(card, card["relation_picker_query"])
            card["relation_picker_selected_index"] = 0
            return True

        return False

    def _build_layout(self, app_width, app_height):
        if self.timeline_collapsed:
            timeline_h = self.TIMELINE_GAP
        else:
            timeline_h = self._clamp_timeline_panel_height(app_height)
            self.timeline_panel_height = timeline_h
            self.timeline_expanded_panel_height = timeline_h

        content_x = self.OUTER_MARGIN
        content_y = self.OUTER_MARGIN + self.HEADER_H + timeline_h
        content_w = app_width - self.OUTER_MARGIN * 2
        content_h = app_height - content_y - self.OUTER_MARGIN

        if self.browser_search_active:
            self.browser_collapsed = False

        left_w = 22 if self.browser_collapsed else int(content_w * self.LEFT_RATIO)
        right_w = content_w - left_w - self.INNER_GAP

        left_rect = pygame.Rect(content_x, content_y, left_w, content_h)
        right_rect = pygame.Rect(content_x + left_w + self.INNER_GAP, content_y, right_w, content_h)
        handle_w = 18
        handle_h = 56
        self.browser_collapse_handle_rect = pygame.Rect(
            left_rect.right - handle_w,
            left_rect.centery - handle_h // 2,
            handle_w,
            handle_h,
        )

        timeline_rect = pygame.Rect(
            self.OUTER_MARGIN,
            self.OUTER_MARGIN + self.HEADER_H,
            content_w,
            0 if self.timeline_collapsed else max(1, timeline_h - self.TIMELINE_GAP),
        )

        splitter_y = timeline_rect.bottom + max(1, (self.TIMELINE_GAP - self.TIMELINE_SPLITTER_H) // 2)
        self.timeline_splitter_rect = pygame.Rect(
            self.OUTER_MARGIN,
            splitter_y,
            content_w,
            self.TIMELINE_SPLITTER_H,
        )
        toggle_w = min(46, max(32, content_w // 12))
        self.timeline_splitter_toggle_rect = pygame.Rect(
            self.timeline_splitter_rect.centerx - toggle_w // 2,
            self.timeline_splitter_rect.y,
            toggle_w,
            self.timeline_splitter_rect.height,
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
            self.random_task_button = None
            self.new_entry_button = None
            self.clear_canvas_button = None
            self.contemporary_spawn_decrease_button = None
            self.contemporary_spawn_value_button = None
            self.contemporary_spawn_increase_button = None
            self.relation_touch_decrease_button = None
            self.relation_touch_value_button = None
            self.relation_touch_increase_button = None
            return

        self.header_button = None

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
        self.random_entry_button = UIButton(
            button_id="knowledge_random_entry",
            label="Random Entry",
            rect=pygame.Rect(button_right - 104, button_y, 104, 28),
            visible=True,
            enabled=True,
        )
        button_right = self.random_entry_button.rect.x - button_gap
        self.clear_canvas_button = UIButton(
            button_id="knowledge_clear_canvas",
            label="Clear Canvas",
            rect=pygame.Rect(button_right - 112, button_y, 112, 28),
            visible=True,
            enabled=True,
        )
        button_right = self.clear_canvas_button.rect.x - button_gap
        contemporary_value_w = 86
        contemporary_step_w = 28
        self.contemporary_spawn_increase_button = UIButton(
            button_id="knowledge_contemporary_spawn_increase",
            label="+",
            rect=pygame.Rect(button_right - contemporary_step_w, button_y, contemporary_step_w, 28),
            visible=True,
            enabled=self.contemporary_spawn_count < self.contemporary_spawn_max,
        )
        button_right = self.contemporary_spawn_increase_button.rect.x - 4
        self.contemporary_spawn_value_button = UIButton(
            button_id="knowledge_contemporary_spawn_value",
            label=f"Contemp {self.contemporary_spawn_count}",
            rect=pygame.Rect(button_right - contemporary_value_w, button_y, contemporary_value_w, 28),
            visible=True,
            enabled=False,
        )
        button_right = self.contemporary_spawn_value_button.rect.x - 4
        self.contemporary_spawn_decrease_button = UIButton(
            button_id="knowledge_contemporary_spawn_decrease",
            label="-",
            rect=pygame.Rect(button_right - contemporary_step_w, button_y, contemporary_step_w, 28),
            visible=True,
            enabled=self.contemporary_spawn_count > self.contemporary_spawn_min,
        )
        button_right = self.contemporary_spawn_decrease_button.rect.x - button_gap
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

    def _schema_display_label(self, name):
        text = str(name or "entry")
        text = text.replace("_", " ").strip()
        return text.title() if text else "Entry"

    def _normalize_schema_name(self, name):
        text = str(name or "").strip().lower()
        suffix = Path(text).suffix
        if suffix:
            text = Path(text).stem
        text = text.replace("-", "_").replace(" ", "_")
        if text.startswith("index0_"):
            text = text[len("index0_"):]
        if text.endswith("_schema"):
            text = text[:-len("_schema")]
        return text

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
        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        datasets = getattr(loader, "datasets", None)
        if isinstance(datasets, dict):
            return set(datasets.keys()) - {"schemas"}
        return set()

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
            "collections": "coll",
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
        if not hasattr(self, "schema_loader"):
            return []

        existing_datasets = self._entry_dataset_names()
        templates = []
        for loader_schema_name, schema in sorted(self.schema_loader.schemas.items()):
            if not isinstance(schema, dict):
                continue
            metadata_name = (schema.get("metadata") or {}).get("name")
            raw_schema_name = schema.get("schema") or metadata_name or loader_schema_name
            schema_name = self._normalize_schema_name(raw_schema_name)
            file_base = schema_name
            if schema_name in self.ABSTRACT_SCHEMA_NAMES or schema_name == "entity_core" or schema_name == "systems":
                continue

            dataset_name = self._dataset_name_for_schema(schema_name, file_base, existing_datasets)
            if dataset_name in {"spatial_features", "systems"}:
                continue
            entity_type = self._entity_type_for_schema(schema_name, dataset_name)
            label = self._schema_display_label(entity_type)
            templates.append(
                {
                    "schema_name": schema_name,
                    "schema_path": None,
                    "schema": schema,
                    "dataset_name": dataset_name,
                    "entity_type": entity_type,
                    "label": label,
                    "id_prefix": self._template_id_prefix(dataset_name, entity_type=entity_type),
                }
            )

        preferred = {"tasks": 0, "ideas": 1, "species": 2, "cladistics": 3}
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
        extra_h = 24 if self.relation_link_target is not None else 0
        if self.browser_period_filter:
            extra_h += 24
        return extra_h

    def _relation_target_dataset_filter(self, target):
        if self.world_model is None:
            return "all"

        if len(self._relation_target_options(target)) != 1:
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
        options = self._relation_target_options(target)
        if len(options) > 1:
            labels = [option.replace("_", " ") for option in options]
            if len(labels) == 2:
                return " or ".join(labels)
            return f"{', '.join(labels[:-1])}, or {labels[-1]}"

        normalized = self._normalize_schema_name(options[0] if options else target)
        if normalized in {"star_system", "stellar_system"}:
            return "star system"
        if not normalized or normalized in {"entity", "entity_core", "core", "any"}:
            return "entry"
        return normalized.replace("_", " ")

    def _relation_target_options(self, target):
        if isinstance(target, (list, tuple, set)):
            return [
                self._normalize_schema_name(candidate)
                for candidate in target
                if self._normalize_schema_name(candidate)
            ]

        target_text = str(target or "").strip()
        if not target_text:
            return []

        for delimiter in ("|", ","):
            if delimiter in target_text:
                return [
                    self._normalize_schema_name(candidate)
                    for candidate in target_text.split(delimiter)
                    if self._normalize_schema_name(candidate)
                ]

        normalized = self._normalize_schema_name(target_text)
        return [normalized] if normalized else []

    def _relation_target_candidates(self, target):
        options = self._relation_target_options(target)
        if not options or any(option in {"entity", "entity_core", "core", "any"} for option in options):
            return set()

        candidates = set()
        for normalized in options:
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
            "species",
            "cladistics",
            "vehicles",
            "locations",
            "components",
            "events",
            "factions",
            "technologies",
            "materials",
        ]
        preferred_index = {name: index for index, name in enumerate(preferred)}

        subclass_order = {
            ("vehicles", None, None): 0,
            ("vehicles", "vehicle_class", "ground_vehicle"): 1,
            ("vehicles", "vehicle_class", "aircraft"): 2,
            ("vehicles", "vehicle_class", "naval_vessel"): 3,
            ("vehicles", "vehicle_class", "orbital_spacecraft"): 4,
            ("vehicles", "vehicle_class", "planetary_spacecraft"): 5,
            ("vehicles", "vehicle_class", "system_spacecraft"): 6,
            ("vehicles", "vehicle_class", "interstellar_spacecraft"): 7,
        }

        def template_subclass_order(template):
            dataset_name = template.get("dataset_name")
            field_key = template.get("subclass_field")
            subclass_value = template.get("subclass_value")
            if field_key is None:
                return subclass_order.get((dataset_name, None, None), 0)
            return subclass_order.get(
                (dataset_name, field_key, self._normalize_schema_name(subclass_value)),
                100,
            )

        templates.sort(
            key=lambda template: (
                preferred_index.get(template.get("dataset_name"), len(preferred)),
                template_subclass_order(template),
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
                identity = (
                    dataset_name,
                    template.get("entity_type"),
                    self._normalize_schema_name(subclass_value),
                )
                if identity in seen:
                    continue
                seen.add(identity)
                variants.append(self._subclass_template_variant(template, field_key, subclass_value))

            if self.world_model is None:
                continue

            value_counts = {}
            field_by_value = {}
            entities = self.world_model.get_entities_by_dataset(dataset_name)
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                for field_key in fields:
                    raw_value = entity.get(field_key)
                    if not isinstance(raw_value, str) or not raw_value.strip():
                        continue
                    subclass_value = raw_value.strip()
                    normalized_value = subclass_value.lower()
                    value_counts[normalized_value] = value_counts.get(normalized_value, 0) + 1
                    field_by_value.setdefault(normalized_value, (field_key, subclass_value))

            for normalized_value, count in sorted(value_counts.items(), key=lambda item: item[0]):
                field_key, subclass_value = field_by_value[normalized_value]
                identity = (dataset_name, template.get("entity_type"), normalized_value)
                if identity in seen:
                    continue
                if not self._keep_subclass_template_variant(dataset_name, field_key, subclass_value, count):
                    continue
                seen.add(identity)
                variants.append(self._subclass_template_variant(template, field_key, subclass_value))

        return variants

    def _keep_subclass_template_variant(self, dataset_name, field_key, subclass_value, entry_count=0):
        normalized_value = self._normalize_schema_name(subclass_value)
        if not normalized_value:
            return False
        allowed_values = self._allowed_subclass_template_values(dataset_name, field_key)
        if allowed_values is not None:
            return normalized_value in allowed_values
        if normalized_value in self._canonical_subclass_value_names(dataset_name, field_key):
            return True
        if entry_count >= self.SUFFICIENT_SUBCLASS_ENTRY_COUNT:
            return True
        return self._subclass_value_used_in_simulations(field_key, normalized_value)

    def _allowed_subclass_template_values(self, dataset_name, field_key):
        if dataset_name == "vehicles" and field_key == "vehicle_class":
            return {
                self._normalize_schema_name(value)
                for value in self.CANONICAL_VEHICLE_CLASSES
            }
        if dataset_name == "components" and field_key == "component_class":
            return set()
        if dataset_name == "locations" and field_key == "location_class":
            return {
                self._normalize_schema_name(value)
                for value in self.CANONICAL_LOCATION_CLASSES
            }
        return None

    def _canonical_subclass_value_names(self, dataset_name, field_key):
        template = self._template_by_dataset(dataset_name) or {}
        values = set()
        for canonical_field_key, subclass_value in self._canonical_subclass_values_for_template(template):
            if canonical_field_key == field_key:
                values.add(self._normalize_schema_name(subclass_value))
        return values

    def _simulation_subclass_terms(self):
        cached = getattr(self, "_simulation_subclass_term_cache", None)
        if cached is not None:
            return cached

        terms = set()
        simulation_dir = self.PROJECT_ROOT / "simulations"
        if simulation_dir.exists():
            for path in simulation_dir.rglob("*.py"):
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                for token in re.findall(r"[A-Za-z][A-Za-z0-9_ -]{1,80}", text):
                    terms.add(self._normalize_schema_name(token))

        self._simulation_subclass_term_cache = terms
        return terms

    def _subclass_value_used_in_simulations(self, field_key, subclass_value):
        normalized_value = self._normalize_schema_name(subclass_value)
        if not normalized_value:
            return False
        if field_key == "vehicle_class":
            try:
                from simulations.vehicle.vehicle_design import VehicleDesignController
            except ImportError:
                return False
            return normalized_value in {
                self._normalize_schema_name(value)
                for value in VehicleDesignController.VEHICLE_CLASS_REQUIREMENTS.keys()
            }
        if field_key == "component_class":
            try:
                from simulations.vehicle.vehicle_design import VehicleDesignController
            except ImportError:
                return False
            return normalized_value in {
                self._normalize_schema_name(value)
                for value in VehicleDesignController.COMPONENT_CATEGORY_HINTS.keys()
            }
        return normalized_value in self._simulation_subclass_terms()

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

    def _browser_model(self):
        model = getattr(self, "_knowledge_browser_model", None)
        if model is None:
            model = KnowledgeBrowserModel(self)
            self._knowledge_browser_model = model
        return model

    def _is_expanded(self, *args, **kwargs):
        return getattr(self._browser_model(), "_is_expanded")(*args, **kwargs)

    def _set_expanded(self, *args, **kwargs):
        return getattr(self._browser_model(), "_set_expanded")(*args, **kwargs)

    def _browser_dataset_filters(self, *args, **kwargs):
        return getattr(self._browser_model(), "_browser_dataset_filters")(*args, **kwargs)

    def _format_browser_filter_label(self, *args, **kwargs):
        return getattr(self._browser_model(), "_format_browser_filter_label")(*args, **kwargs)

    def _entity_exists_during_browser_period(self, *args, **kwargs):
        return getattr(self._browser_model(), "_entity_exists_during_browser_period")(*args, **kwargs)

    def _matches_browser_filters(self, *args, **kwargs):
        return getattr(self._browser_model(), "_matches_browser_filters")(*args, **kwargs)

    def _matches_schema_browser_filters(self, *args, **kwargs):
        return getattr(self._browser_model(), "_matches_schema_browser_filters")(*args, **kwargs)

    def _build_schema_browser_items(self, *args, **kwargs):
        return getattr(self._browser_model(), "_build_schema_browser_items")(*args, **kwargs)

    def _resolve_schema_for_entity(self, *args, **kwargs):
        return getattr(self._browser_model(), "_resolve_schema_for_entity")(*args, **kwargs)

    def _collect_schema_fields(self, *args, **kwargs):
        return getattr(self._browser_model(), "_collect_schema_fields")(*args, **kwargs)

    def _entity_missing_scalar_count(self, *args, **kwargs):
        return getattr(self._browser_model(), "_entity_missing_scalar_count")(*args, **kwargs)

    def _location_tree_entity_matches(self, *args, **kwargs):
        return getattr(self._browser_model(), "_location_tree_entity_matches")(*args, **kwargs)

    def _location_tree_auto_reveal_descendants(self, *args, **kwargs):
        return getattr(self._browser_model(), "_location_tree_auto_reveal_descendants")(*args, **kwargs)

    def _location_tree_item(self, *args, **kwargs):
        return getattr(self._browser_model(), "_location_tree_item")(*args, **kwargs)

    def _canonical_location_class_key(self, *args, **kwargs):
        return getattr(self._browser_model(), "_canonical_location_class_key")(*args, **kwargs)

    def _location_class_display_label(self, *args, **kwargs):
        return getattr(self._browser_model(), "_location_class_display_label")(*args, **kwargs)

    def _location_browser_domain(self, *args, **kwargs):
        return getattr(self._browser_model(), "_location_browser_domain")(*args, **kwargs)

    def _location_browser_domain_label(self, *args, **kwargs):
        return getattr(self._browser_model(), "_location_browser_domain_label")(*args, **kwargs)

    def _location_hierarchy_sort_key(self, *args, **kwargs):
        return getattr(self._browser_model(), "_location_hierarchy_sort_key")(*args, **kwargs)

    def _build_location_browser_items(self, *args, **kwargs):
        return getattr(self._browser_model(), "_build_location_browser_items")(*args, **kwargs)

    def _dataset_display_label(self, *args, **kwargs):
        return getattr(self._browser_model(), "_dataset_display_label")(*args, **kwargs)

    def _entity_class_label(self, *args, **kwargs):
        return getattr(self._browser_model(), "_entity_class_label")(*args, **kwargs)

    def _build_browser_items(self, *args, **kwargs):
        return getattr(self._browser_model(), "_build_browser_items")(*args, **kwargs)
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
            subtype = entity.get("idea_class") or entity.get("entry_status") or "generic"
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

        start_year = parse_year(start_year)
        end_year = parse_year(end_year)
        point_year = parse_year(point_year)

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
            "phylogeny_parent_input_active": False,
            "phylogeny_parent_query": "",
            "phylogeny_parent_matches": [],
            "phylogeny_parent_selected_index": 0,
            "phylogeny_parent_scroll_y": 0,
            "phylogeny_parent_scroll_max_y": 0,
            "phylogeny_child_input_active": False,
            "phylogeny_child_query": "",
            "phylogeny_child_matches": [],
            "phylogeny_child_selected_index": 0,
            "phylogeny_child_sibling_id": "",
            "phylogeny_clade_member_limit": self.phylogeny_clade_member_count,
            "phylogeny_species_relative_limit": self.phylogeny_species_relative_count,
            "phylogeny_status": "",
            "production_input_active": False,
            "production_active_field": None,
            "production_active_line": None,
            "production_query": "",
            "production_matches": [],
            "production_selected_index": 0,
            "production_hitboxes": [],
            "production_match_rows": [],
            "production_line_rows": [],
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
        self._sync_card_working_year_context(card)
        self._apply_cached_draft_to_card(card)
        return card

    def _build_card_from_schema(self, schema_name):
        if not schema_name or self.layout is None:
            return None

        schema = self.schema_loader.schemas.get(schema_name)
        if not isinstance(schema, dict):
            return None

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
                schema_path=None,
                usage_by_field=self.schema_field_usage,
            ),
            "schema_name": schema_name,
            "schema_schema_name": schema.get("schema", schema_name),
            "schema_extends": schema.get("extends"),
            "schema_path": None,
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
            "phylogeny_parent_input_active": False,
            "phylogeny_parent_query": "",
            "phylogeny_parent_matches": [],
            "phylogeny_parent_selected_index": 0,
            "phylogeny_parent_scroll_y": 0,
            "phylogeny_parent_scroll_max_y": 0,
            "phylogeny_child_input_active": False,
            "phylogeny_child_query": "",
            "phylogeny_child_matches": [],
            "phylogeny_child_selected_index": 0,
            "phylogeny_child_sibling_id": "",
            "phylogeny_clade_member_limit": self.phylogeny_clade_member_count,
            "phylogeny_species_relative_limit": self.phylogeny_species_relative_count,
            "phylogeny_status": "",
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


    def _canvas_controller(self):
        controller = getattr(self, "_knowledge_canvas_controller", None)
        if controller is None:
            controller = KnowledgeCanvasController(self)
            self._knowledge_canvas_controller = controller
        return controller

    def _layout_all_cards(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_layout_all_cards")(*args, **kwargs)

    def _layout_offscreen_card(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_layout_offscreen_card")(*args, **kwargs)

    def _is_compact_canvas_mode(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_is_compact_canvas_mode")(*args, **kwargs)

    def _layout_compact_card(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_layout_compact_card")(*args, **kwargs)

    def _clamp_canvas_offsets(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_clamp_canvas_offsets")(*args, **kwargs)

    def _card_accepts_canvas_relation(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_card_accepts_canvas_relation")(*args, **kwargs)

    def _layout_canvas_relation_controls(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_layout_canvas_relation_controls")(*args, **kwargs)

    def _relayout_cards(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_relayout_cards")(*args, **kwargs)

    def _card_font_for_zoom(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_card_font_for_zoom")(*args, **kwargs)

    def _screen_to_canvas_pos(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_screen_to_canvas_pos")(*args, **kwargs)

    def _set_canvas_zoom_at(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_set_canvas_zoom_at")(*args, **kwargs)

    def _scroll_card_at(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_scroll_card_at")(*args, **kwargs)

    def _scroll_phylogeny_parent_at(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_scroll_phylogeny_parent_at")(*args, **kwargs)

    def _scroll_type_picker_at(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_scroll_type_picker_at")(*args, **kwargs)

    def _bring_card_to_front(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_bring_card_to_front")(*args, **kwargs)

    def _close_card_at_index(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_close_card_at_index")(*args, **kwargs)

    def _begin_card_resize(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_begin_card_resize")(*args, **kwargs)
    def _focus_timeline_year(self, year):
        return self.timeline_ui.focus_year(year)

    def _is_wiki_text_edit_field(self, card_or_view, field_key=None):
        card_view = None
        if isinstance(card_or_view, dict):
            card_view = card_or_view.get("card_view")
        else:
            card_view = card_or_view
        timeline_field = getattr(card_view, "TIMELINE_SNAPSHOT_FIELD", EntityCard.TIMELINE_SNAPSHOT_FIELD)
        return field_key in {"wiki_entry", "temporal_periods", timeline_field}

    def _sync_card_working_year_context(self, card):
        if card is None or getattr(self, "timeline_ui", None) is None:
            return False
        year_range = self.timeline_ui.get_working_year_range()
        if year_range is None:
            changed = card.pop("working_year_range", None) is not None
            return changed
        normalized = (int(year_range[0]), int(year_range[1]))
        changed = card.get("working_year_range") != normalized
        card["working_year_range"] = normalized
        return changed

    def _sync_cards_working_year_context(self):
        changed = False
        for card in self.cards:
            changed = self._sync_card_working_year_context(card) or changed
        return changed

    def _apply_timeline_action(self, timeline_action):
        if not isinstance(timeline_action, dict):
            return False
        action_kind = timeline_action.get("kind")
        if action_kind == "period_filter_started":
            self.timeline_ui.set_period_filter(pending_start=timeline_action.get("year"))
            return True
        if action_kind == "period_filter_changed":
            start_year = timeline_action.get("start_year")
            end_year = timeline_action.get("end_year")
            try:
                self.browser_period_filter = (int(start_year), int(end_year))
            except (TypeError, ValueError):
                return False
            self.timeline_ui.set_period_filter(*self.browser_period_filter)
            self.browser_items = self._build_browser_items(self.world_model)
            self.browser_scroll = 0
            self._rebuild_browser_hitboxes()
            return True
        if action_kind == "open_timeline_entity":
            entity_id = timeline_action.get("entity_id")
            entity = self.world_model.get_entity(entity_id) if self.world_model is not None else None
            if entity is None:
                return False
            card = self._ensure_card(entity)
            if card is not None:
                start_year = timeline_action.get("start_year")
                end_year = timeline_action.get("end_year", start_year)
                try:
                    card["active_timeline_snapshot_range"] = (int(start_year), int(end_year))
                    card["selected_year"] = int(start_year)
                except (TypeError, ValueError):
                    pass
                self._sync_card_working_year_context(card)
                self._relayout_cards()
            return True
        if action_kind in {
            "working_year_changed",
            "working_year_focus",
            "working_year_editing",
            "working_year_cancelled",
            "random_working_year_changed",
            "location_focus_changed",
            "location_focus_focus",
            "location_focus_editing",
            "location_focus_cancelled",
            "location_focus_invalid",
            "random_location_focus_changed",
        }:
            if action_kind.startswith("working_year_") or action_kind == "random_working_year_changed":
                self._sync_cards_working_year_context()
            if timeline_action.get("changed"):
                self._refresh_timeline_items()
            return True
        return True

    def _clear_browser_period_filter(self):
        if not self.browser_period_filter and self.timeline_ui.period_filter_pending_start is None:
            return False
        self.browser_period_filter = None
        self.timeline_ui.set_period_filter()
        self.browser_items = self._build_browser_items(self.world_model)
        self.browser_scroll = 0
        self._rebuild_browser_hitboxes()
        return True

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

    def _random_task_entity(self):
        if self.world_model is None:
            return None

        wiki_tasks = []
        for entity in self.world_model.loader.entities.values():
            if not isinstance(entity, dict) or not entity.get("id"):
                continue
            for task in CardWikiRenderer.extract_tasks(entity.get("wiki_entry", "")):
                wiki_tasks.append(
                    {
                        "entity": entity,
                        "task_number": task.get("task_number"),
                        "text": task.get("text", ""),
                    }
                )
        if wiki_tasks:
            selected = random.choice(wiki_tasks)
            return selected.get("entity")
        return None

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

    def _clear_card_canvas(self):
        self.cards = []
        self.selected_entity_id = None
        self.active_card_drag_id = None
        self.active_card_resize_id = None
        self.active_card_color_slider = None
        self.canvas_relation_link_source_id = None
        self.canvas_relation_status = ""
        self.canvas_relation_edges = []
        self.timeline_ui.set_open_canvas_entity_ids([])
        self.timeline_ui.rebuild_layout()
        self._layout_all_cards()
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

    def _requested_illustration_entity_id_from_name(self, entry_name):
        slug = self._slug_from_text(entry_name)
        if not slug:
            return ""
        requested_id = slug if slug.startswith("illust_") else f"illust_{slug}"
        return self._unique_entity_id(requested_id)

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
            }
        else:
            entity = {
                "id": entity_id,
                "pretty_name": label,
                "name": label,
                "type": entity_type,
                "_dataset": dataset_name,
            }
        self._populate_required_schema_fields(entity, template)
        entity.setdefault("three_word_description", "")
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

    def _entry_name_prompt_controller(self):
        controller = getattr(self, "_entry_name_prompt_ui", None)
        if controller is None:
            controller = EntryNamePromptUI(self)
            self._entry_name_prompt_ui = controller
        return controller

    def _open_entry_name_prompt(self, template, mode="template", context=None, label=None, initial_buffer=""):
        return self._entry_name_prompt_controller()._open_entry_name_prompt(
            template,
            mode=mode,
            context=context,
            label=label,
            initial_buffer=initial_buffer,
        )

    def _open_new_entry_name_prompt(self):
        return self._entry_name_prompt_controller()._open_new_entry_name_prompt()

    def _relation_tab_new_entry_context(self):
        return self._entry_name_prompt_controller()._relation_tab_new_entry_context()

    def _entry_name_prompt_uses_suggestions(self, prompt=None):
        return self._entry_name_prompt_controller()._entry_name_prompt_uses_suggestions(prompt)

    def _entry_name_prompt_matches(self, query_text, limit=7):
        return self._entry_name_prompt_controller()._entry_name_prompt_matches(
            query_text,
            limit=limit,
        )

    def _refresh_entry_name_prompt_suggestions(self):
        return self._entry_name_prompt_controller()._refresh_entry_name_prompt_suggestions()

    def _select_entry_name_prompt_suggestion(self, index=None, link_from_context=True):
        return self._entry_name_prompt_controller()._select_entry_name_prompt_suggestion(
            index=index,
            link_from_context=link_from_context,
        )

    def _open_entry_description_prompt(self, template, entry_name, context=None):
        entry_name = str(entry_name or "").strip()
        if not entry_name:
            return False
        template_label = "Entry"
        if isinstance(template, dict):
            template_label = template.get("label") or self._schema_display_label(template.get("dataset_name"))
        return self._open_entry_name_prompt(
            template,
            mode="entry_description",
            context={
                "entry_name": entry_name,
                **dict(context or {}),
            },
            label=f"{entry_name} | {template_label}",
        )

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

    def _open_illustration_prompt(self, parent_card):
        if parent_card is None:
            return False

        parent_entity_id = parent_card.get("entity_id")
        if not parent_entity_id:
            return False

        parent_label = parent_card.get("title") or parent_entity_id
        parent_entity = self.world_model.get_entity(parent_entity_id) if self.world_model is not None else None
        if parent_entity is not None:
            parent_label = self._entity_display_label(parent_entity, fallback=parent_label)

        selected_year = parent_card.get("selected_year")
        return self._open_entry_name_prompt(
            None,
            mode="illustration_from_parent",
            context={
                "parent_entity_id": parent_entity_id,
                "parent_label": parent_label,
                "selected_year": selected_year,
            },
            label=f"Illustration for {parent_label}",
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
        if role in {"wiki", "wiki_alt"}:
            colors = entity.get("wiki_field_colors")
            if not isinstance(colors, dict):
                colors = {}
            section_id = str(section_id or "").strip()
            if role == "wiki_alt":
                return colors.get("alternate") or colors.get("default") or "#222632"
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
        elif role in {"wiki", "wiki_alt"}:
            section_id = str(section_id or (card or {}).get("active_wiki_section_id") or "default").strip() or "default"
            if role == "wiki_alt":
                section_id = "alternate"
            colors = entity.get("wiki_field_colors")
            if not isinstance(colors, dict):
                colors = {}
            colors[section_id] = color_hex
            entity["wiki_field_colors"] = colors
        else:
            entity["card_color"] = color_hex
            entity.pop("card_color_source", None)
        entity.pop("wiki_link_color", None)
        if card is None:
            return True

        card_view = card.get("card_view")
        if card_view is not None:
            card_view.entity = entity

        if not persist and not card.get("is_temporary", False):
            card["pending_color_persist"] = True
            return True

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
        return self._entry_name_prompt_controller()._close_entry_name_prompt()
    def _is_star_system_template(self, template):
        if not isinstance(template, dict) or template.get("dataset_name") != "locations":
            return False
        initial_fields = self._template_initial_fields(template)
        class_value = (
            template.get("subclass_value")
            or initial_fields.get("location_class")
            or ""
        )
        return self._normalize_schema_name(class_value) in {"star_system", "stellar_system"}

    def _next_star_system_entity_ids(self, system_name):
        slug = self._slug_from_text(system_name) or "new_system"
        system_base_id = f"system_{slug}"
        star_base_id = f"star_{slug}_primary"
        existing_ids = set(self.world_model.loader.entities.keys()) if self.world_model is not None else set()
        existing_ids.update(self.card_drafts.keys())
        system_id = self._unique_entity_id(system_base_id)
        star_id = self._unique_entity_id(star_base_id)
        if system_id == star_id:
            star_id = self._unique_entity_id(f"{star_base_id}_star")
        return system_id, star_id

    def _create_star_system_from_class(self, template, system_name, star_class_text):
        if self.world_model is None:
            return None

        from simulations.space.stellar import is_valid_stellar_class, stellar_profile_for_class

        if not is_valid_stellar_class(star_class_text):
            return None

        system_name = str(system_name or "").strip()
        if not system_name:
            return None

        profile = stellar_profile_for_class(star_class_text)
        system_id, star_id = self._next_star_system_entity_ids(system_name)
        class_label = profile.get("label", "G-Class")
        star_name = f"{system_name} Primary"

        system_entity = self._create_template_entity(
            template,
            requested_id=system_id,
            initial_fields={
                "pretty_name": system_name,
                "name": system_name,
                "location_class": "star_system",
                "location_role": "star_system",
                "star_class": class_label,
                "spectral_class": profile.get("spectral_class", profile.get("class_key")),
                "luminosity_solar": profile.get("luminosity_solar"),
                "habitable_zone_inner_au": profile.get("habitable_zone_inner_au"),
                "habitable_zone_outer_au": profile.get("habitable_zone_outer_au"),
                "tags": ["empty_system", "habitable_zone"],
                "offspring": [{"id": star_id}],
                "card_color": profile.get("card_color"),
            },
            label=system_name,
        )
        if system_entity is None:
            return None

        location_template = self._template_by_dataset("locations") or template
        star_entity = self._create_template_entity(
            location_template,
            requested_id=star_id,
            initial_fields={
                "pretty_name": star_name,
                "name": star_name,
                "location_class": "star",
                "location_role": "orbital_body",
                "parent_location": system_id,
                "star_system": system_id,
                "star_class": class_label,
                "spectral_class": profile.get("spectral_class", profile.get("class_key")),
                "luminosity_solar": profile.get("luminosity_solar"),
                "mass_kg": profile.get("mass_kg"),
                "radius_m": profile.get("radius_m"),
                "display_color": list(profile.get("display_color", [])),
                "card_color": profile.get("card_color"),
            },
            label=star_name,
        )
        if star_entity is None:
            return system_entity

        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()

        system_card = self._ensure_card(system_entity)
        if system_card is not None:
            system_card["is_draft_entity"] = True
            system_card["title"] = system_name
            self._place_new_card_in_canvas_view(system_card)
            self._save_card_draft(system_card)

        self._relayout_cards()
        return system_entity

    def _create_named_template_entity(self, template, entry_name, short_description=""):
        initial_fields = {
            "pretty_name": entry_name,
            "name": entry_name,
        }
        short_description = str(short_description or "").strip()
        if short_description:
            initial_fields["three_word_description"] = short_description

        entity = self._create_and_open_template_entity(
            template,
            requested_id=self._requested_template_entity_id_from_name(template, entry_name),
            initial_fields=initial_fields,
            label=entry_name,
            place_in_view=True,
        )
        if entity is None:
            return None

        entity["pretty_name"] = entry_name
        entity["name"] = entry_name
        if short_description:
            entity["three_word_description"] = short_description
        card = self._find_card_by_entity_id(entity.get("id"))
        if card is not None:
            card["title"] = entry_name
            self._save_card_draft(card)

        return entity

    def _finish_named_template_entry_creation(self, template, entry_name, short_description="", context=None):
        context = dict(context or {})
        entity = self._create_named_template_entity(template, entry_name, short_description=short_description)
        if entity is None:
            return None

        created_entity_id = str(entity.get("id") or "").strip()
        if context.get("relation_create"):
            source_card = context.get("card")
            if source_card not in self.cards:
                source_card = self._find_card_by_entity_id(context.get("source_entity_id"))
            if source_card is not None and created_entity_id:
                self._replace_relation_reference_on_card(
                    source_card,
                    context.get("field_key"),
                    context.get("missing_ref"),
                    created_entity_id,
                )
        elif context.get("production_create_site"):
            producer_card = self._find_card_by_entity_id(context.get("producer_card_entity_id"))
            producer_id = str((producer_card or {}).get("entity_id") or "").strip()
            if producer_id:
                entity["location_class"] = "site"
                entity["site_class"] = "production_site"
                entity["operated_by"] = [producer_id]
                entity["type"] = "location"
                entity["_dataset"] = "locations"
                created_card = self._find_card_by_entity_id(created_entity_id)
                if created_card is not None:
                    created_card["subtitle"] = self._card_subtitle_for_entity(entity)
                    self._save_card_draft(created_card)
                self._persist_entity_to_repository(entity)
            if producer_card is not None and created_entity_id:
                line_index = context.get("production_line_index")
                card_view = producer_card.get("card_view")
                if card_view is not None and hasattr(card_view, "_update_production_line"):
                    card_view._update_production_line(producer_card, line_index, location_id=created_entity_id)
                    related_update_ids = list(producer_card.pop("production_related_entity_update_ids", []) or [])
                    for related_entity_id in related_update_ids:
                        related_entity = self.world_model.get_entity(related_entity_id) if self.world_model is not None else None
                        if isinstance(related_entity, dict):
                            self._persist_entity_to_repository(related_entity)
                    producer_card["last_edit_action"] = None
        else:
            self._link_entry_name_prompt_result(created_entity_id, context)

        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return entity

    def _link_entry_name_prompt_result(self, entity_id, context):
        context = context if isinstance(context, dict) else {}
        source_entity_id = str(context.get("link_source_entity_id") or "").strip()
        field_key = str(context.get("link_field_key") or "related").strip()
        entity_id = str(entity_id or "").strip()
        if not source_entity_id or not field_key or not entity_id or source_entity_id == entity_id:
            return False

        source_card = self._find_card_by_entity_id(source_entity_id)
        if source_card is None and self.world_model is not None:
            source_entity = self.world_model.get_entity(source_entity_id)
            source_card = self._ensure_card(source_entity, bring_to_front=False) if source_entity is not None else None
        if source_card is None:
            return False

        linked = self._insert_relation_reference_into_card(source_card, field_key, entity_id)
        if linked:
            source_card["relation_link_status"] = f"Linked {entity_id}"
            self.browser_items = self._build_browser_items(self.world_model)
            self._rebuild_browser_hitboxes()
            self._relayout_cards()
        return linked

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

    def _create_illustration_from_parent(self, parent_entity_id, entry_name, description="", date_value=None):
        if self.world_model is None or not parent_entity_id:
            return None

        template = self._template_by_dataset("ideas") or {
            "dataset_name": "ideas",
            "entity_type": "idea",
            "schema_name": "idea",
        }
        initial_fields = {
            "pretty_name": entry_name,
            "name": entry_name,
            "idea_class": "illustration",
            "description": str(description or "").strip(),
            "wiki_entry": str(description or "").strip(),
            "date": "" if date_value in (None, "") else str(date_value),
            "parents": [parent_entity_id],
            "media_path": "",
            "entry_status": "",
        }
        illustration = self._create_template_entity(
            template,
            requested_id=self._requested_illustration_entity_id_from_name(entry_name),
            initial_fields=initial_fields,
            label=entry_name,
        )
        if illustration is None:
            return None

        illustration.update(initial_fields)
        self._persist_entity_to_repository(illustration)
        self._sync_bidirectional_relations(persist=True)
        self.browser_items = self._build_browser_items(self.world_model)
        self._refresh_timeline_items()
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return illustration

    def _open_relation_note_prompt(self, source_card, relation_info, initial_text=""):
        return self._entry_name_prompt_controller()._open_relation_note_prompt(
            source_card,
            relation_info,
            initial_text=initial_text,
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
        mode = prompt.get("mode", "template")
        template = prompt.get("template")
        if mode == "entry_description":
            context = dict(prompt.get("context") or {})
            actual_entry_name = str(context.get("entry_name") or "").strip()
            if not actual_entry_name:
                prompt["status"] = "Name required"
                return True
            created = self._finish_named_template_entry_creation(
                template,
                actual_entry_name,
                short_description=entry_name,
                context=context,
            )
            if created is None:
                prompt["status"] = "Could not create entry"
                return True
            self._close_entry_name_prompt()
            return True

        if not entry_name:
            prompt["status"] = "Name required"
            return True

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

        if mode == "illustration_from_parent":
            context = prompt.get("context", {})
            illustration = self._create_illustration_from_parent(
                context.get("parent_entity_id"),
                entry_name,
                description=prompt.get("description_buffer", ""),
                date_value=context.get("selected_year"),
            )
            if illustration is None:
                prompt["status"] = "Could not create illustration"
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

        if mode == "star_system_class":
            context = prompt.get("context", {})
            system_name = str(context.get("system_name") or "").strip()
            created = self._create_star_system_from_class(template, system_name, entry_name)
            if created is None:
                prompt["status"] = "Valid: O/B/A/F/G/K/M + optional 0-9 + Ia/Ib/II/III/IV/V (e.g. G2V)"
                return True
            self._link_entry_name_prompt_result(created.get("id"), context)
            self._close_entry_name_prompt()
            return True

        if mode == "new_entry" or template is None:
            self.pending_new_entry_name = entry_name
            context = dict(prompt.get("context") or {})
            self._close_entry_name_prompt()
            self.schema_entry_templates = self._load_schema_entry_templates()
            self.template_picker_mode = "create"
            self.template_picker_context = context
            self.template_picker_search_query = ""
            self.template_picker_search_active = True
            self.show_template_picker = True
            self.template_picker_scroll = 0
            self.template_picker_status = f"Choose type for {entry_name}"
            self._build_template_picker_hitboxes()
            return True

        if self._is_star_system_template(template):
            context = dict(prompt.get("context") or {})
            self._close_entry_name_prompt()
            return self._open_entry_name_prompt(
                template,
                mode="star_system_class",
                context={"system_name": entry_name, **context},
                label=f"Star Class for {entry_name}",
            )

        context = dict(prompt.get("context") or {})
        self._close_entry_name_prompt()
        return self._open_entry_description_prompt(template, entry_name, context=context)

    def _handle_entry_name_prompt_keydown(self, event):
        return self._entry_name_prompt_controller()._handle_entry_name_prompt_keydown(event)

    def _handle_entry_name_prompt_click(self, mouse_pos):
        return self._entry_name_prompt_controller()._handle_entry_name_prompt_click(mouse_pos)
    def _create_new_entry_from_template(self, template):
        entry_name = str(self.pending_new_entry_name or "").strip()
        if entry_name:
            context = dict(self.template_picker_context or {})
            self.pending_new_entry_name = None
            if self._is_star_system_template(template):
                self.show_template_picker = False
                self.template_picker_status = ""
                self.template_picker_mode = "create"
                self.template_picker_context = {}
                self._build_template_picker_hitboxes()
                return self._open_entry_name_prompt(
                    template,
                    mode="star_system_class",
                    context={"system_name": entry_name, **context},
                    label=f"Star Class for {entry_name}",
                )
            self.show_template_picker = False
            self.template_picker_status = ""
            self.template_picker_mode = "create"
            self.template_picker_context = {}
            self._build_template_picker_hitboxes()
            return self._open_entry_description_prompt(template, entry_name, context=context)
        if self._is_star_system_template(template):
            return self._open_entry_name_prompt(template, label="System Name")
        return self._open_entry_name_prompt(template)

    def _open_card_class_template_picker(self, card):
        if not isinstance(card, dict) or not card.get("is_edit_mode", False):
            return False
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
            if not card.get("is_edit_mode", False):
                self.template_picker_status = "Edit mode required"
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

        entity_type = str(entity.get("type") or "").strip()
        dataset_name = str(entity.get("_dataset") or entity_type or "entity").strip()
        class_key = entity_type or self._singularize_name(dataset_name) or dataset_name
        subclass_value = self._entity_subclass_value(entity, dataset_name, class_key)
        class_label = self._schema_display_label(class_key)
        if subclass_value:
            return f"{class_label} | {self._schema_display_label(subclass_value)}"
        return class_label

    def _entity_subclass_value(self, entity, dataset_name, class_key):
        if dataset_name == "locations":
            return entity.get("location_class")
        if dataset_name == "systems":
            if entity.get("system_role") == "star_system":
                return entity.get("system_class")
            if entity.get("system_role") == "orbital_body":
                return entity.get("body_class")
            return entity.get("system_class") or entity.get("body_class")

        candidate_fields = [
            f"{self._singularize_name(dataset_name)}_class",
            f"{class_key}_class",
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
            "person_class",
        ]
        for field_key in candidate_fields:
            value = entity.get(field_key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

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
        return self._repository_service()._remove_entity_from_dataset_index(
            dataset_name,
            entity_id,
            entity_obj,
        )

    def _dataset_name_for_entity(self, entity):
        return self._repository_service()._dataset_name_for_entity(entity)

    def _remove_entity_from_repository(self, dataset_name, entity_id):
        return self._repository_service()._remove_entity_from_repository(
            dataset_name,
            entity_id,
        )

    def _delete_card_entry(self, card):
        return self._repository_service()._delete_card_entry(card)
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

        related = converted.get("related")
        if not isinstance(related, list):
            related = []
        if old_id not in related:
            related.append(old_id)
        converted["related"] = related

        self._populate_required_schema_fields(converted, template)
        for field_key, value in self._template_initial_fields(template).items():
            if (
                field_key not in {"id", "_dataset", "pretty_name", "name", "type"}
                and converted.get(field_key) in (None, "", [])
            ):
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
        return parse_year(value)

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
                if field_key in {"id", "pretty_name", "name", "wiki_entry"}:
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

        for contemporary_id in self._contemporary_entity_ids(
            root_id,
            existing_ids=visited,
            limit=self.contemporary_spawn_count,
        ):
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

    def _persist_schema_card(self, card):
        if card.get("card_kind") != "schema":
            return False

        card_view = card.get("card_view")
        if card_view is not None and card.get("schema_active_field"):
            card_view.commit_edit_field(card)

        schema_name = card.get("schema_name")
        loader = getattr(self.world_model, "loader", None) if self.world_model is not None else None
        if not schema_name or loader is None or not hasattr(loader, "persist_entity"):
            card["schema_status"] = "No schema repository found"
            return False

        updated_schema = copy.deepcopy(card.get("schema_original", {}))
        updated_schema["schema"] = card.get("schema_schema_name") or updated_schema.get("schema") or schema_name
        if card.get("schema_extends") is not None:
            updated_schema["extends"] = card.get("schema_extends")
        updated_schema["fields"] = copy.deepcopy(card.get("schema_draft_fields", {}))

        schema_entity = {
            "id": f"schema_{schema_name}",
            "type": "schema",
            "_dataset": "schemas",
            "name": updated_schema.get("schema", schema_name),
            "pretty_name": self._schema_display_label(updated_schema.get("schema", schema_name)),
            **updated_schema,
        }
        if not loader.persist_entity(schema_entity):
            card["schema_status"] = "Save failed"
            return False

        self.schema_loader.load_schemas()
        self.schema_field_usage = self._build_schema_field_usage()

        refreshed_schema = self.schema_loader.schemas.get(schema_name, updated_schema)
        card["schema_original"] = copy.deepcopy(refreshed_schema)
        card["schema_draft_fields"] = copy.deepcopy(refreshed_schema.get("fields", {}))
        card["schema_schema_name"] = refreshed_schema.get("schema", schema_name)
        card["schema_extends"] = refreshed_schema.get("extends")
        card["schema_path"] = None
        card["schema_dirty"] = False
        card["schema_status"] = "Saved"
        card["subtitle"] = f"schema | {card.get('schema_extends') or 'root'}"
        card["card_view"] = SchemaCard(
            schema_name=schema_name,
            schema=refreshed_schema,
            schema_path=None,
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

    def _repository_service(self):
        service = getattr(self, "_knowledge_repository_service", None)
        if service is None:
            service = KnowledgeRepositoryService(self)
            self._knowledge_repository_service = service
        return service

    def _load_card_drafts(self):
        return self._repository_service()._load_card_drafts()

    def _write_card_drafts(self):
        return self._repository_service()._write_card_drafts()

    def _entity_for_card(self, card):
        return self._repository_service()._entity_for_card(card)

    def _draft_entity_snapshot(self, entity):
        return self._repository_service()._draft_entity_snapshot(entity)

    def _replace_entity_id_reference_value(self, value, old_entity_id, new_entity_id):
        return self._repository_service()._replace_entity_id_reference_value(
            value,
            old_entity_id,
            new_entity_id,
        )

    def _replace_entity_references(self, entity, old_entity_id, new_entity_id):
        return self._repository_service()._replace_entity_references(
            entity,
            old_entity_id,
            new_entity_id,
        )

    def _replace_draft_references(self, old_entity_id, new_entity_id):
        return self._repository_service()._replace_draft_references(
            old_entity_id,
            new_entity_id,
        )

    def _rewrite_entity_id_references(self, old_entity_id, new_entity_id, renamed_entity_id=None):
        return self._repository_service()._rewrite_entity_id_references(
            old_entity_id,
            new_entity_id,
            renamed_entity_id=renamed_entity_id,
        )

    def _save_card_draft(self, card):
        return self._repository_service()._save_card_draft(card)

    def _remove_card_draft(self, entity_id):
        return self._repository_service()._remove_card_draft(entity_id)

    def _apply_cached_draft_to_card(self, card):
        return self._repository_service()._apply_cached_draft_to_card(card)

    def _hydrate_draft_entities(self, world_model):
        return self._repository_service()._hydrate_draft_entities(world_model)

    def _persist_entity_to_repository(self, entity, previous_entity_id=None):
        return self._repository_service()._persist_entity_to_repository(
            entity,
            previous_entity_id=previous_entity_id,
        )

    def _sync_bidirectional_relations(self, persist=True):
        return self._repository_service()._sync_bidirectional_relations(persist=persist)

    def _persist_card_entity(self, card):
        return self._repository_service()._persist_card_entity(card)

    def _finalize_relation_picker_edit(self, card):
        action = card.get("last_edit_action")
        if action == "commit":
            self._persist_card_entity(card)
            related_update_ids = list(card.pop("location_related_entity_update_ids", []) or [])
            for related_entity_id in related_update_ids:
                related_entity = self.world_model.get_entity(related_entity_id) if self.world_model is not None else None
                if isinstance(related_entity, dict):
                    self._persist_entity_to_repository(related_entity)
            self._sync_bidirectional_relations(persist=True)
        elif action == "draft":
            self._save_card_draft(card)
        card["last_edit_action"] = None

    def _finalize_card_color_slider_edit(self, slider):
        if not isinstance(slider, dict):
            return False

        card = self._find_card_by_entity_id(slider.get("entity_id"))
        if card is None or card.get("is_temporary", False):
            return False
        if not card.get("pending_color_persist", False):
            return False

        if card.get("is_draft_entity", False):
            saved = self._save_card_draft(card)
        else:
            saved = self._persist_card_entity(card)
        if saved:
            card.pop("pending_color_persist", None)
        return saved

    def _entity_rgb_for_average(self, entity):
        if not isinstance(entity, dict):
            return None
        color_value = entity.get("card_color") or entity.get("wiki_link_color") or entity.get("display_color")
        if isinstance(color_value, (list, tuple)) and len(color_value) >= 3:
            try:
                return tuple(max(0, min(255, int(part))) for part in color_value[:3])
            except (TypeError, ValueError):
                return None
        color_text = str(color_value or "").strip()
        if color_text.startswith("#") and len(color_text) == 7:
            try:
                return (
                    int(color_text[1:3], 16),
                    int(color_text[3:5], 16),
                    int(color_text[5:7], 16),
                )
            except ValueError:
                return None
        return None

    def _entity_custom_rgb_for_average(self, entity, role="body"):
        if not isinstance(entity, dict):
            return None
        if entity.get("card_color_source") == "derived_offspring":
            return None
        role = str(role or "body").strip().lower()
        if role == "header":
            color_value = entity.get("card_header_color") or entity.get("card_color") or entity.get("wiki_link_color")
        elif role == "wiki_default":
            colors = entity.get("wiki_field_colors")
            colors = colors if isinstance(colors, dict) else {}
            color_value = colors.get("default") or entity.get("card_color") or entity.get("wiki_link_color")
        elif role == "wiki_alternate":
            colors = entity.get("wiki_field_colors")
            colors = colors if isinstance(colors, dict) else {}
            color_value = (
                colors.get("alternate")
                or colors.get("default")
                or entity.get("card_color")
                or entity.get("wiki_link_color")
            )
        else:
            color_value = entity.get("card_color") or entity.get("wiki_link_color")
        if isinstance(color_value, (list, tuple)) and len(color_value) >= 3:
            try:
                return tuple(max(0, min(255, int(part))) for part in color_value[:3])
            except (TypeError, ValueError):
                return None
        color_text = str(color_value or "").strip()
        if color_text.startswith("#") and len(color_text) == 7:
            try:
                return (
                    int(color_text[1:3], 16),
                    int(color_text[3:5], 16),
                    int(color_text[5:7], 16),
                )
            except ValueError:
                return None
        return None

    def _clade_offspring_ids(self, parent_id):
        if self.world_model is None or not parent_id:
            return []
        parent = self.world_model.get_entity(parent_id)
        offspring_ids = relation_ids(parent.get("offspring")) if isinstance(parent, dict) else []
        seen = set(offspring_ids)
        for entity in self.world_model.loader.entities.values():
            if not isinstance(entity, dict):
                continue
            entity_id = str(entity.get("id") or "").strip()
            if not entity_id or entity_id in seen:
                continue
            if parent_id in relation_ids(entity.get("parents")):
                offspring_ids.append(entity_id)
                seen.add(entity_id)
        return offspring_ids

    def _terminal_phylogeny_descendant_ids(self, clade_id):
        if self.world_model is None or not clade_id:
            return []
        graph = phylogeny_graph_context(self.world_model)

        def nested_offspring_ids(value):
            if value is None:
                return []
            if isinstance(value, str):
                text = value.strip()
                if not text:
                    return []
                if text.startswith("[") or text.startswith("{"):
                    try:
                        return nested_offspring_ids(ast.literal_eval(text))
                    except (ValueError, SyntaxError):
                        return [text] if text in graph.phylogeny_entities else []
                return [text] if text in graph.phylogeny_entities else []
            if isinstance(value, dict):
                ids = []
                child_id = str(value.get("id") or value.get("entity_id") or value.get("target") or "").strip()
                if child_id in graph.phylogeny_entities:
                    ids.append(child_id)
                ids.extend(nested_offspring_ids(value.get("offspring")))
                return ids
            if isinstance(value, (list, tuple, set)):
                ids = []
                for item in value:
                    for child_id in nested_offspring_ids(item):
                        if child_id not in ids:
                            ids.append(child_id)
                return ids
            return []

        def child_ids_for(entity_id):
            ids = []
            for child_id in graph.children_by_parent.get(entity_id, []):
                if child_id in graph.phylogeny_entities and child_id not in ids:
                    ids.append(child_id)
            entity = graph.phylogeny_entities.get(entity_id)
            if isinstance(entity, dict):
                for child_id in nested_offspring_ids(entity.get("offspring")):
                    if child_id in graph.phylogeny_entities and child_id not in ids:
                        ids.append(child_id)
            return ids

        terminal_ids = []
        seen = set()
        stack = child_ids_for(clade_id)
        while stack:
            descendant_id = str(stack.pop() or "").strip()
            if not descendant_id or descendant_id in seen:
                continue
            seen.add(descendant_id)
            child_ids = [child_id for child_id in child_ids_for(descendant_id) if child_id not in seen]
            if child_ids:
                stack.extend(child_ids)
            elif descendant_id in graph.phylogeny_entities:
                terminal_ids.append(descendant_id)
        return terminal_ids

    def _update_derived_clade_color(self, clade_id, persist=True, force=False):
        if self.world_model is None or not clade_id:
            return False
        clade = self.world_model.get_entity(clade_id)
        if not isinstance(clade, dict):
            return False
        if not (clade.get("_dataset") == "cladistics" or clade.get("type") == "cladistics"):
            return False
        if not force and clade.get("card_color") and clade.get("card_color_source") != "derived_offspring":
            return False

        colors = []
        for descendant_id in self._terminal_phylogeny_descendant_ids(clade_id):
            descendant = self.world_model.get_entity(descendant_id)
            rgb = self._entity_custom_rgb_for_average(descendant)
            if rgb is not None:
                colors.append(rgb)
        if not colors:
            return False

        average = tuple(round(sum(color[index] for color in colors) / len(colors)) for index in range(3))
        palette = {"card_color": self._rgb_to_hex(average)}
        for role, field_key in (
            ("header", "card_header_color"),
            ("wiki_default", "wiki_default"),
            ("wiki_alternate", "wiki_alternate"),
        ):
            role_colors = []
            for descendant_id in self._terminal_phylogeny_descendant_ids(clade_id):
                descendant = self.world_model.get_entity(descendant_id)
                rgb = self._entity_custom_rgb_for_average(descendant, role=role)
                if rgb is not None:
                    role_colors.append(rgb)
            if role_colors:
                role_average = tuple(
                    round(sum(color[index] for color in role_colors) / len(role_colors))
                    for index in range(3)
                )
                palette[field_key] = self._rgb_to_hex(role_average)

        existing_wiki_colors = clade.get("wiki_field_colors")
        existing_wiki_colors = existing_wiki_colors if isinstance(existing_wiki_colors, dict) else {}
        unchanged = (
            clade.get("card_color") == palette.get("card_color")
            and clade.get("card_header_color") == palette.get("card_header_color")
            and existing_wiki_colors.get("default") == palette.get("wiki_default")
            and existing_wiki_colors.get("alternate") == palette.get("wiki_alternate")
            and clade.get("card_color_source") == "derived_offspring"
        )
        if unchanged:
            return False
        clade["card_color"] = palette["card_color"]
        if palette.get("card_header_color"):
            clade["card_header_color"] = palette["card_header_color"]
        wiki_colors = clade.get("wiki_field_colors")
        if not isinstance(wiki_colors, dict):
            wiki_colors = {}
        if palette.get("wiki_default"):
            wiki_colors["default"] = palette["wiki_default"]
        if palette.get("wiki_alternate"):
            wiki_colors["alternate"] = palette["wiki_alternate"]
        if wiki_colors:
            clade["wiki_field_colors"] = wiki_colors
        clade["card_color_source"] = "derived_offspring"
        card = self._find_card_by_entity_id(clade_id)
        if card is not None and isinstance(card.get("card_view"), EntityCard):
            card["card_view"].entity = clade
        if persist:
            self._persist_entity_to_repository(clade)
        return True

    def _invalidate_phylogeny_views(self):
        if self.world_model is not None and hasattr(self.world_model, "_phylogeny_graph_context_cache"):
            self.world_model._phylogeny_graph_context_cache = None
        self.relation_tree_neighbor_cache = {}
        self.canvas_relation_edges = []

    def _add_phylogeny_offspring_reference(self, parent_entity, child_id):
        if not isinstance(parent_entity, dict) or not child_id:
            return False
        existing = relation_ids(parent_entity.get("offspring"))
        if child_id in existing:
            parent_entity["offspring"] = existing
            return False
        existing.append(child_id)
        parent_entity["offspring"] = existing
        return True

    def _sync_stellar_class_profile(self, card, entity):
        committed_field = card.get("last_committed_field")
        if committed_field not in {"star_class", "spectral_class"}:
            return False

        location_class = str(entity.get("location_class") or entity.get("body_class") or "").strip().lower()
        if location_class not in {"star", "star_system"}:
            return False

        class_text = entity.get(committed_field) or entity.get("spectral_class") or entity.get("star_class")
        from simulations.space.stellar import is_valid_stellar_class, stellar_profile_for_class

        if not class_text or not is_valid_stellar_class(class_text):
            return False

        profile = stellar_profile_for_class(class_text)
        entity["star_class"] = profile.get("star_class")
        entity["spectral_class"] = profile.get("spectral_class", profile.get("class_key"))
        entity["luminosity_solar"] = profile.get("luminosity_solar")
        entity["habitable_zone_inner_au"] = profile.get("habitable_zone_inner_au")
        entity["habitable_zone_outer_au"] = profile.get("habitable_zone_outer_au")
        entity["card_color"] = profile.get("card_color")

        if location_class == "star":
            entity["display_color"] = list(profile.get("display_color", []))
            entity["mass_kg"] = profile.get("mass_kg")
            entity["radius_m"] = profile.get("radius_m")

        return True

    def _build_canonical_illustration_path(self, illustration_id, source_path):
        _, ext = os.path.splitext(source_path)
        ext = ext.lower() if ext else ".png"
        safe_id = self._sanitize_entity_id(illustration_id) or "illustration"
        rel_path = os.path.join("assets", "illustrations", f"{safe_id}{ext}")
        return rel_path.replace("\\", "/")

    def _copy_to_canonical_illustration_asset(self, illustration_id, source_path):
        canonical_rel_path = self._build_canonical_illustration_path(illustration_id, source_path)
        canonical_abs_path = os.path.normpath(str(self.PROJECT_ROOT / canonical_rel_path))
        os.makedirs(os.path.dirname(canonical_abs_path), exist_ok=True)
        shutil.copy2(source_path, canonical_abs_path)
        return canonical_rel_path

    def assign_illustration_image(self, illustration_id, image_path):
        if not illustration_id or not image_path or self.world_model is None:
            return False

        illustration = self.world_model.get_entity(illustration_id)
        if not isinstance(illustration, dict):
            return False

        if str(illustration.get("idea_class") or "").strip().lower() != "illustration":
            return False

        illustration["media_path"] = image_path
        self._persist_entity_to_repository(illustration)
        for card in self.cards:
            if card.get("entity_id") != illustration_id:
                continue
            card_view = card.get("card_view")
            if card_view is not None and isinstance(getattr(card_view, "entity", None), dict):
                card_view.entity["media_path"] = image_path
            card["is_draft_entity"] = False
            self._remove_card_draft(illustration_id)

        self.browser_items = self._build_browser_items(self.world_model)
        self._refresh_timeline_items()
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return True

    def choose_and_assign_illustration_image(self, illustration_id):
        image_path = self._open_image_file_dialog()
        if not image_path:
            return False

        canonical_path = self._copy_to_canonical_illustration_asset(illustration_id, image_path)
        return self.assign_illustration_image(illustration_id, canonical_path)

    def _parent_entity_for_illustration(self, illustration):
        if self.world_model is None or not isinstance(illustration, dict):
            return None
        parent_ids = illustration.get("parents")
        if isinstance(parent_ids, str):
            parent_ids = [parent_ids]
        if not isinstance(parent_ids, list):
            return None
        for parent_id in parent_ids:
            parent = self.world_model.get_entity(parent_id)
            if isinstance(parent, dict):
                return parent
        return None

    def _pixel_canvas_size_for_entity(self, entity, metric_size_m):
        metric_size_m = max(0.0, float(metric_size_m or 0.0))
        entity = entity if isinstance(entity, dict) else {}
        entity_type = str(entity.get("type") or entity.get("_dataset") or "").strip().lower()
        location_class = str(entity.get("location_class") or "").strip().lower()
        vehicle_class = str(entity.get("vehicle_class") or "").strip().lower()

        if location_class in {"planet", "moon", "star"}:
            return 128, 128
        if location_class in {"continent", "country", "state", "region"}:
            return 160, 120
        if location_class in {"city", "quarter", "site", "building"}:
            return 120, 80
        if vehicle_class or entity_type in {"vehicle", "vehicles"}:
            if metric_size_m <= 1.0:
                return 50, 50
            if metric_size_m <= 8:
                return 80, 50
            if metric_size_m <= 60:
                return 120, 60
            return 160, 80
        if metric_size_m <= 1.0:
            return 50, 50
        if metric_size_m <= 5.0:
            return 75, 75
        if metric_size_m <= 20.0:
            return 100, 100
        if metric_size_m <= 200.0:
            return 150, 150
        return 200, 200
    def _pixel_art_editor_controller(self):
        controller = getattr(self, "_pixel_art_editor_ui", None)
        if controller is None:
            controller = PixelArtEditorUI(self)
            self._pixel_art_editor_ui = controller
        return controller

    def _open_pixel_art_editor(self, illustration_id):
        return self._pixel_art_editor_controller().open(illustration_id)

    def _close_pixel_art_editor(self):
        return self._pixel_art_editor_controller().close()

    def _pixel_editor_metric_size(self):
        return self._pixel_art_editor_controller().metric_size()

    def _begin_pixel_art_canvas(self):
        return self._pixel_art_editor_controller().begin_canvas()

    def _set_pixel_editor_color_from_hsv(self, channel, value):
        return self._pixel_art_editor_controller().set_color_from_hsv(channel, value)

    def _set_pixel_editor_color_rgb(self, color):
        return self._pixel_art_editor_controller().set_color_rgb(color)

    def _set_pixel_editor_tool(self, tool):
        return self._pixel_art_editor_controller().set_tool(tool)

    def _set_pixel_editor_brush_size(self, brush_size):
        return self._pixel_art_editor_controller().set_brush_size(brush_size)

    def _clear_pixel_art_canvas(self):
        return self._pixel_art_editor_controller().clear_canvas()

    def _pixel_editor_set_slider_from_mouse(self, slider_info, mouse_x):
        return self._pixel_art_editor_controller().set_slider_from_mouse(slider_info, mouse_x)

    def _surface_from_image_bytes(self, data):
        return self._pixel_art_editor_controller().surface_from_image_bytes(data)

    def _load_pixel_reference_from_clipboard(self):
        return self._pixel_art_editor_controller().load_reference_from_clipboard()

    def _sample_pixel_reference_at(self, mouse_pos):
        return self._pixel_art_editor_controller().sample_reference_at(mouse_pos)

    def _paint_pixel_editor_at(self, mouse_pos):
        return self._pixel_art_editor_controller().paint_at(mouse_pos)

    def _pixel_art_asset_path(self, illustration_id):
        return self._pixel_art_editor_controller().asset_path(illustration_id)

    def _save_pixel_art_editor(self):
        return self._pixel_art_editor_controller().save()

    def _handle_pixel_art_editor_keydown(self, event):
        return self._pixel_art_editor_controller().handle_keydown(event)

    def _handle_pixel_art_editor_click(self, mouse_pos):
        return self._pixel_art_editor_controller().handle_click(mouse_pos)

    def _handle_pixel_art_editor_motion(self, mouse_pos):
        return self._pixel_art_editor_controller().handle_motion(mouse_pos)
    def _rebuild_browser_hitboxes(self):
        self.browser_hitboxes = []
        self.browser_toggle_hitboxes = []
        self.browser_filter_hitboxes = []

        if self.layout is None:
            return

        left_rect = self.layout["left_rect"]
        if self.browser_collapsed:
            self.browser_search_rect = None
            return

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

        if card.get("is_compact_canvas_card", False):
            self._draw_compact_card(screen, font, card)
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

    def _draw_compact_card(self, screen, font, card):
        rect = card.get("rect")
        if rect is None:
            return

        entity = self._entity_for_card(card)
        card_color = (32, 36, 48)
        if isinstance(entity, dict):
            card_color = self._coerce_hex_rgb(entity.get("card_color"), fallback=card_color)
        border = (210, 220, 240) if card.get("entity_id") == self.selected_entity_id else (112, 122, 146)
        pygame.draw.rect(screen, card_color, rect)
        pygame.draw.rect(screen, border, rect, 1)

        title = card.get("title") or card.get("entity_id") or "Card"
        subtitle = card.get("subtitle") or ""
        description = ""
        if isinstance(entity, dict):
            description = str(entity.get("three_word_description") or "").strip()
        title_surface = font.render(self._ellipsize_text(title, font, rect.width - 34), True, (244, 246, 250))
        description_surface = None
        if description:
            description_surface = font.render(self._ellipsize_text(description, font, rect.width - 18), True, (202, 210, 226))
        subtitle_surface = font.render(self._ellipsize_text(subtitle, font, rect.width - 18), True, (178, 188, 206))
        screen.blit(title_surface, (rect.x + 8, rect.y + 8))
        if description_surface is not None:
            screen.blit(description_surface, (rect.x + 8, rect.y + 28))
        subtitle_y = rect.y + (48 if description else 28)
        screen.blit(subtitle_surface, (rect.x + 8, subtitle_y))

        years = card.get("years", [])
        if years:
            year_text = str(years[0]) if len(years) == 1 else f"{years[0]}-{years[-1]}"
        else:
            year_text = "year missing"
        year_surface = font.render(self._ellipsize_text(year_text, font, rect.width - 18), True, (206, 214, 230))
        year_y = rect.y + (68 if description else 48)
        if year_y + year_surface.get_height() <= rect.bottom - 6:
            screen.blit(year_surface, (rect.x + 8, year_y))

        close_rect = card.get("close_rect")
        if close_rect is not None:
            pygame.draw.rect(screen, (70, 44, 50), close_rect)
            pygame.draw.rect(screen, (190, 130, 140), close_rect, 1)
            close_surface = font.render("x", True, (250, 230, 234))
            screen.blit(close_surface, close_surface.get_rect(center=close_rect.center))

    def _card_visual_rect(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_card_visual_rect")(*args, **kwargs)

    def _graph_relation_entity_ids_for_card(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_graph_relation_entity_ids_for_card")(*args, **kwargs)

    def _rect_edge_point_toward(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_rect_edge_point_toward")(*args, **kwargs)

    def _draw_canvas_graph_line(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_draw_canvas_graph_line")(*args, **kwargs)

    def _rebuild_canvas_relation_edges(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_rebuild_canvas_relation_edges")(*args, **kwargs)

    def _draw_canvas_relation_lines(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_draw_canvas_relation_lines")(*args, **kwargs)

    def _draw_canvas_relation_target_highlights(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_draw_canvas_relation_target_highlights")(*args, **kwargs)

    def _draw_canvas_relation_control_for_card(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_draw_canvas_relation_control_for_card")(*args, **kwargs)

    def _draw_card_canvas(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_draw_card_canvas")(*args, **kwargs)
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
        if getattr(self, "pixel_art_editor", None) is not None:
            if self._handle_pixel_art_editor_keydown(event):
                return "__ui_consumed__"
            return None

        if getattr(self, "stellar_neighbourhood_prompt", None) is not None:
            if self._handle_stellar_neighbourhood_prompt_keydown(event):
                return "__ui_consumed__"
            return None

        if self.entry_name_prompt is not None:
            if self._handle_entry_name_prompt_keydown(event):
                return "__ui_consumed__"
            return None

        if self._handle_task_checklist_keydown(event):
            return "__ui_consumed__"

        if self._handle_phylogeny_parent_keydown(event):
            return "__ui_consumed__"

        if self._handle_template_picker_keydown(event):
            return "__ui_consumed__"

        timeline_ui = getattr(self, "timeline_ui", None)
        if timeline_ui is not None:
            timeline_action = timeline_ui.handle_keydown(event)
            if timeline_action is not None:
                self._apply_timeline_action(timeline_action)
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
                self._is_wiki_text_edit_field(card, card.get("active_edit_field"))
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
                self._finalize_relation_picker_edit(card)
                self._sync_card_years_from_entity(card)
                self._refresh_timeline_items()
                self._relayout_cards()
                return "__ui_consumed__"

            if card_view.handle_keydown(card, event):
                self._bring_card_to_front(index)
                pending_production_action_opened = self._open_pending_production_site_prompt(card)
                if not card_view.is_relation_edit_field(card.get("active_edit_field")):
                    self._close_relation_picker(card)
                action = card.get("last_edit_action")
                if action == "commit":
                    self._persist_card_entity(card)
                    self._sync_card_years_from_entity(card)
                    self._refresh_timeline_items()
                elif action == "cancel":
                    card["last_edit_action"] = None
                elif action == "draft":
                    self._save_card_draft(card)
                card["last_edit_action"] = None
                self._relayout_cards()
                if pending_production_action_opened:
                    return "__ui_consumed__"
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
                    self._is_wiki_text_edit_field(card, card.get("active_edit_field"))
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
                    self._finalize_relation_picker_edit(card)
                    self._sync_card_years_from_entity(card)
                    self._refresh_timeline_items()
                    self._relayout_cards()
                    return "__ui_consumed__"

                if card_view.handle_keydown(card, event):
                    self._bring_card_to_front(index)
                    pending_production_action_opened = self._open_pending_production_site_prompt(card)
                    if not card_view.is_relation_edit_field(card.get("active_edit_field")):
                        self._close_relation_picker(card)
                    action = card.get("last_edit_action")
                    if action == "commit":
                        self._persist_card_entity(card)
                        self._sync_card_years_from_entity(card)
                        self._refresh_timeline_items()
                    elif action == "cancel":
                        card["last_edit_action"] = None
                    elif action == "draft":
                        self._save_card_draft(card)
                    card["last_edit_action"] = None
                    self._relayout_cards()
                    if pending_production_action_opened:
                        return "__ui_consumed__"
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
            if self._scroll_phylogeny_parent_at(mouse_pos, event.y):
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

        if self.timeline_splitter_click_pending:
            should_toggle = self.timeline_splitter_pending_toggle
            self._clear_timeline_splitter_click()
            self.active_timeline_resize = False
            self.active_timeline_pan = False
            self.timeline_resize_start_mouse_y = None
            self.timeline_resize_start_height = None
            self.timeline_pan_last_mouse_x = None
            if should_toggle:
                self._toggle_timeline_collapsed()
            return "__ui_consumed__"

        self.active_timeline_resize = False
        self.active_timeline_pan = False
        self.timeline_resize_start_mouse_y = None
        self.timeline_resize_start_height = None
        self.timeline_pan_last_mouse_x = None
        active_color_slider = self.active_card_color_slider
        if active_color_slider is not None:
            self._finalize_card_color_slider_edit(active_color_slider)
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
        if self.timeline_splitter_click_pending:
            start_pos = self.timeline_splitter_pending_mouse_pos
            if start_pos is None:
                start_pos = event.pos
            moved_y = abs(event.pos[1] - start_pos[1])
            moved_x = abs(event.pos[0] - start_pos[0])
            if not self.timeline_collapsed and (moved_y >= 3 or moved_x >= 6):
                self._begin_timeline_resize(start_pos)
            else:
                return "__ui_consumed__"

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

        handle_rect = self.browser_collapse_handle_rect
        if handle_rect is not None and handle_rect.collidepoint(mouse_pos):
            self.browser_collapsed = not self.browser_collapsed
            if self.browser_collapsed:
                self.browser_search_active = False
            self._refresh_layout_geometry()
            return "__ui_consumed__"

        if self.browser_collapsed:
            return "__ui_consumed__"

        if (
            self.browser_period_filter_clear_rect is not None
            and self.browser_period_filter_clear_rect.collidepoint(mouse_pos)
        ):
            self._clear_browser_period_filter()
            return "__ui_consumed__"

        if self.browser_search_rect is not None and self.browser_search_rect.collidepoint(mouse_pos):
            self.browser_search_active = True
            self.browser_collapsed = False
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

    def _insert_relation_reference_into_card(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_insert_relation_reference_into_card")(*args, **kwargs)

    def _remove_relation_reference_from_card(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_remove_relation_reference_from_card")(*args, **kwargs)

    def _find_card_by_entity_id(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_find_card_by_entity_id")(*args, **kwargs)

    def _begin_canvas_relation_link(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_begin_canvas_relation_link")(*args, **kwargs)

    def _clear_canvas_relation_link(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_clear_canvas_relation_link")(*args, **kwargs)

    def _link_canvas_relation_cards(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_link_canvas_relation_cards")(*args, **kwargs)

    def _handle_canvas_relation_target_click(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_handle_canvas_relation_target_click")(*args, **kwargs)

    def _clear_relation_browser_link(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_clear_relation_browser_link")(*args, **kwargs)

    def _finish_relation_browser_link(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_finish_relation_browser_link")(*args, **kwargs)

    def _handle_relation_link_mode_click(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_handle_relation_link_mode_click")(*args, **kwargs)

    def _begin_relation_browser_link(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_begin_relation_browser_link")(*args, **kwargs)

    def _handle_relation_card_link_target_click(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_handle_relation_card_link_target_click")(*args, **kwargs)

    def _link_relation_from_browser_entity(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_link_relation_from_browser_entity")(*args, **kwargs)

    def _create_relation_target_entity(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_create_relation_target_entity")(*args, **kwargs)

    def _open_relation_target_template_picker(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_open_relation_target_template_picker")(*args, **kwargs)

    def _replace_relation_reference_on_card(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_replace_relation_reference_on_card")(*args, **kwargs)

    def _create_relation_target_from_template_picker(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_create_relation_target_from_template_picker")(*args, **kwargs)
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
                "field_key": "related",
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

        if kind == "create":
            opened = self._open_entry_name_prompt(
                None,
                mode="new_entry",
                context={
                    "link_source_entity_id": card.get("entity_id"),
                    "link_field_key": relation_info.get("field_key") or "related",
                },
            )
            if opened:
                self._relayout_cards()
            return opened

        if kind == "missing" and relation_info.get("field_key") == "related":
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

    def _is_cladistics_card_obj(self, card):
        entity = self._entity_for_card(card)
        return isinstance(entity, dict) and (
            entity.get("_dataset") == "cladistics"
            or entity.get("type") == "cladistics"
        )

    def _is_phylogeny_card_obj(self, card):
        entity = self._entity_for_card(card)
        return isinstance(entity, dict) and (
            entity.get("_dataset") in {"cladistics", "species"}
            or entity.get("type") in {"cladistics", "species"}
        )

    def _active_phylogeny_parent_card(self):
        for card in reversed(self.cards):
            card_view = card.get("card_view")
            if (
                card.get("phylogeny_parent_input_active")
                and card_view is not None
                and getattr(card_view, "_is_phylogeny_mode", lambda: False)()
            ):
                return card
        return None

    def _active_phylogeny_child_card(self):
        for card in reversed(self.cards):
            card_view = card.get("card_view")
            if (
                card.get("phylogeny_child_input_active")
                and card_view is not None
                and getattr(card_view, "_is_phylogeny_mode", lambda: False)()
            ):
                return card
        return None

    def _clade_is_descendant_of(self, candidate_id, ancestor_id):
        if not candidate_id or not ancestor_id or self.world_model is None:
            return False
        if candidate_id == ancestor_id:
            return True
        entity = self.world_model.get_entity(candidate_id)
        seen = set()
        stack = list(relation_ids(entity.get("offspring") if isinstance(entity, dict) else []))
        while stack:
            child_id = stack.pop()
            if child_id in seen:
                continue
            if child_id == ancestor_id:
                return True
            seen.add(child_id)
            child = self.world_model.get_entity(child_id)
            if isinstance(child, dict):
                stack.extend(relation_ids(child.get("offspring")))
        return False

    def _create_clade_from_name(self, name):
        name = str(name or "").strip()
        if not name or self.world_model is None:
            return None
        requested_id = clade_id_from_name(name)
        entity_id = self._unique_entity_id(requested_id)
        entity = {
            "id": entity_id,
            "pretty_name": name,
            "name": name,
            "type": "cladistics",
            "_dataset": "cladistics",
            "common_name": "",
            "binomial_name": "",
            "parents": [],
            "offspring": [],
        }
        self.world_model.loader.datasets.setdefault("cladistics", []).append(entity)
        self.world_model.loader.entities[entity_id] = entity
        self._persist_entity_to_repository(entity)
        return entity

    def _add_phylogeny_parent_to_card(self, card, parent_entity):
        target_id = str(card.get("phylogeny_parent_target_id") or card.get("entity_id") or "").strip()
        child = self.world_model.get_entity(target_id) if self.world_model is not None else self._entity_for_card(card)
        if not isinstance(child, dict) or not isinstance(parent_entity, dict):
            return False

        child_id = str(child.get("id") or "").strip()
        parent_id = str(parent_entity.get("id") or "").strip()
        if not child_id or not parent_id or child_id == parent_id:
            card["phylogeny_status"] = "Choose a different parent clade"
            return False
        if self._clade_is_descendant_of(child_id, parent_id):
            card["phylogeny_status"] = "That would create a loop in the tree"
            return False

        parents = relation_ids(child.get("parents"))
        if parent_id not in parents:
            parents.append(parent_id)
        child["parents"] = parents
        parent_changed = self._add_phylogeny_offspring_reference(parent_entity, child_id)

        target_card = self._find_card_by_entity_id(child_id)
        if target_card is not None:
            self._persist_card_entity(target_card)
        else:
            self._persist_entity_to_repository(child)
        if parent_changed:
            self._persist_entity_to_repository(parent_entity)
        self._update_derived_clade_color(parent_id, persist=True)
        self._invalidate_phylogeny_views()
        card["phylogeny_parent_query"] = ""
        card["phylogeny_parent_matches"] = []
        card["phylogeny_parent_selected_index"] = 0
        card["phylogeny_parent_input_active"] = False
        card["phylogeny_status"] = f"Added parent {clade_label(parent_entity, parent_id)} to {clade_label(child, child_id)}"
        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return True

    def _confirm_phylogeny_parent_input(self, card, match_index=None):
        if not self._is_phylogeny_card_obj(card):
            return False

        query = str(card.get("phylogeny_parent_query") or "").strip()
        if not query:
            card["phylogeny_parent_input_active"] = False
            self._relayout_cards()
            return True

        matches = find_clade_matches(self.world_model, query)
        card["phylogeny_parent_matches"] = matches
        if match_index is None:
            match_index = card.get("phylogeny_parent_selected_index", 0)

        parent_entity = None
        if matches and isinstance(match_index, int) and 0 <= match_index < len(matches):
            parent_entity = matches[match_index]
        else:
            parent_entity = self._create_clade_from_name(query)

        if parent_entity is None:
            card["phylogeny_status"] = "Could not create parent clade"
            self._relayout_cards()
            return True

        self._add_phylogeny_parent_to_card(card, parent_entity)
        return True

    def _add_phylogeny_child_to_card(self, card, child_entity):
        target_id = str(card.get("phylogeny_child_target_id") or card.get("entity_id") or "").strip()
        parent = self.world_model.get_entity(target_id) if self.world_model is not None else self._entity_for_card(card)
        if not isinstance(parent, dict) or not isinstance(child_entity, dict):
            return False
        if not (
            parent.get("_dataset") == "cladistics"
            or parent.get("type") == "cladistics"
        ):
            card["phylogeny_status"] = "Only clades can receive child entries"
            return False

        parent_id = str(parent.get("id") or "").strip()
        child_id = str(child_entity.get("id") or "").strip()
        if not parent_id or not child_id or parent_id == child_id:
            card["phylogeny_status"] = "Choose a different child entry"
            return False
        if self._clade_is_descendant_of(child_id, parent_id):
            card["phylogeny_status"] = "That would create a loop in the tree"
            return False

        parents = relation_ids(child_entity.get("parents"))
        if parent_id not in parents:
            parents.append(parent_id)
        child_entity["parents"] = parents
        parent_changed = self._add_phylogeny_offspring_reference(parent, child_id)

        child_card = self._find_card_by_entity_id(child_id)
        if child_card is not None:
            self._persist_card_entity(child_card)
        else:
            self._persist_entity_to_repository(child_entity)
        if parent_changed:
            self._persist_entity_to_repository(parent)
        self._update_derived_clade_color(parent_id, persist=True)
        self._invalidate_phylogeny_views()
        card["phylogeny_child_query"] = ""
        card["phylogeny_child_matches"] = []
        card["phylogeny_child_selected_index"] = 0
        card["phylogeny_child_input_active"] = False
        sibling_id = str(card.get("phylogeny_child_sibling_id") or "").strip()
        sibling = self.world_model.get_entity(sibling_id) if self.world_model is not None and sibling_id else None
        if sibling_id:
            card["phylogeny_status"] = f"Added sister {clade_label(child_entity, child_id)} beside {clade_label(sibling, sibling_id)}"
        else:
            card["phylogeny_status"] = f"Added child {clade_label(child_entity, child_id)} to {clade_label(parent, parent_id)}"
        self.browser_items = self._build_browser_items(self.world_model)
        self._rebuild_browser_hitboxes()
        self._relayout_cards()
        return True

    def _phylogeny_child_matches_for_card(self, card, query):
        parent_id = str(card.get("phylogeny_child_target_id") or "").strip()
        sibling_id = str(card.get("phylogeny_child_sibling_id") or "").strip()
        excluded_ids = {entity_id for entity_id in (parent_id, sibling_id) if entity_id}
        return [
            match for match in find_clade_matches(self.world_model, query)
            if str(match.get("id") or "").strip() not in excluded_ids
        ]

    def _confirm_phylogeny_child_input(self, card, match_index=None):
        if not self._is_cladistics_card_obj(card):
            return False

        query = str(card.get("phylogeny_child_query") or "").strip()
        if not query:
            card["phylogeny_child_input_active"] = False
            self._relayout_cards()
            return True

        matches = self._phylogeny_child_matches_for_card(card, query)
        card["phylogeny_child_matches"] = matches
        if match_index is None:
            match_index = card.get("phylogeny_child_selected_index", 0)

        child_entity = None
        if matches and isinstance(match_index, int) and 0 <= match_index < len(matches):
            child_entity = matches[match_index]
        else:
            child_entity = self._create_clade_from_name(query)

        if child_entity is None:
            card["phylogeny_status"] = "Could not create sister clade"
            self._relayout_cards()
            return True

        return self._add_phylogeny_child_to_card(card, child_entity)

    def _handle_phylogeny_parent_keydown(self, event):
        child_card = self._active_phylogeny_child_card()
        if child_card is not None:
            query = str(child_card.get("phylogeny_child_query") or "")
            matches = child_card.get("phylogeny_child_matches") or []
            if event.key == pygame.K_ESCAPE:
                child_card["phylogeny_child_input_active"] = False
                child_card["phylogeny_status"] = ""
                self._relayout_cards()
                return True
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self._confirm_phylogeny_child_input(child_card)
            if event.key == pygame.K_UP and matches:
                child_card["phylogeny_child_selected_index"] = max(0, int(child_card.get("phylogeny_child_selected_index", 0)) - 1)
                self._relayout_cards()
                return True
            if event.key == pygame.K_DOWN and matches:
                child_card["phylogeny_child_selected_index"] = min(len(matches) - 1, int(child_card.get("phylogeny_child_selected_index", 0)) + 1)
                self._relayout_cards()
                return True
            if event.key == pygame.K_BACKSPACE:
                child_card["phylogeny_child_query"] = query[:-1]
                child_card["phylogeny_child_matches"] = self._phylogeny_child_matches_for_card(child_card, child_card["phylogeny_child_query"])
                child_card["phylogeny_child_selected_index"] = 0
                child_card["phylogeny_status"] = ""
                self._relayout_cards()
                return True
            text = getattr(event, "unicode", "")
            if text and text.isprintable():
                child_card["phylogeny_child_query"] = query + text
                child_card["phylogeny_child_matches"] = self._phylogeny_child_matches_for_card(child_card, child_card["phylogeny_child_query"])
                child_card["phylogeny_child_selected_index"] = 0
                child_card["phylogeny_status"] = ""
                self._relayout_cards()
                return True
            return True

        card = self._active_phylogeny_parent_card()
        if card is None:
            return False

        query = str(card.get("phylogeny_parent_query") or "")
        matches = card.get("phylogeny_parent_matches") or []
        if event.key == pygame.K_ESCAPE:
            card["phylogeny_parent_input_active"] = False
            card["phylogeny_status"] = ""
            self._relayout_cards()
            return True
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            return self._confirm_phylogeny_parent_input(card)
        if event.key == pygame.K_UP and matches:
            card["phylogeny_parent_selected_index"] = max(0, int(card.get("phylogeny_parent_selected_index", 0)) - 1)
            self._relayout_cards()
            return True
        if event.key == pygame.K_DOWN and matches:
            card["phylogeny_parent_selected_index"] = min(len(matches) - 1, int(card.get("phylogeny_parent_selected_index", 0)) + 1)
            self._relayout_cards()
            return True
        if event.key == pygame.K_BACKSPACE:
            card["phylogeny_parent_query"] = query[:-1]
            card["phylogeny_parent_matches"] = find_clade_matches(self.world_model, card["phylogeny_parent_query"])
            card["phylogeny_parent_selected_index"] = 0
            card["phylogeny_status"] = ""
            self._relayout_cards()
            return True
        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            card["phylogeny_parent_query"] = query + text
            card["phylogeny_parent_matches"] = find_clade_matches(self.world_model, card["phylogeny_parent_query"])
            card["phylogeny_parent_selected_index"] = 0
            card["phylogeny_status"] = ""
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
            if self._is_wiki_text_edit_field(card_obj, field_key):
                card_obj["card_view"].set_edit_cursor_from_pos(card_obj, field_key, mouse_pos, self.font_for_layout)
            if self._is_temporal_field(field_key):
                self._set_timeline_edit_target(card_obj, field_key)
            else:
                self._clear_timeline_edit_target()
            if not self._is_wiki_text_edit_field(card_obj, field_key):
                self._close_wiki_link_picker(card_obj)
            if card_obj["card_view"].is_relation_edit_field(field_key):
                self._open_relation_picker(card_obj)
            else:
                self._close_relation_picker(card_obj)
            self._relayout_cards()
            return "__ui_consumed__"

        return None

    def _handle_card_canvas_click(self, *args, **kwargs):
        return getattr(self._canvas_controller(), "_handle_card_canvas_click")(*args, **kwargs)
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
        return self._entry_name_prompt_controller()._draw_entry_name_prompt(screen, font)
    def _draw_pixel_art_editor(self, screen, font):
        return self._pixel_art_editor_controller().draw(screen, font)
    def _draw_stellar_neighbourhood_prompt(self, screen, font):
        return self._stellar_neighbour_prompt_controller()._draw_stellar_neighbourhood_prompt(
            screen,
            font,
        )

    def _handle_stellar_neighbourhood_prompt_click(self, mouse_pos):
        return self._stellar_neighbour_prompt_controller()._handle_stellar_neighbourhood_prompt_click(
            mouse_pos
        )
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

        self.timeline_ui.set_rect(timeline_rect)
        self.timeline_ui.set_font(font)
        if not self.timeline_collapsed and timeline_rect.height > 0:
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
        toggle_rect = getattr(self, "timeline_splitter_toggle_rect", None)
        if toggle_rect is not None and toggle_rect.width > 0:
            toggle_fill = (46, 52, 70) if self.timeline_collapsed else (36, 42, 58)
            pygame.draw.rect(screen, toggle_fill, toggle_rect)
            pygame.draw.rect(screen, (150, 160, 182), toggle_rect, 1)
            toggle_bar_half_w = max(8, min(grip_half_w, toggle_rect.width // 2 - 8))
            for offset in (-2, 2):
                pygame.draw.line(
                    screen,
                    (226, 232, 244),
                    (toggle_rect.centerx - toggle_bar_half_w, toggle_rect.centery + offset),
                    (toggle_rect.centerx + toggle_bar_half_w, toggle_rect.centery + offset),
                    1,
                )

        pygame.draw.rect(screen, (12, 12, 20), left_rect)
        pygame.draw.rect(screen, (200, 200, 200), left_rect, 1)

        pygame.draw.rect(screen, (12, 16, 28), right_rect)
        pygame.draw.rect(screen, (200, 200, 200), right_rect, 1)

        left_title = font.render("Repository Browser", True, (240, 240, 240))
        right_title = font.render("Card Canvas", True, (240, 240, 240))
        if not self.browser_collapsed:
            screen.blit(left_title, (left_rect.x + 12, left_rect.y + 10))
        screen.blit(right_title, (right_rect.x + 12, right_rect.y + 10))

        handle_rect = self.browser_collapse_handle_rect
        if handle_rect is not None:
            handle_fill = (42, 48, 62) if self.browser_collapsed else (34, 40, 52)
            pygame.draw.rect(screen, handle_fill, handle_rect)
            pygame.draw.rect(screen, (150, 160, 182), handle_rect, 1)
            handle_text = font.render("||", True, (226, 232, 244))
            screen.blit(handle_text, handle_text.get_rect(center=handle_rect.center))

        if self.relation_link_target is not None and not self.browser_collapsed:
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

        self.browser_period_filter_clear_rect = None
        if self.browser_period_filter is not None and not self.browser_collapsed:
            period_y = left_rect.y + 32 + (24 if self.relation_link_target is not None else 0)
            period_rect = pygame.Rect(left_rect.x + 10, period_y, left_rect.width - 20, 22)
            clear_rect = pygame.Rect(period_rect.right - 24, period_rect.y + 3, 18, 16)
            self.browser_period_filter_clear_rect = clear_rect
            start_year, end_year = self.browser_period_filter
            pygame.draw.rect(screen, (42, 36, 26), period_rect)
            pygame.draw.rect(screen, (196, 164, 108), period_rect, 1)
            label = self._ellipsize_text(f"Period: {start_year} to {end_year}", font, period_rect.width - 40)
            screen.blit(font.render(label, True, (238, 214, 166)), (period_rect.x + 6, period_rect.y + 3))
            pygame.draw.rect(screen, (72, 48, 42), clear_rect)
            pygame.draw.rect(screen, (210, 150, 130), clear_rect, 1)
            clear_surface = font.render("x", True, (248, 228, 220))
            screen.blit(clear_surface, clear_surface.get_rect(center=clear_rect.center))
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
        if self.random_task_button is not None:
            draw_button_fn(screen, font, self.random_task_button)
        if self.new_entry_button is not None:
            draw_button_fn(screen, font, self.new_entry_button)
        if self.clear_canvas_button is not None:
            draw_button_fn(screen, font, self.clear_canvas_button)
        if self.contemporary_spawn_decrease_button is not None:
            draw_button_fn(screen, font, self.contemporary_spawn_decrease_button)
        if self.contemporary_spawn_value_button is not None:
            draw_button_fn(screen, font, self.contemporary_spawn_value_button)
        if self.contemporary_spawn_increase_button is not None:
            draw_button_fn(screen, font, self.contemporary_spawn_increase_button)
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

        for item in ([] if self.browser_collapsed else self.browser_items):
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
                depth = item.get("depth", 0)
                indent_px = depth * 18
                if item.get("location_group"):
                    color = (176, 188, 208)
                else:
                    color = (220, 220, 220)
                text_surface = font.render(item["text"], True, color)
                screen.blit(text_surface, (left_rect.x + 12 + indent_px, line_y + text_offset_y))

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
        self._draw_stellar_neighbourhood_prompt(screen, font)
        self._draw_pixel_art_editor(screen, font)

    def handle_event(self, event):
        if self.layout is None:
            return None

        timeline_rect = self.layout["timeline_rect"]
        timeline_splitter_rect = self.layout["timeline_splitter_rect"]
        left_rect = self.layout["left_rect"]
        right_rect = self.layout["right_rect"]

        if event.type == pygame.KEYDOWN:
            return self._handle_keydown_event(event)

        if getattr(self, "pixel_art_editor", None) is not None:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_pixel_art_editor_click(event.pos)
                return "__ui_consumed__"
            if event.type == pygame.MOUSEBUTTONUP:
                self.pixel_art_painting = False
                if isinstance(self.pixel_art_editor, dict):
                    self.pixel_art_editor["active_slider"] = None
                return "__ui_consumed__"
            if event.type == pygame.MOUSEMOTION:
                self._handle_pixel_art_editor_motion(event.pos)
                return "__ui_consumed__"
            if event.type == pygame.MOUSEWHEEL:
                return "__ui_consumed__"

        if getattr(self, "stellar_neighbourhood_prompt", None) is not None:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._handle_stellar_neighbourhood_prompt_click(event.pos):
                    return "__ui_consumed__"
            if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                return "__ui_consumed__"

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
                self._apply_timeline_action(timeline_action)
                return "__ui_consumed__"

            if self.timeline_edit_target is not None:
                picked_year = self.timeline_ui.pick_year_from_axis_pos(mouse_pos)
                if picked_year is not None:
                    self._apply_timeline_year_pick(picked_year)
                    return "__ui_consumed__"

            self.active_timeline_pan = True
            self.timeline_pan_last_mouse_x = mouse_pos[0]
            return "__ui_consumed__"

        if timeline_splitter_rect.collidepoint(mouse_pos):
            toggle_hit = (
                self.timeline_splitter_toggle_rect is not None
                and self.timeline_splitter_toggle_rect.collidepoint(mouse_pos)
            )
            self._begin_timeline_splitter_click(mouse_pos, toggle=toggle_hit)
            return "__ui_consumed__"

        if self.random_entry_button is not None and self.random_entry_button.rect.collidepoint(mouse_pos):
            self._create_random_entry_card()
            return "__ui_consumed__"

        if self.random_task_button is not None and self.random_task_button.rect.collidepoint(mouse_pos):
            self._create_random_task_card()
            return "__ui_consumed__"

        if self.new_entry_button is not None and self.new_entry_button.rect.collidepoint(mouse_pos):
            self._open_new_entry_name_prompt()
            return "__ui_consumed__"

        if self.clear_canvas_button is not None and self.clear_canvas_button.rect.collidepoint(mouse_pos):
            self._clear_card_canvas()
            return "__ui_consumed__"

        if (
            self.contemporary_spawn_decrease_button is not None
            and self.contemporary_spawn_decrease_button.rect.collidepoint(mouse_pos)
        ):
            self._set_contemporary_spawn_count(self.contemporary_spawn_count - 1)
            return "__ui_consumed__"

        if (
            self.contemporary_spawn_increase_button is not None
            and self.contemporary_spawn_increase_button.rect.collidepoint(mouse_pos)
        ):
            self._set_contemporary_spawn_count(self.contemporary_spawn_count + 1)
            return "__ui_consumed__"

        if (
            self.contemporary_spawn_value_button is not None
            and self.contemporary_spawn_value_button.rect.collidepoint(mouse_pos)
        ):
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

        left_result = self._handle_left_panel_click(mouse_pos, left_rect)
        if left_result is not None:
            return left_result

        return self._handle_card_canvas_click(mouse_pos, right_rect)
