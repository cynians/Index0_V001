"""What a view shows of the populations, within a bounded number of plants.

A crust or a sward is cover: display plants are sampled from it and are never
an input to the ecology.  A stand kept as individuals is shown as the plants
it is; only where there are more in view than the budget allows are some left
out.
"""
from __future__ import annotations

from contextlib import nullcontext
import hashlib
import math

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships with the app
    np = None


def _canopy_light(xs, ys, height_m, canopies):
    """``forest_ecology.light_at`` for arrays of points."""
    light = np.ones(len(xs), dtype=np.float64)
    for canopy in canopies:
        top = canopy["height_m"]
        if top <= height_m:
            continue
        distance = np.hypot(xs - canopy["x"], ys - canopy["y"])
        overlap = np.maximum(0.0, 1.0 - (distance / (canopy["radius_m"] * 1.25)) ** 2)
        vertical = min(1.0, (top - height_m) / (top * 0.35))
        light *= 1.0 - overlap * vertical * canopy["opacity"]
    return np.clip(light, 0.02, 1.0)


def population_abundances(ecology, species_id, xs, ys):
    """``ecology.abundance_at`` for many points of ground already known to be habitable.

    The scalar version asks for the canopy light plant by plant; at site
    scale that was half a second for one picture of the vegetation.
    """
    xs = np.asarray(xs, dtype=np.float64)
    ys = np.asarray(ys, dtype=np.float64)
    profile = ecology.profiles[species_id]
    shaded = bool(ecology.canopy_light_enabled) and profile.light_minimum > 0.0

    def response(light):
        return np.clip((light / profile.light_minimum - 0.65) / 0.35, 0.0, 1.0)

    incident = None
    if shaded:
        sample_array = getattr(ecology.substrate, "sample_array", None)
        if callable(sample_array):
            incident = np.asarray(sample_array("surface_solar_exposure", xs, ys, 1.0), dtype=np.float64)
        else:
            incident = np.asarray([ecology._incident_light_at(x, y) for x, y in zip(xs.tolist(), ys.tolist())])
    recruitment = None
    total = np.zeros(len(xs), dtype=np.float64)
    for patch in ecology.species_patches(species_id):
        distance = np.hypot(xs - patch.x, ys - patch.y)
        inside = distance <= patch.radius_m
        if not inside.any():
            continue
        factor = 1.0
        if shaded and patch.development_days < (getattr(profile, "establishment_days", None) or profile.maturity_days):
            if recruitment is None:
                recruitment = response(incident * _canopy_light(xs, ys, 0.05, ecology.canopy_footprints()))
            factor = recruitment[inside]
        elif shaded and patch.establishment_canopies is not None:
            # Maturing a seedbed must not create adults in previously shaded holes.
            factor = response(incident[inside] * _canopy_light(xs[inside], ys[inside], 0.05, patch.establishment_canopies))
        total[inside] += patch.abundance * factor * np.sqrt(np.maximum(0.0, 1.0 - distance[inside] / patch.radius_m))
    return np.clip(total, 0.0, 1.0)


