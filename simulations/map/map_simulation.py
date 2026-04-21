import math
import re
import time
from pathlib import Path

from engine.logger import logger


class MapSimulation:
    """
    Pure map simulation (entity-driven).

    In map mode, planets are rendered as 2D surface containers rather than
    physical spheres. Child regions are expected to use projected map-space
    coordinates inside that container.

    Selection ownership also lives here:
    * click handling is map-specific
    * picking is done in world/map coordinates
    * selected entity state is stored on the simulation
    * hover state is stored on the simulation

    Map-space convention:
    * 1 world unit is one projected longitude/latitude degree
    * Earth-facing map data stores X as longitude and Y as negative latitude
      so the renderer can stay in its native positive-Y-down coordinate system
    * planet roots use a 2:1 equirectangular frame derived from radius
    """

    MAP_KM_PER_WORLD_UNIT = 111.195
    MAP_METERS_PER_WORLD_UNIT = MAP_KM_PER_WORLD_UNIT * 1000.0
    MOUSEBUTTONDOWN_EVENT_TYPE = 1025
    MOUSEBUTTONUP_EVENT_TYPE = 1026
    DRAFT_DOUBLE_CLICK_SECONDS = 0.35
    DRAFT_DOUBLE_CLICK_DISTANCE_PX = 10.0
    POLYGON_POINT_HIT_RADIUS_PX = 10.0
    SQUARE_HANDLE_HIT_RADIUS_PX = 10.0
    MIN_SQUARE_SIDE_WORLD = 0.001

    DEFAULT_PLANET_WORLD_WIDTH = 4000.0
    DEFAULT_PLANET_WORLD_HEIGHT = 2000.0
    LOCATIONS_ENTRY_PATH = (
        Path(__file__).resolve().parents[2] / "entries" / "locations.yaml"
    )
    SPATIAL_FEATURES_ENTRY_PATH = (
        Path(__file__).resolve().parents[2] / "entries" / "spatial_features.yaml"
    )

    LOCATION_LAYER_KIND = "locations"

    LAYER_LABELS = {
        "locations": "Locations",
        "ecoregions": "Ecoregions",
        "faction_borders": "Faction Borders",
        "city_margins": "City Margins",
        "sites": "Sites",
    }

    SPATIAL_LAYER_COLORS = {
        "ecoregions": (74, 132, 82),
        "faction_borders": (150, 82, 82),
        "city_margins": (160, 142, 78),
        "sites": (86, 118, 158),
    }

    def __init__(self, simulation_context):
        from engine.clock import Clock
        from engine.simulation_manager import SimulationManager

        self.render_mode = "map"
        self.world_units_to_meters = self.MAP_METERS_PER_WORLD_UNIT

        self.context = simulation_context
        self.world_model = simulation_context.world_model

        self.sim_clock = Clock(base_dt=1.0)

        class _DummySystem:
            def update(self, dt):
                pass

        self.system = _DummySystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)

        self.min_zoom = 0.02
        self.max_zoom = 80.0
        self.preferred_zoom = 4.0

        self._layer_cache = None
        self._cache_year = None
        self._cache_layer_kind = None

        self.active_layer_kind = self.LOCATION_LAYER_KIND

        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        self.is_creating_spatial_feature = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self.is_editing_spatial_feature_polygon = False
        self.editing_spatial_feature_id = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self.is_creating_map_square = False
        self.map_square_anchor = None
        self.map_square_hover_pos = None
        self.last_saved_location_id = None
        self.is_editing_map_square = False
        self.editing_map_square_entity_id = None
        self.editing_map_square_bounds = None
        self.square_drag_handle = None
        self.square_drag_start_pos = None
        self.square_drag_start_bounds = None
        self.square_drag_opposite_point = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self._selection_last_click_time = None
        self._selection_last_click_screen_pos = None
        self._selection_last_click_target = None
        self._pending_inspector_target = None
        self.last_saved_spatial_feature_id = None

        self.bounds = self._resolve_root_bounds()

    @property
    def year(self):
        return getattr(self.context, "year", 0)

    def get_root_entity(self):
        return self.world_model.get_entity(self.context.root_entity_id)

    def get_root_name(self):
        root_entity = self.get_root_entity()
        if not root_entity:
            return self.context.root_entity_id
        return root_entity.get("name", self.context.root_entity_id)

    def get_parent_root_entity_id(self):
        root_entity = self.get_root_entity()
        if not root_entity:
            return None
        return root_entity.get("parent_location")

    def get_scope_breadcrumb(self):
        """
        Return a root breadcrumb from top ancestor down to the current root.
        """
        breadcrumb = []
        visited = set()
        current_entity = self.get_root_entity()

        while current_entity:
            entity_id = current_entity.get("id")
            if entity_id in visited:
                break

            visited.add(entity_id)
            breadcrumb.append(current_entity.get("name", entity_id))

            parent_id = current_entity.get("parent_location")
            if not parent_id:
                break

            current_entity = self.world_model.get_entity(parent_id)

        breadcrumb.reverse()
        return breadcrumb

    def _planet_world_size_from_radius(self, radius_m):
        """
        Derive a 2:1 projected planet frame from physical radius.

        Output world units follow the map convention:
        * 1 world unit ~= 1 projected longitude/latitude degree
        """
        radius_m = float(radius_m)

        circumference_m = 2.0 * math.pi * radius_m
        width_world = circumference_m / self.MAP_METERS_PER_WORLD_UNIT
        height_world = width_world / 2.0

        return width_world, height_world

    def _planet_canvas_size_from_radius(self, radius_m):
        """
        Derive the canonical planet map canvas size in pixels.

        Rule:
        * one projected degree-ish world unit per pixel
        * 2:1 aspect ratio
        """
        width_world, height_world = self._planet_world_size_from_radius(radius_m)

        width_px = max(1, int(round(width_world)))
        height_px = max(1, int(round(height_world)))

        return width_px, height_px

    def _planet_rect_from_entity(self, entity):
        """
        Resolve a planet rect from either bbox or radius data.
        """
        coords = entity.get("coords") or {}
        bounds = entity.get("bounds") or {}

        center_x = 0.0
        center_y = 0.0

        if coords.get("type") == "point":
            center_x = coords.get("x", 0.0)
            center_y = coords.get("y", 0.0)

        if bounds.get("type") == "bbox":
            min_x = bounds.get("min_x", -self.DEFAULT_PLANET_WORLD_WIDTH / 2)
            max_x = bounds.get("max_x", self.DEFAULT_PLANET_WORLD_WIDTH / 2)
            min_y = bounds.get("min_y", -self.DEFAULT_PLANET_WORLD_HEIGHT / 2)
            max_y = bounds.get("max_y", self.DEFAULT_PLANET_WORLD_HEIGHT / 2)

            width_world = max_x - min_x
            height_world = max_y - min_y

            if coords.get("type") != "point":
                center_x = (min_x + max_x) / 2.0
                center_y = (min_y + max_y) / 2.0

            center_x, center_y = self._map_point_to_world(center_x, center_y)
            canvas_w = entity.get("map_canvas_width_px", max(1, int(round(width_world))))
            canvas_h = entity.get("map_canvas_height_px", max(1, int(round(height_world))))

            return {
                "x": center_x,
                "y": center_y,
                "width_world": width_world,
                "height_world": height_world,
                "canvas_width_px": canvas_w,
                "canvas_height_px": canvas_h,
            }

        if bounds.get("type") == "radius":
            radius_m = bounds.get("value", 0.0)
            width_world, height_world = self._planet_world_size_from_radius(radius_m)
            canvas_w, canvas_h = self._planet_canvas_size_from_radius(radius_m)
            center_x, center_y = self._map_point_to_world(center_x, center_y)

            return {
                "x": center_x,
                "y": center_y,
                "width_world": width_world,
                "height_world": height_world,
                "canvas_width_px": canvas_w,
                "canvas_height_px": canvas_h,
            }

        center_x, center_y = self._map_point_to_world(center_x, center_y)
        return {
            "x": center_x,
            "y": center_y,
            "width_world": self.DEFAULT_PLANET_WORLD_WIDTH,
            "height_world": self.DEFAULT_PLANET_WORLD_HEIGHT,
            "canvas_width_px": int(self.DEFAULT_PLANET_WORLD_WIDTH),
            "canvas_height_px": int(self.DEFAULT_PLANET_WORLD_HEIGHT),
        }

    def _resolve_root_bounds(self):
        """
        Resolve one stable world-space rectangle for the current root scope.

        Rules:
        * bbox roots use their bbox directly
        * planet roots use bbox if present, otherwise derive a 2:1 frame from radius
        * point roots get a small synthetic scope so reset/clamping still work
        * final fallback is the default planet-sized rectangle around origin
        """
        root_entity = self.get_root_entity()
        if not root_entity:
            return {
                "min_x": -self.DEFAULT_PLANET_WORLD_WIDTH / 2,
                "max_x": self.DEFAULT_PLANET_WORLD_WIDTH / 2,
                "min_y": -self.DEFAULT_PLANET_WORLD_HEIGHT / 2,
                "max_y": self.DEFAULT_PLANET_WORLD_HEIGHT / 2,
            }

        coords = root_entity.get("coords") or {}
        bounds = root_entity.get("bounds") or {}

        if bounds.get("type") == "bbox":
            min_x = bounds.get("min_x", -self.DEFAULT_PLANET_WORLD_WIDTH / 2)
            max_x = bounds.get("max_x", self.DEFAULT_PLANET_WORLD_WIDTH / 2)
            min_y = bounds.get("min_y", -self.DEFAULT_PLANET_WORLD_HEIGHT / 2)
            max_y = bounds.get("max_y", self.DEFAULT_PLANET_WORLD_HEIGHT / 2)
            world_bounds = self._map_bbox_to_world_bounds(min_x, max_x, min_y, max_y)
            return {
                "min_x": world_bounds["min_x"],
                "max_x": world_bounds["max_x"],
                "min_y": world_bounds["min_y"],
                "max_y": world_bounds["max_y"],
            }

        center_x = 0.0
        center_y = 0.0
        if coords.get("type") == "point":
            center_x, center_y = self._map_point_to_world(
                coords.get("x", 0.0),
                coords.get("y", 0.0),
            )

        if root_entity.get("location_class") == "planet":
            rect = self._planet_rect_from_entity(root_entity)
            half_w = rect["width_world"] / 2.0
            half_h = rect["height_world"] / 2.0

            return {
                "min_x": rect["x"] - half_w,
                "max_x": rect["x"] + half_w,
                "min_y": rect["y"] - half_h,
                "max_y": rect["y"] + half_h,
            }

        if coords.get("type") == "point":
            point_half_extent = 500.0
            return {
                "min_x": center_x - point_half_extent,
                "max_x": center_x + point_half_extent,
                "min_y": center_y - point_half_extent,
                "max_y": center_y + point_half_extent,
            }

        return {
            "min_x": -self.DEFAULT_PLANET_WORLD_WIDTH / 2,
            "max_x": self.DEFAULT_PLANET_WORLD_WIDTH / 2,
            "min_y": -self.DEFAULT_PLANET_WORLD_HEIGHT / 2,
            "max_y": self.DEFAULT_PLANET_WORLD_HEIGHT / 2,
        }

    def _color_for_entity(self, entity):
        location_class = entity.get("location_class")

        if location_class == "planet":
            return (70, 90, 120)

        if location_class == "continent":
            return (120, 140, 170)

        if location_class == "country":
            return (155, 170, 195)

        if location_class == "region":
            return (180, 190, 205)

        if location_class == "city":
            return (220, 220, 220)

        return (200, 200, 200)

    def _map_point_to_world(self, x, y):
        """
        Convert stored map coordinates to display/world coordinates.

        This is intentionally identity now. Earth-facing YAML stores latitude
        as negative Y so the renderer does not need a hidden flip.
        """
        return float(x), float(y)

    def _world_point_to_map(self, x, y):
        return float(x), float(y)

    def _map_bbox_to_world_bounds(self, min_x, max_x, min_y, max_y):
        return {
            "min_x": min(float(min_x), float(max_x)),
            "max_x": max(float(min_x), float(max_x)),
            "min_y": min(float(min_y), float(max_y)),
            "max_y": max(float(min_y), float(max_y)),
        }

    def _invalidate_layer_cache(self):
        self._layer_cache = None
        self._cache_year = None
        self._cache_layer_kind = None

    def _format_layer_label(self, layer_kind):
        if layer_kind in self.LAYER_LABELS:
            return self.LAYER_LABELS[layer_kind]

        return str(layer_kind).replace("_", " ").title()

    def get_active_layer_kind(self):
        return self.active_layer_kind

    def get_active_layer_label(self):
        return self._format_layer_label(self.active_layer_kind)

    def get_available_layer_kinds(self):
        layer_kinds = [self.LOCATION_LAYER_KIND]

        for feature in self._get_scoped_spatial_features():
            layer_kind = feature.get("layer_kind")
            if layer_kind and layer_kind not in layer_kinds:
                layer_kinds.append(layer_kind)

        return layer_kinds

    def set_active_layer_kind(self, layer_kind):
        available = self.get_available_layer_kinds()
        if layer_kind not in available:
            layer_kind = self.LOCATION_LAYER_KIND

        if layer_kind == self.active_layer_kind:
            return False

        self.active_layer_kind = layer_kind
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.debug(
            f"[MapSimulation] Active layer changed to {self.get_active_layer_label()}",
            key="map_layer_change",
            interval=0.1
        )
        return True

    def cycle_active_layer_kind(self):
        available = self.get_available_layer_kinds()
        if not available:
            return False

        if self.active_layer_kind not in available:
            return self.set_active_layer_kind(self.LOCATION_LAYER_KIND)

        current_index = available.index(self.active_layer_kind)
        next_index = (current_index + 1) % len(available)
        return self.set_active_layer_kind(available[next_index])

    def get_spatial_feature(self, spatial_feature_id):
        if not spatial_feature_id:
            return None

        if str(spatial_feature_id).startswith("virtual:"):
            return None

        return self.world_model.get_entity(spatial_feature_id)

    def get_location(self, location_id):
        if not location_id:
            return None

        return self.world_model.get_entity(location_id)

    def _get_entity_bbox_bounds(self, entity):
        if not entity:
            return None

        bounds = entity.get("bounds") or {}
        if bounds.get("type") != "bbox":
            return None

        return {
            "min_x": float(bounds.get("min_x", 0.0)),
            "max_x": float(bounds.get("max_x", 0.0)),
            "min_y": float(bounds.get("min_y", 0.0)),
            "max_y": float(bounds.get("max_y", 0.0)),
        }

    def _can_inspect_location(self, location_id):
        if not location_id:
            return False

        if location_id == self.context.root_entity_id:
            return False

        entity = self.get_location(location_id)
        if not entity:
            return False

        if entity.get("_dataset") not in (None, "locations"):
            return False

        if entity.get("type") != "location":
            return False

        if entity.get("location_class") == "planet":
            return False

        return self._get_entity_bbox_bounds(entity) is not None

    def consume_pending_inspector_target(self):
        target = self._pending_inspector_target
        self._pending_inspector_target = None
        return target

    def can_create_spatial_feature_draft(self):
        return self.active_layer_kind != self.LOCATION_LAYER_KIND

    def can_create_map_square_draft(self):
        return self.active_layer_kind == self.LOCATION_LAYER_KIND

    def is_square_editor_active(self):
        return self.is_creating_map_square or self.is_editing_map_square

    def is_map_editor_active(self):
        return self.is_polygon_editor_active() or self.is_square_editor_active()

    def _reset_square_drag_state(self):
        self.square_drag_handle = None
        self.square_drag_start_pos = None
        self.square_drag_start_bounds = None
        self.square_drag_opposite_point = None

    def _set_all_editor_modes_inactive(self):
        self.is_creating_spatial_feature = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self.is_editing_spatial_feature_polygon = False
        self.editing_spatial_feature_id = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self.is_creating_map_square = False
        self.map_square_anchor = None
        self.map_square_hover_pos = None
        self.is_editing_map_square = False
        self.editing_map_square_entity_id = None
        self.editing_map_square_bounds = None
        self._reset_square_drag_state()

    def can_finish_map_editor(self):
        if self.is_creating_map_square:
            return self.can_finish_map_square_draft()

        if self.is_editing_map_square:
            return self.can_finish_map_square_edit()

        return self.can_finish_polygon_editor()

    def finish_map_editor(self):
        if self.is_creating_map_square:
            return self.finish_map_square_draft()

        if self.is_editing_map_square:
            return self.finish_map_square_edit()

        return self.finish_polygon_editor()

    def cancel_map_editor(self):
        if self.is_creating_map_square:
            return self.cancel_map_square_draft()

        if self.is_editing_map_square:
            return self.cancel_map_square_edit()

        return self.cancel_polygon_editor()

    def get_map_editor_status_label(self):
        if self.is_creating_map_square:
            if self.map_square_anchor is None:
                return "Draft rectangle: choose first corner"
            if self.can_finish_map_square_draft():
                return "Draft rectangle: ready"
            return "Draft rectangle: choose opposite corner"

        if self.is_editing_map_square:
            if self.square_drag_handle:
                return f"Edit rectangle: dragging {self.square_drag_handle}"
            return "Edit rectangle: drag a handle"

        if self.is_polygon_editor_active():
            return f"{self.get_polygon_editor_mode_label()}: {self.get_polygon_editor_point_count()} points"

        return ""

    def is_polygon_editor_active(self):
        return (
            self.is_creating_spatial_feature
            or self.is_editing_spatial_feature_polygon
        )

    def get_polygon_editor_points(self):
        if self.is_editing_spatial_feature_polygon:
            return self.editing_spatial_feature_points

        return self.draft_spatial_feature_points

    def get_polygon_editor_hover_point(self):
        if self.is_editing_spatial_feature_polygon:
            return self.editing_hover_map_pos

        return self.draft_hover_map_pos

    def get_polygon_editor_point_count(self):
        return len(self.get_polygon_editor_points())

    def get_polygon_editor_mode_label(self):
        if self.is_editing_spatial_feature_polygon:
            return "Edit polygon"

        if self.is_creating_spatial_feature:
            return "Draft selection"

        return "Polygon"

    def can_finish_polygon_editor(self):
        return (
            self.is_polygon_editor_active()
            and self.get_polygon_editor_point_count() >= 3
        )

    def can_finish_spatial_feature_draft(self):
        return (
            self.is_creating_spatial_feature
            and len(self.draft_spatial_feature_points) >= 3
        )

    def begin_spatial_feature_draft(self):
        if not self.can_create_spatial_feature_draft():
            return False

        self._set_all_editor_modes_inactive()
        self.is_creating_spatial_feature = True
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        logger.info(
            f"[MapSimulation] Started spatial feature draft "
            f"layer={self.active_layer_kind}"
        )
        return True

    def begin_map_square_draft(self):
        if not self.can_create_map_square_draft():
            return False

        self._set_all_editor_modes_inactive()
        self.is_creating_map_square = True
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        logger.info(
            f"[MapSimulation] Started map rectangle draft root={self.context.root_entity_id}"
        )
        return True

    def cancel_spatial_feature_draft(self):
        if not self.is_creating_spatial_feature:
            return False

        self.is_creating_spatial_feature = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None

        logger.info("[MapSimulation] Cancelled spatial feature draft")
        return True

    def cancel_map_square_draft(self):
        if not self.is_creating_map_square:
            return False

        self.is_creating_map_square = False
        self.map_square_anchor = None
        self.map_square_hover_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None

        logger.info("[MapSimulation] Cancelled map rectangle draft")
        return True

    def begin_location_square_edit(self, target_kind, target_id):
        if target_kind != "location":
            return False

        if not self._can_inspect_location(target_id):
            return False

        entity = self.get_location(target_id)
        bounds = self._get_entity_bbox_bounds(entity)
        if bounds is None:
            return False

        self._set_all_editor_modes_inactive()
        self.active_layer_kind = self.LOCATION_LAYER_KIND
        self.is_editing_map_square = True
        self.editing_map_square_entity_id = target_id
        self.editing_map_square_bounds = dict(bounds)
        self.selected_entity_id = target_id
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Started rectangle edit {target_id}")
        return True

    def cancel_map_square_edit(self):
        if not self.is_editing_map_square:
            return False

        target_id = self.editing_map_square_entity_id
        self.is_editing_map_square = False
        self.editing_map_square_entity_id = None
        self.editing_map_square_bounds = None
        self._reset_square_drag_state()
        self.selected_entity_id = target_id
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Cancelled rectangle edit {target_id}")
        return True

    def can_finish_map_square_edit(self):
        return (
            self.is_editing_map_square
            and self._square_bounds_side(self.editing_map_square_bounds)
            >= self.MIN_SQUARE_SIDE_WORLD
        )

    def finish_map_square_edit(self):
        if not self.can_finish_map_square_edit():
            return False

        target_id = self.editing_map_square_entity_id
        if not self._update_location_bounds(target_id, self.editing_map_square_bounds):
            return False

        self.is_editing_map_square = False
        self.editing_map_square_entity_id = None
        self.editing_map_square_bounds = None
        self._reset_square_drag_state()
        self.selected_entity_id = target_id
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()
        logger.info(f"[MapSimulation] Saved rectangle edit {target_id}")
        return True

    def begin_spatial_feature_polygon_edit(self, target_kind, target_id):
        if target_kind != "spatial_feature":
            return False

        if not self._is_real_spatial_feature_id(target_id):
            return False

        feature = self.get_spatial_feature(target_id)
        if feature is None:
            return False

        points = self._get_geometry_points(feature.get("geometry") or {})
        if len(points) < 3:
            return False

        layer_kind = feature.get("layer_kind")
        if layer_kind:
            self.active_layer_kind = layer_kind

        self.is_creating_spatial_feature = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self.is_editing_spatial_feature_polygon = True
        self.editing_spatial_feature_id = target_id
        self.editing_spatial_feature_points = list(points)
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = target_id
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Started polygon edit {target_id}")
        return True

    def cancel_spatial_feature_polygon_edit(self):
        if not self.is_editing_spatial_feature_polygon:
            return False

        target_id = self.editing_spatial_feature_id
        self.is_editing_spatial_feature_polygon = False
        self.editing_spatial_feature_id = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_spatial_feature_id = target_id
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Cancelled polygon edit {target_id}")
        return True

    def finish_spatial_feature_polygon_edit(self):
        if not self.is_editing_spatial_feature_polygon:
            return False

        if len(self.editing_spatial_feature_points) < 3:
            return False

        target_id = self.editing_spatial_feature_id
        if not self._update_spatial_feature_geometry(
            target_id,
            self.editing_spatial_feature_points,
        ):
            return False

        self.is_editing_spatial_feature_polygon = False
        self.editing_spatial_feature_id = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = target_id
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Saved polygon edit {target_id}")
        return True

    def finish_polygon_editor(self):
        if self.is_editing_spatial_feature_polygon:
            return self.finish_spatial_feature_polygon_edit()

        return self.finish_spatial_feature_draft()

    def cancel_polygon_editor(self):
        if self.is_editing_spatial_feature_polygon:
            return self.cancel_spatial_feature_polygon_edit()

        return self.cancel_spatial_feature_draft()

    def finish_spatial_feature_draft(self):
        if not self.can_finish_spatial_feature_draft():
            return False

        feature = self._build_draft_spatial_feature_record()

        try:
            self._append_spatial_feature_record(feature)
        except OSError as exc:
            logger.error(
                f"[MapSimulation] Failed to save spatial feature draft: {exc}"
            )
            return False

        self.is_creating_spatial_feature = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.last_saved_spatial_feature_id = feature["id"]
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = feature["id"]
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(
            f"[MapSimulation] Saved spatial feature draft {feature['id']}"
        )
        return True

    def finish_map_square_draft(self):
        if not self.can_finish_map_square_draft():
            return False

        location = self._build_draft_map_square_location_record()
        if location.get("bounds") is None:
            return False

        try:
            self._append_location_record(location)
        except OSError as exc:
            logger.error(
                f"[MapSimulation] Failed to save map rectangle draft: {exc}"
            )
            return False

        self.is_creating_map_square = False
        self.map_square_anchor = None
        self.map_square_hover_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.last_saved_location_id = location["id"]
        self.selected_entity_id = location["id"]
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Saved map rectangle draft {location['id']}")
        return True

    def get_spatial_feature_draft_preview(self):
        if not self.is_polygon_editor_active():
            return None

        editor_points = self.get_polygon_editor_points()
        preview_points = [
            self._map_point_to_world(x, y)
            for x, y in editor_points
        ]
        preview_hover_point = None
        editor_hover_point = self.get_polygon_editor_hover_point()
        if editor_hover_point is not None:
            preview_hover_point = self._map_point_to_world(
                editor_hover_point[0],
                editor_hover_point[1],
            )

        return {
            "points": preview_points,
            "hover_point": preview_hover_point,
            "layer_kind": self.active_layer_kind,
            "can_finish": self.can_finish_polygon_editor(),
            "area_label": self.get_draft_area_label(),
            "mode": "edit" if self.is_editing_spatial_feature_polygon else "draft",
        }

    def get_draft_area_label(self):
        editor_points = self.get_polygon_editor_points()
        if len(editor_points) < 3:
            return None

        area_square_meters = self._polygon_area_square_meters(editor_points)
        return self._format_area(area_square_meters)

    def _square_bounds_side(self, bounds):
        if bounds is None:
            return 0.0

        width = abs(float(bounds["max_x"]) - float(bounds["min_x"]))
        height = abs(float(bounds["max_y"]) - float(bounds["min_y"]))
        return min(width, height)

    def _square_bounds_area_label(self, bounds):
        points = self._square_bounds_to_points(bounds)
        if len(points) < 3:
            return None

        return self._format_area(self._polygon_area_square_meters(points))

    def _square_bounds_to_points(self, bounds):
        if bounds is None:
            return []

        return [
            (bounds["min_x"], bounds["min_y"]),
            (bounds["max_x"], bounds["min_y"]),
            (bounds["max_x"], bounds["max_y"]),
            (bounds["min_x"], bounds["max_y"]),
        ]

    def _square_bounds_center(self, bounds):
        return (
            (float(bounds["min_x"]) + float(bounds["max_x"])) / 2.0,
            (float(bounds["min_y"]) + float(bounds["max_y"])) / 2.0,
        )

    def _square_bounds_from_anchor_hover(self, anchor, hover):
        if anchor is None or hover is None:
            return None

        anchor_x, anchor_y = anchor
        hover_x, hover_y = hover
        dx = float(hover_x) - float(anchor_x)
        dy = float(hover_y) - float(anchor_y)
        width = abs(dx)
        height = abs(dy)
        if width < self.MIN_SQUARE_SIDE_WORLD or height < self.MIN_SQUARE_SIDE_WORLD:
            return None

        return {
            "min_x": min(float(anchor_x), float(hover_x)),
            "max_x": max(float(anchor_x), float(hover_x)),
            "min_y": min(float(anchor_y), float(hover_y)),
            "max_y": max(float(anchor_y), float(hover_y)),
        }

    def _square_handle_positions(self, bounds):
        if bounds is None:
            return {}

        center_x, center_y = self._square_bounds_center(bounds)
        return {
            "nw": (bounds["min_x"], bounds["min_y"]),
            "ne": (bounds["max_x"], bounds["min_y"]),
            "se": (bounds["max_x"], bounds["max_y"]),
            "sw": (bounds["min_x"], bounds["max_y"]),
            "center": (center_x, center_y),
        }

    def _square_opposite_point_for_handle(self, bounds, handle):
        handles = self._square_handle_positions(bounds)
        opposites = {
            "nw": "se",
            "ne": "sw",
            "se": "nw",
            "sw": "ne",
        }
        opposite_handle = opposites.get(handle)
        if opposite_handle is None:
            return None

        return handles.get(opposite_handle)

    def _current_map_square_bounds(self):
        if self.is_editing_map_square:
            return self.editing_map_square_bounds

        if self.is_creating_map_square:
            return self._square_bounds_from_anchor_hover(
                self.map_square_anchor,
                self.map_square_hover_pos,
            )

        return None

    def can_finish_map_square_draft(self):
        return (
            self.is_creating_map_square
            and self._current_map_square_bounds() is not None
        )

    def get_map_square_preview(self):
        if not self.is_square_editor_active():
            return None

        bounds = self._current_map_square_bounds()
        handles = []
        if bounds is not None:
            handles = [
                {"id": handle_id, "point": point}
                for handle_id, point in self._square_handle_positions(bounds).items()
            ]

        return {
            "mode": "edit" if self.is_editing_map_square else "draft",
            "bounds": bounds,
            "anchor_point": self.map_square_anchor,
            "hover_point": self.map_square_hover_pos,
            "handles": handles,
            "active_handle": self.square_drag_handle,
            "can_finish": self.can_finish_map_editor(),
            "area_label": self._square_bounds_area_label(bounds),
        }

    def _format_area(self, area_square_meters):
        area_square_meters = abs(float(area_square_meters))

        if area_square_meters >= 1_000_000:
            area_square_km = area_square_meters / 1_000_000
            if area_square_km >= 1_000_000:
                return f"{area_square_km / 1_000_000:.2f}M sq km"
            if area_square_km >= 10_000:
                return f"{area_square_km:,.0f} sq km"
            if area_square_km >= 100:
                return f"{area_square_km:,.1f} sq km"
            return f"{area_square_km:,.2f} sq km"

        if area_square_meters >= 10_000:
            return f"{area_square_meters / 10_000:,.2f} ha"

        return f"{area_square_meters:,.0f} sq m"

    def _get_existing_entity_ids(self):
        loader = getattr(self.world_model, "loader", None)
        entities = getattr(loader, "entities", None)

        if isinstance(entities, dict):
            return set(entities.keys())

        ids = set()
        for entity in self.world_model.get_active_entities(self.year):
            entity_id = entity.get("id")
            if entity_id:
                ids.add(entity_id)

        return ids

    def _sanitize_identifier_part(self, value):
        chars = []

        for char in str(value).lower():
            if char.isalnum():
                chars.append(char)
            elif chars and chars[-1] != "_":
                chars.append("_")

        sanitized = "".join(chars).strip("_")
        return sanitized or "selection"

    def _allocate_spatial_feature_draft_id(self):
        existing_ids = self._get_existing_entity_ids()
        root_id = self._sanitize_identifier_part(self.context.root_entity_id)
        layer_kind = self._sanitize_identifier_part(self.active_layer_kind)

        index = 1
        while True:
            feature_id = f"sf_draft_{layer_kind}_{root_id}_{index:03d}"
            if feature_id not in existing_ids:
                return feature_id, index
            index += 1

    def _allocate_location_draft_id(self):
        existing_ids = self._get_existing_entity_ids()
        root_id = self._sanitize_identifier_part(self.context.root_entity_id)

        index = 1
        while True:
            location_id = f"loc_draft_{root_id}_{index:03d}"
            if location_id not in existing_ids:
                return location_id, index
            index += 1

    def _build_draft_spatial_feature_record(self):
        feature_id, index = self._allocate_spatial_feature_draft_id()
        layer_label = self.get_active_layer_label()
        root_name = self.get_root_name()
        name = f"Draft {layer_label} Selection {index:03d}"
        notes = f"Draft polygon created from the {layer_label} map layer under {root_name}."

        return {
            "id": feature_id,
            "pretty_name": name,
            "name": name,
            "type": "spatial_feature",
            "notes": notes,
            "layer_kind": self.active_layer_kind,
            "parent_entity": self.context.root_entity_id,
            "geometry": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(self.draft_spatial_feature_points),
            },
            "start_year": self.year,
            "entry_status": "draft",
        }

    def _build_draft_map_square_location_record(self):
        location_id, index = self._allocate_location_draft_id()
        root_name = self.get_root_name()
        name = f"Draft Map Area {index:03d}"
        notes = f"Draft rectangle map area created under {root_name}."

        return {
            "id": location_id,
            "pretty_name": name,
            "name": name,
            "type": "location",
            "location_class": "region",
            "parent_location": self.context.root_entity_id,
            "notes": notes,
            "bounds": self._current_map_square_bounds(),
            "start_year": self.year,
            "entry_status": "draft",
        }

    def _format_yaml_scalar(self, value):
        if value is None:
            return "null"

        text = str(value).replace("'", "''")
        if "\n" in text:
            lines = text.splitlines()
            if not lines:
                return "''"
            return "|\n" + "\n".join(f"    {line}" for line in lines)

        if text == "":
            return "''"

        return f"'{text}'"

    def _format_yaml_field_lines(self, key, value):
        scalar = self._format_yaml_scalar(value)
        if scalar.startswith("|\n"):
            block_lines = scalar.splitlines()
            return [f"  {key}: {block_lines[0]}"] + block_lines[1:]

        return [f"  {key}: {scalar}"]

    def _format_yaml_number(self, value):
        number = float(value)
        text = f"{number:.3f}".rstrip("0").rstrip(".")
        return text or "0"

    def _format_spatial_feature_record_yaml(self, feature):
        lines = [
            "",
            f"# ---------- {feature['id']} | {feature['name']} ----------",
            f"- id: {feature['id']}",
        ]
        lines.extend(self._format_yaml_field_lines("pretty_name", feature["pretty_name"]))
        lines.extend(self._format_yaml_field_lines("name", feature["name"]))
        lines.extend([
            "  type: spatial_feature",
        ])
        lines.extend(self._format_yaml_field_lines("notes", feature["notes"]))
        lines.extend([
            f"  layer_kind: {feature['layer_kind']}",
            f"  parent_entity: {feature['parent_entity']}",
            "  geometry:",
            "    type: polygon",
            "    coordinate_space: map_world",
            "    points:",
        ])

        points = feature["geometry"]["points"]
        for x, y in points:
            lines.append(
                f"      - [{self._format_yaml_number(x)}, "
                f"{self._format_yaml_number(y)}]"
            )

        lines.extend(
            [
                f"  start_year: {feature['start_year']}",
                "  entry_status: draft",
            ]
        )

        return "\n".join(lines) + "\n"

    def _format_location_bounds_lines(self, bounds):
        return [
            "  bounds:",
            "    type: bbox",
            f"    min_x: {self._format_yaml_number(bounds['min_x'])}",
            f"    max_x: {self._format_yaml_number(bounds['max_x'])}",
            f"    min_y: {self._format_yaml_number(bounds['min_y'])}",
            f"    max_y: {self._format_yaml_number(bounds['max_y'])}",
        ]

    def _format_location_record_yaml(self, location):
        lines = [
            "",
            f"# ---------- {location['id']} | {location['name']} ----------",
            f"- id: {location['id']}",
        ]
        lines.extend(self._format_yaml_field_lines("pretty_name", location["pretty_name"]))
        lines.extend(self._format_yaml_field_lines("name", location["name"]))
        lines.extend([
            "  type: location",
            f"  location_class: {location['location_class']}",
            f"  parent_location: {location['parent_location']}",
        ])
        lines.extend(self._format_yaml_field_lines("notes", location["notes"]))
        lines.extend(self._format_location_bounds_lines(location["bounds"]))
        lines.extend([
            f"  start_year: {location['start_year']}",
            "  entry_status: draft",
        ])

        return "\n".join(lines) + "\n"

    def _append_spatial_feature_record(self, feature):
        entry_path = self.SPATIAL_FEATURES_ENTRY_PATH
        entry_path.parent.mkdir(parents=True, exist_ok=True)

        block = self._format_spatial_feature_record_yaml(feature)

        if entry_path.exists():
            existing_text = entry_path.read_text(encoding="utf-8")
        else:
            existing_text = "# ==================================================\n# SPATIAL FEATURES\n# ==================================================\n"

        separator = "" if existing_text.endswith("\n") else "\n"
        entry_path.write_text(existing_text + separator + block, encoding="utf-8")

    def _append_location_record(self, location):
        entry_path = self.LOCATIONS_ENTRY_PATH
        entry_path.parent.mkdir(parents=True, exist_ok=True)

        block = self._format_location_record_yaml(location)

        if entry_path.exists():
            existing_text = entry_path.read_text(encoding="utf-8")
        else:
            existing_text = "# ==================================================\n# LOCATIONS\n# ==================================================\n"

        separator = "" if existing_text.endswith("\n") else "\n"
        entry_path.write_text(existing_text + separator + block, encoding="utf-8")

    def save_selection_inspector_updates(self, target_kind, target_id, updates):
        if target_kind not in {"spatial_feature", "location"}:
            return False

        name = str(updates.get("name", "")).strip()
        notes = str(updates.get("notes", "")).strip()

        if not name:
            name = str(target_id)

        if target_kind == "spatial_feature":
            if not self._is_real_spatial_feature_id(target_id):
                return False

            updated = self._update_spatial_feature_text_fields(target_id, name, notes)
        else:
            if not self._can_inspect_location(target_id):
                return False

            updated = self._update_location_text_fields(target_id, name, notes)

        if not updated:
            return False

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()
        logger.info(f"[MapSimulation] Updated inspector fields {target_kind}:{target_id}")
        return True

    def _is_real_spatial_feature_id(self, spatial_feature_id):
        if not spatial_feature_id:
            return False

        return not str(spatial_feature_id).startswith("virtual:")

    def _find_yaml_entity_block(self, text, entity_id):
        start_pattern = rf"(?m)^- id: {re.escape(str(entity_id))}\s*$"
        start_match = re.search(start_pattern, text)
        if not start_match:
            return None

        next_match = re.search(r"(?m)^- id: ", text[start_match.end():])
        block_start = start_match.start()
        block_end = start_match.end() + next_match.start() if next_match else len(text)
        return block_start, block_end

    def _replace_yaml_field_in_block(self, block_text, key, value):
        lines = block_text.rstrip("\n").splitlines()
        new_field_lines = self._format_yaml_field_lines(key, value)

        target_prefix = f"  {key}:"
        index = 0
        while index < len(lines):
            if not lines[index].startswith(target_prefix):
                index += 1
                continue

            end_index = index + 1
            while end_index < len(lines):
                line = lines[end_index]
                if line.startswith("  ") and not line.startswith("    "):
                    break
                if line.startswith("- id: "):
                    break
                end_index += 1

            return "\n".join(lines[:index] + new_field_lines + lines[end_index:]) + "\n"

        insert_index = 1 if lines and lines[0].startswith("- id: ") else len(lines)
        return "\n".join(lines[:insert_index] + new_field_lines + lines[insert_index:]) + "\n"

    def _format_spatial_feature_geometry_lines(self, points):
        lines = [
            "  geometry:",
            "    type: polygon",
            "    coordinate_space: map_world",
            "    points:",
        ]
        for x, y in points:
            lines.append(
                f"      - [{self._format_yaml_number(x)}, "
                f"{self._format_yaml_number(y)}]"
            )

        return lines

    def _replace_yaml_geometry_in_block(self, block_text, points):
        lines = block_text.rstrip("\n").splitlines()
        new_geometry_lines = self._format_spatial_feature_geometry_lines(points)
        target_prefix = "  geometry:"

        index = 0
        while index < len(lines):
            if not lines[index].startswith(target_prefix):
                index += 1
                continue

            end_index = index + 1
            while end_index < len(lines):
                line = lines[end_index]
                if line.startswith("  ") and not line.startswith("    "):
                    break
                if line.startswith("- id: "):
                    break
                end_index += 1

            return "\n".join(lines[:index] + new_geometry_lines + lines[end_index:]) + "\n"

        insert_index = len(lines)
        for index, line in enumerate(lines):
            if line.startswith("  start_year:") or line.startswith("  entry_status:"):
                insert_index = index
                break

        return "\n".join(lines[:insert_index] + new_geometry_lines + lines[insert_index:]) + "\n"

    def _replace_yaml_bounds_in_block(self, block_text, bounds):
        lines = block_text.rstrip("\n").splitlines()
        new_bounds_lines = self._format_location_bounds_lines(bounds)
        target_prefix = "  bounds:"

        index = 0
        while index < len(lines):
            if not lines[index].startswith(target_prefix):
                index += 1
                continue

            end_index = index + 1
            while end_index < len(lines):
                line = lines[end_index]
                if line.startswith("  ") and not line.startswith("    "):
                    break
                if line.startswith("- id: "):
                    break
                end_index += 1

            return "\n".join(lines[:index] + new_bounds_lines + lines[end_index:]) + "\n"

        insert_index = len(lines)
        for index, line in enumerate(lines):
            if line.startswith("  start_year:") or line.startswith("  entry_status:"):
                insert_index = index
                break

        return "\n".join(lines[:insert_index] + new_bounds_lines + lines[insert_index:]) + "\n"

    def _update_spatial_feature_text_fields(self, spatial_feature_id, name, notes):
        entry_path = self.SPATIAL_FEATURES_ENTRY_PATH
        if not entry_path.exists():
            return False

        text = entry_path.read_text(encoding="utf-8")
        found = self._find_yaml_entity_block(text, spatial_feature_id)
        if found is None:
            return False

        block_start, block_end = found
        block = text[block_start:block_end]
        block = self._replace_yaml_field_in_block(block, "pretty_name", name)
        block = self._replace_yaml_field_in_block(block, "name", name)
        block = self._replace_yaml_field_in_block(block, "notes", notes)

        updated_text = text[:block_start] + block + text[block_end:].lstrip("\n")
        entry_path.write_text(updated_text, encoding="utf-8")
        return True

    def _update_location_text_fields(self, location_id, name, notes):
        entry_path = self.LOCATIONS_ENTRY_PATH
        if not entry_path.exists():
            return False

        text = entry_path.read_text(encoding="utf-8")
        found = self._find_yaml_entity_block(text, location_id)
        if found is None:
            return False

        block_start, block_end = found
        block = text[block_start:block_end]
        block = self._replace_yaml_field_in_block(block, "pretty_name", name)
        block = self._replace_yaml_field_in_block(block, "name", name)
        block = self._replace_yaml_field_in_block(block, "notes", notes)

        updated_text = text[:block_start] + block + text[block_end:].lstrip("\n")
        entry_path.write_text(updated_text, encoding="utf-8")
        return True

    def _update_spatial_feature_geometry(self, spatial_feature_id, points):
        entry_path = self.SPATIAL_FEATURES_ENTRY_PATH
        if not entry_path.exists():
            return False

        text = entry_path.read_text(encoding="utf-8")
        found = self._find_yaml_entity_block(text, spatial_feature_id)
        if found is None:
            return False

        block_start, block_end = found
        block = text[block_start:block_end]
        block = self._replace_yaml_geometry_in_block(block, points)

        updated_text = text[:block_start] + block + text[block_end:].lstrip("\n")
        entry_path.write_text(updated_text, encoding="utf-8")
        return True

    def _update_location_bounds(self, location_id, bounds):
        entry_path = self.LOCATIONS_ENTRY_PATH
        if not entry_path.exists():
            return False

        text = entry_path.read_text(encoding="utf-8")
        found = self._find_yaml_entity_block(text, location_id)
        if found is None:
            return False

        block_start, block_end = found
        block = text[block_start:block_end]
        block = self._replace_yaml_bounds_in_block(block, bounds)

        updated_text = text[:block_start] + block + text[block_end:].lstrip("\n")
        entry_path.write_text(updated_text, encoding="utf-8")
        return True

    def _is_draft_double_click(self, screen_pos):
        if self._draft_last_click_time is None:
            return False

        if self._draft_last_click_screen_pos is None:
            return False

        now = time.monotonic()
        if now - self._draft_last_click_time > self.DRAFT_DOUBLE_CLICK_SECONDS:
            return False

        last_x, last_y = self._draft_last_click_screen_pos
        dx = float(screen_pos[0]) - float(last_x)
        dy = float(screen_pos[1]) - float(last_y)
        distance_sq = dx * dx + dy * dy

        return distance_sq <= self.DRAFT_DOUBLE_CLICK_DISTANCE_PX ** 2

    def _record_draft_click(self, screen_pos):
        self._draft_last_click_time = time.monotonic()
        self._draft_last_click_screen_pos = screen_pos

    def _is_selection_double_click(self, target, screen_pos):
        if self._selection_last_click_time is None:
            return False

        if self._selection_last_click_screen_pos is None:
            return False

        if target != self._selection_last_click_target:
            return False

        now = time.monotonic()
        if now - self._selection_last_click_time > self.DRAFT_DOUBLE_CLICK_SECONDS:
            return False

        last_x, last_y = self._selection_last_click_screen_pos
        dx = float(screen_pos[0]) - float(last_x)
        dy = float(screen_pos[1]) - float(last_y)
        distance_sq = dx * dx + dy * dy

        return distance_sq <= self.DRAFT_DOUBLE_CLICK_DISTANCE_PX ** 2

    def _record_selection_click(self, target, screen_pos):
        self._selection_last_click_time = time.monotonic()
        self._selection_last_click_screen_pos = screen_pos
        self._selection_last_click_target = target

    def _entity_id_is_in_root_scope(self, entity_id):
        if not entity_id:
            return False

        entity = self.world_model.get_entity(entity_id)
        if not entity:
            return False

        return self.context._is_in_root_subtree(entity)

    def _spatial_feature_is_in_scope(self, feature):
        owner_entity_id = feature.get("owner_entity")
        parent_entity_id = feature.get("parent_entity")

        if self._entity_id_is_in_root_scope(owner_entity_id):
            return True

        if self._entity_id_is_in_root_scope(parent_entity_id):
            return True

        return False

    def _get_scoped_spatial_features(self):
        features = self.world_model.get_active_entities(
            self.year,
            dataset_name="spatial_features",
            entity_type="spatial_feature",
        )

        return [
            feature for feature in features
            if self._spatial_feature_is_in_scope(feature)
        ]

    def _color_for_spatial_layer(self, layer_kind):
        return self.SPATIAL_LAYER_COLORS.get(layer_kind, (120, 112, 145))

    def _get_geometry_points(self, geometry):
        geometry_type = geometry.get("type")

        if geometry_type == "polygon":
            points = geometry.get("points", [])
            return [
                (float(point[0]), float(point[1]))
                for point in points
                if isinstance(point, (list, tuple)) and len(point) >= 2
            ]

        if geometry_type == "bbox":
            min_x = float(geometry.get("min_x", 0.0))
            max_x = float(geometry.get("max_x", 0.0))
            min_y = float(geometry.get("min_y", 0.0))
            max_y = float(geometry.get("max_y", 0.0))
            return [
                (min_x, min_y),
                (max_x, min_y),
                (max_x, max_y),
                (min_x, max_y),
            ]

        return []

    def _polygon_area(self, points):
        if len(points) < 3:
            return 0.0

        total = 0.0
        previous_x, previous_y = points[-1]

        for x, y in points:
            total += (previous_x * y) - (x * previous_y)
            previous_x = x
            previous_y = y

        return abs(total) / 2.0

    def _polygon_area_square_meters(self, points):
        if len(points) < 3:
            return 0.0

        mean_latitude = 0.0
        for _lon, stored_y in points:
            mean_latitude += -float(stored_y)
        mean_latitude /= len(points)

        latitude_scale_m = self.MAP_METERS_PER_WORLD_UNIT
        longitude_scale_m = latitude_scale_m * max(
            0.01,
            abs(math.cos(math.radians(mean_latitude))),
        )
        projected_points = [
            (
                float(lon) * longitude_scale_m,
                -float(stored_y) * latitude_scale_m,
            )
            for lon, stored_y in points
        ]

        return self._polygon_area(projected_points)

    def _polygon_centroid(self, points):
        if not points:
            return 0.0, 0.0

        total_x = 0.0
        total_y = 0.0

        for x, y in points:
            total_x += x
            total_y += y

        count = max(1, len(points))
        return total_x / count, total_y / count

    def _root_bounds_as_polygon(self):
        bounds = self.bounds
        min_x = bounds["min_x"]
        max_x = bounds["max_x"]
        min_y = bounds["min_y"]
        max_y = bounds["max_y"]

        return [
            (min_x, min_y),
            (max_x, min_y),
            (max_x, max_y),
            (min_x, max_y),
        ]

    def _build_virtual_spatial_layer(self, layer_kind):
        root_entity = self.get_root_entity()
        if not root_entity:
            return None

        root_entity_id = root_entity.get("id")
        points = self._root_bounds_as_polygon()
        centroid_x, centroid_y = self._polygon_centroid(points)
        layer_label = self._format_layer_label(layer_kind)

        return {
            "shape": "polygon",
            "x": centroid_x,
            "y": centroid_y,
            "points": points,
            "name": f"{self.get_root_name()} {layer_label}",
            "entity_id": root_entity_id,
            "spatial_feature_id": f"virtual:{layer_kind}:{root_entity_id}",
            "layer_kind": layer_kind,
            "color": self._color_for_spatial_layer(layer_kind),
            "area_world": self._polygon_area(points),
            "resolution_m_per_pixel": None,
            "coverage_mode": "virtual_aggregate",
            "is_virtual_spatial_feature": True,
            "draw_order": -1000,
        }

    def _build_spatial_feature_layer(self, feature):
        if (
            self.is_editing_spatial_feature_polygon
            and feature.get("id") == self.editing_spatial_feature_id
        ):
            return None

        geometry = feature.get("geometry") or {}
        map_points = self._get_geometry_points(geometry)

        if len(map_points) < 3:
            return None

        points = [
            self._map_point_to_world(x, y)
            for x, y in map_points
        ]
        layer_kind = feature.get("layer_kind")
        centroid_x, centroid_y = self._polygon_centroid(points)

        return {
            "shape": "polygon",
            "x": centroid_x,
            "y": centroid_y,
            "points": points,
            "name": feature.get("name") or feature.get("pretty_name") or feature.get("id"),
            "entity_id": feature.get("owner_entity"),
            "spatial_feature_id": feature.get("id"),
            "layer_kind": layer_kind,
            "parent_entity": feature.get("parent_entity"),
            "color": self._color_for_spatial_layer(layer_kind),
            "area_world": self._polygon_area(map_points),
            "resolution_m_per_pixel": feature.get("resolution_m_per_pixel"),
            "coverage_mode": feature.get("coverage_mode"),
            "draw_order": feature.get("draw_order", 0),
            "notes": feature.get("notes"),
        }

    def _spatial_layer_sort_key(self, layer):
        is_virtual = 0 if layer.get("is_virtual_spatial_feature") else 1
        area_world = layer.get("area_world", 0.0)
        resolution = layer.get("resolution_m_per_pixel")

        if resolution is None:
            resolution = 0.0

        return (
            layer.get("draw_order", 0),
            is_virtual,
            -area_world,
            -float(resolution),
        )

    def _build_spatial_feature_layers(self, year, layer_kind):
        layers = []

        for feature in self._get_scoped_spatial_features():
            if feature.get("layer_kind") != layer_kind:
                continue

            layer = self._build_spatial_feature_layer(feature)
            if layer is not None:
                layers.append(layer)

        root_entity = self.get_root_entity()
        root_entity_id = root_entity.get("id") if root_entity else None
        has_authored_root_layer = any(
            layer.get("entity_id") == root_entity_id
            for layer in layers
        )

        if not has_authored_root_layer:
            virtual_layer = self._build_virtual_spatial_layer(layer_kind)
            if virtual_layer is not None:
                layers.append(virtual_layer)

        layers.sort(key=self._spatial_layer_sort_key)
        return layers

    def _build_layers(self, year):
        """
        Build render layers from active entities.

        Supported map geometry:
        * planet       -> map_rect surface container
        * bbox region  -> rect
        * point place  -> marker
        """
        if self.active_layer_kind != self.LOCATION_LAYER_KIND:
            return self._build_spatial_feature_layers(year, self.active_layer_kind)

        layers = []

        for entity in self.context.get_active_locations():
            if not entity:
                continue

            entity_id = entity.get("id")
            if (
                self.is_editing_map_square
                and entity_id == self.editing_map_square_entity_id
            ):
                continue

            coords = entity.get("coords") or {}
            bounds = entity.get("bounds") or {}

            x = None
            y = None

            if coords.get("type") == "point":
                x, y = self._map_point_to_world(
                    coords.get("x", 0),
                    coords.get("y", 0),
                )

            location_class = entity.get("location_class")
            color = self._color_for_entity(entity)

            if location_class == "planet":
                rect = self._planet_rect_from_entity(entity)

                layers.append({
                    "shape": "map_rect",
                    "x": rect["x"],
                    "y": rect["y"],
                    "width_world": rect["width_world"],
                    "height_world": rect["height_world"],
                    "canvas_width_px": rect["canvas_width_px"],
                    "canvas_height_px": rect["canvas_height_px"],
                    "name": entity.get("name"),
                    "entity_id": entity_id,
                    "color": color,
                })
                continue

            if bounds.get("type") == "bbox":
                min_x = bounds.get("min_x", 0)
                max_x = bounds.get("max_x", 0)
                min_y = bounds.get("min_y", 0)
                max_y = bounds.get("max_y", 0)

                width_world = max_x - min_x
                height_world = max_y - min_y

                if x is None or y is None:
                    x, y = self._map_point_to_world(
                        (min_x + max_x) / 2,
                        (min_y + max_y) / 2,
                    )

                layers.append({
                    "shape": "rect",
                    "x": x,
                    "y": y,
                    "width_world": width_world,
                    "height_world": height_world,
                    "name": entity.get("name"),
                    "entity_id": entity_id,
                    "color": color,
                })
                continue

            if x is None or y is None:
                continue

            layers.append({
                "shape": "marker",
                "x": x,
                "y": y,
                "min_screen_size": 8,
                "name": entity.get("name"),
                "entity_id": entity_id,
                "color": color,
            })

        return layers

    def get_layers(self):
        year = self.year

        if (
            self._layer_cache is None
            or self._cache_year != year
            or self._cache_layer_kind != self.active_layer_kind
        ):
            logger.debug(
                f"[MapSimulation] Rebuilding layer cache for year {year} "
                f"layer={self.active_layer_kind}",
                key="map_layers_build",
                interval=0.5
            )
            self._layer_cache = self._build_layers(year)
            self._cache_year = year
            self._cache_layer_kind = self.active_layer_kind

        return self._layer_cache

    def get_entries(self):
        entries = []

        for entity in self.context.get_active_locations():
            if not entity:
                continue

            entries.append({
                "entity": entity,
                "name": entity.get("name"),
                "entity_id": entity.get("id"),
            })

        return entries

    def _screen_to_world(self, camera, screen_pos):
        sx, sy = screen_pos

        world_x = (sx - camera.width / 2) / camera.zoom + camera.x
        world_y = (sy - camera.height / 2) / camera.zoom + camera.y

        return world_x, world_y

    def _point_in_rect_layer(self, world_x, world_y, layer):
        half_w = layer.get("width_world", 0) / 2
        half_h = layer.get("height_world", 0) / 2

        min_x = layer["x"] - half_w
        max_x = layer["x"] + half_w
        min_y = layer["y"] - half_h
        max_y = layer["y"] + half_h

        return min_x <= world_x <= max_x and min_y <= world_y <= max_y

    def _point_in_marker_layer(self, world_x, world_y, layer, camera):
        pick_radius_world = max(12.0 / max(camera.zoom, 1e-9), 8.0)

        dx = world_x - layer["x"]
        dy = world_y - layer["y"]

        return (dx * dx + dy * dy) <= (pick_radius_world * pick_radius_world)

    def _screen_points_for_polygon_layer(self, layer, camera):
        screen_points = []

        for point in layer.get("points", []):
            screen_point = camera.world_to_screen(point)
            if screen_point is None:
                return []

            screen_points.append((float(screen_point[0]), float(screen_point[1])))

        return screen_points

    def _point_near_segment(self, x, y, ax, ay, bx, by, tolerance):
        dx = bx - ax
        dy = by - ay
        length_sq = dx * dx + dy * dy

        if length_sq <= 1e-9:
            point_dx = x - ax
            point_dy = y - ay
            return (point_dx * point_dx + point_dy * point_dy) <= tolerance * tolerance

        t = ((x - ax) * dx + (y - ay) * dy) / length_sq
        t = max(0.0, min(1.0, t))

        closest_x = ax + t * dx
        closest_y = ay + t * dy
        point_dx = x - closest_x
        point_dy = y - closest_y

        return (point_dx * point_dx + point_dy * point_dy) <= tolerance * tolerance

    def _point_in_polygon_points(self, x, y, points, edge_tolerance=0.0):
        if len(points) < 3:
            return False

        if edge_tolerance > 0.0:
            previous_x, previous_y = points[-1]
            for current_x, current_y in points:
                if self._point_near_segment(
                    x,
                    y,
                    previous_x,
                    previous_y,
                    current_x,
                    current_y,
                    edge_tolerance,
                ):
                    return True

                previous_x = current_x
                previous_y = current_y

        inside = False
        previous_x, previous_y = points[-1]

        for current_x, current_y in points:
            y_crosses = (current_y > y) != (previous_y > y)
            if y_crosses:
                denominator = previous_y - current_y
                if abs(denominator) <= 1e-9:
                    previous_x = current_x
                    previous_y = current_y
                    continue

                x_at_y = (
                    (previous_x - current_x)
                    * (y - current_y)
                    / denominator
                    + current_x
                )
                if x < x_at_y:
                    inside = not inside

            previous_x = current_x
            previous_y = current_y

        return inside

    def _point_in_polygon_layer(self, world_x, world_y, layer):
        return self._point_in_polygon_points(
            x=world_x,
            y=world_y,
            points=layer.get("points", []),
        )

    def _point_in_polygon_layer_screen(self, screen_pos, layer, camera):
        screen_points = self._screen_points_for_polygon_layer(layer, camera)
        if not screen_points:
            return False

        return self._point_in_polygon_points(
            x=float(screen_pos[0]),
            y=float(screen_pos[1]),
            points=screen_points,
            edge_tolerance=3.0,
        )

    def _pick_layer_at_world(self, world_x, world_y, camera, screen_pos=None):
        """
        Pick from topmost to bottommost.

        Reverse iteration matters so that:
        * Berlin beats Germany
        * Germany beats Europe
        * Europe beats Earth
        """
        layers = self.get_layers()

        for layer in reversed(layers):
            shape = layer.get("shape", "marker")

            if shape in ("map_rect", "rect"):
                if self._point_in_rect_layer(world_x, world_y, layer):
                    return layer

            elif shape == "polygon":
                if screen_pos is not None:
                    if self._point_in_polygon_layer_screen(screen_pos, layer, camera):
                        return layer
                elif self._point_in_polygon_layer(world_x, world_y, layer):
                    return layer

            elif shape == "marker":
                if self._point_in_marker_layer(world_x, world_y, layer, camera):
                    return layer

        return None

    def _set_polygon_editor_hover_point(self, map_point):
        if self.is_editing_spatial_feature_polygon:
            self.editing_hover_map_pos = map_point
        elif self.is_creating_spatial_feature:
            self.draft_hover_map_pos = map_point

    def _append_polygon_editor_point(self, map_point):
        if self.is_editing_spatial_feature_polygon:
            self.editing_spatial_feature_points.append(map_point)
            return len(self.editing_spatial_feature_points)

        self.draft_spatial_feature_points.append(map_point)
        return len(self.draft_spatial_feature_points)

    def _delete_polygon_editor_point(self, index=None):
        points = self.get_polygon_editor_points()
        if not points:
            return False

        if index is None:
            index = len(points) - 1

        if index < 0 or index >= len(points):
            return False

        del points[index]
        return True

    def _polygon_editor_hit_point_index(self, screen_pos, camera):
        points = self.get_polygon_editor_points()
        if not points:
            return None

        best_index = None
        best_distance_sq = self.POLYGON_POINT_HIT_RADIUS_PX ** 2
        screen_x = float(screen_pos[0])
        screen_y = float(screen_pos[1])

        for index, map_point in enumerate(points):
            world_point = self._map_point_to_world(map_point[0], map_point[1])
            point_screen = camera.world_to_screen(world_point)
            if point_screen is None:
                continue

            dx = screen_x - float(point_screen[0])
            dy = screen_y - float(point_screen[1])
            distance_sq = dx * dx + dy * dy
            if distance_sq <= best_distance_sq:
                best_index = index
                best_distance_sq = distance_sq

        return best_index

    def _handle_polygon_editor_pointer_event(
        self,
        event,
        camera,
        screen_pos,
        world_x,
        world_y,
    ):
        if event.type != self.MOUSEBUTTONDOWN_EVENT_TYPE:
            return

        button = getattr(event, "button", None)
        map_point = self._world_point_to_map(world_x, world_y)
        hit_index = self._polygon_editor_hit_point_index(screen_pos, camera)

        if button == 3:
            deleted = self._delete_polygon_editor_point(hit_index)
            if deleted:
                self._set_polygon_editor_hover_point(map_point)
                self._record_draft_click(screen_pos)
                self._invalidate_layer_cache()
            return

        if button != 1:
            return

        if hit_index is not None and self.can_finish_polygon_editor():
            self.finish_polygon_editor()
            return

        if self._is_draft_double_click(screen_pos):
            if self.finish_polygon_editor():
                return

            self._record_draft_click(screen_pos)
            return

        point_count = self._append_polygon_editor_point(map_point)
        self._set_polygon_editor_hover_point(map_point)
        self._record_draft_click(screen_pos)
        self._invalidate_layer_cache()
        logger.debug(
            f"[MapSimulation] Polygon editor point added count={point_count}",
            key="map_polygon_editor_point",
            interval=0.1
        )

    def _square_editor_hit_handle(self, screen_pos, camera):
        bounds = self._current_map_square_bounds()
        if bounds is None:
            return None

        best_handle = None
        best_distance_sq = self.SQUARE_HANDLE_HIT_RADIUS_PX ** 2
        screen_x = float(screen_pos[0])
        screen_y = float(screen_pos[1])

        for handle_id, point in self._square_handle_positions(bounds).items():
            screen_point = camera.world_to_screen(point)
            if screen_point is None:
                continue

            dx = screen_x - float(screen_point[0])
            dy = screen_y - float(screen_point[1])
            distance_sq = dx * dx + dy * dy
            if distance_sq <= best_distance_sq:
                best_handle = handle_id
                best_distance_sq = distance_sq

        return best_handle

    def _move_square_bounds(self, bounds, dx, dy):
        return {
            "min_x": bounds["min_x"] + dx,
            "max_x": bounds["max_x"] + dx,
            "min_y": bounds["min_y"] + dy,
            "max_y": bounds["max_y"] + dy,
        }

    def _begin_square_drag(self, handle, map_point):
        bounds = self._current_map_square_bounds()
        if bounds is None:
            return False

        self.square_drag_handle = handle
        self.square_drag_start_pos = map_point
        self.square_drag_start_bounds = dict(bounds)
        self.square_drag_opposite_point = self._square_opposite_point_for_handle(
            bounds,
            handle,
        )
        return True

    def _update_square_drag(self, map_point):
        if not self.is_editing_map_square or self.square_drag_handle is None:
            return False

        if self.square_drag_handle == "center":
            start_pos = self.square_drag_start_pos
            start_bounds = self.square_drag_start_bounds
            if start_pos is None or start_bounds is None:
                return False

            dx = float(map_point[0]) - float(start_pos[0])
            dy = float(map_point[1]) - float(start_pos[1])
            self.editing_map_square_bounds = self._move_square_bounds(
                start_bounds,
                dx,
                dy,
            )
            return True

        opposite_point = self.square_drag_opposite_point
        if opposite_point is None:
            return False

        bounds = self._square_bounds_from_anchor_hover(opposite_point, map_point)
        if bounds is None:
            return False

        self.editing_map_square_bounds = bounds
        return True

    def _handle_square_editor_motion(self, map_point):
        if self.is_creating_map_square:
            self.map_square_hover_pos = map_point
            return

        if self.is_editing_map_square and self.square_drag_handle is not None:
            if self._update_square_drag(map_point):
                self._invalidate_layer_cache()

    def _handle_square_editor_pointer_event(
        self,
        event,
        camera,
        screen_pos,
        world_x,
        world_y,
    ):
        map_point = self._world_point_to_map(world_x, world_y)

        if self.is_creating_map_square:
            if event.type != self.MOUSEBUTTONDOWN_EVENT_TYPE:
                return

            button = getattr(event, "button", None)
            if button == 3:
                if self.map_square_anchor is None:
                    self.cancel_map_square_draft()
                else:
                    self.map_square_anchor = None
                    self.map_square_hover_pos = None
                self._record_draft_click(screen_pos)
                return

            if button != 1:
                return

            if self.map_square_anchor is None:
                self.map_square_anchor = map_point
                self.map_square_hover_pos = map_point
                self._record_draft_click(screen_pos)
                return

            self.map_square_hover_pos = map_point
            if self.finish_map_square_draft():
                return

            self._record_draft_click(screen_pos)
            return

        if not self.is_editing_map_square:
            return

        if event.type == self.MOUSEBUTTONDOWN_EVENT_TYPE:
            if getattr(event, "button", None) != 1:
                return

            handle = self._square_editor_hit_handle(screen_pos, camera)
            if handle is not None:
                self._begin_square_drag(handle, map_point)
            return

        if event.type == self.MOUSEBUTTONUP_EVENT_TYPE:
            if getattr(event, "button", None) == 1:
                self._reset_square_drag_state()

    def handle_pointer_motion(self, event, camera, screen_pos):
        """
        Update hover state from pointer motion.
        """
        world_x, world_y = self._screen_to_world(camera, screen_pos)

        if self.is_square_editor_active():
            map_point = self._world_point_to_map(world_x, world_y)
            self._handle_square_editor_motion(map_point)
            self.hover_entity_id = None
            self.hover_spatial_feature_id = None
            self.hover_screen_pos = screen_pos
            return

        if self.is_polygon_editor_active():
            self._set_polygon_editor_hover_point(self._world_point_to_map(world_x, world_y))
            self.hover_entity_id = None
            self.hover_spatial_feature_id = None
            self.hover_screen_pos = screen_pos
            return

        picked_layer = self._pick_layer_at_world(world_x, world_y, camera, screen_pos)

        if picked_layer is None:
            self.hover_entity_id = None
            self.hover_spatial_feature_id = None
            self.hover_screen_pos = None
            return

        self.hover_entity_id = picked_layer.get("entity_id")
        self.hover_spatial_feature_id = picked_layer.get("spatial_feature_id")
        self.hover_screen_pos = screen_pos

    def handle_pointer_event(self, event, camera, screen_pos):
        """
        Handle pointer input for the map simulation.

        This method receives screen coordinates from the app and performs
        picking in world/map coordinates.
        """
        world_x, world_y = self._screen_to_world(camera, screen_pos)

        if self.is_square_editor_active():
            self._handle_square_editor_pointer_event(
                event,
                camera,
                screen_pos,
                world_x,
                world_y,
            )
            return

        if self.is_polygon_editor_active():
            self._handle_polygon_editor_pointer_event(
                event,
                camera,
                screen_pos,
                world_x,
                world_y,
            )
            return

        picked_layer = self._pick_layer_at_world(world_x, world_y, camera, screen_pos)

        self.hover_screen_pos = screen_pos
        self.hover_entity_id = picked_layer.get("entity_id") if picked_layer else None
        self.hover_spatial_feature_id = picked_layer.get("spatial_feature_id") if picked_layer else None

        if picked_layer is None:
            self.selected_entity_id = None
            self.selected_spatial_feature_id = None
            return

        self.selected_entity_id = picked_layer.get("entity_id")
        self.selected_spatial_feature_id = picked_layer.get("spatial_feature_id")

        if (
            event.type == self.MOUSEBUTTONDOWN_EVENT_TYPE
            and getattr(event, "button", None) == 1
        ):
            target = None
            if (
                self.active_layer_kind == self.LOCATION_LAYER_KIND
                and self._can_inspect_location(self.selected_entity_id)
            ):
                target = ("location", self.selected_entity_id)
            elif self._is_real_spatial_feature_id(self.selected_spatial_feature_id):
                target = ("spatial_feature", self.selected_spatial_feature_id)

            if target is not None and self._is_selection_double_click(target, screen_pos):
                self._pending_inspector_target = {
                    "kind": target[0],
                    "id": target[1],
                }
                self._record_selection_click(None, None)
            else:
                self._record_selection_click(target, screen_pos)

        logger.debug(
            f"[MapSimulation] Selected entity={self.selected_entity_id} "
            f"spatial_feature={self.selected_spatial_feature_id}",
            key="map_selection",
            interval=0.1
        )

    def get_center(self):
        return (
            (self.bounds["min_x"] + self.bounds["max_x"]) / 2,
            (self.bounds["min_y"] + self.bounds["max_y"]) / 2,
        )

    def update(self, dt):
        self.sim_manager.update(dt)
