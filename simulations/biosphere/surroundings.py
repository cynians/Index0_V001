"""The ground round a Biosphere's living area, as the map of it shows it.

A Biosphere simulates its living area: a few metres of ground at first, more
as the player plants.  That area lies in a landscape a map already shows
with its woods and meadows (``simulations/city/city_vegetation.py``), and the
isometric view looks at the same ground.  So the view is given what the map
has there:

* the same plants at the same places (``ResidentVegetation.individuals``):
  the planet's own places.  Close to the living area each is the very
  individual of its species, as far grown, that it is as a resident: when
  the living area grows over it, it is that resident
  (``ResidentFlora.settle``).  Further off a plant is drawn as a map draws
  its species: one of the few individuals kept from above, at one of three
  sizes, so a wide view does not need a picture of every individual at
  every stage;
* a sward or a crust, which is cover and no plants, as tufts set out at the
  places a display gives them, as thick as the cover is;
* all of them, as many as there are (owner, 2026-10-12: the green of the
  ground is its plants, at their density).  Only what would be a pixel or
  two tall in a view, or more than a view can hold, is left out, and is
  told as a share of the ground instead (``ground``), which whoever draws
  the ground sets in it as single pixels of the plants' colour
  (``plant_pictures.plant_colour``);
* under it the soil a grown community stands on, as the residents have it.

Round the living area the ground is read as closely as for the residents
(``ResidentFlora.vegetation``); beyond that as a map of the whole ground
reads it (``potential_vegetation.MAP_CELLS`` cells along a side, a city
map's own lattice), so far off the view shows what that map shows.

None of this is simulated.  It does not grow, die, seed into the living area
or shade it: it is what the map says stands there, and what the living area
takes over as it grows.
"""

from __future__ import annotations

import math
import time

import numpy as np

from simulations.biosphere.plant_pictures import MAP_SPRITE_DIR, MAP_VARIANTS, STAGES, plant_colour
from simulations.biosphere.potential_vegetation import (
    CLIMBER_LAYER, LAYERS, MAP_CELLS, plant_number, resident_vegetation,
)
from simulations.biosphere.resident_start import FULL_SOIL_COVER, RESIDENT_ORGANIC_MATTER_KG_M2, kept_individual
from simulations.biosphere.vegetation import VegetationSampler


# How many plants and tufts of the surroundings a view is given: what one picture of them takes a few
# hundredths of a second to paint.  A close view of a meadow holds some tens of thousands of tufts and herbs.
PLANT_BUDGET = 80_000
# A species with more places than this in a view is not set out plant by plant there.
MAX_PLACES = 1_000_000
# The places of a species are gone through this many at a time, a strip of the view after the other: a step
# of the setting out takes a few hundredths of a second.
PLACES_A_STEP = 60_000
# A sward's tufts are drawn in its own colour, this much darker (``BiosphereBuilderRenderer._draw_groundcover``).
TUFT_SHADE = 0.8
# A plant that would stand lower than this many pixels in a view is not set out in it.
LEAST_PLANT_PX = 2.0
# How high a tuft of a sward or a crust is drawn, in metres (``BiosphereBuilderRenderer._draw_groundcover``).
TUFT_HEIGHT_M = 0.32
# Within this many metres of the living area a plant is drawn as the individual and stage a resident there is.
EXACT_WITHIN_M = 6.0
# The shares of full size further plants are drawn at, and the steps in which they differ in size.
FAR_STAGES = (0.30, 0.68, 1.0)
SIZE_STEP, FAR_SIZE_STEP = 0.1, 0.15
# Of a plant that grows in patches (a sward, a crust, what spreads into beds) the patch is drawn as ground
# it covers, and this share of its plants stands on it.
PATCH_PLANT_SHARE = 1.0 / 8.0
# A plant that spreads into beds is drawn so only up to this height in metres, as a mat: a taller one (a
# thistle, bracken) is its single plants, which as a texture on the ground are noise.
PATCH_MAX_HEIGHT_M = 0.6
# Close in, a sward is its plants: where its tufts stand this many pixels high and the view has room for at
# least every other one, they are drawn and its patch is not.  A meadow is grass, not beds of its colour.
SWARD_PLANTS_FROM_PX = 12.0
# Readings of the ground whose colours are kept.
LATTICES_KEPT = 6