class VegetationSampler:
    MAX_CANDIDATES = 12000
    MAX_INSTANCES = 2400
    # A sward seen close enough to be its tufts (``surroundings.SWARD_PLANTS_FROM_PX``) has no patch under it:
    # it is given room for every tuft of a close view of the living area.
    MAX_SWARD_CANDIDATES = 12000
    MAX_SWARD_INSTANCES = 6000
    # Display spacing defaults, not measured planting densities.
    SPACING_M = {"tree": 0.46, "shrub": 0.42, "graminoid": 0.20,
                 "forb": 0.28, "fern": 0.36, "aquatic": 0.40,
                 "succulent": 0.42, "lichen": 0.18}

    # In a true-to-scale view a plant needs room for its own crown: spacing is
    # at least this share of the species' mature height.
    CROWN_SPACING = {"tree": 0.28, "shrub": 0.40, "subshrub": 0.40, "succulent": 0.40, "fern": 0.30}

    def __init__(self):
        self._key = None
        self._instances = []

    @staticmethod
    def display_growth(species_id, x, y, patches, maturity_days, individual_byte):
        """Artistic age mix bounded by the local cohort; never an ecology input."""
        containing = [p for p in patches if math.hypot(x-p.x, y-p.y) <= p.radius_m]
        patch = max(containing, key=lambda p: (p.abundance * math.sqrt(max(0, 1-math.hypot(x-p.x, y-p.y)/p.radius_m)), p.patch_id))
        cohort = max(0.0, min(1.0, patch.development_days / maturity_days))
        edge = math.hypot(x-patch.x, y-patch.y) / patch.radius_m
        cluster = hashlib.sha256(f"{species_id}:growth:{math.floor(x/1.4)}:{math.floor(y/1.4)}".encode()).digest()[0]
        mixture = .25 + .75 * (.65 * cluster/255 + .35 * individual_byte/255) - .20 * edge
        index = max(0, min(6, int(mixture*7)))
        return round(cohort * (.06, .16, .30, .48, .68, .85, 1.0)[index], 4)

    def spacing_m(self, profile, true_scale):
        """Room between two display plants of a species, before it is widened to fit the budget."""
        spacing = self.SPACING_M.get(profile.growth_form, 0.28)
        if true_scale:
            spacing = max(spacing, profile.mature_height_m * self.CROWN_SPACING.get(profile.growth_form, 0.0))
        return spacing

    def sample(self, ecology, representatives, true_scale=False, window=None):
        """Display plants for the populations.

        ``window`` limits the work to the ground a view can show, given as
        ``(u0, u1, v0, v1)`` in ``x - y`` and ``x + y`` (the axes of an
        isometric screen).  The budget then goes to what is looked at: a close
        view of one stand on a site of fifty is drawn as densely as that stand
        alone would be.
        """
        key = (bool(true_scale), window, tuple(sorted(ecology.bounds.items())),
               getattr(ecology.substrate, "fingerprint", None),
               tuple((p.patch_id, p.species_id, p.x, p.y, p.radius_m, p.abundance)
                     for p in ecology.patches),
               ecology.canopy_light_enabled,
               tuple((p.development_days, None if p.establishment_canopies is None else
                      tuple(tuple(sorted(c.items())) for c in p.establishment_canopies)) for p in ecology.patches),
               tuple((sid, p.growth_form, p.light_minimum, p.mature_height_m, p.maturity_days, p.crown_openness)
                     for sid, p in sorted(ecology.profiles.items())),
               tuple((r.get("representative_id"), r["species_id"], r["x"], r["y"],
                      r.get("age_bucket"), r.get("variant")) for r in representatives),
               getattr(getattr(ecology, "individuals", None), "revision", None), getattr(ecology, "season", None))
        if key == self._key:
            return list(self._instances)
        # One canopy picture for the whole sampling: asked plant by plant, the
        # ecology would rebuild it from every patch each time.
        with getattr(ecology, "canopies_held", nullcontext)():
            instances = self._sample(ecology, representatives, true_scale, window)
        self._key, self._instances = key, instances
        return list(instances)

    @staticmethod
    def _recorded(ecology, species_id, window, quota):
        """The recorded plants of a species in view, each as the kept individual and stage it is.

        Plants simulated in depth are left to their own pictures.  More plants
        than the budget are thinned by a rule that keeps the same ones while
        the view pans; with budget to spare, a record that stands for several
        plants has them put back around it.
        """
        from simulations.biosphere.plant_pictures import stage_of

        plants = ecology.species_individuals(species_id)
        x, y, uid = plants["x"], plants["y"], plants["uid"].astype(np.int64)
        if not len(x):
            return []
        shown = ~np.isin(uid, list(ecology.individuals.simulated)) if ecology.individuals.simulated else np.ones(len(x), dtype=bool)
        if window is not None:
            u0, u1, v0, v1 = window
            shown &= (x - y >= u0) & (x - y <= u1) & (x + y >= v0) & (x + y <= v1)
        index = np.flatnonzero(shown)
        if not len(index):
            return []
        # A fixed number per plant, so that thinning does not flicker.
        rank = (uid[index] * 2654435761) % 4294967296
        if len(index) > quota:
            index = index[rank < 4294967296.0 * quota / len(index)]
        profile = ecology.profiles[species_id]
        form = "structural_graminoid" if profile.growth_form == "graminoid" else profile.growth_form
        cell = ecology.spacing_m(profile)
        room = quota - len(index)
        instances = []
        for i in index.tolist():
            share = float(plants["share"][i])
            stage = stage_of(share)
            mark = int(uid[i])
            plant = {
                "species_id": species_id, "x": float(x[i]), "y": float(y[i]), "growth_form": form,
                "abundance": 0.8, "age_bucket": 0, "variant": int(plants["variant"][i]),
                "individual_uid": mark, "display_maturity": stage,
                # Between two kept stages a plant grows on in size; plants of one stage differ a little.
                "visual_scale": round((0.9 + 0.1 * ((mark * 40503) % 97) / 96.0) * max(0.8, min(1.2, share / stage)), 3),
                "display_only": True,
            }
            instances.append(plant)
            # The neighbours a record stands for, set around it where there is budget to show them.
            for extra in range(1, min(int(round(float(plants["count"][i]))), room + 1)):
                digest = hashlib.sha256(f"{mark}:{extra}".encode()).digest()
                reach = cell * math.sqrt(float(plants["count"][i])) * 0.5
                instances.append(dict(
                    plant, x=plant["x"] + (digest[0] / 127.5 - 1.0) * reach, y=plant["y"] + (digest[1] / 127.5 - 1.0) * reach,
                    individual_uid=None))
                room -= 1
        return instances

    def _sample(self, ecology, representatives, true_scale, window):
        sources = {}
        for rep in representatives:
            sources.setdefault(rep["species_id"], []).append(rep)
        active = sorted({p.species_id for p in ecology.patches if p.abundance > 0.006})
        instances = []
        if window is not None:
            u0, u1, v0, v1 = window
            window_area = max(0.0, (u1 - u0) * (v1 - v0) / 2.0)
            window_box = ((u0 + v0) / 2.0, (u1 + v1) / 2.0, (v0 - u1) / 2.0, (v1 - u0) / 2.0)
        keeps_individuals = getattr(ecology, "keeps_individuals", None)
        for species_id in active:
            if callable(keeps_individuals) and keeps_individuals(ecology.profiles[species_id]):
                instances.extend(self._recorded(ecology, species_id, window, self.MAX_INSTANCES // max(1, len(active))))
                continue
            patches = ecology.species_patches(species_id)
            form = ecology.profiles[species_id].growth_form
            spacing = self.spacing_m(ecology.profiles[species_id], true_scale)
            # Power-of-two thinning keeps work bounded for expanding domains.
            area = sum((2 * p.radius_m + spacing * 2) ** 2 for p in patches)
            if window is not None:
                # Whichever is smaller: all the species' ground, or all the
                # view can show.  Neither changes while the view pans.
                area = min(area, window_area)
            sward = true_scale and form == "graminoid"
            candidate_budget = self.MAX_SWARD_CANDIDATES if sward else max(1, self.MAX_CANDIDATES // len(active))
            while area / spacing ** 2 > candidate_budget:
                spacing *= 2
            sites = set()
            bounds = ecology.bounds
            for patch in patches:
                low_x, high_x = max(bounds["min_x"], patch.x - patch.radius_m), min(bounds["max_x"], patch.x + patch.radius_m)
                low_y, high_y = max(bounds["min_y"], patch.y - patch.radius_m), min(bounds["max_y"], patch.y + patch.radius_m)
                if window is None:
                    ix0, ix1 = math.floor(low_x / spacing), math.floor(high_x / spacing)
                    iy0, iy1 = math.floor(low_y / spacing), math.floor(high_y / spacing)
                    sites.update((ix, iy) for ix in range(ix0, ix1 + 1) for iy in range(iy0, iy1 + 1))
                    continue
                low_x, high_x = max(low_x, window_box[0]), min(high_x, window_box[1])
                low_y, high_y = max(low_y, window_box[2]), min(high_y, window_box[3])
                if low_x > high_x or low_y > high_y:
                    continue
                ix0, ix1 = math.floor(low_x / spacing), math.floor(high_x / spacing)
                iy0, iy1 = math.floor(low_y / spacing), math.floor(high_y / spacing)
                # The view is a diamond in the lattice; its corners are not looked at.
                low_u, high_u = math.floor(u0 / spacing) - 1, math.ceil(u1 / spacing) + 1
                low_v, high_v = math.floor(v0 / spacing) - 1, math.ceil(v1 / spacing) + 1
                for ix in range(ix0, ix1 + 1):
                    first = max(iy0, ix - high_u, low_v - ix)
                    last = min(iy1, ix - low_u, high_v - ix)
                    sites.update((ix, iy) for iy in range(first, last + 1))
            candidates = []
            located = []
            for ix, iy in sorted(sites):
                digest = hashlib.sha256(f"{species_id}:{spacing}:{ix}:{iy}".encode()).digest()
                x = (ix + 0.15 + digest[0] / 255 * 0.70) * spacing
                y = (iy + 0.15 + digest[1] / 255 * 0.70) * spacing
                if ecology.contains(x, y):
                    located.append((digest, x, y))
            # Terrestrial plants are not drawn on open water.  A substrate that
            # samples arrays answers that for every candidate at once.
            water_array = getattr(ecology.substrate, "open_water_array", None)
            
            habitat_checked = callable(water_array) and form != "aquatic" and getattr(ecology.substrate, "native", None) is None
            if habitat_checked and located:
                wet = water_array([item[1] for item in located], [item[2] for item in located])
                located = [item for item, is_wet in zip(located, wet.tolist()) if not is_wet]
            # The real ecology answers for all candidates at once; a stand-in is asked plant by plant.
            together = (np is not None and habitat_checked and located
                        and callable(getattr(ecology, "canopy_footprints", None)) and hasattr(ecology, "species_patches"))
            abundances = population_abundances(
                ecology, species_id, [item[1] for item in located], [item[2] for item in located],
            ).tolist() if together else None
            for index, (digest, x, y) in enumerate(located):
                abundance = abundances[index] if abundances is not None else ecology.abundance_at(
                    species_id, x, y, habitat_checked=habitat_checked)
                # Stable thresholds: densifying a patch adds plants, not flicker.
                if abundance <= 0.006 or digest[2] / 255 >= abundance:
                    continue
                prototypes = sources.get(species_id, [])
                if any(math.hypot(x - r["x"], y - r["y"]) < spacing * 0.42 for r in prototypes):
                    continue
                source = prototypes[digest[3] % len(prototypes)] if prototypes else {}
                candidates.append((int.from_bytes(digest[4:8], "big"), {
                    "species_id": species_id, "x": x, "y": y,
                    "growth_form": form, "abundance": abundance,
                    "age_bucket": source.get("age_bucket", 0),
                    "variant": source.get("variant", digest[3] % 3),
                    "visual_source_id": source.get("representative_id"),
                    "display_maturity": self.display_growth(species_id, x, y, patches,
                                                             ecology.profiles[species_id].maturity_days, digest[9]),
                    "visual_scale": (0.72, 0.84, 0.96)[digest[8] % 3],
                    "display_only": True,
                }))
            # Spatially unbiased subset instead of truncating one map edge.
            quota = self.MAX_SWARD_INSTANCES if sward else self.MAX_INSTANCES // max(1, len(active))
            instances.extend(item for _, item in sorted(candidates, key=lambda pair: pair[0])[:quota])
        return instances
