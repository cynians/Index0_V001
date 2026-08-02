import math
import random
import re
from collections import deque

import pygame


class TimelineUI:
    """
    Reusable timeline band widget.

    Responsibilities:
    * receive prebuilt timeline items
    * compute a visible year range
    * assign readable non-overlapping lanes
    * draw major period bars, point events, and duration bars
    * support wheel-based zoom on the visible year range
    """

    HEADER_H = 84
    AXIS_H = 22
    PERIOD_FILTER_H = 10
    PERIOD_FILTER_GAP = 8
    COVERAGE_H = 8
    COVERAGE_GAP = 8
    PERIOD_H = 12
    PERIOD_GAP = 4
    ITEM_H = 14
    LANE_GAP = 4
    PERIOD_SECTION_GAP = 10
    LANE_PIXEL_GAP = 14
    TOP_PAD = 8
    BOTTOM_PAD = 8
    LEFT_PAD = 12
    RIGHT_PAD = 12

    def _query_matches_text(self, query, text):
        terms = [term for term in str(query or "").strip().casefold().split() if term]
        if not terms:
            return True
        haystack = str(text or "").casefold()
        return all(term in haystack for term in terms)
    FILTER_GROUPS = [
        ("general", "General", ["all", "open_canvas", "contemporary"]),
        ("locations", "Locations", ["locations"]),
        ("engineering", "Engineering", ["vehicles", "components", "technologies"]),
        ("human", "Human", ["pops", "people", "cultures", "factions", "institutions"]),
        ("material", "Material", ["items", "materials", "production", "producers"]),
        ("world", "World", ["systems", "species", "events", "formations", "spatial_features"]),
        ("ideas", "Ideas", ["ideas", "tasks", "behaviors", "cultural_aspects", "cladistics", "conflicts"]),
    ]
    DEFAULT_HIDDEN_DATASETS = {"animals", "cladistics", "species"}
    DEFAULT_HIDDEN_ENTITY_TYPES = {"animal", "animals", "cladistics", "species"}
    RELATION_CLUSTER_FIELDS = (
        "parents",
        "related",
        "offspring",
        "parent_entity",
        "parent_location",
        "parent_body",
        "predecessor",
        "predecessors",
        "successor",
        "successors",
        "constituents",
        "owner_entity",
    )

    ZOOM_IN_FACTOR = 0.80
    ZOOM_OUT_FACTOR = 1.25
    MIN_VIEW_SPAN_YEARS = 10
    AXIS_PICK_HALF_H = 10

    def __init__(self):
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.title = "Repository Timeline"
        self.items = []
        self._items_signature = ()
        self._entity_lookup_signature = ()
        self._available_filter_categories_cache = None
        self._filter_groups_cache = None
        self._layout_cache_key = None
        self._filter_hitbox_cache_key = None
        self._full_range_cache_key = None
        self._full_range_cache_value = None
        self._label_width_cache = {}
        self.period_layout_items = []
        self.layout_items = []
        self.coverage_segments = []
        self.coverage_max_density = 0
        self.layout_font = None
        self.active_category_filter = "all"
        self.active_filter_group = "general"
        self.active_filter_groups = {"general"}
        self.active_filter_mode = "category"
        self.timeline_sort_mode = "relations"
        self.selected_year_filter_mode = "contemporary"
        self.open_canvas_entity_ids = set()
        self.filter_hitboxes = []
        self.filter_group_hitboxes = []
        self.sort_mode_hitboxes = []
        self.selected_year_filter_hitboxes = []
        self.period_filter_range = None
        self.period_filter_pending_start = None
        self.period_filter_rect = pygame.Rect(0, 0, 0, 0)
        self.picker_target_label = None
        self.picker_preview_year = None
        self.year_selection_enabled = False
        self.selected_year = None
        self.selected_year_context_label = None
        self.working_year_enabled = False
        self.working_year = None
        self.working_year_range = None
        self.working_year_buffer = ""
        self.working_year_active = False
        self.working_year_rect = pygame.Rect(0, 0, 0, 0)
        self.random_working_year_rect = pygame.Rect(0, 0, 0, 0)
        self.reset_working_year_rect = pygame.Rect(0, 0, 0, 0)
        self.location_focus_enabled = False
        self.location_focus_id = None
        self.location_focus_label = None
        self.location_focus_buffer = ""
        self.location_focus_active = False
        self.location_focus_invalid = False
        self.location_focus_rect = pygame.Rect(0, 0, 0, 0)
        self.random_location_focus_rect = pygame.Rect(0, 0, 0, 0)
        self.reset_location_focus_rect = pygame.Rect(0, 0, 0, 0)
        self.location_focus_matches = []
        self.location_focus_selected_index = 0
        self.location_focus_keyboard_active = False
        self.location_focus_suggestion_hitboxes = []
        self.entity_lookup = {}

        self.full_min_year = 0
        self.full_max_year = 1

        self.view_min_year = 0
        self.view_max_year = 1
        self._view_range_initialized = False

        self.period_lane_count = 0
        self.lane_count = 1
        self.relationship_cluster_lane_ranges = []
        self.vertical_scroll_px = 0
        self.content_rect = pygame.Rect(0, 0, 0, 0)
        self.axis_y = 0

    def set_rect(self, rect):
        rect = pygame.Rect(rect)
        changed = rect != self.rect
        self.rect = rect
        if changed:
            self._layout_cache_key = None
            self._filter_hitbox_cache_key = None
        return changed

    def set_font(self, font):
        changed = font is not self.layout_font
        self.layout_font = font
        if changed:
            self._layout_cache_key = None
            self._filter_hitbox_cache_key = None
            self._label_width_cache = {}
        return changed

    def set_title(self, title):
        self.title = str(title or "Timeline")

    def set_items(self, items):
        had_focus_item = self._items_have_default_focus_item(self.items)
        new_items = list(items or [])
        new_signature = self._make_items_signature(new_items)
        changed = new_signature != self._items_signature
        self.items = new_items
        self._items_signature = new_signature
        if changed:
            self._layout_cache_key = None
            self._filter_hitbox_cache_key = None
            self._available_filter_categories_cache = None
            self._filter_groups_cache = None
        has_focus_item = self._items_have_default_focus_item(self.items)
        if has_focus_item and not had_focus_item:
            self._view_range_initialized = False
        self._ensure_active_filter_valid()
        return changed

    def set_entity_lookup(self, entity_lookup):
        self.entity_lookup = {
            str(entity_id): entity
            for entity_id, entity in (entity_lookup or {}).items()
            if str(entity_id or "").strip() and isinstance(entity, dict)
        }
        signature = self._make_entity_lookup_signature(self.entity_lookup)
        changed = signature != self._entity_lookup_signature
        self._entity_lookup_signature = signature
        if changed:
            self._layout_cache_key = None
            self._filter_hitbox_cache_key = None
        self._refresh_location_focus_matches()
        return changed

    def set_open_canvas_entity_ids(self, entity_ids):
        open_ids = {
            str(entity_id)
            for entity_id in (entity_ids or [])
            if str(entity_id or "").strip()
        }
        changed = open_ids != self.open_canvas_entity_ids
        self.open_canvas_entity_ids = open_ids
        if changed:
            self._layout_cache_key = None
            self._filter_hitbox_cache_key = None
            self._ensure_active_filter_valid()
        return changed

    def _make_items_signature(self, items):
        return tuple(
            (
                item.get("entity_id"),
                item.get("timeline_kind"),
                item.get("dataset"),
                item.get("entity_type"),
                item.get("start_year"),
                item.get("end_year"),
                item.get("label"),
                item.get("card_color"),
                item.get("commentary"),
                item.get("start_commentary"),
                item.get("end_commentary"),
            )
            for item in items
            if isinstance(item, dict)
        )

    def _make_entity_lookup_signature(self, entity_lookup):
        relation_fields = (
            "id",
            "parents",
            "related",
            "parent_entity",
            "parent_location",
            "parent_body",
            "offspring",
            "constituents",
            "predecessor",
            "predecessors",
            "successor",
            "successors",
            "location_entity",
            "location",
            "locations",
            "associated_location",
            "associated_locations",
            "location_history",
            "place",
            "places",
            "owner_entity",
            "neighbours",
            "overlaps",
            "location_class",
            "type",
            "_dataset",
            "pretty_name",
            "name",
            "common_name",
            "short_name",
        )
        signature = []
        relation_field_names = {
            "parents",
            "related",
            "parent_entity",
            "parent_location",
            "parent_body",
            "offspring",
            "constituents",
            "predecessor",
            "predecessors",
            "successor",
            "successors",
            "location_entity",
            "location",
            "locations",
            "associated_location",
            "associated_locations",
            "location_history",
            "place",
            "places",
            "owner_entity",
            "neighbours",
            "overlaps",
        }
        for entity_id, entity in sorted(entity_lookup.items()):
            values = []
            for field_key in relation_fields:
                if field_key in relation_field_names:
                    values.append(tuple(self._relation_entity_ids(entity.get(field_key))))
                else:
                    values.append(entity.get(field_key))
            signature.append((entity_id, tuple(values)))
        return tuple(signature)

    def set_year_selection_enabled(self, enabled):
        self.year_selection_enabled = bool(enabled)

    def set_working_year_enabled(self, enabled):
        self.working_year_enabled = bool(enabled)
        if not self.working_year_enabled:
            self.working_year_active = False
            self.working_year_rect = pygame.Rect(0, 0, 0, 0)
            self.random_working_year_rect = pygame.Rect(0, 0, 0, 0)
            self.reset_working_year_rect = pygame.Rect(0, 0, 0, 0)

    def set_location_focus_enabled(self, enabled):
        self.location_focus_enabled = bool(enabled)
        if not self.location_focus_enabled:
            self.location_focus_active = False
            self.location_focus_rect = pygame.Rect(0, 0, 0, 0)
            self.random_location_focus_rect = pygame.Rect(0, 0, 0, 0)
            self.location_focus_suggestion_hitboxes = []

    def set_working_year(self, year, focus=False):
        old_year = self.working_year
        old_range = self.working_year_range
        if year is None or str(year).strip() == "":
            self.working_year = None
            self.working_year_range = None
            self.working_year_buffer = ""
            self.working_year_active = False
            if (
                (self.selected_year == old_year or old_range is not None)
                and str(self.selected_year_context_label or "").startswith("Working Year")
            ):
                self.selected_year = None
                self.selected_year_context_label = None
            self.rebuild_layout()
            return old_range is not None

        parsed_range = self._parse_working_year_value(year)
        if parsed_range is None:
            return False
        start_year, end_year = parsed_range

        changed = parsed_range != self.working_year_range
        self.working_year_range = parsed_range
        self.working_year = start_year if start_year == end_year else None
        self.working_year_buffer = self._format_working_year_range(parsed_range)
        self.working_year_active = False
        if self.working_year is not None:
            self.set_selected_year(
                self.working_year,
                context_label=f"Working Year {self.working_year}",
                focus=focus,
            )
        else:
            self.selected_year = None
            self.selected_year_context_label = None
            if focus:
                self.focus_year((start_year + end_year) // 2)
        self.rebuild_layout()
        return changed

    def get_working_year(self):
        return self.working_year

    def get_working_year_range(self):
        return self.working_year_range

    def set_location_focus(self, location_value):
        old_location_id = self.location_focus_id
        if location_value is None or str(location_value).strip() == "":
            self.location_focus_id = None
            self.location_focus_label = None
            self.location_focus_buffer = ""
            self.location_focus_active = False
            self.location_focus_invalid = False
            self.location_focus_matches = []
            self.location_focus_suggestion_hitboxes = []
            self.rebuild_layout()
            return old_location_id is not None

        resolved = self._resolve_location_focus(location_value)
        if resolved is None:
            self.location_focus_invalid = True
            return False

        location_id, location_label = resolved
        changed = location_id != self.location_focus_id
        self.location_focus_id = location_id
        self.location_focus_label = location_label
        self.location_focus_buffer = location_label
        self.location_focus_active = False
        self.location_focus_invalid = False
        self.location_focus_matches = []
        self.location_focus_suggestion_hitboxes = []
        self.rebuild_layout()
        return changed

    def get_location_focus(self):
        return self.location_focus_id

    def _resolve_location_focus(self, location_value):
        query = str(location_value or "").strip()
        if not query:
            return None
        query_folded = query.casefold()

        matches = self._build_location_focus_matches(query, limit=12)
        exact_matches = [
            match
            for match in matches
            if match["id"].casefold() == query_folded or str(match["label"]).casefold() == query_folded
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]["id"], exact_matches[0]["label"]
        if len(matches) == 1:
            return matches[0]["id"], matches[0]["label"]
        return None

    def _build_location_focus_matches(self, query_text, limit=7):
        query = str(query_text or "").strip().casefold()
        matches = []

        for entity_id, entity in self.entity_lookup.items():
            if not self._is_location_entity(entity):
                continue

            label = self._entity_display_label(entity, fallback=entity_id)
            location_class = str(entity.get("location_class") or entity.get("type") or "location")
            haystack = " ".join(
                [
                    str(entity_id),
                    str(label),
                    str(entity.get("pretty_name", "")),
                    str(entity.get("name", "")),
                    str(entity.get("short_name", "")),
                    str(location_class),
                ]
            ).casefold()
            if query and not self._query_matches_text(query, haystack):
                continue

            label_folded = str(label).casefold()
            id_folded = str(entity_id).casefold()
            if query and (label_folded == query or id_folded == query):
                rank = 0
            elif query and (label_folded.startswith(query) or id_folded.startswith(query)):
                rank = 1
            elif query:
                rank = 2
            else:
                rank = 3
            subtitle = f"{location_class.replace('_', ' ').title()} | {entity_id}"
            matches.append(
                {
                    "id": str(entity_id),
                    "label": str(label),
                    "subtitle": subtitle,
                    "rank": rank,
                    "card_color": entity.get("card_color", ""),
                }
            )

        matches.sort(key=lambda item: (item["rank"], item["label"].casefold(), item["id"]))
        return matches[:limit]

    def _refresh_location_focus_matches(self):
        if not self.location_focus_enabled or not self.location_focus_active:
            self.location_focus_matches = []
            self.location_focus_selected_index = 0
            self.location_focus_keyboard_active = False
            self.location_focus_suggestion_hitboxes = []
            return

        matches = self._build_location_focus_matches(self.location_focus_buffer)
        self.location_focus_matches = matches
        self.location_focus_suggestion_hitboxes = []
        if not matches:
            self.location_focus_selected_index = 0
            self.location_focus_keyboard_active = False
            return
        self.location_focus_selected_index = max(
            0,
            min(int(self.location_focus_selected_index or 0), len(matches) - 1),
        )

    def _select_location_focus_match(self, index=None):
        matches = self.location_focus_matches or []
        if not matches:
            return False
        if index is None:
            index = self.location_focus_selected_index
        index = max(0, min(int(index or 0), len(matches) - 1))
        match = matches[index]
        self.location_focus_selected_index = index
        self.location_focus_keyboard_active = False
        return self.set_location_focus(match.get("id"))

    @staticmethod
    def _parse_working_year_token(value):
        text = str(value or "").strip()
        match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(mya)?", text, flags=re.IGNORECASE)
        if match is None:
            return None
        number_text = match.group(1)
        try:
            if match.group(2):
                return -int(round(float(number_text) * 1_000_000))
            if "." in number_text:
                return None
            return int(number_text)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_working_year_value(value):
        text = str(value or "").strip()
        if "mya" in text.casefold():
            token_pattern = r"([+-]?\d+(?:\.\d+)?\s*(?:mya)?)"
            match = re.fullmatch(
                token_pattern + r"(?:\s*(?:-|–|—|to)\s*" + token_pattern + r")?",
                text,
                flags=re.IGNORECASE,
            )
            if match is None:
                return None
            start_year = TimelineUI._parse_working_year_token(match.group(1))
            end_year = TimelineUI._parse_working_year_token(match.group(2)) if match.group(2) is not None else start_year
            if start_year is None or end_year is None:
                return None
            return (min(start_year, end_year), max(start_year, end_year))
        match = re.fullmatch(r"([+-]?\d+)(?:\s*(?:-|–|—|to)\s*([+-]?\d+))?", text, flags=re.IGNORECASE)
        if match is None:
            return None

        start_year = int(match.group(1))
        end_year = int(match.group(2)) if match.group(2) is not None else start_year
        return (min(start_year, end_year), max(start_year, end_year))

    @staticmethod
    def _format_working_year_value(year):
        try:
            year = int(year)
        except (TypeError, ValueError):
            return ""
        if year <= -1_000_000 and year % 1_000_000 == 0:
            return f"{abs(year) // 1_000_000}MYA"
        return str(year)

    @staticmethod
    def _format_working_year_range(year_range):
        if year_range is None:
            return ""
        start_year, end_year = year_range
        if start_year == end_year:
            return TimelineUI._format_working_year_value(start_year)
        return (
            f"{TimelineUI._format_working_year_value(start_year)}"
            f" - {TimelineUI._format_working_year_value(end_year)}"
        )

    def set_selected_year(self, year, context_label=None, focus=False):
        if year is None:
            changed = self.selected_year is not None
            self.selected_year = None
            self.selected_year_context_label = None
            if changed:
                self.rebuild_layout()
            return changed

        try:
            year = int(year)
        except (TypeError, ValueError):
            return False

        changed = year != self.selected_year
        self.selected_year = year
        self.selected_year_context_label = context_label
        self._ensure_active_filter_valid()

        if focus:
            self.focus_year(year)
        elif changed:
            self.rebuild_layout()

        return changed

    def get_selected_year(self):
        return self.selected_year

    def set_active_category_filter(self, category_name):
        category_name = category_name or "all"
        if category_name not in self._available_filter_categories():
            category_name = "all"
        changed = category_name != self.active_category_filter or self.active_filter_mode != "category"
        self.active_category_filter = category_name
        self.active_filter_group = self._group_for_category(category_name) or self.active_filter_group
        self.active_filter_groups = {self.active_filter_group}
        self.active_filter_mode = "category"
        if changed:
            self.rebuild_layout()
        return changed

    def set_active_filter_group(self, group_id):
        available_groups = self.get_filter_groups()
        valid_group_ids = {available_group_id for available_group_id, _, _ in available_groups}
        if group_id not in valid_group_ids:
            group_id = available_groups[0][0] if available_groups else "general"

        changed = group_id != self.active_filter_group or self.active_filter_mode != "group" or self.active_filter_groups != {group_id}
        self.active_filter_group = group_id
        self.active_filter_groups = {group_id}
        self.active_filter_mode = "group"
        categories = self._categories_for_group(group_id)
        if categories and self.active_category_filter not in categories:
            self.active_category_filter = categories[0]
            changed = True
        if changed:
            self.rebuild_layout()
        return changed

    def toggle_active_filter_group(self, group_id):
        available_groups = self.get_filter_groups()
        valid_group_ids = {available_group_id for available_group_id, _, _ in available_groups}
        if group_id not in valid_group_ids:
            return False

        old_groups = set(self.active_filter_groups)
        if group_id == "general":
            self.active_filter_groups = {"general"}
        else:
            self.active_filter_groups.discard("general")
            if group_id in self.active_filter_groups:
                self.active_filter_groups.remove(group_id)
            else:
                self.active_filter_groups.add(group_id)
            if not self.active_filter_groups:
                self.active_filter_groups = {"general"}

        self.active_filter_group = sorted(self.active_filter_groups)[0]
        self.active_filter_mode = "group"
        categories = self._categories_for_group(self.active_filter_group)
        if categories and self.active_category_filter not in categories:
            self.active_category_filter = categories[0]

        changed = old_groups != self.active_filter_groups
        if changed:
            self.rebuild_layout()
        return changed

    def set_timeline_sort_mode(self, mode):
        mode = str(mode or "relations").strip().lower()
        if mode not in {"relations", "flat", "offspring"}:
            mode = "relations"
        changed = mode != self.timeline_sort_mode
        self.timeline_sort_mode = mode
        if changed:
            self.rebuild_layout()
        return changed

    def set_selected_year_filter_mode(self, mode):
        mode = str(mode or "contemporary").strip().lower()
        if mode not in {"contemporary", "near", "all"}:
            mode = "contemporary"
        changed = mode != self.selected_year_filter_mode
        self.selected_year_filter_mode = mode
        if changed:
            self.rebuild_layout()
        return changed

    def set_period_filter(self, start_year=None, end_year=None, pending_start=None):
        old_range = self.period_filter_range
        old_pending = self.period_filter_pending_start
        if start_year is None or end_year is None:
            self.period_filter_range = None
        else:
            start_year = int(start_year)
            end_year = int(end_year)
            self.period_filter_range = (min(start_year, end_year), max(start_year, end_year))
        self.period_filter_pending_start = None if pending_start is None else int(pending_start)
        return old_range != self.period_filter_range or old_pending != self.period_filter_pending_start

    def _available_filter_categories(self):
        if self._available_filter_categories_cache is not None:
            return set(self._available_filter_categories_cache)

        categories = {"all", "open_canvas", "contemporary"}
        for item in self.items:
            if item.get("timeline_kind") == "major_period":
                continue
            if self._item_hidden_by_default(item):
                continue
            dataset_name = item.get("dataset")
            if dataset_name:
                categories.add(str(dataset_name))

        self._available_filter_categories_cache = frozenset(categories)
        return categories

    def _group_for_category(self, category_name):
        for group_id, _, category_names in self.FILTER_GROUPS:
            if category_name in category_names:
                return group_id
        for group_id, _, category_names in self.get_filter_groups():
            if category_name in category_names:
                return group_id
        return "ideas"

    def get_filter_groups(self):
        if self._filter_groups_cache is not None:
            return list(self._filter_groups_cache)

        categories = self._available_filter_categories()
        groups = []
        assigned = set()
        for group_id, group_label, category_names in self.FILTER_GROUPS:
            group_categories = [name for name in category_names if name in categories]
            if group_categories:
                groups.append((group_id, group_label, group_categories))
                assigned.update(group_categories)

        remaining = sorted(name for name in categories if name not in assigned)
        if remaining:
            groups.append(("other", "Other", remaining))
        self._filter_groups_cache = tuple(
            (group_id, group_label, tuple(group_categories))
            for group_id, group_label, group_categories in groups
        )
        return groups

    def _categories_for_group(self, group_id):
        for available_group_id, _, categories in self.get_filter_groups():
            if available_group_id == group_id:
                return categories
        return []

    def get_filter_categories(self):
        groups = self.get_filter_groups()
        valid_group_ids = {group_id for group_id, _, _ in groups}
        if self.active_filter_group not in valid_group_ids:
            self.active_filter_group = groups[0][0] if groups else "general"
        self.active_filter_groups = {
            group_id for group_id in self.active_filter_groups if group_id in valid_group_ids
        } or {self.active_filter_group}

        for group_id, _, categories in groups:
            if group_id == self.active_filter_group:
                if self.active_filter_mode == "category" and self.active_category_filter not in categories:
                    self.active_category_filter = categories[0] if categories else "all"
                return categories

        return ["all"]

    def _ensure_active_filter_valid(self):
        categories = self._available_filter_categories()
        valid_group_ids = {group_id for group_id, _, _ in self.get_filter_groups()}
        if self.active_filter_mode == "group" and self.active_filter_group in valid_group_ids:
            self.active_filter_groups = {
                group_id for group_id in self.active_filter_groups if group_id in valid_group_ids
            } or {self.active_filter_group}
            group_categories = self._categories_for_group(self.active_filter_group)
            if group_categories and self.active_category_filter not in group_categories:
                self.active_category_filter = group_categories[0]
            return

        if self.active_category_filter not in categories:
            self.active_category_filter = "all"
            self.active_filter_mode = "category"

        self.active_filter_group = self._group_for_category(self.active_category_filter)
        self.active_filter_groups = {self.active_filter_group}
        self.active_filter_mode = "category"

    def set_picker_target(self, field_label=None, preview_year=None):
        self.picker_target_label = field_label
        self.picker_preview_year = preview_year

    def clear_picker_target(self):
        self.picker_target_label = None
        self.picker_preview_year = None

    def _format_filter_label(self, category_name):
        if category_name == "all":
            return "All"
        if category_name == "open_canvas":
            return "Open In Canvas"
        if category_name == "contemporary":
            return "Contemporary"
        return str(category_name).replace("_", " ").title()

    def _format_selected_year_label(self):
        if self.selected_year is None:
            return None

        if self.selected_year_context_label:
            return str(self.selected_year_context_label)

        return f"Selected {self.selected_year}"

    def _format_location_focus_display_value(self):
        if self.location_focus_active:
            return self.location_focus_buffer
        return self.location_focus_label or ""

    def _format_working_year_display_value(self):
        if self.working_year_active:
            return self.working_year_buffer
        return self._format_working_year_range(self.working_year_range)

    def _entity_display_label(self, entity, fallback=None):
        if not isinstance(entity, dict):
            return fallback or ""
        return str(
            entity.get("pretty_name")
            or entity.get("name")
            or entity.get("common_name")
            or entity.get("label")
            or fallback
            or entity.get("id")
            or ""
        )

    def _ellipsize_text(self, text, font, max_width):
        text = str(text or "")
        if font is None or font.size(text)[0] <= max_width:
            return text
        ellipsis = "..."
        if font.size(ellipsis)[0] > max_width:
            return ""
        while text and font.size(text + ellipsis)[0] > max_width:
            text = text[:-1]
        return text + ellipsis if text else ellipsis

    def _is_location_entity(self, entity):
        return isinstance(entity, dict) and (
            entity.get("_dataset") == "locations"
            or entity.get("type") == "location"
        )

    @staticmethod
    def _coerce_color(value, fallback):
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                return tuple(max(0, min(255, int(part))) for part in value[:3])
            except (TypeError, ValueError):
                return fallback
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
    def _mix_color(color, target, ratio):
        ratio = max(0.0, min(1.0, float(ratio)))
        return tuple(
            max(0, min(255, int(round(color[index] * (1.0 - ratio) + target[index] * ratio))))
            for index in range(3)
        )

    @staticmethod
    def _readable_text_color(background):
        red, green, blue = background[:3]
        luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
        return (18, 22, 30) if luminance >= 0.58 else (240, 244, 250)

    def _item_hidden_by_default(self, item):
        if item.get("timeline_kind") == "major_period":
            return False
        dataset_name = str(item.get("dataset") or "").strip().lower()
        entity_type = str(item.get("entity_type") or "").strip().lower()
        return (
            dataset_name in self.DEFAULT_HIDDEN_DATASETS
            or entity_type in self.DEFAULT_HIDDEN_ENTITY_TYPES
        )

    def _draw_selected_year_marker(self, screen):
        if self.selected_year is None or not self._year_is_in_view(self.selected_year):
            return

        selected_x = self._year_to_x(self.selected_year)
        pygame.draw.line(
            screen,
            (255, 220, 112),
            (selected_x, self.content_rect.y),
            (selected_x, self.rect.bottom - 10),
            2,
        )
        pygame.draw.polygon(
            screen,
            (255, 220, 112),
            [
                (selected_x, self.axis_y + 8),
                (selected_x - 5, self.axis_y + 16),
                (selected_x + 5, self.axis_y + 16),
            ],
        )

    def _filtered_visible_items(self):
        visible_items = self._location_focus_visible_items(
            self._working_year_visible_items(self._visible_items())
        )
        if self.active_filter_mode == "group":
            group_categories = set()
            for group_id in self.active_filter_groups:
                group_categories.update(self._categories_for_group(group_id))
            if "all" in group_categories:
                return visible_items

            filtered = []
            for item in visible_items:
                if item.get("timeline_kind") == "major_period":
                    filtered.append(item)
                    continue
                if item.get("dataset") in group_categories:
                    filtered.append(item)
            return filtered

        if self.active_category_filter == "all":
            return visible_items
        if self.active_category_filter == "open_canvas":
            return [
                item for item in visible_items
                if str(item.get("entity_id") or "") in self.open_canvas_entity_ids
            ]
        if self.active_category_filter == "contemporary":
            return self._contemporary_visible_items(visible_items)

        filtered = []
        for item in visible_items:
            if item.get("timeline_kind") == "major_period":
                filtered.append(item)
                continue
            if item.get("dataset") == self.active_category_filter:
                filtered.append(item)
        return filtered

    def _item_year_range(self, item):
        start_year = item.get("start_year")
        end_year = item.get("end_year")
        if start_year is None and end_year is None:
            return None
        if start_year is None:
            start_year = end_year
        if end_year is None:
            end_year = start_year
        return (min(start_year, end_year), max(start_year, end_year))

    def _item_extant_in_year(self, item, year):
        return self._item_extant_in_period(item, year, year)

    def _item_extant_in_period(self, item, filter_start_year, filter_end_year):
        start_year = item.get("raw_start_year", item.get("start_year"))
        end_year = item.get("raw_end_year", item.get("end_year"))
        if start_year is None and end_year is None:
            return False

        try:
            if start_year is not None:
                start_year = int(start_year)
            if end_year is not None:
                end_year = int(end_year)
            filter_start_year = int(filter_start_year)
            filter_end_year = int(filter_end_year)
        except (TypeError, ValueError):
            return False

        if filter_end_year < filter_start_year:
            filter_start_year, filter_end_year = filter_end_year, filter_start_year

        if start_year is None:
            return filter_start_year <= end_year
        if end_year is None:
            return start_year <= filter_end_year

        if end_year < start_year:
            start_year, end_year = end_year, start_year
        return start_year <= filter_end_year and end_year >= filter_start_year

    def _working_year_visible_items(self, visible_items):
        if self.selected_year is not None:
            if self.selected_year_filter_mode == "all":
                return visible_items
            if self.selected_year_filter_mode == "near":
                filter_start_year = self.selected_year - 10
                filter_end_year = self.selected_year + 10
            else:
                filter_start_year = self.selected_year
                filter_end_year = self.selected_year
        elif self.working_year_range is not None:
            filter_start_year, filter_end_year = self.working_year_range
        else:
            return visible_items
        return [
            item
            for item in visible_items
            if self._item_extant_in_period(item, filter_start_year, filter_end_year)
        ]

    def _random_working_year_candidates(self):
        ordinary_years = set()
        mya_buckets = set()
        geologic_cutoff = -1_000_000

        for item in self.items:
            if item.get("timeline_kind") == "major_period" or self._item_hidden_by_default(item):
                continue
            year_range = self._item_year_range(item)
            if year_range is None:
                continue

            start_year, end_year = year_range
            try:
                start_year = int(start_year)
                end_year = int(end_year)
            except (TypeError, ValueError):
                continue
            if end_year < start_year:
                start_year, end_year = end_year, start_year

            ordinary_start = max(start_year, geologic_cutoff + 1)
            ordinary_end = end_year
            if ordinary_start <= ordinary_end:
                ordinary_years.update(range(ordinary_start, ordinary_end + 1))

            geologic_start = start_year
            geologic_end = min(end_year, geologic_cutoff)
            if geologic_start <= geologic_end:
                oldest_bucket = int(math.ceil(abs(geologic_start) / 1_000_000))
                youngest_bucket = int(math.ceil(abs(geologic_end) / 1_000_000))
                mya_buckets.update(range(max(1, youngest_bucket), max(1, oldest_bucket) + 1))

        candidates = list(ordinary_years)
        candidates.extend(-bucket * 1_000_000 for bucket in mya_buckets)
        return candidates

    def _random_working_year_candidate_space(self):
        ordinary_ranges = []
        mya_buckets = set()
        geologic_cutoff = -1_000_000

        for item in self.items:
            if item.get("timeline_kind") == "major_period" or self._item_hidden_by_default(item):
                continue
            year_range = self._item_year_range(item)
            if year_range is None:
                continue

            start_year, end_year = year_range
            try:
                start_year = int(start_year)
                end_year = int(end_year)
            except (TypeError, ValueError):
                continue
            if end_year < start_year:
                start_year, end_year = end_year, start_year

            ordinary_start = max(start_year, geologic_cutoff + 1)
            ordinary_end = end_year
            if ordinary_start <= ordinary_end:
                ordinary_ranges.append((ordinary_start, ordinary_end))

            geologic_start = start_year
            geologic_end = min(end_year, geologic_cutoff)
            if geologic_start <= geologic_end:
                oldest_bucket = int(math.ceil(abs(geologic_start) / 1_000_000))
                youngest_bucket = int(math.ceil(abs(geologic_end) / 1_000_000))
                mya_buckets.update(range(max(1, youngest_bucket), max(1, oldest_bucket) + 1))

        ordinary_ranges = self._merge_year_ranges(ordinary_ranges)
        ordinary_total = sum(end_year - start_year + 1 for start_year, end_year in ordinary_ranges)
        return ordinary_ranges, sorted(mya_buckets), ordinary_total

    @staticmethod
    def _merge_year_ranges(ranges):
        normalized = sorted(
            (int(start_year), int(end_year))
            for start_year, end_year in ranges
            if start_year is not None and end_year is not None
        )
        merged = []
        for start_year, end_year in normalized:
            if end_year < start_year:
                start_year, end_year = end_year, start_year
            if not merged or start_year > merged[-1][1] + 1:
                merged.append([start_year, end_year])
            else:
                merged[-1][1] = max(merged[-1][1], end_year)
        return [(start_year, end_year) for start_year, end_year in merged]

    def _choose_random_working_year(self):
        ordinary_ranges, mya_buckets, ordinary_total = self._random_working_year_candidate_space()
        total_weight = ordinary_total + len(mya_buckets)
        if total_weight <= 0:
            return None

        pick_index = random.randrange(total_weight)
        if pick_index < ordinary_total:
            offset = pick_index
            for start_year, end_year in ordinary_ranges:
                span = end_year - start_year + 1
                if offset < span:
                    return start_year + offset
                offset -= span
            return ordinary_ranges[-1][1] if ordinary_ranges else None

        bucket_index = pick_index - ordinary_total
        return -mya_buckets[bucket_index] * 1_000_000 if bucket_index < len(mya_buckets) else None

    def set_random_working_year(self):
        picked_year = self._choose_random_working_year()
        if picked_year is None:
            return None
        changed = self.set_working_year(picked_year, focus=True)
        return {
            "kind": "random_working_year_changed",
            "year": self.working_year,
            "start_year": self.working_year_range[0] if self.working_year_range is not None else None,
            "end_year": self.working_year_range[1] if self.working_year_range is not None else None,
            "changed": changed,
        }

    def reset_working_year(self):
        changed = self.set_working_year(None)
        return {
            "kind": "working_year_reset",
            "year": None,
            "start_year": None,
            "end_year": None,
            "changed": changed,
        }

    def _random_extant_location_ids(self):
        filter_range = self.working_year_range
        if filter_range is None:
            return sorted(
                entity_id
                for entity_id, entity in self.entity_lookup.items()
                if self._is_location_entity(entity)
            )
        filter_start_year, filter_end_year = filter_range
        location_ids = set()
        for item in self.items:
            if item.get("timeline_kind") == "major_period":
                continue
            entity_id = str(item.get("entity_id") or "").strip()
            if not entity_id:
                continue
            entity = self.entity_lookup.get(entity_id)
            if not self._is_location_entity(entity):
                continue
            if self._item_extant_in_period(item, filter_start_year, filter_end_year):
                location_ids.add(entity_id)
        return sorted(location_ids)

    def set_random_location_focus(self):
        location_ids = self._random_extant_location_ids()
        if not location_ids:
            return None
        picked_location_id = random.choice(location_ids)
        changed = self.set_location_focus(picked_location_id)
        return {
            "kind": "random_location_focus_changed",
            "location_id": self.location_focus_id,
            "label": self.location_focus_label,
            "changed": changed,
        }

    def reset_location_focus(self):
        changed = self.set_location_focus(None)
        return {
            "kind": "location_focus_reset",
            "location_id": None,
            "label": None,
            "changed": changed,
        }

    def _relation_entity_ids(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = value.strip()
            return [value] if value else []
        if isinstance(value, dict):
            candidate = value.get("location_id") or value.get("id") or value.get("entity_id") or value.get("target")
            return [str(candidate)] if candidate else []
        if isinstance(value, (list, tuple, set)):
            ids = []
            for item in value:
                ids.extend(self._relation_entity_ids(item))
            return ids
        return []

    def _location_parent_ids(self, entity):
        if not isinstance(entity, dict):
            return []
        parent_ids = []
        entity_id = str(entity.get("id") or "")
        for field_key in ("parent_location", "parent_entity", "parent_body", "parents"):
            for parent_id in self._relation_entity_ids(entity.get(field_key)):
                parent_entity = self.entity_lookup.get(parent_id)
                if parent_id != entity_id and self._is_location_entity(parent_entity):
                    parent_ids.append(parent_id)
        for candidate_id, candidate in self.entity_lookup.items():
            if not self._is_location_entity(candidate):
                continue
            if candidate_id == entity_id:
                continue
            if entity_id in self._relation_entity_ids(candidate.get("constituents")):
                parent_ids.append(candidate_id)
        return parent_ids

    def _location_id_is_in_focus(self, location_id, focus_id=None, visited=None):
        if not location_id:
            return False
        location_id = str(location_id)
        focus_id = str(focus_id or self.location_focus_id or "")
        if not focus_id:
            return True
        if location_id == focus_id:
            return True

        if visited is None:
            visited = set()
        if location_id in visited:
            return False
        visited.add(location_id)

        location_entity = self.entity_lookup.get(location_id)
        if not self._is_location_entity(location_entity):
            return False
        return any(
            self._location_id_is_in_focus(parent_id, focus_id=focus_id, visited=visited)
            for parent_id in self._location_parent_ids(location_entity)
        )

    def _entity_location_reference_ids(self, entity):
        if not isinstance(entity, dict):
            return []

        reference_keys = (
            "location_entity",
            "location",
            "locations",
            "associated_location",
            "associated_locations",
            "location_history",
            "place",
            "places",
            "parent_location",
            "parent_entity",
            "parent_body",
            "owner_entity",
            "parents",
            "neighbours",
            "constituents",
            "overlaps",
        )
        location_ids = []
        for field_key in reference_keys:
            for candidate_id in self._relation_entity_ids(entity.get(field_key)):
                if self._is_location_entity(self.entity_lookup.get(candidate_id)):
                    location_ids.append(candidate_id)
        return location_ids

    def _entity_is_in_location_focus(self, entity_id):
        if self.location_focus_id is None:
            return True

        entity = self.entity_lookup.get(str(entity_id or ""))
        if not isinstance(entity, dict):
            return False

        if self._is_location_entity(entity):
            return self._location_id_is_in_focus(entity.get("id") or entity_id)

        return any(
            self._location_id_is_in_focus(location_id)
            for location_id in self._entity_location_reference_ids(entity)
        )

    def _location_focus_visible_items(self, visible_items):
        if self.location_focus_id is None:
            return visible_items
        return [
            item
            for item in visible_items
            if item.get("timeline_kind") == "major_period"
            or self._entity_is_in_location_focus(item.get("entity_id"))
        ]

    def _contemporary_visible_items(self, visible_items):
        if self.selected_year is not None:
            context_start = self.selected_year - 100
            context_end = self.selected_year + 100
            return [
                item for item in visible_items
                if item.get("timeline_kind") == "major_period"
                or (
                    (year_range := self._item_year_range(item)) is not None
                    and (
                        year_range[0] <= self.selected_year <= year_range[1]
                        or context_start <= year_range[0] <= context_end
                        or context_start <= year_range[1] <= context_end
                    )
                )
            ]

        open_ranges = []
        if self.open_canvas_entity_ids:
            for item in self.items:
                if str(item.get("entity_id") or "") not in self.open_canvas_entity_ids:
                    continue
                year_range = self._item_year_range(item)
                if year_range is not None:
                    open_ranges.append(year_range)

        if not open_ranges:
            return visible_items

        contemporary = []
        for item in visible_items:
            if item.get("timeline_kind") == "major_period":
                contemporary.append(item)
                continue
            year_range = self._item_year_range(item)
            if year_range is None:
                continue
            start_year, end_year = year_range
            if any(start_year <= open_end and end_year >= open_start for open_start, open_end in open_ranges):
                contemporary.append(item)
        return contemporary

    def _compute_full_range(self):
        cache_key = (self._items_signature, self.selected_year, self.working_year_range)
        if cache_key == self._full_range_cache_key and self._full_range_cache_value is not None:
            self.full_min_year, self.full_max_year = self._full_range_cache_value
            return

        if not self.items:
            self.full_min_year = 0
            self.full_max_year = 1
            self._full_range_cache_key = cache_key
            self._full_range_cache_value = (self.full_min_year, self.full_max_year)
            return

        years = []
        if self.selected_year is not None:
            years.append(self.selected_year)
        if self.working_year_range is not None:
            years.extend(self.working_year_range)

        for item in self.items:
            start = item.get("start_year")
            end = item.get("end_year")

            if start is not None:
                years.append(start)
            if end is not None:
                years.append(end)

        if not years:
            self.full_min_year = 0
            self.full_max_year = 1
            self._full_range_cache_key = cache_key
            self._full_range_cache_value = (self.full_min_year, self.full_max_year)
            return

        min_year = min(years)
        max_year = max(years)

        if min_year == max_year:
            self.full_min_year = min_year - 1
            self.full_max_year = max_year + 1
            self._full_range_cache_key = cache_key
            self._full_range_cache_value = (self.full_min_year, self.full_max_year)
            return

        padding = max(1, int((max_year - min_year) * 0.03))
        self.full_min_year = min_year - padding
        self.full_max_year = max_year + padding
        self._full_range_cache_key = cache_key
        self._full_range_cache_value = (self.full_min_year, self.full_max_year)

    def _ensure_view_range_initialized(self):
        current_span = self.view_max_year - self.view_min_year
        full_span = self.full_max_year - self.full_min_year

        if not self._view_range_initialized:
            self._initialize_view_range()
            self._view_range_initialized = True
            return

        if current_span <= 0:
            self.view_min_year = self.full_min_year
            self.view_max_year = self.full_max_year
            return

        if self.view_min_year < self.full_min_year:
            shift = self.full_min_year - self.view_min_year
            self.view_min_year += shift
            self.view_max_year += shift

        if self.view_max_year > self.full_max_year:
            shift = self.view_max_year - self.full_max_year
            self.view_min_year -= shift
            self.view_max_year -= shift

        if (self.view_max_year - self.view_min_year) > full_span:
            self.view_min_year = self.full_min_year
            self.view_max_year = self.full_max_year
            return

        if self.view_max_year - self.view_min_year < self.MIN_VIEW_SPAN_YEARS:
            center = (self.view_min_year + self.view_max_year) / 2.0
            half = self.MIN_VIEW_SPAN_YEARS / 2.0
            self.view_min_year = int(round(center - half))
            self.view_max_year = int(round(center + half))
            self._clamp_view_to_full()

    def _default_focus_year(self):
        if self.selected_year is not None:
            return self.selected_year

        for item in reversed(self.items):
            if item.get("timeline_kind") == "major_period":
                continue
            start_year = item.get("start_year")
            end_year = item.get("end_year")
            if start_year is not None:
                return int(start_year)
            if end_year is not None:
                return int(end_year)

        return None

    def _items_have_default_focus_item(self, items):
        for item in items or []:
            if item.get("timeline_kind") == "major_period":
                continue
            if item.get("start_year") is not None or item.get("end_year") is not None:
                return True
        return False

    def _initialize_view_range(self):
        full_span = self.full_max_year - self.full_min_year
        if full_span <= 0:
            self.view_min_year = self.full_min_year
            self.view_max_year = self.full_max_year
            return

        focus_year = self._default_focus_year()
        if focus_year is None:
            self.view_min_year = self.full_min_year
            self.view_max_year = self.full_max_year
            return

        view_span = max(self.MIN_VIEW_SPAN_YEARS, self.view_max_year - self.view_min_year)
        view_span = min(full_span, view_span)
        half_span = view_span / 2.0
        self.view_min_year = int(round(focus_year - half_span))
        self.view_max_year = self.view_min_year + int(round(view_span))
        self._clamp_view_to_full()

    def _clamp_view_to_full(self):
        full_span = self.full_max_year - self.full_min_year
        view_span = self.view_max_year - self.view_min_year

        if full_span <= 0:
            self.view_min_year = self.full_min_year
            self.view_max_year = self.full_max_year
            return

        if view_span >= full_span:
            self.view_min_year = self.full_min_year
            self.view_max_year = self.full_max_year
            return

        if self.view_min_year < self.full_min_year:
            shift = self.full_min_year - self.view_min_year
            self.view_min_year += shift
            self.view_max_year += shift

        if self.view_max_year > self.full_max_year:
            shift = self.view_max_year - self.full_max_year
            self.view_min_year -= shift
            self.view_max_year -= shift

    def reset_zoom(self):
        self.view_min_year = self.full_min_year
        self.view_max_year = self.full_max_year
        self.rebuild_layout()

    def _year_to_x(self, year):
        if self.content_rect.width <= 1:
            return self.content_rect.x

        span = max(1, self.view_max_year - self.view_min_year)
        t = (year - self.view_min_year) / span
        t = max(0.0, min(1.0, t))
        return self.content_rect.x + int(t * self.content_rect.width)

    def _year_is_in_view(self, year):
        if year is None:
            return False

        return self.view_min_year <= year <= self.view_max_year

    def _item_commentary_text(self, item):
        commentary = str(item.get("commentary") or "").strip()
        if commentary:
            return commentary
        parts = []
        for key, label in (("start_commentary", "Start"), ("end_commentary", "End")):
            text = str(item.get(key) or "").strip()
            if text:
                parts.append(f"{label}: {text}")
        return " / ".join(parts)

    def _show_item_commentary(self):
        return (self.view_max_year - self.view_min_year) <= 500

    def _lane_pitch(self):
        extra = 0
        if self._show_item_commentary():
            extra = max(0, (self.layout_font.get_linesize() if self.layout_font is not None else 14) - 2)
        return self.ITEM_H + self.LANE_GAP + extra

    def _nice_year_step(self, target_years):
        target_years = max(1.0, float(target_years))
        magnitude = 10 ** math.floor(math.log10(target_years))
        for multiplier in (1, 2, 5, 10):
            step = int(multiplier * magnitude)
            if step >= target_years:
                return max(1, step)
        return max(1, int(10 * magnitude))

    def _axis_tick_step(self, min_pixel_gap=72):
        span = max(1, self.view_max_year - self.view_min_year)
        content_w = max(1, self.content_rect.width)
        target_years = (span / float(content_w)) * min_pixel_gap
        return self._nice_year_step(target_years)

    def _axis_ticks(self, font=None):
        if self.content_rect.width <= 1:
            return []

        step = self._axis_tick_step()
        start = self.view_min_year
        end = self.view_max_year
        if end < start:
            start, end = end, start

        first_tick = int(math.ceil(start / float(step)) * step)
        years = {start, end}
        year = first_tick
        guard = 0
        while year <= end and guard < 1000:
            years.add(int(year))
            year += step
            guard += 1

        ticks = []
        for year in sorted(years):
            ticks.append(
                {
                    "year": int(year),
                    "x": self._year_to_x(year),
                    "is_endpoint": year in {start, end},
                }
            )

        if font is None:
            for tick in ticks:
                tick["label"] = str(tick["year"])
            return ticks

        placed_label_rects = []
        label_candidates = sorted(ticks, key=lambda tick: (0 if tick["is_endpoint"] else 1, tick["x"]))
        for tick in label_candidates:
            label = str(tick["year"])
            label_w, label_h = font.size(label)
            if tick["year"] == start:
                label_x = self.content_rect.x
            elif tick["year"] == end:
                label_x = self.content_rect.right - label_w
            else:
                label_x = tick["x"] - label_w // 2
                label_x = max(self.content_rect.x, min(label_x, self.content_rect.right - label_w))
            label_rect = pygame.Rect(label_x, self.content_rect.y, label_w, label_h)

            has_overlap = any(label_rect.inflate(8, 0).colliderect(existing) for existing in placed_label_rects)
            if has_overlap and not tick["is_endpoint"]:
                continue

            tick["label"] = label
            tick["label_rect"] = label_rect
            placed_label_rects.append(label_rect)

        return ticks

    def is_selected_year_marker_hit(self, mouse_pos, tolerance_px=8):
        if self.selected_year is None:
            return False

        if not self._year_is_in_view(self.selected_year):
            return False

        if not self.rect.collidepoint(mouse_pos):
            return False

        if mouse_pos[1] < self.content_rect.y or mouse_pos[1] > self.rect.bottom:
            return False

        selected_x = self._year_to_x(self.selected_year)
        return abs(int(mouse_pos[0]) - selected_x) <= int(tolerance_px)

    def _x_to_year(self, screen_x):
        if self.content_rect.width <= 1:
            return self.view_min_year

        clamped_x = max(self.content_rect.x, min(self.content_rect.right, screen_x))
        span = max(1, self.view_max_year - self.view_min_year)
        t = (clamped_x - self.content_rect.x) / self.content_rect.width
        return self.view_min_year + (t * span)

    def _visible_items(self):
        visible = []

        for item in self.items:
            if self._item_hidden_by_default(item):
                continue

            raw_start = item.get("start_year")
            raw_end = item.get("end_year")
            start = raw_start
            end = raw_end

            if start is None and end is None:
                continue

            if start is None:
                start = end
            if end is None:
                if self.working_year_range is not None:
                    end = max(start, self.working_year_range[1])
                else:
                    end = start

            if raw_start is None and self.working_year_range is not None:
                start = min(start, self.working_year_range[0])

            if end < start:
                start, end = end, start

            if end < self.view_min_year or start > self.view_max_year:
                continue

            visible.append(
                {
                    **item,
                    "raw_start_year": raw_start,
                    "raw_end_year": raw_end,
                    "start_year": start,
                    "end_year": end,
                }
            )

        return visible

    def _measure_label_width(self, label):
        label = str(label or "")

        if self.layout_font is not None:
            cache_key = (id(self.layout_font), label)
            cached_width = self._label_width_cache.get(cache_key)
            if cached_width is None:
                cached_width = self.layout_font.size(label)[0]
                self._label_width_cache[cache_key] = cached_width
            return cached_width

        return max(28, len(label) * 7)

    def _get_duration_label_x(self, x1, x2, label_width):
        axis_left = self.content_rect.x
        axis_right = self.content_rect.right
        bar_w = max(6, x2 - x1)

        if bar_w >= (label_width + 12):
            return x1 + 6

        preferred_x = x1 + bar_w + 8
        clamped_x = min(preferred_x, axis_right - label_width)
        return max(axis_left, clamped_x)

    def _get_item_horizontal_bounds(self, item):
        start_year = item["start_year"]
        end_year = item["end_year"]
        label = item.get("label", item.get("entity_id", "unknown"))

        x1 = self._year_to_x(start_year)
        x2 = self._year_to_x(end_year)
        label_w = self._measure_label_width(label)

        if item.get("timeline_kind") == "major_period":
            bar_right = x1 + max(8, x2 - x1)
            label_left = max(self.content_rect.x, min(x1 + 6, self.content_rect.right - label_w))
            return min(x1, label_left), max(bar_right, label_left + label_w)

        if start_year == end_year:
            return x1, max(x1 + 8 + label_w, x1 + 6)

        bar_right = x1 + max(6, x2 - x1)
        label_left = self._get_duration_label_x(x1, x2, label_w)
        return min(x1, label_left), max(bar_right, label_left + label_w)

    def _assign_items_to_lanes(self, items, allow_touching=False, preserve_order=False):
        layout_items = []
        sortable = list(items)
        if not preserve_order:
            sortable.sort(key=self._timeline_item_stable_key)

        lane_end_pixels = []

        for item in sortable:
            placed_lane = None
            item_left, item_right = self._get_item_horizontal_bounds(item)

            for lane_index, lane_end in enumerate(lane_end_pixels):
                can_share_lane = item_left > (lane_end + self.LANE_PIXEL_GAP)
                if allow_touching:
                    can_share_lane = item_left >= lane_end

                if can_share_lane:
                    placed_lane = lane_index
                    lane_end_pixels[lane_index] = item_right
                    break

            if placed_lane is None:
                placed_lane = len(lane_end_pixels)
                lane_end_pixels.append(item_right)

            layout_items.append(
                {
                    **item,
                    "lane": placed_lane,
                    "layout_left_px": item_left,
                    "layout_right_px": item_right,
                }
            )

        return layout_items, max(0, len(lane_end_pixels))

    @staticmethod
    def _timeline_item_stable_key(item):
        return (
            int(item.get("start_year", 0)),
            int(item.get("end_year", item.get("start_year", 0))),
            str(item.get("label", "")).casefold(),
            str(item.get("entity_id", "")),
        )

    @staticmethod
    def _timeline_item_midpoint(item):
        return (int(item.get("start_year", 0)) + int(item.get("end_year", 0))) / 2.0

    @staticmethod
    def _timeline_item_temporal_gap(left_item, right_item):
        left_start = int(left_item.get("start_year", 0))
        left_end = int(left_item.get("end_year", left_start))
        right_start = int(right_item.get("start_year", 0))
        right_end = int(right_item.get("end_year", right_start))
        if left_end < right_start:
            return right_start - left_end
        if right_end < left_start:
            return left_start - right_end
        return 0

    def _relationship_cluster_entity_order(self, component, graph, items_by_entity):
        representatives = {
            entity_id: min(items_by_entity[entity_id], key=self._timeline_item_stable_key)
            for entity_id in component
        }

        def representative(entity_id):
            return representatives[entity_id]

        def root_key(entity_id):
            item = representative(entity_id)
            return (
                -len(graph.get(entity_id, ())),
                self._timeline_item_midpoint(item),
                self._timeline_item_stable_key(item),
                entity_id,
            )

        root = min(component, key=root_key)
        ordered = []
        queued = {root}
        queue = deque([root])
        while queue:
            entity_id = queue.popleft()
            ordered.append(entity_id)
            source_item = representative(entity_id)
            neighbours = [
                neighbour_id
                for neighbour_id in graph.get(entity_id, ())
                if neighbour_id in component and neighbour_id not in queued
            ]
            neighbours.sort(key=lambda neighbour_id: (
                self._timeline_item_temporal_gap(source_item, representative(neighbour_id)),
                -len(graph.get(neighbour_id, ())),
                self._timeline_item_midpoint(representative(neighbour_id)),
                self._timeline_item_stable_key(representative(neighbour_id)),
                neighbour_id,
            ))
            queue.extend(neighbours)
            queued.update(neighbours)

        for entity_id in sorted(component - set(ordered), key=root_key):
            ordered.append(entity_id)
        return ordered

    def _relationship_item_clusters(self, items):
        items_by_entity = {}
        unkeyed_items = []
        for item in items:
            entity_id = str(item.get("entity_id") or "").strip()
            if not entity_id:
                unkeyed_items.append(item)
                continue
            items_by_entity.setdefault(entity_id, []).append(item)

        visible_ids = set(items_by_entity)
        graph = {entity_id: set() for entity_id in visible_ids}
        for entity_id in visible_ids:
            entity = self.entity_lookup.get(entity_id)
            if not isinstance(entity, dict):
                continue
            for field_key in self.RELATION_CLUSTER_FIELDS:
                for target_id in self._relation_entity_ids(entity.get(field_key)):
                    target_id = str(target_id or "").strip()
                    if target_id in visible_ids and target_id != entity_id:
                        graph[entity_id].add(target_id)
                        graph[target_id].add(entity_id)

        linked_clusters = []
        isolated_items = list(unkeyed_items)
        visited = set()
        for entity_id in sorted(visible_ids):
            if entity_id in visited:
                continue
            component = set()
            queue = deque([entity_id])
            visited.add(entity_id)
            while queue:
                current_id = queue.popleft()
                component.add(current_id)
                for neighbour_id in sorted(graph[current_id]):
                    if neighbour_id not in visited:
                        visited.add(neighbour_id)
                        queue.append(neighbour_id)

            if len(component) == 1 and not graph[entity_id]:
                isolated_items.extend(items_by_entity[entity_id])
                continue

            ordered_items = []
            for ordered_id in self._relationship_cluster_entity_order(component, graph, items_by_entity):
                ordered_items.extend(sorted(items_by_entity[ordered_id], key=self._timeline_item_stable_key))
            linked_clusters.append({"items": ordered_items, "has_links": True})

        clusters = linked_clusters
        if isolated_items:
            clusters.append({
                "items": sorted(isolated_items, key=self._timeline_item_stable_key),
                "has_links": False,
            })

        for cluster in clusters:
            midpoints = sorted(self._timeline_item_midpoint(item) for item in cluster["items"])
            cluster["temporal_center"] = midpoints[len(midpoints) // 2] if midpoints else 0
            cluster["stable_key"] = min(
                (self._timeline_item_stable_key(item) for item in cluster["items"]),
                default=(0, 0, "", ""),
            )
        clusters.sort(key=lambda cluster: (
            cluster["temporal_center"],
            0 if cluster["has_links"] else 1,
            cluster["stable_key"],
        ))
        return clusters

    def _assign_relationship_clustered_lanes(self, items):
        layout_items = []
        lane_offset = 0
        self.relationship_cluster_lane_ranges = []
        for cluster_index, cluster in enumerate(self._relationship_item_clusters(items)):
            clustered_items, cluster_lane_count = self._assign_items_to_lanes(
                cluster["items"],
                preserve_order=bool(cluster["has_links"]),
            )
            if cluster_lane_count <= 0:
                continue
            first_lane = lane_offset
            for item in clustered_items:
                item["lane"] += lane_offset
                item["relationship_cluster"] = cluster_index
                item["relationship_cluster_has_links"] = bool(cluster["has_links"])
                layout_items.append(item)
            lane_offset += cluster_lane_count
            self.relationship_cluster_lane_ranges.append({
                "cluster": cluster_index,
                "first_lane": first_lane,
                "last_lane": lane_offset - 1,
                "item_count": len(clustered_items),
                "has_links": bool(cluster["has_links"]),
            })
        return layout_items, lane_offset

    def _timeline_parent_ids_for_item(self, entity_id, visible_ids):
        entity = self.entity_lookup.get(str(entity_id or ""))
        parent_ids = []
        if isinstance(entity, dict):
            for field_key in ("parents", "parent_entity", "parent_location", "parent_body"):
                for parent_id in self._relation_entity_ids(entity.get(field_key)):
                    if parent_id in visible_ids and parent_id != entity_id:
                        parent_ids.append(parent_id)

        for parent_id, parent_entity in self.entity_lookup.items():
            if parent_id == entity_id or parent_id not in visible_ids:
                continue
            for child_id in self._relation_entity_ids(parent_entity.get("offspring") if isinstance(parent_entity, dict) else None):
                if child_id == entity_id and parent_id not in parent_ids:
                    parent_ids.append(parent_id)
        return parent_ids

    def _expand_nested_item_range(self, item, children_by_parent, items_by_id, visiting=None):
        entity_id = str(item.get("entity_id") or "")
        if visiting is None:
            visiting = set()
        if entity_id in visiting:
            return int(item["start_year"]), int(item["end_year"])
        visiting.add(entity_id)

        start_year = int(item["start_year"])
        end_year = int(item["end_year"])
        for child_id in children_by_parent.get(entity_id, []):
            child = items_by_id.get(child_id)
            if child is None:
                continue
            child_start, child_end = self._expand_nested_item_range(child, children_by_parent, items_by_id, visiting)
            start_year = min(start_year, child_start)
            end_year = max(end_year, child_end)
        visiting.discard(entity_id)
        return start_year, end_year

    def _assign_offspring_nested_lanes(self, items):
        items_by_id = {
            str(item.get("entity_id")): item
            for item in items
            if str(item.get("entity_id") or "").strip()
        }
        visible_ids = set(items_by_id)
        parent_by_child = {}
        children_by_parent = {entity_id: [] for entity_id in visible_ids}

        for entity_id in visible_ids:
            parent_ids = sorted(set(self._timeline_parent_ids_for_item(entity_id, visible_ids)))
            if parent_ids:
                parent_id = parent_ids[0]
                parent_by_child[entity_id] = parent_id
                children_by_parent.setdefault(parent_id, []).append(entity_id)

        for child_ids in children_by_parent.values():
            child_ids.sort(key=lambda child_id: (
                items_by_id[child_id]["start_year"],
                items_by_id[child_id]["end_year"],
                str(items_by_id[child_id].get("label", "")),
            ))

        roots = [
            entity_id
            for entity_id in visible_ids
            if entity_id not in parent_by_child
        ]
        roots.sort(key=lambda entity_id: (
            items_by_id[entity_id]["start_year"],
            items_by_id[entity_id]["end_year"],
            str(items_by_id[entity_id].get("label", "")),
        ))

        layout_items = []
        visited = set()

        def append_tree(entity_id, depth):
            if entity_id in visited:
                return
            item = items_by_id[entity_id]
            visited.add(entity_id)
            expanded_start, expanded_end = self._expand_nested_item_range(item, children_by_parent, items_by_id)
            display_item = {
                **item,
                "original_start_year": item["start_year"],
                "original_end_year": item["end_year"],
                "start_year": expanded_start,
                "end_year": expanded_end,
                "nest_depth": depth,
                "has_nested_children": bool(children_by_parent.get(entity_id)),
                "lane": len(layout_items),
            }
            item_left, item_right = self._get_item_horizontal_bounds(display_item)
            display_item["layout_left_px"] = item_left
            display_item["layout_right_px"] = item_right
            layout_items.append(display_item)
            for child_id in children_by_parent.get(entity_id, []):
                append_tree(child_id, depth + 1)

        for root_id in roots:
            append_tree(root_id, 0)
        for entity_id in sorted(visible_ids - visited):
            append_tree(entity_id, 0)

        return layout_items, len(layout_items)

    def _assign_period_lanes(self, visible_items=None):
        visible_items = self._filtered_visible_items() if visible_items is None else visible_items
        period_items = [
            item
            for item in visible_items
            if item.get("timeline_kind") == "major_period"
        ]
        self.period_layout_items, self.period_lane_count = self._assign_items_to_lanes(
            period_items,
            allow_touching=True,
        )

    def _assign_lanes(self, visible_items=None):
        visible_items = self._filtered_visible_items() if visible_items is None else visible_items
        timeline_items = [
            item
            for item in visible_items
            if item.get("timeline_kind") != "major_period"
        ]
        if self.timeline_sort_mode == "offspring":
            self.relationship_cluster_lane_ranges = []
            self.layout_items, lane_count = self._assign_offspring_nested_lanes(timeline_items)
        elif self.timeline_sort_mode == "relations":
            self.layout_items, lane_count = self._assign_relationship_clustered_lanes(timeline_items)
        else:
            self.relationship_cluster_lane_ranges = []
            self.layout_items, lane_count = self._assign_items_to_lanes(timeline_items)
        self.lane_count = max(1, lane_count)

    def _build_coverage_segments(self, visible_items=None):
        visible_items = self._filtered_visible_items() if visible_items is None else visible_items
        delta_by_year = {}

        for item in visible_items:
            if item.get("timeline_kind") == "major_period":
                continue

            start_year = item["start_year"]
            end_year = item["end_year"]
            if end_year < start_year:
                start_year, end_year = end_year, start_year

            delta_by_year[start_year] = delta_by_year.get(start_year, 0) + 1
            delta_by_year[end_year + 1] = delta_by_year.get(end_year + 1, 0) - 1

        self.coverage_segments = []
        self.coverage_max_density = 0

        if not delta_by_year:
            return

        running_density = 0
        sorted_years = sorted(delta_by_year.keys())

        for index, year in enumerate(sorted_years[:-1]):
            running_density += delta_by_year[year]
            next_year = sorted_years[index + 1]
            segment_end = next_year - 1

            if running_density <= 0 or segment_end < year:
                continue

            self.coverage_segments.append(
                {
                    "start_year": year,
                    "end_year": segment_end,
                    "density": running_density,
                }
            )
            self.coverage_max_density = max(self.coverage_max_density, running_density)

    def _layout_state_key(self):
        font_key = None
        if self.layout_font is not None:
            font_key = (id(self.layout_font), self.layout_font.get_linesize())
        return (
            (self.rect.x, self.rect.y, self.rect.width, self.rect.height),
            font_key,
            self._items_signature,
            self._entity_lookup_signature,
            tuple(sorted(self.open_canvas_entity_ids)),
            self.active_filter_mode,
            self.active_category_filter,
            tuple(sorted(self.active_filter_groups)),
            self.timeline_sort_mode,
            self.selected_year_filter_mode,
            self.period_filter_range,
            self.period_filter_pending_start,
            self.selected_year,
            self.working_year_range,
            self.location_focus_id,
            self.view_min_year,
            self.view_max_year,
            self.full_min_year,
            self.full_max_year,
            self._view_range_initialized,
        )

    def rebuild_layout(self):
        self.content_rect = pygame.Rect(
            self.rect.x + self.LEFT_PAD,
            self.rect.y + self.TOP_PAD + self.HEADER_H,
            max(1, self.rect.width - self.LEFT_PAD - self.RIGHT_PAD),
            max(1, self.rect.height - self.TOP_PAD - self.BOTTOM_PAD - self.HEADER_H),
        )
        self.axis_y = self.content_rect.y + self.AXIS_H
        self._compute_full_range()
        self._ensure_view_range_initialized()
        layout_key = self._layout_state_key()
        if layout_key == self._layout_cache_key:
            return False

        self._label_width_cache = {}
        visible_items = self._filtered_visible_items()
        self._build_coverage_segments(visible_items)
        self._assign_period_lanes(visible_items)
        self._assign_lanes(visible_items)
        self._clamp_vertical_scroll()
        self._layout_cache_key = layout_key
        return True

    def _rebuild_filter_hitboxes(self):
        if self.layout_font is None:
            self.filter_hitboxes = []
            self.filter_group_hitboxes = []
            self.sort_mode_hitboxes = []
            self.selected_year_filter_hitboxes = []
            self._filter_hitbox_cache_key = None
            return

        filter_groups = self.get_filter_groups()
        filter_categories = tuple(
            (category_name, self._format_filter_label(category_name))
            for category_name in self.get_filter_categories()
        )
        cache_key = (
            (self.rect.x, self.rect.y, self.rect.width, self.rect.height),
            id(self.layout_font),
            self.layout_font.get_linesize(),
            self.working_year_enabled,
            self._format_working_year_display_value(),
            self.location_focus_enabled,
            self._format_location_focus_display_value(),
            tuple(filter_groups),
            filter_categories,
            self.selected_year,
            self.selected_year_filter_mode,
        )
        if cache_key == self._filter_hitbox_cache_key:
            return

        self.filter_hitboxes = []
        self.filter_group_hitboxes = []
        self.sort_mode_hitboxes = []
        self.selected_year_filter_hitboxes = []
        self._layout_working_year_rect(self.layout_font)
        self._layout_location_focus_rect(self.layout_font)
        self._layout_random_working_year_rect(self.layout_font)
        self._layout_random_location_focus_rect(self.layout_font)
        self._layout_reset_working_year_rect(self.layout_font)
        self._layout_reset_location_focus_rect(self.layout_font)
        self._layout_sort_mode_hitboxes(self.layout_font)
        self._layout_selected_year_filter_hitboxes(self.layout_font)
        x = self.rect.x + 180
        y = self.rect.y + 6
        chip_h = 20
        gap = 6
        max_right = self.rect.right - 10
        group_max_right = max_right
        if self.working_year_enabled and self.working_year_rect.width > 0:
            group_max_right = min(group_max_right, self.working_year_rect.x - 8)
        if self.sort_mode_hitboxes:
            group_max_right = min(group_max_right, self.sort_mode_hitboxes[0][2].x - 8)

        for group_id, group_label, _ in filter_groups:
            chip_w = self.layout_font.size(group_label)[0] + 16
            chip_rect = pygame.Rect(x, y, chip_w, chip_h)
            if chip_rect.right > group_max_right:
                break
            self.filter_group_hitboxes.append((group_id, group_label, chip_rect))
            x = chip_rect.right + gap

        x = self.rect.x + 180
        y = self.rect.y + 58
        for category_name, label in filter_categories:
            chip_w = self.layout_font.size(label)[0] + 16
            chip_rect = pygame.Rect(x, y, chip_w, chip_h)
            if chip_rect.right > max_right:
                break
            self.filter_hitboxes.append((category_name, label, chip_rect))
            x = chip_rect.right + gap
        self._filter_hitbox_cache_key = cache_key

    def _layout_sort_mode_hitboxes(self, font):
        self.sort_mode_hitboxes = []
        if font is None or self.rect.width < 180:
            return
        labels = [("relations", "Links"), ("offspring", "Nest")]
        button_h = 20
        gap = 4
        widths = [max(34, font.size(label)[0] + 14) for _, label in labels]
        total_w = sum(widths) + gap
        x = self.rect.right - total_w - 10
        y = self.rect.y + 6
        for (mode, label), width in zip(labels, widths):
            rect = pygame.Rect(x, y, width, button_h)
            self.sort_mode_hitboxes.append((mode, label, rect))
            x = rect.right + gap

    def _layout_selected_year_filter_hitboxes(self, font):
        self.selected_year_filter_hitboxes = []
        if self.selected_year is None or font is None or self.rect.width < 280:
            return
        labels = [("contemporary", "Contemporary"), ("near", "Near +/-10"), ("all", "All")]
        button_h = 20
        gap = 4
        widths = [max(34, font.size(label)[0] + 14) for _, label in labels]
        total_w = sum(widths) + gap * (len(labels) - 1)
        x = self.rect.right - total_w - 10
        y = self.rect.y + 31
        for (mode, label), width in zip(labels, widths):
            rect = pygame.Rect(x, y, width, button_h)
            self.selected_year_filter_hitboxes.append((mode, label, rect))
            x = rect.right + gap

    def _layout_location_focus_rect(self, font):
        if not self.location_focus_enabled or font is None:
            self.location_focus_rect = pygame.Rect(0, 0, 0, 0)
            return

        label_w = font.size("Location")[0]
        value_w = max(font.size("Planet X / Northern Spain")[0], font.size(self._format_location_focus_display_value())[0])
        width = max(200, label_w + value_w + 34)
        width = min(width, max(140, self.rect.width - 36))
        self.location_focus_rect = pygame.Rect(
            self.rect.centerx - width // 2,
            self.rect.y + 31,
            width,
            24,
        )

    def _layout_working_year_rect(self, font):
        if not self.working_year_enabled or font is None:
            self.working_year_rect = pygame.Rect(0, 0, 0, 0)
            self.random_working_year_rect = pygame.Rect(0, 0, 0, 0)
            return

        label_w = font.size("Working Year")[0]
        value_w = max(font.size("0000 - 0000")[0], font.size(self._format_working_year_display_value())[0])
        width = max(170, label_w + value_w + 34)
        width = min(width, max(120, self.rect.width - 36))
        self.working_year_rect = pygame.Rect(
            self.rect.centerx - width // 2,
            self.rect.y + 5,
            width,
            24,
        )

    def _layout_button_next_to_rect(self, anchor_rect, label, font):
        if anchor_rect is None or anchor_rect.width <= 0 or font is None:
            return pygame.Rect(0, 0, 0, 0)
        button_w = max(72, font.size(label)[0] + 16)
        button_h = anchor_rect.height
        gap = 6
        right_x = anchor_rect.right + gap
        if right_x + button_w <= self.rect.right - 12:
            return pygame.Rect(right_x, anchor_rect.y, button_w, button_h)
        left_x = anchor_rect.x - gap - button_w
        if left_x >= self.rect.x + 12:
            return pygame.Rect(left_x, anchor_rect.y, button_w, button_h)
        return pygame.Rect(0, 0, 0, 0)

    def _layout_random_working_year_rect(self, font):
        if not self.working_year_enabled:
            self.random_working_year_rect = pygame.Rect(0, 0, 0, 0)
            return
        self.random_working_year_rect = self._layout_button_next_to_rect(
            self.working_year_rect,
            "Random Year",
            font,
        )

    def _layout_random_location_focus_rect(self, font):
        if not self.location_focus_enabled:
            self.random_location_focus_rect = pygame.Rect(0, 0, 0, 0)
            self.reset_location_focus_rect = pygame.Rect(0, 0, 0, 0)
            return
        self.random_location_focus_rect = self._layout_button_next_to_rect(
            self.location_focus_rect,
            "Random Loc",
            font,
        )

    def _layout_reset_next_to_random(self, anchor_rect, random_rect, font):
        if (
            anchor_rect is None or random_rect is None
            or anchor_rect.width <= 0 or random_rect.width <= 0 or font is None
        ):
            return pygame.Rect(0, 0, 0, 0)
        width = max(48, font.size("Reset")[0] + 14)
        gap = 6
        if random_rect.x >= anchor_rect.right:
            x = random_rect.right + gap
            if x + width <= self.rect.right - 12:
                return pygame.Rect(x, anchor_rect.y, width, anchor_rect.height)
        else:
            x = random_rect.x - gap - width
            if x >= self.rect.x + 12:
                return pygame.Rect(x, anchor_rect.y, width, anchor_rect.height)
        return pygame.Rect(0, 0, 0, 0)

    def _layout_reset_working_year_rect(self, font):
        self.reset_working_year_rect = self._layout_reset_next_to_random(
            self.working_year_rect, self.random_working_year_rect, font,
        )

    def _layout_reset_location_focus_rect(self, font):
        self.reset_location_focus_rect = self._layout_reset_next_to_random(
            self.location_focus_rect, self.random_location_focus_rect, font,
        )

    def _draw_working_year_input(self, screen, font, layout=True):
        if not self.working_year_enabled:
            return

        if layout:
            self._layout_working_year_rect(font)
            self._layout_random_working_year_rect(font)
            self._layout_reset_working_year_rect(font)
        if self.working_year_rect.width <= 0:
            return

        fill = (36, 44, 61) if self.working_year_active else (24, 30, 43)
        border = (232, 210, 148) if self.working_year_active else (96, 108, 130)
        pygame.draw.rect(screen, fill, self.working_year_rect)
        pygame.draw.rect(screen, border, self.working_year_rect, 1)

        label_surface = font.render("Working Year", True, (178, 188, 208))
        label_x = self.working_year_rect.x + 8
        label_y = self.working_year_rect.y + (self.working_year_rect.height - label_surface.get_height()) // 2
        screen.blit(label_surface, (label_x, label_y))

        value = self._format_working_year_display_value()
        if value:
            value_color = (245, 242, 226)
        else:
            value = "Year/Period"
            value_color = (112, 124, 146)
        max_value_w = max(20, self.working_year_rect.right - (label_x + label_surface.get_width() + 22))
        value = self._ellipsize_text(value, font, max_value_w)
        value_surface = font.render(value, True, value_color)
        value_x = max(
            label_x + label_surface.get_width() + 12,
            self.working_year_rect.right - value_surface.get_width() - 10,
        )
        value_y = self.working_year_rect.y + (self.working_year_rect.height - value_surface.get_height()) // 2
        screen.blit(value_surface, (value_x, value_y))

        if self.working_year_active:
            cursor_x = min(self.working_year_rect.right - 7, value_x + value_surface.get_width() + 2)
            pygame.draw.line(
                screen,
                (245, 242, 226),
                (cursor_x, self.working_year_rect.y + 5),
                (cursor_x, self.working_year_rect.bottom - 5),
                1,
            )

        self._draw_small_button(screen, font, self.random_working_year_rect, "Random Year")
        self._draw_small_button(screen, font, self.reset_working_year_rect, "Reset")

    def _draw_location_focus_input(self, screen, font, layout=True):
        if not self.location_focus_enabled:
            return

        if layout:
            self._layout_location_focus_rect(font)
            self._layout_random_location_focus_rect(font)
            self._layout_reset_location_focus_rect(font)
        if self.location_focus_rect.width <= 0:
            return

        if self.location_focus_invalid:
            border = (220, 112, 112)
        elif self.location_focus_active:
            border = (232, 210, 148)
        else:
            border = (96, 108, 130)
        fill = (36, 44, 61) if self.location_focus_active else (24, 30, 43)
        pygame.draw.rect(screen, fill, self.location_focus_rect)
        pygame.draw.rect(screen, border, self.location_focus_rect, 1)

        label_surface = font.render("Location", True, (178, 188, 208))
        label_x = self.location_focus_rect.x + 8
        label_y = self.location_focus_rect.y + (self.location_focus_rect.height - label_surface.get_height()) // 2
        screen.blit(label_surface, (label_x, label_y))

        value = self._format_location_focus_display_value()
        if value:
            value_color = (245, 242, 226)
        else:
            value = "Any"
            value_color = (112, 124, 146)
        max_value_w = max(20, self.location_focus_rect.right - (label_x + label_surface.get_width() + 22))
        value = self._ellipsize_text(value, font, max_value_w)
        value_surface = font.render(value, True, value_color)
        value_x = max(
            label_x + label_surface.get_width() + 12,
            self.location_focus_rect.right - value_surface.get_width() - 10,
        )
        value_y = self.location_focus_rect.y + (self.location_focus_rect.height - value_surface.get_height()) // 2
        screen.blit(value_surface, (value_x, value_y))

        if self.location_focus_active:
            cursor_x = min(self.location_focus_rect.right - 7, value_x + value_surface.get_width() + 2)
            pygame.draw.line(
                screen,
                (245, 242, 226),
                (cursor_x, self.location_focus_rect.y + 5),
                (cursor_x, self.location_focus_rect.bottom - 5),
                1,
            )

        self._draw_small_button(screen, font, self.random_location_focus_rect, "Random Loc")
        self._draw_small_button(screen, font, self.reset_location_focus_rect, "Reset")

    def _draw_small_button(self, screen, font, rect, label):
        if rect is None or rect.width <= 0 or rect.height <= 0:
            return
        mouse_pos = pygame.mouse.get_pos()
        hovered = rect.collidepoint(mouse_pos)
        fill = (48, 58, 78) if hovered else (30, 36, 50)
        border = (158, 176, 210) if hovered else (86, 98, 120)
        text_color = (238, 242, 250) if hovered else (178, 188, 208)
        pygame.draw.rect(screen, fill, rect)
        pygame.draw.rect(screen, border, rect, 1)
        label_surface = font.render(label, True, text_color)
        screen.blit(label_surface, label_surface.get_rect(center=rect.center))

    def _draw_location_focus_suggestions(self, screen, font):
        self.location_focus_suggestion_hitboxes = []
        if not self.location_focus_enabled or not self.location_focus_active:
            return

        matches = self.location_focus_matches or []
        if not matches:
            return

        selected_index = max(0, min(int(self.location_focus_selected_index or 0), len(matches) - 1))
        row_y = self.location_focus_rect.bottom + 4
        row_h = 22
        max_rows = 6
        for index, match in enumerate(matches[:max_rows]):
            row_rect = pygame.Rect(self.location_focus_rect.x, row_y + index * row_h, self.location_focus_rect.width, row_h)
            self.location_focus_suggestion_hitboxes.append((index, row_rect))
            selected = index == selected_index
            fill = (52, 64, 86) if selected else (31, 36, 48)
            border = (138, 164, 206) if selected else (72, 82, 104)
            pygame.draw.rect(screen, fill, row_rect)
            pygame.draw.rect(screen, border, row_rect, 1)

            label = self._ellipsize_text(match.get("label", ""), font, row_rect.width - 128)
            subtitle = self._ellipsize_text(match.get("subtitle", ""), font, 112)
            label_color = (240, 244, 250) if selected else (188, 198, 216)
            subtitle_color = (176, 188, 208)
            screen.blit(font.render(label, True, label_color), (row_rect.x + 6, row_rect.y + 3))
            if subtitle:
                subtitle_surface = font.render(subtitle, True, subtitle_color)
                screen.blit(subtitle_surface, (row_rect.right - subtitle_surface.get_width() - 6, row_rect.y + 3))

    def zoom_at(self, screen_x, factor):
        if factor <= 0:
            return False

        full_span = self.full_max_year - self.full_min_year
        if full_span <= 0:
            return False

        old_min = self.view_min_year
        old_max = self.view_max_year
        old_span = max(1.0, float(old_max - old_min))

        anchor_year = self._x_to_year(screen_x)
        anchor_t = 0.5
        if old_span > 0:
            anchor_t = (anchor_year - old_min) / old_span
            anchor_t = max(0.0, min(1.0, anchor_t))

        new_span = old_span * factor
        new_span = max(float(self.MIN_VIEW_SPAN_YEARS), new_span)
        new_span = min(float(full_span), new_span)

        new_min = anchor_year - (anchor_t * new_span)
        new_max = new_min + new_span

        self.view_min_year = int(round(new_min))
        self.view_max_year = int(round(new_max))

        if self.view_max_year - self.view_min_year < self.MIN_VIEW_SPAN_YEARS:
            center = (self.view_min_year + self.view_max_year) / 2.0
            half = self.MIN_VIEW_SPAN_YEARS / 2.0
            self.view_min_year = int(round(center - half))
            self.view_max_year = int(round(center + half))

        self._clamp_view_to_full()
        self.rebuild_layout()
        return (self.view_min_year != old_min) or (self.view_max_year != old_max)

    def focus_year(self, year, target_span_years=None):
        if year is None:
            return False

        try:
            year = int(year)
        except (TypeError, ValueError):
            return False

        full_span = self.full_max_year - self.full_min_year
        if full_span <= 0:
            return False

        current_span = max(self.MIN_VIEW_SPAN_YEARS, self.view_max_year - self.view_min_year)
        if target_span_years is None:
            target_span_years = max(
                self.MIN_VIEW_SPAN_YEARS,
                min(current_span, max(120, int(full_span * 0.05)), 1200),
            )

        new_span = max(self.MIN_VIEW_SPAN_YEARS, min(full_span, int(target_span_years)))
        half_span = new_span / 2.0

        old_min = self.view_min_year
        old_max = self.view_max_year

        self.view_min_year = int(round(year - half_span))
        self.view_max_year = self.view_min_year + new_span
        self._clamp_view_to_full()
        self.rebuild_layout()
        return (self.view_min_year != old_min) or (self.view_max_year != old_max)

    def pan_by_pixels(self, delta_px):
        if self.content_rect.width <= 1:
            return False

        old_min = self.view_min_year
        old_max = self.view_max_year
        span = max(1, self.view_max_year - self.view_min_year)
        year_delta = int(round((delta_px / float(self.content_rect.width)) * span))
        if year_delta == 0:
            year_delta = 1 if delta_px > 0 else -1

        self.view_min_year += year_delta
        self.view_max_year += year_delta
        self._clamp_view_to_full()
        self.rebuild_layout()
        return (self.view_min_year != old_min) or (self.view_max_year != old_max)

    def _period_section_height(self):
        if self.period_lane_count <= 0:
            return 0
        return (
            self.period_lane_count * self.PERIOD_H
            + max(0, self.period_lane_count - 1) * self.PERIOD_GAP
            + self.PERIOD_SECTION_GAP
        )

    def _vertical_scroll_content_height(self):
        return self._period_section_height() + self.lane_count * self._lane_pitch()

    def _unscrolled_period_base_y(self):
        if self.period_filter_rect is None:
            return self.content_rect.y
        return (
            self.period_filter_rect.bottom
            + self.PERIOD_FILTER_GAP
            + self.COVERAGE_H
            + self.COVERAGE_GAP
        )

    def _vertical_viewport_rect(self):
        top = self._unscrolled_period_base_y()
        bottom = max(top, self.rect.bottom - self.BOTTOM_PAD)
        return pygame.Rect(
            self.content_rect.x,
            top,
            max(1, self.content_rect.width),
            max(0, bottom - top),
        )

    def _max_vertical_scroll_px(self):
        viewport = self._vertical_viewport_rect()
        return max(0, self._vertical_scroll_content_height() - viewport.height)

    def _clamp_vertical_scroll(self):
        old_scroll = int(self.vertical_scroll_px or 0)
        self.vertical_scroll_px = max(
            0,
            min(self._max_vertical_scroll_px(), old_scroll),
        )
        return self.vertical_scroll_px != old_scroll

    def pan_vertical_by_pixels(self, delta_px):
        try:
            delta_px = int(round(float(delta_px)))
        except (TypeError, ValueError, OverflowError):
            return False
        if delta_px == 0:
            return False
        old_scroll = self.vertical_scroll_px
        self.vertical_scroll_px += delta_px
        self._clamp_vertical_scroll()
        return self.vertical_scroll_px != old_scroll

    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL:
            mouse_pos = pygame.mouse.get_pos()
            if not self.rect.collidepoint(mouse_pos):
                return False

            if event.y > 0:
                return self.zoom_at(mouse_pos[0], self.ZOOM_IN_FACTOR)

            if event.y < 0:
                return self.zoom_at(mouse_pos[0], self.ZOOM_OUT_FACTOR)

        return False

    def handle_keydown(self, event):
        if self.location_focus_enabled and self.location_focus_active:
            return self._handle_location_focus_keydown(event)

        if self.working_year_enabled and self.working_year_active:
            return self._handle_working_year_keydown(event)

        return None

    def _handle_working_year_keydown(self, event):
        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            value = self.working_year_buffer.strip()
            changed = self.set_working_year(value if value else None, focus=bool(value))
            start_year = self.working_year_range[0] if self.working_year_range is not None else None
            end_year = self.working_year_range[1] if self.working_year_range is not None else None
            return {
                "kind": "working_year_changed",
                "year": self.working_year,
                "start_year": start_year,
                "end_year": end_year,
                "changed": changed,
            }

        if event.key == pygame.K_ESCAPE:
            self.working_year_active = False
            self.working_year_buffer = self._format_working_year_range(self.working_year_range)
            return {"kind": "working_year_cancelled", "changed": False}

        if event.key == pygame.K_BACKSPACE:
            self.working_year_buffer = self.working_year_buffer[:-1]
            return {"kind": "working_year_editing", "changed": False}

        if event.key == pygame.K_DELETE:
            self.working_year_buffer = ""
            return {"kind": "working_year_editing", "changed": False}

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            if text.isdigit() or text in {" ", "-", "+", "–", "—"}:
                self.working_year_buffer += text
            return {"kind": "working_year_editing", "changed": False}

        return {"kind": "working_year_editing", "changed": False}

    def _handle_location_focus_keydown(self, event):
        matches = self.location_focus_matches or []
        if event.key == pygame.K_UP and matches:
            self.location_focus_selected_index = (
                int(self.location_focus_selected_index or 0) - 1
            ) % len(matches)
            self.location_focus_keyboard_active = True
            return {"kind": "location_focus_editing", "changed": False}

        if event.key == pygame.K_DOWN and matches:
            self.location_focus_selected_index = (
                int(self.location_focus_selected_index or 0) + 1
            ) % len(matches)
            self.location_focus_keyboard_active = True
            return {"kind": "location_focus_editing", "changed": False}

        if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            value = self.location_focus_buffer.strip()
            if matches and (value or self.location_focus_keyboard_active):
                changed = self._select_location_focus_match()
            else:
                changed = self.set_location_focus(value if value else None)
            if value and self.location_focus_invalid:
                return {
                    "kind": "location_focus_invalid",
                    "location_id": None,
                    "changed": False,
                }
            return {
                "kind": "location_focus_changed",
                "location_id": self.location_focus_id,
                "label": self.location_focus_label,
                "changed": changed,
            }

        if event.key == pygame.K_ESCAPE:
            self.location_focus_active = False
            self.location_focus_invalid = False
            self.location_focus_buffer = self.location_focus_label or ""
            return {"kind": "location_focus_cancelled", "changed": False}

        if event.key == pygame.K_BACKSPACE:
            self.location_focus_buffer = self.location_focus_buffer[:-1]
            self.location_focus_invalid = False
            self.location_focus_keyboard_active = False
            self._refresh_location_focus_matches()
            return {"kind": "location_focus_editing", "changed": False}

        if event.key == pygame.K_DELETE:
            self.location_focus_buffer = ""
            self.location_focus_invalid = False
            self.location_focus_keyboard_active = False
            self._refresh_location_focus_matches()
            return {"kind": "location_focus_editing", "changed": False}

        text = getattr(event, "unicode", "")
        if text and text.isprintable():
            self.location_focus_buffer += text
            self.location_focus_invalid = False
            self.location_focus_keyboard_active = False
            self._refresh_location_focus_matches()
            return {"kind": "location_focus_editing", "changed": False}

        return {"kind": "location_focus_editing", "changed": False}

    def handle_click(self, mouse_pos):
        random_action = self.handle_random_button_click(mouse_pos)
        if random_action is not None:
            return random_action

        location_focus_action = self.handle_location_focus_click(mouse_pos)
        if location_focus_action is not None:
            return location_focus_action

        working_year_action = self.handle_working_year_click(mouse_pos)
        if working_year_action is not None:
            return working_year_action

        filter_action = self.handle_filter_click(mouse_pos)
        if filter_action is not None:
            return filter_action

        period_filter_action = self.handle_period_filter_click(mouse_pos)
        if period_filter_action is not None:
            return period_filter_action

        item_action = self.handle_item_click(mouse_pos)
        if item_action is not None:
            return item_action

        if self.year_selection_enabled:
            return self.select_year_from_pos(mouse_pos)

        return None

    def _timeline_item_hit_rect(self, item, period=False):
        if not isinstance(item, dict):
            return None

        if period:
            lane = item.get("lane", 0)
            x1 = self._year_to_x(item["start_year"])
            x2 = self._year_to_x(item["end_year"])
            y = self._period_base_y() + lane * (self.PERIOD_H + self.PERIOD_GAP)
            return pygame.Rect(x1, y - 4, max(8, x2 - x1), self.PERIOD_H + 8)

        lane = item.get("lane", 0)
        start_year = item["start_year"]
        end_year = item["end_year"]
        label = item.get("label", item.get("entity_id", "unknown"))
        y = self._lane_base_y() + lane * self._lane_pitch()
        x1 = self._year_to_x(start_year)
        x2 = self._year_to_x(end_year)
        if start_year == end_year:
            label_w = self._measure_label_width(label)
            return pygame.Rect(x1 - 8, y - 4, max(20, label_w + 20), self._lane_pitch() + 4)
        label_w = self._measure_label_width(label)
        bar_w = max(6, x2 - x1)
        label_x = self._get_duration_label_x(x1, x2, label_w)
        left = min(x1, label_x)
        right = max(x1 + bar_w, label_x + label_w)
        return pygame.Rect(left, y - 4, max(8, right - left), self._lane_pitch() + 4)

    def _period_base_y(self):
        return self._unscrolled_period_base_y() - self.vertical_scroll_px

    def _lane_base_y(self):
        return self._period_base_y() + self._period_section_height()

    def handle_item_click(self, mouse_pos):
        if not self._vertical_viewport_rect().collidepoint(mouse_pos):
            return None
        for item in reversed(self.layout_items):
            hit_rect = self._timeline_item_hit_rect(item)
            if hit_rect is not None and hit_rect.collidepoint(mouse_pos):
                entity_id = item.get("entity_id")
                if entity_id:
                    return {
                        "kind": "open_timeline_entity",
                        "entity_id": entity_id,
                        "year": item.get("raw_start_year", item.get("start_year")),
                        "start_year": item.get("raw_start_year", item.get("start_year")),
                        "end_year": item.get("raw_end_year", item.get("end_year")),
                        "changed": False,
                    }

        for item in reversed(self.period_layout_items):
            hit_rect = self._timeline_item_hit_rect(item, period=True)
            if hit_rect is not None and hit_rect.collidepoint(mouse_pos):
                entity_id = item.get("entity_id")
                if entity_id:
                    return {
                        "kind": "open_timeline_entity",
                        "entity_id": entity_id,
                        "year": item.get("raw_start_year", item.get("start_year")),
                        "start_year": item.get("raw_start_year", item.get("start_year")),
                        "end_year": item.get("raw_end_year", item.get("end_year")),
                        "changed": False,
                    }

        return None

    def handle_working_year_click(self, mouse_pos):
        if not self.working_year_enabled:
            return None

        if self.working_year_rect.collidepoint(mouse_pos):
            self.working_year_active = True
            self.location_focus_active = False
            self.location_focus_invalid = False
            self.working_year_buffer = "" if self.working_year is None else str(self.working_year)
            if self.working_year_range is not None:
                self.working_year_buffer = self._format_working_year_range(self.working_year_range)
            return {
                "kind": "working_year_focus",
                "year": self.working_year,
                "changed": False,
            }

        if self.working_year_active:
            self.working_year_active = False
            self.working_year_buffer = self._format_working_year_range(self.working_year_range)

        return None

    def handle_location_focus_click(self, mouse_pos):
        if not self.location_focus_enabled:
            return None

        for match_index, hitbox in self.location_focus_suggestion_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                changed = self._select_location_focus_match(match_index)
                return {
                    "kind": "location_focus_changed",
                    "location_id": self.location_focus_id,
                    "label": self.location_focus_label,
                    "changed": changed,
                }

        if self.location_focus_rect.collidepoint(mouse_pos):
            self.location_focus_active = False
            self.working_year_active = False
            self.location_focus_invalid = False
            self.location_focus_buffer = self.location_focus_label or ""
            self.location_focus_keyboard_active = False
            self.location_focus_matches = []
            self.location_focus_suggestion_hitboxes = []
            return {
                "kind": "location_focus_browse",
                "location_id": self.location_focus_id,
                "changed": False,
            }

        if self.location_focus_active:
            self.location_focus_active = False
            self.location_focus_invalid = False
            self.location_focus_buffer = self.location_focus_label or ""
            self.location_focus_matches = []
            self.location_focus_suggestion_hitboxes = []

        return None

    def handle_filter_click(self, mouse_pos):
        for mode, _, hitbox in self.sort_mode_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                changed = self.set_timeline_sort_mode(mode)
                return {"kind": "timeline_sort_changed", "mode": mode, "changed": changed}

        for mode, _, hitbox in self.selected_year_filter_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                changed = self.set_selected_year_filter_mode(mode)
                return {"kind": "selected_year_filter_changed", "mode": mode, "changed": changed}

        for group_id, _, hitbox in self.filter_group_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                changed = self.toggle_active_filter_group(group_id)
                return {
                    "kind": "filter_group_changed",
                    "group": group_id,
                    "groups": sorted(self.active_filter_groups),
                    "changed": changed,
                }

        for category_name, _, hitbox in self.filter_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                changed = self.set_active_category_filter(category_name)
                return {"kind": "filter_changed", "category": category_name, "changed": changed}

        return None

    def handle_random_button_click(self, mouse_pos):
        if self.working_year_enabled and self.reset_working_year_rect.collidepoint(mouse_pos):
            self.working_year_active = False
            self.location_focus_active = False
            self.location_focus_invalid = False
            return self.reset_working_year()

        if self.location_focus_enabled and self.reset_location_focus_rect.collidepoint(mouse_pos):
            self.working_year_active = False
            self.location_focus_active = False
            self.location_focus_invalid = False
            return self.reset_location_focus()

        if self.working_year_enabled and self.random_working_year_rect.collidepoint(mouse_pos):
            self.working_year_active = False
            self.location_focus_active = False
            self.location_focus_invalid = False
            return self.set_random_working_year()

        if (
            self.location_focus_enabled
            and self.random_location_focus_rect.collidepoint(mouse_pos)
        ):
            self.working_year_active = False
            self.location_focus_active = False
            self.location_focus_invalid = False
            return self.set_random_location_focus()

        return None

    def handle_period_filter_click(self, mouse_pos):
        if self.period_filter_rect is None or not self.period_filter_rect.collidepoint(mouse_pos):
            return None
        year = int(round(self._x_to_year(mouse_pos[0])))
        if self.period_filter_pending_start is None:
            self.set_period_filter(pending_start=year)
            return {
                "kind": "period_filter_started",
                "year": year,
                "changed": True,
            }

        start_year = self.period_filter_pending_start
        self.set_period_filter(start_year, year)
        return {
            "kind": "period_filter_changed",
            "start_year": min(start_year, year),
            "end_year": max(start_year, year),
            "changed": True,
        }

    def select_year_from_pos(self, mouse_pos):
        picked_year = self.pick_year_from_pos(mouse_pos)
        if picked_year is None:
            return None

        changed = self.set_selected_year(picked_year)
        return {
            "kind": "selected_year_changed",
            "year": picked_year,
            "changed": changed,
        }

    def select_year_from_drag_pos(self, mouse_pos):
        if not self.year_selection_enabled:
            return None

        picked_year = int(round(self._x_to_year(mouse_pos[0])))
        changed = self.set_selected_year(picked_year)
        return {
            "kind": "selected_year_changed",
            "year": picked_year,
            "changed": changed,
        }

    def pick_year_from_pos(self, mouse_pos):
        if not self.rect.collidepoint(mouse_pos):
            return None

        if mouse_pos[0] < self.content_rect.x or mouse_pos[0] > self.content_rect.right:
            return None

        if mouse_pos[1] < self.content_rect.y or mouse_pos[1] > self.rect.bottom:
            return None

        return int(round(self._x_to_year(mouse_pos[0])))

    def pick_year_from_axis_pos(self, mouse_pos):
        if not self.rect.collidepoint(mouse_pos):
            return None

        if mouse_pos[0] < self.content_rect.x or mouse_pos[0] > self.content_rect.right:
            return None

        axis_hit_rect = pygame.Rect(
            self.content_rect.x,
            self.axis_y - self.AXIS_PICK_HALF_H,
            self.content_rect.width,
            self.AXIS_PICK_HALF_H * 2 + 1,
        )
        if not axis_hit_rect.collidepoint(mouse_pos):
            return None

        return int(round(self._x_to_year(mouse_pos[0])))

    def get_minimum_height(self):
        coverage_h = self.PERIOD_FILTER_H + self.PERIOD_FILTER_GAP + self.COVERAGE_H + self.COVERAGE_GAP
        period_h = 0
        if self.period_lane_count > 0:
            period_h = (
                self.period_lane_count * self.PERIOD_H
                + max(0, self.period_lane_count - 1) * self.PERIOD_GAP
                + self.PERIOD_SECTION_GAP
            )

        lanes_h = self.lane_count * self._lane_pitch()
        total = self.TOP_PAD + self.HEADER_H + self.AXIS_H + 10 + coverage_h + period_h + lanes_h + self.BOTTOM_PAD
        return max(70, total)

    def _draw_vertical_scrollbar(self, screen):
        max_scroll = self._max_vertical_scroll_px()
        viewport = self._vertical_viewport_rect()
        if max_scroll <= 0 or viewport.height <= 8:
            return
        track = pygame.Rect(self.rect.right - 7, viewport.y, 4, viewport.height)
        pygame.draw.rect(screen, (29, 36, 50), track)
        content_height = max(viewport.height, self._vertical_scroll_content_height())
        thumb_height = max(18, int(round(track.height * viewport.height / float(content_height))))
        thumb_height = min(track.height, thumb_height)
        travel = max(0, track.height - thumb_height)
        thumb_y = track.y + int(round(travel * self.vertical_scroll_px / float(max_scroll)))
        thumb = pygame.Rect(track.x, thumb_y, track.width, thumb_height)
        pygame.draw.rect(screen, (104, 126, 160), thumb)

    def draw(self, screen, font):
        pygame.draw.rect(screen, (14, 18, 30), self.rect)
        pygame.draw.rect(screen, (200, 200, 200), self.rect, 1)

        previous_clip = screen.get_clip()
        screen.set_clip(self.rect.inflate(-2, -2))

        try:
            self._rebuild_filter_hitboxes()
            title = font.render(self.title, True, (240, 240, 240))
            screen.blit(title, (self.rect.x + 12, self.rect.y + 8))
            self._draw_working_year_input(screen, font, layout=False)
            self._draw_location_focus_input(screen, font, layout=False)

            for mode, label, chip_rect in self.sort_mode_hitboxes:
                selected = mode == self.timeline_sort_mode
                fill = (64, 84, 122) if selected else (28, 34, 48)
                border = (210, 220, 240) if selected else (88, 100, 124)
                text_color = (245, 245, 245) if selected else (178, 188, 208)
                pygame.draw.rect(screen, fill, chip_rect)
                pygame.draw.rect(screen, border, chip_rect, 1)
                chip_text = font.render(label, True, text_color)
                screen.blit(chip_text, chip_text.get_rect(center=chip_rect.center))

            for mode, label, chip_rect in self.selected_year_filter_hitboxes:
                selected = mode == self.selected_year_filter_mode
                fill = (76, 94, 128) if selected else (25, 31, 44)
                border = (220, 226, 240) if selected else (82, 94, 116)
                text_color = (248, 248, 248) if selected else (172, 184, 202)
                pygame.draw.rect(screen, fill, chip_rect)
                pygame.draw.rect(screen, border, chip_rect, 1)
                chip_text = font.render(label, True, text_color)
                screen.blit(chip_text, chip_text.get_rect(center=chip_rect.center))

            for group_id, label, chip_rect in self.filter_group_hitboxes:
                selected = self.active_filter_mode == "group" and group_id in self.active_filter_groups
                fill = (56, 66, 90) if selected else (26, 31, 44)
                border = (190, 204, 230) if selected else (78, 88, 108)
                text_color = (245, 245, 245) if selected else (166, 176, 196)
                pygame.draw.rect(screen, fill, chip_rect)
                pygame.draw.rect(screen, border, chip_rect, 1)
                chip_text = font.render(label, True, text_color)
                chip_text_rect = chip_text.get_rect(center=chip_rect.center)
                screen.blit(chip_text, chip_text_rect)

            for category_name, label, chip_rect in self.filter_hitboxes:
                selected = (
                    self.active_filter_mode == "category"
                    and category_name == self.active_category_filter
                )
                fill = (64, 84, 122) if selected else (33, 39, 54)
                border = (210, 220, 240) if selected else (92, 102, 124)
                text_color = (245, 245, 245) if selected else (190, 198, 214)
                pygame.draw.rect(screen, fill, chip_rect)
                pygame.draw.rect(screen, border, chip_rect, 1)
                chip_text = font.render(label, True, text_color)
                chip_text_rect = chip_text.get_rect(center=chip_rect.center)
                screen.blit(chip_text, chip_text_rect)

            self._draw_location_focus_suggestions(screen, font)

            if self.picker_target_label:
                picker_text = f"Pick year for {self.picker_target_label}"
                if self.picker_preview_year is not None:
                    picker_text += f" ({self.picker_preview_year})"
                picker_surface = font.render(picker_text, True, (232, 210, 148))
                picker_x = self.rect.right - picker_surface.get_width() - 12
                screen.blit(picker_surface, (picker_x, self.rect.y + 8))
            elif self.selected_year is not None and not self.working_year_enabled:
                selected_label = self._format_selected_year_label()
                selected_surface = font.render(selected_label, True, (232, 210, 148))
                selected_x = self.rect.right - selected_surface.get_width() - 12
                if self.sort_mode_hitboxes:
                    selected_x = min(selected_x, self.sort_mode_hitboxes[0][2].x - selected_surface.get_width() - 10)
                if selected_x > self.rect.x + 12 + title.get_width() + 12:
                    screen.blit(selected_surface, (selected_x, self.rect.y + 8))

            axis_left = self.content_rect.x
            axis_right = self.content_rect.right
            pygame.draw.line(screen, (150, 150, 170), (axis_left, self.axis_y), (axis_right, self.axis_y), 1)

            for tick in self._axis_ticks(font):
                tick_x = tick["x"]
                tick_color = (148, 150, 172) if tick.get("is_endpoint") else (120, 120, 140)
                tick_top = self.axis_y - 7 if tick.get("is_endpoint") else self.axis_y - 5
                tick_bottom = self.axis_y + 7 if tick.get("is_endpoint") else self.axis_y + 5
                pygame.draw.line(screen, tick_color, (tick_x, tick_top), (tick_x, tick_bottom), 1)
                label = tick.get("label")
                label_rect = tick.get("label_rect")
                if label and label_rect is not None:
                    label_surface = font.render(label, True, (190, 190, 190))
                    screen.blit(label_surface, label_rect)

            if self.picker_target_label and self.picker_preview_year is not None:
                picker_x = self._year_to_x(self.picker_preview_year)
                pygame.draw.line(screen, (232, 210, 148), (picker_x, self.content_rect.y), (picker_x, self.rect.bottom - 10), 1)

            period_filter_y = self.axis_y + 10
            period_filter_label = font.render("Period Filter", True, (166, 174, 190))
            screen.blit(period_filter_label, (axis_left, period_filter_y - 16))
            self.period_filter_rect = pygame.Rect(axis_left, period_filter_y, self.content_rect.width, self.PERIOD_FILTER_H)
            pygame.draw.rect(screen, (22, 26, 38), self.period_filter_rect)
            pygame.draw.rect(screen, (82, 90, 110), self.period_filter_rect, 1)
            if self.period_filter_range is not None:
                start_year, end_year = self.period_filter_range
                x1 = self._year_to_x(start_year)
                x2 = self._year_to_x(end_year)
                selected_rect = pygame.Rect(min(x1, x2), period_filter_y + 1, max(2, abs(x2 - x1)), max(1, self.PERIOD_FILTER_H - 2))
                pygame.draw.rect(screen, (92, 128, 176), selected_rect)
                pygame.draw.line(screen, (230, 238, 252), (x1, period_filter_y - 3), (x1, self.period_filter_rect.bottom + 3), 1)
                pygame.draw.line(screen, (230, 238, 252), (x2, period_filter_y - 3), (x2, self.period_filter_rect.bottom + 3), 1)
            elif self.period_filter_pending_start is not None:
                pending_x = self._year_to_x(self.period_filter_pending_start)
                pygame.draw.line(screen, (232, 210, 148), (pending_x, period_filter_y - 3), (pending_x, self.period_filter_rect.bottom + 3), 2)
            else:
                hint_surface = font.render("click start, click end", True, (116, 126, 146))
                if hint_surface.get_width() < self.period_filter_rect.width - 8:
                    screen.blit(hint_surface, (self.period_filter_rect.x + 6, self.period_filter_rect.y - 2))

            coverage_y = self.period_filter_rect.bottom + self.PERIOD_FILTER_GAP
            coverage_label = font.render("Coverage", True, (166, 174, 190))
            screen.blit(coverage_label, (axis_left, coverage_y - 16))

            coverage_rect = pygame.Rect(axis_left, coverage_y, self.content_rect.width, self.COVERAGE_H)
            pygame.draw.rect(screen, (26, 30, 42), coverage_rect)
            pygame.draw.rect(screen, (72, 78, 96), coverage_rect, 1)

            if self.coverage_max_density > 0:
                for segment in self.coverage_segments:
                    x1 = self._year_to_x(segment["start_year"])
                    x2 = self._year_to_x(segment["end_year"])
                    if x2 < axis_left or x1 > axis_right:
                        continue
                    bar_w = max(2, x2 - x1 + 1)
                    density_ratio = segment["density"] / float(self.coverage_max_density)
                    fill_color = (
                        int(60 + 70 * density_ratio),
                        int(92 + 78 * density_ratio),
                        int(118 + 90 * density_ratio),
                    )
                    segment_rect = pygame.Rect(x1, coverage_y + 1, bar_w, max(1, self.COVERAGE_H - 2))
                    pygame.draw.rect(screen, fill_color, segment_rect)

            timeline_content_clip = screen.get_clip()
            vertical_viewport = self._vertical_viewport_rect()
            screen.set_clip(timeline_content_clip.clip(vertical_viewport))
            period_base_y = self._period_base_y()

            for item in self.period_layout_items:
                lane = item["lane"]
                x1 = self._year_to_x(item["start_year"])
                x2 = self._year_to_x(item["end_year"])
                y = period_base_y + lane * (self.PERIOD_H + self.PERIOD_GAP)
                if y > vertical_viewport.bottom or y + self.PERIOD_H < vertical_viewport.y:
                    continue
                if x2 < axis_left or x1 > axis_right:
                    continue
                fill_color = self._coerce_color(item.get("card_color"), (70, 76, 108))
                border_color = self._mix_color(fill_color, (240, 230, 180), 0.55)
                label_color = self._readable_text_color(fill_color)

                bar_rect = pygame.Rect(x1, y, max(8, x2 - x1), self.PERIOD_H)
                pygame.draw.rect(screen, fill_color, bar_rect)
                pygame.draw.rect(screen, border_color, bar_rect, 1)

                label_surface = font.render(item.get("label", "period"), True, label_color)
                label_x = max(axis_left, min(bar_rect.x + 6, axis_right - label_surface.get_width()))
                screen.blit(label_surface, (label_x, y - 2))

            lane_base_y = period_base_y + self._period_section_height()
            lane_pitch = self._lane_pitch()

            if self.timeline_sort_mode == "relations":
                for cluster_range in self.relationship_cluster_lane_ranges[1:]:
                    separator_y = lane_base_y + cluster_range["first_lane"] * lane_pitch - max(2, self.LANE_GAP // 2)
                    separator_color = (
                        (62, 78, 102)
                        if cluster_range.get("has_links")
                        else (42, 50, 66)
                    )
                    pygame.draw.line(
                        screen,
                        separator_color,
                        (axis_left, separator_y),
                        (axis_right, separator_y),
                        1,
                    )

            for item in self.layout_items:
                lane = item["lane"]
                start_year = item["start_year"]
                end_year = item["end_year"]
                label = item.get("label", item.get("entity_id", "unknown"))
                depth = max(0, int(item.get("nest_depth", 0) or 0))
                is_point = start_year == end_year

                y = lane_base_y + lane * lane_pitch
                if y > vertical_viewport.bottom or y + lane_pitch < vertical_viewport.y:
                    continue
                x1 = self._year_to_x(start_year)
                x2 = self._year_to_x(end_year)
                if is_point:
                    if x1 < axis_left or x1 > axis_right:
                        continue
                elif x2 < axis_left or x1 > axis_right:
                    continue

                color = self._coerce_color(item.get("card_color"), (110, 140, 220) if is_point else (80, 110, 180))
                border_color = self._mix_color(color, (210, 225, 255), 0.55)
                label_color = self._readable_text_color(color)
                label_prefix = "  " * min(depth, 4)
                if depth:
                    label_prefix += "> "
                render_label = f"{label_prefix}{label}"

                is_snapshot = item.get("timeline_kind") in {"snapshot", "wiki_snapshot", "mentioned_wiki_snapshot"}
                if is_point and is_snapshot:
                    label_surface = font.render(render_label, True, label_color)
                    chip_w = min(max(28, label_surface.get_width() + 14), max(28, axis_right - x1))
                    chip_rect = pygame.Rect(x1 + 4, y - 1, chip_w, self.ITEM_H + 2)
                    pygame.draw.rect(screen, color, chip_rect)
                    pygame.draw.rect(screen, border_color, chip_rect, 1)
                    screen.blit(label_surface, (chip_rect.x + 7, y - 1))
                    pygame.draw.line(screen, color, (x1, self.axis_y), (x1, chip_rect.centery), 1)
                elif is_point:
                    pygame.draw.line(screen, color, (x1, self.axis_y), (x1, y + self.ITEM_H // 2), 1)
                    pygame.draw.circle(screen, border_color, (x1, y + self.ITEM_H // 2), 4)
                    label_surface = font.render(render_label, True, (220, 220, 220))
                    screen.blit(label_surface, (x1 + 8, y))
                else:
                    bar_w = max(6, x2 - x1)
                    bar_rect = pygame.Rect(x1, y, bar_w, self.ITEM_H)
                    pygame.draw.rect(screen, color, bar_rect)
                    pygame.draw.rect(screen, border_color, bar_rect, 1)

                    if x1 <= axis_right and x2 >= axis_left:
                        label_surface = font.render(render_label, True, label_color)
                        label_x = self._get_duration_label_x(x1, x2, label_surface.get_width())
                        screen.blit(label_surface, (label_x, y - 1))

                commentary = self._item_commentary_text(item)
                if commentary and self._show_item_commentary():
                    note = self._ellipsize_text(commentary, font, max(80, axis_right - max(axis_left, x1 + 8) - 4))
                    if note:
                        note_surface = font.render(note, True, (178, 194, 218))
                        note_x = max(axis_left, min(x1 + 8 + depth * 12, axis_right - note_surface.get_width()))
                        screen.blit(note_surface, (note_x, y + self.ITEM_H))

            screen.set_clip(timeline_content_clip)
            self._draw_vertical_scrollbar(screen)
            self._draw_selected_year_marker(screen)
        finally:
            screen.set_clip(previous_clip)
