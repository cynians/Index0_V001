"""Placing blueprints on a site map, and drawing placed blueprints there.

A placement creates an ordinary ``location_class: building`` location that
references the exact blueprint version (``building_blueprint``) plus its
``blueprint_position`` / ``blueprint_rotation_deg`` in the parent's site-metre
coordinates.  Its ``bounds`` polygon is the derived outer footprint so every
existing map consumer sees the building without knowing about blueprints.
Placing a draft blueprint releases it: from then on, edits fork a new version
and buildings that already exist keep the version they were built from.
"""

from __future__ import annotations

import copy

import pygame

from . import blueprint_model as bm
from .blueprint_store import BLUEPRINT_DATASET, entity_display_name, safe_identifier, shared_store


ROTATION_STEP_DEG = 90.0


def _blueprint_entity(world_model, blueprint_id):
    entity = world_model.get_entity(blueprint_id) if world_model is not None else None
    if not isinstance(entity, dict):
        return None
    if entity.get("_dataset") != BLUEPRINT_DATASET and entity.get("type") != "building_blueprint":
        return None
    return entity


def placed_blueprint_geometry(world_model, building, store=None):
    """Derived geometry for a placed building, or ``None``.

    Returns ``{"blueprint", "derived", "position", "rotation_deg"}``.
    """

    if not isinstance(building, dict) or not building.get("building_blueprint"):
        return None
    entity = _blueprint_entity(world_model, building.get("building_blueprint"))
    if entity is None:
        return None
    blueprint = (store or shared_store()).load_for_entity(entity)
    if blueprint is None:
        return None
    position = building.get("blueprint_position") or [0.0, 0.0]
    try:
        position = (float(position[0]), float(position[1]))
        rotation = float(building.get("blueprint_rotation_deg") or 0.0)
    except (TypeError, ValueError, IndexError):
        return None
    return {
        "blueprint": blueprint,
        "derived": bm.derive_geometry(blueprint),
        "position": position,
        "rotation_deg": rotation,
    }


class BlueprintPlacement:
    """Ghost-and-click placement state held by a MapSimulation."""

    def __init__(self, map_sim, blueprint_id, store=None):
        self.map_sim = map_sim
        self.world_model = map_sim.world_model
        self.blueprint_id = blueprint_id
        self.store = store or shared_store()
        self.entity = _blueprint_entity(self.world_model, blueprint_id)
        self.blueprint = self.store.load_for_entity(self.entity) if self.entity else None
        self.derived = bm.derive_geometry(self.blueprint) if self.blueprint else None
        self.anchor = bm.plan_anchor(self.derived) if self.derived else (0.0, 0.0)
        self.rotation_deg = 0.0
        self.cursor = None
        self.status = ""

    @property
    def valid(self):
        return bool(self.blueprint and self.derived and self.derived["walls"])

    def name(self):
        return entity_display_name(self.entity, self.blueprint_id)

    def position_for_cursor(self, cursor=None):
        """Plan-origin position that keeps the footprint centre under the cursor."""

        cursor = cursor or self.cursor
        if cursor is None:
            return None
        ax, ay = bm.rotate_point(self.anchor, self.rotation_deg)
        return float(cursor[0]) - ax, float(cursor[1]) - ay

    def set_cursor(self, map_point):
        self.cursor = (float(map_point[0]), float(map_point[1]))

    def rotate(self, degrees=ROTATION_STEP_DEG):
        self.rotation_deg = (self.rotation_deg + degrees) % 360.0
        return True

    def ghost(self):
        position = self.position_for_cursor()
        if position is None or not self.valid:
            return None
        return {
            "footprint": bm.placed_footprint(self.derived, position, self.rotation_deg),
            "walls": bm.placed_wall_segments(self.derived, position, self.rotation_deg),
            "position": position,
        }

    def ground_problem(self, position=None):
        """Why the footprint cannot stand here, or ``None``.

        Only maps that know their ground (a city on generated terrain)
        answer; an authored site has no terrain to object with.
        """

        substrate = getattr(self.map_sim, "get_ground_substrate", lambda: None)()
        position = position or self.position_for_cursor()
        if substrate is None or position is None or not self.valid:
            return None
        points = [tuple(point) for loop in bm.placed_footprint(self.derived, position, self.rotation_deg) for point in loop]
        if not points:
            return None
        centre = (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))
        # Corners, edge midpoints and the centre: a channel narrower than
        # the building still crosses one of them.
        probes = points + [centre] + [
            ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2) for a, b in zip(points, points[1:] + points[:1])
        ]
        if any(substrate.open_water_at(x, y) for x, y in probes):
            return "open water"
        return None

    def status_label(self):
        label = f"Place {self.name()} · rotation {self.rotation_deg:.0f}°"
        problem = self.ground_problem()
        if problem:
            label = f"{label} · cannot build on {problem}"
        return f"{label} | Click place · R / right-click rotate · Shift+R 15° · Esc cancel"

    def _existing_ids(self):
        loader = getattr(self.world_model, "loader", None)
        return set(getattr(loader, "entities", {}) or {})

    def _allocate_building_id(self):
        existing = self._existing_ids()
        base = safe_identifier(self.blueprint_id).removeprefix("bp_")
        index = 1
        while f"loc_bldg_{base}_{index:03d}" in existing:
            index += 1
        return f"loc_bldg_{base}_{index:03d}", index

    def place(self):
        """Create the building location.  Returns the new id or ``None``."""

        position = self.position_for_cursor()
        if position is None or not self.valid:
            self.status = "Move over the map to place the blueprint"
            return None
        problem = self.ground_problem(position)
        if problem:
            self.status = f"Cannot build on {problem}"
            return None
        loader = getattr(self.world_model, "loader", None)
        if loader is None or not hasattr(loader, "persist_entity"):
            return None
        parent_id = self.map_sim.context.root_entity_id
        building_id, index = self._allocate_building_id()
        footprint = bm.placed_footprint(self.derived, position, self.rotation_deg)
        if not footprint:
            return None
        name = f"{self.name()} {index}"
        building = {
            "id": building_id,
            "_dataset": "locations",
            "type": "location",
            "name": name,
            "pretty_name": name,
            "location_class": "building",
            "building_class": str(self.entity.get("building_class") or self.name()),
            "building_blueprint": self.blueprint_id,
            "blueprint_position": [round(position[0], 4), round(position[1], 4)],
            "blueprint_rotation_deg": round(self.rotation_deg, 3),
            "parent_location": parent_id,
            "parents": [parent_id],
            "bounds": {
                "type": "polygon",
                "coordinate_space": "map_world",
                "points": [[round(x, 4), round(y, 4)] for x, y in footprint[0]],
            },
            "entry_status": "draft",
            "wiki_entry": f"Built from blueprint {self.name()}.",
        }
        if self.entity.get("map_color"):
            building["map_color"] = self.entity["map_color"]
        year = getattr(self.map_sim, "year", None)
        if year is not None:
            building["start_year"] = year
        if not loader.persist_entity(building):
            return None
        changed = set()
        if hasattr(loader, "set_relation"):
            changed.update(loader.set_relation(parent_id, "constituents", building_id, persist=False))
        parent = getattr(loader, "entities", {}).get(parent_id)
        if isinstance(parent, dict) and isinstance(parent.get("layout_structures"), list) and hasattr(loader, "set_literal"):
            structures = list(parent["layout_structures"])
            if building_id not in structures:
                structures.append(building_id)
                changed.update(loader.set_literal(parent_id, "layout_structures", structures, persist=False))
        if changed and hasattr(loader, "save_changed_dataset_files"):
            loader.save_changed_dataset_files(changed)
        self._release_blueprint(loader)
        self.status = f"Placed {name}"
        return building_id

    def _release_blueprint(self, loader):
        source = getattr(loader, "entities", {}).get(self.blueprint_id)
        if not isinstance(source, dict) or source.get("blueprint_status") == "released":
            return
        materialize = getattr(source, "materialize", None)
        entity = copy.deepcopy(dict(materialize() if callable(materialize) else source))
        entity["blueprint_status"] = "released"
        loader.persist_entity(entity)
        self.entity = entity

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, screen, camera):
        ghost = self.ghost()
        if ghost is None:
            return
        blocked = self.ground_problem(ghost["position"]) is not None
        fill = (236, 110, 96) if blocked else (120, 200, 236)
        wall = (250, 204, 196) if blocked else (200, 236, 250)
        for loop in ghost["footprint"]:
            points = [camera.world_to_screen(tuple(p)) for p in loop]
            if len(points) >= 3 and all(p is not None for p in points):
                overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
                pygame.draw.polygon(overlay, (*fill, 60), points)
                screen.blit(overlay, (0, 0))
                pygame.draw.polygon(screen, fill, points, 2)
        for start, end in ghost["walls"]:
            a = camera.world_to_screen(start)
            b = camera.world_to_screen(end)
            if a is not None and b is not None:
                pygame.draw.line(screen, wall, a, b, 2)


