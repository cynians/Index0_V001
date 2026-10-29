"""Minimal preview renderer for the standalone Species Sim."""

import colorsys
import functools
import json
import math
import random
from pathlib import Path

import pygame
from ui.fonts import get_font

from world.texture_sets import TextureSet
from simulations.species.graminoid_visuals import (
    VISUAL_VERSION as GRAMINOID_VISUAL_VERSION,
    compound_panicle_surface,
    draw_blade,
)
from engine import asset_files
from simulations.species.species_simulation import (
    SCREEN_DEPTH_PROJECTION,
    normalise_climbing_supports,
    normalise_neighbour_root_zones,
)
from simulations.species.solid_structures import SolidStructureField, normalise_solid_structures
from simulations.species.surface_supports import rock_point, rock_normal, cross
from simulations.species.surface_growth import surface_palette, surface_disc_colors

# asset_ref/texture_set_ref values are authored relative to the repo root.
# Resolving them against Path.cwd() breaks silently (empty surface, falls
# back to the plain-line leaf/branch rendering) whenever the app happens to
# be launched from a different working directory; anchor to this file's
# location instead, matching the convention already used by
# world/entity_loader.py and app/app.py.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROCK_VISUAL_VERSION = 2
TREE_PHYSICAL_WIDTH_VISUAL_VERSION = 1
FERN_PINNULE_VISUAL_VERSION = 4
ROCK_PIXEL_PALETTE = ((69,65,60),(88,82,73),(109,101,88),(136,125,106),(159,147,124))
THALLUS_PIXEL_PALETTE = ((105,119,84),(124,139,101),(144,159,117),(165,178,136))


class PixelSceneCamera:
    """Project a support and its covering onto one nearest-neighbour grid."""

    def __init__(self, camera, pixel_scale):
        self.camera = camera
        self.pixel_scale = pixel_scale
        self.scale = SpeciesRenderer._projection_pixels_per_meter(camera)/pixel_scale
        self.view_direction = getattr(camera,"view_direction",(0,-1,0))

    def world_to_screen_3d(self, position):
        if hasattr(self.camera,"world_to_screen_3d"):
            point = self.camera.world_to_screen_3d(position)
        else:
            point = self.camera.world_to_screen((position[0]+position[1]*SCREEN_DEPTH_PROJECTION,position[2]))
        return tuple(math.floor(value/self.pixel_scale) for value in point) if point is not None else None

    def world_to_screen(self, position):
        point = self.camera.world_to_screen(position)
        return tuple(math.floor(value/self.pixel_scale) for value in point) if point is not None else None


class DiagnosticCamera:
    """Small camera used by the in-simulation diagnostic views."""

    def __init__(self, width, height, bounds, minimum_span_m=0.1):
        self.view_direction = (SCREEN_DEPTH_PROJECTION, -1, 0)
        min_x, max_x, min_z, max_z = bounds
        self.center_x = (min_x + max_x) * 0.5
        self.screen_center_x = width * 0.5
        self.min_z = min_z
        self.scale = min(
            (width - 24) / max(minimum_span_m, max_x - min_x),
            (height - 52) / max(minimum_span_m, max_z - min_z),
        )
        self.bottom = height - 24

    def world_to_screen(self, position):
        x, z = float(position[0]), float(position[1])
        return (
            round(self.screen_center_x + (x - self.center_x) * self.scale),
            round(self.bottom - (z - self.min_z) * self.scale),
        )

    def world_to_screen_3d(self, position):
        """Project a model-space (x, y, z) point into the 2D diagnostic view."""

        x, y, z = (float(position[0]), float(position[1]), float(position[2]))
        return self.world_to_screen((x + y * SCREEN_DEPTH_PROJECTION, z))


class TopDownDiagnosticCamera:
    """Orthographic crown camera looking down the plant's positive z axis."""

    def __init__(self, width, height, bounds):
        self.view_direction = (0, 0, 1)
        min_x, max_x, min_y, max_y = bounds
        self.center_x = (min_x + max_x) * 0.5
        self.center_y = (min_y + max_y) * 0.5
        self.screen_center_x = width * 0.5
        self.screen_center_y = height * 0.5
        self.scale = min(
            (width - 48) / max(0.1, max_x - min_x),
            (height - 48) / max(0.1, max_y - min_y),
        )

    def world_to_screen(self, position):
        x, y = float(position[0]), float(position[1])
        return (
            round(self.screen_center_x + (x - self.center_x) * self.scale),
            round(self.screen_center_y - (y - self.center_y) * self.scale),
        )

    def world_to_screen_3d(self, position):
        return self.world_to_screen(position[:2])


class SurfaceElevationCamera:
    """Orthographic elevation of an x/y-oriented 2D surface and model z."""

    def __init__(self, width, height, bounds, surface_rotation_deg=0.0):
        min_x, max_x, min_y, max_y, min_z, max_z = (float(value) for value in bounds)
        angle = math.radians(float(surface_rotation_deg))
        self.view_direction = (math.sin(angle), -math.cos(angle), 0)
        self.tangent_x = math.cos(angle)
        self.tangent_y = math.sin(angle)
        projected_x = [
            x * self.tangent_x + y * self.tangent_y
            for x in (min_x, max_x)
            for y in (min_y, max_y)
        ]
        self.min_u = min(projected_x)
        self.max_u = max(projected_x)
        self.min_z = min_z
        self.max_z = max_z
        self.scale = min(
            (width - 48) / max(0.1, self.max_u - self.min_u),
            (height - 48) / max(0.1, self.max_z - self.min_z),
        )
        self.offset_x = width * 0.5 - (self.min_u + self.max_u) * 0.5 * self.scale
        self.bottom = height - 24 + self.min_z * self.scale
        self.surface_rotation_deg = float(surface_rotation_deg)

    def world_to_screen_3d(self, position):
        x, y, z = (float(position[0]), float(position[1]), float(position[2]))
        u = x * self.tangent_x + y * self.tangent_y
        return (
            round(self.offset_x + u * self.scale),
            round(self.bottom - z * self.scale),
        )

    def world_to_screen(self, position):
        return self.world_to_screen_3d((float(position[0]), 0.0, float(position[1])))


class IsometricDiagnosticCamera:
    """Two-to-one isometric projection over a true 3D model-space bound."""

    def __init__(self, width, height, bounds):
        self.view_direction = (1, 1, 1)
        min_x, max_x, min_y, max_y, min_z, max_z = (float(value) for value in bounds)
        projected = [
            (x - y, (x + y) * 0.5 - z)
            for x in (min_x, max_x)
            for y in (min_y, max_y)
            for z in (min_z, max_z)
        ]
        min_sx, max_sx = min(p[0] for p in projected), max(p[0] for p in projected)
        min_sy, max_sy = min(p[1] for p in projected), max(p[1] for p in projected)
        self.scale = min(
            (width - 48) / max(0.1, max_sx - min_sx),
            (height - 48) / max(0.1, max_sy - min_sy),
        )
        self.offset_x = width * 0.5 - (min_sx + max_sx) * 0.5 * self.scale
        self.offset_y = height * 0.5 - (min_sy + max_sy) * 0.5 * self.scale

    def world_to_screen_3d(self, position):
        x, y, z = (float(position[0]), float(position[1]), float(position[2]))
        return (
            round(self.offset_x + (x - y) * self.scale),
            round(self.offset_y + ((x + y) * 0.5 - z) * self.scale),
        )

    def world_to_screen(self, position):
        return self.world_to_screen_3d((float(position[0]), 0.0, float(position[1])))


class OffsetDiagnosticCamera:
    def __init__(self, camera, offset_x, local_scale=1.0):
        self.camera = camera
        self.offset_x = float(offset_x)
        self.local_scale = float(local_scale)
        self.view_direction = getattr(camera, "view_direction", (0,-1,0))

    def world_to_screen(self, position):
        return self.camera.world_to_screen(
            (self.offset_x + float(position[0]) * self.local_scale, float(position[1]) * self.local_scale)
        )

    def world_to_screen_3d(self, position):
        x, y, z = (float(position[0]), float(position[1]), float(position[2]))
        return self.camera.world_to_screen_3d(
            (self.offset_x + x * self.local_scale, y * self.local_scale, z * self.local_scale)
        )


def diagnostic_cell_bounds(snapshot):
    min_x, max_x, min_y, max_y, min_z, max_z = snapshot.bounds_m
    projected_x = (
        min_x + min_y * SCREEN_DEPTH_PROJECTION,
        min_x + max_y * SCREEN_DEPTH_PROJECTION,
        max_x + min_y * SCREEN_DEPTH_PROJECTION,
        max_x + max_y * SCREEN_DEPTH_PROJECTION,
    )
    return min(projected_x), max(projected_x), min_z, max_z


def top_down_diagnostic_bounds(sim, snapshot=None):
    """Return an x/y footprint that fits the above-ground plant and foliage."""

    snapshot = snapshot or sim.render_snapshot
    if (sim.blueprint.growth.get("fungal_growth_profile", {}).get("resolved", {}).get("body_variant_keys")):
        # The colony's point sockets are not its shelf silhouettes. Include
        # wood and a conservative envelope for the camera-facing cap views.
        points = [(x,y) for x in snapshot.bounds_m[:2] for y in snapshot.bounds_m[2:4]]
        for body in snapshot.stats.get("fungal_bodies",[]):
            x,y,_ = body["cap_socket_m"]
            radius = body["cap_width_m"]*1.2
            points.extend((x+dx*radius,y+dy*radius) for dx in (-1,1) for dy in (-1,1))
        return (min(p[0] for p in points)-.02,max(p[0] for p in points)+.02,
                min(p[1] for p in points)-.02,max(p[1] for p in points)+.02)
    root_kinds = {"root", "root_section", "root_support", "renewal_organ", "renewal_bud"}
    canopy_indices=canopy_visible_indices(sim,snapshot)
    leaf_module = sim.blueprint.module("leaf") if hasattr(sim.blueprint, "module") else None
    leaf_length = max(0.04, float(getattr(leaf_module, "length_m", 0.1) or 0.1))
    leaf_radius = max(0.006, float(getattr(leaf_module, "radius_m", 0.012) or 0.012))
    points = [
        (float(placement[2]), float(placement[3]))
        for index,placement in enumerate(snapshot.placements)
        if index in canopy_indices
    ]
    orientations = getattr(snapshot, "placement_orientations", {}) or {}
    for index, placement in enumerate(snapshot.placements):
        head_profile = sim.blueprint.growth.get("inflorescence_profile")
        if (head_profile and (head_profile.get("head_layout") == "rounded" or sim.blueprint.growth.get("basal_subshrub_version"))
                and (placement[0] == "flower" or (placement[0] == "fruit"
                     and (sim.blueprint.growth.get("clonal_forb_reproduction_version") or sim.blueprint.growth.get("basal_subshrub_version"))))):
            radius = math.hypot(head_profile["length_m"], head_profile["width_m"]*.5)*placement[6]
            points.extend((placement[2]+dx*radius, placement[3]+dy*radius)
                          for dx in (-1,1) for dy in (-1,1))
        if placement[0] != "leaf":
            if sim.blueprint.growth.get('columnar_version') and placement[0] in {'stem_section','branch_section'}:
                r=float(placement[6])
                points.extend((p[0]+dx*r,p[1]+dy*r)
                              for p in snapshot.placement_paths.get(str(index), [placement[2:5]])
                              for dx in (-1,1) for dy in (-1,1))
            continue
        orientation = orientations.get(str(index)) or {}
        if orientation.get("planar_leaf"):
            if 'width_m' in orientation:
                from simulations.species.floating_leaves import metric_blade_bounds
                points.extend(point[:2] for point in metric_blade_bounds(
                    placement[2:5],orientation,leaf_length*float(placement[6])))
                continue
            from simulations.species.emergent_rosettes import planar_blade_bounds
            points.extend(point[:2] for point in planar_blade_bounds(placement[2:5], orientation,
                leaf_length*float(placement[6]),
                sim.blueprint.growth["emergent_rosette_profile"]["blade_width_ratio"]))
            continue
        forward = orientation.get("forward") or []
        if len(forward) < 2:
            continue
        extent = leaf_length * max(0.55, float(placement[6])) * 1.35
        points.append((
            float(placement[2]) + float(forward[0]) * extent,
            float(placement[3]) + float(forward[1]) * extent,
        ))
    for index, path in (getattr(snapshot, "placement_paths", {}) or {}).items():
        try:
            placement = snapshot.placements[int(index)]
        except (IndexError, TypeError, ValueError):
            continue
        if int(index) not in canopy_indices:
            continue
        points.extend((float(point[0]), float(point[1])) for point in path if len(point) >= 2)
    for cluster in getattr(snapshot, "leaf_clusters", []) or []:
        position = cluster.get("position_m") or []
        if len(position) >= 2:
            x, y = float(position[0]), float(position[1])
            host_index = int(cluster.get("host_placement_index", -1) or -1)
            host_is_leaf = (
                0 <= host_index < len(snapshot.placements)
                and snapshot.placements[host_index][0] == "leaf"
            )
            if host_is_leaf or int(cluster.get("estimated_leaf_count", 1) or 1) <= 1:
                points.append((x, y))
            else:
                spread = leaf_length * 1.45
                spread = max(spread, float(cluster.get("foliage_spray_radius_m", 0.0) or 0.0) * 1.5)
                if cluster.get("shoot_type"):
                    spread += max(0.0, float(cluster.get("length", 0.0) or 0.0)) * 0.5
                points.extend(((x - spread, y - spread), (x + spread, y + spread)))

    zones = snapshot.stats.get("neighbour_root_zones")
    if zones is None:
        zones = normalise_neighbour_root_zones(snapshot.stats.get("environment"))
    for zone in zones or []:
        center = zone.get("center_m") or []
        if len(center) < 2:
            continue
        radius = max(0.0, float(zone.get("radius_m", 0.0) or 0.0))
        points.extend((
            (float(center[0]) - radius, float(center[1]) - radius),
            (float(center[0]) + radius, float(center[1]) + radius),
        ))

    supports = snapshot.stats.get("climbing_supports")
    if supports is None:
        supports = normalise_climbing_supports(snapshot.stats.get("environment"))
    for support in supports or []:
        center = support.get("center_m") or []
        if len(center) < 2:
            continue
        radius = max(
            float(support.get("radius_m", 0.0) or 0.0),
            float(support.get("crown_radius_m", 0.0) or 0.0),
        )
        points.extend((
            (float(center[0]) - radius, float(center[1]) - radius),
            (float(center[0]) + radius, float(center[1]) + radius),
        ))

    structures = snapshot.stats.get("solid_structures")
    if structures is None:
        structures = normalise_solid_structures(snapshot.stats.get("environment"))
    for structure in structures or []:
        min_x, max_x, min_y, max_y, _min_z, _max_z = SolidStructureField.bounds_m(structure)
        points.extend(((min_x, min_y), (max_x, max_y)))

    organ_margin = max(0.04, leaf_radius * 2.0)
    if not points:
        return (-organ_margin, organ_margin, -organ_margin, organ_margin)
    min_x = min(point[0] for point in points) - organ_margin
    max_x = max(point[0] for point in points) + organ_margin
    min_y = min(point[1] for point in points) - organ_margin
    max_y = max(point[1] for point in points) + organ_margin
    return min_x, max_x, min_y, max_y


def root_diagnostic_bounds(snapshot):
    roots = [p for p in snapshot.placements
             if p[0] in {"root", "root_section", "root_support", "renewal_organ", "renewal_bud"}]
    if not roots:
        return (-0.5, 0.5, -1.0, 0.1)
    xs = [p[2] + p[3] * SCREEN_DEPTH_PROJECTION for p in roots]
    zs = [p[4] for p in roots]
    return min(xs) - 0.05, max(xs) + 0.05, min(zs) - 0.04, max(zs) + 0.06


def frond_primary_pinna_rows(primary_pinna_count, arrangement):
    """Return bounded display rows while preserving alternate/opposite rhythm."""

    count = max(0, int(primary_pinna_count or 0))
    arrangement = str(arrangement or "").lower()
    if arrangement in {"alternate", "distichous"}:
        sampled_count = min(24, count)
        return [
            ((index + 0.35) / (sampled_count + 0.2), (1.0,) if index % 2 == 0 else (-1.0,))
            for index in range(sampled_count)
        ]

    sampled_rows = min(12, math.ceil(count / 2.0))
    rows = []
    for index in range(sampled_rows):
        sides = (-1.0, 1.0)
        if count % 2 and index == sampled_rows - 1 and sampled_rows == math.ceil(count / 2.0):
            sides = (1.0,)
        rows.append(((index + 0.35) / (sampled_rows + 0.2), sides))
    return rows


def frond_pinna_world_geometry(path, progress, side, extent_m, sweep):
    """Place a primary pinna in a shallowly tilted physical blade plane.

    Screen-space normals collapse the blade in top view and rotate it toward
    the ground in elevation views. The rachis path supplies the physical
    position; its horizontal travel supplies the lateral direction.
    """
    position = max(0.0, min(1.0, progress)) * (len(path) - 1)
    segment = min(len(path) - 2, int(position))
    fraction = position - segment
    a, b = path[segment], path[segment + 1]
    base = tuple(a[axis] + (b[axis] - a[axis]) * fraction for axis in range(3))
    dx = path[-1][0] - path[0][0]
    dy = path[-1][1] - path[0][1]
    norm = max(1e-9, math.hypot(dx, dy))
    along_x, along_y = dx / norm, dy / norm
    tilt = 0.24
    lateral = extent_m * math.sqrt(1.0 - tilt * tilt)
    tip = (base[0] - along_y * side * lateral + along_x * extent_m * sweep,
           base[1] + along_x * side * lateral + along_y * extent_m * sweep,
           base[2] + side * extent_m * tilt)
    return base, tip


def branch_diagnostic_selection(sim, snapshot=None):
    snapshot = snapshot or sim.render_snapshot
    ps = snapshot.placements
    root = next((i for i,p in enumerate(ps) if p[0] == "branch_section" and p[7] == 3), None)
    if root is None:
        return set(), set()
    def descendants(start):
        selected = {start}
        for i,p in enumerate(ps):
            if p[1] in selected:
                selected.add(i)
        return selected
    branch = descendants(root)
    cluster = next((c for c in snapshot.leaf_clusters if c["host_placement_index"] in branch), None)
    shoot = descendants(ps[cluster["host_placement_index"]][1]) if cluster else branch
    return branch, shoot


def branch_diagnostic_bounds(sim, selected, snapshot=None):
    snapshot = snapshot or sim.render_snapshot
    points = [p[2:5] for i,p in enumerate(snapshot.placements) if i in selected]
    if not points:
        return (-1,1,0,1)
    xs = [p[0]+SCREEN_DEPTH_PROJECTION*p[1] for p in points]
    zs = [p[2] for p in points]
    margin = sim.blueprint.module("leaf").length_m * 1.5
    return min(xs)-margin,max(xs)+margin,min(zs)-margin,max(zs)+margin


def _camera_state_key(camera):
    """A small hashable snapshot of a camera's view, for frame-cache keys.

    Two calls with an unmoved camera must produce an equal key so a cached
    render can be reused; any real pan/zoom/resize must change it.
    """
    if isinstance(camera, OffsetDiagnosticCamera):
        return ("offset", round(camera.offset_x, 4), round(camera.local_scale, 4), _camera_state_key(camera.camera))
    if isinstance(camera, SurfaceElevationCamera):
        return (
            "surface_elevation",
            round(camera.surface_rotation_deg, 4), round(camera.min_u, 4),
            round(camera.max_u, 4), round(camera.min_z, 4),
            round(camera.max_z, 4), round(camera.scale, 4),
        )
    if isinstance(camera, TopDownDiagnosticCamera):
        return (
            "top_down",
            round(camera.center_x, 4), round(camera.center_y, 4),
            round(camera.screen_center_x, 4), round(camera.screen_center_y, 4),
            round(camera.scale, 4),
        )
    if isinstance(camera, DiagnosticCamera):
        return (
            "diagnostic",
            round(camera.center_x, 4), round(camera.screen_center_x, 4),
            round(camera.min_z, 4), round(camera.scale, 4), round(camera.bottom, 4),
        )
    # The general app camera (engine.camera.Camera): world position + zoom.
    x = getattr(camera, "x", None)
    y = getattr(camera, "y", None)
    zoom = getattr(camera, "zoom", None)
    if x is not None and y is not None and zoom is not None:
        return ("app", round(float(x), 4), round(float(y), 4), round(float(zoom), 8))
    return ("unknown", id(camera))


def canopy_visible_indices(sim,snapshot):
    """Canopy views omit roots and concealed rhizome axes; cutaways retain them."""
    roots={'root','root_section','root_support','renewal_organ','renewal_bud'}
    rhizomatous='rhizome' in (sim.blueprint.growth.get('belowground_storage') or [])
    return {i for i,p in enumerate(snapshot.placements) if p[0] not in roots
            and not (rhizomatous and p[0] in {'stem_section','branch_section'} and p[4]<0)}


