"""Minimal preview renderer for the standalone Species Sim."""

import gzip
import json
import math
import random
from pathlib import Path

import pygame

from world.texture_sets import TextureSet
from simulations.species.species_simulation import SCREEN_DEPTH_PROJECTION


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


def root_diagnostic_bounds(snapshot):
    roots = [p for p in snapshot.placements if p[0] in {"root", "root_section", "root_support"}]
    if not roots:
        return (-0.5, 0.5, -1.0, 0.1)
    xs = [p[2] + p[3] * SCREEN_DEPTH_PROJECTION for p in roots]
    zs = [p[4] for p in roots]
    return min(xs) - 0.05, max(xs) + 0.05, min(zs) - 0.04, max(zs) + 0.06


def branch_diagnostic_selection(sim):
    ps = sim.render_snapshot.placements
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
    cluster = next((c for c in sim.render_snapshot.leaf_clusters if c["host_placement_index"] in branch), None)
    shoot = descendants(ps[cluster["host_placement_index"]][1]) if cluster else branch
    return branch, shoot


def branch_diagnostic_bounds(sim, selected):
    points = [p[2:5] for i,p in enumerate(sim.render_snapshot.placements) if i in selected]
    if not points:
        return (-1,1,0,1)
    xs = [p[0]+SCREEN_DEPTH_PROJECTION*p[1] for p in points]
    zs = [p[2] for p in points]
    margin = sim.blueprint.module("leaf").length_m * 1.5
    return min(xs)-margin,max(xs)+margin,min(zs)-margin,max(zs)+margin


