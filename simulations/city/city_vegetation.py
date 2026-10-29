"""The plants a city's ground carries.

A city founded on generated terrain stands in the biomes of its planet.  What
grows there is what has been established in those biomes (``biosphere.flora``):
nothing on a planet no Biosphere has touched and no plant collection was
assigned to, and after that each species as often as it is common, where the
ground suits it (``biosphere.potential_vegetation``).

The city map shows it from above, over its ground:

* herbs, grass and what creeps as a tint, as dense as their cover;
* everything from two metres up as a plant where it stands (``PlantField``).

A plant on the map is its species' own picture: one of the individuals the
planet keeps of it, full-grown, as Species Sim draws it from straight above
(``PlanetPlantPictures.map_sprite``), turned and mirrored one of eight ways
and sized to the ground the plant takes.  Close in, it is that picture pixel
for pixel.  Further out it is a coarser one made from it, of fewer pixels and
tones, and each of its pixels takes two or three on the screen: a small pixel
picture that still is that plant.  A species whose plants would be only a few
pixels across at a scale is a tint there instead, in its own colour, and
turns into single plants on the way in.

The field is painted in tiles as they are first looked at, and the plants of a
piece of ground are set out then too (``ResidentVegetation.plants``), the same
ones each time: a city holds millions and shows a few thousand.  Climbers
stand in the crowns of what carries them and are not drawn.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import time

import numpy as np
import pygame

from simulations.biosphere.ecology import BiosphereEcology, profile_from_entity
from simulations.biosphere.flora import planet_floras
from simulations.biosphere.plant_pictures import (
    MAP_SPRITE_DIR, MAP_VARIANTS, foliage_colour, map_sprite_at, planet_plant_pictures, plant_colour, plant_picture,
)
from simulations.biosphere.potential_vegetation import MAP_CELLS, planet_seed, resident_vegetation


VEGETATION_CELLS = MAP_CELLS
OVERVIEW_LONG_SIDE_PX = 2048
GROUND_COVER_LONG_SIDE_PX = 448
TILE_PX = 384
# Close in, from this many screen pixels to the metre, a painted pixel is a screen pixel: the plant as it is drawn.
FINEST_PX_PER_M = 16.0
# Further out a painted pixel takes more screen pixels, up to this many: a coarser picture of the same plant.
COARSEST_PIXEL_PX = 3.0
# A plant is painted as itself from this many painted pixels across; smaller, its species is a tint.
RESOLVED_CROWN_PX = 4.0
# The crown of a full-grown plant, as a share of the ground it takes: crowns of a closed stand touch and overlap.
CROWN_SHARE = 0.62
# The eight ways a picture from above is laid down: four turns, each also mirrored.
WAYS = 8
SHADOW = (14, 20, 14, 95)
TILES_KEPT = 96
STAMP_PIXELS_KEPT = 12_000_000
LOW_LAYERS = ("field", "ground")
TALL_LAYERS = ("understorey", "canopy")


def city_planet_id(world_model, city):
    planet_id = city.get("terrain_root_planet_id")
    if planet_id:
        return planet_id
    region = world_model.get_entity(city.get("terrain_source_map_id")) if world_model is not None else None
    return (region or {}).get("refinement_root_planet_id")


def city_bounds(city):
    bounds = city.get("bounds") or {}
    return {key: float(bounds[key]) for key in ("min_x", "max_x", "min_y", "max_y")}


def _profiles(world_model, floras):
    resolved = getattr(world_model, "resolved_species_entity", None)
    profiles = {}
    for flora in floras.values():
        for species_id in flora.species():
            if species_id not in profiles:
                entity = (resolved(species_id) if callable(resolved) else None) or world_model.get_entity(species_id)
                if entity:
                    profiles[species_id] = profile_from_entity(entity)
    return profiles


def city_vegetation(world_model, city, substrate, cells=VEGETATION_CELLS):
    """``(vegetation, profiles, spacing by species)`` of a city's ground, or ``None`` where no biome has a flora."""
    planet_id = city_planet_id(world_model, city)
    floras = planet_floras(world_model, planet_id) if planet_id else {}
    floras = {key: flora for key, flora in floras.items() if flora.records}
    if not floras or substrate is None:
        return None
    profiles = _profiles(world_model, floras)
    bounds = city_bounds(city)
    # The planet's seed, not the city's: the woods of a piece of ground are the same on every map of it.
    vegetation = resident_vegetation(substrate, bounds, profiles, floras, cells=cells, seed=planet_seed(planet_id))
    # The ground one plant takes is the Biosphere's own figure, from the planet's kept individuals.
    ecology = BiosphereEcology(bounds, profiles.values())
    ecology.pictures = planet_plant_pictures(world_model, planet_id)
    spacing = {species_id: ecology.spacing_m(profiles[species_id]) for species_id in vegetation.cover}
    return vegetation, profiles, spacing


