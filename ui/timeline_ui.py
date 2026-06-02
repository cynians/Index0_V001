import math

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

    HEADER_H = 48
    AXIS_H = 22
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
    FILTER_GROUPS = [
        ("general", "General", ["all", "open_canvas", "contemporary"]),
        ("locations", "Locations", ["locations"]),
        ("engineering", "Engineering", ["vehicles", "components", "technologies"]),
        ("human", "Human", ["pops", "people", "cultures", "factions", "institutions"]),
        ("material", "Material", ["items", "materials", "production", "producers"]),
        ("world", "World", ["systems", "species", "events", "formations", "spatial_features"]),
        ("ideas", "Ideas", ["ideas", "tasks", "behaviors", "cultural_aspects", "cladistics", "conflicts"]),
    ]

    ZOOM_IN_FACTOR = 0.80
    ZOOM_OUT_FACTOR = 1.25
    MIN_VIEW_SPAN_YEARS = 10

    def __init__(self):
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.title = "Repository Timeline"
        self.items = []
        self.period_layout_items = []
        self.layout_items = []
        self.coverage_segments = []
        self.coverage_max_density = 0
        self.layout_font = None
        self.active_category_filter = "all"
        self.active_filter_group = "general"
        self.active_filter_mode = "category"
        self.open_canvas_entity_ids = set()
        self.filter_hitboxes = []
        self.filter_group_hitboxes = []
        self.picker_target_label = None
        self.picker_preview_year = None
        self.year_selection_enabled = False
        self.selected_year = None
        self.selected_year_context_label = None

        self.full_min_year = 0
        self.full_max_year = 1

        self.view_min_year = 0
        self.view_max_year = 1
        self._view_range_initialized = False

        self.period_lane_count = 0
        self.lane_count = 1
        self.content_rect = pygame.Rect(0, 0, 0, 0)
        self.axis_y = 0

    def set_rect(self, rect):
        self.rect = pygame.Rect(rect)

    def set_font(self, font):
        self.layout_font = font

    def set_title(self, title):
        self.title = str(title or "Timeline")

    def set_items(self, items):
        had_focus_item = self._items_have_default_focus_item(self.items)
        self.items = list(items or [])
        has_focus_item = self._items_have_default_focus_item(self.items)
        if has_focus_item and not had_focus_item:
            self._view_range_initialized = False
        self._ensure_active_filter_valid()

    def set_open_canvas_entity_ids(self, entity_ids):
        self.open_canvas_entity_ids = {
            str(entity_id)
            for entity_id in (entity_ids or [])
            if str(entity_id or "").strip()
        }
        self._ensure_active_filter_valid()

    def set_year_selection_enabled(self, enabled):
        self.year_selection_enabled = bool(enabled)

    def set_selected_year(self, year, context_label=None, focus=False):
        if year is None:
            self.selected_year = None
            self.selected_year_context_label = None
            return False

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
        self.active_filter_mode = "category"
        if changed:
            self.rebuild_layout()
        return changed

    def set_active_filter_group(self, group_id):
        available_groups = self.get_filter_groups()
        valid_group_ids = {available_group_id for available_group_id, _, _ in available_groups}
        if group_id not in valid_group_ids:
            group_id = available_groups[0][0] if available_groups else "general"

        changed = group_id != self.active_filter_group or self.active_filter_mode != "group"
        self.active_filter_group = group_id
        self.active_filter_mode = "group"
        categories = self._categories_for_group(group_id)
        if categories and self.active_category_filter not in categories:
            self.active_category_filter = categories[0]
            changed = True
        if changed:
            self.rebuild_layout()
        return changed

    def _available_filter_categories(self):
        categories = {"all", "open_canvas", "contemporary"}
        for item in self.items:
            if item.get("timeline_kind") == "major_period":
                continue
            dataset_name = item.get("dataset")
            if dataset_name:
                categories.add(str(dataset_name))

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
            group_categories = self._categories_for_group(self.active_filter_group)
            if group_categories and self.active_category_filter not in group_categories:
                self.active_category_filter = group_categories[0]
            return

        if self.active_category_filter not in categories:
            self.active_category_filter = "all"
            self.active_filter_mode = "category"

        self.active_filter_group = self._group_for_category(self.active_category_filter)
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
        visible_items = self._visible_items()
        if self.active_filter_mode == "group":
            group_categories = set(self._categories_for_group(self.active_filter_group))
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

    def _contemporary_visible_items(self, visible_items):
        if self.selected_year is not None:
            return [
                item for item in visible_items
                if item.get("timeline_kind") == "major_period"
                or (
                    (year_range := self._item_year_range(item)) is not None
                    and year_range[0] <= self.selected_year <= year_range[1]
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
        if not self.items:
            self.full_min_year = 0
            self.full_max_year = 1
            return

        years = []
        if self.selected_year is not None:
            years.append(self.selected_year)

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
            return

        min_year = min(years)
        max_year = max(years)

        if min_year == max_year:
            self.full_min_year = min_year - 1
            self.full_max_year = max_year + 1
            return

        padding = max(1, int((max_year - min_year) * 0.03))
        self.full_min_year = min_year - padding
        self.full_max_year = max_year + padding

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
            start = item.get("start_year")
            end = item.get("end_year")

            if start is None and end is None:
                continue

            if start is None:
                start = end
            if end is None:
                end = start

            if end < start:
                start, end = end, start

            if end < self.view_min_year or start > self.view_max_year:
                continue

            visible.append(
                {
                    **item,
                    "start_year": start,
                    "end_year": end,
                }
            )

        return visible

    def _measure_label_width(self, label):
        label = str(label or "")

        if self.layout_font is not None:
            return self.layout_font.size(label)[0]

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

    def _assign_items_to_lanes(self, items, allow_touching=False):
        layout_items = []
        sortable = list(items)
        sortable.sort(key=lambda item: (item["start_year"], item["end_year"], item.get("label", "")))

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

    def _assign_period_lanes(self):
        period_items = [
            item
            for item in self._filtered_visible_items()
            if item.get("timeline_kind") == "major_period"
        ]
        self.period_layout_items, self.period_lane_count = self._assign_items_to_lanes(
            period_items,
            allow_touching=True,
        )

    def _assign_lanes(self):
        timeline_items = [
            item
            for item in self._filtered_visible_items()
            if item.get("timeline_kind") != "major_period"
        ]
        self.layout_items, lane_count = self._assign_items_to_lanes(timeline_items)
        self.lane_count = max(1, lane_count)

    def _build_coverage_segments(self):
        delta_by_year = {}

        for item in self._filtered_visible_items():
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
        self._build_coverage_segments()
        self._assign_period_lanes()
        self._assign_lanes()

    def _rebuild_filter_hitboxes(self):
        self.filter_hitboxes = []
        self.filter_group_hitboxes = []
        if self.layout_font is None:
            return

        x = self.rect.x + 180
        y = self.rect.y + 6
        chip_h = 20
        gap = 6
        max_right = self.rect.right - 10

        for group_id, group_label, _ in self.get_filter_groups():
            chip_w = self.layout_font.size(group_label)[0] + 16
            chip_rect = pygame.Rect(x, y, chip_w, chip_h)
            if chip_rect.right > max_right:
                break
            self.filter_group_hitboxes.append((group_id, group_label, chip_rect))
            x = chip_rect.right + gap

        x = self.rect.x + 180
        y = self.rect.y + 28
        for category_name in self.get_filter_categories():
            label = self._format_filter_label(category_name)
            chip_w = self.layout_font.size(label)[0] + 16
            chip_rect = pygame.Rect(x, y, chip_w, chip_h)
            if chip_rect.right > max_right:
                break
            self.filter_hitboxes.append((category_name, label, chip_rect))
            x = chip_rect.right + gap

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

    def handle_click(self, mouse_pos):
        filter_action = self.handle_filter_click(mouse_pos)
        if filter_action is not None:
            return filter_action

        if self.year_selection_enabled:
            return self.select_year_from_pos(mouse_pos)

        return None

    def handle_filter_click(self, mouse_pos):
        for group_id, _, hitbox in self.filter_group_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                changed = self.set_active_filter_group(group_id)
                return {
                    "kind": "filter_group_changed",
                    "group": group_id,
                    "category": self.active_category_filter,
                    "changed": changed,
                }

        for category_name, _, hitbox in self.filter_hitboxes:
            if hitbox.collidepoint(mouse_pos):
                changed = self.set_active_category_filter(category_name)
                return {"kind": "filter_changed", "category": category_name, "changed": changed}

        return None

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

    def get_minimum_height(self):
        coverage_h = self.COVERAGE_H + self.COVERAGE_GAP
        period_h = 0
        if self.period_lane_count > 0:
            period_h = (
                self.period_lane_count * self.PERIOD_H
                + max(0, self.period_lane_count - 1) * self.PERIOD_GAP
                + self.PERIOD_SECTION_GAP
            )

        lanes_h = self.lane_count * self.ITEM_H + max(0, self.lane_count - 1) * self.LANE_GAP
        total = self.TOP_PAD + self.HEADER_H + self.AXIS_H + 10 + coverage_h + period_h + lanes_h + self.BOTTOM_PAD
        return max(70, total)

    def draw(self, screen, font):
        pygame.draw.rect(screen, (14, 18, 30), self.rect)
        pygame.draw.rect(screen, (200, 200, 200), self.rect, 1)

        previous_clip = screen.get_clip()
        screen.set_clip(self.rect.inflate(-2, -2))

        try:
            self._rebuild_filter_hitboxes()
            title = font.render(self.title, True, (240, 240, 240))
            screen.blit(title, (self.rect.x + 12, self.rect.y + 8))

            for group_id, label, chip_rect in self.filter_group_hitboxes:
                selected = group_id == self.active_filter_group
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

            if self.picker_target_label:
                picker_text = f"Pick year for {self.picker_target_label}"
                if self.picker_preview_year is not None:
                    picker_text += f" ({self.picker_preview_year})"
                picker_surface = font.render(picker_text, True, (232, 210, 148))
                picker_x = self.rect.right - picker_surface.get_width() - 12
                screen.blit(picker_surface, (picker_x, self.rect.y + 8))
            elif self.selected_year is not None:
                selected_label = self._format_selected_year_label()
                selected_surface = font.render(selected_label, True, (232, 210, 148))
                selected_x = self.rect.right - selected_surface.get_width() - 12
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

            coverage_y = self.axis_y + 10
            coverage_label = font.render("Coverage", True, (166, 174, 190))
            screen.blit(coverage_label, (axis_left, coverage_y - 16))

            coverage_rect = pygame.Rect(axis_left, coverage_y, self.content_rect.width, self.COVERAGE_H)
            pygame.draw.rect(screen, (26, 30, 42), coverage_rect)
            pygame.draw.rect(screen, (72, 78, 96), coverage_rect, 1)

            if self.coverage_max_density > 0:
                for segment in self.coverage_segments:
                    x1 = self._year_to_x(segment["start_year"])
                    x2 = self._year_to_x(segment["end_year"])
                    bar_w = max(2, x2 - x1 + 1)
                    density_ratio = segment["density"] / float(self.coverage_max_density)
                    fill_color = (
                        int(60 + 70 * density_ratio),
                        int(92 + 78 * density_ratio),
                        int(118 + 90 * density_ratio),
                    )
                    segment_rect = pygame.Rect(x1, coverage_y + 1, bar_w, max(1, self.COVERAGE_H - 2))
                    pygame.draw.rect(screen, fill_color, segment_rect)

            period_base_y = coverage_rect.bottom + self.COVERAGE_GAP

            for item in self.period_layout_items:
                lane = item["lane"]
                x1 = self._year_to_x(item["start_year"])
                x2 = self._year_to_x(item["end_year"])
                y = period_base_y + lane * (self.PERIOD_H + self.PERIOD_GAP)
                fill_color = self._coerce_color(item.get("card_color"), (70, 76, 108))
                border_color = self._mix_color(fill_color, (240, 230, 180), 0.55)
                label_color = self._readable_text_color(fill_color)

                bar_rect = pygame.Rect(x1, y, max(8, x2 - x1), self.PERIOD_H)
                pygame.draw.rect(screen, fill_color, bar_rect)
                pygame.draw.rect(screen, border_color, bar_rect, 1)

                label_surface = font.render(item.get("label", "period"), True, label_color)
                label_x = max(axis_left, min(bar_rect.x + 6, axis_right - label_surface.get_width()))
                screen.blit(label_surface, (label_x, y - 2))

            period_section_h = 0
            if self.period_lane_count > 0:
                period_section_h = (
                    self.period_lane_count * self.PERIOD_H
                    + max(0, self.period_lane_count - 1) * self.PERIOD_GAP
                    + self.PERIOD_SECTION_GAP
                )

            lane_base_y = period_base_y + period_section_h

            for item in self.layout_items:
                lane = item["lane"]
                start_year = item["start_year"]
                end_year = item["end_year"]
                label = item.get("label", item.get("entity_id", "unknown"))
                is_point = start_year == end_year

                y = lane_base_y + lane * (self.ITEM_H + self.LANE_GAP)
                x1 = self._year_to_x(start_year)
                x2 = self._year_to_x(end_year)

                color = self._coerce_color(item.get("card_color"), (110, 140, 220) if is_point else (80, 110, 180))
                border_color = self._mix_color(color, (210, 225, 255), 0.55)
                label_color = self._readable_text_color(color)

                if is_point:
                    pygame.draw.line(screen, color, (x1, self.axis_y), (x1, y + self.ITEM_H // 2), 1)
                    pygame.draw.circle(screen, border_color, (x1, y + self.ITEM_H // 2), 4)
                    label_surface = font.render(label, True, (220, 220, 220))
                    screen.blit(label_surface, (x1 + 8, y))
                else:
                    bar_w = max(6, x2 - x1)
                    bar_rect = pygame.Rect(x1, y, bar_w, self.ITEM_H)
                    pygame.draw.rect(screen, color, bar_rect)
                    pygame.draw.rect(screen, border_color, bar_rect, 1)

                    if x1 <= axis_right and x2 >= axis_left:
                        label_surface = font.render(label, True, label_color)
                        label_x = self._get_duration_label_x(x1, x2, label_surface.get_width())
                        screen.blit(label_surface, (label_x, y - 1))

            self._draw_selected_year_marker(screen)
        finally:
            screen.set_clip(previous_clip)
