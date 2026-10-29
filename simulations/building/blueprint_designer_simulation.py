"""Blueprint Designer: author a building blueprint in two stages.

1. **Grundriss** -- draw rooms (polygon or rectangle) on a snap grid or freely,
   with live segment lengths and area; walls, outline, and floor space are
   derived.  Place openings on walls, fixed items in rooms, stairs, levels,
   and roof parameters.
2. **Design** -- assign materials to surfaces and paint facade/top details in
   Pixel Studio over a material-textured orthographic view.

The blueprint is a JSON payload in ``assets/buildings`` referenced from its
``building_blueprints`` ontology entity.  A released blueprint (one that has
been placed) is read-only; editing it forks a new version so buildings that
already exist keep the version they were placed from.
"""

from __future__ import annotations

import copy
import math
import time

import pygame

from engine.clock import Clock
from engine.simulation_manager import SimulationManager
from ui.pixel_art_editor_ui import PixelArtEditorUI

from . import blueprint_model as bm
from .blueprint_store import PROJECT_ROOT as STORE_PROJECT_ROOT
from .blueprint_store import (
    BLUEPRINT_DATASET,
    blueprint_for_entity,
    default_asset_path,
    entity_display_name,
    safe_identifier,
    shared_store,
    updated_blueprint_entity,
)
from .blueprint_views import (
    VIEW_LABELS,
    elevation_primitives,
    top_primitives,
    view_frame,
)
from .material_visuals import MaterialVisuals


SNAP_STEPS_M = (0.1, 0.25, 0.5, 1.0)
VERTEX_SNAP_PX = 11
EDGE_SNAP_PX = 8
DOUBLE_CLICK_S = 0.35
UNDO_LIMIT = 60
MAX_DETAIL_CANVAS_PX = 720


def next_version_label(label):
    text = str(label or "").strip()
    if not text:
        return "v2"
    if text[-1].isalpha() and text[-1].lower() != "z":
        return text[:-1] + chr(ord(text[-1]) + 1)
    digits = ""
    for char in reversed(text):
        if char.isdigit():
            digits = char + digits
        else:
            break
    if digits:
        return text[: len(text) - len(digits)] + str(int(digits) + 1)
    return f"{text} v2"


