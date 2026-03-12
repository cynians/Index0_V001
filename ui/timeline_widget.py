from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF, QPointF, Signal
from PySide6.QtGui import QPainter, QPen, QFont, QColor, QBrush


class TimelineWidget(QWidget):

    event_clicked = Signal(str)

    def __init__(self, world_model=None):
        super().__init__()

        # world integration
        self.world = world_model

        self.timeline_start = 1900
        self.timeline_end = 2300
        self.current_year = 2022

        self.events = []
        self.active_entities = []

        self.base_years_per_pixel = 3.0
        self.zoom_factor = 1.0
        self.min_zoom_factor = 0.05
        self.max_zoom_factor = 2500.0

        self.pan_offset = 0.0
        self._dragging = False
        self._last_mouse_pos = None

        self.event_hitboxes = []

        self.setMinimumHeight(60)
        self.setMaximumHeight(140)
        self.setMouseTracking(True)

        # load events if world model exists
        if self.world:
            self.load_events_from_world()

    # --------------------------------------------------
    # WORLD INTEGRATION
    # --------------------------------------------------

    def set_world_model(self, world_model):
        """
        Attach world model after widget creation.
        """
        self.world = world_model
        self.load_events_from_world()

    def load_events_from_world(self):
        """
        Pull events from world model.
        """

        if not self.world:
            return

        try:
            events = self.world.get_events()
        except Exception:
            return

        parsed = []

        for event in events.values():

            year = event.get("year")

            if year is None:
                continue

            parsed.append({
                "id": event.get("id"),
                "name": event.get("name", "Event"),
                "year": year
            })

        self.events = parsed
        self.update()

    def refresh_from_world(self):
        """
        Refresh timeline after world reload.
        """
        if self.world:
            self.load_events_from_world()

    # --------------------------------------------------
    # BASIC SETTINGS
    # --------------------------------------------------

    def set_range(self, start_year, end_year):

        self.timeline_start = start_year
        self.timeline_end = end_year
        self.clamp_pan()
        self.update()

    def set_current_year(self, year):

        self.current_year = year
        self.update()

    def set_events(self, events):

        # manual override
        self.events = events or []
        self.update()

    def set_active_entities(self, entities):

        self.active_entities = entities or []
        self.update()

    def register_entity(self, entity):

        entity_id = entity.get("id")

        if entity_id is None:
            return

        for e in self.active_entities:
            if e["id"] == entity_id:
                return

        self.active_entities.append(entity)
        self.update()

    def unregister_entity(self, entity_id):

        self.active_entities = [
            e for e in self.active_entities if e["id"] != entity_id
        ]

        self.update()

    def sizeHint(self):

        return self.minimumSizeHint()

    # --------------------------------------------------
    # TIMELINE CALCULATION
    # --------------------------------------------------

    def years_per_pixel(self):

        return self.base_years_per_pixel / self.zoom_factor

    def visible_year_span(self):

        return max(1.0, self.width() * self.years_per_pixel())

    def visible_start_year(self):

        return self.timeline_start + self.pan_offset

    def visible_end_year(self):

        return self.visible_start_year() + self.visible_year_span()

    def clamp_pan(self):

        full_span = max(1.0, self.timeline_end - self.timeline_start)
        visible_span = self.visible_year_span()

        if visible_span >= full_span:
            self.pan_offset = 0.0
            return

        max_offset = full_span - visible_span
        self.pan_offset = max(0.0, min(self.pan_offset, max_offset))

    def year_to_x(self, year):

        return (year - self.visible_start_year()) / self.years_per_pixel()

    def x_to_year(self, x):

        return self.visible_start_year() + (x * self.years_per_pixel())

    # --------------------------------------------------
    # INTERACTION
    # --------------------------------------------------

    def wheelEvent(self, event):

        old_mouse_year = self.x_to_year(event.position().x())

        zoom_step = 1.02

        if event.angleDelta().y() > 0:
            self.zoom_factor *= zoom_step
        else:
            self.zoom_factor /= zoom_step

        self.zoom_factor = max(
            self.min_zoom_factor,
            min(self.zoom_factor, self.max_zoom_factor)
        )

        new_mouse_year = self.x_to_year(event.position().x())
        self.pan_offset += (old_mouse_year - new_mouse_year)

        self.clamp_pan()
        self.update()

    def mousePressEvent(self, event):

        if event.button() == Qt.LeftButton:

            for event_id, rect in self.event_hitboxes:
                if rect.contains(event.position()):
                    self.event_clicked.emit(event_id)
                    event.accept()
                    return

            self._dragging = True
            self._last_mouse_pos = event.position()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):

        if self._dragging and self._last_mouse_pos is not None:

            dx = event.position().x() - self._last_mouse_pos.x()
            self.pan_offset -= dx * self.years_per_pixel()

            self._last_mouse_pos = event.position()

            self.clamp_pan()
            self.update()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):

        self._dragging = False
        self._last_mouse_pos = None
        super().mouseReleaseEvent(event)

    # --------------------------------------------------
    # GRID HELPERS
    # --------------------------------------------------

    def _grid_steps(self):

        span = self.visible_end_year() - self.visible_start_year()

        if span <= 0:
            return 1, 0.25

        import math

        magnitude = 10 ** math.floor(math.log10(span))
        normalized = span / magnitude

        if normalized < 2:
            major = magnitude / 10
        elif normalized < 5:
            major = magnitude / 5
        else:
            major = magnitude

        minor = major / 5

        if span < 5:
            return 1, 1 / 12

        return major, minor

    def _first_tick_at_or_after(self, start, step):

        tick = (start // step) * step
        if tick < start:
            tick += step
        return tick

    # --------------------------------------------------
    # EVENT CLUSTERING
    # --------------------------------------------------

    def _cluster_events(self, visible_events):

        if not visible_events:
            return []

        cluster_px = 24
        clusters = []

        for event_data in sorted(visible_events, key=lambda e: e.get("year", 0)):
            x = self.year_to_x(event_data.get("year", 0))

            if not clusters:
                clusters.append({"events": [event_data], "x": x})
                continue

            last = clusters[-1]

            if abs(x - last["x"]) <= cluster_px:
                last["events"].append(event_data)
                last["x"] = (
                    last["x"] * (len(last["events"]) - 1) + x
                ) / len(last["events"])
            else:
                clusters.append({"events": [event_data], "x": x})

        return clusters

    # --------------------------------------------------
    # PAINTING
    # --------------------------------------------------

    def paintEvent(self, event):

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        self.event_hitboxes = []

        painter.fillRect(self.rect(), QColor(248, 248, 248))

        margin_left = 24
        margin_right = 24

        lane_height = 10
        lane_gap = 5
        lanes_top = 8

        visible_entities = []
        visible_start = self.visible_start_year()
        visible_end = self.visible_end_year()

        for entity in self.active_entities:
            start = entity.get("start")
            end = entity.get("end")

            if start is None:
                continue

            if end is None:
                end = visible_end

            if end < visible_start or start > visible_end:
                continue

            visible_entities.append(entity)

        entity_area_height = 0
        if visible_entities:
            entity_area_height = len(visible_entities) * (lane_height + lane_gap) + 6

        top_margin = lanes_top + entity_area_height + 8
        line_y = h - 42

        usable_left = margin_left
        usable_right = w - margin_right

        # base line
        painter.setPen(QPen(QColor(60, 60, 60), 3))
        painter.drawLine(usable_left, line_y, usable_right, line_y)

        # visible events
        visible_events = []

        for event_data in self.events:
            year = event_data.get("year")

            if year is None:
                continue

            try:
                year = int(year)
            except Exception:
                continue

            if visible_start <= year <= visible_end:
                visible_events.append(event_data)

        clusters = self._cluster_events(visible_events)

        painter.setFont(QFont("Arial", 8))

        for cluster in clusters:
            cluster_events = cluster["events"]
            x = usable_left + cluster["x"]
            marker_y = line_y - 18

            if len(cluster_events) == 1:

                event_data = cluster_events[0]
                event_name = event_data.get("name", "Event")
                event_id = event_data.get("id", event_name)

                triangle = [
                    QPointF(x, marker_y - 8),
                    QPointF(x - 6, marker_y + 4),
                    QPointF(x + 6, marker_y + 4)
                ]

                painter.setPen(QPen(QColor(40, 90, 160), 1))
                painter.setBrush(QBrush(QColor(70, 120, 210)))
                painter.drawPolygon(triangle)

                label_rect = QRectF(x - 45, marker_y - 26, 90, 14)
                painter.setPen(QColor(40, 40, 40))
                painter.drawText(label_rect, Qt.AlignCenter, event_name[:16])

                hitbox = QRectF(x - 8, marker_y - 10, 16, 16)
                self.event_hitboxes.append((event_id, hitbox))

            else:

                count = len(cluster_events)
                circle_rect = QRectF(x - 10, marker_y - 10, 20, 20)

                painter.setPen(QPen(QColor(120, 80, 20), 1))
                painter.setBrush(QBrush(QColor(230, 180, 70)))
                painter.drawEllipse(circle_rect)

                painter.setPen(QColor(30, 30, 30))
                painter.drawText(circle_rect, Qt.AlignCenter, str(count))

                label_rect = QRectF(x - 50, marker_y - 28, 100, 14)
                painter.drawText(label_rect, Qt.AlignCenter, "Events")

                cluster_id = cluster_events[0].get(
                    "id",
                    cluster_events[0].get("name", "event_cluster")
                )

                self.event_hitboxes.append((cluster_id, circle_rect))