def draw_placed_blueprints(screen, map_sim, camera, store=None):
    """Draw walls and openings of blueprint buildings on a site map."""

    root = map_sim.get_root_entity() if hasattr(map_sim, "get_root_entity") else None
    if not isinstance(root, dict) or root.get("map_coordinate_space") != "site_meters":
        return
    zoom = float(getattr(camera, "zoom", 1.0) or 1.0)
    if zoom < 2.0:
        return
    world_model = map_sim.world_model
    loader = getattr(world_model, "loader", None)
    root_id = map_sim.context.root_entity_id
    cache = getattr(map_sim, "_placed_blueprint_cache", None)
    revision = getattr(world_model, "repository_revision", 0)
    if cache is None or cache.get("revision") != revision:
        buildings = []
        for entity in (getattr(loader, "entities", {}) or {}).values():
            if not isinstance(entity, dict) or not entity.get("building_blueprint"):
                continue
            if entity.get("parent_location") != root_id:
                continue
            geometry = placed_blueprint_geometry(world_model, entity, store)
            if geometry is None:
                continue
            derived = geometry["derived"]
            buildings.append({
                "rooms": bm.placed_rooms(geometry["blueprint"], geometry["position"], geometry["rotation_deg"]),
                "walls": bm.placed_wall_segments(derived, geometry["position"], geometry["rotation_deg"]),
                "openings": bm.placed_openings(derived, geometry["position"], geometry["rotation_deg"]),
            })
        cache = {"revision": revision, "buildings": buildings}
        map_sim._placed_blueprint_cache = cache
    for building in cache["buildings"]:
        for start, end in building["walls"]:
            a = camera.world_to_screen(start)
            b = camera.world_to_screen(end)
            if a is not None and b is not None:
                pygame.draw.line(screen, (18, 20, 24), a, b, max(2, int(zoom * 0.3)))
                pygame.draw.line(screen, (196, 202, 208), a, b, 1)
        for opening in building["openings"]:
            if opening["passable"]:
                continue
            a = camera.world_to_screen(opening["start"])
            b = camera.world_to_screen(opening["end"])
            if a is not None and b is not None:
                pygame.draw.line(screen, (130, 180, 210), a, b, 1)
