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

    HEADER_H = 24
    AXIS_H = 22
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

    ZOOM_IN_FACTOR = 0.80
    ZOOM_OUT_FACTOR = 1.25
    MIN_VIEW_SPAN_YEARS = 10

    def __init__(self):
        self.rect = pygame.Rect(0, 0, 0, 0)
        self.items = []
        self.period_layout_items = []
        self.layout_items = []
        self.layout_font = None

        self.full_min_year = 0
        self.full_max_year = 1

        self.view_min_year = 0
        self.view_max_year = 1

        self.period_lane_count = 0
        self.lane_count = 1
        self.content_rect = pygame.Rect(0, 0, 0, 0)
        self.axis_y = 0

    def set_rect(self, rect):
        self.rect = pygame.Rect(rect)

    def set_font(self, font):
        self.layout_font = font

    def set_items(self, items):
        self.items = list(items or [])

    def _compute_full_range(self):
        if not self.items:
            self.full_min_year = 0
            self.full_max_year = 1
            return

        years = []
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
            for item in self._visible_items()
            if item.get("timeline_kind") == "major_period"
        ]
        self.period_layout_items, self.period_lane_count = self._assign_items_to_lanes(
            period_items,
            allow_touching=True,
        )

    def _assign_lanes(self):
        timeline_items = [
            item
            for item in self._visible_items()
            if item.get("timeline_kind") != "major_period"
        ]
        self.layout_items, lane_count = self._assign_items_to_lanes(timeline_items)
        self.lane_count = max(1, lane_count)

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
        self._assign_period_lanes()
        self._assign_lanes()

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

    def handle_event(self, event):
        if event.type != pygame.MOUSEWHEEL:
            return False

        mouse_pos = pygame.mouse.get_pos()
        if not self.rect.collidepoint(mouse_pos):
            return False

        if event.y > 0:
            return self.zoom_at(mouse_pos[0], self.ZOOM_IN_FACTOR)

        if event.y < 0:
            return self.zoom_at(mouse_pos[0], self.ZOOM_OUT_FACTOR)

        return False

    def get_minimum_height(self):
        period_h = 0
        if self.period_lane_count > 0:
            period_h = (
                self.period_lane_count * self.PERIOD_H
                + max(0, self.period_lane_count - 1) * self.PERIOD_GAP
                + self.PERIOD_SECTION_GAP
            )

        lanes_h = self.lane_count * self.ITEM_H + max(0, self.lane_count - 1) * self.LANE_GAP
        total = self.TOP_PAD + self.HEADER_H + self.AXIS_H + 10 + period_h + lanes_h + self.BOTTOM_PAD
        return max(70, total)

    def draw(self, screen, font):
        pygame.draw.rect(screen, (14, 18, 30), self.rect)
        pygame.draw.rect(screen, (200, 200, 200), self.rect, 1)

        previous_clip = screen.get_clip()
        screen.set_clip(self.rect.inflate(-2, -2))

        try:
            title = font.render("Repository Timeline", True, (240, 240, 240))
            screen.blit(title, (self.rect.x + 12, self.rect.y + 8))

            axis_left = self.content_rect.x
            axis_right = self.content_rect.right
            pygame.draw.line(screen, (150, 150, 170), (axis_left, self.axis_y), (axis_right, self.axis_y), 1)

            start_text = font.render(str(self.view_min_year), True, (190, 190, 190))
            mid_year = int((self.view_min_year + self.view_max_year) / 2)
            mid_text = font.render(str(mid_year), True, (190, 190, 190))
            end_text = font.render(str(self.view_max_year), True, (190, 190, 190))

            screen.blit(start_text, (axis_left, self.content_rect.y))
            screen.blit(
                mid_text,
                (
                    axis_left + (self.content_rect.width // 2) - (mid_text.get_width() // 2),
                    self.content_rect.y,
                ),
            )
            screen.blit(end_text, (axis_right - end_text.get_width(), self.content_rect.y))

            for year in (self.view_min_year, mid_year, self.view_max_year):
                tick_x = self._year_to_x(year)
                pygame.draw.line(screen, (120, 120, 140), (tick_x, self.axis_y - 6), (tick_x, self.axis_y + 6), 1)

            period_base_y = self.axis_y + 10

            for item in self.period_layout_items:
                lane = item["lane"]
                x1 = self._year_to_x(item["start_year"])
                x2 = self._year_to_x(item["end_year"])
                y = period_base_y + lane * (self.PERIOD_H + self.PERIOD_GAP)

                bar_rect = pygame.Rect(x1, y, max(8, x2 - x1), self.PERIOD_H)
                pygame.draw.rect(screen, (70, 76, 108), bar_rect)
                pygame.draw.rect(screen, (212, 195, 130), bar_rect, 1)

                label_surface = font.render(item.get("label", "period"), True, (240, 232, 205))
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

                color = (110, 140, 220) if is_point else (80, 110, 180)

                if is_point:
                    pygame.draw.line(screen, color, (x1, self.axis_y), (x1, y + self.ITEM_H // 2), 1)
                    pygame.draw.circle(screen, (170, 190, 255), (x1, y + self.ITEM_H // 2), 4)
                    label_surface = font.render(label, True, (220, 220, 220))
                    screen.blit(label_surface, (x1 + 8, y))
                else:
                    bar_w = max(6, x2 - x1)
                    bar_rect = pygame.Rect(x1, y, bar_w, self.ITEM_H)
                    pygame.draw.rect(screen, color, bar_rect)
                    pygame.draw.rect(screen, (170, 190, 255), bar_rect, 1)

                    if x1 <= axis_right and x2 >= axis_left:
                        label_surface = font.render(label, True, (230, 230, 230))
                        label_x = self._get_duration_label_x(x1, x2, label_surface.get_width())
                        screen.blit(label_surface, (label_x, y - 1))
        finally:
            screen.set_clip(previous_clip)
