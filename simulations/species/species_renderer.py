"""Minimal preview renderer for the standalone Species Sim."""

import gzip
import json
import math
import random
from pathlib import Path

import pygame

from world.texture_sets import TextureSet
from simulations.species.species_simulation import SCREEN_DEPTH_PROJECTION

# asset_ref/texture_set_ref values are authored relative to the repo root.
# Resolving them against Path.cwd() breaks silently (empty surface, falls
# back to the plain-line leaf/branch rendering) whenever the app happens to
# be launched from a different working directory; anchor to this file's
# location instead, matching the convention already used by
# world/entity_loader.py and app/app.py.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DiagnosticCamera:
    """Small camera used by the in-simulation diagnostic views."""

    def __init__(self, width, height, bounds):
        min_x, max_x, min_z, max_z = bounds
        self.center_x = (min_x + max_x) * 0.5
        self.screen_center_x = width * 0.5
        self.min_z = min_z
        self.scale = min(
            (width - 24) / max(0.1, max_x - min_x),
            (height - 52) / max(0.1, max_z - min_z),
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


class OffsetDiagnosticCamera:
    def __init__(self, camera, offset_x, local_scale=1.0):
        self.camera = camera
        self.offset_x = float(offset_x)
        self.local_scale = float(local_scale)

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
    root_kinds = {"root", "root_section", "root_support", "renewal_organ", "renewal_bud"}
    leaf_module = sim.blueprint.module("leaf") if hasattr(sim.blueprint, "module") else None
    leaf_length = max(0.04, float(getattr(leaf_module, "length_m", 0.1) or 0.1))
    leaf_radius = max(0.006, float(getattr(leaf_module, "radius_m", 0.012) or 0.012))
    points = [
        (float(placement[2]), float(placement[3]))
        for placement in snapshot.placements
        if placement[0] not in root_kinds
    ]
    orientations = getattr(snapshot, "placement_orientations", {}) or {}
    for index, placement in enumerate(snapshot.placements):
        if placement[0] != "leaf":
            continue
        orientation = orientations.get(str(index)) or {}
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
        if placement[0] in root_kinds:
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
                if cluster.get("shoot_type"):
                    spread += max(0.0, float(cluster.get("length", 0.0) or 0.0)) * 0.5
                points.extend(((x - spread, y - spread), (x + spread, y + spread)))

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


class SpeciesRenderer:
    def __init__(self, app_view):
        self.app_view = app_view
        self._asset_cache = {}
        self._asset_path_cache = {}
        self._asset_revision_cache = {}
        self._texture_cache = {}
        self._texture_path_cache = {}
        self._texture_surface_cache = {}
        self._leaf_sprite_cache = {}
        self._individual_draw_cache = {}
        self._individual_draw_cache_order = []
        self._font_cache = {}
        self._species_editor_reference_cache = {}

    def _font(self, size):
        size = int(size)
        if size not in self._font_cache:
            self._font_cache[size] = pygame.font.SysFont("consolas", size)
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

    def _path_screen(self, camera, point):
        if hasattr(camera, "world_to_screen_3d"):
            return camera.world_to_screen_3d(point)
        return self._screen(camera, float(point[0]) + float(point[1]) * SCREEN_DEPTH_PROJECTION, float(point[2]))

    def _color(self, kind):
        return {
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
                self._color(kind),
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
        color = self._color(kind)
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
        font = pygame.font.SysFont("consolas", 11)
        label = font.render(str(reference.get("label") or "Human 1.75 m"), True, figure_color)
        screen.blit(label, (base_x - label.get_width() // 2, max(2, top_y - label.get_height() - 3)))

    def _fallback_leaf_endpoint(self, camera, sim, snapshot, index, point, rotation, scale):
        orientations = getattr(snapshot, "placement_orientations", {}) or {}
        orientation = orientations.get(str(index))
        if isinstance(orientation, dict):
            forward = orientation.get("forward") or []
            if len(forward) >= 3:
                module = sim.blueprint.module("leaf") if hasattr(sim.blueprint, "module") else None
                length_m = float(getattr(module, "length_m", 0.1) or 0.1) if module is not None else 0.1
                length_m = max(0.04, length_m * max(0.55, float(scale)) * 1.35)
                origin = snapshot.placements[index][2:5]
                target = [
                    float(origin[0]) + float(forward[0]) * length_m,
                    float(origin[1]) + float(forward[1]) * length_m,
                    float(origin[2]) + float(forward[2]) * length_m,
                ]
                projected = self._placement_screen(camera, ["leaf_extent", -1, target[0], target[1], target[2], rotation, scale, 0])
                if projected is not None:
                    return projected
        length = max(3.0, 18.0 * scale)
        return (
            point[0] + math.cos(math.radians(rotation)) * length,
            point[1] - math.sin(math.radians(rotation)) * length,
        )

    def _draw_fallback_leaf(self, screen, sim, camera, snapshot, index, point, rotation, scale, color=None):
        """Draw a readable fallback for authored leaf structures.

        A compound leaf is still one reusable leaf module.  The fallback only
        expands its internal leaflet silhouette for diagnostics when no pixel
        asset has been authored yet; it does not create extra simulation
        placements or ecological entities.
        """
        color = color or self._color("leaf")
        end = self._fallback_leaf_endpoint(camera, sim, snapshot, index, point, rotation, scale)
        structure = "simple"
        module = sim.blueprint.module("leaf") if hasattr(sim.blueprint, "module") else None
        if module is not None:
            structure = str((getattr(module, "visual", {}) or {}).get("leaf_structure") or "simple").lower()
        width = max(1, int(3 * max(0.45, float(scale))))
        if structure not in {"pinnately_compound", "palmately_compound"}:
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

        pygame.draw.line(screen, color, point, end, width)

        dx, dy = end[0] - point[0], end[1] - point[1]
        length = max(1.0, math.hypot(dx, dy))
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        leaflet_count = 5 if structure == "pinnately_compound" else 4
        for leaflet_index in range(leaflet_count):
            fraction = 0.22 + 0.13 * leaflet_index
            base_x = point[0] + dx * fraction
            base_y = point[1] + dy * fraction
            side = -1.0 if leaflet_index % 2 else 1.0
            leaflet_length = max(2.5, length * (0.24 - 0.018 * leaflet_index))
            tip_x = base_x + px * side * leaflet_length + ux * leaflet_length * 0.18
            tip_y = base_y + py * side * leaflet_length + uy * leaflet_length * 0.18
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
            surface = pygame.image.load(path_key)
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
        try:
            revision = Path(path_key).stat().st_mtime_ns
        except OSError:
            revision = None
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
        return tuple(revisions)

    def _module_texture(self, sim, kind):
        module = sim.blueprint.module(kind) if hasattr(sim.blueprint, "module") else None
        ref = getattr(module, "texture_set_ref", None) if module is not None else None
        if not ref and module is not None:
            ref = (getattr(module, "visual", {}) or {}).get("texture_set_ref")
        if not ref:
            return None, None
        cache_key = self._texture_path_cache.get(ref)
        if cache_key is None:
            path = Path(ref)
            if not path.is_absolute():
                path = _PROJECT_ROOT / path
            cache_key = str(path.resolve())
            self._texture_path_cache[ref] = cache_key
        if cache_key in self._texture_cache:
            return cache_key, self._texture_cache[cache_key]
        texture = None
        try:
            with gzip.open(cache_key, "rt", encoding="utf-8") as handle:
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

    def _draw_module_asset(self, screen, sim, camera, kind, point, rotation, scale):
        surface = self._module_asset(sim, kind)
        if surface is None:
            return False
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
        bounds = surface.get_bounding_rect()
        if bounds.width > 0 and bounds.height > 0 and bounds.size != surface.get_size():
            original_width, original_height = surface.get_size()
            surface = surface.subsurface(bounds).copy()
            anchor_x = (anchor_x * original_width - bounds.x) / max(1, bounds.width)
            anchor_y = (anchor_y * original_height - bounds.y) / max(1, bounds.height)
            anchor_x, anchor_y = max(0.0, min(1.0, anchor_x)), max(0.0, min(1.0, anchor_y))
        try:
            pixels_per_meter = abs(camera.world_to_screen((1.0, 0.0))[0] - camera.world_to_screen((0.0, 0.0))[0])
        except (TypeError, IndexError):
            pixels_per_meter = 64.0
        target_height = max(10, int(max(0.04, float(getattr(module, "length_m", 0.1))) * pixels_per_meter * max(0.55, float(scale))))
        if kind == "leaf":
            target_height = max(14, int(target_height * 1.45))
        if kind == "leaf" and sim.blueprint.growth.get("shoot_distribution_grammar"):
            target_height = max(2, round(float(module.length_m) * pixels_per_meter * float(scale)))
        target_height = min(180, target_height)
        aspect = surface.get_width() / max(1, surface.get_height())
        target_width = max(4, int(target_height * aspect))
        if kind == "leaf" and sim.blueprint.growth.get("shoot_distribution_grammar"):
            target_width = max(1, round(target_height * aspect))
        mirror = self._mirror_leaf_for_rotation(kind, rotation)
        if mirror:
            anchor_x = 1.0 - anchor_x
        cache_key = (getattr(module,"asset_ref",None),target_width,target_height,round(render_rotation/5)*5,mirror)
        cached = self._leaf_sprite_cache.get(cache_key) if kind == "leaf" else None
        render_rotation = cache_key[3] if kind == "leaf" else render_rotation
        if cached is None:
            sprite = pygame.transform.scale(surface, (target_width, target_height))
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
            physical = sim.blueprint.growth.get("shoot_distribution_grammar")
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

    def _draw_individual(self, screen, sim, camera=None, clear=True, show_height_reference=False, roots_only=False, visible_indices=None, skeleton=False, snapshot=None, cache=True, draw_ground_line=True, foliage_sample_cap=None):
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
                tuple(sorted(visible_indices)) if visible_indices is not None else None,
                bool(skeleton), bool(roots_only), bool(show_height_reference), bool(clear), bool(draw_ground_line),
                foliage_sample_cap,
                screen.get_size(), _camera_state_key(camera),
                self._visual_asset_revision(sim),
            )
            cached = self._individual_draw_cache.get(cache_key)
            if cached is not None:
                screen.blit(cached, (0, 0))
                return
        self._draw_individual_uncached(
            screen, sim, camera=camera, clear=clear, show_height_reference=show_height_reference,
            roots_only=roots_only, visible_indices=visible_indices, skeleton=skeleton, snapshot=snapshot,
            draw_ground_line=draw_ground_line, foliage_sample_cap=foliage_sample_cap,
        )
        if cache:
            frame = screen.copy()
            self._individual_draw_cache[cache_key] = frame
            self._individual_draw_cache_order.append(cache_key)
            if len(self._individual_draw_cache_order) > 64:
                stale_key = self._individual_draw_cache_order.pop(0)
                self._individual_draw_cache.pop(stale_key, None)

    def _draw_individual_uncached(self, screen, sim, camera=None, clear=True, show_height_reference=False, roots_only=False, visible_indices=None, skeleton=False, snapshot=None, draw_ground_line=True, foliage_sample_cap=None):
        camera = camera or self.app_view.camera
        if clear:
            screen.fill((18, 23, 20))
        snapshot = snapshot or sim.render_snapshot
        if draw_ground_line:
            ground = self._screen(camera, snapshot.bounds_m[0] - 1.0, 0.0)
            ground_right_x = max(snapshot.bounds_m[1] + 1.0, float(getattr(sim, "height_reference_x", snapshot.bounds_m[1] + 1.0)) + 0.35)
            ground_right = self._screen(camera, ground_right_x, 0.0)
            if ground and ground_right:
                line_color = (62, 112, 126) if sim.blueprint.growth.get("shape") == "aquatic" else (82, 72, 55)
                pygame.draw.line(screen, line_color, ground, ground_right, 2)
        if clear and snapshot.stats.get("root_segment_count", 0):
            soil_z = snapshot.stats.get("root_origin_z_m", 0.0)
            soil_point = self._screen(camera, 0.0, soil_z)
            if soil_point:
                soil_y = max(0, min(screen.get_height(), soil_point[1]))
                pygame.draw.rect(screen, (28, 27, 22), (0, soil_y, screen.get_width(), screen.get_height() - soil_y))
                pygame.draw.line(screen, (104, 90, 64), (0, soil_y), (screen.get_width(), soil_y), 1)
                if roots_only:
                    label = "Sediment / root crown" if sim.blueprint.growth.get("shape") == "aquatic" else "Root crown"
                    font = pygame.font.SysFont("consolas", 13)
                    screen.blit(font.render(label, True, (163, 155, 128)), (12, max(0, soil_y - 19)))

        texture_sequences = {}
        texture_slots = {}
        renewal_overlays = []
        for index, placement in enumerate(snapshot.placements):
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
            if kind in {"renewal_organ", "renewal_bud"}:
                renewal_overlays.append((kind, point, scale))
                continue
            color = self._color(kind)
            if sim.blueprint.growth.get("shape") in {"tree", "shrub", "subshrub"}:
                if kind in {"stem_section", "branch_section", "root"}:
                    color = (126, 91, 62)
                elif kind == "flower":
                    color = (190, 151, 64)
            elif sim.blueprint.growth.get("shape") == "aquatic":
                if kind in {"stem_section", "branch_section", "root"}:
                    color = (53, 117, 126)
            elif sim.blueprint.growth.get("shape") == "succulent":
                if kind in {"stem_section", "branch_section", "root"}:
                    color = (117, 137, 73)
            parent_point = None
            if int(parent) >= 0 and int(parent) < len(snapshot.placements):
                parent_point = self._placement_screen(camera, snapshot.placements[int(parent)])
            if kind in {"stem_section", "branch_section", "root_section", "root_support"} and parent_point:
                path = getattr(snapshot, "placement_paths", {}).get(str(index), [])
                path_points = [parent_point]
                path_points.extend(self._path_screen(camera, path_point) for path_point in path)
                if not path:
                    path_points.append(point)
                line_width = max(1, int(3 * scale))
                if kind in {"stem_section", "branch_section"} and sim.blueprint.growth.get("shoot_distribution_grammar"):
                    line_width = max(1, min(45, round(2 * scale * self._projection_pixels_per_meter(camera))))
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
            elif kind == "leaf":
                if not self._draw_module_asset(screen, sim, camera, "leaf", point, rotation, scale):
                    self._draw_fallback_leaf(screen, sim, camera, snapshot, index, point, rotation, scale, color=color)
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
            for cluster in clusters:
                if cluster.get("explicit_samples"):
                    continue
                estimated = int(cluster.get("estimated_leaf_count", 1) or 1)
                if estimated <= 1:
                    continue
                position = cluster.get("position_m") or [0.0, 0.0, 0.0]
                if len(position) < 3:
                    continue
                x, y, z = (float(position[0]), float(position[1]), float(position[2]))
                host_index = int(cluster.get("host_placement_index", -1) or -1)
                host = snapshot.placements[host_index] if 0 <= host_index < len(snapshot.placements) else None
                host_angle = float(host[5]) if host is not None and len(host) > 5 else 0.0
                host_scale = float(host[6]) if host is not None and len(host) > 6 else 1.0
                density = max(0.0, min(1.0, float(cluster.get("visual_density", 0.6) or 0.6)))
                sample_draws = 2 if dense_canopy else max(1, min(4, int(round(density * 4.0))))
                # Dense-canopy blobs are drawn larger so a handful of blits
                # per cluster still reads as full foliage rather than a
                # sparse scatter of dots.
                blob_scale = max(0.42, min(1.35, host_scale * (0.9 if dense_canopy else 0.64)))
                shoot = cluster.get("shoot_type")
                if shoot:
                    sample_draws = min(estimated, 18 + round(density * 18))
                    leaf_module = sim.blueprint.module("leaf")
                    leaf_length = leaf_module.length_m if leaf_module else .1
                    blob_scale = .85
                if foliage_sample_cap is not None:
                    sample_draws = min(sample_draws, max(0, int(foliage_sample_cap)))
                for sample_index in range(sample_draws):
                    sample_angle = host_angle + sample_index * 137.5 + 34.0
                    radius = 0.018 + 0.010 * (sample_index % 2)
                    radians = math.radians(sample_angle)
                    sample_x = x + math.cos(radians) * radius
                    sample_y = y + math.sin(radians) * radius
                    sample_z = z + (0.012 if sample_index % 2 else -0.006)
                    if shoot:
                        # Distribute along the shoot and around its leaf-bearing volume.
                        along = (sample_index / max(1, sample_draws-1) - .5) * float(cluster.get("length", .2))
                        azimuth = float(cluster.get("angle", 0.))
                        spread = leaf_length * (0.7 + .7 * density) * math.sqrt((sample_index % 7 + 1) / 7)
                        sample_x = x + math.cos(azimuth)*along + math.cos(radians)*spread
                        sample_y = y + math.sin(azimuth)*along + math.sin(radians)*spread
                        sample_z = z + math.sin(radians*1.7)*spread
                    sample_point = self._path_screen(camera, (sample_x, sample_y, sample_z))
                    if sample_point is None:
                        continue
                    sample_rotation = sample_angle + (180.0 if sample_index % 2 else 0.0)
                    sample_scale = blob_scale if dense_canopy or shoot else max(0.42, min(0.82, host_scale * 0.64))
                    if not self._draw_module_asset(screen, sim, camera, "leaf", sample_point, sample_rotation, sample_scale):
                        self._draw_fallback_leaf(
                            screen, sim, camera, snapshot, host_index if host_index >= 0 else 0,
                            sample_point, sample_rotation, sample_scale,
                            color=self._color("leaf"),
                        )

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
        title_font = pygame.font.SysFont("consolas", 20)
        font = pygame.font.SysFont("consolas", 11)
        small = pygame.font.SysFont("consolas", 10)
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

        above_ground = {
            index for index, placement in enumerate(sim.render_snapshot.placements)
            if placement[0] not in {"root", "root_section", "root_support"}
        }
        self._draw_individual(
            panel, sim, camera=camera, clear=False, visible_indices=above_ground,
            draw_ground_line=False,
        )

        screen.fill((13, 18, 17))
        screen.blit(panel, (0, header_height))
        title = pygame.font.SysFont("consolas", 22)
        font = pygame.font.SysFont("consolas", 13)
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
        title = pygame.font.SysFont("consolas", 22)
        font = pygame.font.SysFont("consolas", 13)
        small = pygame.font.SysFont("consolas", 11)
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

    def _draw_editor_plant_panel(self, panel, preview, camera, state=None, top_down=False, foliage_cap=4):
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
            visible = {i for i, placement in enumerate(preview.render_snapshot.placements)
                       if placement[0] not in {"root", "root_section", "root_support"}}
        self._draw_individual(layer, preview, camera=camera, clear=False, visible_indices=visible,
                              draw_ground_line=not top_down, foliage_sample_cap=foliage_cap)
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
            self._draw_editor_plant_panel(side_panel, preview,
                DiagnosticCamera(side_rect.width, side_rect.height, diagnostic_cell_bounds(preview.render_snapshot)), state=state)
            screen.blit(side_panel, side_rect)
            top_panel = pygame.Surface(top_rect.size)
            self._draw_editor_plant_panel(top_panel, preview,
                TopDownDiagnosticCamera(top_rect.width, top_rect.height, top_down_diagnostic_bounds(preview)), top_down=True)
            screen.blit(top_panel, top_rect)
            screen.blit(font.render("SIDE", True, (222,220,185)), (side_rect.x+8, side_rect.y+8))
            screen.blit(font.render("TOP", True, (222,220,185)), (top_rect.x+8, top_rect.y+8))

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
        title_font = pygame.font.SysFont("consolas", 20)
        font = pygame.font.SysFont("consolas", 11)
        screen.blit(title_font.render("Normal Individual | R: compare roots", True, (230, 238, 232)), (14, 36))
        screen.blit(font.render(f"current individual • {sim.age_days:.0f}d • seed {sim.seed}", True, (157, 181, 169)), (14, 60))

    def _draw_roots(self, screen, sim):
        width, height = screen.get_size()
        panel = pygame.Surface((width, max(80, height - 165)))
        camera = DiagnosticCamera(panel.get_width(), panel.get_height(), root_diagnostic_bounds(sim.render_snapshot))
        self._draw_individual(panel, sim, camera=camera, roots_only=True)
        screen.fill((18, 23, 20))
        screen.blit(panel, (0, 95))
        title = pygame.font.SysFont("consolas", 22)
        font = pygame.font.SysFont("consolas", 16)
        stats = sim.get_growth_summary()
        screen.blit(title.render(f"Roots | {sim.blueprint.display_name}", True, (232, 237, 224)), (18, 28))
        source = str(stats.get("root_depth_source", "runtime_default")).replace("_", " ")
        life_form = str(stats.get("plant_life_form", "other_unknown")).replace("_", " ")
        label = f"{stats.get('root_architecture', 'other_unknown')} | {life_form} | age {sim.age_days:.0f} days | {source}"
        screen.blit(font.render(label, True, (187, 200, 181)), (18, 62))
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
        title = pygame.font.SysFont("consolas",22)
        font = pygame.font.SysFont("consolas",15)
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
        self._draw_individual(screen, sim, show_height_reference=True)
