"""Render SpeciesSim plant snapshots as grounded sprites on a BioSim map."""

from __future__ import annotations

import math
import hashlib
import json
import time
import zlib
from collections import OrderedDict
from types import SimpleNamespace

import numpy as np
import pygame

from simulations.species.species_renderer import (
    DiagnosticCamera, IsometricDiagnosticCamera, SpeciesRenderer,
    canopy_visible_indices, diagnostic_cell_bounds, top_down_diagnostic_bounds,
)
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.surface_growth import surface_palette
from simulations.biosphere.plant_pictures import above_ground_extent, map_sprite_at, plant_picture
from simulations.biosphere.potential_vegetation import plant_number
from simulations.biosphere.surroundings import SWARD_PLANTS_FROM_PX
from simulations.biosphere.vegetation import VegetationSampler, population_abundances
from simulations.world_gen.true_color import render_true_color_surface


class BiosphereBuilderRenderer:
    """Isometric scene adapter for continuous ecology and SpeciesSim plants."""

    # Generated terrain is meshed in screen space: a cell's diamond is twice
    # this wide.  The coarse size keeps panning fluid; the fine one is drawn
    # once the view rests and is then reused.
    GROUND_CELL_PX = 6.0
    GROUND_CELL_PX_MOVING = 22.0
    # The fine mesh costs a few hundred milliseconds: wait until the view has
    # stopped, not for every pause between two wheel notches.
    GROUND_SETTLE_SECONDS = 0.25
    GROUND_MAX_CELLS_PER_AXIS = 320
    FALLBACK_GROUND_RGB = (115, 105, 81)

    def __init__(self, app_view, species_renderer=None):
        self.app_view = app_view
        self.species_renderer = species_renderer or SpeciesRenderer(app_view)
        self._simulation_cache = {}
        self._art_blueprints = {}
        self._surface_cache = {}
        self._display_sprite_cache = {}
        self._display_canonical = {}
        self._sprites_painted = 0
        self._frame_started = 0.0
        self._true_scale = False
        self._world_map_cache = None
        self._soil_tint_cache = None
        self._ground_mips = {}
        self._frame_surfaces = {}
        self._frame_surface_context = None
        self._vegetation_sampler = VegetationSampler()
        self._terrain_surface_cache = {}
        self._ground_view = None
        self._ground_changed_at = float("-inf")
        self._ground_moving = None
        self._ground_rest = None
        self._ground_texture_cache = {}
        self._ground_gain_cache = {}
        self._soil_overlay_cache = None
        self._rest_layers = {}
        self._ground_pixel_cache = {}
        self._moving_ground = None
        self._tuft_pictures = {}
        self._shadow_pictures = {}
        self._plant_layer_attempt = 0
        self._stage_paths = {}
        self._mirror_pictures = {}
        self._enlarged_pictures = OrderedDict()
        self._see_through_pictures = {}
        self._enlarged_pixels = 0
        self._view_pictures = OrderedDict()
        self._view_pixels = 0
        self._stage_absent = set()
        self._patch_textures = {}
        self._clump_ranks = None
        self._ground_cells = {}

    def _species_case(self, biosphere_sim, instance):
        representative_id = instance.get("representative_id")
        if "display_maturity" not in instance:
            representative_id = representative_id or instance.get("visual_source_id")
        if representative_id:
            representative_case = getattr(
                biosphere_sim,
                "get_representative_species_simulation",
                lambda _representative_id: None,
            )(representative_id)
            if representative_case is not None:
                return representative_case
        species_id = instance["species_id"]
        age_bucket = int(instance.get("age_bucket", 1))
        variant = int(instance.get("variant", 0))
        pictures = getattr(biosphere_sim, "plant_pictures", None)
        if pictures is not None and instance.get("display_maturity") is not None:
            # One of the individuals the planet keeps of this species, at the stage nearest to the plant's.
            return pictures.body(species_id, variant, instance["display_maturity"])
        entity = biosphere_sim.world_model.get_entity(species_id) or {"id": species_id, "type": "species"}
        revision = getattr(biosphere_sim.world_model, "repository_revision", 0)
        display_maturity = instance.get("display_maturity")
        key = id(biosphere_sim.world_model), species_id, age_bucket, variant, revision, display_maturity
        cached = self._simulation_cache.get(key)
        if cached is not None:
            return cached
        case = SpeciesSimulation(
            world_model=biosphere_sim.world_model,
            species_id=species_id,
            species_entity=entity,
            seed=1709 + variant * 101,
        )
        case.lod = 1
        maturity = display_maturity if display_maturity is not None else (0.18, 0.38, 0.62, 0.88)[max(0, min(3, age_bucket))]
        case.set_age(case.mature_age_days * maturity)
        self._simulation_cache[key] = case
        if len(self._simulation_cache) > 96:
            self._simulation_cache.pop(next(iter(self._simulation_cache)))
        return case

    @classmethod
    def _target_height_px(cls, case, instance, camera, world_units_to_meters):
        return cls._target_height_for(
            max(0.08, float(case.render_snapshot.bounds_m[5] or 0.0)), instance, camera, world_units_to_meters)

    @staticmethod
    def _target_height_for(above_ground_m, instance, camera, world_units_to_meters):
        pixels_per_metre = float(getattr(camera, "zoom", 1.0) or 1.0) / max(1e-9, float(world_units_to_meters or 1.0))
        physical_height = above_ground_m * pixels_per_metre
        form = str(instance.get("growth_form") or "forb")
        semantic_floor = {"tree": 30, "shrub": 24, "graminoid": 18, "forb": 20, "aquatic": 22, "succulent": 22}.get(form, 20)
        if getattr(camera, "true_scale", False):
            # A landscape view: plants keep their real size against the
            # ground.  The legibility floor shrinks as the view pulls back, so
            # a stand reads as cover instead of a few giant plants.
            semantic_floor = max(3, round(semantic_floor * max(0.22, min(1.0, pixels_per_metre / 6.0))))
            # And never many times its size: a herb half as tall again as it is still reads beside a tree
            # drawn true; one drawn six times its size makes the tree a shrub.
            semantic_floor = max(3, min(semantic_floor, round(physical_height * 1.5)))
        abundance = round(max(0.0, min(1.0, float(instance.get("abundance", 0.0) or 0.0))) * 5) / 5
        height_cap = max(84, int(getattr(camera, "sprite_height_cap", 84) or 84))
        if getattr(camera, "enlarged_to", None):
            # A view that enlarges kept pictures (``_enlarged``) draws a plant at its own size up to this height.
            height_cap = max(height_cap, int(camera.enlarged_to))
        if "display_maturity" in instance:
            # Tall species hit the map height cap even while young; retain a
            # visible stage difference instead of making every crown equally tall.
            stage = max(0.0, min(1.0, instance["display_maturity"]))
            height_cap = max(6, round(height_cap * stage ** 0.65))
            semantic_floor = min(semantic_floor, height_cap)
        height = max(semantic_floor, min(height_cap, round(max(physical_height, semantic_floor) * (0.72 + abundance * 0.38))))
        return max(5 if "display_maturity" in instance else 8, round(height * instance.get("visual_scale", 1.0)))

    # Every plant picture is grown and painted once at full size; seasons,
    # zooming and the per-plant size mix only rescale it.  Display-only plants
    # come from a small ladder of growth stages, representatives from the body
    # they last grew.
    DISPLAY_MATURITY_STEPS = 16
    # How many full-size pictures are kept; the oldest goes first.  Room for
    # the planet's kept individuals of a dozen species at every stage.
    DISPLAY_PICTURE_LIMIT = 1200
    # The closest a view gets, in pixels per metre: full-size pictures are painted for it.
    FULL_SIZE_PX_PER_M = 400.0
    # Painting one woody plant takes tens of milliseconds.  With a budget set
    # (the app sets one) a frame paints new pictures only this long; plants
    # still waiting keep their previous picture, or appear a frame later.
    sprite_budget_ms = None

    def _over_sprite_budget(self):
        return (self.sprite_budget_ms is not None and self._sprites_painted > 0
                and (time.perf_counter() - self._frame_started) * 1000.0 > self.sprite_budget_ms)

    def _instance_art_revision(self, biosphere_sim, instance):
        """Check artwork without regrowing an evicted scenery body each frame."""
        representative = getattr(biosphere_sim, "get_representative_species_simulation", lambda _id: None)(
            instance.get("representative_id"))
        if representative is not None:
            return self.species_renderer._visual_asset_revision(representative)
        world = biosphere_sim.world_model
        key = (id(world), getattr(world, "repository_revision", 0), instance["species_id"])
        blueprint = self._art_blueprints.get(key)
        if blueprint is None:
            blueprint = self._species_case(biosphere_sim, instance).blueprint
            if len(self._art_blueprints) >= 256:
                self._art_blueprints.clear()
            self._art_blueprints[key] = blueprint
        return self.species_renderer._visual_asset_revision(SimpleNamespace(blueprint=blueprint))

    def _full_size_sprite(self, biosphere_sim, key, token, instance, height_cap, stale_ok):
        """``(sprite, anchor, height above ground in metres, full pixel height)`` or ``None`` if deferred."""
        cached = self._display_canonical.get(key)
        if cached is not None and cached[0] == token:
            return cached[1]
        kept_plant = key[0] == "stage"
        # A kept plant painted in an earlier session is taken from where the planet's pictures are kept.
        full = self._kept_stage_picture(biosphere_sim, instance, height_cap) if kept_plant else None
        if full is None:
            if self._over_sprite_budget():
                return cached[1] if cached is not None and stale_ok else None
            case = self._species_case(biosphere_sim, instance)
            # Close enough that the plant is drawn as large as the view ever shows it.
            close = SimpleNamespace(zoom=self.FULL_SIZE_PX_PER_M, sprite_height_cap=height_cap,
                                    true_scale=self._true_scale)
            above_ground_m = max(0.08, float(case.render_snapshot.bounds_m[5] or 0.0))
            # Representatives and scenery consume the same authored organs:
            # paint fine foliage before reduction and give both the scene's light.
            sprite, anchor = self._paint_stage_picture(biosphere_sim, case, instance, close, above_ground_m)
            self._sprites_painted += 1
            # The height the plant was painted at, which a wide plant held to the
            # width cap does not reach: measured, so that a smaller view of it is
            # scaled from what the picture holds.
            full = (sprite, anchor, above_ground_m, max(1, round(anchor[1])))
            if kept_plant:
                self._keep_stage_picture(biosphere_sim, instance, height_cap, full)
        if len(self._display_canonical) >= self.DISPLAY_PICTURE_LIMIT and key not in self._display_canonical:
            self._display_canonical.pop(next(iter(self._display_canonical)))
        self._display_canonical[key] = (token, full)
        return full

    # A kept plant is painted this many pixels to the length of a leaf (as its picture from above is), at
    # most this tall, with all its leaves, and reduced to the size it is kept at.
    STAGE_LEAF_PX = 3.8
    STAGE_PAINT_MAX_PX = 1000

    def _stage_paint_heights(self, biosphere_sim, case, instance, close, above_ground_m):
        """``(kept, painted)``: the height a kept plant's picture is kept at, and the height it is painted at."""
        kept = self._target_height_px(case, instance, close, biosphere_sim.world_units_to_meters)
        leaf = case.blueprint.module("leaf") if hasattr(case.blueprint, "module") else None
        leaf_length_m = float(getattr(leaf, "length_m", 0.0) or 0.0)
        needles = str(case.blueprint.growth.get("leaf_structure") or "") in {"needle_like", "scale_like"}
        foliage_cohorts = bool(getattr(case.render_snapshot, "leaf_clusters", ()) or ())
        painted = kept
        # These cohorts already carry a collective canopy footprint at small
        # sizes. Supersampling turns it into sparse single leaves and loses it.
        if leaf_length_m > 0.0 and not needles and not foliage_cohorts:
            painted = int(min(self.STAGE_PAINT_MAX_PX, max(kept, math.ceil(above_ground_m * self.STAGE_LEAF_PX / leaf_length_m))))
        return kept, max(kept, painted)

    def _paint_stage_picture(self, biosphere_sim, case, instance, close, above_ground_m, look_px=None):
        """The picture of a kept plant at a stage: ``(picture, where its foot lies in it)``.

        Individually represented leaves are painted large enough to survive
        reduction. Foliage cohorts and needles keep their collective optical
        footprint at the kept size. The result is reduced as
        a map reduces a plant's picture (``plant_pictures.map_sprite_at``):
        what is thin in it stays, in few tones.  Needles are the other way
        round: drawn small, each shoot is clothed whole.

        ``look_px``: the height of the painting whose look this one keeps (its kept picture's): painted
        larger, it is that painting in finer pixels (Species Sim's ``pixel_scale``).
        """
        kept, painted = self._stage_paint_heights(biosphere_sim, case, instance, close, above_ground_m)
        larger = SimpleNamespace(
            zoom=close.zoom, true_scale=close.true_scale,
            sprite_height_cap=max(close.sprite_height_cap, math.ceil(close.sprite_height_cap * painted / max(1, kept))),
            sprite_width_cap=getattr(close, "sprite_width_cap", None),
            pixel_scale=max(1.0, painted / look_px) if look_px else 1.0)
        sprite, anchor = self._render_sprite_surface(biosphere_sim, instance, larger, foliage_sample_cap=None)
        factor = kept / max(1.0, anchor[1])
        if factor >= 0.95:
            return self._lit(sprite), anchor
        reduced = map_sprite_at(sprite, max(1, round(max(sprite.get_size()) * factor)))
        return self._lit(reduced), (anchor[0] * reduced.get_width() / sprite.get_width(),
                                    anchor[1] * reduced.get_height() / sprite.get_height())

    # Every kept plant stands in one light: this much lighter at its top and darker at its foot.  And no
    # colour is purer or lighter than these (of 1): a species drawn in a glowing colour is brought in.
    CROWN_LIGHT = (1.08, 0.84)
    MOST_SATURATION, MOST_VALUE = 0.62, 0.80

    @classmethod
    def _calmed(cls, colour):
        """Colours (0..255, last axis red, green, blue) held to the range all plants are drawn in."""
        colour = np.asarray(colour, dtype=np.float32) / 255.0
        value = colour.max(axis=-1, keepdims=True)
        saturation = (value - colour.min(axis=-1, keepdims=True)) / np.maximum(value, 1e-6)
        colour = value - (value - colour) * np.where(saturation > cls.MOST_SATURATION,
                                                     cls.MOST_SATURATION / np.maximum(saturation, 1e-6), 1.0)
        return colour * np.where(value > cls.MOST_VALUE, cls.MOST_VALUE / np.maximum(value, 1e-6), 1.0) * 255.0

    def _lit(self, sprite):
        """A plant's picture in the light and the range of colour all of them stand in."""
        lit = sprite.copy()
        colour = pygame.surfarray.pixels3d(lit)
        light = np.linspace(self.CROWN_LIGHT[0], self.CROWN_LIGHT[1], colour.shape[1], dtype=np.float32)[None, :, None]
        colour[...] = np.clip(self._calmed(colour) * light, 0.0, 255.0).astype(np.uint8)
        del colour
        return lit

    # The tallest a landscape view draws a plant, in pixels.  Its picture is kept much smaller
    # (``isometric_sprite_height_cap``) and enlarged for the view, each of its pixels a block; the enlarged
    # ones are kept up to this many pixels in all, the longest unused going first.
    ENLARGED_TO_PX = 1400
    ENLARGED_PIXELS_KEPT = 40_000_000

    def _enlarged(self, sprite, anchor, factor):
        """A kept picture larger than it is kept: a tree seen from close stands at its size beside the herbs."""
        key = (id(sprite), round(factor, 2))
        kept = self._enlarged_pictures.get(key)
        if kept is not None and kept[2] is sprite:
            self._enlarged_pictures.move_to_end(key)
            return kept[0], kept[1]
        if kept is not None:
            self._enlarged_pixels -= kept[0].get_width() * kept[0].get_height()
        size = (max(1, round(sprite.get_width() * factor)), max(1, round(sprite.get_height() * factor)))
        kept = (pygame.transform.scale(sprite, size), (anchor[0] * factor, anchor[1] * factor), sprite)
        self._enlarged_pictures[key] = kept
        self._enlarged_pictures.move_to_end(key)
        self._enlarged_pixels += size[0] * size[1]
        while self._enlarged_pixels > self.ENLARGED_PIXELS_KEPT and len(self._enlarged_pictures) > 1:
            _key, old = self._enlarged_pictures.popitem(last=False)
            self._enlarged_pixels -= old[0].get_width() * old[0].get_height()
        return kept[0], kept[1]

    # A view that shows a plant larger than its kept picture paints the plant again at the view's size instead
    # of enlarging the kept picture's pixels (``_enlarged`` only stands in until it is painted): every plant in a
    # view is drawn in the view's own pixels, a tree as finely as a herb.  Painted in steps of this factor, so a
    # zoom does not repaint every frame, and reduced from there to each plant's size; kept in as much room as the
    # enlarged pictures.
    VIEW_PICTURE_STEP = 1.25

    def _view_picture(self, biosphere_sim, key, instance, full, target, height_cap):
        """A plant painted at least ``target`` pixels high: ``(picture, foot)``; ``None`` while it waits to be painted.

        ``instance`` is the plant as its kept picture was painted (``_sprite_surface``); ``full`` that picture.
        A planet's kept individual is kept on disk at each size beside its kept picture, as that is.
        """
        _sprite, _anchor, above_ground_m, full_height = full
        steps = max(1, math.ceil(math.log(target / full_height) / math.log(self.VIEW_PICTURE_STEP) - 1e-9))
        size = min(self.ENLARGED_TO_PX, round(full_height * self.VIEW_PICTURE_STEP ** steps))
        kept_key = (key, size)
        kept = self._view_pictures.get(kept_key)
        on_disk = key[0] == "stage"  # a planet's kept individual, not a simulated body that goes on growing
        if kept is None and on_disk:
            found = self._kept_stage_picture(biosphere_sim, instance, height_cap, size)
            kept = None if found is None else found[:2]
        if kept is None:
            # A plant takes up to a second to paint this large: not while the view moves, and one a frame.
            if self._over_sprite_budget() or time.monotonic() - self._ground_changed_at < self.GROUND_SETTLE_SECONDS:
                return None
            case = self._species_case(biosphere_sim, instance)
            # A kept stage is held under the height cap times stage ** 0.65 (``_target_height_for``).
            stage = max(1e-3, min(1.0, float(instance["display_maturity"]))) if "display_maturity" in instance else 1.0
            close = SimpleNamespace(zoom=self.FULL_SIZE_PX_PER_M, sprite_height_cap=math.ceil(size / stage ** 0.65),
                                    true_scale=self._true_scale, sprite_width_cap=self.SPRITE_PANEL_MAX_PX)
            # The kept picture's look, painted finer: as large as its own painting was, Species Sim draws it alike.
            as_kept = SimpleNamespace(zoom=self.FULL_SIZE_PX_PER_M, sprite_height_cap=height_cap, true_scale=self._true_scale)
            look_px = self._stage_paint_heights(biosphere_sim, case, instance, as_kept, above_ground_m)[1]
            kept = self._paint_stage_picture(biosphere_sim, case, instance, close, above_ground_m, look_px)
            self._sprites_painted += 1
            if on_disk:
                self._keep_stage_picture(biosphere_sim, instance, height_cap,
                                         (kept[0], kept[1], above_ground_m, max(1, round(kept[1][1]))), size)
        if kept_key not in self._view_pictures:
            self._view_pictures[kept_key] = kept
            self._view_pixels += kept[0].get_width() * kept[0].get_height()
            while self._view_pixels > self.ENLARGED_PIXELS_KEPT and len(self._view_pictures) > 1:
                _key, old = self._view_pictures.popitem(last=False)
                self._view_pixels -= old[0].get_width() * old[0].get_height()
        self._view_pictures.move_to_end(kept_key)
        return kept

    def _plant_reach(self, state):
        """How far beyond the screen a plant may stand and still reach into it: ``(to a side, above, below)`` in pixels."""
        if not state.get("generated"):
            return 240.0, 40.0, 360.0
        # A tree of 45 m, drawn at its size up to the tallest a view draws.
        tallest = max(360.0, min(float(self.ENLARGED_TO_PX), 45.0 * state["scale"]))
        return max(240.0, 0.5 * tallest), 40.0, tallest

    # A plant of the surroundings this tall or taller (in pixels) that stands in front of plants of the
    # living area is drawn this see-through (of 255): a tree at its size would hide the ground one works on.
    SEE_THROUGH_FROM_PX = 160
    SEE_THROUGH_ALPHA = 105

    def _see_through(self, sprite):
        kept = self._see_through_pictures.get(id(sprite))
        if kept is None or kept[0] is not sprite:
            thin = sprite.copy()
            thin.fill((255, 255, 255, self.SEE_THROUGH_ALPHA), special_flags=pygame.BLEND_RGBA_MULT)
            if len(self._see_through_pictures) >= 512:
                self._see_through_pictures.clear()
            self._see_through_pictures[id(sprite)] = kept = (sprite, thin)
        return kept[1]

    def _mirrored(self, sprite):
        kept = self._mirror_pictures.get(id(sprite))
        if kept is None or kept[0] is not sprite:
            if len(self._mirror_pictures) >= 4000:
                self._mirror_pictures.clear()
            self._mirror_pictures[id(sprite)] = kept = (sprite, pygame.transform.flip(sprite, True, False))
        return kept[1]

    def _stage_picture_path(self, biosphere_sim, instance, height_cap, view_px=None):
        """Where a kept plant's picture at a stage is kept between sessions, or ``None`` where nothing is.

        Beside the planet's pictures from above, and named like them by what
        the plant was grown from: a changed species is painted anew.  ``view_px``: the picture of it painted
        that high for a view (``_view_picture``).
        """
        art_revision = self._instance_art_revision(biosphere_sim, instance)
        art_stamp = hashlib.sha256(repr(art_revision).encode()).hexdigest()[:16]
        key = (id(biosphere_sim.world_model), instance["species_id"], instance.get("variant") or 0,
               instance["display_maturity"], height_cap, self._true_scale, art_stamp, view_px)
        if key not in self._stage_paths:
            pictures = getattr(biosphere_sim, "plant_pictures", None)
            base = None
            if pictures is not None and getattr(pictures, "map_sprite_dir", None) is not None:
                base = pictures._map_sprite_path(instance["species_id"], instance.get("variant") or 0)
            self._stage_paths[key] = None if base is None else base.parent / "isometric" / (
                f"{base.stem}_{round(float(instance['display_maturity']) * 1000)}_{int(height_cap)}"
                f"_{int(bool(self._true_scale))}_{self.STAGE_PICTURE_MAKE}_{art_stamp}"
                + (f"_view{int(view_px)}" if view_px else "") + ".png")
        return self._stage_paths[key]

    # Counts the ways these pictures have been painted: one painted another way is not taken from disk.
    STAGE_PICTURE_MAKE = 3

    def _kept_stage_picture(self, biosphere_sim, instance, height_cap, view_px=None):
        path = self._stage_picture_path(biosphere_sim, instance, height_cap, view_px)
        if path is None or path in self._stage_absent:
            return None
        try:
            told = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            sprite = pygame.image.load(str(path))
            sprite = sprite.convert_alpha() if pygame.display.get_surface() else sprite
            return (sprite, (float(told["foot"][0]), float(told["foot"][1])), float(told["above_ground_m"]),
                    int(told["height"]))
        except (OSError, ValueError, KeyError, TypeError, pygame.error):
            self._stage_absent.add(path)
            return None

    def _keep_stage_picture(self, biosphere_sim, instance, height_cap, full, view_px=None):
        path = self._stage_picture_path(biosphere_sim, instance, height_cap, view_px)
        if path is None:
            return
        sprite, anchor, above_ground_m, height = full
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            pygame.image.save(sprite, str(path))
            path.with_suffix(".json").write_text(json.dumps(
                {"foot": [anchor[0], anchor[1]], "above_ground_m": above_ground_m, "height": height}), encoding="utf-8")
            self._stage_absent.discard(path)
        except (OSError, pygame.error):
            pass

    def _sprite_surface(self, biosphere_sim, instance, camera):
        height_cap = getattr(camera, "sprite_height_cap", 84)
        units = biosphere_sim.world_units_to_meters
        art_revision = self._instance_art_revision(biosphere_sim, instance)
        world = (id(biosphere_sim.world_model), getattr(biosphere_sim.world_model, "repository_revision", 0),
                 height_cap, units, art_revision)
        if "display_maturity" in instance:
            steps = self.DISPLAY_MATURITY_STEPS
            maturity = max(1, round(float(instance["display_maturity"]) * steps)) / steps
            sized = dict(instance, display_maturity=maturity)
            key = ("stage", instance["species_id"], instance.get("variant"), maturity) + world
            painting = dict(sized, age_bucket=0, abundance=1.0, visual_scale=1.0)
            view_key = key
            full = self._full_size_sprite(biosphere_sim, key, None, painting, height_cap, stale_ok=False)
        else:
            representative = getattr(biosphere_sim, "get_representative_species_simulation", lambda _id: None)(
                instance.get("representative_id"))
            if representative is None:
                return self._render_sprite_surface(biosphere_sim, instance, camera)
            sized = instance
            key = ("organism", instance.get("representative_id")) + world
            # Repainted when the body has visibly grown, not for every regrown
            # snapshot; until then, and for a frame or two after, the older
            # picture stands in.
            stats = getattr(representative.render_snapshot, "stats", None) or {}
            stage = round(float(stats.get("maturity", 0.0) or 0.0) * self.DISPLAY_MATURITY_STEPS)
            painting = dict(instance, abundance=1.0)
            view_key = key + (stage, representative.seed, representative.blueprint.fingerprint())  # the body as it stands
            full = self._full_size_sprite(
                biosphere_sim, key, (stage, representative.seed, representative.blueprint.fingerprint()),
                painting, height_cap, stale_ok=True)
        if full is None:
            return None
        sprite, anchor, above_ground_m, full_height = full
        target = self._flat_plant_height(
            self._target_height_for(above_ground_m, sized, camera, units),
            above_ground_m * self._pixels_per_metre(camera, units), sprite.get_width() / max(1, full_height))
        if target > full_height * 1.15:
            painted = self._view_picture(biosphere_sim, view_key, painting, full, target, height_cap)
            if painted is None:
                return self._enlarged(sprite, anchor, target / full_height)  # until it is painted
            sprite, anchor = painted
            full_height = max(1, round(anchor[1]))
        if target >= full_height:
            # A picture that could not be painted as large (a plant held to its width) is enlarged the rest.
            return (sprite, anchor) if target <= full_height * 1.15 else self._enlarged(sprite, anchor, target / full_height)
        scaled_key = (key, id(sprite), target)
        scaled = self._display_sprite_cache.get(scaled_key)
        if scaled is None:
            factor = target / max(1, full_height)
            # Reduced as a map reduces a plant's picture: thin twigs and small leaves stay, in few tones.
            reduced = map_sprite_at(sprite, max(1, round(max(sprite.get_size()) * factor)))
            scaled = (reduced, (anchor[0] * reduced.get_width() / sprite.get_width(),
                                anchor[1] * reduced.get_height() / sprite.get_height()), sprite)
            if len(self._display_sprite_cache) >= 6000:
                self._display_sprite_cache.pop(next(iter(self._display_sprite_cache)))
            self._display_sprite_cache[scaled_key] = scaled
        return scaled[0], scaled[1]

    # The widest panel a plant is painted on, roots and all, before it is cropped.
    SPRITE_PANEL_MAX_PX = 4096
    # A painted plant larger than this many pixels is not kept among the painted surfaces: a hundred of them
    # would hold gigabytes, and what is painted that large is kept where it was painted for.
    SURFACE_CACHE_MAX_PIXELS = 1_000_000

    @staticmethod
    def _shown_extent(snapshot, bounds):
        """Width and height, in metres, of the part of a plant that stands above the ground."""
        return above_ground_extent(snapshot, bounds)

    @staticmethod
    def _pixels_per_metre(camera, world_units_to_meters):
        return float(getattr(camera, "zoom", 1.0) or 1.0) / max(1e-9, float(world_units_to_meters or 1.0))

    @staticmethod
    def _flat_plant_height(target_px, natural_px, width_per_height):
        """The pixel height to draw a plant at, given that it may lie flat.

        A plant too small to see is enlarged to a legible height.  One wider
        than tall reads by its width: enlarged until its few centimetres of
        height did, a water-lily pad would cover a pond.  ``natural_px`` is
        its height at the view's own scale.
        """
        if width_per_height <= 1.0 or target_px <= natural_px * 1.2:
            return target_px
        return max(1, round(max(natural_px, target_px / width_per_height)))

    def _render_sprite_surface(self, biosphere_sim, instance, camera, foliage_sample_cap=3):
        case = self._species_case(biosphere_sim, instance)
        art_revision = self.species_renderer._visual_asset_revision(case)
        pixel_scale = float(getattr(camera, "pixel_scale", 1.0) or 1.0)
        frame_key = (instance["species_id"], instance.get("representative_id") or instance.get("visual_source_id"),
                     instance.get("age_bucket"), instance.get("variant"), instance.get("visual_scale", 1.0),
                     round(float(instance.get("abundance", 0.0)) * 5), instance.get("display_maturity"),
                     foliage_sample_cap, getattr(camera, "sprite_height_cap", 84), art_revision,
                     id(case.render_snapshot), case.blueprint.fingerprint(), round(pixel_scale, 3))
        frame_cached = getattr(self, "_frame_surfaces", {}).get(frame_key)
        if frame_cached is not None:
            return frame_cached
        if (case.blueprint.growth.get("growth_behaviour") == "fern_fronding"
                and case.blueprint.growth.get("leaf_structure") == "frond_like"):
            result = self._render_fern_canopy_sprite(case, camera, foliage_sample_cap)
            self._frame_surfaces[frame_key] = result
            return result
        units = biosphere_sim.world_units_to_meters
        bounds = diagnostic_cell_bounds(case.render_snapshot)
        model_width = max(0.08, bounds[1] - bounds[0])
        # The picture is cut off at the ground, so it is sized by what stands
        # above it.  Roots reach as deep and as far as the crown or further:
        # counted in, a deep-rooted herb was drawn at a fraction of its size.
        shown_width, shown_height = self._shown_extent(case.render_snapshot, bounds)
        target_height = self._flat_plant_height(
            self._target_height_px(case, instance, camera, units),
            shown_height * self._pixels_per_metre(camera, units), shown_width / shown_height)
        height_cap = int(getattr(camera, "sprite_height_cap", 84) or 84)
        # The 84 px map symbol stays 96 px wide at most; a taller picture may be as wide as it needs.  A picture
        # painted for a view's own scale (``_view_picture``) says how wide it may be.
        width_cap = getattr(camera, "sprite_width_cap", None) or (96 if height_cap <= 84 else round(height_cap * 1.6))
        scale = min(width_cap / shown_width, target_height / shown_height)
        # Room for the whole model, roots included, so that nothing above ground is clipped.
        target_width = max(10, min(self.SPRITE_PANEL_MAX_PX, round(model_width * scale)))
        cache_key = (
            instance["species_id"], instance.get("age_bucket"), instance.get("variant"), foliage_sample_cap,
            target_width, target_height, case.blueprint.fingerprint(),
            round(float(case.render_snapshot.age_days), 3),
            case.seed, getattr(biosphere_sim.world_model, "repository_revision", 0), art_revision, round(pixel_scale, 3),
        )
        cached = self._surface_cache.get(cache_key)
        if cached is not None:
            self._frame_surfaces[frame_key] = cached
            if len(self._frame_surfaces) > 1024:
                self._frame_surfaces.pop(next(iter(self._frame_surfaces)))
            return cached

        panel = pygame.Surface((target_width + 12, target_height + 12), pygame.SRCALPHA)
        sprite_camera = DiagnosticCamera(panel.get_width(), panel.get_height(), bounds)
        sprite_camera.scale = scale
        sprite_camera.sprite_height_cap = height_cap
        sprite_camera.pixel_scale = pixel_scale
        root_x, root_y = sprite_camera.world_to_screen((0.0, 0.0))
        sprite_camera.bottom += panel.get_height() - 5 - root_y
        self.species_renderer._draw_individual(
            panel,
            case,
            camera=sprite_camera,
            clear=False,
            cache=True,
            draw_ground_line=False,
            foliage_sample_cap=foliage_sample_cap,
        )
        root_x, root_y = sprite_camera.world_to_screen((0.0, 0.0))
        if root_y + 1 < panel.get_height():
            panel.fill((0, 0, 0, 0), (0, root_y + 1, panel.get_width(), panel.get_height() - root_y - 1))
        bounds_rect = panel.get_bounding_rect(min_alpha=1)
        if bounds_rect.width > 0 and bounds_rect.height > 0:
            cropped = panel.subsurface(bounds_rect).copy()
            anchor = (root_x - bounds_rect.x, root_y - bounds_rect.y)
        else:
            cropped = panel
            anchor = (panel.get_width() * 0.5, panel.get_height() - 1)
        if cropped.get_width() > width_cap:
            # Leaves reach beyond where they are attached: the width was a guess, the cap is not.
            factor = width_cap / cropped.get_width()
            cropped = pygame.transform.smoothscale(cropped, (width_cap, max(1, round(cropped.get_height() * factor))))
            anchor = (anchor[0] * factor, anchor[1] * factor)
        result = cropped, anchor
        if cropped.get_width() * cropped.get_height() > self.SURFACE_CACHE_MAX_PIXELS:
            return result  # a picture painted to be kept (``_full_size_sprite``, ``_view_picture``) is kept there
        self._surface_cache[cache_key] = result
        self._frame_surfaces[frame_key] = result
        if len(self._frame_surfaces) > 1024:
            self._frame_surfaces.pop(next(iter(self._frame_surfaces)))
        if len(self._surface_cache) > 128:
            self._surface_cache.pop(next(iter(self._surface_cache)))
        return result

    def _render_fern_canopy_sprite(self, case, scene_camera, foliage_sample_cap):
        """Paint a divided fern from above the stand at BioSim billboard scale."""
        snapshot = case.render_snapshot
        footprint = top_down_diagnostic_bounds(case, snapshot)
        max_z = max(.05, snapshot.bounds_m[5])
        bounds = (*footprint, 0., max_z)
        projected = [(x-y, (x+y)*.5-z)
                     for x in (bounds[0], bounds[1])
                     for y in (bounds[2], bounds[3])
                     for z in (0., max_z)]
        min_u, max_u = min(p[0] for p in projected), max(p[0] for p in projected)
        min_v, max_v = min(p[1] for p in projected), max(p[1] for p in projected)
        height_cap = int(getattr(scene_camera, "sprite_height_cap", 84) or 84)
        width_cap = 96 if height_cap <= 84 else round(height_cap * 1.6)
        scale = min((width_cap-12)/max(.1, max_u-min_u),
                    (height_cap-12)/max(.1, max_v-min_v))
        panel = pygame.Surface((max(12, round((max_u-min_u)*scale)+12),
                                max(12, round((max_v-min_v)*scale)+12)), pygame.SRCALPHA)
        sprite_camera = IsometricDiagnosticCamera(*panel.get_size(), bounds)
        sprite_camera.scale = scale
        sprite_camera.pixel_scale = getattr(scene_camera, "pixel_scale", 1.0)
        sprite_camera.offset_x = panel.get_width()*.5 - (min_u+max_u)*.5*scale
        sprite_camera.offset_y = panel.get_height()*.5 - (min_v+max_v)*.5*scale
        sprite_camera.sprite_height_cap = height_cap
        self.species_renderer._draw_individual(
            panel, case, camera=sprite_camera, clear=False, cache=True,
            visible_indices=canopy_visible_indices(case, snapshot),
            draw_ground_line=False, foliage_sample_cap=foliage_sample_cap,
        )
        painted = panel.get_bounding_rect(min_alpha=1)
        if not painted.width or not painted.height:
            return panel, (panel.get_width()*.5, panel.get_height()-1)
        cropped = panel.subsurface(painted).copy()
        root_x = sprite_camera.world_to_screen_3d((0.,0.,0.))[0]-painted.x
        return cropped, (root_x, cropped.get_height()-1)

    @staticmethod
    def _draw_groundcover(screen, instance, anchor_screen, scale, color, surface_profile=None):
        """Map-scale grass/lichen symbols; individual organ models remain in SpeciesSim."""
        sx, sy = map(round, anchor_screen)
        stage = max(0.0, min(1.0, instance.get("display_maturity", .88)))
        size = max(1, min(13, round(scale * 0.16 * max(.10, stage) ** .65 * instance.get("visual_scale", 1.0))))
        if instance.get("growth_form")=="lichen" and surface_profile:
            # This is a bounded population symbol, not one enlarged organism.
            # The field's thallus form controls its habit and palette at all
            # zoom levels, without drawing thousands of full SpeciesSim bodies.
            digest=hashlib.sha256(f"{instance['species_id']}:{instance['x']:.5f}:{instance['y']:.5f}".encode()).digest()
            pale=(205,211,195); center=(117,132,119)
            fruticose=surface_profile.get("thallus_form")=="fruticose"
            count=3 if size<3 else 5 if size<7 else 9
            height=max(1,min(12,round(scale*surface_profile.get("tuft_height_m",.015)*max(.1,stage))))
            for i in range(count):
                dx=round((digest[i]/255*2-1)*size)
                dy=round((digest[i+10]/255*2-1)*size*.45)
                base=(sx+dx,sy+dy)
                if fruticose:
                    lean=round((digest[i+20]/255*2-1)*height*.4)
                    tip=(base[0]+lean,base[1]-height)
                    pygame.draw.line(screen,(149,151,139),base,tip,max(1,size//6))
                    for j in range(1,5):
                        x=round(base[0]+lean*j/4)
                        y=round(base[1]-height*j/4)
                        reach=max(1,size//5)
                        for side in (-1,1):
                            nub=(x+side*reach,y-(j%2))
                            pygame.draw.line(screen,(170,174,159),(x,y),nub,1)
                            pygame.draw.circle(screen,pale,nub,max(1,size//8))
                    pygame.draw.circle(screen,pale,tip,max(1,size//7))
                else:
                    width=max(1,size//3)
                    palette=surface_palette(surface_profile,((162,177,139),)*4)
                    if surface_profile.get("thallus_form")=="foliose":
                        pygame.draw.ellipse(screen,palette[i%4],
                                           (base[0]-width,base[1]-max(1,width//2),
                                            width*2+1,max(2,width)))
                    else:
                        jag=1 if digest[(i+6)%len(digest)]&1 else -1
                        pygame.draw.polygon(screen,palette[i%4],
                                            ((base[0]-width,base[1]),
                                             (base[0]-width//2,base[1]-2),
                                             (base[0]+jag,base[1]-1),
                                             (base[0]+width,base[1]),
                                             (base[0]+width//2,base[1]+1),
                                             (base[0],base[1]+2)))
            return pygame.Rect(sx-size-3,sy-size-height-2,size*2+6,size*2+height+4)
        shade = tuple(max(0, round(c * 0.48)) for c in color)
        pygame.draw.ellipse(screen, shade, (sx - size, sy - size // 3, size * 2, max(2, size)))
        if instance.get("growth_form") == "lichen":
            pygame.draw.ellipse(screen, color, (sx - size, sy - size // 2, size * 2, max(2, size)))
        else:
            blades = 2 if stage < .2 else 3 if stage < .45 else 5 if stage < .7 else 7
            for index in range(blades):
                offset = index - (blades-1)/2
                tip = (sx + round(offset * size * 0.65), sy - size - (index % 2) * size // 2)
                blade_color = tuple(min(255, round(c * (0.70 + index * 0.25 / max(1, blades-1)))) for c in color)
                pygame.draw.line(screen, blade_color, (sx + offset, sy), tip, max(1, size // 3))
        return pygame.Rect(sx - size, sy - size * 2, size * 2, size * 3)

    @staticmethod
    def _projection(screen, biosphere_sim):
        bounds = biosphere_sim.bounds
        width = max(0.1, bounds["max_x"] - bounds["min_x"])
        height = max(0.1, bounds["max_y"] - bounds["min_y"])
        if getattr(biosphere_sim, "isometric_fullscreen_preview", False):
            scene = pygame.Rect(22, 22, screen.get_width() - 44, screen.get_height() - 44)
        else:
            left_margin = min(318, max(228, round(screen.get_width() * 0.245)))
            scene = pygame.Rect(left_margin, 104, max(120, screen.get_width() - left_margin - 18), max(120, screen.get_height() - 222))
        scale = min(scene.width / (width + height + 1.0), scene.height / ((width + height) * 0.5 + 2.0))
        generated = getattr(biosphere_sim, "terrain_frame", None) is not None
        # Generated terrain continues past the domain, so the view may pull
        # far back; a bounded patch has nothing further out to show.
        zoom_floor = 0.004 if generated else 0.25
        scale = max(0.05, scale) * max(zoom_floor, float(getattr(biosphere_sim, "isometric_view_zoom", 1.0) or 1.0))
        view_center = getattr(biosphere_sim, "isometric_view_center", None)
        center_x = float(view_center[0]) if isinstance(view_center, (tuple, list)) and len(view_center) >= 2 else (bounds["min_x"] + bounds["max_x"]) * 0.5
        center_y = float(view_center[1]) if isinstance(view_center, (tuple, list)) and len(view_center) >= 2 else (bounds["min_y"] + bounds["max_y"]) * 0.5
        substrate = getattr(biosphere_sim, "substrate", None)
        state = {
            "scale": scale,
            "center_x": center_x,
            "center_y": center_y,
            "origin_x": float(scene.centerx),
            "origin_y": float(scene.centery + scene.height * 0.08),
            "scene_rect": scene,
            "substrate": substrate,
            # Generated ground sits at its true elevation, hundreds of metres
            # from zero.  The ground under the view centre is the drawing
            # plane, so it stays on screen wherever the view goes.
            "datum_m": substrate.elevation(center_x, center_y, True) if generated and substrate is not None else 0.0,
            "vertical_scale": float(getattr(biosphere_sim, "terrain_vertical_scale", 1.0) or 1.0) if generated else 1.0,
            "generated": generated,
        }
        biosphere_sim._isometric_projection_state = state
        return state

    @staticmethod
    def _iso(state, x, y):
        dx = float(x) - state["center_x"]
        dy = float(y) - state["center_y"]
        substrate = state.get("substrate")
        z = substrate.elevation(x, y, True) if substrate is not None else 0.0
        z = (z - state.get("datum_m", 0.0)) * state.get("vertical_scale", 1.0)
        return (
            state["origin_x"] + (dx - dy) * state["scale"],
            state["origin_y"] + (dx + dy) * state["scale"] * 0.5 - z * state["scale"],
        )

    @staticmethod
    def _iso_points(state, xs, ys):
        """``_iso`` over arrays; returns screen x and y arrays."""
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)
        substrate = state.get("substrate")
        if substrate is None:
            height = np.zeros(xs.shape)
        else:
            height = (substrate.elevation_array(xs, ys, True) - state.get("datum_m", 0.0)) * state.get("vertical_scale", 1.0)
        dx, dy = xs - state["center_x"], ys - state["center_y"]
        return (state["origin_x"] + (dx - dy) * state["scale"],
                state["origin_y"] + (dx + dy) * state["scale"] * 0.5 - height * state["scale"])

    # ------------------------------------------------------------------
    # Generated terrain
    # ------------------------------------------------------------------
    def _ground_texture(self, layer):
        """One substrate layer's abiotic true colour as a float array, rendered once."""
        source = layer.source
        key = (source.get("id"), id(layer.fields.get("elevation_m")))
        if key in self._ground_texture_cache:
            return self._ground_texture_cache[key]
        texture = None
        try:
            grid = source["heightmap_model"]["sample_grid"]
            target = (max(64, min(768, (int(grid["width"]) - 1) * 2)),
                      max(64, min(768, (int(grid["height"]) - 1) * 2)))
            surface = render_true_color_surface(
                source["heightmap_model"], source.get("true_color_model"),
                water_cycle=source.get("water_cycle_model"),
                surface_evolution=source.get("surface_evolution_model"),
                surface_exposure=source.get("surface_exposure_model"),
                surface_geomorphology=source.get("surface_geomorphology_model"),
                atmosphere=source.get("atmosphere_model"),
                target_size=target,
            )
            if surface is not None:
                texture = pygame.surfarray.array3d(surface).swapaxes(0, 1).astype(np.float32)
        except Exception:
            # Colour is presentation; the heightfield still draws in a neutral tone.
            texture = None
        if len(self._ground_texture_cache) >= 96:
            self._ground_texture_cache.pop(next(iter(self._ground_texture_cache)))
        self._ground_texture_cache[key] = texture
        return texture

    @staticmethod
    def _sample_texture(texture, bounds, xs, ys):
        height, width = texture.shape[:2]
        gx = np.clip((xs - bounds["min_x"]) / (bounds["max_x"] - bounds["min_x"]), 0.0, 1.0) * (width - 1)
        gy = np.clip((ys - bounds["min_y"]) / (bounds["max_y"] - bounds["min_y"]), 0.0, 1.0) * (height - 1)
        ix = np.minimum(width - 2, gx.astype(int))
        iy = np.minimum(height - 2, gy.astype(int))
        fx, fy = (gx - ix)[..., None], (gy - iy)[..., None]
        top = texture[iy, ix] * (1 - fx) + texture[iy, ix + 1] * fx
        bottom = texture[iy + 1, ix] * (1 - fx) + texture[iy + 1, ix + 1] * fx
        return top * (1 - fy) + bottom * fy

    def _texture_gain(self, key, texture, bounds, base_texture, base_bounds):
        """Match a finer patch's overall tone to the region it sits in.

        Each refinement re-derives colour from its own models and can drift a
        shade from its parent; left alone, every chunk reads as a tile.
        """
        gain = self._ground_gain_cache.get(key)
        if gain is None:
            height, width = base_texture.shape[:2]
            span_x = base_bounds["max_x"] - base_bounds["min_x"]
            span_y = base_bounds["max_y"] - base_bounds["min_y"]
            x0 = int(max(0, min(width - 1, (bounds["min_x"] - base_bounds["min_x"]) / span_x * (width - 1))))
            x1 = int(max(x0 + 1, min(width, math.ceil((bounds["max_x"] - base_bounds["min_x"]) / span_x * (width - 1)) + 1)))
            y0 = int(max(0, min(height - 1, (bounds["min_y"] - base_bounds["min_y"]) / span_y * (height - 1))))
            y1 = int(max(y0 + 1, min(height, math.ceil((bounds["max_y"] - base_bounds["min_y"]) / span_y * (height - 1)) + 1)))
            region_mean = base_texture[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
            patch_mean = np.maximum(1.0, texture.reshape(-1, 3).mean(axis=0))
            gain = np.clip(region_mean / patch_mean, 0.6, 1.6).astype(np.float32)
            if len(self._ground_gain_cache) >= 256:
                self._ground_gain_cache.pop(next(iter(self._ground_gain_cache)))
            self._ground_gain_cache[key] = gain
        return gain

    def _texture_for_step(self, texture, bounds, step_m):
        """The texture averaged down until one texel is about one mesh cell.

        A detailed raster sampled once per much larger mesh cell picks single
        texels: the refined chunk then reads as noise next to the smooth
        region around it.
        """
        texel_m = (bounds["max_x"] - bounds["min_x"]) / max(1, texture.shape[1])
        level = max(0, min(5, int(math.floor(math.log2(max(1e-9, step_m / max(1e-9, texel_m)))))))
        if level == 0:
            return texture
        key = (id(texture), level)
        reduced = self._ground_mips.get(key)
        if reduced is None:
            reduced = texture
            for _ in range(level):
                if min(reduced.shape[:2]) < 4:
                    break
                height, width = (reduced.shape[0] // 2) * 2, (reduced.shape[1] // 2) * 2
                reduced = reduced[:height, :width].reshape(height // 2, 2, width // 2, 2, 3).mean(axis=(1, 3))
            if len(self._ground_mips) >= 256:
                self._ground_mips.pop(next(iter(self._ground_mips)))
            self._ground_mips[key] = reduced
        return reduced

    def _ground_colors(self, substrate, xs, ys, step_m=0.0):
        """Abiotic ground colour at points: the region's, overridden by finer patches."""
        colors = np.empty(xs.shape + (3,), dtype=np.float32)
        colors[...] = self.FALLBACK_GROUND_RGB
        layers = substrate.layers() if hasattr(substrate, "layers") else [(substrate.bounds, substrate)]
        base_texture, base_bounds = None, None
        for index, (bounds, layer) in enumerate(layers):
            texture = self._ground_texture(layer)
            if texture is None:
                continue
            if index == 0:
                base_texture, base_bounds = texture, bounds
                colors[...] = self._sample_texture(self._texture_for_step(texture, bounds, step_m), bounds, xs, ys)
                continue
            inside = ((xs >= bounds["min_x"]) & (xs <= bounds["max_x"])
                      & (ys >= bounds["min_y"]) & (ys <= bounds["max_y"]))
            if not inside.any():
                continue
            sampled = self._sample_texture(self._texture_for_step(texture, bounds, step_m), bounds, xs[inside], ys[inside])
            if base_texture is not None:
                sampled = sampled * self._texture_gain(
                    (layer.source.get("id"), id(texture)), texture, bounds, base_texture, base_bounds,
                )
            colors[inside] = sampled
        return colors

    def _render_generated_ground(self, size, substrate, state, cell_px):
        """Mesh the visible window of the heightfield and paint it back to front."""
        surface = pygame.Surface(size)
        surface.fill((15, 20, 18))
        width, height = size
        scale = state["scale"]
        center_x, center_y = state["center_x"], state["center_y"]
        origin_x, origin_y = state["origin_x"], state["origin_y"]
        datum, vertical = state["datum_m"], state["vertical_scale"]

        # Where the screen corners meet the datum plane.
        corner_x, corner_y = [], []
        for sx, sy in ((0, 0), (width, 0), (0, height), (width, height)):
            a = (sx - origin_x) / scale
            b = (sy - origin_y) / (scale * 0.5)
            corner_x.append(center_x + (a + b) * 0.5)
            corner_y.append(center_y + (b - a) * 0.5)
        bounds = substrate.bounds
        x0, x1 = max(bounds["min_x"], min(corner_x)), min(bounds["max_x"], max(corner_x))
        y0, y1 = max(bounds["min_y"], min(corner_y)), min(bounds["max_y"], max(corner_y))
        if x1 <= x0 or y1 <= y0:
            return surface
        # Ground standing above or below the datum is drawn displaced along
        # the view diagonal; widen the window by the relief it actually has.
        probe_x, probe_y = np.meshgrid(np.linspace(x0, x1, 24), np.linspace(y0, y1, 24))
        relief = (substrate.elevation_array(probe_x, probe_y, True) - datum) * vertical
        low, high = float(relief.min()), float(relief.max())
        x0, x1 = max(bounds["min_x"], x0 + min(0.0, low) - 2.0 / scale), min(bounds["max_x"], x1 + max(0.0, high) + 2.0 / scale)
        y0, y1 = max(bounds["min_y"], y0 + min(0.0, low) - 2.0 / scale), min(bounds["max_y"], y1 + max(0.0, high) + 2.0 / scale)

        step = max(cell_px / scale, (x1 - x0) / self.GROUND_MAX_CELLS_PER_AXIS, (y1 - y0) / self.GROUND_MAX_CELLS_PER_AXIS)
        # Lattice lines sit on multiples of the step, so the mesh does not
        # crawl over the ground while the view pans.
        xs = np.clip(np.arange(math.floor(x0 / step), math.ceil(x1 / step) + 1) * step, x0, x1)
        ys = np.clip(np.arange(math.floor(y0 / step), math.ceil(y1 / step) + 1) * step, y0, y1)
        if len(xs) < 2 or len(ys) < 2:
            return surface
        grid_x, grid_y = np.meshgrid(xs, ys)
        relief = (substrate.elevation_array(grid_x, grid_y, True) - datum) * vertical
        screen_x = origin_x + ((grid_x - center_x) - (grid_y - center_y)) * scale
        screen_y = origin_y + ((grid_x - center_x) + (grid_y - center_y)) * scale * 0.5 - relief * scale

        cell_x = (grid_x[:-1, :-1] + grid_x[1:, 1:]) * 0.5
        cell_y = (grid_y[:-1, :-1] + grid_y[1:, 1:]) * 0.5
        # Slope over a baseline no shorter than the data's own spacing: a mesh
        # finer than the heightfield would otherwise shade every sample cell
        # as one flat facet.
        spacing = getattr(substrate, "sample_spacing_at", lambda _x, _y: substrate.sample_spacing_m())(center_x, center_y)
        reach = max(step * 0.5, float(spacing))
        slope_x = (substrate.elevation_array(cell_x + reach, cell_y, True)
                   - substrate.elevation_array(cell_x - reach, cell_y, True)) * vertical / (2.0 * reach)
        slope_y = (substrate.elevation_array(cell_x, cell_y + reach, True)
                   - substrate.elevation_array(cell_x, cell_y - reach, True)) * vertical / (2.0 * reach)
        shade = np.clip((1.0 + 0.45 * slope_x - 0.55 * slope_y) / np.sqrt(1.0 + slope_x ** 2 + slope_y ** 2), 0.55, 1.2)
        colors = self._ground_colors(substrate, cell_x, cell_y, step)
        water = substrate.open_water_array(cell_x, cell_y).astype(bool)
        if all(self._ground_texture(layer) is None for _bounds, layer in (
                substrate.layers() if hasattr(substrate, "layers") else [(substrate.bounds, substrate)])):
            colors[water] = (57, 109, 121)
        shade[water] = 1.0
        rgb = np.clip(colors * shade[..., None], 0, 255).astype(np.uint8)

        corners_x = np.stack([screen_x[:-1, :-1], screen_x[:-1, 1:], screen_x[1:, 1:], screen_x[1:, :-1]])
        corners_y = np.stack([screen_y[:-1, :-1], screen_y[:-1, 1:], screen_y[1:, 1:], screen_y[1:, :-1]])
        visible = ((corners_x.max(axis=0) >= 0) & (corners_x.min(axis=0) <= width)
                   & (corners_y.max(axis=0) >= 0) & (corners_y.min(axis=0) <= height))
        rows, columns = np.nonzero(visible)
        if not len(rows):
            return surface
        order = np.argsort(rows + columns, kind="stable")
        rows, columns = rows[order], columns[order]
        quads = np.stack([corners_x[:, rows, columns], corners_y[:, rows, columns]], axis=-1).transpose(1, 0, 2).tolist()
        polygon = pygame.draw.polygon
        for color, quad in zip(rgb[rows, columns].tolist(), quads):
            polygon(surface, color, quad)
        return surface

    def _draw_generated_ground(self, screen, substrate, state, dragging=False):
        frame = (substrate.fingerprint, screen.get_size(), round(state["scale"], 6),
                 state["origin_x"], state["origin_y"], state["vertical_scale"])
        view = frame + (round(state["center_x"], 4), round(state["center_y"], 4))
        now = time.monotonic()
        if view != self._ground_view:
            # The very first view is not a movement: mesh it finely at once.
            self._ground_changed_at = now if self._ground_view is not None else float("-inf")
            self._ground_view = view
        rest = self._ground_rest
        if rest is not None and rest["view"] == view:
            screen.blit(rest["surface"], (0, 0))
            return
        if not dragging and now - self._ground_changed_at >= self.GROUND_SETTLE_SECONDS:
            # The view rests: mesh it finely once and keep it.
            self._ground_rest = rest = {
                "view": view, "frame": frame, "surface": self._render_generated_ground(
                    screen.get_size(), substrate, state, self.GROUND_CELL_PX),
                "center": (state["center_x"], state["center_y"]), "datum": state["datum_m"],
            }
            self._ground_moving = None
            screen.blit(rest["surface"], (0, 0))
            return
        moving = self._ground_moving
        if moving is None or moving[0] != view:
            self._ground_moving = moving = (view, self._render_generated_ground(
                screen.get_size(), substrate, state, self.GROUND_CELL_PX_MOVING))
        screen.blit(moving[1], (0, 0))
        if rest is not None and rest["frame"] == frame:
            # A pan only slides the picture: reuse the resting mesh where it
            # still covers the screen, the coarse one in the strips it left.
            scale = state["scale"]
            dx = state["center_x"] - rest["center"][0]
            dy = state["center_y"] - rest["center"][1]
            screen.blit(rest["surface"], (
                round(-(dx - dy) * scale),
                round(-(dx + dy) * scale * 0.5 + (state["datum_m"] - rest["datum"]) * state["vertical_scale"] * scale),
            ))

    def _draw_domain_outline(self, screen, biosphere_sim, state):
        """The simulated area, draped on the ground it is part of."""
        b = biosphere_sim.bounds
        t = np.linspace(0.0, 1.0, 33)
        edge_x = np.concatenate([b["min_x"] + (b["max_x"] - b["min_x"]) * t, np.full(33, b["max_x"]),
                                 b["max_x"] - (b["max_x"] - b["min_x"]) * t, np.full(33, b["min_x"])])
        edge_y = np.concatenate([np.full(33, b["min_y"]), b["min_y"] + (b["max_y"] - b["min_y"]) * t,
                                 np.full(33, b["max_y"]), b["max_y"] - (b["max_y"] - b["min_y"]) * t])
        sx, sy = self._iso_points(state, edge_x, edge_y)
        points = list(zip(sx.tolist(), sy.tolist()))
        pygame.draw.lines(screen, (28, 34, 26), True, points, 3)
        pygame.draw.lines(screen, (226, 214, 150), True, points, 1)

    def _draw_imported_ground(self, screen, substrate, state):
        key = (substrate.fingerprint, screen.get_size(), tuple(state[k] for k in
               ("scale", "center_x", "center_y", "origin_x", "origin_y")))
        surface = self._terrain_surface_cache.get(key)
        if surface is None:
            surface = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
            b = dict(substrate.bounds)
            grid = substrate.heightmap["sample_grid"]
            # Tessellate the visible window, not all 36km² when zoomed to a river bank.
            if substrate.native is not None:
                rect, scale = state["scene_rect"], state["scale"]
                lo,hi=substrate.heightmap["min_elevation_m"],substrate.heightmap["max_elevation_m"]
                corners=[]
                for sx,sy in (rect.topleft,rect.topright,rect.bottomleft,rect.bottomright):
                    a=(sx-state["origin_x"])/scale
                    c=(sy-state["origin_y"])/(scale*.5)
                    corners.append((state["center_x"]+(a+c)*.5,state["center_y"]+(c-a)*.5))
                b.update(min_x=max(b["min_x"],min(p[0] for p in corners)+lo-2),
                         max_x=min(b["max_x"],max(p[0] for p in corners)+hi+2),
                         min_y=max(b["min_y"],min(p[1] for p in corners)+lo-2),
                         max_y=min(b["max_y"],max(p[1] for p in corners)+hi+2))
                if b["max_x"]<=b["min_x"] or b["max_y"]<=b["min_y"]:
                    return
            step=max(1.,3./state["scale"]) if substrate.native is not None else 0.
            nx,ny=(max(1,min(400,math.ceil((b["max_x"]-b["min_x"])/step))),
                   max(1,min(400,math.ceil((b["max_y"]-b["min_y"])/step)))) if step else (min(200,grid["width"]-1),min(200,grid["height"]-1))
            dx, dy = (b["max_x"]-b["min_x"])/nx, (b["max_y"]-b["min_y"])/ny
            points = [[self._iso(state, b["min_x"]+i*dx, b["min_y"]+j*dy)
                       for i in range(nx+1)] for j in range(ny+1)]
            for _, j, i in sorted((i+j, j, i) for j in range(ny) for i in range(nx)):
                x, y = b["min_x"]+(i+.5)*dx, b["min_y"]+(j+.5)*dy
                wet = substrate.open_water_at(x,y)
                color = substrate.sample("abiotic_rgb", x, y, (115, 105, 81))
                if wet:
                    shade = .99 + .01 * math.sin(x * .8 + y * 3)
                    if substrate.fields.get("abiotic_rgb") is None:
                        color = (57, 109, 121)
                else:
                    sx = (substrate.elevation(x+dx*.5, y)-substrate.elevation(x-dx*.5, y))/dx
                    sy = (substrate.elevation(x, y+dy*.5)-substrate.elevation(x, y-dy*.5))/dy
                    shade = max(.55, min(1.2, (1 + .45*sx - .55*sy) / math.sqrt(1+sx*sx+sy*sy)))
                rgb = tuple(max(0, min(255, round(c*shade))) for c in color)
                pygame.draw.polygon(surface, rgb, [points[j][i], points[j][i+1], points[j+1][i+1], points[j+1][i]])
            if len(self._terrain_surface_cache) >= 4:
                self._terrain_surface_cache.pop(next(iter(self._terrain_surface_cache)))
            self._terrain_surface_cache[key] = surface
        screen.blit(surface, (0, 0))

    def _draw_ground(self, screen, biosphere_sim, state):
        screen.fill((15, 20, 18))
        if state.get("generated") and state.get("substrate") is not None:
            self._draw_generated_ground(
                screen, state["substrate"], state,
                dragging=bool(getattr(biosphere_sim, "is_camera_dragging", False)
                              and getattr(biosphere_sim, "camera_drag_has_moved", False)),
            )
            self._draw_domain_outline(screen, biosphere_sim, state)
            return
        if getattr(biosphere_sim, "substrate", None) is not None:
            self._draw_imported_ground(screen, biosphere_sim.substrate, state)
            return
        bounds = biosphere_sim.bounds
        corners = [
            self._iso(state, bounds["min_x"], bounds["min_y"]),
            self._iso(state, bounds["max_x"], bounds["min_y"]),
            self._iso(state, bounds["max_x"], bounds["max_y"]),
            self._iso(state, bounds["min_x"], bounds["max_y"]),
        ]
        lower = [(x, y + 13) for x, y in corners]
        pygame.draw.polygon(screen, (49, 41, 31), [corners[0], corners[1], lower[1], lower[0]])
        pygame.draw.polygon(screen, (39, 34, 28), [corners[1], corners[2], lower[2], lower[1]])
        pygame.draw.polygon(screen, (103, 91, 68), corners)

        # Broad continuous habitat bands make moisture legible without cells.
        band = []
        for index in range(25):
            ny = index / 24.0
            x = bounds["min_x"] + (0.23 + 0.18 * ny) * (bounds["max_x"] - bounds["min_x"])
            y = bounds["min_y"] + ny * (bounds["max_y"] - bounds["min_y"])
            band.append(self._iso(state, x, y))
        if len(band) > 1:
            pygame.draw.lines(screen, (77, 103, 96), False, band, max(2, round(state["scale"] * 0.10)))
            pygame.draw.lines(screen, (103, 126, 113), False, band, 1)

        # Sparse world-coordinate flecks provide scale without introducing a grid.
        for index in range(58):
            fx = ((index * 0.61803398875 + 0.17) % 1.0)
            fy = ((index * 0.41421356237 + 0.31) % 1.0)
            x = bounds["min_x"] + fx * (bounds["max_x"] - bounds["min_x"])
            y = bounds["min_y"] + fy * (bounds["max_y"] - bounds["min_y"])
            sx, sy = self._iso(state, x, y)
            color = (126, 111, 82) if index % 3 else (78, 70, 57)
            pygame.draw.circle(screen, color, (round(sx), round(sy)), 1)
        pygame.draw.polygon(screen, (149, 132, 91), corners, 2)

    # The soil tint is resolved per screen pixel block of this size: finely
    # once the view rests, coarsely while it moves.
    SOIL_TINT_STEP_PX = 3
    SOIL_TINT_STEP_PX_MOVING = 9

    def _ground_world_map(self, size, state, step_px, offset=None):
        """World x and y of the ground under a lattice of screen pixels.

        The ray through a pixel meets the datum plane at a known point; the
        ground it actually hits lies further along the view diagonal by its
        own height, found by a few fixed-point steps.  Gentle ground converges
        at once; behind a steep rise the result is the nearer slope, which is
        harmless for a soft tint.  With ``offset`` the lattice begins there
        (left and top, which may lie off the screen) and covers the screen.
        """
        key = (size, step_px, offset, state["scale"], state["center_x"], state["center_y"], state["origin_x"],
               state["origin_y"], state["vertical_scale"], state["substrate"].fingerprint)
        cached = self._world_map_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        substrate, scale = state["substrate"], state["scale"]
        if offset is None:
            columns = np.arange(step_px * 0.5, size[0], step_px)
            rows = np.arange(step_px * 0.5, size[1], step_px)
        else:
            columns = np.arange(offset[0] + step_px * 0.5, size[0] + step_px * 0.5, step_px)
            rows = np.arange(offset[1] + step_px * 0.5, size[1] + step_px * 0.5, step_px)
        screen_x, screen_y = np.meshgrid(columns, rows)
        a = (screen_x - state["origin_x"]) / scale
        b = (screen_y - state["origin_y"]) / (scale * 0.5)
        flat_x = state["center_x"] + (a + b) * 0.5
        flat_y = state["center_y"] + (b - a) * 0.5
        rise = np.zeros(flat_x.shape)
        for _ in range(3):
            rise = (substrate.elevation_array(flat_x + rise, flat_y + rise, True) - state["datum_m"]) * state["vertical_scale"]
        world = (flat_x + rise, flat_y + rise)
        self._world_map_cache = (key, world)
        return world

    @staticmethod
    def _sample_soil(soil, rows, world_x, world_y):
        """A soil field at world points, bilinear between cell centres, zero outside the field."""
        values = np.asarray(rows, dtype=np.float32)
        b = soil.bounds
        gx = (world_x - b["min_x"]) / (b["max_x"] - b["min_x"]) * soil.columns - 0.5
        gy = (world_y - b["min_y"]) / (b["max_y"] - b["min_y"]) * soil.rows - 0.5
        inside = (gx > -1.0) & (gx < soil.columns) & (gy > -1.0) & (gy < soil.rows)
        gx = np.clip(gx, 0.0, soil.columns - 1.0)
        gy = np.clip(gy, 0.0, soil.rows - 1.0)
        ix = np.minimum(soil.columns - 2, gx.astype(int))
        iy = np.minimum(soil.rows - 2, gy.astype(int))
        fx, fy = gx - ix, gy - iy
        top = values[iy, ix] * (1 - fx) + values[iy, ix + 1] * fx
        bottom = values[iy + 1, ix] * (1 - fx) + values[iy + 1, ix + 1] * fx
        return np.where(inside, top * (1 - fy) + bottom * fy, 0.0)

    def _draw_soil_tint(self, screen, biosphere_sim, state):
        """Soil state lying on the ground, without changing the mineral ground itself.

        The soil itself in blocks of a few pixels (``_paint_ground_pixels``);
        what is asked of it besides (nitrogen, phosphorus) as a soft tint.
        """
        soil = getattr(biosphere_sim, "soil", None)
        mode = getattr(biosphere_sim, "soil_diagnostic_mode", "organic")
        if soil is None or (mode == "organic" and soil.summary()["max_soil_organic_matter_kg_m2"] <= 0.0001):
            return
        view = (screen.get_size(), state["scale"], state["center_x"], state["center_y"], state["origin_x"],
                state["origin_y"], state["vertical_scale"], state["substrate"].fingerprint)
        if mode == "organic":
            def paint():
                _left, _top, world_x, world_y, _numbers = self._ground_pixels(screen.get_size(), state)
                return self._paint_ground_pixels(
                    screen.get_size(), state, self._sample_soil(soil, soil.organic_matter_rows, world_x, world_y),
                    self._sample_soil(soil, soil.litter_rows, world_x, world_y),
                    patches=self._ground_patches(biosphere_sim, state, self._own_patch_cover(biosphere_sim, world_x, world_y, state)))

            # Its swards and crusts are part of the picture: it is painted anew when one of them changes.
            ecology = biosphere_sim.ecology
            swards = tuple((patch.patch_id, round(patch.abundance, 2), round(patch.radius_m, 2))
                           for patch in getattr(ecology, "patches", ())
                           if not ecology.keeps_individuals(ecology.profiles[patch.species_id]))
            kept = self._rest_layer(screen, state, "soil", (view, id(soil), soil.revision, swards), paint)
            if kept is not None:
                self._blit_rest_layer(screen, kept, state)
            return
        cached = self._soil_tint_cache
        moving = cached is not None and cached["view"] != view
        step = self.SOIL_TINT_STEP_PX_MOVING if moving else self.SOIL_TINT_STEP_PX
        key = (view, step, id(soil), soil.revision, mode)
        if cached is not None and cached["key"] == key:
            screen.blit(cached["surface"], (0, 0))
            return
        world_x, world_y = self._ground_world_map(screen.get_size(), state, step)
        if mode == "nitrogen":
            strength = np.clip(self._sample_soil(soil, soil.available_nitrogen_rows, world_x, world_y) / 0.35, 0.0, 1.0)
            red, green, blue = np.full(strength.shape, 44.0), 80 + strength * 95, np.full(strength.shape, 112.0)
            alpha = 38 + strength * 145
        elif mode == "phosphorus":
            strength = np.clip(self._sample_soil(soil, soil.available_phosphorus_rows, world_x, world_y) / 0.12, 0.0, 1.0)
            red, green, blue = 105 + strength * 115, np.full(strength.shape, 72.0), 120 + strength * 90
            alpha = 38 + strength * 145
        else:
            red, green, blue, alpha, strength = self._organic_tint(
                self._sample_soil(soil, soil.organic_matter_rows, world_x, world_y),
                self._sample_soil(soil, soil.litter_rows, world_x, world_y))
        alpha = self._soil_fade(alpha, strength)
        pixels = np.stack([red, green, blue, alpha], axis=-1).round().astype(np.uint8)
        small = pygame.image.frombuffer(pixels.tobytes(), (pixels.shape[1], pixels.shape[0]), "RGBA")
        surface = pygame.transform.smoothscale(small.convert_alpha() if pygame.display.get_surface() else small,
                                               screen.get_size())
        self._soil_tint_cache = {"key": key, "view": view, "step": step, "surface": surface}
        screen.blit(surface, (0, 0))

    @staticmethod
    def _organic_tint(organic, litter):
        """The tint of soil by its organic matter and litter in kg/m2: red, green, blue, opacity and strength."""
        strength = np.clip((organic + litter * 0.22) / 0.45, 0.0, 1.0)
        mature = np.clip(organic / 0.30, 0.0, 1.0)
        return 77 - mature * 22, 61 + mature * 20, 42 + mature * 4, 35 + strength * 112, strength

    @staticmethod
    def _soil_fade(alpha, strength):
        """Fade in from nothing, so the edge of soil formation is a gradient, not a step."""
        return np.where(strength <= 0.002, 0.0, alpha * np.clip(strength / 0.12, 0.0, 1.0))

    # ------------------------------------------------------------------
    # Pictures of the resting view
    # ------------------------------------------------------------------
    def _view_rests(self):
        """Whether the view has stopped moving (``_draw_generated_ground`` decides)."""
        rest = self._ground_rest
        return rest is not None and rest["view"] == self._ground_view

    def _rest_layer(self, screen, state, name, key, paint, hold=False):
        """A picture of the ground or of its plants, painted for the resting view and kept.

        While the view moves, the picture last painted is shown moved with
        the ground (``_blit_rest_layer``); it is painted anew once the view
        rests, unless it is to be held longer.  ``paint`` gives a dict with
        ``surface`` and ``at`` (its top left on the screen), or ``None``
        where there is nothing to show.
        """
        kept = self._rest_layers.get(name)
        if (kept is None or kept["size"] != screen.get_size()
                or (kept["key"] != key and self._view_rests() and not hold)):
            kept = paint()
            if kept is None:
                self._rest_layers.pop(name, None)
                return None
            kept.update(key=key, size=screen.get_size(), scale=state["scale"],
                        center=(state["center_x"], state["center_y"]), datum=state["datum_m"],
                        origin=(state["origin_x"], state["origin_y"]))
            self._rest_layers[name] = kept
        return kept

    @staticmethod
    def _layer_placed(kept, state, size):
        """A kept picture as the present view shows it: ``(surface, top left)``, moved and scaled with the ground."""
        scale = state["scale"]
        dx, dy = state["center_x"] - kept["center"][0], state["center_y"] - kept["center"][1]
        factor = scale / kept["scale"]
        left = state["origin_x"] + factor * (kept["at"][0] - kept["origin"][0]) - (dx - dy) * scale
        top = (state["origin_y"] + factor * (kept["at"][1] - kept["origin"][1]) - (dx + dy) * scale * 0.5
               + (state["datum_m"] - kept["datum"]) * state["vertical_scale"] * scale)
        surface = kept["surface"]
        left, top = float(left), float(top)
        if abs(factor - 1.0) < 1e-9:
            return surface, (round(left), round(top))
        # Only the part the screen shows is scaled: looked at from close, the whole would be many screens large.
        part = pygame.Rect(math.floor(-left / factor), math.floor(-top / factor),
                           math.ceil(size[0] / factor) + 2, math.ceil(size[1] / factor) + 2).clip(surface.get_rect())
        if part.width <= 0 or part.height <= 0:
            return None, (0, 0)
        token = (factor, part.x, part.y, part.width, part.height)
        scaled = kept.get("scaled")
        if scaled is None or scaled[0] != token:
            kept["scaled"] = scaled = (token, pygame.transform.scale(
                surface.subsurface(part), (max(1, round(part.width * factor)), max(1, round(part.height * factor)))))
        return scaled[1], (round(left + part.x * factor), round(top + part.y * factor))

    def _blit_rest_layer(self, screen, kept, state):
        surface, at = self._layer_placed(kept, state, screen.get_size())
        if surface is not None:
            screen.blit(surface, at)

    # ------------------------------------------------------------------
    # The ground under plants, in blocks
    # ------------------------------------------------------------------
    # Soil and what grows on it are drawn in blocks of this many screen pixels, each of one colour.
    GROUND_PIXEL_PX = 4
    # The tones of a block: one of them to a block, by the ground it lies on.
    GROUND_PIXEL_TONES = (0.80, 0.91, 1.0, 1.11)
    # How opaque (of 255) a block is that stands for plants not drawn one by one, and the steps of its colour.
    GROUND_PLANT_ALPHA = 235
    GROUND_PLANT_COLOUR_STEP = 12.0

    def _ground_pixels(self, size, state, coarser=1):
        """The blocks the ground under plants is drawn in: ``(left, top, world x, world y, numbers)``.

        Where the lattice of blocks begins on the screen, the ground under
        the middle of each block and three numbers in 0..1 to a block.  The
        lattice is the ground's own, as the view lays it out: where the
        ground goes on the screen its blocks go with it, each with its
        numbers, so a block keeps its colour while the view pans.  ``coarser``
        makes the blocks that many times larger.
        """
        block, scale = self.GROUND_PIXEL_PX * coarser, state["scale"]
        # Where the ground's lattice has a corner on the screen: the place of the point all views measure from.
        corner_x = state["origin_x"] - (state["center_x"] - state["center_y"]) * scale
        corner_y = (state["origin_y"] - (state["center_x"] + state["center_y"]) * scale * 0.5
                    + state["datum_m"] * state["vertical_scale"] * scale)
        left, top = float(corner_x % block - block), float(corner_y % block - block)
        key = (size, block, state["scale"], state["center_x"], state["center_y"], state["origin_x"], state["origin_y"],
               state["datum_m"], state["vertical_scale"], state["substrate"].fingerprint)
        cached = self._ground_pixel_cache.get(coarser)
        if cached is not None and cached[0] == key:
            return cached[1]
        world_x, world_y = self._ground_world_map(size, state, block, offset=(left, top))
        rows, columns = world_x.shape
        across = np.rint((left - corner_x) / block).astype(np.int64) + np.arange(columns, dtype=np.int64)
        down = np.rint((top - corner_y) / block).astype(np.int64) + np.arange(rows, dtype=np.int64)
        with np.errstate(over="ignore"):
            cell = ((across.astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15))[None, :]
                    ^ (down.astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F))[:, None])
        pixels = (left, top, world_x, world_y, tuple(plant_number(cell, stream) for stream in (11, 12, 13)))
        self._ground_pixel_cache[coarser] = (key, pixels)
        self._ground_cells[coarser] = (key, across, down)
        return pixels

    def _paint_ground_pixels(self, size, state, organic, litter, plants=None, coarser=1, patches=None):
        """The ground in blocks: soil by its organic matter and litter, and blocks of plants.

        ``plants`` is ``(colour, share)`` by block: that share of the blocks
        is drawn in that colour, for plants a view does not show one by one.
        ``patches`` (``_ground_patches``) are the species that cover ground
        as patches: each stands where its cover is larger than a number that
        changes slowly over the ground, so in beds with an outline, drawn in
        the texture of its own plants and as high as they are, with a darker
        side towards the viewer.  Nothing is blended: a block is soil of one
        tone, or plants, or clear.
        """
        left, top, _world_x, _world_y, numbers = self._ground_pixels(size, state, coarser)
        red, green, blue, alpha, strength = self._organic_tint(organic, litter)
        tones = np.asarray(self.GROUND_PIXEL_TONES)
        tone = tones[np.minimum(len(tones) - 1, (numbers[0] * len(tones)).astype(np.int64))]
        pixels = np.zeros(numbers[0].shape + (4,), dtype=np.float32)
        pixels[..., 0], pixels[..., 1], pixels[..., 2] = red * tone, green * tone, blue * tone
        # Thin soil comes in block by block: no block is half drawn.
        pixels[..., 3] = np.where((strength > 0.002) & (numbers[1] < np.clip(strength / 0.12, 0.0, 1.0)), alpha, 0.0)
        if plants is not None:
            colour, share = plants
            planted = numbers[2] < share
            if planted.any():
                step = self.GROUND_PLANT_COLOUR_STEP
                pixels[planted, :3] = ((np.floor(colour / step) * step + step * 0.5) * tone[..., None])[planted]
                pixels[planted, 3] = self.GROUND_PLANT_ALPHA
        for lift, species_id, cover, tile, side in patches or ():
            _key, across, down = self._ground_cells[coarser]
            clump = self.SWARD_CLUMP_BLOCKS if lift == 0 else self.PATCH_CLUMP_BLOCKS
            stands = cover > self._clump_numbers(across.astype(np.float64), down.astype(np.float64), species_id, clump)
            # A block with fewer than two of its four neighbours is no patch: it would stand as a post.
            beside = np.zeros(stands.shape, dtype=np.int8)
            beside[1:] += stands[:-1]
            beside[:-1] += stands[1:]
            beside[:, 1:] += stands[:, :-1]
            beside[:, :-1] += stands[:, 1:]
            stands &= beside >= 2
            if not stands.any():
                continue
            front = np.zeros_like(stands)
            for blocks in range(lift):
                front |= self._raised(stands, blocks)
            crown = self._raised(stands, lift)
            pixels[front, :3], pixels[front, 3] = side, 255.0
            # The texture is the ground's: a block of it stays on the piece of ground it stands on.
            texture = tile[((down + lift) % tile.shape[0])[:, None], (across % tile.shape[1])[None, :]]
            pixels[crown, :3], pixels[crown, 3] = texture[crown], 255.0
        if not (pixels[..., 3] > 0.0).any():
            return None
        data = np.clip(pixels, 0.0, 255.0).round().astype(np.uint8)
        small = pygame.image.frombuffer(data.tobytes(), (data.shape[1], data.shape[0]), "RGBA")
        block = self.GROUND_PIXEL_PX * coarser
        surface = pygame.transform.scale(small.convert_alpha() if pygame.display.get_surface() else small,
                                         (data.shape[1] * block, data.shape[0] * block))
        return {"surface": surface, "at": (left, top)}

    # While the view moves, ground the kept picture does not reach is drawn in blocks this many times larger.
    GROUND_PIXEL_COARSER_MOVING = 3

    def _draw_surroundings(self, screen, biosphere_sim, state, scenery):
        """The ground round the living area as its map has it, in blocks.

        The soil its vegetation stands on, and blocks in the colour of the
        plants the view does not show one by one (``surroundings``).  While
        the view moves, and until the plants of where it comes to rest are
        set out, the picture last painted goes with the ground; ground it
        does not reach is drawn in larger blocks with all its plants as
        blocks, since none of them is drawn there yet.
        """
        size = screen.get_size()
        view = (size, state["scale"], state["center_x"], state["center_y"], state["origin_x"],
                state["origin_y"], state["vertical_scale"], state["substrate"].fingerprint)

        def paint(coarser=1, shown=None):
            _left, _top, world_x, world_y, _numbers = self._ground_pixels(size, state, coarser)
            # In the larger blocks of a moving view what grows in patches is plants like the rest.
            colour, share, organic = scenery.ground(world_x, world_y, shown, patches_too=coarser > 1)
            patches = None if coarser > 1 else self._ground_patches(biosphere_sim, state, scenery.patch_cover(world_x, world_y))
            return self._paint_ground_pixels(size, state, organic, 0.0, plants=(colour, share), coarser=coarser,
                                             patches=patches)

        key = (view, id(scenery), scenery.revision, tuple(sorted(biosphere_sim.bounds.items())))
        kept = self._rest_layer(screen, state, "surroundings", key, paint, hold=scenery.pending)
        if kept is None:
            return
        if kept["key"] == key:
            screen.blit(kept["surface"], kept["at"])
            return
        surface, at = self._layer_placed(kept, state, size)
        reached = (surface.get_rect(topleft=at) if surface is not None else pygame.Rect(0, 0, 0, 0)).clip(screen.get_rect())
        if reached.size != size:
            coarse = self._moving_ground
            if coarse is None or coarse[0] != key[:2] + key[3:]:
                self._moving_ground = coarse = (key[:2] + key[3:], paint(self.GROUND_PIXEL_COARSER_MOVING, {}))
            if coarse[1] is not None:
                left, top = coarse[1]["at"]
                for part in ((pygame.Rect(0, 0, size[0], size[1]),) if reached.width <= 0 or reached.height <= 0 else (
                        pygame.Rect(0, 0, size[0], reached.top),
                        pygame.Rect(0, reached.bottom, size[0], size[1] - reached.bottom),
                        pygame.Rect(0, reached.top, reached.left, reached.height),
                        pygame.Rect(reached.right, reached.top, size[0] - reached.right, reached.height))):
                    if part.width > 0 and part.height > 0:
                        screen.blit(coarse[1]["surface"], part.topleft, area=part.move(-round(left), -round(top)))
        if surface is not None:
            screen.blit(surface, at)

    # ------------------------------------------------------------------
    # The plants round the living area, as one picture
    # ------------------------------------------------------------------
    # An unfinished picture of them is painted again this long after it was, once more plant pictures are there.
    PLANT_LAYER_REPAINT_SECONDS = 0.4

    def _tuft_picture(self, biosphere_sim, instance, scale):
        """A tuft of a sward or a crust as a small picture: ``(picture, where its foot lies in it)``."""
        profile = biosphere_sim.ecology.profiles[instance["species_id"]]
        key = (instance["species_id"], instance["growth_form"], instance["variant"], instance["display_maturity"],
               instance["visual_scale"], round(scale, 4), tuple(profile.color))
        kept = self._tuft_pictures.get(key)
        if kept is None:
            panel = pygame.Surface((112, 112), pygame.SRCALPHA)
            foot = (56, 72)
            # A crust's flecks are set by where it lies: a few different ones stand for all of them.
            self._draw_groundcover(panel, dict(instance, x=float(instance["variant"]), y=0.0), foot, scale,
                                   profile.color, profile.surface_growth_profile)
            filled = panel.get_bounding_rect(min_alpha=1)
            if filled.width <= 0 or filled.height <= 0:
                filled = pygame.Rect(foot[0], foot[1], 1, 1)
            kept = (panel.subsurface(filled).copy(), (foot[0] - filled.x, foot[1] - filled.y))
            if len(self._tuft_pictures) >= 4000:
                self._tuft_pictures.clear()
            self._tuft_pictures[key] = kept
        return kept

    # How dark a shadow lies on the ground (of 255), and how many screen pixels one of its pixels takes.
    SHADOW_ALPHA = 96
    SHADOW_PIXEL_PX = 3

    def _shadow_picture(self, sprite, abundance=0.8, solid=False):
        """The shadow on the ground under a plant picture: a few coarse pixels of shade, seen through.

        ``solid`` gives it opaque, for whoever lays many shadows into one
        picture and thins them together: where two overlap the ground is
        not twice as dark.
        """
        width = max(5, round(sprite.get_width() * (0.34 + abundance * 0.18)))
        height = max(5, round(width * 0.16))
        kept = self._shadow_pictures.get((width, height, solid))
        if kept is None:
            coarse = self.SHADOW_PIXEL_PX
            small = pygame.Surface((max(2, round(width / coarse)), max(1, round(height / coarse))), pygame.SRCALPHA)
            pygame.draw.ellipse(small, (31, 38, 27, 255 if solid else self.SHADOW_ALPHA), small.get_rect())
            kept = pygame.transform.scale(small, (width, height))
            if len(self._shadow_pictures) >= 4000:
                self._shadow_pictures.clear()
            self._shadow_pictures[(width, height, solid)] = kept
        return kept

    def _surrounding_plant_layer(self, screen, biosphere_sim, state, scenery, window, camera):
        """The plants round the living area as one picture of the resting view.

        They are many more than a frame can draw one by one, and they do not
        change.  So they are painted once for a view that rests, from the
        far edge to the near, and that picture is shown until the view rests
        elsewhere.  Kept with it is where each plant lies in it, for those
        that stand among the living area's own plants (``draw``).
        """
        units = biosphere_sim.world_units_to_meters
        view = (screen.get_size(), state["scale"], state["center_x"], state["center_y"], state["origin_x"],
                state["origin_y"], state["vertical_scale"], state["substrate"].fingerprint)
        kept = self._rest_layers.get("plants")
        if kept is None or self._view_rests():
            # Set out a few milliseconds a frame: the plants of the last view stand until those of this one do.
            within = None if self.sprite_budget_ms is None else 0.5 * self.sprite_budget_ms
            groups = scenery.groups(window, self._pixels_per_metre(camera, units), within_ms=within)
            if kept is not None and kept.get("pending") and kept.get("view") == view:
                waiting = [proto for proto in kept["pending"] if self._sprite_surface(biosphere_sim, proto, camera) is None]
                kept["progress"] = kept.get("progress", False) or len(waiting) < len(kept["pending"])
                kept["pending"] = waiting
                if kept["progress"] and (not waiting or time.monotonic() - kept["painted_at"] >= self.PLANT_LAYER_REPAINT_SECONDS):
                    self._plant_layer_attempt += 1
        else:
            groups = ()
        key = (view, id(scenery), scenery.plants_revision, getattr(biosphere_sim.world_model, "repository_revision", 0),
               getattr(camera, "sprite_height_cap", 84), units, self._plant_layer_attempt)
        return self._rest_layer(screen, state, "plants", key,
                                lambda: self._paint_surrounding_plants(screen.get_size(), biosphere_sim, state, groups, camera, view))

    def _paint_surrounding_plants(self, size, biosphere_sim, state, groups, camera, view):
        width, height = size
        generated = bool(state.get("generated"))
        sprites, shadows, pending = [], [], []
        columns = {name: [] for name in ("sprite", "left", "top", "foot_x", "foot_y", "depth", "world_y", "world_x")}
        for group in groups:
            foot_x, foot_y = self._iso_points(state, group["x"], group["y"])
            # A plant stands on its lower edge and reaches up and to the sides from there.
            side, above, below = self._plant_reach(state)
            seen = (foot_x > -side) & (foot_x < width + side) & (foot_y > -above) & (foot_y < height + below)
            if not seen.any():
                continue
            tuft = group["growth_form"] in {"graminoid", "lichen"}
            # The pictures the group needs: one to a kept individual, stage and size.
            code = (group["variant"][seen].astype(np.int64) * 10_000_000
                    + np.round(group["stage"][seen] * 1000.0).astype(np.int64) * 1000
                    + np.round(group["size"][seen] * 100.0).astype(np.int64))
            if not tuft and "mirrored" in group:
                code = code + group["mirrored"][seen].astype(np.int64) * 100_000_000_000
            codes, which = np.unique(code, return_inverse=True)
            number = np.full(len(codes), -1, dtype=np.int64)
            foot = np.zeros((len(codes), 2))
            for position, value in enumerate(codes.tolist()):
                mirrored, value = divmod(value, 100_000_000_000)
                proto = {"species_id": group["species_id"], "growth_form": group["growth_form"], "abundance": 0.8,
                         "age_bucket": 0, "variant": value // 10_000_000,
                         "display_maturity": (value % 10_000_000) // 1000 / 1000.0,
                         "visual_scale": (value % 1000) / 100.0, "display_only": True, "x": 0.0, "y": 0.0}
                picture = (self._tuft_picture(biosphere_sim, proto, state["scale"]) if tuft
                           else self._sprite_surface(biosphere_sim, proto, camera))
                if picture is None:
                    pending.append(proto)  # over this frame's painting budget: it comes with the next painting
                    continue
                if mirrored:
                    picture = (self._mirrored(picture[0]), (picture[0].get_width() - picture[1][0], picture[1][1]))
                number[position], foot[position] = len(sprites), picture[1]
                sprites.append(picture[0])
                shadows.append(self._shadow_picture(picture[0])
                               if generated and not tuft and picture[0].get_height() >= 14 else None)
            painted = number[which] >= 0
            if not painted.any():
                continue
            which = which[painted]
            foot_x, foot_y = foot_x[seen][painted], foot_y[seen][painted]
            world_x, world_y = group["x"][seen][painted], group["y"][seen][painted]
            columns["sprite"].append(number[which])
            columns["left"].append(np.round(foot_x - foot[which, 0]).astype(np.int64))
            columns["top"].append(np.round(foot_y - foot[which, 1]).astype(np.int64))
            columns["foot_x"].append(foot_x)
            columns["foot_y"].append(foot_y)
            columns["depth"].append(world_x + world_y)
            columns["world_y"].append(world_y)
            columns["world_x"].append(world_x)
        if not columns["sprite"]:
            if not pending:
                return None
            return {"surface": pygame.Surface(size, pygame.SRCALPHA), "at": (0, 0), "view": view, "count": 0,
                    "pending": pending, "painted_at": time.monotonic()}
        plants = {name: np.concatenate(parts) for name, parts in columns.items()}
        # From the far edge to the near, as ``draw`` orders the living area's plants.
        order = np.lexsort((plants["world_x"], plants["world_y"], plants["depth"]))
        plants = {name: values[order] for name, values in plants.items()}
        widths = np.array([sprite.get_width() for sprite in sprites], dtype=np.int64)[plants["sprite"]]
        heights = np.array([sprite.get_height() for sprite in sprites], dtype=np.int64)[plants["sprite"]]
        layer = pygame.Surface(size, pygame.SRCALPHA)
        shadow_at = [None if shadow is None else (shadow.get_width() * 0.5, shadow.get_height() * 0.4) for shadow in shadows]
        number, left, top = plants["sprite"].tolist(), plants["left"].tolist(), plants["top"].tolist()
        feet_x, feet_y = plants["foot_x"].tolist(), plants["foot_y"].tolist()
        # The shadows lie under all of them, as one shade: laid in opaque and thinned together.
        solid = [None if shadow is None else self._shadow_picture(sprites[k], solid=True) for k, shadow in enumerate(shadows)]
        layer.blits([(solid[k], (round(fx - shadow_at[k][0]), round(fy - shadow_at[k][1])))
                     for k, fx, fy in zip(number, feet_x, feet_y) if solid[k] is not None], doreturn=False)
        layer.fill((255, 255, 255, self.SHADOW_ALPHA), special_flags=pygame.BLEND_RGBA_MULT)
        layer.blits([(sprites[k], (x, y)) for k, x, y in zip(number, left, top)], doreturn=False)
        plants.update(right=plants["left"] + widths, bottom=plants["top"] + heights + 8)
        return {"surface": layer, "at": (0, 0), "view": view, "count": len(number), "pending": pending,
                "painted_at": time.monotonic(), "plants": plants, "sprites": sprites, "shadows": shadows,
                "shadow_at": shadow_at}

    def _surrounding_plants_among(self, layer, own):
        """The plants of the surroundings whose pictures reach into a part of the screen, from the far to the near.

        Each is ``(depth, picture, top left, shadow, top left of the shadow)``, the depth as ``draw`` orders by.
        """
        kept = layer.get("among")
        token = (own.x, own.y, own.width, own.height)
        if kept is not None and kept[0] == token:
            return kept[1]
        plants = layer["plants"]
        reach = np.flatnonzero((plants["left"] < own.right) & (plants["right"] > own.left)
                               & (plants["top"] < own.bottom) & (plants["bottom"] > own.top))
        sprites, shadows, shadow_at = layer["sprites"], layer["shadows"], layer["shadow_at"]
        among = [((depth, world_y, world_x), sprites[k], (x, y), shadows[k],
                  None if shadows[k] is None else (round(fx - shadow_at[k][0]), round(fy - shadow_at[k][1])))
                 for depth, world_y, world_x, k, x, y, fx, fy in zip(*(plants[name][reach].tolist() for name in (
                     "depth", "world_y", "world_x", "sprite", "left", "top", "foot_x", "foot_y")))]
        layer["among"] = (token, among)
        return among

    # ------------------------------------------------------------------
    # Plants that grow in patches, drawn as the ground they cover
    # ------------------------------------------------------------------
    # A patch's texture repeats after this many blocks; its outline is ragged at about that many blocks; it
    # stands at most this many blocks high.
    PATCH_TILE_BLOCKS = 32
    PATCH_CLUMP_BLOCKS = 7.0
    PATCH_LIFT_MAX_BLOCKS = 3
    # A sward is a turf, not beds: it lies flat (no side), and is broken into clumps this many blocks across.
    SWARD_CLUMP_BLOCKS = 2.5

    def _patch_texture(self, biosphere_sim, species_id, block_m):
        """What a patch of a species looks like from above, block by block, and the colour of its side.

        Made of the species' own picture from above (``plant_pictures``):
        its plants set side by side as close as they stand, or, where a
        plant is no larger than a block, a block the colour of a piece of
        one.  ``(tile, side colour)``; the tile repeats.
        """
        ecology = biosphere_sim.ecology
        profile = ecology.profiles[species_id]
        spacing = (ecology.spacing_m(profile) if ecology.keeps_individuals(profile)
                   else VegetationSampler.SPACING_M.get(profile.growth_form, 0.28))
        size = self.PATCH_TILE_BLOCKS
        stamp = max(1, min(size // 2, round(spacing / max(block_m, 1e-9))))
        key = (id(biosphere_sim.world_model), getattr(biosphere_sim.world_model, "repository_revision", 0), species_id, stamp)
        kept = self._patch_textures.get(key)
        if kept is not None:
            return kept
        rng = np.random.default_rng(zlib.crc32(species_id.encode("utf-8")))
        picture = plant_picture(getattr(biosphere_sim, "plant_pictures", None), species_id, 0)
        colours = None
        if picture is not None:
            opaque = pygame.surfarray.array_alpha(picture) > 0
            if opaque.any():
                colours = pygame.surfarray.array3d(picture)[opaque].astype(np.float32)
        if colours is None:
            # Nothing of it shows from above: the colour its flecks are drawn in, in a few tones.
            base = 0.8 * np.asarray(profile.color, dtype=np.float32)[:3]
            tile = base * rng.choice(np.asarray(self.GROUND_PIXEL_TONES, dtype=np.float32), size=(size, size, 1))
        else:
            base = colours.mean(axis=0)
            step = self.GROUND_PLANT_COLOUR_STEP
            if stamp == 1:
                tile = np.floor(colours[rng.integers(0, len(colours), size=(size, size))] / step) * step + step * 0.5
            else:
                tile = np.empty((size, size, 3), dtype=np.float32)
                tile[...] = base * 0.8  # between two plants: the ground in their shade
                small = map_sprite_at(picture, stamp)
                colour = np.transpose(pygame.surfarray.array3d(small), (1, 0, 2)).astype(np.float32)
                solid = pygame.surfarray.array_alpha(small).T > 0
                # As many as stand on that much ground, anywhere on it: set in rows they would show as a grid.
                for _plant in range(int((size / stamp) ** 2 * 1.4)):
                    rows = (int(rng.integers(0, size)) + np.arange(colour.shape[0])) % size
                    columns = (int(rng.integers(0, size)) + np.arange(colour.shape[1])) % size
                    part = tile[np.ix_(rows, columns)]
                    part[solid] = colour[solid]
                    tile[np.ix_(rows, columns)] = part
        tile, base = self._calmed(tile), self._calmed(base)
        kept = (np.clip(tile, 0.0, 255.0).astype(np.float32), np.clip(base * 0.68, 0.0, 255.0))
        if len(self._patch_textures) >= 256:
            self._patch_textures.clear()
        self._patch_textures[key] = kept
        return kept

    def _ground_patches(self, biosphere_sim, state, covers):
        """What ``_paint_ground_pixels`` needs of each species that covers ground in patches, the lowest first."""
        px_per_m = state["scale"] / max(1e-9, float(biosphere_sim.world_units_to_meters or 1.0))
        block = self.GROUND_PIXEL_PX
        patches = []
        for species_id, cover in covers.items():
            if not (cover > 0.02).any():
                continue
            tile, side = self._patch_texture(biosphere_sim, species_id, block / px_per_m)
            profile = biosphere_sim.ecology.profiles[species_id]
            lift = (0 if profile.growth_form == "graminoid"
                    else min(self.PATCH_LIFT_MAX_BLOCKS, int(round(profile.mature_height_m * px_per_m / block))))
            patches.append((lift, species_id, cover, tile, side))
        return sorted(patches, key=lambda patch: (patch[0], patch[1]))

    @staticmethod
    def _clump_raw(across, down, salt):
        """A number for every block that changes slowly from block to block: ``across`` and ``down`` count clumps."""
        left, top = np.floor(across).astype(np.int64), np.floor(down).astype(np.int64)
        fx, fy = across - left, down - top
        fx, fy = (fx * fx * (3.0 - 2.0 * fx))[None, :], (fy * fy * (3.0 - 2.0 * fy))[:, None]

        def corner(dx, dy):
            with np.errstate(over="ignore"):
                cell = (((left + dx).astype(np.uint64) * np.uint64(0x9E3779B97F4A7C15))[None, :]
                        ^ ((top + dy).astype(np.uint64) * np.uint64(0xC2B2AE3D27D4EB4F))[:, None]) ^ np.uint64(salt)
            return plant_number(cell, 14)

        return (corner(0, 0) * (1.0 - fx) + corner(1, 0) * fx) * (1.0 - fy) + (corner(0, 1) * (1.0 - fx) + corner(1, 1) * fx) * fy

    def _clump_numbers(self, across, down, species_id, clump_blocks=None):
        """A number in 0..1 for every block, alike in neighbouring blocks: where a cover is larger, a patch stands.

        Every number is as frequent as any other, so a species stands on
        about the share of the blocks its cover is.
        """
        if self._clump_ranks is None:
            sample = np.arange(0.0, 96.0, 0.37)
            self._clump_ranks = np.sort(self._clump_raw(sample, sample, 17).ravel())
        clump_blocks = clump_blocks or self.PATCH_CLUMP_BLOCKS
        raw = self._clump_raw(across / clump_blocks, down / clump_blocks,
                              zlib.crc32(species_id.encode("utf-8")))
        return (np.searchsorted(self._clump_ranks, raw) + 0.5) / len(self._clump_ranks)

    @staticmethod
    def _raised(stands, blocks):
        """Blocks shown ``blocks`` higher on the screen."""
        if blocks <= 0:
            return stands
        raised = np.zeros_like(stands)
        raised[:-blocks] = stands[blocks:]
        return raised

    def _own_patch_cover(self, biosphere_sim, world_x, world_y, state=None):
        """The cover at points of the living area's own swards and crusts, by species.

        A sward seen close enough to be its tufts is left out: the view draws its plants (as round the
        living area, ``surroundings.SWARD_PLANTS_FROM_PX``).
        """
        ecology = biosphere_sim.ecology
        if not callable(getattr(ecology, "species_patches", None)) or not callable(getattr(ecology, "keeps_individuals", None)):
            return {}
        bounds = ecology.bounds
        inside = ((world_x >= bounds["min_x"]) & (world_x <= bounds["max_x"])
                  & (world_y >= bounds["min_y"]) & (world_y <= bounds["max_y"]))
        covers = {}
        if not inside.any():
            return covers
        px_per_m = (state["scale"] / max(1e-9, float(biosphere_sim.world_units_to_meters or 1.0))
                    if state is not None and state.get("generated") else None)
        for species_id in sorted({patch.species_id for patch in ecology.patches if patch.abundance > 0.006}):
            profile = ecology.profiles[species_id]
            if ecology.keeps_individuals(profile):
                continue
            if (px_per_m is not None and profile.growth_form == "graminoid"
                    and profile.mature_height_m * px_per_m >= SWARD_PLANTS_FROM_PX):
                continue
            cover = np.zeros(world_x.shape, dtype=np.float32)
            cover[inside] = population_abundances(ecology, species_id, world_x[inside], world_y[inside])
            covers[species_id] = cover
        return covers

    def _draw_organic_soil(self, screen, biosphere_sim, state):
        """Tint soil state without changing the authoritative mineral ground."""
        soil = getattr(biosphere_sim, "soil", None)
        mode = getattr(biosphere_sim, "soil_diagnostic_mode", "organic")
        if soil is None or (mode == "organic" and soil.summary()["max_soil_organic_matter_kg_m2"] <= 0.0001):
            return
        substrate = state.get("substrate")
        key = (id(soil), soil.revision, mode, screen.get_size(), state["scale"], state["center_x"], state["center_y"],
               state["origin_x"], state["origin_y"], state.get("vertical_scale", 1.0),
               getattr(substrate, "fingerprint", None))
        if self._soil_overlay_cache is not None and self._soil_overlay_cache[0] == key:
            screen.blit(self._soil_overlay_cache[1], (0, 0))
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        lattice_x = soil.bounds["min_x"] + np.arange(soil.columns + 1) * (soil.bounds["max_x"] - soil.bounds["min_x"]) / soil.columns
        lattice_y = soil.bounds["min_y"] + np.arange(soil.rows + 1) * (soil.bounds["max_y"] - soil.bounds["min_y"]) / soil.rows
        corner_x, corner_y = self._iso_points(state, *np.meshgrid(lattice_x, lattice_y))
        corner_x, corner_y = corner_x.tolist(), corner_y.tolist()
        for row in range(soil.rows):
            for column in range(soil.columns):
                organic = soil.organic_matter_rows[row][column]
                litter = soil.litter_rows[row][column]
                if mode == "nitrogen":
                    value = soil.available_nitrogen_rows[row][column]
                    strength = max(0.0, min(1.0, value / 0.35))
                    color = (44, round(80 + strength * 95), 112, round(38 + strength * 145))
                elif mode == "phosphorus":
                    value = soil.available_phosphorus_rows[row][column]
                    strength = max(0.0, min(1.0, value / 0.12))
                    color = (round(105 + strength * 115), 72, round(120 + strength * 90), round(38 + strength * 145))
                else:
                    strength = max(0.0, min(1.0, (organic + litter * 0.22) / 0.45))
                    mature = max(0.0, min(1.0, organic / 0.30))
                    color = (
                        round(77 - mature * 22),
                        round(61 + mature * 20),
                        round(42 + mature * 4),
                        round(35 + strength * 112),
                    )
                if strength <= 0.002:
                    continue
                points = [
                    (corner_x[row][column], corner_y[row][column]),
                    (corner_x[row][column + 1], corner_y[row][column + 1]),
                    (corner_x[row + 1][column + 1], corner_y[row + 1][column + 1]),
                    (corner_x[row + 1][column], corner_y[row + 1][column]),
                ]
                pygame.draw.polygon(overlay, color, points)
        self._soil_overlay_cache = (key, overlay)
        screen.blit(overlay, (0, 0))

    def _draw_population_patches(self, screen, biosphere_sim, state):
        if getattr(biosphere_sim, "substrate", None) is not None and not getattr(biosphere_sim, "show_population_footprints", False):
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        patches = sorted(biosphere_sim.ecology.population_footprints(), key=lambda item: item["x"] + item["y"])
        for patch in patches:
            points = []
            for index in range(24):
                angle = math.tau * index / 24.0
                wobble = 1.0 + 0.08 * math.sin(index * 2.17 + len(patch["patch_id"]))
                points.append(self._iso(
                    state,
                    max(biosphere_sim.bounds["min_x"], min(biosphere_sim.bounds["max_x"], patch["x"] + math.cos(angle) * patch["radius_m"] * wobble)),
                    max(biosphere_sim.bounds["min_y"], min(biosphere_sim.bounds["max_y"], patch["y"] + math.sin(angle) * patch["radius_m"] * wobble)),
                ))
            abundance = max(0.0, min(1.0, patch["abundance"]))
            color = patch["color"]
            pygame.draw.polygon(overlay, (*color, round(40 + abundance * 78)), points)
        screen.blit(overlay, (0, 0))

    def draw(self, screen, biosphere_sim):
        if getattr(biosphere_sim, "simulation_mode", None) != "biosphere_builder":
            return
        self._frame_started = time.perf_counter()
        self._sprites_painted = 0
        state = self._projection(screen, biosphere_sim)
        # Reuse unchanged scene sprites across frames, not only within one frame.
        # Deep representative snapshots/repository revision invalidate real growth.
        representatives = getattr(biosphere_sim, "representatives", None)
        rep_key = tuple((r.representative_id, id(r.simulation.render_snapshot), r.simulation.seed)
                        for r in representatives.items(alive_only=True)) if representatives is not None else ()
        context = (id(biosphere_sim.world_model), getattr(biosphere_sim.world_model, "repository_revision", 0),
                   state["scale"], getattr(biosphere_sim, "isometric_sprite_height_cap", 84),
                   biosphere_sim.world_units_to_meters, rep_key)
        if context != self._frame_surface_context:
            self._frame_surfaces = {}
            self._frame_surface_context = context
        self._draw_ground(screen, biosphere_sim, state)
        show_vegetation = bool(getattr(biosphere_sim, "show_vegetation", True))
        landscape = bool(state.get("generated")) and state.get("substrate") is not None
        window = self._vegetation_window(screen, state) if landscape and show_vegetation else None
        sprite_camera = SimpleNamespace(
            zoom=state["scale"],
            sprite_height_cap=getattr(biosphere_sim, "isometric_sprite_height_cap", 84),
            true_scale=bool(state.get("generated")),
            enlarged_to=self.ENLARGED_TO_PX if state.get("generated") else None,
        )
        self._true_scale = sprite_camera.true_scale
        # What the map shows round the living area (``surroundings``).  Its plants are set out before its
        # ground is drawn: the ground has in it those the view does not show one by one.
        scenery = getattr(biosphere_sim, "surroundings", None) if window is not None else None
        plant_layer = (self._surrounding_plant_layer(screen, biosphere_sim, state, scenery, window, sprite_camera)
                       if scenery is not None else None)
        if landscape:
            self._draw_soil_tint(screen, biosphere_sim, state)
            if scenery is not None:
                self._draw_surroundings(screen, biosphere_sim, state, scenery)
        else:
            self._draw_organic_soil(screen, biosphere_sim, state)
        if show_vegetation:
            self._draw_population_patches(screen, biosphere_sim, state)
        instances = list(getattr(biosphere_sim, "get_species_sprite_instances", lambda: [])() or []) if show_vegetation else []
        vegetation = self._vegetation_sampler.sample(
            biosphere_sim.ecology, instances, true_scale=bool(state.get("generated")),
            window=window) if show_vegetation else []
        biosphere_sim._vegetation_render_count = len(vegetation)
        biosphere_sim._surroundings_render_count = plant_layer["count"] if plant_layer is not None else 0
        instances.extend(vegetation)
        instances.sort(key=lambda item: (item["x"] + item["y"], item["y"], item["x"]))
        hitboxes = []
        # Further out than a plant is tall and wide it cannot reach the screen.
        side, above, below = self._plant_reach(state)
        paint_rect = pygame.Rect(-side, -max(above, 240.0), screen.get_width() + 2 * side,
                                 screen.get_height() + max(above, 240.0) + max(below, 240.0))
        cover_rect = screen.get_rect().inflate(30, 30)
        anchors_x, anchors_y = self._iso_points(
            state, [instance["x"] for instance in instances], [instance["y"] for instance in instances],
        ) if instances else ((), ())
        # What is to be drawn of the living area's own, from the far edge to the near, and the part of the
        # screen it takes.
        own_plants, own = [], None
        for instance, anchor_screen in zip(instances, zip(
                getattr(anchors_x, "tolist", lambda: [])(), getattr(anchors_y, "tolist", lambda: [])())):
            depth = (instance["x"] + instance["y"], instance["y"], instance["x"])
            if (landscape and instance.get("growth_form") == "graminoid" and "display_maturity" in instance
                    and not instance.get("representative_id")
                    and getattr(biosphere_sim, "plant_pictures", None) is not None):
                # On generated ground a grass of a sward is its own picture, as it is round the living area.
                instance = dict(instance, growth_form="structural_graminoid")
            if instance.get("growth_form") in {"graminoid", "lichen"}:
                if not cover_rect.collidepoint(anchor_screen):
                    continue
                own_plants.append((depth, instance, anchor_screen, None, None))
                taken = pygame.Rect(round(anchor_screen[0]) - 22, round(anchor_screen[1]) - 46, 44, 64)
            else:
                if not paint_rect.collidepoint(anchor_screen):
                    continue
                picture = self._sprite_surface(biosphere_sim, instance, sprite_camera)
                if picture is None:
                    continue  # over this frame's painting budget; it appears next frame
                sprite, root_anchor = picture
                x = round(anchor_screen[0] - root_anchor[0])
                y = round(anchor_screen[1] - root_anchor[1])
                if x > screen.get_width() or y > screen.get_height() or x + sprite.get_width() < 0 or y + sprite.get_height() < 0:
                    continue
                own_plants.append((depth, instance, anchor_screen, sprite, (x, y)))
                taken = pygame.Rect(x - 4, y - 4, sprite.get_width() + 8, sprite.get_height() + 16)
            own = taken if own is None else own.union(taken)
        # The plants round the living area are one picture.  Where the living area's own plants stand, those
        # of them that reach in are drawn one by one among them, each behind what stands nearer.
        among, whole = (), screen.get_clip()
        if plant_layer is not None:
            picture = plant_layer["surface"]
            if plant_layer.get("view") != (screen.get_size(), state["scale"], state["center_x"], state["center_y"],
                                           state["origin_x"], state["origin_y"], state["vertical_scale"],
                                           state["substrate"].fingerprint):
                self._blit_rest_layer(screen, plant_layer, state)  # the view moves: the picture moves with the ground
            elif own is None or not plant_layer["count"]:
                screen.blit(picture, (0, 0))
            else:
                own = own.clip(screen.get_rect())
                for part in (pygame.Rect(0, 0, screen.get_width(), own.top),
                             pygame.Rect(0, own.bottom, screen.get_width(), screen.get_height() - own.bottom),
                             pygame.Rect(0, own.top, own.left, own.height),
                             pygame.Rect(own.right, own.top, screen.get_width() - own.right, own.height)):
                    if part.width > 0 and part.height > 0:
                        screen.blit(picture, part.topleft, area=part)
                among = self._surrounding_plants_among(plant_layer, own)
        reached, held, behind_all = 0, False, True
        for depth, instance, anchor_screen, sprite, at in own_plants + [(None, None, None, None, None)]:
            # First what of the surroundings stands behind this plant (after the last: all that is left).
            while reached < len(among) and (depth is None or among[reached][0] < depth):
                if not held:
                    screen.set_clip(own.clip(whole))
                    held = True
                _depth, picture, place, shadow, shadow_place = among[reached]
                if shadow is not None:
                    screen.blit(shadow, shadow_place)
                if not behind_all and picture.get_height() >= self.SEE_THROUGH_FROM_PX:
                    picture = self._see_through(picture)  # it stands in front of plants of the living area
                screen.blit(picture, place)
                reached += 1
            if held:
                screen.set_clip(whole)
                held = False
            if instance is None:
                break
            behind_all = False
            if sprite is None:
                rect = self._draw_groundcover(screen, instance, anchor_screen, state["scale"],
                                              biosphere_sim.ecology.profiles[instance["species_id"]].color,
                                              biosphere_sim.ecology.profiles[instance["species_id"]].surface_growth_profile)
                if instance.get("representative_id"):
                    hitboxes.append((instance["representative_id"], rect.inflate(8, 8)))
                if instance.get("selected"):
                    pygame.draw.rect(screen, (255, 224, 112), rect.inflate(6, 6), 2)
                continue
            x, y = at
            abundance = max(0.0, min(1.0, float(instance.get("abundance", 0.0) or 0.0)))
            shadow_w = max(5, round(sprite.get_width() * (0.34 + abundance * 0.18)))
            # A ground shadow in proportion: a flat 5 px line under a 300 px tree reads as a dash.
            shadow_h = max(5, round(shadow_w * 0.16)) if state.get("generated") else 5
            if not state.get("generated"):
                pygame.draw.ellipse(
                    screen,
                    (31, 38, 27),
                    (round(anchor_screen[0] - shadow_w / 2), round(anchor_screen[1] - shadow_h * 0.4), shadow_w, shadow_h),
                )
            elif sprite.get_height() >= 14:
                # Under a plant a few pixels tall the shadow would be all one sees.
                screen.blit(self._shadow_picture(sprite, abundance),
                            (round(anchor_screen[0] - shadow_w / 2), round(anchor_screen[1] - shadow_h * 0.4)))
            screen.blit(sprite, (x, y))
            sprite_rect = pygame.Rect(x, y, sprite.get_width(), sprite.get_height())
            representative_id = instance.get("representative_id")
            if representative_id:
                hitboxes.append((representative_id, sprite_rect.inflate(8, 8)))
            if instance.get("selected"):
                pygame.draw.rect(screen, (255, 224, 112), sprite_rect.inflate(6, 6), 2, border_radius=4)
        biosphere_sim._representative_screen_hitboxes = hitboxes
        self._draw_seeding_ring(screen, biosphere_sim, state)

    def _vegetation_window(self, screen, state):
        """The ground whose plants can reach the screen, as ``(u0, u1, v0, v1)`` in ``x - y`` and ``x + y``.

        Snapped to a lattice of an eighth of the view or coarser and of one
        size per zoom, so the display plants are taken from the populations
        again only when the view has moved a good part of a screen, and never
        change density while it pans.
        """
        substrate = state.get("substrate")
        scale = state["scale"]
        width, height = screen.get_size()
        # A plant stands on its lower edge and reaches up and to the sides from there.
        side, above, below = self._plant_reach(state)
        centre_u = state["center_x"] - state["center_y"]
        centre_v = state["center_x"] + state["center_y"]
        u0 = centre_u + (-side - state["origin_x"]) / scale
        u1 = centre_u + (width + side - state["origin_x"]) / scale
        v0 = centre_v + (-above - state["origin_y"]) / (scale * 0.5)
        v1 = centre_v + (height + below - state["origin_y"]) / (scale * 0.5)
        # Ground above the drawing plane is seen higher on the screen.
        probe_u, probe_v = np.meshgrid(np.linspace(u0, u1, 5), np.linspace(v0, v1, 5))
        bounds = substrate.bounds
        probe_x = np.clip((probe_u + probe_v) * 0.5, bounds["min_x"], bounds["max_x"])
        probe_y = np.clip((probe_v - probe_u) * 0.5, bounds["min_y"], bounds["max_y"])
        relief = (substrate.elevation_array(probe_x, probe_y, True) - state["datum_m"]) * state["vertical_scale"]
        v0 += 2.0 * min(0.0, float(relief.min()))
        v1 += 2.0 * max(0.0, float(relief.max()))
        box = []
        for low, high in ((u0, u1), (v0, v1)):
            extent = max(high - low, 1e-6)
            lattice = 2.0 ** math.ceil(math.log2(extent / 8.0))
            low = math.floor(low / lattice) * lattice
            box += [low, low + (math.ceil(extent / lattice) + 1) * lattice]
        return tuple(box)

    def _draw_seeding_ring(self, screen, biosphere_sim, state):
        """Where a click would sow, draped on the ground under the pointer."""
        preview = getattr(biosphere_sim, "get_seeding_preview", lambda: None)()
        if not preview:
            return
        angles = np.linspace(0.0, math.tau, 49)
        ring_x, ring_y = self._iso_points(
            state, preview["x"] + np.cos(angles) * preview["radius_m"], preview["y"] + np.sin(angles) * preview["radius_m"])
        points = list(zip(ring_x.tolist(), ring_y.tolist()))
        if max(ring_x) - min(ring_x) < 6:
            return
        pygame.draw.lines(screen, (28, 34, 26), True, points, 3)
        pygame.draw.lines(screen, (236, 244, 214) if preview["brush"] else (190, 204, 170), True, points, 1)