def _inside(bounds, x, y):
    return (x >= bounds["min_x"]) & (x <= bounds["max_x"]) & (y >= bounds["min_y"]) & (y <= bounds["max_y"])


def _between_cells(vegetation, lattice, x, y):
    """``ResidentVegetation.between_cells`` for a lattice of several values to a cell."""
    rows, columns = vegetation.x.shape
    bounds = vegetation.bounds
    gx = np.clip((x - bounds["min_x"]) / (bounds["max_x"] - bounds["min_x"]) * columns - 0.5, 0.0, columns - 1.0)
    gy = np.clip((y - bounds["min_y"]) / (bounds["max_y"] - bounds["min_y"]) * rows - 0.5, 0.0, rows - 1.0)
    ix, iy = np.minimum(gx.astype(np.int64), columns - 2), np.minimum(gy.astype(np.int64), rows - 2)
    fx, fy = (gx - ix).astype(lattice.dtype)[..., None], (gy - iy).astype(lattice.dtype)[..., None]
    return ((lattice[iy, ix] * (1.0 - fx) + lattice[iy, ix + 1] * fx) * (1.0 - fy)
            + (lattice[iy + 1, ix] * (1.0 - fx) + lattice[iy + 1, ix + 1] * fx) * fy)


class Surroundings:
    """What the map shows round the living area of a Biosphere."""

    def __init__(self, flora):
        self.flora = flora
        # Of each species: the share of its plants (of a sward: its tufts) in view that are drawn as plants.
        self.shown = {}
        # The species that grow in patches which the last view drew as their plants instead (``SWARD_PLANTS_FROM_PX``).
        self.as_plants = frozenset()
        # Counts every change of ``shown``, for whoever keeps a picture of the ground.
        self.revision = 0
        self._far = None
        # Counts every set of plants set out, for whoever keeps a picture of them.
        self.plants_revision = 0
        self._plants_key = None
        self._groups = []
        self._plants = []
        self._work = None
        self._colours = {}
        self._lattices = {}
        self._patch_lattices = {}
        simulation = flora.simulation
        pictures = getattr(simulation, "plant_pictures", None)
        if (pictures is not None and pictures.map_sprite_dir is None
                and getattr(getattr(simulation.world_model, "loader", None), "use_ontology", False)):
            # A session on the stored world keeps the pictures from above for the next one, as a city's map does.
            pictures.map_sprite_dir = MAP_SPRITE_DIR

    @property
    def pending(self):
        """Whether the plants of the view last asked for are still being set out (``groups`` with ``within_ms``)."""
        return self._work is not None

    def grows_in_patches(self, species_id):
        """Whether a species is drawn as the ground it covers: a sward, a crust, or a plant that spreads into beds."""
        ecology = self.flora.simulation.ecology
        profile = ecology.profiles[species_id]
        return not ecology.keeps_individuals(profile) or (
            getattr(profile, "clonal_spread", "") == "high" and profile.mature_height_m <= PATCH_MAX_HEIGHT_M)

    # ------------------------------------------------------------------
    def far(self):
        """The whole ground as a map of it reads it; ``None`` where the residents' reading holds all of it."""
        simulation = self.flora.simulation
        frame, near = simulation.terrain_frame, self.flora.vegetation().bounds
        if all(near[f"min_{axis}"] <= frame[f"min_{axis}"] + 1e-6 and near[f"max_{axis}"] >= frame[f"max_{axis}"] - 1e-6
               for axis in "xy"):
            return None
        if self._far is None:
            self._far = resident_vegetation(simulation.substrate, dict(frame), self.flora.profiles(), self.flora.floras,
                                            cells=MAP_CELLS, seed=self.flora.seed)
        return self._far

    def _readings(self, reaches_beyond):
        """The readings of the ground, the closer first, each with the ground a closer one has taken."""
        near = self.flora.vegetation()
        far = self.far() if reaches_beyond(near.bounds) else None
        return [(near, None)] + ([(far, near.bounds)] if far is not None else [])

    def colour(self, species_id):
        """The colour a species is seen in from far off: that of its own picture from above."""
        colour = self._colours.get(species_id)
        if colour is None:
            simulation = self.flora.simulation
            profile = simulation.ecology.profiles[species_id]
            if simulation.ecology.keeps_individuals(profile):
                colour = np.asarray(plant_colour(getattr(simulation, "plant_pictures", None), species_id, profile),
                                    dtype=np.float64)[:3]
            else:
                # A sward or a crust has no plants to look at from above: it is the colour its tufts are drawn in.
                colour = TUFT_SHADE * np.asarray(profile.color, dtype=np.float64)[:3]
            self._colours[species_id] = colour
        return colour

    # ------------------------------------------------------------------
    def groups(self, window, px_per_m=None, budget=PLANT_BUDGET, within_ms=None):
        """The plants a view shows of the surroundings, species by species.

        ``window`` is the ground in view as ``(u0, u1, v0, v1)`` in ``x - y``
        and ``x + y``, as ``VegetationSampler.sample`` takes it; ``px_per_m``
        the scale it is seen at.  Each group is one species' plants in it:
        ``species_id``, ``growth_form`` (``graminoid`` or ``lichen`` for the
        tufts of a sward or a crust) and, plant by plant, ``x``, ``y``,
        ``variant`` (which kept individual), ``stage`` (its share of full
        size, as kept) and ``size`` (how it differs from that).

        The plants are the planet's: where and what they are does not
        depend on the view.  A view shows all of them from the trees down;
        of a species it cannot show whole it shows a share (a half, a
        quarter, ...: the same plants whenever it is the same share), and
        leaves that and what would be too small to see to the ground
        (``shown``, ``ground``).

        Setting out the plants of a wide view takes some tenths of a
        second.  With ``within_ms`` a call works only about that long and
        gives the plants of the last view it finished until this one's are
        all set out: asked every frame, it never holds one up.
        """
        simulation = self.flora.simulation
        near = self.flora.vegetation()
        key = (tuple(window), None if px_per_m is None else round(float(px_per_m), 6),
               tuple(sorted(simulation.ecology.bounds.items())), id(near), int(budget))
        if key == self._plants_key:
            return self._groups
        work = self._work
        if work is None or work["key"] != key:
            work = self._work = self._begin(key, window, px_per_m, budget)
        started = time.perf_counter()
        while work["left"]:
            vegetation, taken, species_id, strip = work["left"].pop()

            def here(x, y, vegetation=vegetation, taken=taken, strip=strip):
                # A reading sets out the plants of every cell its ground touches: those beyond it are
                # another's, and those beyond the strip another strip's.
                return work["in_view"](x, y, taken) & _inside(vegetation.bounds, x, y) & (y >= strip[1]) & (y < strip[3])

            x, y, grown, mark = vegetation.individuals(species_id, work["spacing"][species_id], seed=self.flora.seed,
                                                       window=strip, shown=work["shown"][species_id], within=here)
            keep = np.ones(len(x), dtype=bool)
            if vegetation.ground is not simulation.substrate and keep.any():
                # The ground has been read more closely since: nothing stands in water it now shows.
                water = np.asarray(simulation.substrate.open_water_array(x, y), dtype=bool)
                keep &= water if species_id in vegetation.aquatic else ~water
            if keep.any():
                work["groups"].append(self._group(species_id, x[keep], y[keep], grown[keep], mark[keep]))
            if within_ms is not None and (time.perf_counter() - started) * 1000.0 >= within_ms:
                break
        if work["left"]:
            return self._groups
        self._work = None
        if work["shown"] != self.shown or work["as_plants"] != self.as_plants:
            self.shown, self.as_plants = work["shown"], frozenset(work["as_plants"])
            self.revision += 1
        self._plants_key, self._groups, self._plants = key, work["groups"], None
        self.plants_revision += 1
        return self._groups

    def plants(self, window, px_per_m=None, budget=PLANT_BUDGET, within_ms=None):
        """``groups`` plant by plant, each a display plant as a population's own are (``VegetationSampler``)."""
        groups = self.groups(window, px_per_m, budget, within_ms)
        if self._plants is None:
            self._plants = [
                {"species_id": group["species_id"], "x": x, "y": y, "growth_form": group["growth_form"], "abundance": 0.8,
                 "age_bucket": 0, "variant": variant, "individual_uid": None, "display_maturity": stage,
                 "visual_scale": size, "display_only": True, "surroundings": True}
                for group in groups for x, y, variant, stage, size in zip(
                    group["x"].tolist(), group["y"].tolist(), group["variant"].tolist(), group["stage"].tolist(),
                    group["size"].tolist())]
        return self._plants

    def _begin(self, key, window, px_per_m, budget):
        """What setting out a view's plants takes: the share of each species to show, and the species still to do."""
        simulation = self.flora.simulation
        ecology = simulation.ecology
        domain, frame = ecology.bounds, simulation.terrain_frame
        u0, u1, v0, v1 = window
        box = (max(frame["min_x"], (u0 + v0) / 2.0), max(frame["min_y"], (v0 - u1) / 2.0),
               min(frame["max_x"], (u1 + v1) / 2.0), min(frame["max_y"], (v1 - u0) / 2.0))

        def in_view(x, y, taken):
            seen = (x - y >= u0) & (x - y <= u1) & (x + y >= v0) & (x + y <= v1) & ~_inside(domain, x, y)
            return seen if taken is None else seen & ~_inside(taken, x, y)

        work = {"key": key, "box": box, "in_view": in_view, "spacing": {}, "shown": {}, "left": [], "groups": [],
                "as_plants": set()}
        if box[2] <= box[0] or box[3] <= box[1]:
            return work
        area = (box[2] - box[0]) * (box[3] - box[1])
        beyond = lambda held: not (held["min_x"] <= box[0] and held["min_y"] <= box[1]  # noqa: E731
                                   and held["max_x"] >= box[2] and held["max_y"] >= box[3])
        readings = self._readings(beyond)
        # About how many plants of each species the view holds, from the cover of the cells in it; and which
        # readings have any of it near the view at all.
        spacing, expected, shown, present, height = work["spacing"], {}, work["shown"], set(), {}
        for vegetation, taken in readings:
            cells = in_view(vegetation.x, vegetation.y, taken)
            cell = math.sqrt(vegetation.cell_area_m2)
            about = _inside({"min_x": box[0] - cell, "min_y": box[1] - cell, "max_x": box[2] + cell, "max_y": box[3] + cell},
                            vegetation.x, vegetation.y)
            for species_id, cover in vegetation.cover.items():
                if not cover[about].any():
                    continue  # none of it near: how much room a plant of it takes need not be found out
                present.add((id(vegetation), species_id))
                profile = ecology.profiles[species_id]
                if species_id in spacing:
                    pass
                elif ecology.keeps_individuals(profile):
                    spacing[species_id], height[species_id] = ecology.spacing_m(profile), profile.mature_height_m
                else:
                    # A sward or a crust is cover: its plants stand where a display sets them, as thick as it is.
                    spacing[species_id] = VegetationSampler.SPACING_M.get(profile.growth_form, 0.28)
                    height[species_id] = TUFT_HEIGHT_M if profile.growth_form == "lichen" else profile.mature_height_m
                expected[species_id] = expected.get(species_id, 0.0) + (
                    float(cover[cells].sum()) * vegetation.cell_area_m2 / spacing[species_id] ** 2)
        # The budget goes to the trees first, then layer by layer down: a wood is seen as its trees.  Within a
        # layer it is shared out from the fewest up: what a species does not need is left to those with more.
        layer_of = {species_id: vegetation.layers.get(species_id) for vegetation, _taken in readings for species_id in vegetation.cover}
        remaining = float(budget)
        for layer in [name for name, _least in LAYERS] + [CLIMBER_LAYER]:
            members = sorted((species_id for species_id in expected if layer_of[species_id] == layer),
                             key=lambda item: (expected[item], item))
            left = len(members)
            for species_id in members:
                quota, left = max(0.0, remaining) / left, left - 1
                count = expected[species_id]
                share = 1.0 if count <= quota else (2.0 ** math.floor(math.log2(quota / count)) if quota > 0.0 else 0.0)
                if self.grows_in_patches(species_id):
                    form = ecology.profiles[species_id].growth_form
                    if (form not in ("aquatic", "lichen") and share >= 0.5 and px_per_m is not None
                            and height[species_id] * px_per_m >= SWARD_PLANTS_FROM_PX):
                        work["as_plants"].add(species_id)  # close in, a sward is its plants
                    else:
                        # The patch is its ground; a few of its plants stand on it.  None of a plant that floats: seen
                        # from the side a lily pad is a stroke on the water, and thousands of them are stripes.
                        share = 0.0 if form == "aquatic" else min(share, PATCH_PLANT_SHARE)
                too_small = px_per_m is not None and height[species_id] * px_per_m < LEAST_PLANT_PX
                if too_small or area / spacing[species_id] ** 2 > MAX_PLACES or share * count < 0.5:
                    share = 0.0 if count >= 0.5 else 1.0  # none to show is all of none shown
                shown[species_id] = share
                remaining -= share * count
        for vegetation, taken in readings:
            for species_id in vegetation.cover:
                if not shown.get(species_id) or (id(vegetation), species_id) not in present:
                    continue
                strips = max(1, math.ceil(area / spacing[species_id] ** 2 / PLACES_A_STEP))
                edges = np.linspace(box[1], box[3], strips + 1).tolist()
                if taken is not None:
                    edges = sorted(set(edges) | {edge for edge in (taken["min_y"], taken["max_y"]) if box[1] < edge < box[3]})
                for low, high in zip(edges[:-1], edges[1:]):
                    # A strip that lies in the ground a closer reading has taken is looked at only beside that.
                    beside = taken is not None and taken["min_y"] <= low and high <= taken["max_y"]
                    spans = ([(box[0], min(box[2], taken["min_x"])), (max(box[0], taken["max_x"]), box[2])] if beside
                             else [(box[0], box[2])])
                    far_edge = math.inf if high == edges[-1] else high  # the last strip has the far edge too
                    work["left"].extend((vegetation, taken, species_id, (first, low, last, far_edge))
                                        for first, last in spans if last > first)
        return work

    def _group(self, species_id, x, y, grown, mark):
        ecology = self.flora.simulation.ecology
        profile, domain = ecology.profiles[species_id], ecology.bounds
        # A grass is its own picture, in a sward too; only a crust, which has no body, is drawn as flecks.
        form = "structural_graminoid" if profile.growth_form == "graminoid" else profile.growth_form
        # How far outside the living area each stands, along the further of the two axes.
        away = np.maximum(np.maximum(domain["min_x"] - x, x - domain["max_x"]), np.maximum(domain["min_y"] - y, y - domain["max_y"]))
        close = away <= EXACT_WITHIN_M

        def nearest(stages):
            stages = np.asarray(stages)
            return stages[np.abs(grown[:, None] - stages[None, :]).argmin(axis=1)]

        stage = np.where(close, nearest(STAGES), nearest(FAR_STAGES))
        variant = kept_individual(mark)
        variant = np.where(close, variant, variant % MAP_VARIANTS)
        # Between two kept stages a plant grows on in size; plants of one stage differ a little.
        size = (0.9 + 0.1 * plant_number(mark, 2)) * np.where(close, np.clip(grown / stage, 0.8, 1.2), np.clip(grown / stage, 0.7, 1.3))
        step = np.where(close, SIZE_STEP, FAR_SIZE_STEP)
        # Half of those further off are shown mirrored: two individuals and their mirror images, and trees
        # that lean lean both ways.  Not the close ones, which are shown as the residents they become.
        return {"species_id": species_id, "growth_form": form, "x": x, "y": y, "variant": variant, "stage": stage,
                "size": np.round(np.round(size / step) * step, 3), "mirrored": ~close & (plant_number(mark, 3) < 0.5)}

    # ------------------------------------------------------------------
    def _lattice(self, vegetation, shown, patches_too=False):
        """A reading's cover not drawn as plants, by cell: colour and share on land, the same in water, the soil built."""
        weights = (patches_too,) + tuple(sorted(shown.items()))
        kept = self._lattices.get((id(vegetation), weights))
        if kept is not None:
            return kept[1]
        # Nine values to a cell: colour times share and share, on land and in water, and the share of full soil.
        lattice = np.zeros(vegetation.x.shape + (9,), dtype=np.float32)
        built = np.zeros(vegetation.x.shape)
        for species_id, cover in vegetation.cover.items():
            aquatic = species_id in vegetation.aquatic
            if not aquatic:
                built += cover
            if vegetation.layers.get(species_id) == CLIMBER_LAYER:
                continue  # it stands in the crowns of what carries it
            weight = 1.0 - shown.get(species_id, 0.0)
            if weight <= 0.0 or (not patches_too and self.grows_in_patches(species_id)):
                continue
            first = 4 if aquatic else 0
            lattice[..., first:first + 3] += (weight * cover)[..., None] * self.colour(species_id)
            lattice[..., first + 3] += weight * cover
        lattice[..., 8] = np.clip(built / FULL_SOIL_COVER, 0.0, 1.0)
        if len(self._lattices) >= LATTICES_KEPT:
            self._lattices.pop(next(iter(self._lattices)))
        self._lattices[(id(vegetation), weights)] = (vegetation, lattice)
        return lattice

    def patch_cover(self, x, y):
        """The cover at points of every species that grows in patches (``grows_in_patches``), by species.

        Whoever draws the ground draws these as ground: the whole of each,
        whatever share of its plants stands on it as plants; but not a sward
        the last view drew as its plants (``as_plants``).
        """
        simulation = self.flora.simulation
        x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
        found = {}
        on_map = _inside(simulation.terrain_frame, x, y) & ~_inside(simulation.ecology.bounds, x, y)
        if not on_map.any():
            return found
        water = np.asarray(simulation.substrate.open_water_array(x, y), dtype=bool)
        beyond = lambda held: bool((on_map & ~_inside(held, x, y)).any())  # noqa: E731
        for vegetation, taken in self._readings(beyond):
            here = on_map & _inside(vegetation.bounds, x, y)
            if taken is not None:
                here &= ~_inside(taken, x, y)
            kept = self._patch_lattices.get(id(vegetation))
            if kept is None:
                species = [species_id for species_id in vegetation.cover if self.grows_in_patches(species_id)]
                lattice = (np.stack([vegetation.cover[species_id] for species_id in species], axis=-1).astype(np.float32)
                           if species else None)
                if len(self._patch_lattices) >= LATTICES_KEPT:
                    self._patch_lattices.pop(next(iter(self._patch_lattices)))
                self._patch_lattices[id(vegetation)] = kept = (vegetation, species, lattice)
            _vegetation, species, lattice = kept
            if not species or not here.any():
                continue
            values = _between_cells(vegetation, lattice, x[here], y[here])
            in_water = water[here]
            for number, species_id in enumerate(species):
                if species_id in self.as_plants:
                    continue  # drawn as its plants in this view
                cover = np.where(in_water == (species_id in vegetation.aquatic), values[:, number], 0.0)
                found.setdefault(species_id, np.zeros(x.shape, dtype=np.float32))[here] = cover
        return found

    def ground(self, x, y, shown=None, patches_too=False):
        """What lies on the ground at points: ``(colour, cover, soil organic matter in kg/m2)``.

        The colour and share of the cover a view does not draw as plants
        (``groups`` first, then this), and the soil under what grows there.
        Nothing in the living area, whose ground is its own, and nothing off
        the map.  ``shown`` gives other shares than those of the view last
        set out (none: all the cover, for ground whose plants are not drawn).
        What grows in patches is left out (``patch_cover`` tells it) unless
        ``patches_too``.
        """
        shown = self.shown if shown is None else shown
        simulation = self.flora.simulation
        x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
        colour = np.zeros(x.shape + (3,), dtype=np.float32)
        cover, organic = np.zeros(x.shape, dtype=np.float32), np.zeros(x.shape, dtype=np.float32)
        on_map = _inside(simulation.terrain_frame, x, y) & ~_inside(simulation.ecology.bounds, x, y)
        if not on_map.any():
            return colour, cover, organic
        water = np.asarray(simulation.substrate.open_water_array(x, y), dtype=bool)
        beyond = lambda held: bool((on_map & ~_inside(held, x, y)).any())  # noqa: E731
        for vegetation, taken in self._readings(beyond):
            here = on_map & _inside(vegetation.bounds, x, y)
            if taken is not None:
                here &= ~_inside(taken, x, y)
            if not here.any():
                continue
            values = _between_cells(vegetation, self._lattice(vegetation, shown, patches_too), x[here], y[here])
            in_water = water[here][:, None]
            mixed = np.where(in_water, values[:, 4:8], values[:, 0:4])
            colour[here] = mixed[:, :3] / np.maximum(mixed[:, 3:], 1e-9)
            cover[here] = np.clip(mixed[:, 3], 0.0, 1.0)
            organic[here] = np.where(in_water[:, 0], 0.0, values[:, 8]) * RESIDENT_ORGANIC_MATTER_KG_M2
        return colour, cover, organic