class SpeciesRenderer:
    def __init__(self, app_view):
        self.app_view = app_view
        self._asset_cache = {}
        self._texture_cache = {}
        self._texture_surface_cache = {}
        self._leaf_sprite_cache = {}

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
            "stem_section": (91, 139, 70),
            "branch_section": (111, 126, 67),
            "leaf": (77, 168, 83),
            "flower": (210, 125, 170),
            "fruit": (208, 143, 61),
        }.get(kind, (150, 150, 150))

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
        pygame.draw.line(screen, color, point, end, width)
        if structure not in {"pinnately_compound", "palmately_compound"}:
            return

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
        path = Path(asset_ref)
        if not path.is_absolute():
            path = Path.cwd() / path
        cache_key = str(path.resolve())
        if cache_key in self._asset_cache:
            return self._asset_cache[cache_key]
        try:
            surface = pygame.image.load(cache_key)
            if pygame.display.get_surface() is not None:
                surface = surface.convert_alpha()
        except (pygame.error, OSError):
            surface = None
        self._asset_cache[cache_key] = surface
        return surface

    def _module_texture(self, sim, kind):
        module = sim.blueprint.module(kind) if hasattr(sim.blueprint, "module") else None
        ref = getattr(module, "texture_set_ref", None) if module is not None else None
        if not ref and module is not None:
            ref = (getattr(module, "visual", {}) or {}).get("texture_set_ref")
        if not ref:
            return None, None
        path = Path(ref)
        if not path.is_absolute():
            path = Path.cwd() / path
        cache_key = str(path.resolve())
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

    def _draw_textured_path(self, screen, cache_key, texture, variant_key, path_points, line_width):
        surface = self._texture_surface(cache_key, texture, variant_key)
        if surface is None or len(path_points) < 2:
            return False
        for start, end in zip(path_points, path_points[1:]):
            dx, dy = float(end[0]) - float(start[0]), float(end[1]) - float(start[1])
            length = math.hypot(dx, dy)
            if length < 0.5:
                continue
            target_width = max(4, int(line_width) * 3)
            target_height = max(4, round(length + max(0, int(line_width) - 2)))
            sprite = pygame.transform.scale(surface, (target_width, target_height))
            angle = math.degrees(math.atan2(dx, -dy))
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
            target_width = max(max(2, int(line_width)), round(target_height * aspect))
            sprite = pygame.transform.scale(surface, (target_width, target_height))
            angle = math.degrees(math.atan2(dx, -dy))
            sprite = pygame.transform.rotate(sprite, angle)
            center = ((float(start[0]) + float(end[0])) * 0.5, (float(start[1]) + float(end[1])) * 0.5)
            screen.blit(sprite, sprite.get_rect(center=(round(center[0]), round(center[1]))))
        return True

    def _draw_individual(self, screen, sim, camera=None, clear=True, show_height_reference=False, roots_only=False, visible_indices=None, skeleton=False):
        camera = camera or self.app_view.camera
        if clear:
            screen.fill((18, 23, 20))
        snapshot = sim.render_snapshot
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
        for index, placement in enumerate(snapshot.placements):
            kind, parent, x, y, z, rotation, scale, level = placement
            if visible_indices is not None and index not in visible_indices:
                continue
            if skeleton and kind in {"leaf", "flower", "fruit"}:
                continue
            if roots_only and kind not in {"root", "root_section", "root_support"}:
                continue
            point = self._placement_screen(camera, placement)
            if point is None:
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
                if kind == "root_support":
                    line_width = max(3, int(5 * scale))
                elif kind == "root_section":
                    line_width = max(1, int(4 * scale))
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
                    screen, texture_cache_key, texture, variant_key, path_points, line_width
                )
                if not structural_asset and not textured:
                    pygame.draw.lines(screen, color, False, path_points, line_width)
            elif kind == "leaf":
                if not self._draw_module_asset(screen, sim, camera, "leaf", point, rotation, scale):
                    self._draw_fallback_leaf(screen, sim, camera, snapshot, index, point, rotation, scale, color=color)
            elif kind == "root":
                pygame.draw.circle(screen, color, point, max(3, int(6 * scale)))
            else:
                if not self._draw_module_asset(screen, sim, camera, kind, point, rotation, scale):
                    pygame.draw.circle(screen, color, point, max(2, int(5 * scale)))

        # Leaf clusters remain one calculative object, but the diagnostic
        # renderer expands each one into a small visual sample. This makes a
        # mature canopy read as hundreds of leaves without expanding the
        # snapshot graph or ecological state to hundreds of entities.
        if not roots_only and not skeleton and getattr(snapshot, "leaf_clusters", None) and snapshot.lod >= 2:
            for cluster in snapshot.leaf_clusters:
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
                sample_count = max(2, min(5, int(round(1.0 + density * 4.0))))
                for sample_index in range(sample_count - 1):
                    sample_angle = host_angle + sample_index * 137.5 + 34.0
                    radius = 0.018 + 0.010 * (sample_index % 2)
                    radians = math.radians(sample_angle)
                    sample_x = x + math.cos(radians) * radius
                    sample_y = y + math.sin(radians) * radius
                    sample_z = z + (0.012 if sample_index % 2 else -0.006)
                    sample_point = self._screen(
                        camera,
                        sample_x + sample_y * SCREEN_DEPTH_PROJECTION,
                        sample_z,
                    )
                    if sample_point is None:
                        continue
                    sample_rotation = sample_angle + (180.0 if sample_index % 2 else 0.0)
                    sample_scale = max(0.42, min(0.82, host_scale * 0.64))
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
        cases = sim.get_growth_gallery_cases()
        width, height = screen.get_size()
        header_height = 76
        footer_height = 136
        body = pygame.Surface((width, max(120, height - header_height - footer_height)))
        body.fill((14, 20, 17))
        max_height = max((case.snapshot.bounds_m[5] for case in cases), default=1.0)
        max_span = max((diagnostic_cell_bounds(case.snapshot)[1] - diagnostic_cell_bounds(case.snapshot)[0] for case in cases), default=1.0)
        field_half_width = max(6.0, min(18.0, max_span * 1.8))
        base_camera = DiagnosticCamera(
            width,
            body.get_height(),
            (-field_half_width, field_half_width, 0.0, max_height * 1.05),
        )
        rng = random.Random(int(sim.seed) + 9201)
        placements = []
        for case in cases:
            depth = rng.random()
            offset_x = rng.uniform(-field_half_width * 0.82, field_half_width * 0.82)
            local_scale = 0.74 + depth * 0.30
            placements.append((depth, offset_x, local_scale, case))
        for _depth, offset_x, local_scale, case in sorted(placements):
            self._draw_individual(
                body,
                case.simulation,
                camera=OffsetDiagnosticCamera(base_camera, offset_x, local_scale),
                clear=False,
            )
        screen.fill((13, 18, 17))
        screen.blit(body, (0, header_height))
        title_font = pygame.font.SysFont("consolas", 20)
        font = pygame.font.SysFont("consolas", 11)
        screen.blit(title_font.render(f"Species Sim forest view — {sim.blueprint.display_name}", True, (230, 238, 232)), (14, 36))
        screen.blit(font.render("20 deterministic individuals • shuffled positions and depth scale • shared ground plane", True, (157, 181, 169)), (14, 60))

    def _draw_compare(self, screen, sim):
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
        screen.blit(title_font.render("Normal Individual", True, (230, 238, 232)), (14, 36))
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
        label = f"{stats.get('root_architecture', 'other_unknown')} | age {sim.age_days:.0f} days | {source}"
        screen.blit(font.render(label, True, (187, 200, 181)), (18, 62))
        if stats.get("root_model_status") == "unresolved":
            label = "Set Root Architecture on the species card to generate a root system."
        else:
            label = (f"Below crown: {stats['root_depth_m']:.2f} m | radial diameter: {stats['root_spread_m']:.2f} m"
                     f" | representative root length: {stats['root_length_m']:.2f} m")
        screen.blit(font.render(label, True, (216, 224, 204)), (18, height - 56))
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
        branch, shoot = branch_diagnostic_selection(sim)
        if not branch:
            screen.blit(font.render("Grow a branched plant to inspect its leafy shoots.",True,(216,224,208)),(18,120))
            return
        cell_w,cell_h = width//2,(height-135)//2
        for col,indices in enumerate((branch,shoot)):
            bounds = branch_diagnostic_bounds(sim,indices)
            for row in range(2):
                panel = pygame.Surface((cell_w-12,cell_h-18))
                camera = DiagnosticCamera(panel.get_width(),panel.get_height(),bounds)
                camera.bottom = panel.get_height()*.5+(bounds[3]-bounds[2])*camera.scale*.5
                self._draw_individual(panel,sim,camera=camera,visible_indices=indices,skeleton=row==1)
                bar = 10**math.floor(math.log10(90/camera.scale))
                pygame.draw.line(panel,(210,219,188),(16,panel.get_height()-18),(16+round(bar*camera.scale),panel.get_height()-18),2)
                panel.blit(font.render(f"{bar:g} m",True,(210,219,188)),(16,panel.get_height()-40))
                screen.blit(panel,(col*cell_w+6,105+row*cell_h))
            screen.blit(font.render("Secondary branch" if col==0 else "Current shoot",True,(219,227,209)),(col*cell_w+18,85))
        screen.blit(font.render("Leaf clusters represent local foliage cohorts; visible leaves attach at explicit shoot nodes.",True,(169,185,162)),(18,height-30))

    def draw(self, screen, sim):
        view = getattr(sim, "diagnostic_view", "individual")
        if view == "branches":
            self._draw_branches(screen, sim)
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
