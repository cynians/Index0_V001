import math
import shutil
import time
from pathlib import Path

from engine.logger import logger
from world.year_utils import parse_year


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
    CAMERA_DRAG_THRESHOLD_PX = 4.0
    MIN_SQUARE_SIDE_WORLD = 0.001

    DEFAULT_PLANET_WORLD_WIDTH = 4000.0
    DEFAULT_PLANET_WORLD_HEIGHT = 2000.0
    MAP_ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets" / "maps" / "locations"

    LOCATION_LAYER_KIND = "locations"
    REGION_LAYER_KIND = "regions"
    GROUND_MATERIALS_LAYER_KIND = "ground_materials"

    LAYER_LABELS = {
        "locations": "Locations",
        "regions": "Regions",
        "ground_materials": "Ground Materials Layer",
    }

    SPATIAL_LAYER_COLORS = {
        "regions": (116, 132, 164),
        "ecoregions": (74, 132, 82),
        "faction_borders": (150, 82, 82),
        "political_control": (150, 82, 82),
        "settlement_extent": (92, 132, 184),
        "resource_claims": (158, 128, 72),
        "infrastructure_corridors": (138, 118, 170),
        "city_margins": (160, 142, 78),
        "sites": (86, 118, 158),
        "rooms": (112, 146, 172),
        "ground_materials": (156, 118, 74),
        "iron_ore": (178, 96, 70),
    }

    AUTHORABLE_HISTORY_LAYER_KINDS = [LOCATION_LAYER_KIND, GROUND_MATERIALS_LAYER_KIND]

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
        self.editing_polygon_target_kind = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self.is_evolving_spatial_feature_polygon = False
        self.evolving_source_spatial_feature_id = None
        self.is_placing_location_polygon = False
        self.placing_location_entity_id = None
        self.placing_location_points = []
        self.placing_hover_map_pos = None
        self.placement_ancestor_entity_ids = []
        self.return_to_repository_entity_id = None
        self.is_creating_map_square = False
        self.map_square_anchor = None
        self.map_square_hover_pos = None
        self.map_square_target_entity_id = None
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
        self.is_camera_dragging = False
        self.camera_drag_start_screen_pos = None
        self.camera_drag_start_camera_pos = None
        self.camera_drag_has_moved = False
        self.last_saved_spatial_feature_id = None

        self.bounds = self._resolve_root_bounds()

    @property
    def year(self):
        return getattr(self.context, "year", 0)

    def set_year(self, year):
        try:
            year = int(year)
        except (TypeError, ValueError):
            return False

        if self.is_map_editor_active():
            return False

        if year == self.year:
            return False

        self.context.year = year
        self.sim_clock.time = 0.0
        self.sim_clock.tick = 0
        self.sim_clock._accumulator = 0.0

        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._pending_inspector_target = None
        self._selection_last_click_time = None
        self._selection_last_click_screen_pos = None
        self._selection_last_click_target = None
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Selected history year {year}")
        return True

    def _repository_loader(self):
        return getattr(self.world_model, "loader", None) if self.world_model is not None else None

    def _persist_repository_entity(self, entity, dataset_name):
        loader = self._repository_loader()
        if loader is None or not hasattr(loader, "persist_entity"):
            return False
        entity["_dataset"] = dataset_name
        if not entity.get("type") and dataset_name == "locations":
            entity["type"] = "location"
        return loader.persist_entity(entity)

    def _update_repository_entity_fields(self, entity_id, updates):
        loader = self._repository_loader()
        entity = getattr(loader, "entities", {}).get(entity_id) if loader is not None else None
        if not isinstance(entity, dict):
            return False
        entity.update(updates)
        return loader.persist_entity(entity) if hasattr(loader, "persist_entity") else False

    def _remove_repository_entity(self, entity_id, dataset_name=None):
        loader = self._repository_loader()
        if loader is None or not hasattr(loader, "remove_entity"):
            return False
        return loader.remove_entity(entity_id, dataset_name=dataset_name)

    def get_year_context_label(self):
        year = int(self.year)
        root_entity = self.get_root_entity() or {}
        relative_context = self._get_relative_year_context(root_entity)

        if relative_context is None:
            return f"Year {year}"

        epoch_year = relative_context["epoch_year"]
        label = relative_context["label"]
        delta = year - epoch_year

        if delta == 0:
            return f"Year {year} | {label} +0"

        if delta > 0:
            return f"Year {year} | {delta} years since {label}"

        return f"Year {year} | {abs(delta)} years before {label}"

    def _get_relative_year_context(self, root_entity):
        if not root_entity:
            return None

        context_candidates = []
        for key in ("relative_year_context", "relative_time_context", "history_epoch"):
            value = root_entity.get(key)
            if isinstance(value, list):
                context_candidates.extend(value)
            elif isinstance(value, dict):
                context_candidates.append(value)

        for context in context_candidates:
            epoch_year = None
            for key in ("epoch_year", "start_year", "year"):
                epoch_year = self._normalize_year_value(context.get(key))
                if epoch_year is not None:
                    break

            if epoch_year is None:
                continue

            label = (
                context.get("label")
                or context.get("name")
                or context.get("description")
                or f"arrival on {self.get_root_name()}"
            )
            return {"epoch_year": epoch_year, "label": str(label)}

        epoch_year = None
        for key in (
            "history_epoch_year",
            "arrival_year",
            "settlement_start_year",
            "relative_year_start",
        ):
            epoch_year = self._normalize_year_value(root_entity.get(key))
            if epoch_year is not None:
                break

        if epoch_year is None:
            return None

        label = (
            root_entity.get("history_epoch_label")
            or root_entity.get("arrival_label")
            or f"arrival on {self.get_root_name()}"
        )
        return {"epoch_year": epoch_year, "label": str(label)}

    def _normalize_year_value(self, value):
        yearer = getattr(self.world_model, "yearer", None)
        if yearer is not None and hasattr(yearer, "normalize_year"):
            return yearer.normalize_year(value)

        return parse_year(value)

    def get_root_entity(self):
        return self.world_model.get_entity(self.context.root_entity_id)

    def get_root_name(self):
        root_entity = self.get_root_entity()
        if not root_entity:
            return self.context.root_entity_id
        return root_entity.get("name", self.context.root_entity_id)

    def _relation_entity_ids(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            candidate = value.get("location_id") or value.get("id") or value.get("entity_id") or value.get("target")
            return [candidate] if candidate else []
        if isinstance(value, (list, tuple, set)):
            ids = []
            for item in value:
                ids.extend(self._relation_entity_ids(item))
            return ids
        return []

    def _structural_parent_location_id(self, entity):
        if not isinstance(entity, dict):
            return None

        entity_id = entity.get("id")
        for field_key in ("parent_location", "parent_entity", "parent_body"):
            for parent_id in self._relation_entity_ids(entity.get(field_key)):
                parent = self.world_model.get_entity(parent_id)
                if parent_id and parent_id != entity_id and self._is_location_entity(parent):
                    return parent_id

        for parent_id in self._relation_entity_ids(entity.get("parents")):
            parent = self.world_model.get_entity(parent_id)
            if parent_id and parent_id != entity_id and self._is_location_entity(parent):
                return parent_id

        entities = getattr(getattr(self.world_model, "loader", None), "entities", {}) or {}
        for candidate_id, candidate in entities.items():
            if candidate_id == entity_id or not self._is_location_entity(candidate):
                continue
            if entity_id in self._relation_entity_ids(candidate.get("constituents")):
                return candidate_id

        return None

    def _is_location_entity(self, entity):
        return isinstance(entity, dict) and (
            entity.get("_dataset") == "locations"
            or entity.get("type") == "location"
        )

    def get_parent_root_entity_id(self):
        root_entity = self.get_root_entity()
        if not root_entity:
            return None
        return self._structural_parent_location_id(root_entity)

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

            parent_id = self._structural_parent_location_id(current_entity)
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

        radius_m = entity.get("radius_m")
        if radius_m not in (None, ""):
            try:
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
            except (TypeError, ValueError):
                pass

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

        if root_entity.get("location_class") == "building" and bounds.get("type") not in {"bbox", "polygon"}:
            return {
                "min_x": -24.0,
                "max_x": 24.0,
                "min_y": -16.0,
                "max_y": 16.0,
            }

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

        if bounds.get("type") == "polygon":
            points = self._get_geometry_points(bounds)
            if len(points) >= 3:
                xs = [point[0] for point in points]
                ys = [point[1] for point in points]
                world_bounds = self._map_bbox_to_world_bounds(min(xs), max(xs), min(ys), max(ys))
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
        card_color = self._coerce_hex_color(entity.get("card_color"))
        if card_color is not None:
            return card_color

        display_color = entity.get("display_color")
        if isinstance(display_color, (list, tuple)) and len(display_color) >= 3:
            try:
                return (int(display_color[0]), int(display_color[1]), int(display_color[2]))
            except (TypeError, ValueError):
                pass

        location_class = entity.get("location_class")

        if location_class == "planet":
            return (70, 90, 120)

        if location_class == "continent":
            return (120, 140, 170)

        if location_class == "country":
            return (155, 170, 195)

        if location_class == "state":
            return (166, 180, 202)

        if location_class == "region":
            return (180, 190, 205)

        if location_class == "city":
            return (220, 220, 220)

        if location_class == "quarter":
            return (212, 210, 198)

        if location_class == "building":
            return (202, 184, 136)

        if location_class == "room":
            return (132, 178, 196)

        return (200, 200, 200)

    def _entity_is_gas_giant(self, entity):
        atmosphere = entity.get("atmosphere_model") if isinstance(entity, dict) else None
        tags = set(entity.get("tags") or []) if isinstance(entity, dict) else set()
        return bool(
            entity.get("surface_render_mode") == "gas_giant_bands"
            or entity.get("map_render_mode") == "gas_giant_bands"
            or "gas_giant" in tags
            or (isinstance(atmosphere, dict) and atmosphere.get("has_solid_surface") is False)
        )

    def _gas_giant_bands_for_entity(self, entity):
        bands = entity.get("atmosphere_bands")
        if isinstance(bands, list) and bands:
            return bands
        atmosphere = entity.get("atmosphere_model")
        if isinstance(atmosphere, dict):
            try:
                from simulations.world_gen.natural_materials import atmospheric_band_palette

                return atmospheric_band_palette(atmosphere).get("bands") or []
            except ImportError:
                pass
        return []

    def _coerce_hex_color(self, value):
        if not isinstance(value, str):
            return None
        text = value.strip()
        if text.startswith("#"):
            text = text[1:]
        if len(text) != 6:
            return None
        try:
            return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            return None

    def _map_point_to_world(self, x, y):
        """
        Convert stored map coordinates to display/world coordinates.

        This is intentionally identity now. Earth-facing map data stores latitude
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

    def _root_is_building(self):
        root = self.get_root_entity()
        return isinstance(root, dict) and root.get("location_class") == "building"

    def _format_layer_label(self, layer_kind):
        if layer_kind in self.LAYER_LABELS:
            return self.LAYER_LABELS[layer_kind]

        return str(layer_kind).replace("_", " ").title()

    def get_initial_camera_zoom(self, screen_w, screen_h):
        bounds = getattr(self, "bounds", None) or {}
        try:
            world_w = abs(float(bounds["max_x"]) - float(bounds["min_x"]))
            world_h = abs(float(bounds["max_y"]) - float(bounds["min_y"]))
        except (KeyError, TypeError, ValueError):
            return self.preferred_zoom

        if world_w <= 0 or world_h <= 0:
            return self.preferred_zoom

        usable_w = max(120.0, float(screen_w) * 0.72)
        usable_h = max(120.0, float(screen_h) * 0.62)
        padding = 1.18 if self.is_placing_location_polygon else 1.32
        zoom = min(usable_w / (world_w * padding), usable_h / (world_h * padding))
        zoom = max(float(self.min_zoom), min(float(self.max_zoom), zoom))
        return zoom

    def get_active_layer_kind(self):
        available = self.get_available_layer_kinds()
        if available and self.active_layer_kind not in available:
            self.active_layer_kind = available[0]
        return self.active_layer_kind

    def get_active_layer_label(self):
        self.get_active_layer_kind()
        return self._format_layer_label(self.active_layer_kind)

    def get_available_layer_kinds(self):
        if self._root_is_building():
            return [self.LOCATION_LAYER_KIND]
        return [self.LOCATION_LAYER_KIND, self.GROUND_MATERIALS_LAYER_KIND]

    def set_active_layer_kind(self, layer_kind):
        available = self.get_available_layer_kinds()
        if layer_kind not in set(available):
            layer_kind = available[0] if available else self.LOCATION_LAYER_KIND
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

    def get_selection_inspector_payload(self):
        entity_id = self.selected_entity_id or self.selected_spatial_feature_id
        if not entity_id:
            return None

        entity = self.world_model.get_entity(entity_id)
        if entity is None:
            return {
                "entity_id": None,
                "title": str(entity_id).removeprefix("virtual:"),
                "kind": "Virtual map aggregate",
                "details": [f"Layer: {self.get_active_layer_label()}"],
                "actions": [],
            }

        entity_class = (
            entity.get("location_class")
            or entity.get("region_class")
            or entity.get("type", "map entity")
        )
        details = [
            f"Class: {entity_class}",
            f"Repository ID: {entity_id}",
            f"Layer: {self.get_active_layer_label()}",
        ]
        start_year = entity.get("start_year")
        end_year = entity.get("end_year")
        if start_year not in (None, "") or end_year not in (None, ""):
            active_start = start_year if start_year not in (None, "") else "?"
            active_end = end_year if end_year not in (None, "") else "present"
            details.append(f"Active: {active_start} to {active_end}")

        return {
            "entity_id": entity_id,
            "title": entity.get("pretty_name") or entity.get("name") or entity_id,
            "kind": "Map selection",
            "details": details,
            "actions": [
                {"id": "open_selection_wiki", "label": "Open Wiki Entry"},
            ],
        }

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

    def _can_open_location_inspector(self, location_id):
        if not location_id:
            return False

        entity = self.get_location(location_id)
        if not entity:
            return False

        if entity.get("_dataset") not in (None, "locations"):
            return False

        if entity.get("type") != "location":
            return False

        return True

    def _get_entity_rectangle_bounds(self, entity):
        if not entity or entity.get("location_class") not in {"planet", "moon"}:
            return None

        bounds = self._get_entity_bbox_bounds(entity)
        if bounds is not None:
            return bounds

        if entity.get("location_class") in {"planet", "moon"}:
            rect = self._planet_rect_from_entity(entity)
            half_w = rect["width_world"] / 2.0
            half_h = rect["height_world"] / 2.0
            return {
                "min_x": rect["x"] - half_w,
                "max_x": rect["x"] + half_w,
                "min_y": rect["y"] - half_h,
                "max_y": rect["y"] + half_h,
            }

        return None

    def _can_edit_location_bounds(self, location_id):
        if not self._can_open_location_inspector(location_id):
            return False

        entity = self.get_location(location_id)
        return self._get_entity_rectangle_bounds(entity) is not None

    def _map_image_target_entity_id(self):
        selected_entity = self.get_location(self.selected_entity_id)
        if (
            selected_entity is not None
            and selected_entity.get("_dataset") in (None, "locations")
            and selected_entity.get("type") == "location"
            and self._map_image_rect_from_entity(selected_entity) is not None
        ):
            return selected_entity.get("id")

        root_entity = self.get_root_entity()
        if root_entity is not None and self._map_image_rect_from_entity(root_entity) is not None:
            return root_entity.get("id")

        return None

    def _map_image_rect_from_entity(self, entity):
        if not isinstance(entity, dict):
            return None

        if entity.get("location_class") in {"planet", "moon"}:
            return self._planet_rect_from_entity(entity)

        bounds = self._get_entity_bbox_bounds(entity)
        if bounds is None:
            geometry = entity.get("bounds") or entity.get("geometry") or {}
            points = self._get_geometry_points(geometry)
            if len(points) < 3:
                return None

            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            bounds = {
                "min_x": min(xs),
                "max_x": max(xs),
                "min_y": min(ys),
                "max_y": max(ys),
            }

        min_x = bounds["min_x"]
        max_x = bounds["max_x"]
        min_y = bounds["min_y"]
        max_y = bounds["max_y"]
        x, y = self._map_point_to_world((min_x + max_x) / 2, (min_y + max_y) / 2)
        return {
            "x": x,
            "y": y,
            "width_world": max_x - min_x,
            "height_world": max_y - min_y,
        }

    def can_import_map_image(self):
        return self._map_image_target_entity_id() is not None

    def get_map_image_import_target_label(self):
        target = self.get_location(self._map_image_target_entity_id())
        if not target:
            return "Map Image"
        return target.get("pretty_name") or target.get("name") or target.get("id") or "Map Image"

    def _open_map_image_file_dialog(self):
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            return ""

        root = tk.Tk()
        root.withdraw()
        try:
            selected = filedialog.askopenfilename(
                title="Select map image",
                filetypes=[
                    ("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"),
                    ("All files", "*.*"),
                ],
            )
        finally:
            root.destroy()

        return selected or ""

    def _prompt_map_image_year(self):
        try:
            import tkinter as tk
            from tkinter import simpledialog
        except ImportError:
            return self.year

        root = tk.Tk()
        root.withdraw()
        try:
            value = simpledialog.askstring(
                "Date map image",
                "Map image year:",
                initialvalue=str(int(self.year)),
            )
        finally:
            root.destroy()

        if value is None:
            return None

        normalized = self._normalize_year_value(value.strip())
        return normalized if normalized is not None else self.year

    def _canonical_map_image_path(self, target_id, source_path, image_year):
        source = Path(source_path)
        suffix = source.suffix.lower() or ".png"
        safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(target_id)).strip("_") or "map"
        year_part = "undated" if image_year is None else str(int(image_year))
        target_dir = self.MAP_ASSET_ROOT / safe_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"base_map_{year_part}{suffix}"
        return target_path

    def _relative_project_path(self, path):
        project_root = Path(__file__).resolve().parents[2]
        try:
            return str(path.relative_to(project_root)).replace("\\", "/")
        except ValueError:
            return str(path)

    def import_map_image_for_current_target(self):
        target_id = self._map_image_target_entity_id()
        if not target_id:
            return False

        target = self.get_location(target_id)
        if target is None:
            return False

        source_path = self._open_map_image_file_dialog()
        if not source_path:
            return False

        image_year = self._prompt_map_image_year()
        if image_year is None:
            return False

        target_path = self._canonical_map_image_path(target_id, source_path, image_year)
        try:
            shutil.copy2(source_path, target_path)
        except OSError as exc:
            logger.error(f"[MapSimulation] Failed to copy map image: {exc}")
            return False

        relative_path = self._relative_project_path(target_path)
        updates = {
            "map_image_path": relative_path,
            "map_image_year": image_year,
            "map_image_fit": "stretch_to_bounds",
        }

        if not self._update_location_map_image_fields(target_id, updates):
            return False

        target.update(updates)
        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self.selected_entity_id = target_id
        self.selected_spatial_feature_id = None
        self._invalidate_layer_cache()
        logger.info(f"[MapSimulation] Imported map image for {target_id}: {relative_path}")
        return True

    def _can_inspect_location(self, location_id):
        return self._can_open_location_inspector(location_id)

    def consume_pending_inspector_target(self):
        target = self._pending_inspector_target
        self._pending_inspector_target = None
        return target

    def can_create_spatial_feature_draft(self):
        if self._root_is_building():
            return True
        return self.active_layer_kind in self.AUTHORABLE_HISTORY_LAYER_KINDS

    def get_spatial_feature_draft_button_label(self):
        if self._root_is_building():
            return "New Room"
        if self.active_layer_kind == self.LOCATION_LAYER_KIND:
            return "New Location"
        return f"New {self._format_layer_label(self.active_layer_kind)}"

    def can_create_map_square_draft(self):
        if self.active_layer_kind != self.LOCATION_LAYER_KIND:
            return False

        if self.selected_entity_id and self._can_edit_location_bounds(self.selected_entity_id):
            return True

        return self._can_edit_location_bounds(self.context.root_entity_id)

    def can_create_location_draft(self):
        return self.active_layer_kind == self.LOCATION_LAYER_KIND

    def _root_planet_has_map_dimensions(self):
        root_entity = self.get_root_entity()
        if not isinstance(root_entity, dict):
            return True

        if root_entity.get("location_class") not in {"planet", "moon"}:
            return True

        bounds = root_entity.get("bounds") or {}
        if bounds.get("type") in {"bbox", "polygon", "radius"}:
            return True

        if root_entity.get("radius_m") not in (None, ""):
            try:
                float(root_entity.get("radius_m"))
                return True
            except (TypeError, ValueError):
                pass

        canvas_w = root_entity.get("map_canvas_width_px")
        canvas_h = root_entity.get("map_canvas_height_px")
        if canvas_w not in (None, "") and canvas_h not in (None, ""):
            return True

        return False

    def _root_requires_dimension_rectangle(self):
        root_entity = self.get_root_entity()
        if not isinstance(root_entity, dict):
            return False

        return (
            root_entity.get("location_class") in {"planet", "moon"}
            and not self._root_planet_has_map_dimensions()
        )

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
        self.editing_polygon_target_kind = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self.is_evolving_spatial_feature_polygon = False
        self.evolving_source_spatial_feature_id = None
        self.is_placing_location_polygon = False
        self.placing_location_entity_id = None
        self.placing_location_points = []
        self.placing_hover_map_pos = None
        self.placement_ancestor_entity_ids = []
        self.is_creating_map_square = False
        self.map_square_anchor = None
        self.map_square_hover_pos = None
        self.map_square_target_entity_id = None
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
            noun = "Planet dimensions" if self.map_square_target_entity_id else "Draft rectangle"
            if self.map_square_anchor is None:
                return f"{noun}: choose first corner"
            if self.can_finish_map_square_draft():
                return f"{noun}: ready"
            return f"{noun}: choose opposite corner"

        if self.is_editing_map_square:
            if self.square_drag_handle:
                return f"Edit rectangle: dragging {self.square_drag_handle}"
            return "Edit rectangle: drag a handle"

        if self.is_polygon_editor_active():
            return f"{self.get_polygon_editor_mode_label()}: {self.get_polygon_editor_point_count()} points"

        return ""

    def consume_repository_return_entity_id(self):
        entity_id = self.return_to_repository_entity_id
        self.return_to_repository_entity_id = None
        return entity_id

    def is_polygon_editor_active(self):
        return (
            self.is_creating_spatial_feature
            or self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
            or self.is_placing_location_polygon
        )

    def get_polygon_editor_points(self):
        if self.is_placing_location_polygon:
            return self.placing_location_points

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            return self.editing_spatial_feature_points

        return self.draft_spatial_feature_points

    def get_polygon_editor_hover_point(self):
        if self.is_placing_location_polygon:
            return self.placing_hover_map_pos

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            return self.editing_hover_map_pos

        return self.draft_hover_map_pos

    def get_polygon_editor_point_count(self):
        return len(self.get_polygon_editor_points())

    def get_polygon_editor_mode_label(self):
        if self.is_placing_location_polygon:
            return "Place on parent"

        if self.is_evolving_spatial_feature_polygon:
            return "Evolve region"

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

        if self.selected_entity_id and self._can_edit_location_bounds(self.selected_entity_id):
            return self.begin_location_square_edit("location", self.selected_entity_id)

        if self._can_edit_location_bounds(self.context.root_entity_id):
            return self.begin_location_square_edit("location", self.context.root_entity_id)

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

    def begin_location_draft(self):
        if not self.can_create_location_draft():
            return False

        if not self._root_requires_dimension_rectangle():
            return self.begin_spatial_feature_draft()

        self._set_all_editor_modes_inactive()
        self.is_creating_map_square = True
        self.map_square_target_entity_id = self.context.root_entity_id
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        logger.info(
            f"[MapSimulation] Started planet dimension rectangle draft root={self.context.root_entity_id}"
        )
        return True

    def begin_location_parent_polygon_placement(self, location_id, return_to_repository=True):
        location = self.get_location(location_id)
        if not location:
            return False

        if location.get("_dataset") not in (None, "locations"):
            return False

        if location.get("type") != "location":
            return False

        parent_location = self._structural_parent_location_id(location)
        if parent_location != self.context.root_entity_id:
            return False

        bounds = location.get("bounds") or {}
        points = []
        if bounds.get("type") == "polygon":
            points = self._get_geometry_points(bounds)
        elif bounds.get("type") == "bbox":
            points = self._get_geometry_points(bounds)

        self._set_all_editor_modes_inactive()
        self.active_layer_kind = self.LOCATION_LAYER_KIND
        self.is_placing_location_polygon = True
        self.placing_location_entity_id = location_id
        self.placing_location_points = list(points)
        self.placing_hover_map_pos = None
        self.placement_ancestor_entity_ids = self._placement_ancestor_ids(parent_location)
        self.return_to_repository_entity_id = location_id if return_to_repository else None
        self.selected_entity_id = location_id
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Started parent placement polygon {location_id}")
        return True

    def _placement_ancestor_ids(self, parent_location_id):
        ancestor_ids = []
        visited = set()
        current = self.world_model.get_entity(parent_location_id)
        while current:
            current_id = current.get("id")
            parent_id = self._structural_parent_location_id(current)
            if not parent_id or parent_id in visited:
                break

            visited.add(parent_id)
            parent = self.world_model.get_entity(parent_id)
            if not parent:
                break

            ancestor_ids.append(parent_id)
            current = parent

        return ancestor_ids

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
        self.map_square_target_entity_id = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None

        logger.info("[MapSimulation] Cancelled map rectangle draft")
        return True

    def cancel_location_parent_polygon_placement(self):
        if not self.is_placing_location_polygon:
            return False

        target_id = self.placing_location_entity_id
        self.is_placing_location_polygon = False
        self.placing_location_entity_id = None
        self.placing_location_points = []
        self.placing_hover_map_pos = None
        self.placement_ancestor_entity_ids = []
        self.selected_entity_id = target_id
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Cancelled parent placement polygon {target_id}")
        return True

    def begin_location_square_edit(self, target_kind, target_id):
        if target_kind != "location":
            return False

        if not self._can_edit_location_bounds(target_id):
            return False

        entity = self.get_location(target_id)
        bounds = self._get_entity_rectangle_bounds(entity)
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
        if target_kind not in {"spatial_feature", "location"}:
            return False

        if target_kind == "spatial_feature":
            if not self._is_real_spatial_feature_id(target_id):
                return False

            feature = self.get_spatial_feature(target_id)
            if feature is None:
                return False
            points = self._get_geometry_points(feature.get("geometry") or feature.get("bounds") or {})
        else:
            if not self._can_open_location_inspector(target_id):
                return False

            feature = self.get_location(target_id)
            if feature is None:
                return False
            points = self._get_geometry_points(feature.get("bounds") or feature.get("geometry") or {})

        if len(points) < 3:
            return False

        layer_kind = feature.get("layer_kind")
        if layer_kind:
            self.active_layer_kind = layer_kind
        elif target_kind == "location":
            self.active_layer_kind = self.LOCATION_LAYER_KIND

        self.is_creating_spatial_feature = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self.is_evolving_spatial_feature_polygon = False
        self.evolving_source_spatial_feature_id = None
        self.is_editing_spatial_feature_polygon = True
        self.editing_spatial_feature_id = target_id
        self.editing_polygon_target_kind = target_kind
        self.editing_spatial_feature_points = list(points)
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = target_id if target_kind == "location" else None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = target_id if target_kind == "spatial_feature" else None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Started polygon edit {target_id}")
        return True

    def begin_spatial_feature_evolution(self, target_kind, target_id):
        if target_kind != "spatial_feature":
            return False

        if not self._is_real_spatial_feature_id(target_id):
            return False

        feature = self.get_spatial_feature(target_id)
        if feature is None:
            return False

        source_start_year = self._normalize_year_value(feature.get("start_year"))
        source_end_year = self._normalize_year_value(feature.get("end_year"))
        selected_year = int(self.year)

        if source_start_year is not None and selected_year <= source_start_year:
            return False

        if source_end_year is not None and selected_year > source_end_year:
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
        self.is_editing_spatial_feature_polygon = False
        self.is_evolving_spatial_feature_polygon = True
        self.evolving_source_spatial_feature_id = target_id
        self.editing_spatial_feature_id = target_id
        self.editing_polygon_target_kind = "spatial_feature"
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

        logger.info(
            f"[MapSimulation] Started spatial feature evolution "
            f"{target_id} year={selected_year}"
        )
        return True

    def cancel_spatial_feature_polygon_edit(self):
        if not (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            return False

        target_id = self.editing_spatial_feature_id
        was_evolving = self.is_evolving_spatial_feature_polygon
        self.is_editing_spatial_feature_polygon = False
        self.is_evolving_spatial_feature_polygon = False
        self.evolving_source_spatial_feature_id = None
        self.editing_spatial_feature_id = None
        self.editing_polygon_target_kind = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_spatial_feature_id = target_id
        self._invalidate_layer_cache()

        action_label = "evolution" if was_evolving else "edit"
        logger.info(f"[MapSimulation] Cancelled polygon {action_label} {target_id}")
        return True

    def finish_spatial_feature_polygon_edit(self):
        if self.is_evolving_spatial_feature_polygon:
            return self.finish_spatial_feature_evolution()

        if not self.is_editing_spatial_feature_polygon:
            return False

        if len(self.editing_spatial_feature_points) < 3:
            return False

        target_id = self.editing_spatial_feature_id
        target_kind = self.editing_polygon_target_kind or "spatial_feature"
        points = self.editing_spatial_feature_points
        if target_kind == "location":
            bounds = {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(points),
            }
            updated = (
                self._update_location_bounds(target_id, bounds)
                and self._update_location_geometry(target_id, points)
            )
        else:
            updated = self._update_spatial_feature_geometry(target_id, points)

        if not updated:
            return False

        self.is_editing_spatial_feature_polygon = False
        self.editing_spatial_feature_id = None
        self.editing_polygon_target_kind = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = target_id if target_kind == "location" else None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = target_id if target_kind == "spatial_feature" else None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Saved polygon edit {target_id}")
        return True

    def finish_spatial_feature_evolution(self):
        if not self.is_evolving_spatial_feature_polygon:
            return False

        if len(self.editing_spatial_feature_points) < 3:
            return False

        source_id = self.evolving_source_spatial_feature_id
        source_feature = self.get_spatial_feature(source_id)
        if source_feature is None:
            return False

        selected_year = int(self.year)
        source_start_year = self._normalize_year_value(source_feature.get("start_year"))
        if source_start_year is not None and selected_year <= source_start_year:
            return False

        evolved_feature = self._build_evolved_spatial_feature_record(
            source_feature,
            self.editing_spatial_feature_points,
        )
        source_end_year = selected_year - 1

        try:
            if not self._update_spatial_feature_end_year(source_id, source_end_year):
                return False
            self._append_location_record(evolved_feature)
        except OSError as exc:
            logger.error(
                f"[MapSimulation] Failed to save spatial feature evolution: {exc}"
            )
            return False

        self.is_editing_spatial_feature_polygon = False
        self.is_evolving_spatial_feature_polygon = False
        self.evolving_source_spatial_feature_id = None
        self.editing_spatial_feature_id = None
        self.editing_polygon_target_kind = None
        self.editing_spatial_feature_points = []
        self.editing_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.selected_entity_id = None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = evolved_feature["id"]
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(
            f"[MapSimulation] Saved spatial feature evolution "
            f"{source_id} -> {evolved_feature['id']}"
        )
        return True

    def finish_location_parent_polygon_placement(self):
        if not self.is_placing_location_polygon:
            return False

        if len(self.placing_location_points) < 3:
            return False

        target_id = self.placing_location_entity_id
        parent_id = self._smallest_placement_parent_for_points(
            self.placing_location_points
        )
        bounds = {
            "type": "polygon",
            "coordinate_space": "map_world",
            "points": list(self.placing_location_points),
        }
        if parent_id and not self._update_location_parent(target_id, parent_id):
            return False

        if not self._update_location_bounds(target_id, bounds):
            return False

        target = self.get_location(target_id)
        if target is not None:
            if parent_id:
                target["parent_location"] = parent_id
            target["bounds"] = bounds

        self.is_placing_location_polygon = False
        self.placing_location_entity_id = None
        self.placing_location_points = []
        self.placing_hover_map_pos = None
        self.placement_ancestor_entity_ids = []
        self.selected_entity_id = target_id
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Saved parent placement polygon {target_id}")
        return True

    def _smallest_placement_parent_for_points(self, points):
        candidate_ids = [self.context.root_entity_id]
        for entity_id in self.placement_ancestor_entity_ids:
            if entity_id not in candidate_ids:
                candidate_ids.append(entity_id)

        containing_candidates = []
        for entity_id in candidate_ids:
            entity = self.get_location(entity_id)
            if not entity:
                continue

            candidate_points = self._location_container_points(entity)
            if len(candidate_points) < 3:
                continue

            if not self._polygon_contains_points(candidate_points, points):
                continue

            containing_candidates.append((
                self._polygon_area(candidate_points),
                entity_id,
            ))

        if not containing_candidates:
            return self.context.root_entity_id

        containing_candidates.sort(key=lambda item: item[0])
        return containing_candidates[0][1]

    def _location_container_points(self, entity):
        bounds = entity.get("bounds") or {}
        if bounds.get("type") in {"bbox", "polygon"}:
            return self._get_geometry_points(bounds)

        if entity.get("location_class") == "planet":
            rect = self._planet_rect_from_entity(entity)
            half_w = rect["width_world"] / 2.0
            half_h = rect["height_world"] / 2.0
            return [
                (rect["x"] - half_w, rect["y"] - half_h),
                (rect["x"] + half_w, rect["y"] - half_h),
                (rect["x"] + half_w, rect["y"] + half_h),
                (rect["x"] - half_w, rect["y"] + half_h),
            ]

        return []

    def _polygon_contains_points(self, container_points, points):
        if len(container_points) < 3 or len(points) < 3:
            return False

        return all(
            self._point_in_polygon_points(
                point[0],
                point[1],
                container_points,
                edge_tolerance=1e-9,
            )
            for point in points
        )

    def finish_polygon_editor(self):
        if self.is_placing_location_polygon:
            return self.finish_location_parent_polygon_placement()

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            return self.finish_spatial_feature_polygon_edit()

        return self.finish_spatial_feature_draft()

    def cancel_polygon_editor(self):
        if self.is_placing_location_polygon:
            return self.cancel_location_parent_polygon_placement()

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            return self.cancel_spatial_feature_polygon_edit()

        return self.cancel_spatial_feature_draft()

    def finish_spatial_feature_draft(self):
        if not self.can_finish_spatial_feature_draft():
            return False

        region = self._build_draft_spatial_feature_record()
        is_location_layer = region.get("layer_kind") == self.LOCATION_LAYER_KIND

        try:
            self._append_location_record(region)
            linked_parent = self._append_offspring_reference_to_location(
                self.context.root_entity_id,
                region["id"],
            )
        except OSError as exc:
            logger.error(
                f"[MapSimulation] Failed to save region draft: {exc}"
            )
            return False
        if not linked_parent:
            logger.info(
                f"[MapSimulation] Saved {region['id']} without parent offspring link "
                f"parent={self.context.root_entity_id}"
            )

        self.is_creating_spatial_feature = False
        self.draft_spatial_feature_points = []
        self.draft_hover_map_pos = None
        self._draft_last_click_time = None
        self._draft_last_click_screen_pos = None
        self.last_saved_spatial_feature_id = region["id"]
        self.selected_entity_id = region["id"] if is_location_layer else None
        self.hover_entity_id = None
        self.selected_spatial_feature_id = None if is_location_layer else region["id"]
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()

        logger.info(
            f"[MapSimulation] Saved location draft {region['id']}"
        )
        return True

    def finish_map_square_draft(self):
        if not self.can_finish_map_square_draft():
            return False

        target_entity_id = self.map_square_target_entity_id
        if target_entity_id:
            bounds = self._current_map_square_bounds()
            if bounds is None:
                return False

            if not self._update_location_bounds(target_entity_id, bounds):
                logger.error(
                    f"[MapSimulation] Failed to save planet dimensions: {target_entity_id}"
                )
                return False

            self.is_creating_map_square = False
            self.map_square_anchor = None
            self.map_square_hover_pos = None
            self.map_square_target_entity_id = None
            self._draft_last_click_time = None
            self._draft_last_click_screen_pos = None
            self.last_saved_location_id = target_entity_id
            self.selected_entity_id = target_entity_id
            self.hover_entity_id = None
            self.selected_spatial_feature_id = None
            self.hover_spatial_feature_id = None
            self.hover_screen_pos = None

            if hasattr(self.world_model, "refresh"):
                self.world_model.refresh()

            self.bounds = self._resolve_root_bounds()
            self._invalidate_layer_cache()

            logger.info(f"[MapSimulation] Saved planet dimensions {target_entity_id}")
            return True

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
        self.map_square_target_entity_id = None
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

        logger.info(f"[MapSimulation] Saved location rectangle draft {location['id']}")
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

        previous_points = None
        if self.is_evolving_spatial_feature_polygon:
            source_feature = self.get_spatial_feature(self.evolving_source_spatial_feature_id)
            if source_feature is not None:
                source_points = self._get_geometry_points(source_feature.get("geometry") or {})
                if len(source_points) >= 3:
                    previous_points = [
                        self._map_point_to_world(x, y)
                        for x, y in source_points
                    ]

        mode = "draft"
        if self.is_placing_location_polygon:
            mode = "place"
        elif self.is_evolving_spatial_feature_polygon:
            mode = "evolve"
        elif self.is_editing_spatial_feature_polygon:
            mode = "edit"

        preview = {
            "points": preview_points,
            "hover_point": preview_hover_point,
            "layer_kind": self.active_layer_kind,
            "can_finish": self.can_finish_polygon_editor(),
            "area_label": self.get_draft_area_label(),
            "mode": mode,
        }

        if previous_points is not None:
            preview["previous_points"] = previous_points

        return preview

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
        if self._root_is_building():
            index = 1
            while True:
                room_id = f"loc_room_{root_id}_{index:03d}"
                if room_id not in existing_ids:
                    return room_id, index
                index += 1

        index = 1
        while True:
            feature_id = f"loc_region_{root_id}_{index:03d}"
            if feature_id not in existing_ids:
                return feature_id, index
            index += 1

    def _allocate_spatial_feature_evolution_id(self, source_feature, year):
        existing_ids = self._get_existing_entity_ids()
        source_id = self._sanitize_identifier_part(source_feature.get("id", "feature"))
        year_part = self._sanitize_identifier_part(str(year))

        index = 1
        while True:
            feature_id = f"loc_region_hist_{source_id}_y{year_part}_{index:03d}"
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
        if self._root_is_building():
            root_name = self.get_root_name()
            name = f"Draft Room {index:03d}"
            notes = f"Draft room polygon created inside {root_name}."
            points = list(self.draft_spatial_feature_points)
            return {
                "id": feature_id,
                "pretty_name": name,
                "name": name,
                "type": "location",
                "location_class": "room",
                "location_role": "indoor_room",
                "room_class": "room",
                "layer_kind": "rooms",
                "wiki_entry": notes,
                "parent_location": self.context.root_entity_id,
                "parent_entity": self.context.root_entity_id,
                "parents": [self.context.root_entity_id],
                "geometry": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": points,
                },
                "bounds": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": points,
                },
                "start_year": self.year,
                "entry_status": "draft",
            }

        root_name = self.get_root_name()
        if self.active_layer_kind == self.LOCATION_LAYER_KIND:
            feature_id, index = self._allocate_location_draft_id()
            name = f"Draft Location {index:03d}"
            notes = f"Draft location polygon created under {root_name}."
            region_class = "region"
            location_role = "map_location"
        else:
            layer_label = self.get_active_layer_label()
            name = f"Draft {layer_label} Region {index:03d}"
            notes = f"Draft region polygon created under {root_name}."
            region_class = self.active_layer_kind
            location_role = "map_region"

        return {
            "id": feature_id,
            "pretty_name": name,
            "name": name,
            "type": "location",
            "location_class": "region",
            "location_role": location_role,
            "region_class": region_class,
            "wiki_entry": notes,
            "layer_kind": self.active_layer_kind,
            "parent_location": self.context.root_entity_id,
            "parent_entity": self.context.root_entity_id,
            "parents": [self.context.root_entity_id],
            "geometry": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(self.draft_spatial_feature_points),
            },
            "bounds": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(self.draft_spatial_feature_points),
            },
            "start_year": self.year,
            "entry_status": "draft",
        }

    def _build_evolved_spatial_feature_record(self, source_feature, points):
        selected_year = int(self.year)
        feature_id, _index = self._allocate_spatial_feature_evolution_id(
            source_feature,
            selected_year,
        )
        source_id = source_feature.get("id")
        source_name = (
            source_feature.get("name")
            or source_feature.get("pretty_name")
            or source_id
        )
        name = f"{source_name} ({selected_year})"
        notes = (
            f"Historical slice evolved from {source_id} at "
            f"{self.get_year_context_label()}."
        )

        related = list(source_feature.get("related") or [])
        if source_id and source_id not in related:
            related.append(source_id)

        evolved = {
            "id": feature_id,
            "pretty_name": name,
            "name": name,
            "type": "location",
            "location_class": "region",
            "location_role": "map_region",
            "wiki_entry": notes,
            "region_class": source_feature.get("region_class") or source_feature.get("layer_kind", self.active_layer_kind),
            "layer_kind": source_feature.get("layer_kind", self.active_layer_kind),
            "parent_location": (
                source_feature.get("parent_location")
                or source_feature.get("parent_entity")
                or self.context.root_entity_id
            ),
            "parent_entity": (
                source_feature.get("parent_entity")
                or source_feature.get("parent_location")
                or self.context.root_entity_id
            ),
            "owner_entity": source_feature.get("owner_entity"),
            "geometry": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(points),
            },
            "bounds": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(points),
            },
            "start_year": selected_year,
            "end_year": self._normalize_year_value(source_feature.get("end_year")),
            "entry_status": "draft",
            "related": related,
        }
        if source_id and source_id not in evolved["related"]:
            evolved["related"].append(source_id)

        for key in (
            "resolution_m_per_pixel",
            "coverage_mode",
            "draw_order",
        ):
            if source_feature.get(key) is not None:
                evolved[key] = source_feature.get(key)

        return evolved

    def _build_draft_map_square_location_record(self):
        location_id, index = self._allocate_location_draft_id()
        root_name = self.get_root_name()
        name = f"Draft Location {index:03d}"
        notes = f"Draft location rectangle created under {root_name}."

        return {
            "id": location_id,
            "pretty_name": name,
            "name": name,
            "type": "location",
            "location_class": "region",
            "parent_location": self.context.root_entity_id,
            "wiki_entry": notes,
            "bounds": self._current_map_square_bounds(),
            "start_year": self.year,
            "entry_status": "draft",
        }

    def _append_spatial_feature_record(self, feature):
        if not self._persist_repository_entity(feature, "spatial_features"):
            raise OSError("Could not persist spatial feature to ontology")

    def _append_location_record(self, location):
        if not self._persist_repository_entity(location, "locations"):
            raise OSError("Could not persist location to ontology")

    def _append_offspring_reference_to_location(self, parent_location_id, child_location_id):
        if not parent_location_id or not child_location_id:
            return False

        loader = self._repository_loader()
        if loader is None or not hasattr(loader, "set_relation"):
            return False
        changed = set()
        changed.update(loader.set_relation(child_location_id, "parents", parent_location_id, persist=False))
        changed.update(loader.set_relation(parent_location_id, "constituents", child_location_id, persist=False))
        child = getattr(loader, "entities", {}).get(child_location_id)
        if isinstance(child, dict) and not child.get("parent_location"):
            changed.update(loader.set_literal(child_location_id, "parent_location", parent_location_id, persist=False))
        if changed:
            loader.save_ontology_file() if getattr(loader, "use_ontology", False) else loader.save_changed_dataset_files(changed)
        return bool(changed) or parent_location_id in self._relation_entity_ids(
            getattr(loader, "entities", {}).get(child_location_id, {}).get("parents")
        )

    def save_selection_inspector_updates(self, target_kind, target_id, updates):
        if target_kind not in {"spatial_feature", "location"}:
            return False

        name = str(updates.get("name", "")).strip()
        notes = str(updates.get("wiki_entry", updates.get("notes", ""))).strip()

        if not name:
            name = str(target_id)

        if target_kind == "spatial_feature":
            if not self._is_real_spatial_feature_id(target_id):
                return False

            updated = self._update_spatial_feature_text_fields(target_id, name, notes)
        else:
            if not self._can_open_location_inspector(target_id):
                return False

            updated = self._update_location_text_fields(target_id, name, notes)

        if not updated:
            return False

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self._invalidate_layer_cache()
        logger.info(f"[MapSimulation] Updated inspector fields {target_kind}:{target_id}")
        return True

    def delete_selection_inspector_target(self, target_kind, target_id):
        if target_kind != "spatial_feature":
            return False
        if not self._is_real_spatial_feature_id(target_id):
            return False

        entity = self.get_spatial_feature(target_id)
        if not isinstance(entity, dict):
            return False

        is_location_region = self._is_location_backed_region(target_id)
        parent_location_id = entity.get("parent_location") or entity.get("parent_entity")

        try:
            removed_from_repository = self._remove_repository_entity(
                target_id,
                dataset_name="locations" if is_location_region else "spatial_features",
            )
            if removed_from_repository is False:
                return False
            if removed_from_repository and is_location_region and parent_location_id:
                self._remove_offspring_reference_from_location(parent_location_id, target_id)
            elif is_location_region and parent_location_id:
                self._remove_offspring_reference_from_location(parent_location_id, target_id)
        except OSError as exc:
            logger.error(f"[MapSimulation] Failed to delete region {target_id}: {exc}")
            return False

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self.selected_spatial_feature_id = None
        self.hover_spatial_feature_id = None
        if self.selected_entity_id == target_id:
            self.selected_entity_id = None
        self.hover_entity_id = None
        self.hover_screen_pos = None
        self._pending_inspector_target = None
        self._invalidate_layer_cache()

        logger.info(f"[MapSimulation] Deleted region {target_id}")
        return True

    def reanchor_selection_time(self, target_kind, target_id, year):
        if target_kind not in {"spatial_feature", "location"}:
            return False

        try:
            year = int(year)
        except (TypeError, ValueError):
            return False

        if target_kind == "spatial_feature":
            if not self._is_real_spatial_feature_id(target_id):
                return False
            entity = self.get_spatial_feature(target_id)
        else:
            if not self._can_open_location_inspector(target_id):
                return False
            entity = self.get_location(target_id)

        if not isinstance(entity, dict):
            return False

        updates = self._build_time_reanchor_updates(entity, year)
        if not updates:
            return False

        try:
            if not self._update_entity_temporal_fields(target_id, updates):
                return False
        except OSError as exc:
            logger.error(f"[MapSimulation] Failed to reanchor {target_kind}:{target_id}: {exc}")
            return False

        if hasattr(self.world_model, "refresh"):
            self.world_model.refresh()

        self.context.year = year
        self.sim_clock.time = 0.0
        self.sim_clock.tick = 0
        self.sim_clock._accumulator = 0.0
        if target_kind == "spatial_feature":
            self.selected_entity_id = None
            self.selected_spatial_feature_id = target_id
        else:
            self.selected_entity_id = target_id
            self.selected_spatial_feature_id = None
        self.hover_entity_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        self._pending_inspector_target = {
            "kind": target_kind,
            "id": target_id,
        }
        self._invalidate_layer_cache()

        logger.info(
            f"[MapSimulation] Reanchored {target_kind}:{target_id} to year {year}"
        )
        return True

    def _build_time_reanchor_updates(self, entity, year):
        old_start_year = self._normalize_year_value(entity.get("start_year"))
        old_end_year = self._normalize_year_value(entity.get("end_year"))
        updates = {}

        if "year" in entity:
            old_anchor_year = self._normalize_year_value(entity.get("year"))
            updates["year"] = year
        elif "year_number" in entity:
            old_anchor_year = self._normalize_year_value(entity.get("year_number"))
            updates["year_number"] = year
        elif "start_year" in entity:
            old_anchor_year = old_start_year
            updates["start_year"] = year

            if old_start_year is not None and old_end_year is not None:
                if old_end_year >= old_start_year and old_end_year != old_start_year:
                    updates["end_year"] = old_end_year + (year - old_start_year)
                elif old_end_year == old_start_year:
                    updates["end_year"] = year
        elif "effective_year" in entity:
            old_anchor_year = self._normalize_year_value(entity.get("effective_year"))
            updates["effective_year"] = year
        elif "end_year" in entity:
            old_anchor_year = old_end_year
            updates["end_year"] = year
        else:
            old_anchor_year = None
            updates["start_year"] = year

        if "effective_year" in entity:
            old_effective_year = self._normalize_year_value(entity.get("effective_year"))
            if old_effective_year is None or old_effective_year == old_anchor_year:
                updates["effective_year"] = year

        return updates

    def _is_real_spatial_feature_id(self, spatial_feature_id):
        if not spatial_feature_id:
            return False

        return not str(spatial_feature_id).startswith("virtual:")

    def _is_location_backed_region(self, entity_id):
        entity = self.get_location(entity_id)
        return (
            isinstance(entity, dict)
            and entity.get("_dataset") in (None, "locations")
            and entity.get("type") == "location"
            and entity.get("location_class") in {"region", "state", "quarter"}
        )

    def _remove_offspring_reference_from_location(self, parent_location_id, child_location_id):
        if not parent_location_id or not child_location_id:
            return False

        loader = self._repository_loader()
        if loader is None or not hasattr(loader, "remove_relation"):
            return False
        changed = set()
        changed.update(loader.remove_relation(child_location_id, "parents", parent_location_id, persist=False))
        changed.update(loader.remove_relation(parent_location_id, "constituents", child_location_id, persist=False))
        child = getattr(loader, "entities", {}).get(child_location_id)
        if isinstance(child, dict) and child.get("parent_location") == parent_location_id:
            changed.update(loader.set_literal(child_location_id, "parent_location", "", persist=False))
        if changed:
            loader.save_ontology_file() if getattr(loader, "use_ontology", False) else loader.save_changed_dataset_files(changed)
        return bool(changed)

    def _update_entity_temporal_fields(self, entity_id, field_values):
        return self._update_repository_entity_fields(entity_id, field_values)

    def _update_spatial_feature_text_fields(self, spatial_feature_id, name, notes):
        if self._is_location_backed_region(spatial_feature_id):
            return self._update_location_text_fields(spatial_feature_id, name, notes)

        updated_repository = self._update_repository_entity_fields(
            spatial_feature_id,
            {"pretty_name": name, "name": name, "wiki_entry": notes},
        )
        return updated_repository

    def _update_location_text_fields(self, location_id, name, notes):
        updated_repository = self._update_repository_entity_fields(
            location_id,
            {"pretty_name": name, "name": name, "wiki_entry": notes},
        )
        return updated_repository

    def _update_location_map_image_fields(self, location_id, updates):
        return self._update_repository_entity_fields(location_id, dict(updates))

    def _update_spatial_feature_geometry(self, spatial_feature_id, points):
        if self._is_location_backed_region(spatial_feature_id):
            bounds = {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": list(points),
            }
            if not self._update_location_bounds(spatial_feature_id, bounds):
                return False
            if not self._update_location_geometry(spatial_feature_id, points):
                return False
            return True

        updated_repository = self._update_repository_entity_fields(
            spatial_feature_id,
            {
                "geometry": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": list(points),
                }
            },
        )
        return updated_repository

    def _update_location_bounds(self, location_id, bounds):
        return self._update_repository_entity_fields(location_id, {"bounds": bounds})

    def _update_location_geometry(self, location_id, points):
        updated_repository = self._update_repository_entity_fields(
            location_id,
            {
                "geometry": {
                    "type": "polygon",
                    "coordinate_space": "map_world",
                    "points": list(points),
                }
            },
        )
        return updated_repository

    def _update_location_parent(self, location_id, parent_location_id):
        updated_repository = self._update_repository_entity_fields(
            location_id,
            {
                "parent_location": parent_location_id,
                "parents": [parent_location_id] if parent_location_id else [],
            },
        )
        return updated_repository

    def _update_spatial_feature_end_year(self, spatial_feature_id, end_year):
        return self._update_repository_entity_fields(spatial_feature_id, {"end_year": end_year})

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

    def _begin_camera_drag(self, screen_pos, camera):
        self.is_camera_dragging = True
        self.camera_drag_start_screen_pos = screen_pos
        self.camera_drag_start_camera_pos = (camera.x, camera.y)
        self.camera_drag_has_moved = False

    def _reset_camera_drag(self):
        self.is_camera_dragging = False
        self.camera_drag_start_screen_pos = None
        self.camera_drag_start_camera_pos = None
        self.camera_drag_has_moved = False

    def _update_camera_drag(self, screen_pos, camera):
        if not self.is_camera_dragging:
            return False

        if self.camera_drag_start_screen_pos is None:
            return False

        if self.camera_drag_start_camera_pos is None:
            return False

        dx = float(screen_pos[0]) - float(self.camera_drag_start_screen_pos[0])
        dy = float(screen_pos[1]) - float(self.camera_drag_start_screen_pos[1])

        if not self.camera_drag_has_moved:
            distance_sq = dx * dx + dy * dy
            if distance_sq < self.CAMERA_DRAG_THRESHOLD_PX ** 2:
                return False

            self.camera_drag_has_moved = True

        start_camera_x, start_camera_y = self.camera_drag_start_camera_pos
        zoom = max(float(camera.zoom), 1e-9)
        camera.x = start_camera_x - (dx / zoom)
        camera.y = start_camera_y - (dy / zoom)

        self.hover_entity_id = None
        self.hover_spatial_feature_id = None
        self.hover_screen_pos = None
        return True

    def _entity_id_is_in_root_scope(self, entity_id):
        if not entity_id:
            return False

        entity = self.world_model.get_entity(entity_id)
        if not entity:
            return False

        return self.context._is_in_root_subtree(entity)

    def _spatial_feature_is_in_scope(self, feature):
        owner_entity_id = feature.get("owner_entity")
        parent_entity_id = feature.get("parent_location") or feature.get("parent_entity")

        if self._entity_id_is_in_root_scope(owner_entity_id):
            return True

        if self._entity_id_is_in_root_scope(parent_entity_id):
            return True

        return False

    def _get_scoped_spatial_features(self):
        root_entity_id = self.context.root_entity_id
        features = [
            entity for entity in self.world_model.get_active_entities(
                self.year,
                dataset_name="locations",
                entity_type="location",
            )
            if entity.get("location_class") in {"region", "state", "quarter"}
            and (entity.get("geometry") or entity.get("bounds"))
            and entity.get("id") != root_entity_id
        ]

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
            (
                self.is_editing_spatial_feature_polygon
                or self.is_evolving_spatial_feature_polygon
            )
            and feature.get("id") == self.editing_spatial_feature_id
        ):
            return None

        geometry = feature.get("geometry") or feature.get("bounds") or {}
        map_points = self._get_geometry_points(geometry)

        if len(map_points) < 3:
            return None

        points = [
            self._map_point_to_world(x, y)
            for x, y in map_points
        ]
        feature_layer_kind = feature.get("layer_kind") or self.REGION_LAYER_KIND
        layer_kind = self.REGION_LAYER_KIND
        region_class = feature.get("region_class") or feature.get("layer_kind")
        ground_material = str(feature.get("ground_material") or "").strip().lower()
        centroid_x, centroid_y = self._polygon_centroid(points)
        color_key = ground_material if feature_layer_kind == self.GROUND_MATERIALS_LAYER_KIND and ground_material else region_class or layer_kind

        return {
            "shape": "polygon",
            "x": centroid_x,
            "y": centroid_y,
            "points": points,
            "name": feature.get("name") or feature.get("pretty_name") or feature.get("id"),
            "entity_id": feature.get("owner_entity") or feature.get("id"),
            "spatial_feature_id": feature.get("id"),
            "layer_kind": layer_kind,
            "feature_layer_kind": feature_layer_kind,
            "region_class": region_class,
            "parent_entity": feature.get("parent_location") or feature.get("parent_entity"),
            "ground_material": ground_material,
            "ground_material_intensity": feature.get("ground_material_intensity"),
            "color": self._color_for_spatial_layer(color_key),
            "area_world": self._polygon_area(map_points),
            "resolution_m_per_pixel": feature.get("resolution_m_per_pixel"),
            "coverage_mode": feature.get("coverage_mode"),
            "draw_order": feature.get("draw_order", 0),
            "wiki_entry": feature.get("wiki_entry"),
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

    def _map_context_entities(self):
        entities = []
        seen = set()
        current = self.get_root_entity()

        while current:
            entity_id = current.get("id")
            if not entity_id or entity_id in seen:
                break

            seen.add(entity_id)
            entities.append(current)

            parent_id = self._structural_parent_location_id(current)
            if not parent_id:
                break
            current = self.world_model.get_entity(parent_id)

        return entities

    def _location_has_context_geometry(self, entity):
        if not isinstance(entity, dict):
            return False

        bounds = entity.get("bounds") or {}
        if bounds.get("type") in {"bbox", "polygon"}:
            return len(self._get_geometry_points(bounds)) >= 3

        if entity.get("location_class") in {"planet", "moon"}:
            return True

        image_path = entity.get("map_image_path")
        return bool(image_path and self._map_image_rect_from_entity(entity) is not None)

    def _map_context_sister_entities(self, context_entities):
        if self.world_model is None:
            return []

        context_ids = {
            entity.get("id")
            for entity in context_entities
            if isinstance(entity, dict) and entity.get("id")
        }
        parent_ids = []
        for entity in context_entities:
            parent_id = self._structural_parent_location_id(entity) if isinstance(entity, dict) else None
            if parent_id and parent_id not in parent_ids:
                parent_ids.append(parent_id)

        locations = self.world_model.get_active_entities(
            self.year,
            dataset_name="locations",
            entity_type="location",
        )
        sisters = []
        seen = set()
        if parent_ids:
            for parent_id in parent_ids:
                for entity in locations:
                    entity_id = entity.get("id")
                    if not entity_id or entity_id in context_ids or entity_id in seen:
                        continue
                    if self._structural_parent_location_id(entity) != parent_id:
                        continue
                    if not self._location_has_context_geometry(entity):
                        continue
                    seen.add(entity_id)
                    sisters.append(entity)

        topology_ids = []
        for entity in context_entities:
            if not isinstance(entity, dict):
                continue
            for field_key in ("neighbours", "overlaps", "constituents"):
                for related_id in self._relation_entity_ids(entity.get(field_key)):
                    if related_id not in topology_ids:
                        topology_ids.append(related_id)

        for related_id in topology_ids:
            if related_id in context_ids or related_id in seen:
                continue
            related = self.world_model.get_entity(related_id)
            if not self._is_location_entity(related):
                continue
            if not self._location_has_context_geometry(related):
                continue
            seen.add(related_id)
            sisters.append(related)

        return sisters

    def _label_for_entity(self, entity):
        return (
            entity.get("name")
            or entity.get("pretty_name")
            or entity.get("id")
            or "location"
        )

    def _build_ghost_context_layers(self):
        layers = []
        context_entities = self._map_context_entities()
        if not context_entities:
            return layers

        for index, entity in enumerate(reversed(context_entities)):
            color = self._color_for_entity(entity)
            layer = self._build_location_bounds_layer(
                entity,
                color,
                draw_order=-3000 + index,
                virtual=True,
            )
            if layer is not None:
                layer["is_ghost_context"] = True
                layer["pickable"] = False
                if self.is_placing_location_polygon:
                    layer["alpha"] = 4 if index < len(context_entities) - 1 else 10
                    layer["border_alpha"] = 72 if index < len(context_entities) - 1 else 118
                else:
                    layer["alpha"] = 34 if index < len(context_entities) - 1 else 52
                    layer["border_alpha"] = 98 if index < len(context_entities) - 1 else 132
                layer["name"] = self._label_for_entity(entity)
                layers.append(layer)

            image_path = entity.get("map_image_path")
            image_rect = self._map_image_rect_from_entity(entity)
            if image_path and image_rect is not None:
                layers.append({
                    "shape": "image_rect",
                    "x": image_rect["x"],
                    "y": image_rect["y"],
                    "width_world": image_rect["width_world"],
                    "height_world": image_rect["height_world"],
                    "image_path": image_path,
                    "image_year": entity.get("map_image_year"),
                    "fit": entity.get("map_image_fit", "stretch_to_bounds"),
                    "name": self._label_for_entity(entity),
                    "entity_id": entity.get("id"),
                    "draw_order": -3100 + index,
                    "is_ghost_context": True,
                    "pickable": False,
                    "alpha": 68,
                })

        sister_start_index = len(context_entities)
        for sister_index, entity in enumerate(self._map_context_sister_entities(context_entities)):
            color = self._color_for_entity(entity)
            draw_index = sister_start_index + sister_index
            layer = self._build_location_bounds_layer(
                entity,
                color,
                draw_order=-2900 + draw_index,
                virtual=True,
            )
            if layer is not None:
                layer["is_ghost_context"] = True
                layer["is_ghost_sister"] = True
                layer["pickable"] = False
                layer["alpha"] = 0 if self.is_placing_location_polygon else 24
                layer["border_alpha"] = 52 if self.is_placing_location_polygon else 86
                layer["name"] = self._label_for_entity(entity)
                layers.append(layer)

            image_path = entity.get("map_image_path")
            image_rect = self._map_image_rect_from_entity(entity)
            if image_path and image_rect is not None:
                layers.append({
                    "shape": "image_rect",
                    "x": image_rect["x"],
                    "y": image_rect["y"],
                    "width_world": image_rect["width_world"],
                    "height_world": image_rect["height_world"],
                    "image_path": image_path,
                    "image_year": entity.get("map_image_year"),
                    "fit": entity.get("map_image_fit", "stretch_to_bounds"),
                    "name": self._label_for_entity(entity),
                    "entity_id": entity.get("id"),
                    "draw_order": -2950 + draw_index,
                    "is_ghost_context": True,
                    "is_ghost_sister": True,
                    "pickable": False,
                    "alpha": 44,
                })

        return layers

    def _build_spatial_feature_layers(self, year, layer_kind):
        layers = self._build_ghost_context_layers()

        for feature in self._get_scoped_spatial_features():
            feature_layer_kind = feature.get("layer_kind") or self.REGION_LAYER_KIND
            if layer_kind != self.REGION_LAYER_KIND and feature_layer_kind != layer_kind:
                continue
            layer = self._build_spatial_feature_layer(feature)
            if layer is not None:
                layers.append(layer)

        layers.sort(key=self._spatial_layer_sort_key)
        return layers

    def _build_location_bounds_layer(self, entity, color, draw_order=0, virtual=False):
        bounds = entity.get("bounds") or {}
        points = []

        if bounds.get("type") == "bbox":
            points = self._get_geometry_points(bounds)
        elif bounds.get("type") == "polygon":
            points = self._get_geometry_points(bounds)
        elif entity.get("location_class") in {"planet", "moon"}:
            rect = self._planet_rect_from_entity(entity)
            half_w = rect["width_world"] / 2.0
            half_h = rect["height_world"] / 2.0
            points = [
                (rect["x"] - half_w, rect["y"] - half_h),
                (rect["x"] + half_w, rect["y"] - half_h),
                (rect["x"] + half_w, rect["y"] + half_h),
                (rect["x"] - half_w, rect["y"] + half_h),
            ]

        if len(points) < 3:
            return None

        world_points = [
            self._map_point_to_world(point[0], point[1])
            for point in points
        ]
        centroid_x, centroid_y = self._polygon_centroid(world_points)
        return {
            "shape": "polygon",
            "x": centroid_x,
            "y": centroid_y,
            "points": world_points,
            "name": entity.get("name"),
            "entity_id": entity.get("id"),
            "color": color,
            "area_world": self._polygon_area(points),
            "draw_order": draw_order,
            "is_virtual_spatial_feature": virtual,
        }

    def _build_default_building_floor_layer(self):
        if not self._root_is_building():
            return None

        root_entity = self.get_root_entity()
        if not root_entity:
            return None

        points = self._root_bounds_as_polygon()
        centroid_x, centroid_y = self._polygon_centroid(points)
        return {
            "shape": "polygon",
            "x": centroid_x,
            "y": centroid_y,
            "points": points,
            "name": root_entity.get("name") or root_entity.get("pretty_name") or self.context.root_entity_id,
            "entity_id": self.context.root_entity_id,
            "color": self._color_for_entity(root_entity),
            "area_world": self._polygon_area(points),
            "draw_order": -2000,
            "is_virtual_building_floor": True,
        }

    def _build_placement_ancestor_layers(self):
        layers = []
        if not self.is_placing_location_polygon:
            return layers

        context_ids = {
            entity.get("id")
            for entity in self._map_context_entities()
            if isinstance(entity, dict) and entity.get("id")
        }

        for index, entity_id in enumerate(reversed(self.placement_ancestor_entity_ids)):
            if entity_id in context_ids:
                continue
            entity = self.get_location(entity_id)
            if not entity:
                continue
            layer = self._build_location_bounds_layer(
                entity,
                self._color_for_entity(entity),
                draw_order=-100 - index,
                virtual=True,
            )
            if layer is not None:
                layer["is_ghost_context"] = True
                layer["is_placement_ancestor"] = True
                layer["pickable"] = False
                layer["alpha"] = 0
                layer["border_alpha"] = 118
                layer["name"] = self._label_for_entity(entity)
                layers.append(layer)
        return layers

    def _build_layers(self, year):
        """
        Build render layers from active entities.

        Supported map geometry:
        * planet       -> map_rect surface container
        * bbox region  -> rect
        * point place  -> marker
        """
        self.get_active_layer_kind()
        if self.active_layer_kind != self.LOCATION_LAYER_KIND:
            return self._build_spatial_feature_layers(year, self.active_layer_kind)

        layers = self._build_ghost_context_layers()
        layers.extend(self._build_placement_ancestor_layers())

        for entity in self.context.get_active_locations():
            if not entity:
                continue

            entity_id = entity.get("id")
            if (
                self.is_editing_map_square
                and entity_id == self.editing_map_square_entity_id
            ):
                continue
            if (
                self.is_placing_location_polygon
                and entity_id == self.placing_location_entity_id
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
            image_rect = self._map_image_rect_from_entity(entity)
            image_path = entity.get("map_image_path")
            if image_path and image_rect is not None:
                layers.append({
                    "shape": "image_rect",
                    "x": image_rect["x"],
                    "y": image_rect["y"],
                    "width_world": image_rect["width_world"],
                    "height_world": image_rect["height_world"],
                    "image_path": image_path,
                    "image_year": entity.get("map_image_year"),
                    "fit": entity.get("map_image_fit", "stretch_to_bounds"),
                    "name": entity.get("name"),
                    "entity_id": entity_id,
                })

            if location_class in {"planet", "moon"}:
                rect = self._planet_rect_from_entity(entity)
                gas_giant = self._entity_is_gas_giant(entity)

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
                    "location_class": location_class,
                    "label_position": "below_right",
                    "has_heightmap_base": (not gas_giant) and isinstance(entity.get("heightmap_model"), dict),
                    "render_style": "gas_giant_bands" if gas_giant else "surface",
                    "bands": self._gas_giant_bands_for_entity(entity) if gas_giant else [],
                })
                continue

            if bounds.get("type") == "bbox":
                min_x = bounds.get("min_x", 0)
                max_x = bounds.get("max_x", 0)
                min_y = bounds.get("min_y", 0)
                max_y = bounds.get("max_y", 0)

                map_points = [
                    (min_x, min_y),
                    (max_x, min_y),
                    (max_x, max_y),
                    (min_x, max_y),
                ]
                points = [
                    self._map_point_to_world(point[0], point[1])
                    for point in map_points
                ]
                centroid_x, centroid_y = self._polygon_centroid(points)
                layers.append({
                    "shape": "polygon",
                    "x": centroid_x,
                    "y": centroid_y,
                    "points": points,
                    "name": entity.get("name"),
                    "entity_id": entity_id,
                    "color": color,
                    "area_world": self._polygon_area(map_points),
                })
                continue

            if bounds.get("type") == "polygon":
                map_points = self._get_geometry_points(bounds)
                if len(map_points) >= 3:
                    points = [
                        self._map_point_to_world(point[0], point[1])
                        for point in map_points
                    ]
                    centroid_x, centroid_y = self._polygon_centroid(points)
                    layers.append({
                        "shape": "polygon",
                        "x": centroid_x,
                        "y": centroid_y,
                        "points": points,
                        "name": entity.get("name"),
                        "entity_id": entity_id,
                        "color": color,
                        "area_world": self._polygon_area(map_points),
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

        if self._root_is_building() and not any(
            layer.get("entity_id") == self.context.root_entity_id
            for layer in layers
        ):
            default_floor_layer = self._build_default_building_floor_layer()
            if default_floor_layer is not None:
                layers.insert(0, default_floor_layer)

        return layers

    def get_heightmap_base_layer(self):
        root_entity = self.get_root_entity()
        if not isinstance(root_entity, dict):
            return None

        if root_entity.get("location_class") not in {"planet", "moon"}:
            return None
        if self._entity_is_gas_giant(root_entity):
            return None

        heightmap = root_entity.get("heightmap_model")
        if not isinstance(heightmap, dict):
            return None

        sample_grid = heightmap.get("sample_grid")
        if not isinstance(sample_grid, dict) or not sample_grid.get("rows"):
            return None

        rect = self._planet_rect_from_entity(root_entity)
        return {
            "shape": "heightmap_base",
            "x": rect["x"],
            "y": rect["y"],
            "width_world": rect["width_world"],
            "height_world": rect["height_world"],
            "canvas_width_px": rect["canvas_width_px"],
            "canvas_height_px": rect["canvas_height_px"],
            "heightmap_model": heightmap,
            "surface_palette": root_entity.get("surface_palette"),
            "color": root_entity.get("display_color") or root_entity.get("color"),
            "display_color": root_entity.get("display_color"),
            "name": root_entity.get("name"),
            "entity_id": root_entity.get("id"),
        }

    def get_layers(self):
        self.get_active_layer_kind()
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

    def get_history_timeline_items(self):
        if not hasattr(self.world_model, "get_timeline_items"):
            return []

        items = []
        for item in self.world_model.get_timeline_items():
            if item.get("timeline_kind") == "major_period":
                items.append(item)
                continue

            entity = self.world_model.get_entity(item.get("entity_id"))
            if self._entity_is_history_timeline_relevant(entity):
                items.append(item)

        return items

    def _entity_is_history_timeline_relevant(self, entity):
        if not entity:
            return False

        entity_id = entity.get("id")
        if entity_id == self.context.root_entity_id:
            return True

        if entity.get("_dataset") == "locations" or entity.get("type") == "location":
            return self.context._is_in_root_subtree(entity)

        if entity.get("_dataset") == "spatial_features" or entity.get("type") == "spatial_feature":
            return self._spatial_feature_is_in_scope(entity)

        referenced_ids = self._collect_history_reference_ids(entity)
        return any(self._entity_id_is_in_root_scope(ref_id) for ref_id in referenced_ids)

    def _collect_history_reference_ids(self, entity):
        reference_keys = (
            "parent_location",
            "parent_entity",
            "owner_entity",
            "associated_locations",
            "locations",
            "location_history",
            "neighbours",
            "constituents",
            "overlaps",
            "related",
            "parents",
        )
        references = []

        for key in reference_keys:
            references.extend(self._relation_entity_ids(entity.get(key)))

        return references

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
            if layer.get("pickable") is False or layer.get("is_ghost_context"):
                continue

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

    def _select_picked_layer(self, picked_layer, screen_pos, record_click=False):
        self.hover_screen_pos = screen_pos
        self.hover_entity_id = picked_layer.get("entity_id") if picked_layer else None
        self.hover_spatial_feature_id = picked_layer.get("spatial_feature_id") if picked_layer else None

        if picked_layer is None:
            self.selected_entity_id = None
            self.selected_spatial_feature_id = None
            return

        self.selected_entity_id = picked_layer.get("entity_id")
        self.selected_spatial_feature_id = picked_layer.get("spatial_feature_id")

        if record_click:
            target = None
            if (
                self.active_layer_kind == self.LOCATION_LAYER_KIND
                and self._can_open_location_inspector(self.selected_entity_id)
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

    def _set_polygon_editor_hover_point(self, map_point):
        if self.is_placing_location_polygon:
            self.placing_hover_map_pos = map_point
            return

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            self.editing_hover_map_pos = map_point
        elif self.is_creating_spatial_feature:
            self.draft_hover_map_pos = map_point

    def _append_polygon_editor_point(self, map_point):
        if self.is_placing_location_polygon:
            self.placing_location_points.append(map_point)
            return len(self.placing_location_points)

        if (
            self.is_editing_spatial_feature_polygon
            or self.is_evolving_spatial_feature_polygon
        ):
            self.editing_spatial_feature_points.append(map_point)
            return len(self.editing_spatial_feature_points)

        self.draft_spatial_feature_points.append(map_point)
        return len(self.draft_spatial_feature_points)

    def _can_reuse_existing_polygon_for_editor(self):
        return (
            self.get_polygon_editor_point_count() == 0
            and (
                self.is_creating_spatial_feature
                or self.is_placing_location_polygon
            )
        )

    def _pick_existing_polygon_point_for_editor(self, camera, screen_pos):
        if camera is None or screen_pos is None:
            return None

        layers = self.get_layers()
        screen_x = float(screen_pos[0])
        screen_y = float(screen_pos[1])
        best_point = None
        best_distance_sq = self.POLYGON_POINT_HIT_RADIUS_PX ** 2

        for layer in reversed(layers):
            if layer.get("pickable") is False or layer.get("is_ghost_context"):
                continue
            if layer.get("shape") != "polygon":
                continue

            points = layer.get("points") or []
            if len(points) < 3:
                continue

            for point in points:
                point_screen = camera.world_to_screen(point)
                if point_screen is None:
                    continue

                dx = screen_x - float(point_screen[0])
                dy = screen_y - float(point_screen[1])
                distance_sq = dx * dx + dy * dy
                if distance_sq <= best_distance_sq:
                    best_point = self._world_point_to_map(point[0], point[1])
                    best_distance_sq = distance_sq

        return best_point

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

        if self._can_reuse_existing_polygon_for_editor():
            reuse_point = self._pick_existing_polygon_point_for_editor(camera, screen_pos)
            if reuse_point is not None:
                point_count = self._append_polygon_editor_point(reuse_point)
                self._set_polygon_editor_hover_point(reuse_point)
                self._record_draft_click(screen_pos)
                self._invalidate_layer_cache()
                logger.debug(
                    f"[MapSimulation] Polygon editor reused existing point count={point_count}",
                    key="map_polygon_editor_point_reuse",
                    interval=0.1,
                )
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
        if self._update_camera_drag(screen_pos, camera):
            return

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
        button = getattr(event, "button", None)

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

        if event.type == self.MOUSEBUTTONDOWN_EVENT_TYPE and button == 1:
            self._begin_camera_drag(screen_pos, camera)
            self.hover_screen_pos = screen_pos
            self.hover_entity_id = picked_layer.get("entity_id") if picked_layer else None
            self.hover_spatial_feature_id = picked_layer.get("spatial_feature_id") if picked_layer else None
            return

        if event.type == self.MOUSEBUTTONUP_EVENT_TYPE and button == 1:
            was_camera_dragging = self.is_camera_dragging
            was_camera_pan = self.camera_drag_has_moved
            self._reset_camera_drag()

            if not was_camera_dragging:
                return

            if was_camera_dragging and was_camera_pan:
                return

            self._select_picked_layer(picked_layer, screen_pos, record_click=True)
            return

        self._select_picked_layer(picked_layer, screen_pos, record_click=False)

    def get_center(self):
        return (
            (self.bounds["min_x"] + self.bounds["max_x"]) / 2,
            (self.bounds["min_y"] + self.bounds["max_y"]) / 2,
        )

    def update(self, dt):
        self.sim_manager.update(dt)
