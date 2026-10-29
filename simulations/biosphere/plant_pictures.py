"""A planet's own stock of plant pictures.

The first time a species settles on a planet, ten individuals of it are laid
down and kept at every growth stage.  From then on each plant of that species
that is not simulated in depth is shown as one of them at its own stage, so a
stand is a mix of ten shapes and seven sizes instead of copies of one plant.
A simulated plant that grows up there joins the collection.

What is kept is how each individual came to be (its seed and the conditions it
grew up in); its body at a stage is grown from that when a picture of it is
first needed, and is the same every time.  Species Sim does not shape a plant
by its light yet.  When it does, the conditions recorded here are what makes a
planet's pines compact on open ground and drawn up in a thicket.

The collection also keeps each species *from above* (``map_sprite``): the
first few individuals, full-grown, as Species Sim's top-down view draws them.
That is the picture a map places where the plant stands.  Every smaller,
coarser version a map needs is made from it (``map_sprite_at``), so a plant
seen from far off is a few pixels that still are that plant.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re

from simulations.biosphere.representatives import RepresentativeBody
from simulations.species.plant_life_timing import resolve_plant_life_timing


# Shares of full size at which an individual is kept: the steps the display has always shown.
STAGES = (0.06, 0.16, 0.30, 0.48, 0.68, 0.85, 1.0)
FOUNDERS = 10
# Plants that grew up on the planet and joined its founders; then the collection is complete.
GROWN_LIMIT = 22
# The longer side, in pixels, at which a plant is kept from above; every coarser picture is made from this one.
MAP_SPRITE_PX = 192
# Species Sim leaves out a leaf smaller than a pixel.  A plant is drawn from above large enough that its leaves are
# this many pixels long (below about three it draws none), up to a longest side; the kept picture is made from that.
TOP_VIEW_LEAF_PX = 3.8
TOP_VIEW_DRAWN_MAX_PX = 1000
# How many of a species' individuals are kept from above.  A map turns and mirrors each: eight looks apiece.
MAP_VARIANTS = 2
# In a coarser picture a pixel is plant where this much of it was (of 255): thin twigs still make a crown.
MAP_SPRITE_SOLID_ALPHA = 56
# Below this size a coarser picture is held to a few tones, as drawn pixel art is.
MAP_SPRITE_FEW_TONES_BELOW_PX = 40
# Where the pictures from above are kept between sessions, for whoever sets ``map_sprite_dir`` to it.
MAP_SPRITE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "planet_plant_pictures"

_top_view_renderer = None


def _native(picture):
    """A picture in the pixel order pygame's own surfaces keep, which blits many times faster than a loaded file's."""
    import pygame

    return pygame.image.frombuffer(pygame.image.tobytes(picture, "BGRA"), picture.get_size(), "BGRA").copy()


def top_view(body, long_side_px=MAP_SPRITE_PX):
    """A plant body from straight above, as Species Sim's top-down view draws it; ``None`` if nothing shows.

    Cut to what stands above the ground, on a clear background, its longer
    side ``long_side_px``.
    """
    import pygame
    from types import SimpleNamespace

    from simulations.species.species_renderer import (
        SpeciesRenderer, TopDownDiagnosticCamera, canopy_visible_indices, top_down_diagnostic_bounds)

    global _top_view_renderer
    if _top_view_renderer is None:
        _top_view_renderer = SpeciesRenderer(SimpleNamespace(width=640, height=640, camera=None))
    snapshot = body.render_snapshot
    bounds = top_down_diagnostic_bounds(body, snapshot)
    leaf = body.blueprint.module("leaf") if hasattr(body.blueprint, "module") else None
    leaf_length_m = float(getattr(leaf, "length_m", 0.0) or 0.0)
    drawn_px = long_side_px
    # Needles are the other way round: drawn small, Species Sim clothes each shoot whole, which is how a conifer
    # reads from above; drawn large it sets out single needles and the crown thins to its branches.
    needles = str(body.blueprint.growth.get("leaf_structure") or "") in {"needle_like", "scale_like"}
    foliage_sprays = any(c.get('planar_spray') or c.get('pendant_branchlet_sites_m') or float(c.get("foliage_spray_radius_m", 0.0) or 0.0) > 0
                         for c in getattr(snapshot, "leaf_clusters", ()) or ())
    # These cohorts already provide their collective optical footprint at
    # map scale. Supersampling sparse individual leaves and then reducing
    # them discarded that footprint, yielding an apparently leafless oak.
    if leaf_length_m > 0.0 and not needles and not foliage_sprays:
        extent_m = max(bounds[1] - bounds[0], bounds[3] - bounds[2])
        drawn_px = int(min(TOP_VIEW_DRAWN_MAX_PX, max(long_side_px, math.ceil(extent_m * TOP_VIEW_LEAF_PX / leaf_length_m))))
    side = drawn_px + 8
    panel = pygame.Surface((side, side), pygame.SRCALPHA)
    camera = TopDownDiagnosticCamera(drawn_px + 48, drawn_px + 48, bounds)  # the camera keeps a 48 px margin
    camera.screen_center_x = camera.screen_center_y = side * 0.5
    # A diagnostic fungal body has no separately rendered host. Include its
    # explicit test support in the picture; real host wood is composed by the
    # Biosphere scene and must not be stamped into the fungus sprite again.
    woods = snapshot.stats.get("fungal_substrates", ())
    draw_fixture = bool(body.blueprint.growth.get("fungal_grammar_version") and woods
                        and all(wood.get("id") == "wood_test_asset" for wood in woods))
    _top_view_renderer._draw_individual(
        panel, body, camera=camera, clear=False, cache=False, snapshot=snapshot,
        visible_indices=canopy_visible_indices(body, snapshot), draw_ground_line=False,
        draw_environment=draw_fixture)
    filled = panel.get_bounding_rect(min_alpha=1)
    if filled.width <= 0 or filled.height <= 0:
        return None
    picture = panel.subsurface(filled).copy()
    return map_sprite_at(picture, long_side_px) if max(filled.size) > long_side_px else picture


def map_sprite_at(picture, longer_side_px):
    """A plant's picture from above at a size: the coarser, the fewer pixels and tones, and still that plant.

    At its own size or larger the picture is given as it is (enlarged without
    smoothing).  Smaller, each pixel takes the colour of the plant in it and
    is either plant or not, so a crown of thin twigs stays a crown.
    """
    import numpy as np
    import pygame

    longer = max(picture.get_size())
    size = (max(1, round(picture.get_width() * longer_side_px / longer)),
            max(1, round(picture.get_height() * longer_side_px / longer)))
    if size == picture.get_size():
        return picture
    if longer_side_px > longer:
        return pygame.transform.scale(picture, size)
    small = pygame.transform.smoothscale(picture.premul_alpha(), size)
    colour, alpha = pygame.surfarray.pixels3d(small), pygame.surfarray.pixels_alpha(small)
    cover = alpha.astype(np.float32)
    tone = np.clip(colour.astype(np.float32) * 255.0 / np.maximum(cover, 1.0)[..., None], 0, 255)
    solid = cover >= min(MAP_SPRITE_SOLID_ALPHA, float(cover.max()))
    if longer_side_px < MAP_SPRITE_FEW_TONES_BELOW_PX:
        tone = np.floor(tone / 20.0) * 20.0 + 10.0
    colour[...] = tone.astype(np.uint8)
    alpha[...] = np.where(solid & (cover > 0), 255, 0).astype(np.uint8)
    del colour, alpha
    return small


def above_ground_extent(snapshot, bounds):
    """Width and height, in metres, of the part of a plant body that stands above the ground.

    ``bounds`` is the body's whole extent as the side view sees it (left,
    right, lowest, highest), roots included.
    """
    from simulations.species.species_simulation import SCREEN_DEPTH_PROJECTION

    across = [
        float(placement[2]) + float(placement[3]) * SCREEN_DEPTH_PROJECTION
        for placement in (getattr(snapshot, "placements", None) or ())
        if len(placement) > 4 and float(placement[4]) >= 0.0
    ]
    full = bounds[1] - bounds[0]
    width = min(full, max(across) - min(across)) if across else full
    return max(0.08, width), max(0.08, float(bounds[3]))


def stage_of(share):
    """The kept stage nearest to a share of full size."""
    share = max(0.0, min(1.0, float(share)))
    return min(STAGES, key=lambda stage: abs(stage - share))


def _show_score(body, age_days):
    body.real_age_days = age_days
    state = body.life_state(age_days)
    return (2.0 * float(state.get("leaf_factor", 1.0)) + float(state.get("reproductive_factor", 0.0) or 0.0)
            + 0.5 * float(state.get("fruiting_factor", 0.0) or 0.0))


def specimen_age_days(body, maturity, prime=0.25):
    """Real age of a plant shown at ``maturity`` of its full size.

    A full-grown plant stands ``prime`` of the way through its adult life.
    Where the species authors a year of its own, the plant is moved within
    that year to when it is in leaf and, if it can be, in flower or fruit: a
    kept picture has no season of its own to follow.
    """
    timing = body.life_timing
    grown = timing.maturity_days
    if maturity < 1.0:
        low, high, age = 0.0, grown, grown * maturity
    else:
        low, high = grown, max(grown + 1.0, timing.senescence_start_days)
        age = low + (high - low) * prime
    cycle = (body.blueprint.growth.get("reproductive_profile") or {}).get("cycle_days")
    if not cycle:
        return age
    year = math.floor(age / cycle) * cycle
    options = [age] + [day for day in (year + cycle * step / 72.0 for step in range(72)) if low <= day < high]
    return max(options, key=lambda day: (round(_show_score(body, day), 3), -abs(day - age)))


def grow_specimen(world_model, species_id, seed, maturity, environment=None, prime=0.25):
    """A plant body at a share of its full size, in the season it looks its best."""
    body = RepresentativeBody(
        world_model=world_model, species_id=species_id,
        species_entity=world_model.get_entity(species_id) or {"id": species_id, "type": "species"},
        seed=seed, environment=environment,
    )
    body.lod = 1
    body.life_timing = resolve_plant_life_timing(body.species_entity, body.blueprint.growth)
    age = specimen_age_days(body, maturity, prime)
    body.real_age_days = age
    body.set_age(min(body.life_timing.developmental_days(age), body.max_age_days))
    return body


@dataclass
class PictureIndividual:
    seed: int
    origin: str  # "founder", or "grown" for a simulated plant that came of age here
    conditions: dict = field(default_factory=dict)


class PlanetPlantPictures:
    """The individuals a planet's plants are drawn as, species by species."""

    BODY_CACHE = 64

    def __init__(self, world_model, planet_id=None):
        self.world_model = world_model
        self.planet_id = planet_id
        self.individuals: dict[str, list[PictureIndividual]] = {}
        self._bodies = OrderedDict()
        self._widths = {}
        self._width_file = None
        self._map_sprites = {}
        # A folder to keep the pictures from above in between sessions; ``None`` keeps them for this session only.
        self.map_sprite_dir = None
        # Counts every change, for whoever keeps pictures made from this collection.
        self.revision = 0

    def settled(self, species_id):
        return species_id in self.individuals

    def settle(self, species_id, conditions=None):
        """Lay down a species' first individuals where it first takes root; later it finds them there."""
        if species_id in self.individuals:
            return False
        founders = []
        for index in range(FOUNDERS):
            digest = hashlib.sha256(f"{self.planet_id}:{species_id}:founder:{index}".encode("utf-8")).digest()
            founders.append(PictureIndividual(int.from_bytes(digest[:2], "big"), "founder", dict(conditions or {})))
        self.individuals[species_id] = founders
        self.revision += 1
        return True

    def count(self, species_id):
        return len(self.individuals.get(species_id, ()))

    def seed(self, species_id, variant):
        individuals = self.individuals.get(species_id)
        if not individuals:
            self.settle(species_id)
            individuals = self.individuals[species_id]
        return individuals[int(variant) % len(individuals)].seed

    def variant_of(self, species_id, seed):
        """Which of the species' individuals has this seed, or ``None``."""
        for index, individual in enumerate(self.individuals.get(species_id, ())):
            if individual.seed == seed:
                return index
        return None

    def add_grown(self, species_id, seed, conditions=None):
        """Take in a plant that came of age on the planet; returns which individual it now is."""
        known = self.variant_of(species_id, seed)
        if known is not None:
            return known
        individuals = self.individuals.setdefault(species_id, [])
        if sum(individual.origin == "grown" for individual in individuals) >= GROWN_LIMIT:
            return None
        individuals.append(PictureIndividual(int(seed), "grown", dict(conditions or {})))
        self.revision += 1
        return len(individuals) - 1

    def growth_environment(self, species_id, individual):
        """What stands around a kept individual as it grows (a support for a climber); nothing yet."""
        return None

    def body(self, species_id, variant, share):
        """The body of one of the species' individuals at the kept stage nearest ``share``."""
        individuals = self.individuals.get(species_id)
        if not individuals:
            self.settle(species_id)
            individuals = self.individuals[species_id]
        variant = int(variant) % len(individuals)
        stage = stage_of(share)
        key = (species_id, variant, stage, getattr(self.world_model, "repository_revision", 0))
        body = self._bodies.get(key)
        if body is None:
            individual = individuals[variant]
            body = grow_specimen(self.world_model, species_id, individual.seed, stage,
                                 self.growth_environment(species_id, individual))
            self._bodies[key] = body
            while len(self._bodies) > self.BODY_CACHE:
                self._bodies.popitem(last=False)
        else:
            self._bodies.move_to_end(key)
        return body

    def _map_sprite_path(self, species_id, variant):
        """Where an individual's picture from above is kept: named by what it was grown from, so a changed species is drawn anew."""
        if self.map_sprite_dir is None:
            return None
        resolved = getattr(self.world_model, "resolved_species_entity", None)
        entity = (resolved(species_id) if callable(resolved) else None) or self.world_model.get_entity(species_id) or {}
        materialize = getattr(entity, "materialize", None)
        entity = materialize() if callable(materialize) else entity
        described = json.dumps(dict(entity), sort_keys=True, default=str)
        digest = hashlib.sha256(
            f"{described}:{self.seed(species_id, variant)}:{MAP_SPRITE_PX}:top-view-1".encode("utf-8")).hexdigest()[:16]
        planet = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(self.planet_id))
        return Path(self.map_sprite_dir) / planet / f"{species_id}_{variant}_{digest}.png"

    def map_sprite(self, species_id, variant=0):
        """One of the species' individuals, full-grown, from straight above; ``None`` if it shows nothing from there.

        The picture a map places.  Made once: kept for the session, and
        between sessions where ``map_sprite_dir`` is set.
        """
        import pygame

        self.seed(species_id, 0)  # settles the species if this is the first that is seen of it
        variant = int(variant) % min(MAP_VARIANTS, self.count(species_id))
        key = (species_id, variant, getattr(self.world_model, "repository_revision", 0))
        if key not in self._map_sprites:
            path = self._map_sprite_path(species_id, variant)
            picture = None
            if path is not None and path.exists():
                try:
                    picture = _native(pygame.image.load(str(path)))
                except (pygame.error, OSError, ValueError):
                    picture = None
            if picture is None:
                picture = top_view(self.body(species_id, variant, 1.0))
                if picture is not None and path is not None:
                    try:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        pygame.image.save(picture, str(path))
                    except (pygame.error, OSError):
                        pass
            self._map_sprites = {kept: value for kept, value in self._map_sprites.items() if kept[2] == key[2]}
            self._map_sprites[key] = picture
        return self._map_sprites[key]

    def body_width(self, species_id):
        """How wide a full-grown plant of the species stands above the ground: its first kept individual's width, in metres.

        A rose is a bush of two metres; a creeping thistle or a bamboo is a
        clone that fills a room.
        """
        if species_id not in self._widths:
            kept, name = self._kept_widths(species_id)
            if name in kept:
                self._widths[species_id] = float(kept[name])
            else:
                from simulations.species.species_renderer import diagnostic_cell_bounds

                snapshot = self.body(species_id, 0, 1.0).render_snapshot
                self._widths[species_id] = above_ground_extent(snapshot, diagnostic_cell_bounds(snapshot))[0]
                self._keep_width(name, self._widths[species_id])
        return self._widths[species_id]

    def _kept_widths(self, species_id):
        """The widths kept between sessions beside the pictures from above, and the name this species' is kept by.

        Growing a body to measure it takes up to seconds; the name tells
        what the body was grown from, as a picture's file name does.
        """
        path = self._map_sprite_path(species_id, 0)
        if path is None:
            return {}, None
        if self._width_file is None or self._width_file[0] != path.parent:
            kept = {}
            try:
                kept = json.loads((path.parent / "body_widths.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            self._width_file = (path.parent, kept if isinstance(kept, dict) else {})
        return self._width_file[1], path.stem

    def _keep_width(self, name, width):
        if name is None or self._width_file is None:
            return
        folder, kept = self._width_file
        kept[name] = float(width)
        try:
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "body_widths.json").write_text(json.dumps(kept, indent=0, sort_keys=True), encoding="utf-8")
        except OSError:
            pass

    def summary(self):
        return {species_id: {"founders": sum(i.origin == "founder" for i in individuals),
                             "grown": sum(i.origin == "grown" for i in individuals)}
                for species_id, individuals in self.individuals.items()}


# The colour a species is told apart by, drawn towards that of foliage: for one that shows nothing from above.
FOLIAGE = (58.0, 86.0, 46.0)


def foliage_colour(profile):
    import numpy as np

    return 0.72 * (0.58 * np.asarray(profile.color, dtype=np.float64) + 0.42 * np.asarray(FOLIAGE))


def plant_picture(pictures, species_id, variant=0):
    """A species' individual from above out of a planet's pictures, or ``None`` where it has none to give."""
    if pictures is None:
        return None
    try:
        return pictures.map_sprite(species_id, variant)
    except Exception:  # a species Species Sim cannot draw from above must not take the map down with it
        return None


def plant_colour(pictures, species_id, profile):
    """The colour of a species seen from above and far off: that of its own picture."""
    import pygame

    picture = plant_picture(pictures, species_id)
    if picture is None:
        return foliage_colour(profile)
    plant = pygame.surfarray.array_alpha(picture) > 0
    return pygame.surfarray.array3d(picture)[plant].mean(axis=0) if plant.any() else foliage_colour(profile)


def planet_plant_pictures(world_model, planet_id):
    """The picture collection of a planet, shared by every Biosphere opened on it."""
    holder = getattr(world_model, "base_world", None) or world_model
    try:
        collections = holder.__dict__.setdefault("_planet_plant_pictures", {})
    except AttributeError:  # a world stand-in without attributes of its own
        return PlanetPlantPictures(world_model, planet_id)
    if planet_id not in collections:
        collections[planet_id] = PlanetPlantPictures(world_model, planet_id)
    return collections[planet_id]