class SpeciesRenderer:
    def __init__(self, app_view):
        self.app_view = app_view
        self._asset_cache = {}
        self._asset_path_cache = {}
        self._asset_revision_cache = {}
        self._texture_cache = {}
        self._texture_revision_cache = {}
        self._texture_path_cache = {}
        self._texture_surface_cache = {}
        self._leaf_sprite_cache = {}
        self._pinnule_source_cache = {}
        self._inflorescence_sprite_cache = {}
        self._asset_color_cache = {}
        self._individual_draw_cache = {}
        self._individual_draw_cache_order = []
        self._font_cache = {}
        self._species_editor_reference_cache = {}

    def _font(self, size):
        size = int(size)
        if size not in self._font_cache:
            self._font_cache[size] = get_font(size)
        return self._font_cache[size]

    @staticmethod
    def _ellipsize(text, font, max_width):
        text = str(text or "")
        if font.size(text)[0] <= max_width:
            return text
        suffix = "…"
        while text and font.size(text + suffix)[0] > max_width:
            text = text[:-1]
        return text + suffix

    def _screen(self, camera, x, y):
        # Plant model space is z-up. The application's general camera uses a
        # screen-down world y, while diagnostic cameras already implement the
        # model-space projection themselves.
        if hasattr(camera, "world_to_screen_3d"):
            return camera.world_to_screen((x, y))
        return camera.world_to_screen((x, -float(y)))

    def _placement_screen(self, camera, placement):
        if hasattr(camera, "world_to_screen_3d"):
            return camera.world_to_screen_3d(placement[2:5])
        return self._screen(camera, placement[2] + placement[3] * SCREEN_DEPTH_PROJECTION, placement[4])

    @staticmethod
    def _draw_neighbour_root_zones(screen, camera, snapshot):
        """Draw contextual root occupancy in the top-down diagnostic only."""

        zones = snapshot.stats.get("neighbour_root_zones")
        if zones is None:
            zones = normalise_neighbour_root_zones(snapshot.stats.get("environment"))
        if not zones:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        for zone in zones:
            center_m = zone.get("center_m") or []
            if len(center_m) < 2:
                continue
            center = camera.world_to_screen(center_m)
            radius_px = max(2, round(float(zone.get("radius_m", 0.0) or 0.0) * camera.scale))
            influence = max(0.0, min(1.0, float(zone.get("influence", 1.0) or 0.0)))
            pygame.draw.circle(overlay, (139, 75, 55, round(28 + 30 * influence)), center, radius_px)
            pygame.draw.circle(overlay, (206, 128, 86, round(125 + 75 * influence)), center, radius_px, 2)

            # A compact radial glyph reads as neighbouring roots while the
            # circle honestly communicates that only their influence zone is
            # known, not their exact topology.
            phase = sum(ord(char) for char in str(zone.get("id") or "root")) % 360
            for spoke in range(8):
                angle = math.radians(phase + spoke * 45.0)
                elbow_radius = radius_px * (0.30 + 0.035 * (spoke % 3))
                tip_radius = radius_px * (0.68 + 0.045 * ((spoke * 5) % 4))
                elbow = (round(center[0] + math.cos(angle) * elbow_radius),
                         round(center[1] - math.sin(angle) * elbow_radius))
                tip_angle = angle + math.radians(-9.0 if spoke % 2 else 11.0)
                tip = (round(center[0] + math.cos(tip_angle) * tip_radius),
                       round(center[1] - math.sin(tip_angle) * tip_radius))
                pygame.draw.lines(overlay, (214, 151, 105, 155), False, (center, elbow, tip), 1)
        screen.blit(overlay, (0, 0))

    def _draw_climbing_supports(self, screen, camera, snapshot):
        """Draw muted scene geometry behind a support-dependent vine."""

        supports = snapshot.stats.get("climbing_supports")
        if supports is None:
            supports = normalise_climbing_supports(snapshot.stats.get("environment"))
        if not supports:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        top_down = isinstance(camera, TopDownDiagnosticCamera)
        scale = max(1.0, float(getattr(camera, "scale", 48.0)))
        for support in supports:
            center = support.get("center_m") or []
            if len(center) < 2:
                continue
            x, y = float(center[0]), float(center[1])
            radius = max(0.01, float(support.get("radius_m", 0.05) or 0.05))
            height = max(0.05, float(support.get("height_m", 1.0) or 1.0))
            crown_radius = max(radius, float(support.get("crown_radius_m", radius) or radius))
            is_rod = str(support.get("kind") or "") == "rod"
            palette = support.get("palette") if isinstance(support.get("palette"), dict) else {}
            rod_fill = tuple(palette.get("fill", (100, 111, 116)))
            rod_highlight = tuple(palette.get("highlight", (190, 205, 208)))
            if top_down:
                point = camera.world_to_screen_3d((x, y, 0.0))
                if not is_rod:
                    pygame.draw.circle(overlay, (45, 80, 48, 46), point, max(2, round(crown_radius * scale)))
                pygame.draw.circle(overlay, (*rod_fill, 230) if is_rod else (101, 78, 55, 210), point, max(2, round(radius * scale)))
                pygame.draw.circle(overlay, (*rod_highlight, 235) if is_rod else (156, 132, 91, 220), point, max(2, round(radius * scale)), 1)
                continue

            axis_points = support.get("axis_points_m") or []
            world_axis = (
                [tuple(float(value) for value in point[:3]) for point in axis_points if len(point) >= 3]
                if len(axis_points) >= 2 else [
                    (x, y, float(support.get("base_z_m", 0.0) or 0.0)),
                    (x, y, float(support.get("top_z_m", height) or height)),
                ]
            )
            projected_axis = [
                camera.world_to_screen_3d(point)
                if hasattr(camera, "world_to_screen_3d")
                else self._screen(camera, point[0] + point[1] * SCREEN_DEPTH_PROJECTION, point[2])
                for point in world_axis
            ]
            width = max(3, min(38, round(radius * scale * 2.0)))
            pygame.draw.lines(overlay, (*rod_fill, 235) if is_rod else (92, 69, 49, 220), False, projected_axis, width)
            pygame.draw.lines(overlay, (*rod_highlight, 220) if is_rod else (151, 122, 79, 185), False, projected_axis, max(1, width // 4))
            if str(support.get("kind") or "") == "tree" and crown_radius > radius:
                crown_axis_point = world_axis[max(0, round((len(world_axis) - 1) * 0.82))]
                crown_center = camera.world_to_screen_3d(crown_axis_point) if hasattr(camera, "world_to_screen_3d") else self._screen(camera, crown_axis_point[0] + crown_axis_point[1] * SCREEN_DEPTH_PROJECTION, crown_axis_point[2])
                crown_width = max(8, round(crown_radius * scale * 1.6))
                crown_height = max(8, round(crown_radius * scale * 1.15))
                pygame.draw.ellipse(
                    overlay,
                    (48, 83, 49, 72),
                    (crown_center[0] - crown_width, crown_center[1] - crown_height,
                     crown_width * 2, crown_height * 2),
                )
                pygame.draw.ellipse(
                    overlay,
                    (91, 126, 72, 135),
                    (crown_center[0] - crown_width, crown_center[1] - crown_height,
                     crown_width * 2, crown_height * 2),
                    2,
                )
        screen.blit(overlay, (0, 0))

    def _draw_solid_structures(self, screen, camera, snapshot):
        """Project occupied logical mask cells from 3D into the active 2D view."""

        structures = snapshot.stats.get("solid_structures")
        if structures is None:
            structures = normalise_solid_structures(snapshot.stats.get("environment"))
        if not structures:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        for structure in structures:
            rows = structure.get("mask_rows") or []
            if not rows:
                continue
            pixel = float(structure["pixel_size_m"])
            depth = float(structure["extrusion_depth_m"])
            width = int(structure["mask_width_px"])
            height = int(structure["mask_height_px"])
            fill = tuple(structure.get("palette", {}).get("fill", (108, 101, 91)))
            edge = tuple(structure.get("palette", {}).get("edge", (184, 174, 153)))
            back = tuple(max(0, int(channel * 0.62)) for channel in fill)
            for row_index in range(height - 1, -1, -1):
                row = rows[row_index]
                bottom = (height - 1 - row_index) * pixel
                top = bottom + pixel
                for column in range(width):
                    if row[column] != "#":
                        continue
                    left = (column - width * 0.5) * pixel
                    right = left + pixel
                    front_world = [
                        SolidStructureField._local_to_world(structure, point)
                        for point in (
                            (left, -depth * 0.5, bottom),
                            (right, -depth * 0.5, bottom),
                            (right, -depth * 0.5, top),
                            (left, -depth * 0.5, top),
                        )
                    ]
                    back_world = [
                        SolidStructureField._local_to_world(structure, point)
                        for point in (
                            (left, depth * 0.5, bottom),
                            (right, depth * 0.5, bottom),
                            (right, depth * 0.5, top),
                            (left, depth * 0.5, top),
                        )
                    ]
                    project = (
                        camera.world_to_screen_3d
                        if hasattr(camera, "world_to_screen_3d")
                        else lambda point: self._screen(
                            camera,
                            point[0] + point[1] * SCREEN_DEPTH_PROJECTION,
                            point[2],
                        )
                    )
                    front_points = [project(point) for point in front_world]
                    back_points = [project(point) for point in back_world]
                    pygame.draw.polygon(overlay, (*back, 220), back_points)
                    pygame.draw.polygon(
                        overlay,
                        (*tuple(max(0, int(channel * 0.78)) for channel in fill), 225),
                        (front_points[1], back_points[1], back_points[2], front_points[2]),
                    )
                    pygame.draw.polygon(overlay, (*fill, 235), front_points)
                    pygame.draw.lines(overlay, (*edge, 225), True, front_points, 1)
        screen.blit(overlay, (0, 0))

    def _draw_surface_supports(self, screen, camera, snapshot):
        """Build a flat-palette pixel sprite from the support's attachment shape."""
        if snapshot.stats.get("surface_support_kind") == "illustrative_specimen_plane":
            radius = max(.006, snapshot.stats.get("surface_radius_m", 0.) * 1.12)
            rim = [self._path_screen(camera, (radius * math.cos(k * math.tau / 32),
                                                   radius * math.sin(k * math.tau / 32), 0.))
                   for k in range(32)]
            if all(point is not None for point in rim):
                pygame.draw.polygon(screen, (60, 61, 57), rim)
                pygame.draw.lines(screen, (108, 105, 94), True, rim, 1)
        view = getattr(camera, "view_direction", (0,-1,0))
        for rock in snapshot.stats.get("surface_supports", []):
            samples = []
            # An even spiral distribution avoids concentric latitude bands.
            sample_count = 24576
            golden_angle = math.pi*(3-math.sqrt(5))
            for sample in range(sample_count):
                z = 1-2*(sample+.5)/sample_count
                radius = math.sqrt(max(0,1-z*z)); angle = sample*golden_angle
                direction = (radius*math.cos(angle),radius*math.sin(angle),z)
                point = rock_point(rock,direction); normal = rock_normal(rock,direction)
                if sum(normal[i]*view[i] for i in range(3)) <= 0:
                    continue
                projected = self._path_screen(camera,point)
                if projected is None:
                    continue
                # Broad discrete face colours replace continuous lighting and
                # fine shaded grain. This remains a 2D indexed-colour sprite.
                dominant = max(range(3),key=lambda i:abs(normal[i]))
                palette_index = (4 if normal[2]>0 else 0) if dominant == 2 else (
                    2 if normal[0]>0 else 1) if dominant == 0 else 3
                color = ROCK_PIXEL_PALETTE[palette_index]
                depth = sum(point[i]*view[i] for i in range(3))
                samples.append((depth,projected,color))
            dot_radius = max(1,math.ceil(max(rock["radii_m"])*math.sqrt(4*math.pi/sample_count)*getattr(camera,"scale",100)))
            for _,point,color in sorted(samples,key=lambda item:item[0]):
                pygame.draw.rect(screen,color,(point[0]-dot_radius,point[1]-dot_radius,2*dot_radius+1,2*dot_radius+1))

    def _path_screen(self, camera, point):
        if hasattr(camera, "world_to_screen_3d"):
            return camera.world_to_screen_3d(point)
        return self._screen(camera, float(point[0]) + float(point[1]) * SCREEN_DEPTH_PROJECTION, float(point[2]))

    #: kinds whose colour is worth varying per species. Roots/renewal organs
    #: stay untinted -- they're mostly hidden underground and not part of
    #: what a viewer compares between species in a landscape.
    _TINTABLE_KINDS = frozenset({"stem_section", "branch_section", "leaf", "flower", "fruit"})

    #: needle/scale foliage (conifers) reads as a darker, cooler green in
    #: real photographs than the bright grass-green default tuned for
    #: broadleaf simple leaves -- trait-driven (leaf_structure), not a
    #: species-ID branch, so every needle/scale-leaved species benefits.
    _NEEDLE_LEAF_BASE = (52, 98, 78)
    #: A gymnosperm cone is small, dry and brown/green/purple -- nothing
    #: like an angiosperm flower's bright reproductive-signal colour. Used
    #: for both "flower" (a young cone) and "fruit" (a mature seed cone)
    #: placements on a plant_reproductive_structure="cone" species -- see
    #: Plant_Design_Process.md's reproductive-structure fix.
    _CONE_BASE = (109, 96, 61)
    _MATURE_CONE_BASE = (94, 68, 42)
    #: A grass/sedge spike (e.g. ryegrass) is a narrow, petal-less cluster
    #: of small spikelets -- a straw/olive tone, nothing like an
    #: angiosperm flower's bright reproductive-signal colour, and visually
    #: distinct from a woody cone's browner tone too.
    _SPIKE_BASE = (156, 149, 79)
    #: A sedge-like digitate/anthela cluster retains the dry olive family of
    #: individual spikes, but is drawn as several flattened spike-bearing
    #: rays from one terminal hub. This is a controlled trait value rather
    #: than a species lookup, so other sedges with the same architecture can
    #: reuse the fallback.
    _DIGITATE_SPIKE_BASE = (132, 122, 64)
    #: A loose branched sedge/grass panicle uses a dry olive family. Broadleaf
    #: forb panicles retain living green axes and clustered greenish flowers,
    #: so they use a separate trait-driven fallback rather than the grass tone.
    _PANICLE_BASE = (132, 128, 70)
    _FORB_PANICLE_BASE = (116, 154, 82)
    #: A generic capitulum fallback uses pale ray florets around a warm disc.
    #: Authored pixel assets can override its exact species colour and ray
    #: count, but the shared fallback must read as a flower head rather than
    #: the five-petal icon used for an ordinary flower.
    _CAPITULUM_RAY_BASE = (238, 238, 226)

    def _color(self, kind, sim=None, placement_index=None):
        base = {
            "root": (151, 103, 68),
            "root_section": (173, 139, 97),
            "root_support": (173, 169, 95),
            "renewal_organ": (151, 103, 62),
            "renewal_bud": (222, 184, 91),
            "stem_section": (91, 139, 70),
            "branch_section": (111, 126, 67),
            "leaf": (77, 168, 83),
            "flower": (210, 125, 170),
            "fruit": (208, 143, 61),
        }.get(kind, (150, 150, 150))
        growth = getattr(getattr(sim, "blueprint", None), "growth", None) if sim is not None else None
        growth = growth if isinstance(growth, dict) else None
        if kind == "leaf" and growth is not None:
            palette = growth.get("leaf_palette")
            if palette:
                from simulations.species.leaf_palette import leaf_display_color
                return leaf_display_color(palette, placement_index)
            if growth.get("leaf_structure") in {"needle_like", "scale_like"}:
                base = self._NEEDLE_LEAF_BASE
        elif kind == "flower" and growth is not None and growth.get("reproductive_structure") == "cone":
            base = self._CONE_BASE
        elif kind == "fruit" and growth is not None and growth.get("reproductive_structure") == "cone":
            base = self._MATURE_CONE_BASE
        elif kind == "flower" and growth is not None and growth.get("reproductive_structure") == "digitate_spike_cluster":
            base = self._DIGITATE_SPIKE_BASE
        elif kind == "flower" and growth is not None and growth.get("reproductive_structure") == "spike":
            base = self._SPIKE_BASE if growth.get("growth_form") == "graminoid" else (104, 125, 67)
        elif kind == "flower" and growth is not None and growth.get("reproductive_structure") == "panicle":
            base = (
                self._PANICLE_BASE
                if growth.get("growth_form") == "graminoid"
                else self._FORB_PANICLE_BASE
            )
        elif kind == "flower" and growth is not None and growth.get("reproductive_structure") == "capitulum":
            base = self._CAPITULUM_RAY_BASE
        species_id = getattr(sim, "species_id", None) if sim is not None else None
        if not species_id or kind not in self._TINTABLE_KINDS:
            return base
        return self._species_tint(base, f"{species_id}:{kind}")

    @staticmethod
    @functools.lru_cache(maxsize=4096)
    def _species_tint(base_rgb, seed_text):
        """Deterministic per-species colour variation.

        Without this, every species that has no authored leaf/branch/flower
        pixel asset renders with the exact same fixed RGB -- a landscape of
        many unauthored species is visually indistinguishable beyond height
        and silhouette. This is a rendering-time-only jitter (never
        persisted, never treated as a biological claim, same spirit as an
        asset's "provisional visual calibration" label): a small deterministic
        hue/saturation/lightness offset seeded by the species id and organ
        kind, bounded so foliage still reads as foliage rather than drifting
        into an unrelated colour family.

        Memoized: this is a pure function of (base_rgb, seed_text) -- every
        leaf/stem/flower/fruit placement of one species+kind produces the
        exact same tint, so recomputing the RNG-seeded HLS math from scratch
        per placement (as this did before) is pure waste. Species that fall
        back to this path for every leaf (no authored pixel asset) were
        measured spending over 40% of total render time here -- caching it
        turns thousands of redundant recomputations into a handful.
        """
        rng = random.Random(sum(ord(char) for char in seed_text))
        r, g, b = (channel / 255.0 for channel in base_rgb)
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        h = (h + rng.uniform(-0.05, 0.05)) % 1.0
        s = max(0.15, min(1.0, s * rng.uniform(0.82, 1.12)))
        l = max(0.12, min(0.88, l * rng.uniform(0.88, 1.12)))
        r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
        return (round(r2 * 255), round(g2 * 255), round(b2 * 255))

    def _draw_renewal_module(self, screen, sim, camera, kind, point, scale):
        """Draw an explicit below-ground renewal body or bud.

        Life form only warrants a renewal position.  The more specific corm
        profile is used only when ``belowground_storage`` contains ``corm``.
        """

        module = sim.blueprint.module(kind)
        ppm = self._projection_pixels_per_meter(camera)
        radius_m = float(getattr(module, "radius_m", 0.006) or 0.006)
        length_m = float(getattr(module, "length_m", 0.012) or 0.012)
        half_width = max(4, round(radius_m * float(scale) * ppm))
        half_height = max(4, round(length_m * float(scale) * ppm * 0.5))
        x, y = point
        if kind == "renewal_bud":
            pygame.draw.polygon(
                screen,
                self._color(kind, sim),
                ((x, y - half_height), (x + half_width, y),
                 (x, y + half_height), (x - half_width, y)),
            )
            pygame.draw.polygon(
                screen, (92, 70, 39),
                ((x, y - half_height), (x + half_width, y),
                 (x, y + half_height), (x - half_width, y)), 1,
            )
            return

        storage = {
            str(item).lower().replace("-", "_").replace(" ", "_")
            for item in sim.blueprint.growth.get("belowground_storage", [])
        }
        color = self._color(kind, sim)
        if "corm" in storage and not isinstance(camera, TopDownDiagnosticCamera):
            # Codonorhiza's authored corm is broadly obconic in profile with a
            # flat base.  Keep the shape recognisable at diagnostic zooms.
            points = (
                (x, y - half_height),
                (x - half_width, y + half_height - 1),
                (x + half_width, y + half_height - 1),
            )
            pygame.draw.polygon(screen, color, points)
            pygame.draw.polygon(screen, (76, 53, 35), points, 1)
        else:
            rect = pygame.Rect(x - half_width, y - half_height, half_width * 2, half_height * 2)
            pygame.draw.ellipse(screen, color, rect)
            pygame.draw.ellipse(screen, (76, 53, 35), rect, 1)

    @staticmethod
    def _pixel_scale(camera):
        """How many times larger than its own look a picture is painted: a BioSim picture painted at a view's
        size (``BiosphereBuilderRenderer._view_picture``).  Pixel floors and caps are multiplied by it, and the
        sizes at which foliage changes how it is drawn are judged at ``pixels_per_meter / pixel_scale``: the
        plant looks as it does small, in finer pixels."""
        try:
            return max(1.0, float(getattr(camera, "pixel_scale", 1.0) or 1.0))
        except (TypeError, ValueError):
            return 1.0

    @staticmethod
    def _projection_pixels_per_meter(camera):
        value = getattr(camera, "zoom", None)
        if value is None:
            value = getattr(camera, "scale", 64.0)
        try:
            return max(1.0, abs(float(value)))
        except (TypeError, ValueError):
            return 64.0

    def _draw_height_reference(self, screen, sim, camera):
        """Draw a small human silhouette using the same model-space scale."""

        reference = sim.get_height_reference() if hasattr(sim, "get_height_reference") else None
        if not isinstance(reference, dict):
            return
        height_m = max(0.1, float(reference.get("height_m", 1.75) or 1.75))
        position = reference.get("position_m") or [0.0, 0.0, 0.0]
        base = self._placement_screen(camera, ["reference", -1, position[0], position[1], position[2], 0.0, 1.0, 0])
        if base is None:
            return
        pixels_per_meter = self._projection_pixels_per_meter(camera)
        height_px = max(12, int(height_m * pixels_per_meter))
        # Keep the reference legible on very small diagnostic canvases while
        # retaining the true model-space height whenever the viewport allows.
        height_px = min(height_px, max(24, screen.get_height() - 30))
        base_x, base_y = base
        top_y = base_y - height_px
        figure_color = (176, 194, 188)
        line_width = max(1, min(3, int(pixels_per_meter * 0.035)))
        head_radius = max(2, int(height_px * 0.045))
        head_center = (base_x, top_y + head_radius + 2)
        pygame.draw.circle(screen, figure_color, head_center, head_radius, 1)
        shoulder_y = top_y + int(height_px * 0.25)
        hip_y = top_y + int(height_px * 0.56)
        pygame.draw.line(screen, figure_color, (base_x, shoulder_y), (base_x, hip_y), line_width)
        arm_span = max(3, int(height_px * 0.17))
        pygame.draw.line(screen, figure_color, (base_x - arm_span, shoulder_y + int(height_px * 0.08)), (base_x + arm_span, shoulder_y + int(height_px * 0.08)), line_width)
        leg_span = max(3, int(height_px * 0.11))
        pygame.draw.line(screen, figure_color, (base_x, hip_y), (base_x - leg_span, base_y), line_width)
        pygame.draw.line(screen, figure_color, (base_x, hip_y), (base_x + leg_span, base_y), line_width)
        font = get_font(11)
        label = font.render(str(reference.get("label") or "Human 1.75 m"), True, figure_color)
        screen.blit(label, (base_x - label.get_width() // 2, max(2, top_y - label.get_height() - 3)))

    def _fallback_leaf_endpoint(self, camera, sim, snapshot, index, point, rotation, scale, rotation_only=False):
        module = sim.blueprint.module("leaf") if hasattr(sim.blueprint, "module") else None
        if not rotation_only and ((getattr(module, "visual", {}) or {}).get("leaf_structure") == "frond_like"
                                 or (getattr(sim.blueprint, "growth", {}) or {}).get("pinnate_crown_version")):
            path = (getattr(snapshot, "placement_paths", {}) or {}).get(str(index)) or []
            if path:
                return self._path_screen(camera, path[-1])
        physical_forb_leaf = bool((getattr(sim.blueprint, "growth", {}) or {}).get("clonal_forb_shoot_grammar_version")
                                  or (getattr(sim.blueprint, "growth", {}) or {}).get("woody_graminoid_grammar_version")
                                  or (getattr(sim.blueprint, "growth", {}) or {}).get("shrub_fascicle_grammar_version")
                                  or (getattr(sim.blueprint, "growth", {}) or {}).get("basal_fan_profile"))
        minimum_scale = 0.025 if (physical_forb_leaf or (getattr(sim.blueprint, "growth", {}) or {}).get("rosette_shoot_grammar_version")) else 0.55
        orientations = getattr(snapshot, "placement_orientations", {}) or {}
        orientation = orientations.get(str(index))
        if isinstance(orientation, dict) and not rotation_only:
            forward = orientation.get("forward") or []
            if len(forward) >= 3:
                module = sim.blueprint.module("leaf") if hasattr(sim.blueprint, "module") else None
                length_m = float(getattr(module, "length_m", 0.1) or 0.1) if module is not None else 0.1
                structure = str((getattr(module, "visual", {}) or {}).get("leaf_structure") or "simple")
                minimum_length_m = 0.001 if physical_forb_leaf or structure in {"needle_like", "scale_like"} else 0.04
                length_m = max(
                    minimum_length_m,
                    length_m * max(minimum_scale, float(scale)) * (1.0 if structure == "frond_like" or physical_forb_leaf else 1.35),
                )
                origin = snapshot.placements[index][2:5]
                target = [
                    float(origin[0]) + float(forward[0]) * length_m,
                    float(origin[1]) + float(forward[1]) * length_m,
                    float(origin[2]) + float(forward[2]) * length_m,
                ]
                projected = self._placement_screen(camera, ["leaf_extent", -1, target[0], target[1], target[2], rotation, scale, 0])
                if projected is not None:
                    return projected
        module = sim.blueprint.module("leaf") if hasattr(sim.blueprint, "module") else None
        length_m = float(getattr(module, "length_m", 0.1) or 0.1) if module is not None else 0.1
        frond = (getattr(module, "visual", {}) or {}).get("leaf_structure") == "frond_like"
        length = max(2.0 * self._pixel_scale(camera), length_m * self._projection_pixels_per_meter(camera) * max(minimum_scale, float(scale)) * (1.0 if frond or physical_forb_leaf else 1.35))
        return (
            point[0] + math.cos(math.radians(rotation)) * length,
            point[1] - math.sin(math.radians(rotation)) * length,
        )

    def _draw_pinnate_crown_frond(self, screen, sim, camera, snapshot, index, scale):
        from simulations.species.pinnate_crowns import frond_leaflets
        path = (snapshot.placement_paths or {}).get(str(index)) or []
        if len(path) < 2:
            return
        visual = sim.blueprint.module("leaf").visual
        stipe = float(visual["frond_stipe_fraction"])
        ppm = self._projection_pixels_per_meter(camera)
        rachis = [self._path_screen(camera, p) for p in path]
        for i, (a, b) in enumerate(zip(rachis, rachis[1:])):
            t = i / (len(rachis) - 1)
            color = (123, 123, 66) if t < stipe else (92, 135, 63)
            pygame.draw.line(screen, color, a, b, max(1, round(ppm * .055 * scale * (1 - .8 * t))))
        for base, tip, taper in frond_leaflets(path, int(visual["leaflet_count"]),
                                             float(visual["leaflet_length_m"]), stipe, scale):
            a, b = self._path_screen(camera, base), self._path_screen(camera, tip)
            dx, dy = b[0] - a[0], b[1] - a[1]
            extent = math.hypot(dx, dy)
            if extent < .5:
                continue
            rotation = -math.degrees(math.atan2(dx, -dy))
            if not self._draw_module_asset(screen, sim, camera, "leaf", a, rotation, scale, unit_length_px=extent):
                half = max(.5, float(visual["leaflet_width_m"]) * ppm * scale * taper * .5)
                nx, ny = -dy / extent * half, dx / extent * half
                middle = (a[0] + dx * .4, a[1] + dy * .4)
                pygame.draw.polygon(screen, (63, 125, 49), [a, (middle[0] + nx, middle[1] + ny), b,
                                                           (middle[0] - nx, middle[1] - ny)])

    def _draw_fallback_leaf(self, screen, sim, camera, snapshot, index, point, rotation, scale, color=None, rotation_only=False, width_scale=1.0):
        """Draw a readable fallback for authored leaf structures.

        A compound leaf is still one reusable leaf module.  The fallback only
        expands its internal leaflet silhouette for diagnostics when no pixel
        asset has been authored yet; it does not create extra simulation
        placements or ecological entities.
        """
        if (getattr(sim.blueprint, "growth", {}) or {}).get("pinnate_crown_version") and not rotation_only:
            self._draw_pinnate_crown_frond(screen, sim, camera, snapshot, index, scale)
            return
        color = color or self._color("leaf", sim)
        if rotation_only:
            end = self._fallback_leaf_endpoint(camera, sim, snapshot, index, point, rotation, scale, True)
        else:
            end = self._fallback_leaf_endpoint(camera, sim, snapshot, index, point, rotation, scale)
        structure = "simple"
        module = sim.blueprint.module("leaf") if hasattr(sim.blueprint, "module") else None
        if module is not None:
            structure = str((getattr(module, "visual", {}) or {}).get("leaf_structure") or "simple").lower()
        width = max(1, int(3 * self._pixel_scale(camera) * max(0.45, float(scale))))
        if structure == "needle_like":
            radius_m = float(getattr(module, "radius_m", 0.001) or 0.001) if module is not None else 0.001
            needle_width = max(
                1,
                round(2.0 * radius_m * self._projection_pixels_per_meter(camera) * max(0.45, float(scale))),
            )
            dx, dy = float(end[0]) - float(point[0]), float(end[1]) - float(point[1])
            length = math.hypot(dx, dy)
            # A small gravity bend gives flexible needles a readable, reusable
            # silhouette without changing their simulated endpoint or area.
            midpoint = (
                round(float(point[0]) + dx * 0.52),
                round(float(point[1]) + dy * 0.52 + min(5.0, length * 0.10)),
            )
            pygame.draw.lines(screen, color, False, (point, midpoint, end), needle_width)
            return

        if structure not in {"pinnately_compound", "palmately_compound", "frond_like"}:
            dx, dy = float(end[0]) - float(point[0]), float(end[1]) - float(point[1])
            length = max(1.0, math.hypot(dx, dy))
            ux, uy = dx / length, dy / length
            px, py = -uy, ux
            radius_m = float(getattr(module, "radius_m", 0.012) or 0.012) if module is not None else 0.012
            half_width = max(
                width * 0.75,
                radius_m * self._projection_pixels_per_meter(camera) * max(0.45, float(scale)),
            )
            half_width = min(half_width, length * 0.28)
            half_width *= max(.2, min(1.5, float(width_scale)))
            shoulder_x = float(point[0]) + dx * 0.43
            shoulder_y = float(point[1]) + dy * 0.43
            base_half_width = half_width * 0.16
            silhouette = [
                (round(float(point[0]) + px * base_half_width), round(float(point[1]) + py * base_half_width)),
                (round(shoulder_x + px * half_width), round(shoulder_y + py * half_width)),
                (round(float(end[0])), round(float(end[1]))),
                (round(shoulder_x - px * half_width), round(shoulder_y - py * half_width)),
                (round(float(point[0]) - px * base_half_width), round(float(point[1]) - py * base_half_width)),
            ]
            pygame.draw.polygon(screen, color, silhouette)
            vein_color = tuple(max(0, int(channel * 0.68)) for channel in color)
            pygame.draw.line(screen, vein_color, point, end, max(1, width // 2))
            return

        dx, dy = end[0] - point[0], end[1] - point[1]
        length = max(1.0, math.hypot(dx, dy))
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        visual = (getattr(module, "visual", {}) or {}) if module is not None else {}
        authored_leaflets = max(0, int(visual.get("leaflet_count", 0) or 0))
        division_order = max(1, min(4, int(visual.get("leaf_division_order", 1) or 1)))
        if structure == "frond_like" and authored_leaflets and division_order >= 2:
            arch = max(0.0, min(0.35, float(visual.get("frond_arch", 0.08) or 0.08)))
            stipe_fraction = max(0.18, min(0.68, float(visual.get("frond_stipe_fraction", 0.36) or 0.36)))
            control = (
                float(point[0]) + dx * 0.46,
                float(point[1]) + dy * 0.46 - length * arch,
            )
            world_path = (getattr(snapshot, "placement_paths", {}) or {}).get(str(index)) or []
            projected_path = [self._path_screen(camera, p) for p in world_path] if not rotation_only else []
            projected_path = [p for p in projected_path if p is not None]

            def frond_curve(t):
                if len(projected_path) >= 2:
                    progress = max(0., min(1., t)) * (len(projected_path) - 1)
                    segment = min(len(projected_path) - 2, int(progress))
                    fraction = progress - segment
                    a, b = projected_path[segment:segment + 2]
                    return (a[0] + (b[0] - a[0]) * fraction,
                            a[1] + (b[1] - a[1]) * fraction)
                inverse = 1.0 - t
                return (
                    inverse * inverse * float(point[0]) + 2.0 * inverse * t * control[0] + t * t * float(end[0]),
                    inverse * inverse * float(point[1]) + 2.0 * inverse * t * control[1] + t * t * float(end[1]),
                )

            rachis = projected_path if projected_path else [frond_curve(step / 18.0) for step in range(19)]
            vein_color = tuple(max(0, int(channel * 0.72)) for channel in color)
            pygame.draw.lines(screen, vein_color, False, rachis, max(1, width))
            primary_rows = frond_primary_pinna_rows(
                authored_leaflets, visual.get("frond_pinna_arrangement", visual.get("leaf_arrangement")),
            )
            leaflet_length_m = max(0.001, float(visual.get("leaflet_length_m", 0.1) or 0.1))
            pinnule_asset = visual.get("visual_unit") == "pinnule" and self._module_asset(sim, "leaf") is not None
            pinnule_pixels = leaflet_length_m * self._projection_pixels_per_meter(camera) * max(0.55, float(scale))
            pinnule_width_pixels = max(0.0002, float(visual.get("leaflet_width_m", .01))) * self._projection_pixels_per_meter(camera) * max(0.55, float(scale))
            if pinnule_asset:
                # The robust rachis is an internal frond axis, not a separate
                # woody stem. Calibrate its width relative to the measured
                # pinnule width, then taper from brown stipe to green blade.
                for n, (a, b) in enumerate(zip(rachis, rachis[1:])):
                    t = n / max(1, len(rachis) - 1)
                    axis_width = max(1, round(pinnule_width_pixels * (1.8 - 1.5 * t)))
                    axis_color = (108, 99, 65) if t < stipe_fraction else (111, 132, 72)
                    pygame.draw.line(screen, axis_color, a, b, axis_width)

            def draw_pinnule(base, tip, taper=1.0):
                # Pygame rotates anticlockwise; a rightward blade needs a
                # negative roll to follow its supporting axis from the base.
                angle = -math.degrees(math.atan2(tip[0] - base[0], base[1] - tip[1]))
                self._draw_module_asset(screen, sim, camera, "leaf", base, angle, scale,
                                        unit_length_px=max(1.0, pinnule_pixels * taper))
            frond_blade_width = visual.get("frond_blade_width_m")
            if frond_blade_width is None:
                # Frozen pre-development blueprints retain their historical
                # scale conflation for an honest before/after comparison.
                primary_max = min(
                    length * 0.43,
                    leaflet_length_m * self._projection_pixels_per_meter(camera) * max(0.55, float(scale)) * 1.5,
                )
            else:
                primary_max = min(
                    length * 0.46,
                    max(0.0, float(frond_blade_width))
                    * self._projection_pixels_per_meter(camera)
                    * max(0.55, float(scale)) * 0.5,
                )
            render_order = min(division_order, max(1, int(getattr(snapshot, "lod", 2)) + 1))
            if length < 140.0 and not pinnule_asset:
                render_order = min(render_order, 2)
            physical_blade = len(world_path) >= 2 and frond_blade_width is not None and not rotation_only
            for _row_index, (blade_progress, primary_sides) in enumerate(primary_rows):
                t = stipe_fraction + (1.0 - stipe_fraction) * blade_progress
                base_x, base_y = frond_curve(t)
                tx = 2.0 * (1.0 - t) * (control[0] - float(point[0])) + 2.0 * t * (float(end[0]) - control[0])
                ty = 2.0 * (1.0 - t) * (control[1] - float(point[1])) + 2.0 * t * (float(end[1]) - control[1])
                if projected_path:
                    before, after = frond_curve(max(0., t - .01)), frond_curve(min(1., t + .01))
                    tx, ty = after[0] - before[0], after[1] - before[1]
                tangent_length = max(0.001, math.hypot(tx, ty))
                tangent_x, tangent_y = tx / tangent_length, ty / tangent_length
                normal_x, normal_y = -tangent_y, tangent_x
                if not rotation_only and not physical_blade:
                    orientation = (getattr(snapshot, "placement_orientations", {}) or {}).get(str(index)) or {}
                    forward = orientation.get("forward") or []
                    if len(forward) >= 3:
                        # A low frond's blade plane projects narrowly in the
                        # vertical direction. A full screen-space normal made
                        # its pinnae hang through the ground after height and
                        # frond length were correctly separated.
                        normal_y *= max(.15, min(1.0, abs(float(forward[2]))))
                primary_taper = max(0.10, (1.0 - blade_progress) ** 0.62)
                if pinnule_asset:
                    # Broad lower/middle pinnae narrow continuously toward
                    # the frond apex rather than isolated rectangular brushes.
                    primary_taper = max(.04, (1 - blade_progress) ** .72 * (.72 + .28 * math.sin(math.pi * blade_progress)))
                primary_extent = max(3.0, primary_max * primary_taper)
                for side in primary_sides:
                    sweep = .3 + .15 * blade_progress if pinnule_asset else .07
                    if physical_blade:
                        extent_m = min(float(frond_blade_width) * .5, float(module.length_m) * .46)
                        extent_m *= max(.55, float(scale)) * primary_taper
                        _, world_tip = frond_pinna_world_geometry(world_path, t, side, extent_m, sweep)
                        tip_x, tip_y = self._path_screen(camera, world_tip)
                    else:
                        tip_x = base_x + normal_x * side * primary_extent + tangent_x * primary_extent * sweep
                        tip_y = base_y + normal_y * side * primary_extent + tangent_y * primary_extent * sweep
                    primary_extent = math.hypot(tip_x - base_x, tip_y - base_y)
                    pygame.draw.line(
                        screen,
                        vein_color,
                        (round(base_x), round(base_y)),
                        (round(tip_x), round(tip_y)),
                        max(1, width // 2),
                    )
                    if render_order < 2 or primary_extent < 7.0:
                        continue
                    primary_dx, primary_dy = tip_x - base_x, tip_y - base_y
                    primary_length = max(0.001, math.hypot(primary_dx, primary_dy))
                    primary_ux, primary_uy = primary_dx / primary_length, primary_dy / primary_length
                    secondary_nx, secondary_ny = -primary_uy, primary_ux
                    secondary_pairs = 5 if render_order == 2 else 6
                    if pinnule_asset:
                        # Sample a bounded hierarchy at physical segment scale.
                        # The asset represents one ultimate pinnule; module
                        # length remains the whole frond for growth/ecology.
                        spacing = max(1.0, pinnule_pixels * 1.3) if render_order >= 3 else max(1.0, pinnule_width_pixels * 1.5)
                        secondary_pairs = max(5, min(8 if render_order >= 3 else 48, round(primary_length / spacing)))
                    for secondary_index in range(secondary_pairs):
                        s = 0.18 + 0.68 * (secondary_index + 0.5) / secondary_pairs
                        if pinnule_asset:
                            s = .045 + .925 * (secondary_index + .5) / secondary_pairs
                        secondary_base = (
                            base_x + primary_dx * s,
                            base_y + primary_dy * s,
                        )
                        secondary_taper = 0.35 + 0.65 * math.sin(math.pi * s) ** 0.5
                        secondary_extent = max(1.5, primary_length * 0.14 * secondary_taper)
                        if pinnule_asset and render_order >= 3:
                            # Higher-order pinnae are themselves divided
                            # triangular blades, not narrow rectangular brushes.
                            # Use the existing whole-blade aspect as a bounded
                            # similarity proxy for this next hierarchical scale.
                            aspect = float(frond_blade_width or 0.) / max(.001,float(module.length_m))
                            half_width_ratio = max(.10,min(.18,aspect*.20))
                            secondary_taper = .12+.88*(1.-s)**.65
                            secondary_extent = max(1.5,primary_length*half_width_ratio*secondary_taper)
                        for secondary_side in (-1.0, 1.0):
                            pinnule_sweep = .5 if pinnule_asset and render_order == 2 else .12
                            secondary_tip = (
                                secondary_base[0] + secondary_nx * secondary_side * secondary_extent + primary_ux * secondary_extent * pinnule_sweep,
                                secondary_base[1] + secondary_ny * secondary_side * secondary_extent + primary_uy * secondary_extent * pinnule_sweep,
                            )
                            if pinnule_asset and render_order == 2:
                                taper = min(1., max(.18, (1 - s) ** .35 * 1.4))
                                draw_pinnule(secondary_base, secondary_tip, taper)
                                continue
                            pygame.draw.line(
                                screen,
                                color,
                                (round(secondary_base[0]), round(secondary_base[1])),
                                (round(secondary_tip[0]), round(secondary_tip[1])),
                                1,
                            )
                            if render_order < 3 or secondary_extent < 3.0:
                                if pinnule_asset:
                                    draw_pinnule(secondary_base, secondary_tip)
                                continue
                            secondary_dx = secondary_tip[0] - secondary_base[0]
                            secondary_dy = secondary_tip[1] - secondary_base[1]
                            secondary_length = max(0.001, math.hypot(secondary_dx, secondary_dy))
                            secondary_ux = secondary_dx / secondary_length
                            secondary_uy = secondary_dy / secondary_length
                            tertiary_nx, tertiary_ny = -secondary_uy, secondary_ux
                            tertiary_fractions = (0.45, 0.70)
                            if pinnule_asset:
                                pairs = max(2, min(3, round(secondary_length / max(1.0, pinnule_width_pixels * 2))))
                                tertiary_fractions = tuple(.15 + .75 * (i + .5) / pairs for i in range(pairs))
                            for tertiary_fraction in tertiary_fractions:
                                tertiary_base = (
                                    secondary_base[0] + secondary_dx * tertiary_fraction,
                                    secondary_base[1] + secondary_dy * tertiary_fraction,
                                )
                                tertiary_extent = max(1.0, secondary_length * 0.24 * (1.0 - tertiary_fraction * 0.32))
                                for tertiary_side in (-1.0, 1.0):
                                    tertiary_tip = (
                                        tertiary_base[0] + tertiary_nx * tertiary_side * tertiary_extent + secondary_ux * tertiary_extent * 0.12,
                                        tertiary_base[1] + tertiary_ny * tertiary_side * tertiary_extent + secondary_uy * tertiary_extent * 0.12,
                                    )
                                    pygame.draw.line(
                                        screen,
                                        color,
                                        (round(tertiary_base[0]), round(tertiary_base[1])),
                                        (round(tertiary_tip[0]), round(tertiary_tip[1])),
                                        1,
                                    )
                                    if pinnule_asset:
                                        draw_pinnule(tertiary_base, tertiary_tip)
            return
        if structure in {"pinnately_compound", "frond_like"} and authored_leaflets:
            arch = max(0.0, min(0.35, float(visual.get("frond_arch", 0.0) or 0.0)))
            control = (
                float(point[0]) + dx * 0.43,
                float(point[1]) + dy * 0.43 - length * arch,
            )

            def curve(t):
                inverse = 1.0 - t
                return (
                    inverse * inverse * float(point[0]) + 2.0 * inverse * t * control[0] + t * t * float(end[0]),
                    inverse * inverse * float(point[1]) + 2.0 * inverse * t * control[1] + t * t * float(end[1]),
                )

            rachis = [curve(step / 16.0) for step in range(17)]
            pygame.draw.lines(screen, color, False, rachis, width)
            pair_count = max(1, math.ceil(authored_leaflets / 2.0))
            # The ecological count stays authored in the snapshot.  The
            # renderer samples it to keep a many-crowned stand legible and
            # bounded while retaining a recognisable compound-leaf rhythm.
            sampled_pairs = min(24, pair_count)
            leaflet_length_m = max(0.001, float(visual.get("leaflet_length_m", 0.1) or 0.1))
            leaflet_width_m = max(0.0002, float(visual.get("leaflet_width_m", 0.01) or 0.01))
            leaflet_pixels = min(
                length * 0.22,
                leaflet_length_m * self._projection_pixels_per_meter(camera) * max(0.55, float(scale)),
            )
            leaflet_width = max(
                1,
                round(leaflet_width_m * self._projection_pixels_per_meter(camera) * max(0.55, float(scale))),
            )
            for pair_index in range(sampled_pairs):
                t = 0.17 + 0.80 * (pair_index + 0.5) / sampled_pairs
                base_x, base_y = curve(t)
                tx = 2.0 * (1.0 - t) * (control[0] - float(point[0])) + 2.0 * t * (float(end[0]) - control[0])
                ty = 2.0 * (1.0 - t) * (control[1] - float(point[1])) + 2.0 * t * (float(end[1]) - control[1])
                tangent_length = max(0.001, math.hypot(tx, ty))
                tangent_x, tangent_y = tx / tangent_length, ty / tangent_length
                normal_x, normal_y = -tangent_y, tangent_x
                normalised_t = max(0.0, min(1.0, (t - 0.15) / 0.85))
                taper = 0.24 + 0.76 * math.sin(math.pi * normalised_t) ** 0.45
                extent = max(2.0, leaflet_pixels * taper)
                # A deterministic forward sweep breaks the rigid fishbone
                # look without inventing extra organs or randomising frames.
                sweep = 0.08 + 0.035 * math.sin(index * 1.73 + pair_index * 0.61)
                for side in (-1.0, 1.0):
                    tip = (
                        round(base_x + normal_x * side * extent + tangent_x * extent * sweep),
                        round(base_y + normal_y * side * extent + tangent_y * extent * sweep + extent * 0.035),
                    )
                    pygame.draw.line(screen, color, (round(base_x), round(base_y)), tip, leaflet_width)
            return

        pygame.draw.line(screen, color, point, end, width)
        leaflet_count = 5 if structure in {"pinnately_compound", "frond_like"} else 4
        for leaflet_index in range(leaflet_count):
            fraction = 0.22 + 0.13 * leaflet_index
            base_x = point[0] + dx * fraction
            base_y = point[1] + dy * fraction
            side = -1.0 if leaflet_index % 2 else 1.0
            legacy_leaflet_length = max(2.5, length * (0.24 - 0.018 * leaflet_index))
            tip_x = base_x + px * side * legacy_leaflet_length + ux * legacy_leaflet_length * 0.18
            tip_y = base_y + py * side * legacy_leaflet_length + uy * legacy_leaflet_length * 0.18
            pygame.draw.line(screen, color, (round(base_x), round(base_y)), (round(tip_x), round(tip_y)), width)

    def _module_asset(self, sim, kind):
        module = sim.blueprint.module(kind) if hasattr(sim.blueprint, "module") else None
        asset_ref = getattr(module, "asset_ref", None) if module is not None else None
        if not asset_ref:
            return None
        # Resolving a path stats the filesystem; a canopy can call this
        # thousands of times per frame for the same asset_ref, so memoize the
        # resolution itself, not just the loaded surface.
        path_key = self._asset_path_cache.get(asset_ref)
        if path_key is None:
            path = Path(asset_ref)
            if not path.is_absolute():
                path = _PROJECT_ROOT / path
            path_key = str(path.resolve())
            self._asset_path_cache[asset_ref] = path_key
        revision = self._asset_revision(path_key)
        cache_key = (path_key, revision)
        if cache_key in self._asset_cache:
            return self._asset_cache[cache_key]
        try:
            surface = asset_files.load_image(path_key)
            if pygame.display.get_surface() is not None:
                surface = surface.convert_alpha()
        except (pygame.error, OSError):
            surface = None
        self._asset_cache[cache_key] = surface
        return surface

    def _asset_revision(self, path_key):
        now = pygame.time.get_ticks()
        cached = self._asset_revision_cache.get(path_key)
        if cached is not None and now - cached[0] < 250:
            return cached[1]
        revision = asset_files.revision(path_key)
        self._asset_revision_cache[path_key] = (now, revision)
        return revision

    def _visual_asset_revision(self, sim):
        revisions = []
        for module in getattr(sim.blueprint, "modules", ()):
            asset_ref = getattr(module, "asset_ref", None)
            if not asset_ref:
                continue
            path_key = self._asset_path_cache.get(asset_ref)
            if path_key is None:
                path = Path(asset_ref)
                if not path.is_absolute():
                    path = _PROJECT_ROOT / path
                path_key = str(path.resolve())
                self._asset_path_cache[asset_ref] = path_key
            revisions.append((module.id, path_key, self._asset_revision(path_key)))
        if sim.blueprint.growth.get("fungal_grammar_version"):
            from simulations.species.fungal_visuals import preview_wood_revision
            revisions.append(preview_wood_revision(self))
        return tuple(revisions)

    def _module_texture(self, sim, kind):
        module = sim.blueprint.module(kind) if hasattr(sim.blueprint, "module") else None
        ref = getattr(module, "texture_set_ref", None) if module is not None else None
        if not ref and module is not None:
            ref = (getattr(module, "visual", {}) or {}).get("texture_set_ref")
        if not ref:
            return None, None
        return self._texture_from_ref(ref)

    def _texture_from_ref(self, ref):
        """Load shared authored bark for organism modules or scene supports."""
        cache_key = self._texture_path_cache.get(ref)
        if cache_key is None:
            path = Path(ref)
            if not path.is_absolute():
                path = _PROJECT_ROOT / path
            cache_key = str(path.resolve())
            self._texture_path_cache[ref] = cache_key
        revision = self._asset_revision(cache_key)
        if self._texture_revision_cache.get(cache_key) != revision:
            self._texture_cache.pop(cache_key, None)
            for surface_key in list(self._texture_surface_cache):
                if surface_key[0] == cache_key:
                    self._texture_surface_cache.pop(surface_key)
            self._texture_revision_cache[cache_key] = revision
        if cache_key in self._texture_cache:
            return cache_key, self._texture_cache[cache_key]
        texture = None
        try:
            with asset_files.open_gzip_text(cache_key) as handle:
                document = json.load(handle)
            payload = document.get("texture_set") if isinstance(document, dict) else document
            texture = TextureSet.from_dict(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            texture = None
        self._texture_cache[cache_key] = texture
        return cache_key, texture

    def _texture_surface(self, cache_key, texture, variant_key=None):
        if texture is None:
            return None
        cache_id = (cache_key, variant_key or "base")
        if cache_id in self._texture_surface_cache:
            return self._texture_surface_cache[cache_id]
        layers = texture.base_layers
        if variant_key and variant_key in texture.variants:
            layers = texture.variants[variant_key].layers
        surface = pygame.Surface((max(1, int(texture.width)), max(1, int(texture.height))), pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        for layer in layers or []:
            if not isinstance(layer, dict) or not layer.get("visible", True):
                continue
            try:
                opacity = max(0.0, min(1.0, float(layer.get("opacity", 1.0) or 0.0)))
            except (TypeError, ValueError):
                opacity = 1.0
            pixels = layer.get("pixels") or []
            for y, row in enumerate(pixels[:texture.height]):
                if not isinstance(row, list):
                    continue
                for x, color in enumerate(row[:texture.width]):
                    if color is None:
                        continue
                    try:
                        rgba = (int(color[0]), int(color[1]), int(color[2]), int(255 * opacity))
                    except (TypeError, ValueError, IndexError):
                        continue
                    surface.set_at((x, y), rgba)
        self._texture_surface_cache[cache_id] = surface
        return surface

    def _draw_textured_path(self, screen, cache_key, texture, variant_key, path_points, line_width, physical_width=False):
        surface = self._texture_surface(cache_key, texture, variant_key)
        if surface is None or len(path_points) < 2:
            return False
        for start, end in zip(path_points, path_points[1:]):
            dx, dy = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
            length = math.hypot(dx, dy)
            if length < 0.5:
                continue
            target_width = max(1, int(line_width)) if physical_width else max(4, int(line_width) * 3)
            target_height = max(4, round(length + max(0, int(line_width) - 2)))
            sprite = pygame.transform.scale(surface, (target_width, target_height))
            angle = -math.degrees(math.atan2(dx, -dy))
            sprite = pygame.transform.rotate(sprite, angle)
            center = (round((float(start[0]) + float(end[0])) * 0.5), round((float(start[1]) + float(end[1])) * 0.5))
            screen.blit(sprite, sprite.get_rect(center=center))
        return True

    @staticmethod
    def _mirror_leaf_for_rotation(kind, rotation):
        if kind != "leaf":
            return False
        return float(rotation) % 360.0 > 180.0

    @staticmethod
    def _module_depicted_size_m(module):
        """Return visual sprite size without changing structural length."""

        visual = getattr(module, "visual", {}) or {} if module is not None else {}
        try:
            value = float(visual.get("depicted_size_m"))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) and value > 0.0 else None

    def _rosette_leaf_width_scale(self, camera, placement, point):
        """Compress a basal leaf when its blade plane projects edge-on.

        The reusable asset remains a face view.  Its width axis is tangential
        to the crown, so projecting that tangent supplies a camera-dependent
        profile without requiring a second hand-painted side-view sprite.
        """

        base_camera = getattr(camera, "camera", camera)
        if isinstance(base_camera, TopDownDiagnosticCamera):
            return 1.0
        if not isinstance(base_camera, DiagnosticCamera):
            return 1.0
        angle = math.radians(float(placement[5]))
        # DiagnosticCamera is an intentionally readable oblique elevation,
        # not a perspective camera: its y contribution is exaggerated rather
        # than foreshortened.  Use the blade's tangential x component to add
        # the missing edge-on cue explicitly in this view.
        return 0.28 + 0.72 * abs(math.sin(angle))

    @staticmethod
    def _sample_reproductive_overlays(overlays, cell_size=14, threshold=64):
        """Keep dense reproductive overlays legible without deleting organs.

        Sampling is renderer-only and deterministic in screen space. Sparse
        flowering plants pass through unchanged; a dense tree keeps at most
        one visible accent per cell while every canonical placement remains in
        the snapshot and ecological metrics. Mature fruit/seed cones win a
        contested cell over young flowers/pollen cones.
        """

        overlays = list(overlays)
        if len(overlays) <= int(threshold):
            return overlays
        cell_size = max(2, int(cell_size))
        ranked = sorted(
            enumerate(overlays),
            key=lambda item: (0 if item[1][0] == "fruit" else 1, item[0]),
        )
        occupied = set()
        selected_indices = []
        for index, overlay in ranked:
            point = overlay[1]
            cell = (round(float(point[0]) / cell_size), round(float(point[1]) / cell_size))
            if cell in occupied:
                continue
            occupied.add(cell)
            selected_indices.append(index)
        return [overlays[index] for index in sorted(selected_indices)]

    def _draw_bloom_cohorts(self, screen, sim, camera, snapshot, visible_indices=None):
        """Draw represented bloom throughout the shoot volume, before accents.

        The accent sampler's one-organ-per-screen-cell rule does not apply to
        collective bloom coverage. Canonical organs/ecological budgets remain
        untouched, and every native unit retains its authored metric size.
        """
        density = float(sim.blueprint.growth.get("bloom_density",0))
        phase = float(sim.life_state().get("reproductive_factor",0))
        if density <= 0 or phase <= 0 or sim.blueprint.growth.get("reproductive_mode") not in {"sexual","both","apomictic"}:
            return 0
        from simulations.species.bloom_cohorts import bloom_samples, bloom_surface
        source = self._module_asset(sim,"flower")
        module = sim.blueprint.module("flower")
        size = self._module_depicted_size_m(module)
        if source is None or size is None:
            return 0
        box = source.get_bounding_rect()
        if not box.width or not box.height:
            return 0
        anchor = ((module.attachment_point[0]*source.get_width()-box.x)/box.width,
                  (module.attachment_point[1]*source.get_height()-box.y)/box.height)
        source = source.subsurface(box)
        ppm = self._projection_pixels_per_meter(camera)
        leaf_length = sim.blueprint.module("leaf").length_m
        drawn = 0
        for cluster in snapshot.leaf_clusters:
            host = int(cluster.get("host_placement_index",-1))
            if visible_indices is not None and host not in visible_indices:
                continue
            samples = bloom_samples(cluster,density,leaf_length,phase)
            if not samples:
                continue
            origin = self._path_screen(camera,cluster["bloom_axis_m"][0])
            if origin is None:
                continue
            projected = []
            for position, forward in samples:
                point = self._path_screen(camera,position)
                tip = self._path_screen(camera,[position[j]+forward[j]*.02 for j in range(3)])
                if point and tip:
                    rotation = -math.degrees(math.atan2(tip[0]-point[0],point[1]-tip[1]))
                    projected.append((point[0]-origin[0],point[1]-origin[1],rotation))
            tile = bloom_surface(source,anchor,projected,size*ppm*(.65+.35*phase))
            if tile is not None:
                canvas, offset = tile
                screen.blit(canvas,(round(origin[0]+offset[0]),round(origin[1]+offset[1])))
                drawn += len(projected)
        return drawn

    def _draw_reproductive_fallback(self, screen, sim, camera, kind, point, rotation, scale, color, variant_seed=0):
        """Draw a small organ-like fallback instead of an unlabelled circle."""

        module = sim.blueprint.module(kind) if hasattr(sim.blueprint, "module") else None
        depicted_size_m = self._module_depicted_size_m(module)
        structure = str(sim.blueprint.growth.get("reproductive_structure") or "other_unknown")
        if depicted_size_m is None:
            if structure == "cone":
                depicted_size_m = 0.055 if kind == "flower" else 0.09
            elif structure == "spike":
                # A grass spike is a genuinely elongated organ (often
                # 10-30cm), not a small point-like flower -- fall back to a
                # generic length rather than the tiny per-flower default
                # below so it still reads as a spike, not a dot.
                depicted_size_m = 0.12
            elif structure == "digitate_spike_cluster":
                # The cluster is conspicuous through its breadth, not by
                # approaching a quarter of the plant's height. Keeping the
                # generic fallback compact also prevents neighbouring culms
                # in a dense tussock from merging into one solid crown blob.
                depicted_size_m = 0.10
            elif structure == "panicle":
                depicted_size_m = 0.22
            elif kind == "fruit":
                depicted_size_m = 0.08
            else:
                depicted_size_m = max(0.04, float(getattr(module, "length_m", 0.1) or 0.1))
        pixels_per_meter = self._projection_pixels_per_meter(camera)
        minimum_height = (
            4 if structure == "cone" and kind == "flower"
            else 7 if structure == "capitulum" and kind == "flower"
            else 6 if structure in {"cone", "spike", "digitate_spike_cluster", "panicle"}
            else 3
        )
        compound_graminoid = structure == "panicle" and sim.blueprint.growth.get("growth_form") == "graminoid"
        maximum_height = 256 if compound_graminoid else 90 if structure == "panicle" else 52 if structure == "digitate_spike_cluster" else 36
        height = max(
            minimum_height,
            min(maximum_height, round(depicted_size_m * pixels_per_meter * max(0.55, float(scale)))),
        )

        if structure == "cone":
            width = max(3, round(height * 0.58))
            canvas = pygame.Surface((width + 6, height + 6), pygame.SRCALPHA)
            cx = canvas.get_width() // 2
            top, bottom = 2, canvas.get_height() - 3
            half = max(1, width // 2)
            dark = tuple(max(0, round(channel * 0.62)) for channel in color)
            light = tuple(min(255, round(channel * 1.18)) for channel in color)
            outline = ((cx, top), (cx + half, top + max(2, height // 3)), (cx + half - 1, bottom - 2),
                       (cx, bottom), (cx - half + 1, bottom - 2), (cx - half, top + max(2, height // 3)))
            pygame.draw.polygon(canvas, color, outline)
            pygame.draw.lines(canvas, dark, True, outline, 1)
            for row in range(top + 2, bottom - 1, max(2, height // 4)):
                span = max(1, round(half * min(1.0, (row - top + 2) / max(2, height * 0.45))))
                pygame.draw.line(canvas, light, (cx - span, row), (cx + span, row), 1)
        elif structure == "digitate_spike_cluster":
            # Several narrow, flattened spike-bearing rays leave one terminal
            # hub. Long green involucral bracts extend beyond the compact,
            # irregular spikelet cluster, matching the general sedge body plan
            # without a species lookup.
            width = max(17, round(height * 1.65))
            canvas = pygame.Surface((width + 8, height + 8), pygame.SRCALPHA)
            hub = (canvas.get_width() // 2, canvas.get_height() - 4)
            dark = tuple(max(0, round(channel * 0.66)) for channel in color)
            light = tuple(min(255, round(channel * 1.16)) for channel in color)
            bract_color = (69, 132, 72)
            for angle_deg, length_factor in ((-76.0, 1.02), (5.0, 1.08), (73.0, 0.94)):
                angle = math.radians(angle_deg)
                bract_length = max(8, round(height * length_factor))
                bract_tip = (
                    round(hub[0] + math.sin(angle) * bract_length),
                    round(hub[1] - math.cos(angle) * bract_length),
                )
                pygame.draw.line(canvas, bract_color, hub, bract_tip, 1)
            rays = (
                (-61.0, 0.62),
                (-39.0, 0.74),
                (-17.0, 0.58),
                (3.0, 0.80),
                (27.0, 0.67),
                (52.0, 0.55),
            )
            for ray_index, (angle_deg, length_factor) in enumerate(rays):
                angle = math.radians(angle_deg)
                ray_length = max(6, round(height * 0.72 * length_factor))
                direction = (math.sin(angle), -math.cos(angle))
                tip = (
                    round(hub[0] + direction[0] * ray_length),
                    round(hub[1] + direction[1] * ray_length),
                )
                pygame.draw.line(canvas, dark, hub, tip, 1)
                perpendicular = (-direction[1], direction[0])
                for spikelet_index, fraction in enumerate((0.28, 0.49, 0.68, 0.86)):
                    center = (
                        hub[0] + direction[0] * ray_length * fraction,
                        hub[1] + direction[1] * ray_length * fraction,
                    )
                    side = -1.0 if (spikelet_index + ray_index) % 2 else 1.0
                    half = max(1, round(height * (0.055 + 0.012 * (spikelet_index % 2))))
                    start = (
                        round(center[0] - perpendicular[0] * half),
                        round(center[1] - perpendicular[1] * half),
                    )
                    end = (
                        round(center[0] + perpendicular[0] * half * side),
                        round(center[1] + perpendicular[1] * half * side),
                    )
                    pygame.draw.line(canvas, color, start, end, 1)
                pygame.draw.circle(canvas, light, tip, 1)
            pygame.draw.circle(canvas, dark, hub, 2)
        elif structure == "spike":
            graminoid_spike = sim.blueprint.growth.get("growth_form") == "graminoid"
            width = (
                max(3, round(height * 0.26))
                if graminoid_spike
                else max(5, round(height * 0.20))
            )
            canvas = pygame.Surface((width + 6, height + 6), pygame.SRCALPHA)
            cx = canvas.get_width() // 2
            top, bottom = 2, canvas.get_height() - 3
            dark = tuple(max(0, round(channel * 0.7)) for channel in color)
            pygame.draw.line(canvas, dark, (cx, top), (cx, bottom), 1)
            if graminoid_spike:
                # Grass spikes retain their two-ranked spikelet silhouette.
                spikelet_count = max(3, (bottom - top) // 3)
                spikelet_half = max(1, width // 2)
                for index in range(spikelet_count):
                    fraction = index / max(1, spikelet_count - 1)
                    row = round(top + fraction * (bottom - top))
                    side = 1 if index % 2 == 0 else -1
                    pygame.draw.line(canvas, color, (cx, row), (cx + side * spikelet_half, row - 1), 1)
            else:
                # Forb spikes such as Plantago are dense cylinders of tiny
                # sessile flowers, not the ladder-like grass arrangement.
                light = tuple(min(255, round(channel * 1.10)) for channel in color)
                half = max(2, width // 2)
                outline = (
                    (cx, top),
                    (cx + half - 1, top + 2),
                    (cx + half, bottom - 2),
                    (cx, bottom),
                    (cx - half, bottom - 2),
                    (cx - half + 1, top + 2),
                )
                pygame.draw.polygon(canvas, color, outline)
                pygame.draw.lines(canvas, dark, True, outline, 1)
                for row in range(top + 2, bottom - 1, 3):
                    offset = 1 if (row // 3) % 2 else -1
                    pygame.draw.circle(canvas, light, (cx + offset, row), 1)
        elif structure == "panicle" and sim.blueprint.growth.get("growth_form") == "graminoid":
            canvas = compound_panicle_surface(height, color, variant_seed)
        elif structure == "panicle":
            # A loose compound inflorescence: one rachis, successively
            # shorter spreading branches, secondary forks, and small terminal
            # spikelets. The deliberately unequal alternating tiers avoid the
            # ladder-like symmetry of a spike while remaining deterministic.
            # This is shared by every species that authors the panicle category.
            graminoid_panicle = sim.blueprint.growth.get("growth_form") == "graminoid"
            width = max(11, round(height * (1.65 if graminoid_panicle else 0.95)))
            canvas = pygame.Surface((width + 8, height + 8), pygame.SRCALPHA)
            cx = canvas.get_width() // 2
            top, bottom = 3, canvas.get_height() - 3
            dark = tuple(max(0, round(channel * (0.68 if graminoid_panicle else 0.82))) for channel in color)
            light = tuple(min(255, round(channel * 1.16)) for channel in color)
            rachis_top = top + max(2, height // 9)
            pygame.draw.line(canvas, dark, (cx, bottom), (cx, rachis_top), 1)
            tiers = (
                (0.18, -1, 0.96, 0.01),
                (0.28, 1, 0.82, -0.04),
                (0.39, -1, 0.74, 0.07),
                (0.50, 1, 0.68, 0.01),
                (0.61, -1, 0.53, -0.03),
                (0.71, 1, 0.46, 0.06),
                (0.80, -1, 0.31, 0.00),
            )
            half_reach = width * 0.45
            for fraction, side, reach_factor, droop_factor in tiers:
                row = round(bottom - fraction * (bottom - rachis_top))
                sides = (side,) if graminoid_panicle else (-1, 1)
                for branch_side in sides:
                    side_factor = 1.0 if branch_side == side else 0.78
                    reach = max(3, round(half_reach * reach_factor * side_factor))
                    tip = (
                        cx + branch_side * reach,
                        row + round(height * droop_factor) - max(1, reach // 8),
                    )
                    pygame.draw.line(canvas, dark, (cx, row), tip, 1)
                    split_x = round(cx + branch_side * reach * 0.56)
                    split_y = round(row + (tip[1] - row) * 0.56)
                    for fork_sign in (-1, 1):
                        fork_tip = (
                            split_x + branch_side * max(2, reach // 3),
                            split_y + fork_sign * max(1, reach // 7),
                        )
                        pygame.draw.line(canvas, dark, (split_x, split_y), fork_tip, 1)
                        pygame.draw.circle(canvas, light if fork_sign > 0 else color, fork_tip, 1)
                    pygame.draw.circle(canvas, color, tip, 1)
                    if not graminoid_panicle:
                        # Dense broadleaf-forb panicles read as many tiny
                        # greenish flowers along living secondary axes, not a
                        # bare brown skeleton with dots only at their tips.
                        for sample in (0.42, 0.68, 0.88):
                            cluster = (
                                round(cx + (tip[0] - cx) * sample),
                                round(row + (tip[1] - row) * sample),
                            )
                            pygame.draw.circle(canvas, light if sample > 0.6 else color, cluster, 1)
            for offset in (-2, 0, 2):
                pygame.draw.line(canvas, dark, (cx, rachis_top + 3), (cx + offset, rachis_top), 1)
                pygame.draw.circle(canvas, light, (cx + offset, rachis_top), 1)
        elif structure == "capitulum" and kind == "flower":
            diameter = max(9, round(height * 1.35))
            canvas = pygame.Surface((diameter + 8, diameter + 8), pygame.SRCALPHA)
            cx, cy = canvas.get_width() // 2, canvas.get_height() // 2
            ray_length = max(3, round(diameter * 0.36))
            ray_width = max(1, round(diameter * 0.09))
            orbit = max(2, round(diameter * 0.22))
            for ray in range(16):
                angle = math.radians(ray * 22.5)
                center = (
                    round(cx + math.cos(angle) * (orbit + ray_length * 0.36)),
                    round(cy + math.sin(angle) * (orbit + ray_length * 0.36)),
                )
                petal = pygame.Surface((ray_length + 2, ray_width + 2), pygame.SRCALPHA)
                pygame.draw.ellipse(petal, color, pygame.Rect(1, 1, ray_length, ray_width))
                rotated = pygame.transform.rotate(petal, -math.degrees(angle))
                canvas.blit(rotated, rotated.get_rect(center=center))
            pygame.draw.circle(canvas, (225, 177, 48), (cx, cy), max(2, round(diameter * 0.19)))
            pygame.draw.circle(canvas, (155, 112, 31), (cx, cy), max(2, round(diameter * 0.19)), 1)
        elif kind == "flower":
            diameter = max(5, height)
            canvas = pygame.Surface((diameter + 6, diameter + 6), pygame.SRCALPHA)
            cx, cy = canvas.get_width() // 2, canvas.get_height() // 2
            petal_radius = max(1, diameter // 4)
            orbit = max(1, diameter // 4)
            for petal in range(5):
                angle = math.radians(petal * 72.0 - 90.0)
                center = (round(cx + math.cos(angle) * orbit), round(cy + math.sin(angle) * orbit))
                pygame.draw.circle(canvas, color, center, petal_radius)
            pygame.draw.circle(canvas, (225, 190, 76), (cx, cy), max(1, diameter // 7))
        else:
            width = max(4, round(height * 0.72))
            canvas = pygame.Surface((width + 6, height + 6), pygame.SRCALPHA)
            rect = pygame.Rect(3, 3, width, height)
            dark = tuple(max(0, round(channel * 0.62)) for channel in color)
            pygame.draw.ellipse(canvas, color, rect)
            pygame.draw.ellipse(canvas, dark, rect, 1)
            pygame.draw.line(canvas, dark, (canvas.get_width() // 2, 3), (canvas.get_width() // 2, 1), 1)

        sprite = pygame.transform.rotate(canvas, float(rotation))
        center = pygame.Vector2(point)
        if compound_graminoid:
            # The panicle's base is the shoot's terminal socket, not the
            # centre of the whole head. Rotate the anchor with the canvas.
            anchor = pygame.Vector2(canvas.get_width()//2, canvas.get_height()-5)
            offset = anchor - pygame.Vector2(canvas.get_size())/2
            center -= offset.rotate(-float(rotation))
        screen.blit(sprite, sprite.get_rect(center=(round(center.x), round(center.y))))

    def _draw_module_asset(self, screen, sim, camera, kind, point, rotation, scale, width_scale=1.0, *, unit_length_px=None):
        module = sim.blueprint.module(kind) if hasattr(sim.blueprint, "module") else None
        pinnule_unit = kind == "leaf" and (getattr(module, "visual", {}) or {}).get("visual_unit") in {"pinnule", "leaflet"}
        if pinnule_unit and unit_length_px is None:
            # A pinnule sprite must be composed inside its frond hierarchy,
            # never stretched to the whole-frond structural length.
            return False
        surface = self._module_asset(sim, kind)
        if kind == "fruit" and sim.blueprint.growth.get("persistent_calyx_version"):
            from simulations.species.persistent_calyces import calyx_surface
            reproductive = sim.blueprint.growth["reproductive_profile"]
            calyx = self._module_asset(sim, "calyx")
            ppm = self._projection_pixels_per_meter(camera)*max(.01, abs(scale))
            ripeness = round(sim.life_state().get("fruit_ripeness", 1.), 3)
            variant = sim.seed + round(rotation*1000)
            refs = tuple(getattr(sim.blueprint.module(role), "asset_ref", None) for role in ("calyx", "fruit"))
            key = ("persistent_calyx", json.dumps(reproductive, sort_keys=True), round(ppm,3),
                   ripeness, variant % reproductive["persistent_calyx_display"]["max_fruitlets"],
                   refs, tuple(self._asset_revision_cache.get(ref) for ref in refs), id(calyx), id(surface))
            cached = self._inflorescence_sprite_cache.get(key)
            if cached is None:
                cached = calyx_surface(reproductive["persistent_calyx_display"], reproductive, ppm,
                                       calyx, surface, ripeness, variant)
                pixels = sum(item[0].get_width()*item[0].get_height() for item in self._inflorescence_sprite_cache.values())
                if len(self._inflorescence_sprite_cache) >= 64 or pixels+cached[0].get_width()*cached[0].get_height() > 2_000_000:
                    self._inflorescence_sprite_cache.clear()
                self._inflorescence_sprite_cache[key] = cached
            canvas, anchor = cached
            sprite = pygame.transform.rotate(canvas, rotation)
            screen.blit(sprite, sprite.get_rect(center=point))
            return True
        cluster = sim.blueprint.growth.get("inflorescence_profile") if (
            kind == "flower" or (kind == "fruit" and (sim.blueprint.growth.get("clonal_forb_reproduction_version")
                                                     or sim.blueprint.growth.get("umbellate_head_version") or sim.blueprint.growth.get("basal_subshrub_version")))) else None
        if sim.blueprint.growth.get("structural_raceme_version"):
            # These flowers/capsules already have individual connected
            # pedicels. Composing another full raceme would multiply them.
            cluster = None
        if kind == "fruit" and cluster and cluster.get("form") == "capitulum_cluster":
            cluster = {**cluster, "head_size_m": min(cluster["length_m"], cluster["width_m"],
                       sim.blueprint.growth["reproductive_profile"]["fruit_size_m"])}
        elif kind == "fruit" and (cluster or {}).get("form") != "umbellate_head":
            cluster = None
        if cluster:
            from simulations.species.inflorescences import bloom_progress, panicle_surface
            from simulations.species.compound_umbels import compound_umbel_surface
            from simulations.species.capitulum_clusters import capitulum_cluster_surface
            from simulations.species.racemes import raceme_surface
            from simulations.species.umbellate_heads import umbellate_head_surface
            ppm = self._projection_pixels_per_meter(camera) * max(.01, abs(scale))
            progress = round(bloom_progress(sim.blueprint.growth, sim.age_days), 3)
            ripeness = round(sim.life_state().get("fruit_ripeness", 1.), 3) if kind == "fruit" else 0.
            curved = bool(cluster.get("axis_curvature") or cluster.get("bloom_sag"))
            curve_rotation = round(rotation,3) if curved else 0.
            corolla_rotation = round(rotation,3) if cluster.get("flower_orientation") == "gravity_upright" else 0.
            # Include the source revision so editing a flower asset refreshes
            # every composed cluster as well as the ordinary module cache.
            module = sim.blueprint.module(kind)
            ref = getattr(module, "asset_ref", None)
            key = (kind, json.dumps(cluster, sort_keys=True), round(ppm, 3), progress,
                   ref, self._asset_revision_cache.get(ref), id(surface), curve_rotation, corolla_rotation, ripeness)
            cached = self._inflorescence_sprite_cache.get(key)
            if cached is None:
                cached = (umbellate_head_surface(cluster,ppm,surface,fruit=kind == "fruit",ripeness=ripeness)
                          if cluster.get("form") == "umbellate_head" else
                          raceme_surface(cluster,ppm,surface,rotation=corolla_rotation)
                          if cluster.get("form") == "raceme" else
                          capitulum_cluster_surface(cluster,ppm,progress,surface)
                          if cluster.get("form") == "capitulum_cluster" else
                          compound_umbel_surface(cluster,ppm,progress,surface)
                          if cluster.get("form") == "compound_umbel" else
                          panicle_surface(cluster, ppm, progress, surface,curve_rotation))
                pixels = sum(item[0].get_width()*item[0].get_height()
                             for item in self._inflorescence_sprite_cache.values())
                if (len(self._inflorescence_sprite_cache) >= 64
                        or pixels + cached[0].get_width()*cached[0].get_height() > 2_000_000):
                    self._inflorescence_sprite_cache.clear()
                self._inflorescence_sprite_cache[key] = cached
            canvas, anchor = cached
            sprite = canvas if curved else pygame.transform.rotate(canvas, rotation)
            offset = pygame.Vector2(anchor) - pygame.Vector2(canvas.get_size()) / 2
            center = pygame.Vector2(point) - (offset if curved else offset.rotate(-rotation))
            screen.blit(sprite, sprite.get_rect(center=(round(center.x), round(center.y))))
            return True
        if surface is None:
            return False
        profile = sim.blueprint.growth.get("reproductive_profile")
        if kind == "fruit" and profile:
            # The approved sprite describes ripe fruit. Preserve its shading
            # and alpha while shifting the base colour during maturation.
            ripeness = sim.life_state().get("fruit_ripeness", 1.0)
            target = [round(a*(1-ripeness)+b*ripeness)
                      for a,b in zip(profile["unripe_color"], profile["ripe_color"])]
            delta = [a-b for a,b in zip(target,profile["ripe_color"])]
            surface = surface.copy()
            surface.fill((*[max(0,c) for c in delta],0), special_flags=pygame.BLEND_RGBA_ADD)
            surface.fill((*[max(0,-c) for c in delta],0), special_flags=pygame.BLEND_RGBA_SUB)
        module = sim.blueprint.module(kind) if hasattr(sim.blueprint, "module") else None
        anchor = getattr(module, "attachment_point", (0.5, 0.9)) if module is not None else (0.5, 0.9)
        growth_vector = getattr(module, "growth_axis", (0.0, -1.0)) if module is not None else (0.0, -1.0)
        try:
            anchor_x, anchor_y = float(anchor[0]), float(anchor[1])
        except (TypeError, ValueError, IndexError):
            anchor_x, anchor_y = 0.5, 0.9
        anchor_x, anchor_y = max(0.0, min(1.0, anchor_x)), max(0.0, min(1.0, anchor_y))
        try:
            vector_x, vector_y = float(growth_vector[0]), float(growth_vector[1])
        except (TypeError, ValueError, IndexError):
            vector_x, vector_y = 0.0, -1.0
        authored_angle = math.degrees(math.atan2(vector_x, -vector_y)) if abs(vector_x) + abs(vector_y) > 1e-6 else 0.0
        render_rotation = float(rotation) - authored_angle
        source_key = getattr(module, "asset_ref", None)
        source_geometry = self._pinnule_source_cache.get(source_key) if pinnule_unit else None
        if source_geometry is not None and source_geometry[0] is surface:
            bounds, cropped_surface, original_width, original_height = source_geometry[1:]
        else:
            bounds = surface.get_bounding_rect()
            original_width, original_height = surface.get_size()
            cropped_surface = surface.subsurface(bounds).copy() if bounds.width and bounds.height else surface
            if pinnule_unit:
                if len(self._pinnule_source_cache) >= 32:
                    self._pinnule_source_cache.clear()
                self._pinnule_source_cache[source_key] = (surface, bounds, cropped_surface, original_width, original_height)
        if bounds.width > 0 and bounds.height > 0 and bounds.size != surface.get_size():
            surface = cropped_surface
            anchor_x = (anchor_x * original_width - bounds.x) / max(1, bounds.width)
            anchor_y = (anchor_y * original_height - bounds.y) / max(1, bounds.height)
            anchor_x, anchor_y = max(0.0, min(1.0, anchor_x)), max(0.0, min(1.0, anchor_y))
        try:
            pixels_per_meter = abs(camera.world_to_screen((1.0, 0.0))[0] - camera.world_to_screen((0.0, 0.0))[0])
        except (TypeError, IndexError):
            pixels_per_meter = 64.0
        if isinstance(camera, SurfaceElevationCamera):
            # A rotated ground x-axis is foreshortened; billboard organ
            # lengths remain metres along the elevation's vertical axis.
            pixels_per_meter = self._projection_pixels_per_meter(camera)
        depicted_size_m = self._module_depicted_size_m(module)
        fine = self._pixel_scale(camera)
        if kind in {"flower", "fruit", "strobilus"} and depicted_size_m is not None:
            # Pixel Studio's metric size is the real authored organ/sprite
            # extent.  Do not route this through module.length_m: that value
            # remains the structural default used by older grammars and
            # ecological calculations. At whole-tree scale a tiny organ may
            # legitimately occupy one pixel; the independently fitted detail
            # camera is what makes it larger, not a global 10 px floor.
            target_height = max(round(fine), round(depicted_size_m * pixels_per_meter * max(0.55, float(scale))))
        else:
            target_height = max(10 * fine, int(max(0.04, float(getattr(module, "length_m", 0.1))) * pixels_per_meter * max(0.55, float(scale))))
        if kind == "leaf":
            target_height = max(14 * fine, int(target_height * 1.45))
        if kind == "leaf" and sim.blueprint.growth.get("shoot_distribution_grammar"):
            target_height = max(round(2 * fine), round(float(module.length_m) * pixels_per_meter * float(scale)))
        physical_creeping_leaf = kind == "leaf" and (
            sim.blueprint.growth.get("growth_behaviour") == "creeping_prostrate"
            or sim.blueprint.growth.get("shrub_cane_grammar_version")
            or sim.blueprint.growth.get("rosette_shoot_grammar_version")
            or sim.blueprint.growth.get("clonal_forb_shoot_grammar_version")
            or sim.blueprint.growth.get("woody_graminoid_grammar_version")
            or sim.blueprint.growth.get("dimorphic_herb_profile_version")
            or sim.blueprint.growth.get("basal_herb_version")
            or sim.blueprint.growth.get('sympodial_herb_version') or sim.blueprint.growth.get('paniculate_rosette_version') or sim.blueprint.growth.get('cyme_herb_version')
            or sim.blueprint.growth.get("basal_fan_profile"))
        if physical_creeping_leaf:
            target_height = max(round(fine), round(float(module.length_m) * pixels_per_meter * float(scale)))
        if pinnule_unit:
            target_height = max(1, round(float(unit_length_px)))
        elif (kind == "leaf" and unit_length_px is not None
              and sim.blueprint.growth.get("leaf_structure") in {"needle_like", "scale_like"}):
            # A needle-clad shoot is a collective visual unit. At BioSim
            # sizes it must follow the sprite's pixel budget rather than the
            # ordinary leaf sprite's 14 px minimum.
            target_height = max(3 * fine, min(64 * fine, round(float(unit_length_px))))
        target_height = round(min(2048 if sim.blueprint.growth.get("basal_fan_profile") else 180 * fine, target_height))
        aspect = surface.get_width() / max(1, surface.get_height())
        width_scale = max(0.2, min(1.5, float(width_scale)))
        target_width = max(1 if kind in {"flower", "fruit", "strobilus"} else round(4 * fine), int(target_height * aspect * width_scale))
        if kind=='flower' and (getattr(module,'visual',{}) or {}).get('visual_unit')=='whole_spike':
            # A whole grass spike is long and narrow, independently of the
            # legacy bitmap's canvas ratio. From above it is a cross-section.
            ppm=self._projection_pixels_per_meter(camera)
            a=self._path_screen(camera,(0.,0.,0.))
            b=self._path_screen(camera,(0.,0.,module.length_m*scale))
            if a is not None and b is not None:
                target_height=max(1,round(math.dist(a,b)))
            target_width=max(1,round(2*module.radius_m*ppm*scale))
        if kind == "leaf" and (sim.blueprint.growth.get("shoot_distribution_grammar") or physical_creeping_leaf or pinnule_unit):
            target_width = max(1, round(target_height * aspect * width_scale))
        mirror = self._mirror_leaf_for_rotation(kind, rotation)
        if mirror:
            anchor_x = 1.0 - anchor_x
        cache_key = (getattr(module,"asset_ref",None),target_width,target_height,round(render_rotation/5)*5,mirror)
        # Every leaf can be edited in Pixel Studio. A new source surface must
        # invalidate its scaled/rotated sprites, not only fern pinnules.
        cache_key += (id(surface),)
        cached = self._leaf_sprite_cache.get(cache_key) if kind == "leaf" else None
        render_rotation = cache_key[3] if kind == "leaf" else render_rotation
        if cached is None:
            # Average subpixel lamina colour rather than selecting only its
            # pale central midrib when a measured pinnule is one pixel wide.
            small_panicle = (kind == "flower"
                              and sim.blueprint.growth.get("reproductive_structure") == "panicle"
                              and target_height < surface.get_height())
            thin_fruit = (kind == 'fruit' and target_width <= 2
                          and target_height < surface.get_height())
            if small_panicle or thin_fruit:
                from simulations.species.inflorescences import _area_resample
                sprite = _area_resample(surface, (target_width, target_height))
            else:
                # A tiny measured broad blade must average its lamina colour,
                # rather than selecting only the one pale midrib column.
                resize = (pygame.transform.smoothscale if target_width < 4 and (pinnule_unit
                          or (kind == "leaf" and sim.blueprint.growth.get("woody_spur_version")))
                          else pygame.transform.scale)
                sprite = resize(surface, (target_width, target_height))
            if mirror:
                sprite = pygame.transform.flip(sprite, True, False)
            sprite = pygame.transform.rotate(sprite, render_rotation)
            if kind == "leaf":
                if len(self._leaf_sprite_cache) >= 2048:
                    self._leaf_sprite_cache.clear()
                self._leaf_sprite_cache[cache_key] = sprite
        else:
            sprite = cached
        local_anchor = pygame.Vector2((anchor_x - 0.5) * target_width, (anchor_y - 0.5) * target_height)
        rotated_anchor = local_anchor.rotate(-render_rotation)
        center = pygame.Vector2(point) - rotated_anchor
        screen.blit(sprite, sprite.get_rect(center=(round(center.x), round(center.y))))
        return True

    def _draw_structural_asset_path(self, screen, sim, kind, path_points, line_width):
        """Repeat a dedicated stem/branch module along a curved segment path."""
        surface = self._module_asset(sim, kind)
        if surface is None or len(path_points) < 2:
            return False
        bounds = surface.get_bounding_rect()
        if bounds.width <= 0 or bounds.height <= 0:
            return False
        surface = surface.subsurface(bounds).copy()
        aspect = surface.get_width() / max(1, surface.get_height())
        for start, end in zip(path_points, path_points[1:]):
            dx, dy = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
            length = math.hypot(dx, dy)
            if length < 1.0:
                continue
            target_height = max(2, round(length * 1.04))
            physical = (sim.blueprint.growth.get('offset_rosette_version')
                        or sim.blueprint.growth.get('cushion_version')
                        or sim.blueprint.growth.get('rhizome_raceme_version')
                        or sim.blueprint.growth.get("shoot_distribution_grammar")
                        or sim.blueprint.growth.get("seasonal_rhizome_version")
                        or sim.blueprint.growth.get("creeping_upright_version")
                        or sim.blueprint.growth.get("shrub_cane_grammar_version")
                        or sim.blueprint.growth.get("rosette_raceme_version")
                        or sim.blueprint.growth.get("lateral_rosette_scapes_version")
                        or sim.blueprint.growth.get('sympodial_herb_version') or sim.blueprint.growth.get('paniculate_rosette_version') or sim.blueprint.growth.get('tufted_sedge_version') or sim.blueprint.growth.get('cyme_herb_version') or sim.blueprint.growth.get('mixed_tiller_version'))
            target_width = max(1, int(line_width)) if physical else max(max(2, int(line_width)), round(target_height * aspect))
            if physical:
                # Preserve the connected botanical axis even where a curved
                # sprite silhouette would otherwise leave subpixel gaps.
                pygame.draw.line(screen,(99,82,61),start,end,max(1,int(line_width)))
            sprite = pygame.transform.scale(surface, (target_width, target_height))
            angle = -math.degrees(math.atan2(dx, -dy))
            sprite = pygame.transform.rotate(sprite, angle)
            center = ((float(start[0]) + float(end[0])) * 0.5, (float(start[1]) + float(end[1])) * 0.5)
            screen.blit(sprite, sprite.get_rect(center=(round(center[0]), round(center[1]))))
        return True

    def _draw_individual(self, screen, sim, camera=None, clear=True, show_height_reference=False, roots_only=False, visible_indices=None, skeleton=False, snapshot=None, cache=True, draw_ground_line=True, foliage_sample_cap=None, draw_environment=True):
        """Draw one plant, reusing a cached frame when nothing has changed.

        A tree's snapshot is only regenerated a few times a second (growth is
        throttled in SpeciesSimulation.update), but without this cache every
        engine tick still re-walked every placement/cluster and re-blitted
        every sprite at 60Hz. Caching the fully-drawn frame per
        (snapshot, view flags, camera state) turns a static view back into a
        single cheap blit, which is what actually lets many trees stay on
        screen at once.

        ``cache`` covers both ``clear=True`` calls (screen is fully
        overwritten, safe to cache unconditionally) and ``clear=False`` calls
        used for compositing a plant onto a transparent sprite (e.g. the
        isometric forest layout) -- the latter is only cache-safe because the
        caller always hands in a freshly created, blank surface each time, so
        "replay the cached frame" and "redraw from scratch" are equivalent.
        Pass ``cache=False`` if that invariant doesn't hold for a given call.
        """
        camera = camera or self.app_view.camera
        snapshot = snapshot or sim.render_snapshot
        if cache:
            cache_key = (
                # id(sim) disambiguates instances that can share a fingerprint
                # and seed but differ in ways not captured by the snapshot's
                # own identity fields (e.g. two forest-experiment trees with
                # the same species/seed but different shading environments).
                id(sim), snapshot.blueprint_fingerprint, snapshot.seed, snapshot.age_days, snapshot.lod,
                json.dumps(snapshot.stats.get("environment") or {}, sort_keys=True, default=str),
                tuple(sorted(visible_indices)) if visible_indices is not None else None,
                bool(skeleton), bool(roots_only), bool(show_height_reference), bool(clear), bool(draw_ground_line), bool(draw_environment),
                foliage_sample_cap,
                screen.get_size(), _camera_state_key(camera),
                self._visual_asset_revision(sim),
                GRAMINOID_VISUAL_VERSION,
                ROCK_VISUAL_VERSION,
                TREE_PHYSICAL_WIDTH_VISUAL_VERSION,
                FERN_PINNULE_VISUAL_VERSION,
                ((sim.diagnostic_view, json.dumps({"wood":snapshot.stats.get("fungal_substrates"),
                    "bodies":snapshot.stats.get("fungal_bodies")},sort_keys=True,default=str))
                 if sim.blueprint.growth.get("fungal_grammar_version") else None),
            )
            cached = self._individual_draw_cache.get(cache_key)
            if cached is not None:
                screen.blit(cached, (0, 0))
                return
        self._draw_individual_uncached(
            screen, sim, camera=camera, clear=clear, show_height_reference=show_height_reference,
            roots_only=roots_only, visible_indices=visible_indices, skeleton=skeleton, snapshot=snapshot,
            draw_ground_line=draw_ground_line, foliage_sample_cap=foliage_sample_cap,
            draw_environment=draw_environment,
        )
        if cache:
            frame = screen.copy()
            self._individual_draw_cache[cache_key] = frame
            self._individual_draw_cache_order.append(cache_key)
            if len(self._individual_draw_cache_order) > 64:
                stale_key = self._individual_draw_cache_order.pop(0)
                self._individual_draw_cache.pop(stale_key, None)

    def _draw_individual_uncached(self, screen, sim, camera=None, clear=True, show_height_reference=False, roots_only=False, visible_indices=None, skeleton=False, snapshot=None, draw_ground_line=True, foliage_sample_cap=None, draw_environment=True):
        camera = camera or self.app_view.camera
        snapshot = snapshot or sim.render_snapshot
        if sim.blueprint.growth.get("fungal_grammar_version"):
            from simulations.species.fungal_visuals import draw_fungal_individual
            draw_fungal_individual(self,screen,sim,camera,snapshot,clear,visible_indices,draw_environment,
                                   cutaway=sim.diagnostic_view=="mycelium" or roots_only)
            return
        rocks = snapshot.stats.get("surface_supports", [])
        if rocks and not roots_only and not isinstance(camera,PixelSceneCamera):
            pixel_m = min(rock.get("render_pixel_size_m",.003) for rock in rocks)
            pixel_scale = max(1,min(12,round(self._projection_pixels_per_meter(camera)*pixel_m)))
            size = tuple((value+pixel_scale-1)//pixel_scale for value in screen.get_size())
            canvas = pygame.Surface(size,pygame.SRCALPHA)
            if not clear:
                canvas.blit(pygame.transform.scale(screen,size),(0,0))
            self._draw_individual_uncached(canvas,sim,camera=PixelSceneCamera(camera,pixel_scale),
                clear=clear,show_height_reference=show_height_reference,roots_only=roots_only,
                visible_indices=visible_indices,skeleton=skeleton,snapshot=snapshot,
                draw_ground_line=draw_ground_line,foliage_sample_cap=foliage_sample_cap,
                draw_environment=draw_environment)
            screen.blit(pygame.transform.scale(canvas,tuple(value*pixel_scale for value in size)),(0,0))
            return
        if clear:
            screen.fill((18, 23, 20))
        top_down_view = isinstance(camera, TopDownDiagnosticCamera)
        if top_down_view and not roots_only and visible_indices is None:
            visible_indices=canopy_visible_indices(sim,snapshot)
        if top_down_view and not roots_only:
            self._draw_neighbour_root_zones(screen, camera, snapshot)
        if not roots_only and draw_environment:
            self._draw_solid_structures(screen, camera, snapshot)
            self._draw_climbing_supports(screen, camera, snapshot)
            self._draw_surface_supports(screen, camera, snapshot)
        if draw_ground_line and not top_down_view:
            ground = self._screen(camera, snapshot.bounds_m[0] - 1.0, 0.0)
            ground_right_x = max(snapshot.bounds_m[1] + 1.0, float(getattr(sim, "height_reference_x", snapshot.bounds_m[1] + 1.0)) + 0.35)
            ground_right = self._screen(camera, ground_right_x, 0.0)
            if ground and ground_right:
                line_color = (62, 112, 126) if sim.blueprint.growth.get("shape") == "aquatic" else (82, 72, 55)
                pygame.draw.line(screen, line_color, ground, ground_right, 2)
        if clear and not top_down_view and snapshot.stats.get("root_segment_count", 0):
            soil_z = snapshot.stats.get("root_origin_z_m", 0.0)
            soil_point = self._screen(camera, 0.0, soil_z)
            if soil_point:
                soil_y = max(0, min(screen.get_height(), soil_point[1]))
                pygame.draw.rect(screen, (28, 27, 22), (0, soil_y, screen.get_width(), screen.get_height() - soil_y))
                pygame.draw.line(screen, (104, 90, 64), (0, soil_y), (screen.get_width(), soil_y), 1)
                if roots_only:
                    label = "Sediment / root crown" if sim.blueprint.growth.get("shape") == "aquatic" else "Root crown"
                    font = get_font(13)
                    screen.blit(font.render(label, True, (163, 155, 128)), (12, max(0, soil_y - 19)))

        texture_sequences = {}
        texture_slots = {}
        renewal_overlays = []
        reproductive_overlays = []
        # A basal/tufted graminoid's leaf blades (real tussock grasses like
        # ryegrass) are grown with a real 3D tip position and an actual
        # curved path (SpeciesSimulation._grow_graminoid_culm), the same as
        # a stem or branch -- not one anchored fixed-aspect sprite per leaf.
        # Keep their connected path and wrap it in one tapered blade surface.
        # Width follows the leaf module in metres and the camera projection;
        # repeated sprites per curve segment would bake in disconnected tips.
        connected_graminoid_leaves = (
            sim.blueprint.growth.get("growth_form") == "graminoid"
        )
        surface_uv={item.get("placement_index"):item.get("uv_m") for item in snapshot.attachment_points
                    if "uv_m" in item}
        leaf_development = {
            item["leaf_placement_index"]: item["leaf_development"]
            for item in snapshot.attachment_points
            if "leaf_placement_index" in item and isinstance(item.get("leaf_development"), dict)
        }

        for index, placement in enumerate(snapshot.placements):
            orientation = snapshot.placement_orientations.get(str(index), {})
            if orientation.get("min_render_lod", 0) > snapshot.lod:
                continue
            kind, parent, x, y, z, rotation, scale, level = placement
            if visible_indices is not None and index not in visible_indices:
                continue
            if skeleton and kind in {"leaf", "flower", "fruit"}:
                continue
            if roots_only and kind not in {"root", "root_section", "root_support", "renewal_organ", "renewal_bud"}:
                continue
            point = self._placement_screen(camera, placement)
            if point is None:
                continue
            if kind in {"pseudopodetium", "phyllocladium", "cephalodium", "soralium"}:
                path = [self._path_screen(camera,p) for p in snapshot.placement_paths.get(str(index),[])]
                path = [p for p in path if p is not None]
                if kind == "pseudopodetium" and len(path)>1:
                    width_m = snapshot.placement_orientations.get(str(index),{}).get("width_m",.0007)
                    width = max(1,round(width_m*self._projection_pixels_per_meter(camera)))
                    pygame.draw.lines(screen,(166,162,151),False,path,width)
                elif len(path)>=3 and not skeleton:
                    color = {"phyllocladium":(215,218,205),"cephalodium":(75,67,51),"soralium":(228,225,207)}[kind]
                    pygame.draw.polygon(screen,color,path)
                    if kind == "phyllocladium":
                        center=pygame.Vector2(point)
                        inner=[center+(pygame.Vector2(p)-center)*.48 for p in path]
                        pygame.draw.polygon(screen,(121,133,122),inner)
                continue
            if kind in {"thallus", "moss_patch", "apothecium"}:
                if (kind == "thallus" and snapshot.stats.get("surface_thallus_form") == "fruticose"
                        and snapshot.stats.get("pseudopodetium_count",0)>0):
                    # The primary squamulose thallus becomes inconspicuous as
                    # tufts develop. Footprint cells still anchor the canonical
                    # organism; painting them as a crust would mask the gaps.
                    continue
                if kind == "apothecium" and snapshot.lod == 0:
                    continue
                world_polygon = snapshot.placement_paths.get(str(index), [])
                surface_chart = snapshot.placement_orientations.get(str(index),{}).get("surface_chart")
                normal = None
                if surface_chart in {"cylindrical_trunk", "analytic_rounded_rock"} and len(world_polygon)>=3:
                    a,b,c = world_polygon[:3]
                    raw = cross([b[k]-a[k] for k in range(3)],[c[k]-a[k] for k in range(3)])
                    length = math.sqrt(sum(x*x for x in raw))
                    normal = [x/max(length,1e-12) for x in raw]
                    view = getattr(camera,"view_direction",(0,-1,0))
                    if sum(normal[k]*view[k] for k in range(3)) <= 0:
                        continue
                polygon = [self._path_screen(camera, p) for p in world_polygon]
                polygon = [p for p in polygon if p is not None]
                if len(polygon) >= 3:
                    if kind == "apothecium":
                        if snapshot.stats.get("surface_thallus_form") == "fruticose":
                            pygame.draw.polygon(screen,(106,73,48),polygon)
                            continue
                        rim, disc = surface_disc_colors(sim.blueprint.growth.get("surface_growth_profile", {}),
                                                       ((208,211,169),(94,99,70)))
                        pygame.draw.polygon(screen, rim, polygon)
                        center = pygame.Vector2(point)
                        inner = [center + (pygame.Vector2(p)-center)*.7 for p in polygon]
                        pygame.draw.polygon(screen, disc, inner)
                    else:
                        if kind == "thallus":
                            weathering = snapshot.placement_orientations.get(str(index),{}).get("weathering_progress",1.)
                            fraction = 1-weathering*(1-max(0., min(1., scale)))
                            phase = (index*37+sim.seed*13)%17/17
                            tint = (phase-.5)*16
                            uv=surface_uv.get(index)
                            if uv and fraction>.65:
                                tint+=10*math.cos(math.atan2(uv[1],uv[0])*snapshot.stats.get("surface_lobe_count",0))
                            base = (117+48*fraction,130+47*fraction,96+40*fraction)
                            color = tuple(round(max(0,min(255,c+tint))) for c in base)
                        else:
                            color=(73,115,64)
                        if normal is not None and surface_chart == "analytic_rounded_rock":
                            # The covering uses the support's pixel grid and a
                            # small palette, rather than fine smooth shading.
                            tone = max(0,min(3,round(fraction*3))) if kind == "thallus" else 1
                            color = THALLUS_PIXEL_PALETTE[tone] if kind == "thallus" else (73,115,64)
                        if kind == "thallus" and snapshot.stats.get("surface_thallus_form") == "fruticose":
                            color = (152,158,146)
                        surface_calibration = sim.blueprint.growth.get("surface_growth_profile",{}).get("visual_calibration",{})
                        if kind == "thallus" and isinstance(surface_calibration,dict) and "thallus_palette" in surface_calibration:
                            tone = snapshot.placement_orientations.get(str(index),{}).get("lobe_tone",max(0,min(3,round(fraction*3))))
                            color = surface_palette(sim.blueprint.growth["surface_growth_profile"],THALLUS_PIXEL_PALETTE)[tone]
                        pygame.draw.polygon(screen, color, polygon)
                        if kind=="thallus" and scale<.7:
                            span=max(p[0] for p in polygon)-min(p[0] for p in polygon)
                            if span>=4:
                                pygame.draw.polygon(screen,tuple(max(0,c-24) for c in color),polygon,1)
                continue
            if kind in {"renewal_organ", "renewal_bud"}:
                if kind == 'renewal_bud' and sim.blueprint.growth.get('seasonal_rhizome_version'):
                    radius = sim.blueprint.growth['seasonal_rhizome_profile']['rhizome_radius_m']*.75
                    pygame.draw.circle(screen, (178, 153, 98), point,
                                       max(1, round(radius*self._projection_pixels_per_meter(camera))))
                    continue
                renewal_overlays.append((kind, point, scale))
                continue
            color = self._color(kind, sim, index if kind == "leaf" else None)
            if orientation.get('spray_axis_role') and kind == 'branch_section':
                projected = [self._path_screen(camera,p) for p in snapshot.placement_paths.get(str(index),[])]
                if len(projected)>=2:
                    pygame.draw.lines(screen,(80,100,66),False,projected,
                        max(1,round(2*scale*self._projection_pixels_per_meter(camera))))
                continue
            if orientation.get('pendant_axis_role') and kind == 'branch_section':
                projected = [self._path_screen(camera,p) for p in snapshot.placement_paths.get(str(index),[])]
                if len(projected) >= 2:
                    width=max(1,round(2*scale*self._projection_pixels_per_meter(camera)))
                    pygame.draw.lines(screen,(108,88,63),False,projected,width)
                continue
            if sim.blueprint.growth.get('renewing_cane_version') and kind in {'stem_section', 'branch_section'}:
                projected = [self._path_screen(camera, p) for p in snapshot.placement_paths.get(str(index), [])]
                width = max(1, round(2*scale*self._projection_pixels_per_meter(camera)))
                if len(projected) >= 2:
                    if orientation.get('cane_age_fraction', 0.) >= sim.blueprint.growth['renewing_cane_profile']['old_cane_fraction']:
                        pygame.draw.lines(screen, (117, 111, 98), False, projected, width)
                    elif not self._draw_structural_asset_path(screen, sim, kind, projected, width):
                        pygame.draw.lines(screen, (132, 78, 61), False, projected, width)
                continue
            if sim.blueprint.growth.get('seasonal_rhizome_version') or sim.blueprint.growth.get('rhizome_raceme_version') or sim.blueprint.growth.get('cushion_version'):
                if kind == 'leaf' and orientation.get('seasonal_planar_blade'):
                    from simulations.species.floating_leaves import draw_planar_leaf
                    surface = self._module_asset(sim, 'leaf')
                    if surface is None:
                        surface = pygame.Surface((75, 75), pygame.SRCALPHA)
                        pygame.draw.polygon(surface, (61, 116, 48), [(37, 70), (8, 30), (29, 34), (37, 3), (46, 34), (67, 30)])
                    module = sim.blueprint.module('leaf')
                    draw_planar_leaf(screen, surface, camera, placement[2:5],
                        orientation['forward'], orientation['normal'], module.length_m*scale,
                        module.attachment_point)
                    continue
                if kind in {'stem_section', 'branch_section'}:
                    projected = [self._path_screen(camera, p) for p in snapshot.placement_paths.get(str(index), [])]
                    width = max(1, round(2*scale*self._projection_pixels_per_meter(camera)))
                    if len(projected) >= 2:
                        if not self._draw_structural_asset_path(screen, sim, kind, projected, width):
                            pygame.draw.lines(screen, (108, 83, 52) if orientation.get('seasonal_axis_role') == 'rhizome' else (95, 119, 65), False, projected, width)
                    continue
            if sim.blueprint.growth.get('creeping_upright_version'):
                if kind == 'leaf' and orientation.get('microphyll'):
                    from simulations.species.creeping_uprights import draw_microphyll
                    draw_microphyll(screen, self._module_asset(sim, 'leaf'),
                        [self._path_screen(camera, p) for p in snapshot.placement_paths.get(str(index), [])],
                        orientation['blade_width_m']*self._projection_pixels_per_meter(camera))
                    continue
                if kind == 'strobilus':
                    if not skeleton:
                        module = sim.blueprint.module(kind)
                        tip = self._path_screen(camera, (x, y, z+module.length_m*scale))
                        width = max(1, round(orientation['organ_width_m']*self._projection_pixels_per_meter(camera)))
                        if math.dist(point, tip) < .5:
                            # A vertical spore cone is a cross-section from above.
                            pygame.draw.circle(screen, (199, 180, 67), point, max(1, width//2))
                            continue
                        rotation = -math.degrees(math.atan2(tip[0]-point[0], point[1]-tip[1]))
                        if not self._draw_module_asset(screen, sim, camera, kind, point, rotation, scale):
                            pygame.draw.line(screen, (195, 174, 65), point, tip, width)
                    continue
                if kind in {'stem_section', 'branch_section'}:
                    projected = [self._path_screen(camera, p) for p in snapshot.placement_paths.get(str(index), [])]
                    width = max(1, round(2*scale*self._projection_pixels_per_meter(camera)))
                    if len(projected) >= 2:
                        if not self._draw_structural_asset_path(screen, sim, kind, projected, width):
                            pygame.draw.lines(screen, (75, 110, 45), False, projected, width)
                    continue
            if sim.blueprint.growth.get('terminal_rosette_version') or sim.blueprint.growth.get('offset_rosette_version'):
                if kind == 'leaf' and orientation.get('terminal_blade'):
                    from simulations.species.terminal_rosettes import draw_terminal_blade
                    path = snapshot.placement_paths.get(str(index), [])
                    draw_terminal_blade(screen, self._module_asset(sim, 'leaf'),
                        [self._path_screen(camera, p) for p in path],
                        orientation['blade_width_m']*self._projection_pixels_per_meter(camera),
                        orientation.get('retained_dead_leaf', False))
                    continue
                if kind in {'stem_section', 'branch_section'}:
                    path = snapshot.placement_paths.get(str(index), [])
                    projected = [self._path_screen(camera, p) for p in path]
                    width = max(1, round(2*scale*self._projection_pixels_per_meter(camera)))
                    if len(projected) >= 2:
                        if orientation.get('spent_axis') or not self._draw_structural_asset_path(screen, sim, kind, projected, width):
                            pygame.draw.lines(screen, (112, 97, 66) if orientation.get('spent_axis') else (100, 126, 83), False, projected, width)
                    continue
            if sim.blueprint.growth.get("shape") in {"tree", "shrub", "subshrub"}:
                if kind in {"stem_section", "branch_section", "root"}:
                    color = self._species_tint((126, 91, 62), f"{sim.species_id}:{kind}")
                # Flower/cone colour already comes from _color(). Keeping a
                # second tree/shrub-only override here used to turn every
                # unasseted angiosperm flower gold, while also risking a
                # future cone-colour mismatch between the two paths.
            elif sim.blueprint.growth.get("shape") == "aquatic":
                if kind in {"stem_section", "branch_section", "root"}:
                    color = self._species_tint((53, 117, 126), f"{sim.species_id}:{kind}")
            elif sim.blueprint.growth.get("shape") == "succulent":
                if kind in {"stem_section", "branch_section", "root"}:
                    color = self._species_tint((117, 137, 73), f"{sim.species_id}:{kind}")
            if (
                kind == "branch_section"
                and float(z) < 0.0
                and "rhizome" in {
                    str(item).lower().replace("-", "_").replace(" ", "_")
                    for item in (sim.blueprint.growth.get("belowground_storage") or [])
                }
            ):
                color = (126, 91, 62)
            if kind in {"flower", "fruit"}:
                if sim.blueprint.growth.get('tufted_sedge_version') and orientation.get('forward'):
                    # Spikelet bunches follow their 3D ray in every view.
                    tip = self._path_screen(camera, [placement[2+q]+orientation['forward'][q]*.02 for q in range(3)])
                    if math.dist(point, tip) > .01:
                        rotation = -math.degrees(math.atan2(tip[0]-point[0],point[1]-tip[1]))
                # Deferred and drawn after the foliage loop below, on the
                # same principle as renewal_overlays -- flower/fruit share
                # a shoot's terminal socket with its own foliage, and the
                # (now properly-sized, post-shoot-unit-fix) foliage sprite
                # drawn at the same point would otherwise paint over a
                # small reproductive-structure marker drawn first.
                if (kind == "flower" or (kind == "fruit" and (sim.blueprint.growth.get("clonal_forb_reproduction_version")
                                                              or sim.blueprint.growth.get("umbellate_head_version") or sim.blueprint.growth.get("basal_subshrub_version")))) and sim.blueprint.growth.get("inflorescence_profile") and not sim.blueprint.growth.get("structural_raceme_version"):
                    # Follow the existing supporting axis in the current
                    # camera projection; no new simulation geometry/counts.
                    if 0 <= int(parent) < len(snapshot.placements):
                        host = snapshot.placements[int(parent)]
                        ancestor = int(host[1])
                        if 0 <= ancestor < len(snapshot.placements):
                            a = self._placement_screen(camera, snapshot.placements[ancestor])
                            b = self._placement_screen(camera, host)
                            if a and b and math.hypot(b[0]-a[0], b[1]-a[1]) > 0:
                                rotation = -math.degrees(math.atan2(b[0]-a[0], a[1]-b[1]))
                    if abs(rotation) < .001 and sim.blueprint.growth["inflorescence_profile"].get("bloom_sag"):
                        # Resolve exactly upright stems to either side using
                        # their stable socket index, rather than all one way.
                        rotation = .001 if index % 2 else -.001
                reproductive_overlays.append((kind, point, rotation, scale, color, index))
                continue
            parent_point = None
            if int(parent) >= 0 and int(parent) < len(snapshot.placements):
                parent_point = self._placement_screen(camera, snapshot.placements[int(parent)])
            if kind in {'stem_section','branch_section'} and orientation.get('structural_socket_m') is not None:
                parent_point = self._path_screen(camera,orientation['structural_socket_m'])
            if sim.blueprint.growth.get('moss_turf_version') and kind in {'stem_section','branch_section'}:
                # Independent shoots start at a substrate socket, not another
                # placement. Their explicit path also avoids drawing a side
                # branch back to its parent's tip in top/side projections.
                points = [self._path_screen(camera,p) for p in snapshot.placement_paths.get(str(index),[])]
                if len(points) >= 2:
                    width = max(1,round(2*sim.blueprint.module(kind).radius_m*self._projection_pixels_per_meter(camera)))
                    if not self._draw_structural_asset_path(screen,sim,kind,points,width):
                        pygame.draw.lines(screen,color,False,points,width)
                continue
            if kind in {"stem_section", "branch_section", "root_section", "root_support"} and parent_point:
                path = getattr(snapshot, "placement_paths", {}).get(str(index), [])
                path_points = [parent_point]
                path_points.extend(self._path_screen(camera, path_point) for path_point in path)
                if (kind == 'stem_section' and path
                        and (sim.blueprint.growth.get('columnar_profile') or {}).get('axis_layout') == 'basal_clump'):
                    # Basal cactus offshoots attach to one underground crown,
                    # but only their upright stem paths are exposed tissue.
                    path_points = [self._path_screen(camera, path_point) for path_point in path]
                if (sim.blueprint.growth.get("woody_graminoid_grammar_version")
                        and (getattr(snapshot, "placement_orientations", {}).get(str(index)) or {}).get("axis_origin")
                        and path):
                    path_points = [self._path_screen(camera, path_point) for path_point in path]
                if not path:
                    path_points.append(point)
                if sim.blueprint.growth.get('columnar_version') and kind in {'stem_section','branch_section'}:
                    from simulations.species.columnar_succulents import draw_column
                    ppm=self._projection_pixels_per_meter(camera)
                    origin=self._path_screen(camera,(0.,0.,0.))
                    unit=[self._path_screen(camera,p) for p in ((1.,0.,0.),(0.,1.,0.),(0.,0.,1.))]
                    # Project the radius through the same camera as areoles.
                    # A sheared side view has x+1.8*y, so a flat screen-width
                    # radius otherwise leaves valid flowers outside its stem.
                    radius_x=scale*math.hypot(unit[0][0]-origin[0],unit[1][0]-origin[0])
                    radius_y=scale*math.sqrt(sum((p[1]-origin[1])**2 for p in unit))
                    draw_column(screen,self._module_asset(sim,kind),self._module_asset(sim,'leaf'),
                                path_points,radius_x,sim.blueprint.growth['columnar_profile'],ppm,
                                cap_radius_px=radius_y,
                                terminal=not any(p[0]=='stem_section' and p[1]==index for p in snapshot.placements))
                    continue
                line_width = max(1, int(3 * scale))
                if kind in {"stem_section", "branch_section"} and (sim.blueprint.growth.get("woody_graminoid_grammar_version") or sim.blueprint.growth.get("basal_fan_profile") or sim.blueprint.growth.get("emergent_rosette_version") or sim.blueprint.growth.get("clonal_forb_profile_version") or sim.blueprint.growth.get("creeping_woody_profile_version") or sim.blueprint.growth.get("creeping_herb_profile_version") or sim.blueprint.growth.get("dimorphic_herb_profile_version") or sim.blueprint.growth.get("woody_spur_version") or sim.blueprint.growth.get('rosette_raceme_version') or sim.blueprint.growth.get('lateral_rosette_scapes_version') or sim.blueprint.growth.get('sympodial_herb_version') or sim.blueprint.growth.get('paniculate_rosette_version') or sim.blueprint.growth.get('tufted_sedge_version') or sim.blueprint.growth.get('cyme_herb_version') or sim.blueprint.growth.get('mixed_tiller_version')):
                    module = sim.blueprint.module(kind)
                    line_width = max(1, round(2 * module.radius_m * scale * self._projection_pixels_per_meter(camera)))
                if kind in {"stem_section", "branch_section"} and (sim.blueprint.growth.get("shoot_distribution_grammar") or sim.blueprint.growth.get('cushion_version')):
                    # Metric trunk/branch radii must remain metric in close-ups.
                    # A fixed screen-width ceiling makes attached organisms
                    # appear to float outside the visible host wood.
                    line_width = max(1, min(2048, round(2 * scale * self._projection_pixels_per_meter(camera))))
                if kind in {"root_support", "root_section"}:
                    from simulations.species.root_visuals import root_segment_style, draw_root_segment
                    maturity = float(snapshot.stats.get("maturity", 1.))
                    radius, color = root_segment_style(sim.blueprint.growth, placement, maturity)
                    parent_placement = snapshot.placements[int(parent)]
                    if parent_placement[0] == kind and parent_placement[7] == level:
                        start_radius, _ = root_segment_style(sim.blueprint.growth, parent_placement, maturity)
                    else:
                        start_radius = radius * 1.22
                    ppm = self._projection_pixels_per_meter(camera)
                    # An explicitly authored root asset takes precedence over
                    # the tissue-style fallback, with the corrected diameter.
                    if self._draw_structural_asset_path(screen, sim, kind, [parent_point, point],
                                                        max(1, round(2*radius*ppm))):
                        continue
                    draw_root_segment(screen, parent_point, point, start_radius, radius, color, ppm)
                    continue
                texture_cache_key, texture = self._module_texture(sim, kind)
                variant_key = None
                if texture is not None and texture.variants:
                    if texture_cache_key not in texture_sequences:
                        sequence_seed = int(sim.seed) + sum(ord(char) for char in str(texture.texture_id or texture_cache_key))
                        texture_sequences[texture_cache_key] = texture.shuffled_variant_keys(max(64, len(snapshot.placements)), sequence_seed)
                        texture_slots[texture_cache_key] = 0
                    sequence = texture_sequences[texture_cache_key]
                    slot = texture_slots[texture_cache_key]
                    variant_key = sequence[slot % len(sequence)] if sequence else None
                    texture_slots[texture_cache_key] = slot + 1
                structural_asset = self._draw_structural_asset_path(screen, sim, kind, path_points, line_width)
                textured = False if structural_asset else self._draw_textured_path(
                    screen, texture_cache_key, texture, variant_key, path_points, line_width,
                    physical_width=bool(sim.blueprint.growth.get("shoot_distribution_grammar"))
                )
                if not structural_asset and not textured:
                    pygame.draw.lines(screen, color, False, path_points, line_width)
            elif (
                kind == "leaf"
                and connected_graminoid_leaves
                and parent_point
                and bool(getattr(snapshot, "placement_paths", {}).get(str(index), []))
            ):
                path = getattr(snapshot, "placement_paths", {}).get(str(index), [])
                basal_tuft_path = sim.blueprint.growth.get("leaf_attachment_pattern") in {
                    "basal",  # compatibility with older experimental fixtures
                    "basal_tuft",
                }
                path_points = [] if basal_tuft_path else [parent_point]
                path_points.extend(self._path_screen(camera, path_point) for path_point in path)
                if not path:
                    path_points.append(point)
                leaf_module = sim.blueprint.module("leaf")
                radius_m = getattr(leaf_module, "radius_m", .012) if leaf_module else .012
                radius_m = .012 if radius_m is None else float(radius_m)
                half_width = radius_m * self._projection_pixels_per_meter(camera) * max(0., float(scale))
                if sim.blueprint.growth.get('tufted_sedge_version') or sim.blueprint.growth.get('mixed_tiller_version'):
                    from simulations.species.tufted_sedges import draw_blade_asset
                    if draw_blade_asset(screen,self._module_asset(sim,'leaf'),path_points,half_width):
                        continue
                draw_blade(screen, path_points, half_width, color)
            elif kind == "leaf":
                if sim.blueprint.growth.get('moss_turf_version'):
                    from simulations.species.moss_turfs import draw_moss_leaf
                    moss_points = [self._path_screen(camera, p) for p in snapshot.placement_paths.get(str(index), [])]
                    width = sim.blueprint.module('leaf').radius_m * self._projection_pixels_per_meter(camera) * scale
                    if draw_moss_leaf(screen, self._module_asset(sim, 'leaf'), moss_points, width,
                                      orientation.get('moss_blade_fraction', 1.)):
                        continue
                if orientation.get('leaf_role')=='cyme_bract':
                    from simulations.species.cyme_herbs import draw_cyme_bract
                    length=sim.blueprint.module('leaf').length_m*scale
                    tip=self._path_screen(camera,[placement[2+q]+orientation['forward'][q]*length for q in range(3)])
                    width=orientation['width_m']*self._projection_pixels_per_meter(camera)
                    forward=orientation['forward']
                    horizontal=math.hypot(forward[0],forward[1])
                    right=(-forward[1]/max(horizontal,1e-9),forward[0]/max(horizontal,1e-9),0.)
                    edge=self._path_screen(camera,[placement[2+q]+right[q]*orientation['width_m']*.5 for q in range(3)])
                    transverse=(edge[0]-point[0],edge[1]-point[1])
                    rim=self._path_screen(camera,[placement[2],placement[3],placement[4]+length*.18])
                    cup_offset=(rim[0]-point[0],rim[1]-point[1])
                    if draw_cyme_bract(screen,self._module_asset(sim,'leaf'),point,tip,width,transverse,cup_offset):continue
                if sim.blueprint.growth.get('cyme_herb_version') and orientation.get('leaf_role') in {'cauline_leaf','involucral_leaf'}:
                    from simulations.species.floating_leaves import draw_planar_leaf
                    surface=self._module_asset(sim,'leaf')
                    if surface is not None:
                        module=sim.blueprint.module('leaf')
                        length=module.length_m*scale
                        bounds=surface.get_bounding_rect()
                        if length>0 and bounds.height>0 and bounds.width>0:
                            # Preserve artwork and its attachment, but honor the
                            # authored blade width rather than the square canvas.
                            target_width=max(1,round(surface.get_width()*orientation['width_m']/length*bounds.height/bounds.width))
                            surface=pygame.transform.scale(surface,(target_width,surface.get_height()))
                            forward=orientation['forward']
                            horizontal=math.hypot(forward[0],forward[1])
                            normal=(-forward[2]*forward[0]/max(horizontal,1e-9),
                                    -forward[2]*forward[1]/max(horizontal,1e-9),horizontal)
                            draw_planar_leaf(screen,surface,camera,placement[2:5],forward,normal,length,module.attachment_point)
                            continue
                if orientation.get("planar_leaf"):
                    from simulations.species.floating_leaves import draw_planar_leaf
                    surface = self._module_asset(sim, "leaf")
                    leaf_module = sim.blueprint.module("leaf")
                    if surface is None:
                        surface = pygame.Surface((75, 75), pygame.SRCALPHA)
                        pygame.draw.ellipse(surface, color, (15, 3, 45, 68))
                    draw_planar_leaf(screen, surface, camera, placement[2:5], orientation["forward"],
                                     orientation["normal"], leaf_module.length_m * scale,
                                     leaf_module.attachment_point,width_m=orientation.get('width_m'))
                    continue
                if orientation.get("floating_leaf"):
                    from simulations.species.floating_leaves import draw_floating_leaf
                    surface = self._module_asset(sim, "leaf")
                    leaf_module = sim.blueprint.module("leaf")
                    if surface is None:
                        surface = pygame.Surface((75, 75), pygame.SRCALPHA)
                        pygame.draw.circle(surface, color, (37, 37), 33)
                        pygame.draw.polygon(surface, (0, 0, 0, 0), [(37, 40), (29, 74), (46, 74)])
                    draw_floating_leaf(screen, surface, camera, placement[2:5], orientation["forward"],
                                       leaf_module.length_m * scale, leaf_module.attachment_point)
                    continue
                asset_rotation = rotation
                asset_scale = scale
                asset_width_scale = float(leaf_development.get(index, {}).get("width_scale", 1.0))
                if (sim.blueprint.growth.get("leaf_attachment_pattern") == "basal_rosette"
                        or sim.blueprint.growth.get("rosette_shoot_grammar_version")
                        or sim.blueprint.growth.get("forb_leaf_placement_version")
                        or sim.blueprint.growth.get("leaf_attachment_angle_version")
                        or sim.blueprint.growth.get("woody_graminoid_grammar_version")
                        or sim.blueprint.growth.get("woody_spur_version")
                        or sim.blueprint.growth.get("shrub_fascicle_grammar_version")
                        or sim.blueprint.growth.get("basal_fan_profile")):
                    if sim.blueprint.growth.get("leaf_attachment_pattern") == "basal_rosette":
                        asset_width_scale = self._rosette_leaf_width_scale(camera, placement, point)
                    orientation = (getattr(snapshot, "placement_orientations", {}) or {}).get(str(index)) or {}
                    forward = orientation.get("forward") or []
                    if len(forward) >= 3:
                        origin = placement[2:5]
                        target = [
                            float(origin[0]) + float(forward[0]),
                            float(origin[1]) + float(forward[1]),
                            float(origin[2]) + float(forward[2]),
                        ]
                        projected = self._placement_screen(
                            camera,
                            ["leaf_extent", -1, target[0], target[1], target[2], rotation, scale, 0],
                        )
                        if projected is not None:
                            dx, dy = float(projected[0]) - float(point[0]), float(projected[1]) - float(point[1])
                            if abs(dx) + abs(dy) > 1e-6:
                                asset_rotation = math.degrees(math.atan2(dx, -dy))
                                if (sim.blueprint.growth.get("forb_leaf_placement_version")
                                        or sim.blueprint.growth.get("leaf_attachment_angle_version")
                                        or sim.blueprint.growth.get("woody_graminoid_grammar_version")
                                        or sim.blueprint.growth.get("woody_spur_version")
                                        or sim.blueprint.growth.get("shrub_fascicle_grammar_version")
                                        or sim.blueprint.growth.get("basal_fan_profile")):
                                    # Pygame rotates anticlockwise; projected
                                    # rightward blades need a negative roll.
                                    asset_rotation = -asset_rotation
                                    asset_scale *= math.hypot(dx, dy) / max(
                                        .001, self._projection_pixels_per_meter(camera))
                if not self._draw_module_asset(
                    screen, sim, camera, "leaf", point, asset_rotation, asset_scale,
                    width_scale=asset_width_scale,
                ):
                    self._draw_fallback_leaf(screen, sim, camera, snapshot, index, point, rotation, scale, color=color,
                                             width_scale=asset_width_scale)
            elif kind == "root":
                if snapshot.stats.get("root_segment_count", 0):
                    # The connected roots form the collar; a fixed disc would
                    # dwarf fine grass roots in a close-up.
                    continue
                pygame.draw.circle(screen, color, point, max(3, int(6 * scale)))
            else:
                if not self._draw_module_asset(screen, sim, camera, kind, point, rotation, scale):
                    pygame.draw.circle(screen, color, point, max(2, int(5 * scale)))

        # Roots originate at the renewal body, so draw that body over their
        # attachment points instead of letting thick first-order roots hide it.
        for kind, point, scale in renewal_overlays:
            self._draw_renewal_module(screen, sim, camera, kind, point, scale)

        # Sample represented foliage without adding simulation entities.
        clusters = getattr(snapshot, "leaf_clusters", None)
        if not roots_only and not skeleton and clusters and snapshot.lod >= 1:
            dense_canopy = len(clusters) > 200
            # A conifer's true placement unit is one needle -- but a mature
            # tree carries thousands to millions of them, so sampling many
            # individual needle sprites per shoot (the else-branch below)
            # doesn't scale and still reads as a sparse scatter rather than
            # foliage. For needle/scale foliage, the smallest *visual* unit
            # instead becomes the needle-clad shoot itself: one sprite (a
            # small foliated twig, not a lone needle -- see
            # Plant_Design_Process.md §6g) stretched/rotated to that one
            # shoot's own length/angle, the same "one placement, one draw"
            # principle stem/branch segments already use.
            needle_foliage = str(sim.blueprint.growth.get("leaf_structure") or "") in {"needle_like", "scale_like"}
            for cluster in clusters:
                if cluster.get("estimated_leaf_count") == 0:
                    continue
                if visible_indices is not None and int(cluster.get("host_placement_index",-1)) not in visible_indices:
                    continue
                if cluster.get("dense_shoot_envelope"):
                    host_index = int(cluster.get("host_placement_index", -1) or -1)
                    if 0 <= host_index < len(snapshot.placements):
                        host = snapshot.placements[host_index]
                        parent_index = int(host[1])
                        if 0 <= parent_index < len(snapshot.placements):
                            parent_point = self._placement_screen(camera, snapshot.placements[parent_index])
                            host_point = self._placement_screen(camera, host)
                            if parent_point is not None and host_point is not None:
                                path = getattr(snapshot, "placement_paths", {}).get(str(host_index), [])
                                path_points = [parent_point]
                                path_points.extend(self._path_screen(camera, point) for point in path)
                                if not path:
                                    path_points.append(host_point)
                                path_points = [point for point in path_points if point is not None]
                                if len(path_points) >= 2:
                                    pixels_per_meter = self._projection_pixels_per_meter(camera)
                                    leaf_length_m = max(
                                        0.001,
                                        float(cluster.get("leaf_length_m", 0.005) or 0.005),
                                    )
                                    # The sleeve diameter is approximately two
                                    # projecting leaf lengths plus the fine stem.
                                    fine = self._pixel_scale(camera)
                                    envelope_width = max(1, min(round(80 * fine), round(leaf_length_m * pixels_per_meter * 1.65)))
                                    leaf_color = self._color("leaf", sim, host_index)
                                    leaf_surface = self._module_asset(sim, "leaf")
                                    if leaf_surface is not None:
                                        # Aggregate foliage must share the approved
                                        # organ palette, not a generic conifer tint.
                                        palette_key = leaf_surface
                                        if palette_key not in self._asset_color_cache:
                                            if len(self._asset_color_cache) >= 32:
                                                self._asset_color_cache.clear()
                                            pixels = [leaf_surface.get_at((px,py))
                                                      for py in range(leaf_surface.get_height())
                                                      for px in range(leaf_surface.get_width())
                                                      if leaf_surface.get_at((px,py)).a]
                                            self._asset_color_cache[palette_key] = tuple(
                                                round(sum(c[i] for c in pixels)/len(pixels)) for i in range(3)
                                            ) if pixels else leaf_color
                                        leaf_color = self._asset_color_cache[palette_key]
                                    envelope_color = tuple(
                                        max(0, round(channel * 0.78)) for channel in leaf_color
                                    )
                                    # This is an optical cue only when leaves
                                    # are subpixel. A close-up must reveal the
                                    # individual organs, not an opaque tube --
                                    # unless the camera keeps the mass at every
                                    # scale (a BioSim picture painted at the
                                    # view's size: its samples sit on top).
                                    if leaf_length_m * pixels_per_meter / fine < 3.0:
                                        pygame.draw.lines(screen, envelope_color, False, path_points, envelope_width)
                                        pygame.draw.circle(screen, envelope_color, path_points[-1], max(1,envelope_width//2))

                                    # Restore the explicit leaf samples above
                                    # the collective sleeve so close views
                                    # retain individual organ structure.
                                    for leaf_index in cluster.get("sample_placement_indices", []):
                                        if not (0 <= int(leaf_index) < len(snapshot.placements)):
                                            continue
                                        leaf = snapshot.placements[int(leaf_index)]
                                        leaf_point = self._placement_screen(camera, leaf)
                                        if leaf_point is None:
                                            continue
                                        if not self._draw_module_asset(
                                            screen,
                                            sim,
                                            camera,
                                            "leaf",
                                            leaf_point,
                                            float(leaf[5]),
                                            float(leaf[6]),
                                        ):
                                            self._draw_fallback_leaf(
                                                screen,
                                                sim,
                                                camera,
                                                snapshot,
                                                int(leaf_index),
                                                leaf_point,
                                                float(leaf[5]),
                                                float(leaf[6]),
                                                color=self._color("leaf", sim, int(leaf_index)),
                                                rotation_only=True,
                                            )
                if cluster.get("explicit_samples"):
                    continue
                if cluster.get('pendant_branchlet_sites_m'):
                    from simulations.species.pendant_branchlets import draw_pendant_cohort
                    draw_pendant_cohort(self,screen,sim,camera,cluster,foliage_sample_cap)
                    continue
                if cluster.get('planar_spray'):
                    from simulations.species.planar_sprays import draw_planar_spray
                    draw_planar_spray(self,screen,sim,camera,cluster,foliage_sample_cap)
                    continue
                estimated = int(cluster.get("estimated_leaf_count", 1) or 1)
                if estimated <= 1:
                    continue
                position = cluster.get("position_m") or [0.0, 0.0, 0.0]
                if len(position) < 3:
                    continue
                x, y, z = (float(position[0]), float(position[1]), float(position[2]))
                host_index = int(cluster.get("host_placement_index", -1) or -1)
                spray_radius = float(cluster.get("foliage_spray_radius_m", 0.0) or 0.0)
                if spray_radius > 0:
                    # A bounded cohort footprint keeps subpixel broadleaf
                    # sprays visible in BioSim. At close range, sample the
                    # actual leaf asset across the same volume instead; a
                    # camera that keeps the mass at every scale (BioSim at the
                    # view's own size) draws both, the samples on top: the
                    # samples alone are a few leaves of a cohort of hundreds.
                    leaf_module = sim.blueprint.module("leaf")
                    ppm = self._projection_pixels_per_meter(camera)
                    if leaf_module and leaf_module.length_m * ppm / self._pixel_scale(camera) < 3.0:
                        center = self._path_screen(camera, (x, y, z))
                        if center is not None:
                            radius_px = max(round(self._pixel_scale(camera)), round(spray_radius * ppm))
                            color = self._color("leaf", sim, host_index)
                            for lobe in range(5):
                                a = lobe * 2.39996 + float(cluster.get("identity", 0)) * .07
                                dx = round(math.cos(a) * radius_px * .45)
                                dy = round(math.sin(a) * radius_px * .32)
                                shade = .72 + .055 * lobe
                                tone = tuple(round(c * shade) for c in color)
                                pygame.draw.ellipse(screen, tone,
                                    (round(center[0])+dx-radius_px, round(center[1])+dy-round(radius_px*.7),
                                     radius_px*2, max(2, round(radius_px*1.4))))
                host = snapshot.placements[host_index] if 0 <= host_index < len(snapshot.placements) else None
                host_angle = float(host[5]) if host is not None and len(host) > 5 else 0.0
                host_scale = float(host[6]) if host is not None and len(host) > 6 else 1.0
                density = max(0.0, min(1.0, float(cluster.get("visual_density", 0.6) or 0.6)))
                if needle_foliage and cluster.get("shoot_type"):
                    leaf_module = sim.blueprint.module("leaf")
                    module_length = max(0.01, float(getattr(leaf_module, "length_m", 0.1) or 0.1))
                    shoot_length = float(cluster.get("length", module_length) or module_length)
                    shoot_rotation = math.degrees(float(cluster.get("angle", 0.0) or 0.0))
                    if cluster.get("shoot_role") == "leader":
                        start_point = self._path_screen(camera, cluster["shoot_start_m"])
                        end_point = self._path_screen(camera, cluster["shoot_end_m"])
                        if start_point is not None and end_point is not None:
                            shoot_rotation = math.degrees(math.atan2(
                                -(end_point[0] - start_point[0]), -(end_point[1] - start_point[1])))
                    visual_positions = cluster.get("visual_positions_m") or [(x, y, z)]
                    if foliage_sample_cap is not None:
                        visual_positions = visual_positions[:max(0, int(foliage_sample_cap))]
                    sprite_scale_factor = max(0.68, len(visual_positions) ** -0.5) if visual_positions else 1.0
                    for visual_index, visual_position in enumerate(visual_positions):
                        if len(visual_position) < 3:
                            continue
                        sample_point = self._path_screen(camera, tuple(float(value) for value in visual_position[:3]))
                        if sample_point is None:
                            continue
                        # One sprite now stands in for a whole needle-clad
                        # shoot (previously 18-36 individual-needle blits
                        # per cluster -- see the else-branch below), so it
                        # has to be sized as a visual unit. The module's
                        # metric length stays at single-needle scale for
                        # structural formulas, while this draw uses a bounded
                        # shoot size that shrinks with the BioSim pixel cap.
                        try:
                            pixels_per_meter = abs(
                                camera.world_to_screen((1.0, 0.0))[0] - camera.world_to_screen((0.0, 0.0))[0]
                            )
                        except (TypeError, IndexError):
                            pixels_per_meter = 64.0
                        pixel_cap = max(1.0, float(getattr(camera, "sprite_height_cap", 220) or 220))
                        cap_scale = max(0.45, min(1.0, math.sqrt(pixel_cap / 220.0)))
                        target_px = (max(7.0, min(26.0, 12.0 * (shoot_length / 0.09) ** 0.5))
                                     * sprite_scale_factor * cap_scale * self._pixel_scale(camera))
                        shoot_scale = max(0.3, target_px / max(1e-6, module_length * max(1e-6, pixels_per_meter)))
                        rotation = shoot_rotation + (-5.0 if visual_index % 2 else 5.0)
                        if not self._draw_module_asset(screen, sim, camera, "leaf", sample_point, rotation,
                                                       shoot_scale, unit_length_px=target_px):
                            # _draw_fallback_leaf's needle-line shape sizes
                            # its *length* from the single-needle
                            # module.length_m too (same collapse-at-zoom
                            # issue as above), while its width has its own
                            # floor -- at whole-tree zoom the line collapses
                            # to a blob instead of a needle. A small filled
                            # marker sized directly to target_px reads
                            # correctly as one shoot-sized clump without
                            # depending on that per-needle formula.
                            pygame.draw.circle(
                                screen, self._color("leaf", sim, host_index * 64 + visual_index),
                                (round(sample_point[0]), round(sample_point[1])),
                                max(2, round(target_px * 0.32)),
                            )
                    continue
                sample_draws = 2 if dense_canopy else max(1, min(4, int(round(density * 4.0))))
                # Dense-canopy blobs are drawn larger so a handful of blits
                # per cluster still reads as full foliage rather than a
                # sparse scatter of dots.
                blob_scale = max(0.42, min(1.35, host_scale * (0.9 if dense_canopy else 0.64)))
                shoot = cluster.get("shoot_type")
                if shoot:
                    fascicle_size = max(0, int(cluster.get("fascicle_size", 0) or 0))
                    if fascicle_size:
                        # Density selects how many real bundle sockets to
                        # sample, never how many needles belong to a bundle.
                        fascicle_draws = min(
                            int(cluster.get("fascicle_count", 1) or 1),
                            max(1, round(2 + 4 * density)),
                        )
                        sample_draws = min(estimated, fascicle_size * fascicle_draws)
                    else:
                        sample_draws = min(estimated, 18 + round(density * 18))
                        compound_tree = (
                            sim.blueprint.growth.get("growth_form") == "tree"
                            and sim.blueprint.growth.get("leaf_structure") in {
                                "pinnately_compound", "palmately_compound",
                            }
                        )
                        if compound_tree:
                            # A cohort can represent dozens of compound leaves.
                            # Sample that cohort without enlarging each leaf;
                            # the landscape's explicit lower budget still wins.
                            sample_draws = min(estimated, 64, 18 + round(density * 46))
                    leaf_module = sim.blueprint.module("leaf")
                    leaf_length = leaf_module.length_m if leaf_module else .1
                    blob_scale = .85
                if foliage_sample_cap is not None:
                    sample_draws = min(sample_draws, max(0, int(foliage_sample_cap)))
                for sample_index in range(sample_draws):
                    sample_angle = host_angle + sample_index * 137.5 + 34.0
                    sample_rotation = sample_angle + (180.0 if sample_index % 2 else 0.0)
                    radius = 0.018 + 0.010 * (sample_index % 2)
                    radians = math.radians(sample_angle)
                    sample_x = x + math.cos(radians) * radius
                    sample_y = y + math.sin(radians) * radius
                    sample_z = z + (0.012 if sample_index % 2 else -0.006)
                    if shoot:
                        # Distribute along the shoot and around its leaf-bearing volume.
                        azimuth = float(cluster.get("angle", 0.))
                        fascicle_size = max(0, int(cluster.get("fascicle_size", 0) or 0))
                        if fascicle_size:
                            fascicle_index = sample_index // fascicle_size
                            needle_index = sample_index % fascicle_size
                            fascicle_draws = max(1, math.ceil(sample_draws / fascicle_size))
                            along = (fascicle_index / max(1, fascicle_draws - 1) - .5) * float(cluster.get("length", .2))
                            sample_x = x + math.cos(azimuth) * along
                            sample_y = y + math.sin(azimuth) * along
                            sample_z = z + (fascicle_index % 2) * leaf_length * .08
                            centre_rotation = math.degrees(azimuth) - 18.0
                            sample_rotation = centre_rotation + (needle_index - (fascicle_size - 1) * .5) * 11.0
                        else:
                            along = (sample_index / max(1, sample_draws-1) - .5) * float(cluster.get("length", .2))
                            spread = leaf_length * (0.7 + .7 * density) * math.sqrt((sample_index % 7 + 1) / 7)
                            if spray_radius > 0:
                                spread = spray_radius * math.sqrt((sample_index % 11 + 1) / 11)
                            if (sim.blueprint.growth.get("growth_form") == "tree"
                                    and sim.blueprint.growth.get("leaf_structure") in {
                                        "pinnately_compound", "palmately_compound",
                                    }):
                                # Spread the represented leaves through their
                                # foliage volume, rather than packing a large
                                # cohort into a single-leaf-width tuft. This
                                # changes display samples only, never biomass.
                                spread *= min(3.0, math.sqrt(max(1, estimated) / 18.0))
                            sample_x = x + math.cos(azimuth)*along + math.cos(radians)*spread
                            sample_y = y + math.sin(azimuth)*along + math.sin(radians)*spread
                            sample_z = z + math.sin(radians*1.7)*spread
                        if cluster.get("shoot_role") == "leader":
                            start, end = cluster["shoot_start_m"], cluster["shoot_end_m"]
                            # Keep the apex even at the landscape's one-leaf
                            # draw budget, then sample back along the leader.
                            fraction = 1. if sample_index == 0 else (sample_index - 1) / max(1, sample_draws - 2)
                            spread = leaf_length * (.7 + .7 * density)
                            sample_x = start[0] + (end[0] - start[0]) * fraction + math.cos(radians) * spread
                            sample_y = start[1] + (end[1] - start[1]) * fraction + math.sin(radians) * spread
                            sample_z = start[2] + (end[2] - start[2]) * fraction
                    sample_point = self._path_screen(camera, (sample_x, sample_y, sample_z))
                    if sample_point is None:
                        continue
                    sample_scale = blob_scale if dense_canopy or shoot else max(0.42, min(0.82, host_scale * 0.64))
                    if not self._draw_module_asset(screen, sim, camera, "leaf", sample_point, sample_rotation, sample_scale):
                        self._draw_fallback_leaf(
                            screen, sim, camera, snapshot, host_index if host_index >= 0 else 0,
                            sample_point, sample_rotation, sample_scale,
                            color=self._color("leaf", sim, host_index * 64 + sample_index),
                            rotation_only=True,
                        )

        # Flower/fruit draw last (on top of foliage) -- see the deferral
        # comment above; otherwise a shoot's own foliage sprite, drawn at
        # the same point, paints over its small reproductive-structure
        # marker.
        if not roots_only and not skeleton:
            self._draw_bloom_cohorts(screen,sim,camera,snapshot,visible_indices)
            overlays = (reproductive_overlays if (sim.blueprint.growth.get('offset_rosette_version') or sim.blueprint.growth.get('terminal_rosette_version') or sim.blueprint.growth.get('paniculate_rosette_version') or sim.blueprint.growth.get('tufted_sedge_version') or sim.blueprint.growth.get('cyme_herb_version') or sim.blueprint.growth.get('woody_spur_version'))
                        else self._sample_reproductive_overlays(reproductive_overlays))
            for kind, point, rotation, scale, color, organ_index in overlays:
                from simulations.species.pendant_reproduction import pendant_display_units
                units = pendant_display_units(sim.blueprint.growth, snapshot.placements[organ_index],
                                              sim.blueprint.module(kind),sim.seed)
                if units:
                    for pendant in units:
                        anchor = self._path_screen(camera, pendant[0])
                        if anchor is None:
                            continue
                        profile = sim.blueprint.growth["reproductive_profile"]["pendant_display"]
                        width = max(1, min(32, round(2 * profile["stalk_radius_m"]
                                                  * self._projection_pixels_per_meter(camera) * max(.55, scale))))
                        pygame.draw.line(screen, profile["stalk_color"], point, anchor, width)
                        if not self._draw_module_asset(screen, sim, camera, kind, anchor, 180., scale):
                            self._draw_reproductive_fallback(screen, sim, camera, kind, anchor, 180., scale, color,
                                                             variant_seed=int(sim.seed) + organ_index * 7919)
                    continue
                if not self._draw_module_asset(screen, sim, camera, kind, point, rotation, scale):
                    self._draw_reproductive_fallback(screen, sim, camera, kind, point, rotation, scale, color,
                                                     variant_seed=int(sim.seed) + organ_index * 7919)

        if show_height_reference:
            self._draw_height_reference(screen, sim, camera)

    def _draw_gallery(self, screen, sim):
        cases = sim.get_growth_gallery_cases()
        width, height = screen.get_size()
        header_height = 76
        footer_height = 136
        columns = 4
        cell_width = max(180, width // columns)
        cell_height = max(96, (height - header_height - footer_height) // 5)
        screen.fill((13, 18, 17))
        title_font = get_font(20)
        font = get_font(11)
        small = get_font(10)
        display_name = sim.blueprint.display_name
        screen.blit(title_font.render(f"Species Sim growth gallery — {display_name}", True, (230, 238, 232)), (14, 36))
        screen.blit(font.render("20 individuals • 4 seeds per maturity stage • same species assets", True, (157, 181, 169)), (14, 60))
        stage_colors = {
            "seedling": (126, 169, 208),
            "juvenile": (119, 181, 112),
            "mature": (197, 181, 94),
            "reproductive": (219, 147, 92),
            "senescent": (167, 133, 145),
        }
        for case in cases:
            col = (case.index - 1) % columns
            row = (case.index - 1) // columns
            x, y = col * cell_width, header_height + row * cell_height
            cell = pygame.Surface((cell_width, cell_height))
            bounds = diagnostic_cell_bounds(case.snapshot)
            camera = DiagnosticCamera(cell_width, cell_height, bounds)
            self._draw_individual(cell, case.simulation, camera=camera)
            screen.blit(cell, (x, y))
            pygame.draw.rect(screen, stage_colors.get(case.stage, (130, 150, 140)), (x, y, cell_width, cell_height), 1)
            record = case.record()
            screen.blit(font.render(f"#{case.index:02} {case.stage} • seed {case.seed}", True, (236, 241, 237)), (x + 6, y + 5))
            screen.blit(small.render(
                f"{case.age_days:>3.0f}d • {float(record['maturity']) * 100:>3.0f}% • {record['life_phase']}",
                True, (201, 215, 205)), (x + 6, y + 20))
            screen.blit(small.render(
                f"seg {record['stem_count']:>2} • br {record.get('branch_count', 0):>2} • "
                f"cl {record.get('leaf_cluster_count', 0):>2} • est leaves {record.get('estimated_leaf_count', 0):>3}",
                True, (159, 183, 170)), (x + 6, y + 35))

    def _draw_forest(self, screen, sim):
        from simulations.species.forest_renderer import draw_forest
        # Match the other diagnostic views' reserved application toolbelt.
        panel = pygame.Surface((screen.get_width(), max(400, screen.get_height()-136)))
        draw_forest(self, panel, sim)
        screen.fill((15,22,19))
        screen.blit(panel,(0,0))

    def _draw_top_down(self, screen, sim):
        width, height = screen.get_size()
        footer_height = 136
        header_height = 82
        panel_height = max(160, height - header_height - footer_height)
        panel = pygame.Surface((width, panel_height))
        panel.fill((18, 23, 20))
        bounds = top_down_diagnostic_bounds(sim)
        camera = TopDownDiagnosticCamera(panel.get_width(), panel.get_height(), bounds)

        # A quiet metre grid makes the crown footprint legible without
        # replacing the actual model geometry with a diagram.
        grid_step = 10 ** math.floor(math.log10(max(0.01, 80.0 / camera.scale)))
        first_x = math.floor(bounds[0] / grid_step) * grid_step
        first_y = math.floor(bounds[2] / grid_step) * grid_step
        x = first_x
        while x <= bounds[1] + grid_step:
            start = camera.world_to_screen((x, bounds[2] - grid_step))
            end = camera.world_to_screen((x, bounds[3] + grid_step))
            pygame.draw.line(panel, (29, 38, 33), start, end, 1)
            x += grid_step
        y = first_y
        while y <= bounds[3] + grid_step:
            start = camera.world_to_screen((bounds[0] - grid_step, y))
            end = camera.world_to_screen((bounds[1] + grid_step, y))
            pygame.draw.line(panel, (29, 38, 33), start, end, 1)
            y += grid_step

        above_ground = canopy_visible_indices(sim,sim.render_snapshot)
        self._draw_individual(
            panel, sim, camera=camera, clear=False, visible_indices=above_ground,
            draw_ground_line=False,
        )

        screen.fill((13, 18, 17))
        screen.blit(panel, (0, header_height))
        title = get_font(22)
        font = get_font(13)
        screen.blit(title.render(f"Top-down | {sim.blueprint.display_name}", True, (230, 238, 232)), (18, 28))
        screen.blit(font.render("Orthographic crown view • same 3D growth snapshot", True, (157, 181, 169)), (18, 59))

        north_x = width - 38
        pygame.draw.line(screen, (205, 216, 199), (north_x, 63), (north_x, 34), 2)
        pygame.draw.polygon(screen, (205, 216, 199), ((north_x, 29), (north_x - 5, 38), (north_x + 5, 38)))
        north = font.render("N", True, (205, 216, 199))
        screen.blit(north, (north_x - north.get_width() // 2, 64))

        scale_width = max(1, round(grid_step * camera.scale))
        scale_y = header_height + panel_height - 18
        pygame.draw.line(screen, (211, 211, 181), (20, scale_y), (20 + scale_width, scale_y), 2)
        screen.blit(font.render(f"{grid_step:g} m", True, (211, 211, 181)), (20, scale_y - 20))

    def _draw_tree_architecture(self, screen, sim):
        """Three authored deciduous trees, front and top, at shared scales."""

        cases = sim.get_tree_architecture_cases()
        width, height = screen.get_size()
        screen.fill((13, 18, 17))
        title = get_font(22)
        font = get_font(13)
        small = get_font(11)
        screen.blit(title.render("Tree patterns | intrinsic architecture", True, (230, 238, 232)), (18, 24))
        screen.blit(font.render(
            "Matched maturity • seed 303 • shared physical scale • no seasonal or water forcing",
            True, (157, 181, 169)), (18, 54))
        if not cases:
            screen.blit(font.render("The comparison species are unavailable in the live ontology.", True,
                                    (220, 198, 174)), (18, 100))
            return

        columns = len(cases)
        cell_width = max(180, width // columns)
        header_height = 112
        footer_height = 145
        row_height = max(145, (height - header_height - footer_height) // 2)

        def shared(values):
            return (
                min(value[0] for value in values), max(value[1] for value in values),
                min(value[2] for value in values), max(value[3] for value in values),
            )

        front_bounds = shared([diagnostic_cell_bounds(case.render_snapshot) for case in cases])
        top_bounds = shared([top_down_diagnostic_bounds(case) for case in cases])
        for column, case in enumerate(cases):
            x = column * cell_width
            growth = case.blueprint.growth
            name = case.blueprint.display_name.split(" - ")[0]
            screen.blit(font.render(name, True, (226, 235, 224)), (x + 12, 76))
            architecture = (
                f"{str(growth.get('axis_continuity', 'unknown')).replace('_', ' ')} | "
                f"{str(growth.get('branching_rhythm', 'unknown')).replace('_', ' ')} | "
                f"{str(growth.get('branching_timing', 'unknown')).replace('_', ' ')}"
            )
            screen.blit(small.render(architecture, True, (174, 194, 176)), (x + 12, 96))

            front = pygame.Surface((cell_width - 10, row_height - 8))
            self._draw_individual(
                front, case,
                camera=DiagnosticCamera(front.get_width(), front.get_height(), front_bounds),
            )
            screen.blit(front, (x + 5, header_height))

            top = pygame.Surface((cell_width - 10, row_height - 8))
            top.fill((18, 23, 20))
            camera = TopDownDiagnosticCamera(top.get_width(), top.get_height(), top_bounds)
            visible = {
                index for index, placement in enumerate(case.render_snapshot.placements)
                if placement[0] not in {"root", "root_section", "root_support"}
            }
            self._draw_individual(top, case, camera=camera, clear=False,
                                  visible_indices=visible, draw_ground_line=False)
            screen.blit(top, (x + 5, header_height + row_height))
            pygame.draw.rect(screen, (50, 63, 55),
                             (x + 4, header_height, cell_width - 8, row_height * 2 - 8), 1)

        screen.blit(font.render("FRONT", True, (221, 220, 188)), (18, header_height + 10))
        screen.blit(font.render("TOP", True, (221, 220, 188)), (18, header_height + row_height + 10))
        baseline_y = header_height + row_height * 2 + 10
        screen.blit(small.render(
            "Birch: diffuse sympodial succession • Oak: continuous monopodial scaffold • "
            "Horse chestnut: rhythmic paired modules and terminal-flower transition",
            True, (178, 197, 180)), (18, baseline_y))
        screen.blit(small.render(
            "Architecture fields choose topology; droop, openness, twig density and apical control tune its expression.",
            True, (158, 180, 164)), (18, baseline_y + 20))

    def _editor_reference_surface(self, state, target_size, scale=1.0, silhouette=False):
        source = state.get("reference_surface")
        if source is None:
            return None
        key = (id(source), tuple(target_size), round(float(scale), 3), bool(silhouette))
        cached = self._species_editor_reference_cache.get(key)
        if cached is not None:
            return cached
        fit = min(target_size[0] / max(1, source.get_width()), target_size[1] / max(1, source.get_height()))
        size = (max(1, round(source.get_width() * fit * scale)), max(1, round(source.get_height() * fit * scale)))
        fitted = pygame.transform.smoothscale(source, size)
        if silhouette:
            corners = [fitted.get_at(point) for point in ((0, 0), (fitted.get_width()-1, 0), (0, fitted.get_height()-1), (fitted.get_width()-1, fitted.get_height()-1))]
            background = tuple(sum(color[i] for color in corners) // len(corners) for i in range(3)) + (255,)
            mask = pygame.mask.from_threshold(fitted, background, (42, 42, 42, 255))
            mask.invert()
            fitted = mask.to_surface(setcolor=(91, 205, 183, 255), unsetcolor=(0, 0, 0, 0))
        self._species_editor_reference_cache[key] = fitted
        if len(self._species_editor_reference_cache) > 20:
            self._species_editor_reference_cache.pop(next(iter(self._species_editor_reference_cache)))
        return fitted

    # foliage_cap=10: this is the Species Editor's single-tree panel, not the
    # forest/biosphere render path (which passes its own stricter cap of 3 in
    # biosphere_renderer.py regardless of this default). 10 was chosen by
    # timing the densest authored trees (Oak/Red Maple, ~900 leaf clusters
    # each): ~400ms per uncached redraw, against a ~200ms floor at cap=4 that
    # visibly under-filled a dense crown. The panel only redraws on
    # interaction release, not every frame, so this cost is paid rarely.
    # Compound-tree cohorts use the bounded density-dependent budget below:
    # their physical-size sprites otherwise leave most represented leaves
    # invisible. Explicit lower budgets (including variation) stay unchanged.
    def _draw_editor_plant_panel(self, panel, preview, camera, state=None, top_down=False, foliage_cap=10):
        panel.fill((18, 23, 20))
        if state and state.get("reference_overlay") and not top_down:
            reference = self._editor_reference_surface(
                state, panel.get_size(), state.get("reference_scale", 1.), state.get("reference_silhouette", False),
            )
            if reference is not None:
                reference = reference.copy()
                reference.set_alpha(round(255 * state.get("reference_opacity", .35)))
                offset = state.get("reference_offset", [0., 0.])
                center = (panel.get_width()//2 + round(offset[0]*panel.get_width()/2),
                          panel.get_height()//2 + round(offset[1]*panel.get_height()/2))
                panel.blit(reference, reference.get_rect(center=center))
        layer = pygame.Surface(panel.get_size(), pygame.SRCALPHA)
        visible = None
        if top_down:
            visible = canopy_visible_indices(preview,preview.render_snapshot)
        if (foliage_cap >= 10
                and preview.blueprint.growth.get("growth_form") == "tree"
                and preview.blueprint.growth.get("leaf_structure") in {
                    "pinnately_compound", "palmately_compound",
                }):
            density = float(preview.blueprint.growth.get("leaf_cluster_density", .5))
            foliage_cap = min(64, 18 + round(max(0.0, min(1.0, density)) * 46))
        self._draw_individual(layer, preview, camera=camera, clear=False, visible_indices=visible,
                              show_height_reference=preview.blueprint.growth.get("growth_behaviour")!="surface_covering",
                              draw_ground_line=not top_down and preview.blueprint.growth.get("growth_behaviour")!="surface_covering",
                              foliage_sample_cap=foliage_cap)
        panel.blit(layer, (0, 0))

    def _draw_species_editor(self, screen, sim):
        from simulations.species.species_editor import (
            FIELD_GROUPS, PREVIEW_MODES, calibration_badge, editable_field_rows, range_value,
        )

        state = sim._ensure_species_editor()
        previews = sim.get_species_editor_previews()
        preview = previews[0]
        width, height = screen.get_size()
        screen.fill((12, 17, 16))
        title, font, small, tiny = self._font(22), self._font(13), self._font(11), self._font(10)
        screen.blit(title.render(f"Species Editor | {preview.blueprint.display_name}", True, (231, 239, 231)), (18, 20))
        screen.blit(font.render(
            "Reference stays temporary • ranges describe variation • Save writes fields to the live species record",
            True, (157, 181, 169)), (18, 51))

        top, bottom, gap = 80, max(320, height - 148), 8
        left_width = max(245, int(width * .25))
        right_width = max(360, int(width * .29))
        middle_width = max(300, width - left_width - right_width - gap * 4)
        left = pygame.Rect(gap, top, left_width, bottom - top)
        middle = pygame.Rect(left.right + gap, top, middle_width, bottom - top)
        right = pygame.Rect(middle.right + gap, top, width - middle.right - gap * 2, bottom - top)
        for rect in (left, middle, right):
            pygame.draw.rect(screen, (18, 24, 21), rect)
            pygame.draw.rect(screen, (57, 72, 63), rect, 1)

        hitboxes = []

        def button(rect, label, kind, active=False, **payload):
            pygame.draw.rect(screen, (56, 78, 65) if active else (39, 52, 46), rect)
            pygame.draw.rect(screen, (116, 151, 130) if active else (76, 96, 85), rect, 1)
            text_surface = tiny.render(label, True, (230, 237, 226))
            screen.blit(text_surface, text_surface.get_rect(center=rect.center))
            hitboxes.append({"kind": kind, "rect": rect, **payload})

        # Temporary reference image and overlay alignment controls.
        screen.blit(font.render("1  REFERENCE PHOTO", True, (220, 225, 201)), (left.x + 12, left.y + 12))
        paste_rect = pygame.Rect(left.x + 12, left.y + 40, left.width - 24, 30)
        pygame.draw.rect(screen, (48, 65, 56), paste_rect)
        pygame.draw.rect(screen, (127, 159, 139), paste_rect, 1)
        paste_label = "Paste image  Ctrl+V" if state.get("reference_surface") is None else "Replace pasted image  Ctrl+V"
        screen.blit(font.render(paste_label, True, (232, 237, 224)), (paste_rect.x + 10, paste_rect.y + 7))
        hitboxes.append({"kind": "paste", "rect": paste_rect})
        controls_y = left.y + 78
        half = (left.width - 27) // 2
        button(pygame.Rect(left.x+12, controls_y, half, 24), "Overlay", "reference_control",
               state.get("reference_overlay", False), control="overlay")
        button(pygame.Rect(left.x+15+half, controls_y, half, 24), "Silhouette", "reference_control",
               state.get("reference_silhouette", False), control="silhouette")
        controls_y += 28
        third = (left.width - 30) // 3
        button(pygame.Rect(left.x+12, controls_y, third, 22), "Opacity −", "reference_control", control="opacity", delta=-.1)
        button(pygame.Rect(left.x+15+third, controls_y, third, 22), f"{state.get('reference_opacity',.35):.0%}", "reference_control", control="opacity", delta=0)
        button(pygame.Rect(left.x+18+third*2, controls_y, third, 22), "Opacity +", "reference_control", control="opacity", delta=.1)
        controls_y += 26
        button(pygame.Rect(left.x+12, controls_y, third, 22), "Scale −", "reference_control", control="scale", delta=-.1)
        button(pygame.Rect(left.x+15+third, controls_y, third, 22), f"{state.get('reference_scale',1.):.0%}", "reference_control", control="scale", delta=0)
        button(pygame.Rect(left.x+18+third*2, controls_y, third, 22), "Scale +", "reference_control", control="scale", delta=.1)
        controls_y += 26
        move_w = (left.width - 36)//5
        for index, (label, dx, dy) in enumerate((("←",-.08,0),("→",.08,0),("↑",0,-.08),("↓",0,.08),("Center",0,0))):
            rect = pygame.Rect(left.x+12+index*(move_w+3), controls_y, move_w, 22)
            button(rect, label, "reference_control", control="move", dx=dx, dy=dy)
            if label == "Center":
                hitboxes[-1]["center"] = True
        image_rect = pygame.Rect(left.x + 12, controls_y + 30, left.width - 24, left.bottom - controls_y - 66)
        pygame.draw.rect(screen, (10, 14, 13), image_rect)
        surface = state.get("reference_surface")
        if surface is not None:
            fitted = self._editor_reference_surface(state, image_rect.size)
            screen.blit(fitted, fitted.get_rect(center=image_rect.center))
        else:
            lines = ("Copy a real plant photograph", "or a local image file,", "then paste it here.", "", "Nothing is uploaded or saved.")
            y = image_rect.centery - len(lines) * 9
            for line in lines:
                label = small.render(line, True, (130, 151, 139))
                screen.blit(label, (image_rect.centerx - label.get_width() // 2, y))
                y += 18
        screen.blit(tiny.render(str(state.get("reference_label") or ""), True, (151, 173, 158)),
                    (left.x + 12, left.bottom - 30))

        # Mature range/variation preview.
        screen.blit(font.render("2  MATURE PREVIEW", True, (220, 225, 201)), (middle.x + 12, middle.y + 12))
        mode_y = middle.y + 36
        mode_w = (middle.width - 22)//4
        for index, mode in enumerate(PREVIEW_MODES):
            button(pygame.Rect(middle.x+8+index*(mode_w+2), mode_y, mode_w, 24), mode.title(),
                   "preview_mode", state.get("preview_mode") == mode, mode=mode)
        view_top = mode_y + 31
        if state.get("preview_mode") == "variation":
            cell_w, cell_h = (middle.width-22)//2, (middle.bottom-view_top-12)//2
            bounds = [diagnostic_cell_bounds(item.render_snapshot) for item in previews]
            shared = (min(x[0] for x in bounds), max(x[1] for x in bounds), min(x[2] for x in bounds), max(x[3] for x in bounds))
            for index, item in enumerate(previews):
                rect = pygame.Rect(middle.x+8+(index%2)*(cell_w+6), view_top+(index//2)*(cell_h+6), cell_w, cell_h)
                panel = pygame.Surface(rect.size)
                self._draw_editor_plant_panel(panel, item, DiagnosticCamera(rect.width, rect.height, shared), foliage_cap=2)
                screen.blit(panel, rect)
                screen.blit(tiny.render(f"seed {303+index}", True, (222,220,185)), (rect.x+7, rect.y+7))
        else:
            view_height = max(120, (middle.bottom - view_top - 8) // 2)
            side_rect = pygame.Rect(middle.x + 8, view_top, middle.width - 16, view_height - 3)
            top_rect = pygame.Rect(middle.x + 8, view_top + view_height, middle.width - 16, view_height - 3)
            side_panel = pygame.Surface(side_rect.size)
            surface_body=preview.blueprint.growth.get("growth_behaviour")=="surface_covering"
            side_camera=(SurfaceElevationCamera(side_rect.width,side_rect.height,preview.render_snapshot.bounds_m)
                         if surface_body else DiagnosticCamera(side_rect.width,side_rect.height,diagnostic_cell_bounds(preview.render_snapshot)))
            self._draw_editor_plant_panel(side_panel, preview,
                side_camera, state=state)
            screen.blit(side_panel, side_rect)
            top_panel = pygame.Surface(top_rect.size)
            top_camera=(IsometricDiagnosticCamera(top_rect.width,top_rect.height,preview.render_snapshot.bounds_m)
                        if surface_body else TopDownDiagnosticCamera(top_rect.width,top_rect.height,top_down_diagnostic_bounds(preview)))
            self._draw_editor_plant_panel(top_panel, preview,
                top_camera, top_down=True)
            screen.blit(top_panel, top_rect)
            screen.blit(font.render("SIDE", True, (222,220,185)), (side_rect.x+8, side_rect.y+8))
            screen.blit(font.render("ISOMETRIC" if surface_body else "TOP", True, (222,220,185)), (top_rect.x+8, top_rect.y+8))

        # Searchable field list, range handles, and direct organ-editor links.
        screen.blit(font.render("3  SPECIES FIELDS", True, (220, 225, 201)), (right.x + 12, right.y + 12))
        action_w = 50
        for index, (label, kind) in enumerate((("Undo","undo"),("Redo","redo"),("Save","save"),("Revert","revert"))):
            rect = pygame.Rect(right.right-12-(4-index)*(action_w+3), right.y+8, action_w, 26)
            active = (kind == "save" and state.get("dirty")) or (kind == "undo" and state.get("undo_stack")) or (kind == "redo" and state.get("redo_stack"))
            button(rect, label, kind, bool(active))
        search_rect = pygame.Rect(right.x + 12, right.y + 43, right.width - 24, 28)
        pygame.draw.rect(screen, (11, 16, 14), search_rect)
        pygame.draw.rect(screen, (74, 96, 83), search_rect, 1)
        query = state.get("query", "")
        search_text = f"Filter fields: {query}_" if query else "Type to filter fields…"
        screen.blit(small.render(search_text, True, (195, 211, 198) if query else (126, 148, 136)),
                    (search_rect.x + 8, search_rect.y + 7))

        asset_y = right.y + 80
        asset_roles = (("leaf", "Leaf"), ("stem", "Stem"), ("flower", "Flower"),
                       ("branch", "Branch"), ("root", "Root"), ("fruit", "Fruit"))
        if preview.blueprint.growth.get("fungal_grammar_version"):
            asset_roles=(("fruiting_body", "Ascocarp" if preview.blueprint.growth.get('ground_fungal_version') else "Bracket"), ("fruiting_cap", "Cap"))
        if preview.blueprint.growth.get("growth_behaviour")=="surface_covering":
            asset_roles=()
        asset_width = max(50, (right.width - 31) // 3)
        for index, (role, label) in enumerate(asset_roles):
            rect = pygame.Rect(right.x + 12 + (index % 3) * (asset_width + 3),
                               asset_y + (index // 3) * 27, asset_width, 24)
            pygame.draw.rect(screen, (39, 57, 49), rect)
            pygame.draw.rect(screen, (91, 119, 102), rect, 1)
            screen.blit(tiny.render(f"{label} Pixel", True, (216, 228, 216)), (rect.x + 7, rect.y + 6))
            hitboxes.append({"kind": "asset", "role": role, "rect": rect})

        groups_y = asset_y + 58
        group_w = max(54, (right.width-30)//3)
        for index, group in enumerate(FIELD_GROUPS):
            rect = pygame.Rect(right.x+12+(index%3)*(group_w+3), groups_y+(index//3)*25, group_w, 22)
            button(rect, group, "field_group", state.get("field_group") == group, group=group)
        relevance_rect = pygame.Rect(right.x+12, groups_y+52, right.width-24, 23)
        relevance_label = "● Preview-affecting fields only" if state.get("preview_only", True) else "○ All species fields"
        button(relevance_rect, relevance_label, "preview_only", state.get("preview_only", True))
        list_top = groups_y + 81
        list_rect = pygame.Rect(right.x + 7, list_top, right.width - 14, right.bottom - list_top - 8)
        rows = editable_field_rows(state["working_entity"], query, state.get("field_group", "All"), state.get("preview_only", True))
        scroll = min(max(0, int(state.get("scroll", 0))), max(0, len(rows) - 1))
        state["scroll"] = scroll
        old_clip = screen.get_clip()
        screen.set_clip(old_clip.clip(list_rect))
        y = list_top
        selected = state.get("selected_field")
        for row in rows[scroll:]:
            row_height = 62 if row["kind"] == "range" else 39
            if y + row_height > list_rect.bottom:
                break
            field_name = row["field"]
            rect = pygame.Rect(list_rect.x + 2, y, list_rect.width - 4, row_height - 3)
            fill = (34, 48, 41) if selected == field_name else (23, 31, 27)
            pygame.draw.rect(screen, fill, rect)
            pygame.draw.line(screen, (45, 58, 51), (rect.x, rect.bottom), (rect.right, rect.bottom))
            marker = "●" if row["affects_preview"] else "○"
            marker_color = (113, 188, 131) if row["affects_preview"] else (102, 112, 106)
            screen.blit(tiny.render(marker, True, marker_color), (rect.x+7, rect.y+7))
            screen.blit(small.render(row["label"], True, (211, 222, 210)), (rect.x + 20, rect.y + 5))
            if row["kind"] == "range":
                value = range_value(state, field_name)
                badge, badge_color = calibration_badge(value)
                summary = f"{value['min']:.2f}   {value['typical']:.2f}   {value['max']:.2f}"
                if field_name == "plant_leaf_attachment_angle":
                    summary = "   ".join(f"{value[k]*180:.0f}°" for k in ("min","typical","max"))
                    badge += " · 0° along shoot, 90° outward"
                label = tiny.render(summary, True, (166, 188, 171))
                screen.blit(label, (rect.right - label.get_width() - 7, rect.y + 6))
                screen.blit(tiny.render(badge, True, badge_color), (rect.x+20, rect.y+23))
                track = pygame.Rect(rect.x + 9, rect.y + 43, rect.width - 18, 8)
                pygame.draw.line(screen, (73, 85, 78), (track.x, track.centery), (track.right, track.centery), 2)
                min_x = round(track.x + value["min"] * track.width)
                typ_x = round(track.x + value["typical"] * track.width)
                max_x = round(track.x + value["max"] * track.width)
                pygame.draw.line(screen, (89, 139, 104), (min_x, track.centery), (max_x, track.centery), 5)
                pygame.draw.circle(screen, (190, 197, 183), (min_x, track.centery), 4)
                pygame.draw.circle(screen, (190, 197, 183), (max_x, track.centery), 4)
                pygame.draw.polygon(screen, (230, 199, 97),
                                    ((typ_x, track.centery - 6), (typ_x + 6, track.centery),
                                     (typ_x, track.centery + 6), (typ_x - 6, track.centery)))
                hitboxes.append({"kind": "range", "field": field_name, "rect": track.inflate(0, 16)})
            elif row["kind"] == "choice":
                value = str(row["value"] or "choose…").replace("_", " ")
                shown = self._ellipsize(value, small, max(80, rect.width - 140))
                screen.blit(small.render(shown, True, (166, 195, 173)), (rect.x + 135, rect.y + 5))
                screen.blit(small.render("‹  ›", True, (211, 190, 107)), (rect.right - 40, rect.y + 5))
                hitboxes.append({"kind": "choice", "field": field_name, "rect": rect})
            else:
                value = str(row["value"] or "unset")
                shown = self._ellipsize(value, tiny, max(70, rect.width - 175))
                screen.blit(tiny.render(shown, True, (151, 171, 159)), (rect.x + 135, rect.y + 7))
                screen.blit(tiny.render("Species Card", True, (181, 164, 112)), (rect.right - 78, rect.y + 7))
                hitboxes.append({"kind": "card", "field": field_name, "rect": rect})
            y += row_height
        screen.set_clip(old_clip)

        dirty = "unsaved changes" if state.get("dirty") else "saved values"
        status = f"{dirty} • {state.get('status', '')}"
        screen.blit(small.render(self._ellipsize(status, small, width - 36), True, (171, 190, 175)),
                    (18, bottom + 13))
        screen.blit(tiny.render(
            "Ranges: circle min/max, gold typical • Ctrl+Z/Y undo/redo • drag rebuilds once on release",
            True, (139, 160, 148)), (18, bottom + 33))
        sim.set_species_editor_hitboxes(hitboxes)

    def _draw_compare(self, screen, sim):
        if getattr(sim, "comparison_subject", "individual") == "roots":
            from simulations.species.root_comparison import draw_root_comparison
            draw_root_comparison(self, screen, sim.get_root_comparison_cases(),
                                 sim.root_comparison_page, sim.root_comparison_common_scale)
            return
        cases = sim.get_growth_gallery_cases()
        width, height = screen.get_size()
        footer_height = 136
        header_height = 76
        body_height = max(120, height - header_height - footer_height)
        left_width = max(360, int(width * 0.38))
        right_width = width - left_width
        left = pygame.Surface((left_width, body_height))
        self._draw_individual(
            left,
            sim,
            camera=DiagnosticCamera(left_width, body_height, diagnostic_cell_bounds(sim.render_snapshot)),
        )
        right = pygame.Surface((right_width, height))
        self._draw_gallery(right, sim)
        screen.fill((8, 12, 11))
        screen.blit(left, (0, header_height))
        screen.blit(right, (left_width, 0))
        pygame.draw.line(screen, (104, 125, 113), (left_width, 0), (left_width, height), 1)
        title_font = get_font(20)
        font = get_font(11)
        screen.blit(title_font.render("Normal Individual | R: compare roots", True, (230, 238, 232)), (14, 36))
        screen.blit(font.render(f"current individual • {sim.age_days:.0f}d • seed {sim.seed}", True, (157, 181, 169)), (14, 60))

    def _draw_roots(self, screen, sim):
        width, height = screen.get_size()
        panel_height = max(80, height - 165)
        side_width = max(1, width // 2)
        top_width = max(1, width - side_width)
        side_panel = pygame.Surface((side_width, panel_height))
        top_panel = pygame.Surface((top_width, panel_height))
        camera = DiagnosticCamera(side_width, panel_height, root_diagnostic_bounds(sim.render_snapshot))
        # Keep the shallow side profile above the app's diagnostic footer.
        # With a wide root system the horizontal fit controls scale, so the
        # default bottom alignment otherwise places the entire 1-2 m-deep
        # profile behind the footer even though the panel itself is tall.
        camera.bottom = panel_height * 0.55 + (0.0 - camera.min_z) * camera.scale
        self._draw_individual(side_panel, sim, camera=camera, roots_only=True)

        roots = [
            placement for placement in sim.render_snapshot.placements
            if placement[0] in {"root", "root_section", "root_support", "renewal_organ", "renewal_bud"}
        ]
        if roots:
            x_values = [float(placement[2]) for placement in roots]
            y_values = [float(placement[3]) for placement in roots]
            span = max(max(x_values) - min(x_values), max(y_values) - min(y_values), 0.1)
            margin = max(0.05, span * 0.04)
            top_bounds = (
                min(x_values) - margin, max(x_values) + margin,
                min(y_values) - margin, max(y_values) + margin,
            )
        else:
            top_bounds = (-0.5, 0.5, -0.5, 0.5)
        top_camera = TopDownDiagnosticCamera(top_width, panel_height, top_bounds)
        self._draw_individual(
            top_panel, sim, camera=top_camera, roots_only=True,
            draw_ground_line=False, draw_environment=False,
        )
        screen.fill((18, 23, 20))
        screen.blit(side_panel, (0, 95))
        screen.blit(top_panel, (side_width, 95))
        pygame.draw.line(screen, (91, 109, 94), (side_width, 95), (side_width, 95 + panel_height), 1)
        title = get_font(22)
        font = get_font(16)
        stats = sim.get_growth_summary()
        screen.blit(title.render(f"Roots | {sim.blueprint.display_name}", True, (232, 237, 224)), (18, 28))
        source = str(stats.get("root_depth_source", "runtime_default")).replace("_", " ")
        life_form = str(stats.get("plant_life_form", "other_unknown")).replace("_", " ")
        label = f"{stats.get('root_architecture', 'other_unknown')} | {life_form} | age {sim.age_days:.0f} days | {source}"
        screen.blit(font.render(label, True, (187, 200, 181)), (18, 62))
        screen.blit(font.render("SIDE", True, (225, 231, 216)), (12, 104))
        screen.blit(font.render("TOP", True, (225, 231, 216)), (side_width + 12, 104))
        if stats.get("root_model_status") == "unresolved":
            label = "Set Root Architecture on the species card to generate a root system."
        else:
            label = (f"Below crown: {stats['root_depth_m']:.2f} m | radial diameter: {stats['root_spread_m']:.2f} m"
                     f" | representative root length: {stats['root_length_m']:.2f} m")
        screen.blit(font.render(label, True, (216, 224, 204)), (18, height - 56))
        if stats.get("renewal_bud_count", 0):
            organ = str(stats.get("renewal_organ_kind", "unresolved")).replace("_", " ")
            bud_label = (
                f"Renewal bud: {stats['renewal_bud_depth_m']:.3f} m below soil"
                f" | organ: {organ} | bud depth is a runtime default"
            )
            screen.blit(font.render(bud_label, True, (222, 184, 91)), (18, height - 82))
        bar = 10 ** math.floor(math.log10(100 / camera.scale))
        pygame.draw.line(screen, (211, 211, 181), (20, height - 14), (20 + round(bar * camera.scale), height - 14), 2)
        screen.blit(font.render(f"{bar:g} m | structural proxy; root hairs and uptake are not simulated", True, (176, 188, 170)), (20, height - 36))

    def _draw_branches(self, screen, sim):
        width, height = screen.get_size()
        screen.fill((18,23,20))
        title = get_font(22)
        font = get_font(15)
        screen.blit(title.render(f"Branches | {sim.blueprint.display_name}",True,(226,234,219)),(18,28))
        label = str(sim.blueprint.growth.get("leaf_distribution","unknown")).replace("_"," ")
        screen.blit(font.render(f"{label} | foliage above, supporting structure below",True,(176,192,168)),(18,62))
        # Close-up shoot/branch geometry needs authentic per-leaf detail,
        # which the default (coarse) snapshot no longer carries by design.
        detailed = sim.get_detailed_snapshot()
        branch, shoot = branch_diagnostic_selection(sim, snapshot=detailed)
        if not branch:
            screen.blit(font.render("Grow a branched plant to inspect its leafy shoots.",True,(216,224,208)),(18,120))
            return
        cell_w,cell_h = width//2,(height-135)//2
        for col,indices in enumerate((branch,shoot)):
            bounds = branch_diagnostic_bounds(sim,indices,snapshot=detailed)
            for row in range(2):
                panel = pygame.Surface((cell_w-12,cell_h-18))
                camera = DiagnosticCamera(panel.get_width(),panel.get_height(),bounds)
                camera.bottom = panel.get_height()*.5+(bounds[3]-bounds[2])*camera.scale*.5
                self._draw_individual(panel,sim,camera=camera,visible_indices=indices,skeleton=row==1,snapshot=detailed)
                bar = 10**math.floor(math.log10(90/camera.scale))
                pygame.draw.line(panel,(210,219,188),(16,panel.get_height()-18),(16+round(bar*camera.scale),panel.get_height()-18),2)
                panel.blit(font.render(f"{bar:g} m",True,(210,219,188)),(16,panel.get_height()-40))
                screen.blit(panel,(col*cell_w+6,105+row*cell_h))
            screen.blit(font.render("Secondary branch" if col==0 else "Current shoot",True,(219,227,209)),(col*cell_w+18,85))
        screen.blit(font.render("Leaf clusters represent local foliage cohorts; visible leaves attach at explicit shoot nodes.",True,(169,185,162)),(18,height-30))

    def draw(self, screen, sim):
        view = getattr(sim, "diagnostic_view", "individual")
        if view == "rock_test":
            width,height=screen.get_size();screen.fill((18,23,20))
            font=get_font(16);small=get_font(12)
            screen.blit(font.render("Rock Test | expansion and lifecycle",True,(226,233,214)),(12,16))
            screen.blit(small.render("Same surface, attachment and scale. Timing and damage are illustrative.",True,(180,195,169)),(12,40))
            cell_w=max(1,width//3);cell_h=max(110,(height-218)//2)
            for i,(label,case) in enumerate(sim.get_rock_test_cases()):
                x=(i%3)*cell_w;y=65+(i//3)*cell_h
                panel=pygame.Surface((max(1,cell_w-12),max(1,cell_h-48)))
                camera=IsometricDiagnosticCamera(panel.get_width(),panel.get_height(),[-.085,.085,-.060,.060,0,.135])
                self._draw_individual(panel,case,camera=camera,show_height_reference=False,
                                      draw_ground_line=False,cache=True)
                screen.blit(panel,(x+6,y+20))
                screen.blit(font.render(label.split(" | ")[0].title(),True,(226,233,214)),(x+10,y))
                stats=case.render_snapshot.stats
                caption=f"Cover {stats['surface_coverage_m2']*10000:.1f} cm² | activity {stats['surface_activity']:.2f}"
                screen.blit(small.render(caption,True,(180,195,169)),(x+10,y+cell_h-23))
            screen.blit(small.render("Drying pauses activity; rewetting retains cover. Reproductive maturity and lifespan remain unknown.",True,(180,195,169)),(12,height-145))
            return
        if view == "surface":
            bounds = sim.render_snapshot.bounds_m
            width,height=screen.get_size()
            screen.fill((18,23,20))
            font=get_font(18)
            for i,cls in enumerate((SurfaceElevationCamera,IsometricDiagnosticCamera)):
                panel=pygame.Surface((max(1,width//2-12),max(1,height-95)))
                camera=cls(panel.get_width(),panel.get_height(),bounds)
                self._draw_individual(panel,sim,camera=camera,show_height_reference=False,
                                      draw_ground_line=False,cache=False)
                screen.blit(panel,(i*(width//2)+6,45))
                screen.blit(font.render("Front" if i==0 else "Isometric",True,(210,224,193)),(i*(width//2)+12,16))
            label=f"Attached cover {sim.render_snapshot.stats.get('surface_coverage_m2',0)*10000:.1f} cm² | {sim.render_snapshot.stats.get('surface_support_kind','unresolved')}"
            screen.blit(font.render(label,True,(178,195,167)),(12,height-35))
            return
        if view == "top_down":
            self._draw_top_down(screen, sim)
            return
        if view == "branches":
            self._draw_branches(screen, sim)
            return
        if view == "architecture":
            self._draw_tree_architecture(screen, sim)
            return
        if view == "editor":
            self._draw_species_editor(screen, sim)
            return
        if view == "roots":
            self._draw_roots(screen, sim)
            return
        if view == "gallery":
            self._draw_gallery(screen, sim)
            return
        if view == "forest":
            self._draw_forest(screen, sim)
            return
        if view == "compare":
            self._draw_compare(screen, sim)
            return
        if sim.blueprint.growth.get("aquatic_rosette_version"):
            camera = IsometricDiagnosticCamera(*screen.get_size(), sim.render_snapshot.bounds_m)
            self._draw_individual(screen, sim, camera=camera, draw_ground_line=False)
            return
        surface_body=sim.blueprint.growth.get("growth_behaviour")=="surface_covering"
        self._draw_individual(screen, sim, show_height_reference=not surface_body,draw_ground_line=not surface_body)