class BlueprintDesignerSimulation:
    render_mode = "building_blueprint"
    show_time_ui = False
    suppress_global_overlays = True
    LINE_HEIGHT = 20

    STAGE_GRUNDRISS = "grundriss"
    STAGE_DESIGN = "design"
    GRUNDRISS_TOOLS = ("select", "room", "rect", "opening", "fixture", "stair")
    TOOL_LABELS = {
        "select": "Select / Edit",
        "room": "Draw Room",
        "rect": "Rectangle Room",
        "opening": "Opening",
        "fixture": "Fixed Item",
        "stair": "Stair",
    }
    DESIGN_VIEWS = ("top", "north", "east", "south", "west")

    def __init__(self, world_model=None, blueprint_entity_id=None, store=None):
        class _DummySystem:
            def update(self, dt):
                return None

        self.world_model = world_model
        self.blueprint_entity_id = str(blueprint_entity_id or "")
        self.sim_clock = Clock(base_dt=1.0)
        self.system = _DummySystem()
        self.sim_manager = SimulationManager(self.sim_clock, self.system)
        self.store = store or shared_store()
        self.materials = MaterialVisuals(world_model)

        # Pixel Studio host contract (see ui/pixel_art_editor_ui.py).
        self.pixel_art_editor = None
        self.pixel_art_painting = False
        self.pixel_art_editor_ui = PixelArtEditorUI(self)
        self.layout = None
        self.preferred_zoom = 1.0

        entity = self._entity() or {}
        self.blueprint = bm.normalize_blueprint(blueprint_for_entity(entity, self.store))
        self.blueprint["blueprint_id"] = self.blueprint_entity_id or self.blueprint["blueprint_id"]
        self.derived = bm.derive_geometry(self.blueprint)
        self.saved_fingerprint = bm.blueprint_fingerprint(self.blueprint) if entity.get("blueprint_asset_path") else None

        self.stage = self.STAGE_GRUNDRISS
        self.tool = "select"
        self.view_id = "plan"
        self.design_view_id = "south"
        self.top_show_roof = True
        self.active_level = self.blueprint["levels"][0]["key"]
        self.snap_enabled = True
        self.opening_class = "door"
        self.pending_fixture_ref = None
        self.fixture_rotation = 0.0

        self.draft_points = []
        self.rect_anchor = None
        self.length_entry = ""
        self.cursor_plan = None
        self.cursor_raw = None
        self.cursor_snap = None
        self.cursor_screen = None
        self.selection = None
        self.hover = None
        self.drag = None
        self.text_edit = None
        self.picker = None

        self.undo_stack = []
        self.redo_stack = []
        self.status = "Draw rooms on the grid · Shift = free placement · Ctrl = 45° steps"
        self.status_is_error = False
        self.pending_navigation_action = None
        self.request_close_tab = False

        self.hitboxes = {}
        self.panel_scroll = {"left": 0, "right": 0}
        self.panel_rects = {}
        self.viewport = (1280, 800)
        self.canvas_rect = pygame.Rect(240, 112, 760, 640)
        self.views = {}
        self._last_click_time = 0.0
        self._last_click_pos = None
        self._mods_override = None
        self._fit_pending = {"plan", *self.DESIGN_VIEWS}

    # ------------------------------------------------------------------
    # Entity / repository
    # ------------------------------------------------------------------

    def _loader(self):
        return getattr(self.world_model, "loader", None) if self.world_model is not None else None

    def _entity(self):
        if self.world_model is None or not self.blueprint_entity_id:
            return None
        entity = self.world_model.get_entity(self.blueprint_entity_id)
        return entity if isinstance(entity, dict) else None

    def _full_entity_copy(self, entity_id=None):
        entity_id = entity_id or self.blueprint_entity_id
        loader = self._loader()
        source = None
        if loader is not None:
            source = getattr(loader, "entities", {}).get(entity_id)
        if source is None and self.world_model is not None:
            source = self.world_model.get_entity(entity_id)
        if not isinstance(source, dict):
            return None
        materialize = getattr(source, "materialize", None)
        if callable(materialize):
            source = materialize()
        return copy.deepcopy(dict(source))

    def get_blueprint_name(self):
        return entity_display_name(self._entity(), self.blueprint.get("display_name") or "Building Blueprint")

    def get_version_label(self):
        return str((self._entity() or {}).get("blueprint_version_label") or "")

    def get_status_label(self):
        return "Released" if self.read_only else "Draft"

    @property
    def read_only(self):
        return str((self._entity() or {}).get("blueprint_status") or "draft") == "released"

    def placed_building_count(self):
        if self.world_model is None:
            return 0
        getter = getattr(self.world_model, "get_dataset", None)
        locations = getter("locations") if callable(getter) else []
        return sum(
            1 for location in locations or []
            if isinstance(location, dict) and location.get("building_blueprint") == self.blueprint_entity_id
        )

    @property
    def dirty(self):
        return bm.blueprint_fingerprint(self.blueprint) != self.saved_fingerprint

    def _persist(self, entity):
        loader = self._loader()
        if loader is None or not hasattr(loader, "persist_entity"):
            return False
        if not loader.persist_entity(entity):
            return False
        touch_degrees = getattr(self.world_model, "touch_degrees", None)
        if touch_degrees is not None and hasattr(touch_degrees, "refresh"):
            touch_degrees.refresh()
        if hasattr(self.world_model, "repository_revision"):
            self.world_model.repository_revision += 1
        return True

    def save(self):
        entity = self._full_entity_copy()
        if entity is None:
            return self._error("Blueprint entity is missing from the repository")
        if self.read_only and self.saved_fingerprint is not None and self.dirty:
            return self._error("Released blueprints are read-only — create a new version")
        asset_path = str(entity.get("blueprint_asset_path") or default_asset_path(self.blueprint_entity_id))
        self.blueprint["display_name"] = self.get_blueprint_name()
        try:
            asset_path = self.store.save(self.blueprint, asset_path)
        except OSError as exc:
            return self._error(f"Could not write blueprint asset: {exc}")
        updated = updated_blueprint_entity(entity, self.blueprint, asset_path)
        if not self._persist(updated):
            return self._error("Blueprint asset saved, but the ontology entity was not updated")
        self.saved_fingerprint = bm.blueprint_fingerprint(self.blueprint)
        return self._info(f"Saved {asset_path}")

    def create_new_version(self):
        entity = self._full_entity_copy()
        if entity is None:
            return self._error("Blueprint entity is missing from the repository")
        if self.dirty and not self.read_only:
            self.save()
        old_label = str(entity.get("blueprint_version_label") or "")
        new_label = next_version_label(old_label)
        base_name = entity_display_name(entity)
        if old_label and base_name.endswith(old_label):
            new_name = base_name[: -len(old_label)].rstrip() + " " + new_label
        else:
            new_name = f"{base_name} {new_label}"
        existing = set()
        getter = getattr(self.world_model, "get_dataset", None)
        for item in (getter(BLUEPRINT_DATASET) if callable(getter) else []) or []:
            if isinstance(item, dict):
                existing.add(item.get("id"))
        base_id = self.blueprint_entity_id
        if old_label:
            suffix = "_" + safe_identifier(old_label).lower()
            if base_id.endswith(suffix):
                base_id = base_id[: -len(suffix)]
        new_id = f"{base_id}_{safe_identifier(new_label).lower()}"
        counter = 2
        while new_id in existing:
            new_id = f"{base_id}_{safe_identifier(new_label).lower()}_{counter}"
            counter += 1
        new_blueprint = copy.deepcopy(self.blueprint)
        new_blueprint["blueprint_id"] = new_id
        new_blueprint["display_name"] = new_name
        asset_path = self.store.save(new_blueprint, default_asset_path(new_id))
        new_entity = copy.deepcopy(entity)
        for key in ("successor", "offspring", "blueprint_fingerprint"):
            new_entity.pop(key, None)
        new_entity.update({
            "id": new_id,
            "name": new_name,
            "pretty_name": new_name,
            "blueprint_status": "draft",
            "blueprint_version_label": new_label,
            "predecessor": self.blueprint_entity_id,
            "blueprint_asset_path": asset_path,
        })
        new_entity = updated_blueprint_entity(new_entity, new_blueprint, asset_path)
        if not self._persist(new_entity):
            return self._error("Could not create the new blueprint version")
        entity["successor"] = new_id
        self._persist(entity)
        self.pending_navigation_action = {
            "id": "knowledge_launch_mode",
            "entity_id": new_id,
            "launch_mode": "blueprint_designer",
        }
        return self._info(f"Created {new_name}")

    def placement_parent_options(self):
        getter = getattr(self.world_model, "get_dataset", None)
        locations = getter("locations") if callable(getter) and self.world_model is not None else []
        options = []
        for location in locations or []:
            if not isinstance(location, dict):
                continue
            if location.get("map_coordinate_space") != "site_meters":
                continue
            options.append({
                "id": location.get("id"),
                "label": location.get("pretty_name") or location.get("name") or location.get("id"),
                "detail": location.get("site_class") or location.get("location_class") or "site",
            })
        options.sort(key=lambda item: str(item["label"]).lower())
        return options

    def request_place_on_parent(self, parent_id):
        if not self.blueprint["rooms"]:
            return self._error("Draw at least one room before placing the blueprint")
        if self.dirty and not self.read_only:
            if not self.save():
                return False
        elif self.saved_fingerprint is None:
            if not self.save():
                return False
        self.pending_navigation_action = {
            "id": "blueprint_place_on_parent",
            "blueprint_id": self.blueprint_entity_id,
            "parent_id": parent_id,
        }
        self.picker = None
        return self._info("Choose a spot on the map")

    def consume_pending_navigation_action(self):
        action = self.pending_navigation_action
        self.pending_navigation_action = None
        return action

    # ------------------------------------------------------------------
    # Status / undo
    # ------------------------------------------------------------------

    def _info(self, message):
        self.status = str(message)
        self.status_is_error = False
        return True

    def _error(self, message):
        self.status = str(message)
        self.status_is_error = True
        return False

    def _editable(self):
        if self.read_only:
            return self._error("Released blueprint — create a new version to edit it")
        return True

    def _checkpoint(self):
        self.undo_stack.append(copy.deepcopy(self.blueprint))
        if len(self.undo_stack) > UNDO_LIMIT:
            del self.undo_stack[0]
        self.redo_stack = []

    def _changed(self):
        self.blueprint = bm.normalize_blueprint(self.blueprint)
        self.derived = bm.derive_geometry(self.blueprint)
        if not any(level["key"] == self.active_level for level in self.blueprint["levels"]):
            self.active_level = self.blueprint["levels"][0]["key"]

    def undo(self):
        if not self.undo_stack:
            return self._info("Nothing to undo")
        self.redo_stack.append(copy.deepcopy(self.blueprint))
        self.blueprint = self.undo_stack.pop()
        self.selection = None
        self._changed()
        return self._info("Undone")

    def redo(self):
        if not self.redo_stack:
            return self._info("Nothing to redo")
        self.undo_stack.append(copy.deepcopy(self.blueprint))
        self.blueprint = self.redo_stack.pop()
        self.selection = None
        self._changed()
        return self._info("Redone")

    # ------------------------------------------------------------------
    # Views / coordinates
    # ------------------------------------------------------------------

    def set_viewport(self, width, height):
        self.viewport = (int(width), int(height))

    def set_layout(self, canvas_rect, hitboxes):
        self.canvas_rect = pygame.Rect(canvas_rect)
        self.hitboxes = dict(hitboxes or {})
        for view_id in list(self._fit_pending):
            self.fit_view(view_id)

    def current_view_id(self):
        return "plan" if self.stage == self.STAGE_GRUNDRISS else self.design_view_id

    def is_elevation_view(self, view_id=None):
        return (view_id or self.current_view_id()) in {"north", "east", "south", "west"}

    def _view(self, view_id=None):
        view_id = view_id or self.current_view_id()
        view = self.views.get(view_id)
        if view is None:
            view = {"center": [0.0, 0.0], "zoom": 24.0}
            self.views[view_id] = view
        return view

    def fit_view(self, view_id=None):
        view_id = view_id or self.current_view_id()
        if view_id != "plan" and not self.blueprint["rooms"]:
            # Keep design views waiting until there is a building to frame.
            self._fit_pending.add(view_id)
            self._view(view_id)
            return False
        self._fit_pending.discard(view_id)
        view = self._view(view_id)
        if view_id == "plan":
            bbox = self.derived.get("bbox")
            if bbox is None:
                points = [tuple(p) for room in self.blueprint["rooms"] for p in room["points"]]
                bbox = bm.polygon_bbox(points) if points else (-10.0, -8.0, 10.0, 8.0)
            min_u, min_v, max_u, max_v = bbox
        else:
            frame = view_frame(self.blueprint, self.derived, view_id, level_key=self.active_level)
            if frame is None:
                frame = (-10.0, -1.0, 10.0, 8.0)
            min_u, min_v, max_u, max_v = frame
        width = max(4.0, max_u - min_u)
        height = max(4.0, max_v - min_v)
        rect = self.canvas_rect
        zoom = min(rect.width / (width * 1.25), rect.height / (height * 1.25))
        view["zoom"] = max(2.0, min(240.0, zoom))
        view["center"] = [(min_u + max_u) / 2.0, (min_v + max_v) / 2.0]
        return True

    def world_to_screen(self, point, view_id=None):
        """Plan (x, y) or elevation (u, z) -> screen."""

        view_id = view_id or self.current_view_id()
        view = self._view(view_id)
        rect = self.canvas_rect
        zoom = view["zoom"]
        cx, cy = view["center"]
        if self.is_elevation_view(view_id):
            return (rect.centerx + (point[0] - cx) * zoom, rect.centery - (point[1] - cy) * zoom)
        return (rect.centerx + (point[0] - cx) * zoom, rect.centery + (point[1] - cy) * zoom)

    def screen_to_world(self, screen_pos, view_id=None):
        view_id = view_id or self.current_view_id()
        view = self._view(view_id)
        rect = self.canvas_rect
        zoom = view["zoom"] or 1.0
        cx, cy = view["center"]
        if self.is_elevation_view(view_id):
            return (cx + (screen_pos[0] - rect.centerx) / zoom, cy - (screen_pos[1] - rect.centery) / zoom)
        return (cx + (screen_pos[0] - rect.centerx) / zoom, cy + (screen_pos[1] - rect.centery) / zoom)

    def zoom_at(self, screen_pos, factor):
        view = self._view()
        before = self.screen_to_world(screen_pos)
        view["zoom"] = max(2.0, min(240.0, view["zoom"] * factor))
        after = self.screen_to_world(screen_pos)
        view["center"][0] += before[0] - after[0]
        view["center"][1] += before[1] - after[1]

    def pan_by_screen(self, dx, dy):
        view = self._view()
        zoom = view["zoom"] or 1.0
        view["center"][0] -= dx / zoom
        if self.is_elevation_view():
            view["center"][1] += dy / zoom
        else:
            view["center"][1] -= dy / zoom

    def meters_to_px(self):
        return self._view()["zoom"]

    # ------------------------------------------------------------------
    # Snapping
    # ------------------------------------------------------------------

    def _mods(self):
        if self._mods_override is not None:
            return self._mods_override
        try:
            return pygame.key.get_mods()
        except pygame.error:
            return 0

    def _level_vertices(self, level_key=None, include_ghost=True):
        level_key = level_key or self.active_level
        vertices = []
        for room in self.blueprint["rooms"]:
            if room["level"] == level_key:
                vertices.extend(tuple(p) for p in room["points"])
        if include_ghost:
            below = self.level_below(level_key)
            if below is not None:
                for room in bm.rooms_on_level(self.blueprint, below["key"]):
                    vertices.extend(tuple(p) for p in room["points"])
        return vertices

    def _level_edges(self, level_key=None, include_ghost=True):
        level_key = level_key or self.active_level
        edges = []
        keys = {level_key}
        if include_ghost:
            below = self.level_below(level_key)
            if below is not None:
                keys.add(below["key"])
        for room in self.blueprint["rooms"]:
            if room["level"] not in keys:
                continue
            points = [tuple(p) for p in room["points"]]
            for index in range(len(points)):
                edges.append((points[index], points[(index + 1) % len(points)]))
        return edges

    def snap(self, screen_pos, *, anchor=None):
        """Snapped plan point for a screen position.

        Priority: existing vertex, then existing edge, then grid (unless free
        placement).  Holding Ctrl constrains the direction from ``anchor`` to
        45° steps.
        """

        raw = self.screen_to_world(screen_pos, "plan")
        mods = self._mods()
        free = bool(mods & pygame.KMOD_SHIFT) != (not self.snap_enabled)
        constrain = bool(mods & pygame.KMOD_CTRL) and anchor is not None
        zoom = self._view("plan")["zoom"] or 1.0
        best = None
        for vertex in self._level_vertices():
            distance_px = math.dist(vertex, raw) * zoom
            if distance_px <= VERTEX_SNAP_PX and (best is None or distance_px < best[0]):
                best = (distance_px, vertex)
        if best is not None and not constrain:
            return best[1], "vertex"
        point = raw
        kind = "free"
        if not free:
            step = self.blueprint["grid"]["snap_m"]
            point = (round(raw[0] / step) * step, round(raw[1] / step) * step)
            kind = "grid"
        if constrain:
            dx, dy = point[0] - anchor[0], point[1] - anchor[1]
            length = math.hypot(dx, dy)
            if length > 1e-9:
                angle = round(math.atan2(dy, dx) / (math.pi / 4.0)) * (math.pi / 4.0)
                if not free:
                    step = self.blueprint["grid"]["snap_m"]
                    length = max(step, round(length / step) * step)
                point = (anchor[0] + math.cos(angle) * length, anchor[1] + math.sin(angle) * length)
                kind = "angle"
            return point, kind
        edge_best = None
        for a, b in self._level_edges():
            distance, t = bm.point_segment_distance(raw, a, b)
            distance_px = distance * zoom
            if distance_px <= EDGE_SNAP_PX and (edge_best is None or distance_px < edge_best[0]):
                projected = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                if not free:
                    # Keep grid alignment along axis-aligned edges.
                    step = self.blueprint["grid"]["snap_m"]
                    if abs(a[0] - b[0]) < 1e-9:
                        projected = (a[0], round(projected[1] / step) * step)
                    elif abs(a[1] - b[1]) < 1e-9:
                        projected = (round(projected[0] / step) * step, a[1])
                    distance_seg, _t = bm.point_segment_distance(projected, a, b)
                    if distance_seg > 1e-6:
                        projected = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                edge_best = (distance_px, projected)
        if edge_best is not None:
            return edge_best[1], "edge"
        return point, kind

    # ------------------------------------------------------------------
    # Levels, grid, walls, roof
    # ------------------------------------------------------------------

    def levels(self):
        return list(self.blueprint["levels"])

    def active_level_record(self):
        return bm.level_by_key(self.blueprint, self.active_level)

    def level_below(self, level_key=None):
        level_key = level_key or self.active_level
        levels = self.blueprint["levels"]
        for index, level in enumerate(levels):
            if level["key"] == level_key:
                return levels[index - 1] if index > 0 else None
        return None

    def level_above(self, level_key=None):
        level_key = level_key or self.active_level
        levels = self.blueprint["levels"]
        for index, level in enumerate(levels):
            if level["key"] == level_key:
                return levels[index + 1] if index + 1 < len(levels) else None
        return None

    def set_active_level(self, level_key):
        if bm.level_by_key(self.blueprint, level_key) is None:
            return False
        self.active_level = level_key
        self.selection = None
        self.cancel_draft()
        self._fit_pending.discard("plan")
        return self._info(f"Editing {bm.level_by_key(self.blueprint, level_key)['name']}")

    def _restack_levels(self):
        elevation = self.blueprint["levels"][0]["elevation_m"] if self.blueprint["levels"] else 0.0
        for level in self.blueprint["levels"]:
            level["elevation_m"] = elevation
            elevation += level["height_m"]

    def add_level(self):
        if not self._editable():
            return False
        self._checkpoint()
        levels = self.blueprint["levels"]
        top = levels[-1]
        existing = {level["key"] for level in levels}
        index = len(levels)
        key = f"L{index}"
        while key in existing:
            index += 1
            key = f"L{index}"
        levels.append({
            "key": key,
            "name": bm.level_default_name(len(levels)),
            "elevation_m": top["elevation_m"] + top["height_m"],
            "height_m": top["height_m"],
        })
        self._changed()
        self.active_level = key
        self.selection = None
        return self._info(f"Added {levels[-1]['name']} — trace the level below or copy its outline")

    def remove_active_level(self):
        if not self._editable():
            return False
        if len(self.blueprint["levels"]) <= 1:
            return self._error("A blueprint needs at least one level")
        self._checkpoint()
        key = self.active_level
        self.blueprint["levels"] = [level for level in self.blueprint["levels"] if level["key"] != key]
        for collection in ("rooms", "openings", "fixtures"):
            self.blueprint[collection] = [item for item in self.blueprint[collection] if item.get("level") != key]
        self.blueprint["vertical_features"] = [
            item for item in self.blueprint["vertical_features"]
            if item.get("from_level") != key and item.get("to_level") != key
        ]
        self._restack_levels()
        self.active_level = self.blueprint["levels"][0]["key"]
        self.selection = None
        self._changed()
        return self._info("Level removed")

    def adjust_level_height(self, delta):
        if not self._editable():
            return False
        level = self.active_level_record()
        if level is None:
            return False
        self._checkpoint()
        level["height_m"] = round(max(2.0, min(12.0, level["height_m"] + delta)), 2)
        self._restack_levels()
        self._changed()
        return self._info(f"{level['name']} height {level['height_m']:.2f} m")

    def copy_outline_from_below(self):
        if not self._editable():
            return False
        below = self.level_below()
        if below is None:
            return self._error("There is no level below this one")
        if bm.rooms_on_level(self.blueprint, self.active_level):
            return self._error("This level already has rooms")
        level_derived = next((item for item in self.derived["levels"] if item["key"] == below["key"]), None)
        loops = (level_derived or {}).get("outline_loops") or []
        if not loops:
            return self._error("The level below has no outline yet")
        self._checkpoint()
        existing = [room["key"] for room in self.blueprint["rooms"]]
        for loop in loops:
            key = bm.next_key(existing, "r")
            existing.append(key)
            self.blueprint["rooms"].append({
                "key": key,
                "level": self.active_level,
                "name": f"Room {len(existing)}",
                "points": [list(p) for p in loop],
            })
        self._changed()
        return self._info("Copied the outline of the level below")

    def adjust_snap(self, direction):
        current = self.blueprint["grid"]["snap_m"]
        steps = list(SNAP_STEPS_M)
        index = min(range(len(steps)), key=lambda i: abs(steps[i] - current))
        index = max(0, min(len(steps) - 1, index + direction))
        self.blueprint["grid"]["snap_m"] = steps[index]
        return self._info(f"Snap grid {steps[index]:g} m")

    def toggle_snap(self):
        self.snap_enabled = not self.snap_enabled
        return self._info("Grid snap on" if self.snap_enabled else "Free placement (grid snap off)")

    def adjust_wall_thickness(self, wall_class, delta):
        if not self._editable():
            return False
        classes = self.blueprint["wall_classes"]
        if wall_class not in classes:
            return False
        self._checkpoint()
        classes[wall_class]["thickness_m"] = round(max(0.05, min(1.5, classes[wall_class]["thickness_m"] + delta)), 3)
        self._changed()
        return self._info(f"{classes[wall_class]['label']} {classes[wall_class]['thickness_m'] * 100:.0f} cm")

    def cycle_roof_shape(self):
        if not self._editable():
            return False
        self._checkpoint()
        shapes = list(bm.ROOF_SHAPES)
        roof = self.blueprint["roof"]
        roof["shape"] = shapes[(shapes.index(roof["shape"]) + 1) % len(shapes)]
        self._changed()
        return self._info(f"Roof: {roof['shape']}")

    def adjust_roof_pitch(self, delta):
        if not self._editable():
            return False
        self._checkpoint()
        roof = self.blueprint["roof"]
        roof["pitch_deg"] = max(5.0, min(60.0, roof["pitch_deg"] + delta))
        self._changed()
        return self._info(f"Roof pitch {roof['pitch_deg']:.0f}°")

    def toggle_roof_axis(self):
        if not self._editable():
            return False
        self._checkpoint()
        roof = self.blueprint["roof"]
        roof["ridge_axis"] = "y" if roof["ridge_axis"] == "x" else "x"
        self._changed()
        return self._info("Ridge runs north–south" if roof["ridge_axis"] == "y" else "Ridge runs east–west")

    def adjust_roof_overhang(self, delta):
        if not self._editable():
            return False
        self._checkpoint()
        roof = self.blueprint["roof"]
        roof["overhang_m"] = round(max(0.0, min(2.0, roof["overhang_m"] + delta)), 2)
        self._changed()
        return self._info(f"Roof overhang {roof['overhang_m']:.2f} m")

    # ------------------------------------------------------------------
    # Stage / tool
    # ------------------------------------------------------------------

    def set_stage(self, stage):
        if stage not in {self.STAGE_GRUNDRISS, self.STAGE_DESIGN}:
            return False
        self.stage = stage
        self.cancel_draft()
        self.selection = None
        self.picker = None
        if stage == self.STAGE_DESIGN:
            if self.design_view_id not in self.views:
                self._fit_pending.add(self.design_view_id)
            return self._info("Design: pick a view, click a surface, assign a material")
        return self._info("Grundriss: draw rooms, then place openings and fixed items")

    def set_tool(self, tool):
        if tool not in self.GRUNDRISS_TOOLS:
            return False
        self.stage = self.STAGE_GRUNDRISS
        self.cancel_draft()
        self.tool = tool
        hints = {
            "select": "Click to select · drag corners · double-click an edge to add a corner · Delete removes",
            "room": "Click corners · type a length + Enter for an exact wall · click the first corner or Enter to close",
            "rect": "Click two opposite corners · or click one and type 6x4 + Enter",
            "opening": f"Click a wall to place a {bm.OPENING_CLASSES[self.opening_class]['label'].lower()}",
            "fixture": "Choose an item, then click inside a room · R rotates",
            "stair": "Click two corners of the stair on the lower level",
        }
        if tool == "fixture" and not self.pending_fixture_ref:
            self.open_fixture_picker()
        return self._info(hints[tool])

    def set_opening_class(self, opening_class):
        if opening_class not in bm.OPENING_CLASSES:
            return False
        self.opening_class = opening_class
        # In the Opening tool the class applies to the next placement; only an
        # opening picked with the Select tool is converted in place.
        if self.tool == "select" and self.selection and self.selection.get("kind") == "opening":
            opening = self._opening(self.selection["key"])
            if opening is not None and self._editable():
                self._checkpoint()
                defaults = bm.OPENING_CLASSES[opening_class]
                opening.update({
                    "opening_class": opening_class,
                    "width_m": defaults["width_m"],
                    "sill_m": defaults["sill_m"],
                    "head_m": defaults["head_m"],
                })
                self._changed()
        if self.tool != "opening" and not (self.selection and self.selection.get("kind") == "opening"):
            self.set_tool("opening")
        return self._info(f"Opening: {bm.OPENING_CLASSES[opening_class]['label']}")

    def set_design_view(self, view_id):
        if view_id not in self.DESIGN_VIEWS:
            return False
        self.stage = self.STAGE_DESIGN
        self.design_view_id = view_id
        self.selection = None
        if view_id not in self.views:
            self._fit_pending.add(view_id)
        return self._info(VIEW_LABELS.get(view_id, view_id))

    def toggle_top_roof(self):
        self.top_show_roof = not self.top_show_roof
        self.selection = None
        return self._info("Top view: roofs" if self.top_show_roof else "Top view: floors of the active level")

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def _room(self, key):
        return next((room for room in self.blueprint["rooms"] if room["key"] == key), None)

    def _opening(self, key):
        return next((item for item in self.blueprint["openings"] if item["key"] == key), None)

    def _fixture(self, key):
        return next((item for item in self.blueprint["fixtures"] if item["key"] == key), None)

    def _feature(self, key):
        return next((item for item in self.blueprint["vertical_features"] if item["key"] == key), None)

    def level_derived(self, level_key=None):
        level_key = level_key or self.active_level
        return next((level for level in self.derived["levels"] if level["key"] == level_key), None)

    def fixture_label(self, ref):
        entity = self.world_model.get_entity(ref) if self.world_model is not None and ref else None
        if isinstance(entity, dict):
            return str(entity.get("pretty_name") or entity.get("name") or ref)
        return str(ref or "Item")

    def _fixture_default_size(self, ref):
        entity = self.world_model.get_entity(ref) if self.world_model is not None and ref else None
        if isinstance(entity, dict):
            try:
                length = float(entity.get("dimension_length_m"))
                width = float(entity.get("dimension_width_m"))
                if length > 0 and width > 0:
                    return [length, width]
            except (TypeError, ValueError):
                pass
        return list(bm.DEFAULT_FIXTURE_SIZE_M)

    # ------------------------------------------------------------------
    # Room drafting
    # ------------------------------------------------------------------

    def cancel_draft(self):
        had = bool(self.draft_points or self.rect_anchor)
        self.draft_points = []
        self.rect_anchor = None
        self.length_entry = ""
        return had

    def accepts_length_entry(self):
        return (
            self.stage == self.STAGE_GRUNDRISS
            and ((self.tool == "room" and bool(self.draft_points))
                 or (self.tool in {"rect", "stair"} and self.rect_anchor is not None))
        )

    @staticmethod
    def _parse_lengths(text):
        parts = [part for part in str(text).replace(",", "x").replace("*", "x").lower().split("x") if part.strip()]
        values = []
        for part in parts:
            try:
                value = float(part)
            except ValueError:
                return None
            if value <= 0:
                return None
            values.append(value)
        return values or None

    def apply_length_entry(self):
        """Place the next corner from a typed length (or rectangle ``W x D``)."""

        values = self._parse_lengths(self.length_entry)
        self.length_entry = ""
        if not values:
            return self._error("Type a length in metres, e.g. 4.5 (rectangles: 6x4)")
        cursor = self.cursor_plan
        if self.tool == "room" and self.draft_points:
            last = self.draft_points[-1]
            dx, dy = ((cursor[0] - last[0], cursor[1] - last[1]) if cursor else (1.0, 0.0))
            span = math.hypot(dx, dy)
            if span < 1e-9:
                dx, dy, span = 1.0, 0.0, 1.0
            point = (round(last[0] + dx / span * values[0], 4), round(last[1] + dy / span * values[0], 4))
            self.draft_points.append(point)
            return self._info(f"Corner placed {values[0]:g} m along the cursor direction")
        if self.tool in {"rect", "stair"} and self.rect_anchor is not None:
            width = values[0]
            depth = values[1] if len(values) > 1 else values[0]
            anchor = self.rect_anchor
            sign_x = -1.0 if cursor and cursor[0] < anchor[0] else 1.0
            sign_y = -1.0 if cursor and cursor[1] < anchor[1] else 1.0
            corner = (anchor[0] + sign_x * width, anchor[1] + sign_y * depth)
            x0, x1 = sorted((anchor[0], corner[0]))
            y0, y1 = sorted((anchor[1], corner[1]))
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            ok = self._add_stair(corners) if self.tool == "stair" else self._add_room(corners)
            if ok:
                self.rect_anchor = None
            return ok
        return False

    def _add_room(self, points, name=None):
        if not self._editable():
            return False
        points = [(round(p[0], 4), round(p[1], 4)) for p in points]
        problem = bm.validate_room_polygon(self.blueprint, self.active_level, points)
        if problem:
            return self._error(problem)
        if bm.polygon_signed_area(points) < 0:
            points = list(reversed(points))
        self._checkpoint()
        key = bm.next_key([room["key"] for room in self.blueprint["rooms"]], "r")
        room_number = len(self.blueprint["rooms"]) + 1
        self.blueprint["rooms"].append({
            "key": key,
            "level": self.active_level,
            "name": name or f"Room {room_number}",
            "points": [list(p) for p in points],
        })
        self._changed()
        self.selection = {"kind": "room", "key": key}
        metrics = self.derived["rooms"].get(key, {})
        return self._info(
            f"{name or f'Room {room_number}'}: {metrics.get('gross_area_m2', 0.0):.2f} m² "
            f"({metrics.get('net_area_m2', 0.0):.2f} m² usable)"
        )

    def finish_room_draft(self):
        if len(self.draft_points) < 3:
            return self._error("A room needs at least three corners")
        points = list(self.draft_points)
        if self._add_room(points):
            self.draft_points = []
            return True
        return False

    def _handle_room_click(self, screen_pos, double=False):
        anchor = self.draft_points[-1] if self.draft_points else None
        point, _kind = self.snap(screen_pos, anchor=anchor)
        if self.draft_points:
            first_screen = self.world_to_screen(self.draft_points[0], "plan")
            if len(self.draft_points) >= 3 and math.dist(first_screen, screen_pos) <= VERTEX_SNAP_PX:
                return self.finish_room_draft()
            if double and len(self.draft_points) >= 3:
                return self.finish_room_draft()
            if math.dist(point, self.draft_points[-1]) < bm.POINT_TOLERANCE_M:
                return False
        self.draft_points.append(point)
        return True

    def _handle_rect_click(self, screen_pos):
        point, _kind = self.snap(screen_pos)
        if self.rect_anchor is None:
            self.rect_anchor = point
            return True
        anchor = self.rect_anchor
        if abs(point[0] - anchor[0]) < 0.3 or abs(point[1] - anchor[1]) < 0.3:
            return self._error("Rectangle is too thin")
        x0, x1 = sorted((anchor[0], point[0]))
        y0, y1 = sorted((anchor[1], point[1]))
        target = "stair" if self.tool == "stair" else "room"
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if target == "stair":
            ok = self._add_stair(corners)
        else:
            ok = self._add_room(corners)
        if ok:
            self.rect_anchor = None
        return ok

    def _add_stair(self, corners):
        if not self._editable():
            return False
        above = self.level_above()
        if above is None:
            return self._error("Add a level above before placing a stair")
        self._checkpoint()
        key = bm.next_key([item["key"] for item in self.blueprint["vertical_features"]], "v")
        self.blueprint["vertical_features"].append({
            "key": key,
            "kind": "stair",
            "from_level": self.active_level,
            "to_level": above["key"],
            "points": [list(p) for p in corners],
        })
        self._changed()
        self.selection = {"kind": "stair", "key": key}
        return self._info(f"Stair to {above['name']}")

    # ------------------------------------------------------------------
    # Openings and fixtures
    # ------------------------------------------------------------------

    def nearest_wall(self, plan_point, level_key=None, max_distance_m=None):
        level = self.level_derived(level_key)
        if level is None:
            return None
        best = None
        for wall in level["walls"]:
            distance, t = bm.point_segment_distance(plan_point, wall["start"], wall["end"])
            if max_distance_m is not None and distance > max_distance_m:
                continue
            if best is None or distance < best[0]:
                best = (distance, t, wall)
        return best

    def opening_preview(self):
        if self.tool != "opening" or self.cursor_raw is None:
            return None
        zoom = self._view("plan")["zoom"] or 1.0
        hit = self.nearest_wall(self.cursor_raw, max_distance_m=max(0.6, 14.0 / zoom))
        if hit is None:
            return None
        _distance, t, wall = hit
        defaults = bm.OPENING_CLASSES[self.opening_class]
        length = wall["length_m"]
        width = min(defaults["width_m"], length - 0.1)
        if width < 0.3:
            return None
        step = self.blueprint["grid"]["snap_m"] / 2.0
        offset = t * length
        mods = self._mods()
        if self.snap_enabled != bool(mods & pygame.KMOD_SHIFT):
            offset = round(offset / step) * step
        offset = max(width / 2.0 + 0.05, min(length - width / 2.0 - 0.05, offset))
        dx = (wall["end"][0] - wall["start"][0]) / (length or 1.0)
        dy = (wall["end"][1] - wall["start"][1]) / (length or 1.0)
        center = (wall["start"][0] + dx * offset, wall["start"][1] + dy * offset)
        return {
            "wall": wall,
            "center": center,
            "width_m": width,
            "offset_m": offset,
            "start": (center[0] - dx * width / 2.0, center[1] - dy * width / 2.0),
            "end": (center[0] + dx * width / 2.0, center[1] + dy * width / 2.0),
            "from_start_m": offset - width / 2.0,
            "to_end_m": length - offset - width / 2.0,
        }

    def place_opening(self):
        if not self._editable():
            return False
        preview = self.opening_preview()
        if preview is None:
            return self._error("Move onto a wall to place the opening")
        wall = preview["wall"]
        low = preview["offset_m"] - preview["width_m"] / 2.0
        high = preview["offset_m"] + preview["width_m"] / 2.0
        for existing in wall["openings"]:
            e_low = existing["offset_m"] - existing["width_m"] / 2.0
            e_high = existing["offset_m"] + existing["width_m"] / 2.0
            if low < e_high - 0.02 and e_low < high - 0.02:
                return self._error("Openings would overlap")
        self._checkpoint()
        defaults = bm.OPENING_CLASSES[self.opening_class]
        key = bm.next_key([item["key"] for item in self.blueprint["openings"]], "o")
        self.blueprint["openings"].append({
            "key": key,
            "level": self.active_level,
            "center": [round(preview["center"][0], 4), round(preview["center"][1], 4)],
            "opening_class": self.opening_class,
            "width_m": preview["width_m"],
            "sill_m": defaults["sill_m"],
            "head_m": defaults["head_m"],
        })
        self._changed()
        self.selection = {"kind": "opening", "key": key}
        return self._info(f"{defaults['label']} {preview['width_m']:.2f} m placed")

    def adjust_opening_width(self, delta):
        if not (self.selection and self.selection.get("kind") == "opening") or not self._editable():
            return False
        opening = self._opening(self.selection["key"])
        if opening is None:
            return False
        self._checkpoint()
        opening["width_m"] = round(max(0.4, min(12.0, opening["width_m"] + delta)), 2)
        self._changed()
        return self._info(f"Opening width {opening['width_m']:.2f} m")

    def adjust_opening_sill(self, delta):
        if not (self.selection and self.selection.get("kind") == "opening") or not self._editable():
            return False
        opening = self._opening(self.selection["key"])
        if opening is None:
            return False
        self._checkpoint()
        opening["sill_m"] = round(max(0.0, min(opening["head_m"] - 0.3, opening["sill_m"] + delta)), 2)
        self._changed()
        return self._info(f"Sill {opening['sill_m']:.2f} m")

    def adjust_opening_head(self, delta):
        if not (self.selection and self.selection.get("kind") == "opening") or not self._editable():
            return False
        opening = self._opening(self.selection["key"])
        if opening is None:
            return False
        self._checkpoint()
        level = bm.level_by_key(self.blueprint, opening["level"]) or {"height_m": 3.0}
        opening["head_m"] = round(max(opening["sill_m"] + 0.3, min(level["height_m"], opening["head_m"] + delta)), 2)
        self._changed()
        return self._info(f"Head height {opening['head_m']:.2f} m")

    def fixture_catalog(self, show_all=False):
        if self.world_model is None:
            return []
        getter = getattr(self.world_model, "get_dataset", None)
        options = []
        for dataset in ("items", "components"):
            for entity in (getter(dataset) if callable(getter) else []) or []:
                if not isinstance(entity, dict) or not entity.get("id"):
                    continue
                contexts = entity.get("install_contexts") or []
                if isinstance(contexts, str):
                    contexts = [contexts]
                vehicle_only = bool(contexts) and set(contexts) <= {"vehicle"}
                relevant = (
                    "building" in contexts
                    or bool(entity.get("placeable"))
                    or (dataset == "components" and not contexts)
                )
                if not show_all and (vehicle_only or not relevant):
                    continue
                options.append({
                    "id": entity["id"],
                    "label": entity.get("pretty_name") or entity.get("name") or entity["id"],
                    "detail": "component" if dataset == "components" else "item",
                })
        options.sort(key=lambda item: str(item["label"]).lower())
        return options

    def open_fixture_picker(self):
        self.picker = {"kind": "fixture", "query": "", "scroll": 0, "show_all": False}
        return True

    def choose_fixture(self, ref):
        self.pending_fixture_ref = ref
        self.picker = None
        self.tool = "fixture"
        self.stage = self.STAGE_GRUNDRISS
        return self._info(f"Click inside a room to place {self.fixture_label(ref)} · R rotates")

    def fixture_preview(self):
        if self.tool != "fixture" or not self.pending_fixture_ref or self.cursor_plan is None:
            return None
        size = self._fixture_default_size(self.pending_fixture_ref)
        return {
            "ref": self.pending_fixture_ref,
            "position": self.cursor_plan,
            "size_m": size,
            "rotation_deg": self.fixture_rotation,
            "points": bm.rectangle_points(self.cursor_plan, size, self.fixture_rotation),
        }

    def place_fixture(self):
        if not self._editable():
            return False
        preview = self.fixture_preview()
        if preview is None:
            return self._error("Choose an item first")
        inside = any(
            bm.point_in_polygon(preview["position"], bm.room_polygon(room))
            for room in bm.rooms_on_level(self.blueprint, self.active_level)
        )
        if not inside:
            return self._error("Fixed items go inside a room")
        self._checkpoint()
        key = bm.next_key([item["key"] for item in self.blueprint["fixtures"]], "f")
        self.blueprint["fixtures"].append({
            "key": key,
            "ref": preview["ref"],
            "level": self.active_level,
            "position": [round(preview["position"][0], 4), round(preview["position"][1], 4)],
            "rotation_deg": preview["rotation_deg"],
            "size_m": preview["size_m"],
        })
        self._changed()
        self.selection = {"kind": "fixture", "key": key}
        return self._info(f"Placed {self.fixture_label(preview['ref'])}")

    def rotate_fixture(self, degrees=90.0):
        if self.selection and self.selection.get("kind") == "fixture":
            fixture = self._fixture(self.selection["key"])
            if fixture is None or not self._editable():
                return False
            self._checkpoint()
            fixture["rotation_deg"] = (fixture["rotation_deg"] + degrees) % 360.0
            self._changed()
            return self._info(f"Rotated to {fixture['rotation_deg']:.0f}°")
        self.fixture_rotation = (self.fixture_rotation + degrees) % 360.0
        return self._info(f"Placement rotation {self.fixture_rotation:.0f}°")

    # ------------------------------------------------------------------
    # Selection and editing
    # ------------------------------------------------------------------

    def _pick_plan(self, screen_pos):
        """Return the plan element under the cursor on the active level."""

        plan = self.screen_to_world(screen_pos, "plan")
        zoom = self._view("plan")["zoom"] or 1.0
        tolerance_m = 8.0 / zoom
        level = self.active_level
        for fixture in reversed(self.blueprint["fixtures"]):
            if fixture["level"] != level:
                continue
            if bm.point_in_polygon(plan, bm.rectangle_points(fixture["position"], fixture["size_m"], fixture["rotation_deg"])):
                return {"kind": "fixture", "key": fixture["key"]}
        level_derived = self.level_derived()
        for wall in (level_derived or {}).get("walls", []):
            for opening in wall["openings"]:
                distance, _t = bm.point_segment_distance(plan, opening["start"], opening["end"])
                if distance <= max(tolerance_m, wall["thickness_m"] / 2.0 + 0.05):
                    return {"kind": "opening", "key": opening["key"]}
        for room in bm.rooms_on_level(self.blueprint, level):
            for index, point in enumerate(room["points"]):
                if math.dist(self.world_to_screen(point, "plan"), screen_pos) <= VERTEX_SNAP_PX:
                    return {"kind": "vertex", "room": room["key"], "index": index, "point": tuple(point)}
        for feature in self.blueprint["vertical_features"]:
            if feature["from_level"] == level and bm.point_in_polygon(plan, [tuple(p) for p in feature["points"]]):
                return {"kind": "stair", "key": feature["key"]}
        for wall in (level_derived or {}).get("walls", []):
            distance, _t = bm.point_segment_distance(plan, wall["start"], wall["end"])
            if distance <= max(tolerance_m, wall["thickness_m"] / 2.0):
                return {"kind": "wall", "key": wall["key"]}
        for room in reversed(bm.rooms_on_level(self.blueprint, level)):
            if bm.point_in_polygon(plan, bm.room_polygon(room)):
                return {"kind": "room", "key": room["key"]}
        return None

    def select(self, selection):
        self.selection = selection
        return True

    def delete_selection(self):
        selection = self.selection
        if not selection or not self._editable():
            return False
        kind = selection.get("kind")
        self._checkpoint()
        if kind == "room":
            room = self._room(selection["key"])
            if room is None:
                return False
            polygon = bm.room_polygon(room)
            self.blueprint["rooms"] = [r for r in self.blueprint["rooms"] if r["key"] != room["key"]]
            self.blueprint["fixtures"] = [
                f for f in self.blueprint["fixtures"]
                if not (f["level"] == room["level"] and bm.point_in_polygon(tuple(f["position"]), polygon))
            ]
            self._changed()
            self._drop_detached_openings()
            message = f"Deleted {room['name']}"
        elif kind == "opening":
            self.blueprint["openings"] = [o for o in self.blueprint["openings"] if o["key"] != selection["key"]]
            message = "Opening removed"
        elif kind == "fixture":
            self.blueprint["fixtures"] = [f for f in self.blueprint["fixtures"] if f["key"] != selection["key"]]
            message = "Fixed item removed"
        elif kind == "stair":
            self.blueprint["vertical_features"] = [
                v for v in self.blueprint["vertical_features"] if v["key"] != selection["key"]
            ]
            message = "Stair removed"
        elif kind == "vertex":
            room = self._room(selection["room"])
            if room is None or len(room["points"]) <= 3:
                self.undo_stack.pop()
                return self._error("A room needs at least three corners")
            candidate = [p for i, p in enumerate(room["points"]) if i != selection["index"]]
            problem = bm.validate_room_polygon(self.blueprint, room["level"], candidate, ignore_room_key=room["key"])
            if problem:
                self.undo_stack.pop()
                return self._error(problem)
            room["points"] = candidate
            message = "Corner removed"
        else:
            self.undo_stack.pop()
            return False
        self.selection = None
        self._changed()
        return self._info(message)

    def _drop_detached_openings(self):
        attached = {o["key"] for wall in self.derived["walls"] for o in wall["openings"]}
        self.blueprint["openings"] = [o for o in self.blueprint["openings"] if o["key"] in attached]

    def _reattach_openings(self):
        """Keep openings on their walls after the room geometry changed."""

        for opening in self.blueprint["openings"]:
            hit = self.nearest_wall(tuple(opening["center"]), level_key=opening["level"], max_distance_m=1.5)
            if hit is None:
                continue
            _distance, t, wall = hit
            point = (
                wall["start"][0] + (wall["end"][0] - wall["start"][0]) * t,
                wall["start"][1] + (wall["end"][1] - wall["start"][1]) * t,
            )
            opening["center"] = [round(point[0], 4), round(point[1], 4)]

    def insert_vertex_on_edge(self, screen_pos):
        if not self._editable():
            return False
        plan = self.screen_to_world(screen_pos, "plan")
        zoom = self._view("plan")["zoom"] or 1.0
        best = None
        for room in bm.rooms_on_level(self.blueprint, self.active_level):
            points = room["points"]
            for index in range(len(points)):
                a, b = tuple(points[index]), tuple(points[(index + 1) % len(points)])
                distance, t = bm.point_segment_distance(plan, a, b)
                if distance * zoom <= EDGE_SNAP_PX and 0.02 < t < 0.98 and (best is None or distance < best[0]):
                    best = (distance, room, index, t, a, b)
        if best is None:
            return False
        _distance, room, index, _t, a, b = best
        point, _kind = self.snap(screen_pos)
        if bm.point_segment_distance(point, a, b)[0] > 1e-6:
            point = (a[0] + (b[0] - a[0]) * best[3], a[1] + (b[1] - a[1]) * best[3])
        self._checkpoint()
        # Insert into every room that shares this edge so the wall stays shared.
        for other in bm.rooms_on_level(self.blueprint, self.active_level):
            pts = other["points"]
            for i in range(len(pts)):
                c, d = tuple(pts[i]), tuple(pts[(i + 1) % len(pts)])
                if bm.point_segment_distance(point, c, d)[0] <= bm.POINT_TOLERANCE_M and \
                        math.dist(point, c) > bm.POINT_TOLERANCE_M and math.dist(point, d) > bm.POINT_TOLERANCE_M:
                    pts.insert(i + 1, [round(point[0], 4), round(point[1], 4)])
                    break
        self._changed()
        vertex_index = next(
            (i for i, p in enumerate(room["points"]) if math.dist(tuple(p), point) <= bm.POINT_TOLERANCE_M),
            index + 1,
        )
        self.selection = {"kind": "vertex", "room": room["key"], "index": vertex_index, "point": point}
        return self._info("Corner added — drag it to reshape")

    def _begin_vertex_drag(self, pick):
        grabbed = pick["point"]
        members = []
        for room in bm.rooms_on_level(self.blueprint, self.active_level):
            for index, point in enumerate(room["points"]):
                if math.dist(tuple(point), grabbed) <= bm.POINT_TOLERANCE_M:
                    members.append((room["key"], index))
        self.drag = {
            "kind": "vertex",
            "members": members,
            "origin": grabbed,
            "before": copy.deepcopy(self.blueprint),
            "moved": False,
        }

    def _update_vertex_drag(self, screen_pos):
        point, _kind = self.snap(screen_pos)
        drag = self.drag
        if math.dist(point, drag["origin"]) > 1e-6:
            drag["moved"] = True
        for room_key, index in drag["members"]:
            room = self._room(room_key)
            if room is not None and index < len(room["points"]):
                room["points"][index] = [round(point[0], 4), round(point[1], 4)]
        self.derived = bm.derive_geometry(self.blueprint)

    def _finish_vertex_drag(self):
        drag = self.drag
        self.drag = None
        if not drag["moved"]:
            self.blueprint = drag["before"]
            self._changed()
            return False
        for room_key, _index in drag["members"]:
            room = self._room(room_key)
            if room is None:
                continue
            problem = bm.validate_room_polygon(self.blueprint, room["level"], room["points"], ignore_room_key=room_key)
            if problem:
                self.blueprint = drag["before"]
                self._changed()
                return self._error(f"{room['name']}: {problem}")
        self.undo_stack.append(drag["before"])
        self.redo_stack = []
        self._changed()
        self._reattach_openings()
        self._changed()
        return self._info("Corner moved")

    def _begin_item_drag(self, pick, screen_pos):
        self.drag = {
            "kind": pick["kind"],
            "key": pick["key"],
            "start_screen": screen_pos,
            "before": copy.deepcopy(self.blueprint),
            "moved": False,
        }

    def _update_item_drag(self, screen_pos):
        drag = self.drag
        if not drag["moved"] and math.dist(drag["start_screen"], screen_pos) < 4:
            return
        drag["moved"] = True
        if drag["kind"] == "fixture":
            fixture = self._fixture(drag["key"])
            if fixture is not None:
                point, _kind = self.snap(screen_pos)
                fixture["position"] = [round(point[0], 4), round(point[1], 4)]
        elif drag["kind"] == "opening":
            opening = self._opening(drag["key"])
            if opening is not None:
                plan = self.screen_to_world(screen_pos, "plan")
                hit = self.nearest_wall(plan, level_key=opening["level"], max_distance_m=2.0)
                if hit is not None:
                    _d, t, wall = hit
                    opening["center"] = [
                        round(wall["start"][0] + (wall["end"][0] - wall["start"][0]) * t, 4),
                        round(wall["start"][1] + (wall["end"][1] - wall["start"][1]) * t, 4),
                    ]
        self.derived = bm.derive_geometry(self.blueprint)

    def _finish_item_drag(self):
        drag = self.drag
        self.drag = None
        if not drag["moved"]:
            return False
        if drag["kind"] == "fixture":
            fixture = self._fixture(drag["key"])
            inside = fixture is not None and any(
                bm.point_in_polygon(tuple(fixture["position"]), bm.room_polygon(room))
                for room in bm.rooms_on_level(self.blueprint, fixture["level"])
            )
            if not inside:
                self.blueprint = drag["before"]
                self._changed()
                return self._error("Fixed items go inside a room")
        self.undo_stack.append(drag["before"])
        self.redo_stack = []
        self._changed()
        return self._info("Moved")

    def begin_rename(self):
        selection = self.selection or {}
        if selection.get("kind") != "room" or not self._editable():
            return False
        room = self._room(selection["key"])
        if room is None:
            return False
        self.text_edit = {"target": ("room", room["key"]), "buffer": room["name"]}
        return self._info("Type a name · Enter to confirm · Esc to cancel")

    def commit_rename(self):
        edit = self.text_edit
        self.text_edit = None
        if not edit:
            return False
        kind, key = edit["target"]
        name = " ".join(str(edit["buffer"]).split())
        if kind == "room" and name:
            room = self._room(key)
            if room is not None and room["name"] != name:
                self._checkpoint()
                room["name"] = name
                self._changed()
                return self._info(f"Renamed to {name}")
        return False

    # ------------------------------------------------------------------
    # Design stage: surfaces and materials
    # ------------------------------------------------------------------

    def design_primitives(self, view_id=None):
        view_id = view_id or self.design_view_id
        if view_id == "top":
            return top_primitives(self.blueprint, self.derived, show_roof=self.top_show_roof, level_key=self.active_level)
        return elevation_primitives(self.blueprint, self.derived, view_id)

    def material_for(self, surface_key, role):
        return bm.surface_material(self.blueprint, surface_key, role)

    def _pick_design(self, screen_pos):
        world = self.screen_to_world(screen_pos)
        for primitive in reversed(self.design_primitives()):
            if bm.point_in_polygon(world, [tuple(p) for p in primitive["polygon"]]):
                return {
                    "kind": "surface",
                    "key": primitive["surface_key"],
                    "role": primitive.get("role"),
                    "room": primitive.get("room"),
                }
        return None

    def open_material_picker(self, *, role=None, surface_key=None, room_walls=None):
        self.picker = {
            "kind": "material",
            "role": role,
            "surface_key": surface_key,
            "room_walls": room_walls,
            "query": "",
            "scroll": 0,
            "show_all": False,
        }
        return True

    def material_catalog(self, show_all=False):
        if self.world_model is None:
            return []
        getter = getattr(self.world_model, "get_dataset", None)
        options = []
        for entity in (getter("materials") if callable(getter) else []) or []:
            if not isinstance(entity, dict) or not entity.get("id"):
                continue
            tags = entity.get("tags") or []
            material_class = str(entity.get("material_class") or "")
            construction = "construction_material" in tags or bool(entity.get("material_texture_set_ref"))
            relevant = construction or material_class == "engineered_material" or entity.get("material_form") == "engineered_stock"
            if not show_all and not relevant:
                continue
            options.append({
                "id": entity["id"],
                "label": entity.get("pretty_name") or entity.get("name") or entity["id"],
                "detail": "construction" if construction else (entity.get("material_subclass") or material_class or "material"),
                "color": self.materials.color(entity["id"]),
                "construction": construction,
            })
        options.sort(key=lambda item: (not item["construction"], str(item["label"]).lower()))
        return options

    def choose_material(self, material_id):
        picker = self.picker or {}
        self.picker = None
        if not self._editable():
            return False
        self._checkpoint()
        if picker.get("room_walls"):
            room = self._room(picker["room_walls"])
            if room is None:
                self.undo_stack.pop()
                return False
            for index in range(len(room["points"])):
                self.blueprint["surface_materials"][f"room:{room['key']}:edge:{index}:inner"] = material_id
            message = f"{room['name']} walls: {self.materials.name(material_id)}"
        elif picker.get("surface_key"):
            self.blueprint["surface_materials"][picker["surface_key"]] = material_id
            message = f"Surface material: {self.materials.name(material_id)}"
        elif picker.get("role"):
            self.blueprint["default_materials"][picker["role"]] = material_id
            message = f"{bm.MATERIAL_ROLE_LABELS.get(picker['role'], picker['role'])}: {self.materials.name(material_id)}"
        else:
            self.undo_stack.pop()
            return False
        self._changed()
        return self._info(message)

    def clear_surface_material(self):
        selection = self.selection or {}
        key = selection.get("key")
        if selection.get("kind") != "surface" or key not in self.blueprint["surface_materials"]:
            return False
        if not self._editable():
            return False
        self._checkpoint()
        self.blueprint["surface_materials"].pop(key, None)
        self._changed()
        return self._info("Surface uses the default material again")

    # ------------------------------------------------------------------
    # Pixel Studio details
    # ------------------------------------------------------------------

    def is_vehicle_pixel_editor_active(self):
        # UIManager's shared Pixel Studio bridge keeps its historical name.
        return isinstance(self.pixel_art_editor, dict) and bool(self.pixel_art_editor.get("embedded"))

    # Pixel Studio only reads this for illustration saves, not embedded views.
    PROJECT_ROOT = STORE_PROJECT_ROOT

    @staticmethod
    def _ellipsize_text(text, font, max_width):
        text = str(text or "")
        if font.size(text)[0] <= max_width:
            return text
        while text and font.size(text + "…")[0] > max_width:
            text = text[:-1]
        return text + "…"

    def detail_frame(self, view_id=None):
        """Detail canvas extent in view metres (u0, v0, u1, v1)."""

        view_id = view_id or self.design_view_id
        existing = self.blueprint["view_details"].get(view_id)
        if isinstance(existing, dict) and existing.get("frame_m"):
            return tuple(existing["frame_m"])
        frame = view_frame(self.blueprint, self.derived, view_id, level_key=self.active_level, margin_m=0.5)
        return frame

    def _raster_view(self, view_id, frame, width, height):
        """Render the material view and its paintable silhouette to pixels."""

        u0, v0, u1, v1 = frame
        ppm = bm.PIXELS_PER_METER
        surface = pygame.Surface((width, height), pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        mask_surface = pygame.Surface((width, height), pygame.SRCALPHA)
        mask_surface.fill((0, 0, 0, 0))

        def to_px(point):
            if view_id == "top":
                return ((point[0] - u0) * ppm, (point[1] - v0) * ppm)
            return ((point[0] - u0) * ppm, (v1 - point[1]) * ppm)

        if view_id == "top":
            primitives = top_primitives(self.blueprint, self.derived, show_roof=True)
        else:
            primitives = elevation_primitives(self.blueprint, self.derived, view_id)
        anchor = to_px((u0, v1) if view_id != "top" else (u0, v0))
        for primitive in primitives:
            points = [to_px(p) for p in primitive["polygon"]]
            material = self.material_for(primitive["surface_key"], primitive.get("role"))
            self.materials.fill_polygon(surface, points, material, primitive.get("role"), meters_to_px=ppm,
                                        anchor=anchor, shade=primitive.get("shade", 1.0),
                                        seed_key=primitive["surface_key"])
            pygame.draw.polygon(mask_surface, (255, 255, 255, 255), points)
        pixels = []
        mask = []
        for y in range(height):
            row = []
            mask_row = []
            for x in range(width):
                color = surface.get_at((x, y))
                row.append([color.r, color.g, color.b] if color.a > 0 else None)
                mask_row.append(mask_surface.get_at((x, y)).a > 0)
            pixels.append(row)
            mask.append(mask_row)
        return pixels, mask

    def open_detail_painter(self):
        if self.stage != self.STAGE_DESIGN:
            return False
        if not self._editable():
            return False
        view_id = self.design_view_id
        frame = self.detail_frame(view_id)
        if frame is None:
            return self._error("Draw rooms first — there is nothing to paint yet")
        ppm = bm.PIXELS_PER_METER
        width = max(1, int(math.ceil((frame[2] - frame[0]) * ppm)))
        height = max(1, int(math.ceil((frame[3] - frame[1]) * ppm)))
        if width > MAX_DETAIL_CANVAS_PX or height > MAX_DETAIL_CANVAS_PX:
            return self._error(f"View is {width}×{height} px at {ppm} px/m — too large to paint in one canvas")
        reference, mask = self._raster_view(view_id, frame, width, height)
        existing = self.blueprint["view_details"].get(view_id) or {}
        detail_layers = [
            copy.deepcopy(layer) for layer in existing.get("layers") or []
            if isinstance(layer, dict) and not layer.get("reference_only")
        ]
        if not detail_layers or existing.get("width") != width or existing.get("height") != height:
            detail_layers = [{
                "name": "Details",
                "visible": True,
                "opacity": 1.0,
                "reference_only": False,
                "locked": False,
                "pixels": [[None] * width for _ in range(height)],
            }] if not detail_layers else detail_layers
        layers = [{
            "name": "Material render",
            "visible": True,
            "opacity": 1.0,
            "reference_only": True,
            "locked": True,
            "pixels": reference,
        }] + detail_layers
        self._detail_session = {"view_id": view_id, "frame": list(frame), "width": width, "height": height}
        opened = self.pixel_art_editor_ui.open_embedded(
            title=f"{self.get_blueprint_name()} · {VIEW_LABELS.get(view_id, view_id)}",
            views={view_id: {
                "name": VIEW_LABELS.get(view_id, view_id),
                "width": width,
                "height": height,
                "active_layer": 1,
                "layers": layers,
            }},
            active_view=view_id,
            masks={view_id: mask},
            on_save=self._save_detail_views,
            finish_on_save=False,
            context_label="building",
        )
        if opened:
            self.pixel_art_editor["status"] = (
                f"Paint details over the material render · {ppm} px per metre · clipped to the building"
            )
        return opened

    def _save_detail_views(self, views, masks):
        session = getattr(self, "_detail_session", None) or {}
        view_id = session.get("view_id")
        view = (views or {}).get(view_id) or {}
        layers = [layer for layer in view.get("layers") or [] if not layer.get("reference_only")]
        if not view_id or not layers:
            return False
        self._checkpoint()
        self.blueprint["view_details"][view_id] = {
            "frame_m": list(session["frame"]),
            "pixels_per_meter": bm.PIXELS_PER_METER,
            "width": session["width"],
            "height": session["height"],
            "layers": copy.deepcopy(layers),
        }
        self._changed()
        self._info(f"{VIEW_LABELS.get(view_id, view_id)} details applied — Save to keep them")
        return True

    def clear_view_details(self):
        view_id = self.design_view_id
        if view_id not in self.blueprint["view_details"] or not self._editable():
            return False
        self._checkpoint()
        self.blueprint["view_details"].pop(view_id, None)
        self._changed()
        return self._info("Details cleared")

    # ------------------------------------------------------------------
    # Pickers (material / fixture / placement parent)
    # ------------------------------------------------------------------

    def picker_options(self):
        picker = self.picker or {}
        kind = picker.get("kind")
        if kind == "material":
            options = self.material_catalog(show_all=picker.get("show_all", False))
        elif kind == "fixture":
            options = self.fixture_catalog(show_all=picker.get("show_all", False))
        elif kind == "parent":
            options = self.placement_parent_options()
        else:
            return []
        query = str(picker.get("query") or "").casefold().strip()
        if query:
            options = [
                option for option in options
                if query in str(option["label"]).casefold() or query in str(option["id"]).casefold()
            ]
        return options

    def open_parent_picker(self):
        self.picker = {"kind": "parent", "query": "", "scroll": 0}
        return True

    def choose_picker_option(self, option_id):
        kind = (self.picker or {}).get("kind")
        if kind == "material":
            return self.choose_material(option_id)
        if kind == "fixture":
            return self.choose_fixture(option_id)
        if kind == "parent":
            return self.request_place_on_parent(option_id)
        return False

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def update(self, dt):
        self.sim_manager.update(dt)

    def draw(self):
        """Rendering is dispatched through BlueprintDesignerRenderer."""

    def get_center(self):
        return 0.0, 0.0

    def get_initial_camera_zoom(self, screen_w, screen_h):
        return 1.0

    def consumes_camera_update(self):
        return True

    def consumes_global_keydown(self):
        # Only modal states capture every key; otherwise app keys (Tab, time
        # controls) keep working and Delete/R/F still reach handle_event.
        return bool(
            self.is_vehicle_pixel_editor_active()
            or self.text_edit is not None
            or self.picker is not None
            or self.draft_points
            or self.rect_anchor is not None
            or self.drag is not None
        )

    def consumes_global_escape(self):
        return self.consumes_global_keydown() or self.selection is not None

    def handle_pre_camera_event(self, event):
        if event.type != pygame.MOUSEWHEEL:
            return False
        if self.is_vehicle_pixel_editor_active():
            return False
        try:
            pos = pygame.mouse.get_pos()
        except pygame.error:
            pos = self.canvas_rect.center
        return self.handle_wheel(getattr(event, "y", 0), pos)

    def handle_wheel(self, amount, pos):
        if self.picker is not None:
            self.picker["scroll"] = max(0, int(self.picker.get("scroll", 0)) - int(amount) * 3)
            return True
        for side, rect in self.panel_rects.items():
            if rect.collidepoint(pos):
                self.panel_scroll[side] = max(0, int(self.panel_scroll.get(side, 0)) - int(amount * 40))
                return True
        if self.canvas_rect.collidepoint(pos):
            if amount:
                self.zoom_at(pos, 1.15 ** float(amount))
            return True
        return True

    def handle_event(self, event):
        if event.type != pygame.KEYDOWN:
            return False
        if self.is_vehicle_pixel_editor_active():
            return self.pixel_art_editor_ui.handle_keydown(event)
        key = event.key
        mods = getattr(event, "mod", 0) or 0
        if self.text_edit is not None:
            if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.commit_rename()
            elif key == pygame.K_ESCAPE:
                self.text_edit = None
            elif key == pygame.K_BACKSPACE:
                self.text_edit["buffer"] = self.text_edit["buffer"][:-1]
            elif getattr(event, "unicode", "") and event.unicode.isprintable():
                self.text_edit["buffer"] += event.unicode
            return True
        if self.picker is not None:
            if key == pygame.K_ESCAPE:
                self.picker = None
            elif key == pygame.K_BACKSPACE:
                self.picker["query"] = self.picker["query"][:-1]
                self.picker["scroll"] = 0
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                options = self.picker_options()
                if len(options) == 1:
                    self.choose_picker_option(options[0]["id"])
            elif getattr(event, "unicode", "") and event.unicode.isprintable():
                self.picker["query"] += event.unicode
                self.picker["scroll"] = 0
            return True
        if self.accepts_length_entry() and not (mods & pygame.KMOD_CTRL):
            char = getattr(event, "unicode", "") or ""
            if char and (char.isdigit() or char in ".,xX*"):
                self.length_entry += char.lower()
                return True
            if self.length_entry and key == pygame.K_BACKSPACE:
                self.length_entry = self.length_entry[:-1]
                return True
            if self.length_entry and key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self.apply_length_entry()
            if self.length_entry and key == pygame.K_ESCAPE:
                self.length_entry = ""
                return True
        if mods & pygame.KMOD_CTRL:
            if key == pygame.K_z:
                return self.undo()
            if key == pygame.K_y:
                return self.redo()
            if key == pygame.K_s:
                return self.save()
        if key == pygame.K_ESCAPE:
            if self.cancel_draft():
                return self._info("Draft cancelled")
            if self.selection is not None:
                self.selection = None
                return True
            return False
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.draft_points:
                return self.finish_room_draft()
            return False
        if key == pygame.K_BACKSPACE:
            if self.draft_points:
                self.draft_points.pop()
                return True
            if self.rect_anchor is not None:
                self.rect_anchor = None
                return True
            return self.delete_selection()
        if key == pygame.K_DELETE:
            return self.delete_selection()
        if key == pygame.K_r and self.stage == self.STAGE_GRUNDRISS:
            return self.rotate_fixture(90.0 if not (mods & pygame.KMOD_SHIFT) else 15.0)
        if key == pygame.K_f:
            return self.fit_view()
        return False

    def _is_double_click(self, screen_pos):
        now = time.monotonic()
        double = (
            self._last_click_pos is not None
            and now - self._last_click_time <= DOUBLE_CLICK_S
            and math.dist(self._last_click_pos, screen_pos) <= 6
        )
        self._last_click_time = now
        self._last_click_pos = screen_pos
        return double

    def handle_pointer_motion(self, event, camera=None, screen_pos=None):
        screen_pos = screen_pos or getattr(event, "pos", None)
        if screen_pos is None or self.is_vehicle_pixel_editor_active():
            return
        buttons = getattr(event, "buttons", (0, 0, 0)) or (0, 0, 0)
        rel = getattr(event, "rel", (0, 0)) or (0, 0)
        self.cursor_screen = screen_pos
        if self.drag is not None and self.drag.get("kind") == "pan":
            self.pan_by_screen(screen_pos[0] - self.drag["last"][0], screen_pos[1] - self.drag["last"][1])
            self.drag["last"] = screen_pos
            if math.dist(screen_pos, self.drag["start"]) > 4:
                self.drag["moved"] = True
            return
        if len(buttons) > 1 and buttons[1]:
            self.pan_by_screen(rel[0], rel[1])
            return
        if not self.canvas_rect.collidepoint(screen_pos):
            self.hover = None
            return
        if self.stage == self.STAGE_DESIGN:
            self.cursor_raw = self.screen_to_world(screen_pos)
            self.hover = self._pick_design(screen_pos)
            return
        anchor = self.draft_points[-1] if self.draft_points else self.rect_anchor
        self.cursor_raw = self.screen_to_world(screen_pos, "plan")
        self.cursor_plan, self.cursor_snap = self.snap(screen_pos, anchor=anchor)
        if self.drag is not None:
            if self.drag["kind"] == "vertex":
                self._update_vertex_drag(screen_pos)
            elif self.drag["kind"] in {"fixture", "opening"}:
                self._update_item_drag(screen_pos)
            return
        if self.tool == "select":
            self.hover = self._pick_plan(screen_pos)
        else:
            self.hover = None

    def _hit(self, screen_pos):
        for key, rect in reversed(list(self.hitboxes.items())):
            if rect.collidepoint(screen_pos):
                return key
        return None

    def handle_pointer_event(self, event, camera=None, screen_pos=None):
        screen_pos = screen_pos or getattr(event, "pos", None)
        if screen_pos is None or self.is_vehicle_pixel_editor_active():
            return False
        button = getattr(event, "button", None)
        if event.type == pygame.MOUSEBUTTONUP:
            return self._handle_button_up(button, screen_pos)
        if event.type != pygame.MOUSEBUTTONDOWN:
            return False
        key = self._hit(screen_pos)
        if key is not None and key != "canvas":
            if button == 1:
                return self.activate_hitbox(key)
            return True
        if self.picker is not None or self.text_edit is not None:
            self.picker = None
            if self.text_edit is not None:
                self.commit_rename()
            return True
        if not self.canvas_rect.collidepoint(screen_pos):
            return False
        if button == 3:
            self.drag = {"kind": "pan", "start": screen_pos, "last": screen_pos, "moved": False, "button": 3}
            return True
        if button != 1:
            return False
        double = self._is_double_click(screen_pos)
        if self.stage == self.STAGE_DESIGN:
            pick = self._pick_design(screen_pos)
            self.selection = pick
            if pick is None:
                self.drag = {"kind": "pan", "start": screen_pos, "last": screen_pos, "moved": False, "button": 1}
            return True
        if self.tool == "room":
            return self._handle_room_click(screen_pos, double=double)
        if self.tool in {"rect", "stair"}:
            return self._handle_rect_click(screen_pos)
        if self.tool == "opening":
            return self.place_opening()
        if self.tool == "fixture":
            return self.place_fixture()
        # Select tool
        if double:
            if self.insert_vertex_on_edge(screen_pos):
                return True
        pick = self._pick_plan(screen_pos)
        if pick is None:
            self.selection = None
            self.drag = {"kind": "pan", "start": screen_pos, "last": screen_pos, "moved": False, "button": 1}
            return True
        if pick["kind"] == "vertex":
            self.selection = pick
            if not self.read_only:
                self._begin_vertex_drag(pick)
            return True
        if pick["kind"] in {"fixture", "opening"}:
            self.selection = {"kind": pick["kind"], "key": pick["key"]}
            if not self.read_only:
                self._begin_item_drag(pick, screen_pos)
            return True
        self.selection = pick
        return True

    def _handle_button_up(self, button, screen_pos):
        drag = self.drag
        if drag is None:
            return False
        if drag["kind"] == "pan":
            self.drag = None
            if button == 3 and not drag.get("moved"):
                # A right click without dragging steps back while drafting.
                if self.draft_points:
                    self.draft_points.pop()
                elif self.rect_anchor is not None:
                    self.rect_anchor = None
                elif self.selection is not None:
                    self.selection = None
            return True
        if button != 1:
            return False
        if drag["kind"] == "vertex":
            self._finish_vertex_drag()
            return True
        if drag["kind"] in {"fixture", "opening"}:
            self._finish_item_drag()
            return True
        self.drag = None
        return False

    def activate_hitbox(self, key):
        """Dispatch a toolbar/panel hitbox key."""

        if key.startswith("picker:item:"):
            return self.choose_picker_option(key[len("picker:item:"):])
        if key == "picker:close":
            self.picker = None
            return True
        if key == "picker:all":
            if self.picker is not None:
                self.picker["show_all"] = not self.picker.get("show_all", False)
                self.picker["scroll"] = 0
            return True
        if key == "picker:up":
            if self.picker is not None:
                self.picker["scroll"] = max(0, self.picker.get("scroll", 0) - 8)
            return True
        if key == "picker:down":
            if self.picker is not None:
                self.picker["scroll"] = self.picker.get("scroll", 0) + 8
            return True
        if key == "picker:panel":
            return True
        if self.picker is not None:
            self.picker = None
        if self.text_edit is not None and key != "sel:rename_box":
            self.commit_rename()

        simple = {
            "save": self.save,
            "undo": self.undo,
            "redo": self.redo,
            "fit": self.fit_view,
            "new_version": self.create_new_version,
            "place_on_map": self.open_parent_picker,
            "snap:toggle": self.toggle_snap,
            "snap:down": lambda: self.adjust_snap(-1),
            "snap:up": lambda: self.adjust_snap(1),
            "level:add": self.add_level,
            "level:remove": self.remove_active_level,
            "level:height_down": lambda: self.adjust_level_height(-0.25),
            "level:height_up": lambda: self.adjust_level_height(0.25),
            "level:copy_below": self.copy_outline_from_below,
            "wall:exterior_down": lambda: self.adjust_wall_thickness("exterior", -0.05),
            "wall:exterior_up": lambda: self.adjust_wall_thickness("exterior", 0.05),
            "wall:interior_down": lambda: self.adjust_wall_thickness("interior", -0.02),
            "wall:interior_up": lambda: self.adjust_wall_thickness("interior", 0.02),
            "roof:shape": self.cycle_roof_shape,
            "roof:pitch_down": lambda: self.adjust_roof_pitch(-5.0),
            "roof:pitch_up": lambda: self.adjust_roof_pitch(5.0),
            "roof:axis": self.toggle_roof_axis,
            "roof:overhang_down": lambda: self.adjust_roof_overhang(-0.1),
            "roof:overhang_up": lambda: self.adjust_roof_overhang(0.1),
            "top:roof_toggle": self.toggle_top_roof,
            "sel:rename": self.begin_rename,
            "sel:rename_box": lambda: True,
            "sel:delete": self.delete_selection,
            "sel:width_down": lambda: self.adjust_opening_width(-0.1),
            "sel:width_up": lambda: self.adjust_opening_width(0.1),
            "sel:sill_down": lambda: self.adjust_opening_sill(-0.1),
            "sel:sill_up": lambda: self.adjust_opening_sill(0.1),
            "sel:head_down": lambda: self.adjust_opening_head(-0.1),
            "sel:head_up": lambda: self.adjust_opening_head(0.1),
            "sel:rotate": lambda: self.rotate_fixture(90.0),
            "fixture:choose": self.open_fixture_picker,
            "surface:clear": self.clear_surface_material,
            "details:paint": self.open_detail_painter,
            "details:clear": self.clear_view_details,
        }
        if key in simple:
            return bool(simple[key]())
        if key.startswith("stage:"):
            return self.set_stage(key[len("stage:"):])
        if key.startswith("tool:"):
            return self.set_tool(key[len("tool:"):])
        if key.startswith("opening_class:"):
            return self.set_opening_class(key[len("opening_class:"):])
        if key.startswith("level:select:"):
            return self.set_active_level(key[len("level:select:"):])
        if key.startswith("view:"):
            return self.set_design_view(key[len("view:"):])
        if key.startswith("role:"):
            if not self._editable():
                return False
            return self.open_material_picker(role=key[len("role:"):])
        if key == "surface:set":
            selection = self.selection or {}
            if selection.get("kind") != "surface" or not self._editable():
                return False
            return self.open_material_picker(surface_key=selection["key"])
        if key == "surface:room_walls":
            selection = self.selection or {}
            if not selection.get("room") or not self._editable():
                return False
            return self.open_material_picker(room_walls=selection["room"])
        if key.startswith("room:list:"):
            room_key = key[len("room:list:"):]
            room = self._room(room_key)
            if room is None:
                return False
            if room["level"] != self.active_level:
                self.set_active_level(room["level"])
            self.stage = self.STAGE_GRUNDRISS
            self.selection = {"kind": "room", "key": room_key}
            return True
        return False