def pixel_px(px_per_m):
    """How many screen pixels one painted pixel takes at a scale: one close in, more the further out."""
    return min(COARSEST_PIXEL_PX, max(1.0, 1.0 + 0.5 * math.log2(FINEST_PX_PER_M / max(px_per_m, 1e-6))))


def _picture_size(bounds, long_side_px):
    width_m, height_m = bounds["max_x"] - bounds["min_x"], bounds["max_y"] - bounds["min_y"]
    px_per_m = long_side_px / max(width_m, height_m)
    return (max(2, round(width_m * px_per_m)), max(2, round(height_m * px_per_m))), px_per_m


def _tint(covers, colours, strength, peak_alpha):
    """An RGBA picture of several covers on one lattice: their mixed colour, as opaque as they are dense."""
    total = np.zeros(covers[0].shape)
    colour = np.zeros(covers[0].shape + (3,))
    for cover, tone in zip(covers, colours):
        total += cover
        colour += cover[..., None] * tone
    # Blue first: the order pygame's own pictures and the display keep, which blits many times faster than any other.
    bgra = np.zeros(total.shape + (4,), dtype=np.uint8)
    bgra[..., :3] = np.clip(colour / np.maximum(total, 1e-9)[..., None], 0, 255)[..., ::-1]
    bgra[..., 3] = np.clip(total * strength, 0.0, 1.0) * peak_alpha
    return pygame.image.frombuffer(bgra.tobytes(), (bgra.shape[1], bgra.shape[0]), "BGRA")


def ground_cover_picture(vegetation, colours, long_side_px=OVERVIEW_LONG_SIDE_PX):
    """Herbs, grass and what creeps, from above: one colour per piece of ground, as dense as their cover.

    ``colours`` maps species ids to the colour each is seen in.
    """
    low = [species_id for species_id, layer in vegetation.layers.items() if layer in LOW_LAYERS]
    if not low:
        return None
    size, _px_per_m = _picture_size(vegetation.bounds, long_side_px)
    (columns, rows), _px_per_m = _picture_size(vegetation.bounds, min(long_side_px, GROUND_COVER_LONG_SIDE_PX))
    bounds = vegetation.bounds
    x, y = np.meshgrid(bounds["min_x"] + (np.arange(columns) + 0.5) * (bounds["max_x"] - bounds["min_x"]) / columns,
                       bounds["min_y"] + (np.arange(rows) + 0.5) * (bounds["max_y"] - bounds["min_y"]) / rows)
    tint = _tint([vegetation.cover_at(species_id, x, y) for species_id in low],
                 [np.asarray(colours[species_id], dtype=np.float64) for species_id in low], 1.0, 185)
    return pygame.transform.smoothscale(tint, size)


