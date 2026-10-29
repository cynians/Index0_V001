"""How a material looks on a building surface.

A material entity may carry ``material_texture_set_ref`` -- a Pixel Studio
texture-mode document (seamless base tile plus seeded character tiles), the
same format tree bark uses (``world/texture_sets.py``).  Without one, the
material's own ``display_color`` is used.  Nothing here invents colours: a
surface with no material assigned renders in a neutral schematic tone so it
is visibly unassigned.
"""

from __future__ import annotations

import json
import random
import zlib
from pathlib import Path

import pygame

from engine import asset_files
from world.texture_sets import TextureSet

from .blueprint_model import PIXELS_PER_METER


PROJECT_ROOT = Path(__file__).resolve().parents[2]
UNASSIGNED_COLORS = {
    "facade": (122, 128, 134),
    "interior_wall": (150, 150, 146),
    "floor": (96, 100, 104),
    "ceiling": (170, 170, 166),
    "roof": (88, 92, 98),
    "window": (70, 96, 118),
    "door": (84, 76, 66),
    None: (90, 94, 98),
}
VARIANT_PROBABILITY = 0.22


def _rgb(value):
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if len(text) == 6:
            try:
                return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                return None
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return tuple(max(0, min(255, int(channel))) for channel in value[:3])
        except (TypeError, ValueError):
            return None
    return None


def shade_color(color, factor):
    return tuple(max(0, min(255, int(round(channel * factor)))) for channel in color[:3])


class MaterialVisuals:
    def __init__(self, world_model=None, project_root=None):
        self.world_model = world_model
        self.project_root = Path(project_root) if project_root else PROJECT_ROOT
        self._texture_cache = {}
        self._tile_cache = {}
        self._scaled_cache = {}

    def entity(self, material_id):
        if not material_id or self.world_model is None:
            return None
        entity = self.world_model.get_entity(material_id)
        return entity if isinstance(entity, dict) else None

    def name(self, material_id):
        entity = self.entity(material_id)
        if entity is None:
            return "Unassigned" if not material_id else f"{material_id} (missing)"
        return str(entity.get("pretty_name") or entity.get("name") or material_id)

    def color(self, material_id, role=None):
        entity = self.entity(material_id)
        if entity is not None:
            color = _rgb(entity.get("display_color"))
            if color is not None:
                return color
            texture = self.texture(material_id)
            if texture is not None:
                average = self._average_texture_color(texture)
                if average is not None:
                    return average
        return UNASSIGNED_COLORS.get(role, UNASSIGNED_COLORS[None])

    def texture(self, material_id):
        entity = self.entity(material_id)
        if entity is None:
            return None
        ref = str(entity.get("material_texture_set_ref") or "").strip()
        if not ref:
            return None
        path = Path(ref)
        if not path.is_absolute():
            path = self.project_root / path
        mtime = asset_files.revision(path)
        if mtime is None:
            return None
        cached = self._texture_cache.get(ref)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        if cached is not None:
            # The texture was repainted: drop tiles rendered from the old one.
            self._tile_cache = {k: v for k, v in self._tile_cache.items() if k[0] != material_id}
            self._scaled_cache = {k: v for k, v in self._scaled_cache.items() if k[0] != material_id}
        texture = None
        try:
            with asset_files.open_gzip_text(path) as handle:
                document = json.load(handle)
            payload = document.get("texture_set") if isinstance(document, dict) else None
            texture = TextureSet.from_dict(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            texture = None
        self._texture_cache[ref] = (mtime, texture)
        return texture

    def _average_texture_color(self, texture):
        totals = [0, 0, 0]
        count = 0
        for layer in texture.base_layers or []:
            if not isinstance(layer, dict) or layer.get("reference_only"):
                continue
            for row in layer.get("pixels") or []:
                for color in row or []:
                    rgb = _rgb(color)
                    if rgb is None:
                        continue
                    totals = [totals[i] + rgb[i] for i in range(3)]
                    count += 1
        if not count:
            return None
        return tuple(total // count for total in totals)

    def _tile_surface(self, material_id, texture, variant_key=None):
        key = (material_id, variant_key or "base")
        surface = self._tile_cache.get(key)
        if surface is not None:
            return surface
        layers = texture.base_layers
        if variant_key and variant_key in texture.variants:
            layers = texture.variants[variant_key].layers
        surface = pygame.Surface((max(1, texture.width), max(1, texture.height)), pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        for layer in layers or []:
            if not isinstance(layer, dict) or not layer.get("visible", True) or layer.get("reference_only"):
                continue
            for y, row in enumerate((layer.get("pixels") or [])[:texture.height]):
                for x, color in enumerate((row or [])[:texture.width]):
                    rgb = _rgb(color)
                    if rgb is not None:
                        surface.set_at((x, y), (*rgb, 255))
        self._tile_cache[key] = surface
        return surface

    def _scaled_tile(self, material_id, texture, variant_key, size, shade):
        key = (material_id, variant_key or "base", size, round(shade, 2))
        cached = self._scaled_cache.get(key)
        if cached is not None:
            return cached
        tile = self._tile_surface(material_id, texture, variant_key)
        scaled = pygame.transform.scale(tile, size)
        if shade < 0.999:
            value = max(0, min(255, int(255 * shade)))
            scaled = scaled.copy()
            scaled.fill((value, value, value, 255), special_flags=pygame.BLEND_RGBA_MULT)
        if len(self._scaled_cache) > 512:
            self._scaled_cache.clear()
        self._scaled_cache[key] = scaled
        return scaled

    def fill_polygon(self, screen, points, material_id, role=None, *, meters_to_px=16.0,
                     anchor=(0, 0), shade=1.0, seed_key=""):
        """Fill a screen-space polygon with a material.

        ``anchor`` is the screen position of the surface's texture origin so
        tiles stay fixed to the surface while the view pans.
        """

        if len(points) < 3:
            return
        texture = self.texture(material_id)
        if texture is None:
            pygame.draw.polygon(screen, shade_color(self.color(material_id, role), shade), points)
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        left, top = int(min(xs)), int(min(ys))
        width, height = int(max(xs)) - left + 1, int(max(ys)) - top + 1
        clip = screen.get_clip() if hasattr(screen, "get_clip") else screen.get_rect()
        visible = pygame.Rect(left, top, width, height).clip(clip)
        if visible.width <= 0 or visible.height <= 0:
            return
        tile_w = max(1, round(texture.width / PIXELS_PER_METER * meters_to_px))
        tile_h = max(1, round(texture.height / PIXELS_PER_METER * meters_to_px))
        if tile_w * tile_h < 4 or (visible.width // tile_w) * (visible.height // tile_h) > 6000:
            pygame.draw.polygon(screen, shade_color(self.color(material_id, role), shade), points)
            return
        layer = pygame.Surface(visible.size, pygame.SRCALPHA)
        variant_keys = sorted(texture.variants)
        origin_x, origin_y = anchor
        first_i = int((visible.left - origin_x) // tile_w) - 1
        first_j = int((visible.top - origin_y) // tile_h) - 1
        last_i = int((visible.right - origin_x) // tile_w) + 1
        last_j = int((visible.bottom - origin_y) // tile_h) + 1
        seed_base = zlib.crc32(f"{material_id}|{seed_key}|{texture.seed}".encode("utf-8"))
        for j in range(first_j, last_j + 1):
            for i in range(first_i, last_i + 1):
                variant = None
                if variant_keys:
                    rng = random.Random(seed_base ^ (i * 73856093) ^ (j * 19349663))
                    if rng.random() < VARIANT_PROBABILITY:
                        variant = rng.choice(variant_keys)
                tile = self._scaled_tile(material_id, texture, variant, (tile_w, tile_h), shade)
                layer.blit(tile, (origin_x + i * tile_w - visible.left, origin_y + j * tile_h - visible.top))
        mask = pygame.Surface(visible.size, pygame.SRCALPHA)
        mask.fill((0, 0, 0, 0))
        pygame.draw.polygon(mask, (255, 255, 255, 255), [(x - visible.left, y - visible.top) for x, y in points])
        layer.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        screen.blit(layer, visible.topleft)