class PlantField:
    """The tall plants of a piece of ground, each its species' own picture from above, painted at the scale looked at."""

    def __init__(self, vegetation, profiles, spacing, pictures=None, seed=0, overview_long_side_px=OVERVIEW_LONG_SIDE_PX):
        self.vegetation = vegetation
        self.pictures = pictures
        self.seed = seed
        self.bounds = dict(vegetation.bounds)
        self.width_m = self.bounds["max_x"] - self.bounds["min_x"]
        self.height_m = self.bounds["max_y"] - self.bounds["min_y"]
        # The lower first, so a tree's crown lies over a shrub's.
        self.species = sorted((species_id for species_id, layer in vegetation.layers.items() if layer in TALL_LAYERS),
                              key=lambda species_id: (profiles[species_id].mature_height_m, species_id))
        self.fallback = [foliage_colour(profiles[species_id]) for species_id in self.species]
        self.colours = [np.asarray(plant_colour(pictures, species_id, profiles[species_id]), dtype=np.float64)
                        for species_id in self.species]
        self.spacing_m = [spacing[species_id] for species_id in self.species]
        self.crown_m = [spacing[species_id] * CROWN_SHARE for species_id in self.species]
        self._masters, self._stamps, self._stamp_pixels = {}, {}, 0
        self._tiles = {}
        self.overview_size, self.overview_px_per_m = _picture_size(self.bounds, overview_long_side_px)
        self.overview = self.paint(self.bounds["min_x"], self.bounds["min_y"], self.overview_px_per_m, self.overview_size)
        # The overview serves until one of its pixels would take more screen pixels than any painted pixel may.
        self.tiles_from_px_per_m = self.overview_px_per_m * COARSEST_PIXEL_PX

    def __bool__(self):
        return bool(self.species)

    def plants_in(self, window, kinds=None):
        """The plants whose crown or shadow reaches a window: ``(kind, x, y, crown radius in metres)``, in drawing order.

        ``kind`` numbers ``self.species``; ``kinds`` narrows to some of them.
        """
        found = []
        for kind in (range(len(self.species)) if kinds is None else kinds):
            reach = self.crown_m[kind] * 1.4
            x, y, share = self.vegetation.plants(
                self.species[kind], self.spacing_m[kind], self.seed,
                window=(window[0] - reach, window[1] - reach, window[2] + reach, window[3] + reach))
            order = np.argsort(y, kind="stable")  # from the far edge to the near
            found.append((np.full(len(x), kind, dtype=np.int64), x[order], y[order], self.crown_m[kind] * share[order]))
        if not found:
            return np.empty(0, dtype=np.int64), np.empty(0), np.empty(0), np.empty(0)
        return tuple(np.concatenate(column) for column in zip(*found))

    # -- the picture of one plant -----------------------------------------
    def _plain_crown(self, kind, variant):
        """A crown in a species' colour, for one whose own picture shows nothing from above."""
        radius = 48
        picture = pygame.Surface((radius * 2 + 16, radius * 2 + 16), pygame.SRCALPHA)
        centre = radius + 8
        digest = hashlib.sha256(f"{self.species[kind]}:{variant}".encode("utf-8")).digest()
        for scale, shift, factor in ((1.0, 0.0, 0.74), (0.84, -0.07, 1.0), (0.46, -0.21, 1.22)):
            colour = (*(int(v) for v in np.clip(self.fallback[kind] * factor, 0, 255)), 255)
            at = centre + radius * shift
            pygame.draw.circle(picture, colour, (at, at), radius * scale * 0.70)
            for step in range(6):
                uneven = 0.82 + 0.30 * digest[1 + step] / 255.0
                angle = digest[0] / 255.0 * math.tau + step * math.tau / 6
                pygame.draw.circle(picture, colour, (at + math.cos(angle) * radius * scale * 0.38 * uneven,
                                                     at + math.sin(angle) * radius * scale * 0.38 * uneven),
                                   radius * scale * 0.55 * uneven)
        return picture

    def _master(self, kind, variant):
        key = (kind, variant)
        if key not in self._masters:
            picture = plant_picture(self.pictures, self.species[kind], variant)
            self._masters[key] = picture if picture is not None else self._plain_crown(kind, variant)
        return self._masters[key]

    def _stamp(self, kind, look, size_px):
        """A plant as it is laid on the field: ``(picture with its shadow, half its width, half its height)``.

        ``look`` is which of the species' kept individuals and which of the
        eight ways it lies; ``size_px`` its longer side in painted pixels.
        """
        key = (kind, look, size_px)
        stamp = self._stamps.get(key)
        if stamp is not None:
            return stamp
        variant, way = divmod(look, WAYS)
        plant = map_sprite_at(self._master(kind, variant), size_px)
        if way >= 4:
            plant = pygame.transform.flip(plant, True, False)
        if way % 4:
            plant = pygame.transform.rotate(plant, 90 * (way % 4))
        shift = max(1, round(size_px * 0.08)) if size_px >= 6 else 0
        if shift:
            # The shadow it throws on the ground and on what is lower: its own outline, to the lower right.
            picture = pygame.Surface((plant.get_width() + shift, plant.get_height() + shift), pygame.SRCALPHA)
            picture.blit(pygame.mask.from_surface(plant, 1).to_surface(setcolor=SHADOW, unsetcolor=(0, 0, 0, 0)), (shift, shift))
            picture.blit(plant, (0, 0))
        else:
            picture = plant
        if self._stamp_pixels > STAMP_PIXELS_KEPT:
            self._stamps.clear()
            self._stamp_pixels = 0
        stamp = self._stamps[key] = (picture, plant.get_width() * 0.5, plant.get_height() * 0.5)
        self._stamp_pixels += picture.get_width() * picture.get_height()
        return stamp

    @staticmethod
    def _stepped(size_px):
        """Sizes in steps of about a tenth, so one picture serves many plants."""
        size_px = np.maximum(1.0, size_px)
        return np.maximum(1, np.round(1.1 ** np.round(np.log(size_px) / math.log(1.1)))).astype(np.int64)

    # -- painting ---------------------------------------------------------
    def paint(self, min_x, min_y, px_per_m, size):
        """A window of the field from above, on a clear ground; ``None`` where nothing tall stands in it."""
        max_x, max_y = min_x + size[0] / px_per_m, min_y + size[1] / px_per_m
        resolved = [crown * 2.0 * px_per_m >= RESOLVED_CROWN_PX for crown in self.crown_m]
        picture = None
        # What is too small to tell apart at this scale: its colour, as dense as it stands.
        faint = [number for number, shown in enumerate(resolved) if not shown]
        if faint:
            step = 2 if max(size) <= TILE_PX else 4  # a tile closely, the whole ground at once more coarsely
            columns, rows = max(2, size[0] // step), max(2, size[1] // step)
            x, y = np.meshgrid(min_x + (np.arange(columns) + 0.5) * (max_x - min_x) / columns,
                               min_y + (np.arange(rows) + 0.5) * (max_y - min_y) / rows)
            inside = ((x >= self.bounds["min_x"]) & (x <= self.bounds["max_x"])
                      & (y >= self.bounds["min_y"]) & (y <= self.bounds["max_y"]))
            covers = [np.where(inside, self.vegetation.cover_at(self.species[number], x, y), 0.0) for number in faint]
            if any(cover.any() for cover in covers):
                # Enlarged as it is: the tint is of the same pixels as the plants it turns into.
                picture = pygame.transform.scale(
                    _tint(covers, [self.colours[number] for number in faint], 1.15, 215), size)
        kind, x, y, radius_m = self.plants_in((min_x, min_y, max_x, max_y),
                                              [number for number, shown in enumerate(resolved) if shown])
        if len(x):
            size_px = self._stepped(radius_m * 2.0 * px_per_m)
            px, py = (x - min_x) * px_per_m, (y - min_y) * px_per_m
            reach = size_px * 0.7
            inside = (px + reach >= 0) & (px - reach <= size[0]) & (py + reach >= 0) & (py - reach <= size[1])
            if inside.any():
                picture = picture or pygame.Surface(size, pygame.SRCALPHA)
                # One of a few looks each, by where it stands: the same plant looks the same in every picture of it.
                look = ((np.floor(x * 7.3).astype(np.int64) * 73856093) ^ (np.floor(y * 7.3).astype(np.int64) * 19349663)
                        ) % (MAP_VARIANTS * WAYS)
                blits = []
                for plant_kind, plant_look, plant_size, cx, cy in zip(kind[inside].tolist(), look[inside].tolist(),
                                                                      size_px[inside].tolist(), px[inside].tolist(), py[inside].tolist()):
                    stamp, half_width, half_height = self._stamp(plant_kind, plant_look, plant_size)
                    blits.append((stamp, (round(cx - half_width), round(cy - half_height))))
                picture.blits(blits, doreturn=False)
        return picture

    # -- tiles ------------------------------------------------------------
    @staticmethod
    def _level(px_per_m):
        """The scale tiles are painted at for a view, in half steps of two: a painted pixel takes
        ``pixel_px`` screen pixels there, or a little more."""
        finest = round(2 * math.log2(FINEST_PX_PER_M))
        return min(finest, math.floor(2 * math.log2(max(px_per_m, 1e-6) / pixel_px(px_per_m)) + 1e-9))

    def tiles(self, window, px_per_m, budget_ms=10.0):
        """What a view of the field shows: ``[(picture, (x_m, y_m), (end_x_m, end_y_m))]``.

        ``window`` is ``(min_x, min_y, max_x, max_y)`` in metres.  Each picture
        is the part of a tile the window shows, enlarged pixel by pixel to the
        view's scale, and covers the ground from its first corner to its end,
        at least; whoever draws it cuts it at the end, for pictures with
        translucent edges laid over each other would show a line.  Tiles are
        painted as they are first seen, a few to a call (``budget_ms``); until
        one is, its piece of the overview stands in for it.
        """
        level = self._level(px_per_m)
        level_px = 2.0 ** (level / 2.0)
        tile_m = TILE_PX / level_px
        scale = px_per_m / level_px
        first_x = max(0, int((window[0] - self.bounds["min_x"]) // tile_m))
        last_x = min(math.ceil(self.width_m / tile_m) - 1, int((window[2] - self.bounds["min_x"]) // tile_m))
        first_y = max(0, int((window[1] - self.bounds["min_y"]) // tile_m))
        last_y = min(math.ceil(self.height_m / tile_m) - 1, int((window[3] - self.bounds["min_y"]) // tile_m))
        started, painted, shown = time.perf_counter(), 0, []
        for tile_y in range(first_y, last_y + 1):
            for tile_x in range(first_x, last_x + 1):
                key = (level, tile_x, tile_y)
                x_m, y_m = self.bounds["min_x"] + tile_x * tile_m, self.bounds["min_y"] + tile_y * tile_m
                tile = self._tiles.get(key)
                if tile is None:
                    if painted and (time.perf_counter() - started) * 1000.0 > budget_ms:
                        stand_in = self._from_overview(x_m, y_m, tile_m, px_per_m)
                        if stand_in is not None:
                            shown.append(stand_in)
                        continue
                    tile = self._tiles[key] = self.paint(x_m, y_m, level_px, (TILE_PX, TILE_PX)) or False
                    while len(self._tiles) > TILES_KEPT:
                        self._tiles.pop(next(iter(self._tiles)))
                    painted += 1
                else:
                    self._tiles[key] = self._tiles.pop(key)  # lately used
                if tile is not False:
                    shown.append(self._enlarged(tile, x_m, y_m, level_px, scale, window))
        return shown

    def _enlarged(self, tile, x_m, y_m, level_px, scale, window):
        """The part of a tile a view shows, each of its pixels enlarged to the view's scale as it is."""
        left = max(0, math.floor((window[0] - x_m) * level_px))
        top = max(0, math.floor((window[1] - y_m) * level_px))
        right = min(TILE_PX, math.ceil((window[2] - x_m) * level_px))
        bottom = min(TILE_PX, math.ceil((window[3] - y_m) * level_px))
        right, bottom = max(left + 1, right), max(top + 1, bottom)
        part = tile.subsurface((left, top, right - left, bottom - top))
        size = (math.ceil(part.get_width() * scale), math.ceil(part.get_height() * scale))
        if size != part.get_size():
            part = pygame.transform.scale(part, size)
        return part, (x_m + left / level_px, y_m + top / level_px), (x_m + right / level_px, y_m + bottom / level_px)

    def _from_overview(self, x_m, y_m, tile_m, px_per_m):
        if self.overview is None:
            return None
        scale = self.overview_px_per_m
        area = pygame.Rect(round((x_m - self.bounds["min_x"]) * scale), round((y_m - self.bounds["min_y"]) * scale),
                           max(1, round(tile_m * scale)), max(1, round(tile_m * scale))).clip(self.overview.get_rect())
        if area.width <= 0 or area.height <= 0:
            return None
        size = (math.ceil(area.width / scale * px_per_m) + 1, math.ceil(area.height / scale * px_per_m) + 1)
        return (pygame.transform.scale(self.overview.subsurface(area), size),
                (self.bounds["min_x"] + area.left / scale, self.bounds["min_y"] + area.top / scale),
                (self.bounds["min_x"] + area.right / scale, self.bounds["min_y"] + area.bottom / scale))


@dataclass
class CityPlantCover:
    """What the city map lays over its ground."""

    vegetation: object
    ground: object       # the low layers as one picture over the whole ground, or ``None``
    field: PlantField    # everything from two metres up, plant by plant


def city_plant_cover(world_model, city, substrate):
    """The plant cover of a city's ground, or ``None`` where nothing is established."""
    result = city_vegetation(world_model, city, substrate)
    if result is None:
        return None
    vegetation, profiles, spacing = result
    if not vegetation.cover:
        return None
    pictures = planet_plant_pictures(world_model, city_planet_id(world_model, city))
    if getattr(getattr(world_model, "loader", None), "use_ontology", False) and pictures.map_sprite_dir is None:
        # A session on the stored world keeps the pictures from above for the next one.
        pictures.map_sprite_dir = MAP_SPRITE_DIR
    # The plants are the planet's too: the tree of this map is the tree a Biosphere founded here finds.
    seed = planet_seed(city_planet_id(world_model, city))
    colours = {species_id: plant_colour(pictures, species_id, profiles[species_id])
               for species_id, layer in vegetation.layers.items() if layer in LOW_LAYERS}
    return CityPlantCover(vegetation, ground_cover_picture(vegetation, colours),
                          PlantField(vegetation, profiles, spacing, pictures, seed))
