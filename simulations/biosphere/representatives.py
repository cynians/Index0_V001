"""Persistent deep-simulation representatives for continuous populations."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
import hashlib
import math
import time

import numpy as np

from simulations.biosphere.ecology import moisture_response, thermal_response
from simulations.species.plant_life_timing import resolve_plant_life_timing
from simulations.species.species_simulation import SpeciesSimulation


def _clamp(value):
    return max(0.0, min(1.0, float(value)))


class RepresentativeBody(SpeciesSimulation):
    """A Species Sim body that lives in real time.

    Its shape is grown on Species Sim's developmental clock (``set_age`` takes
    developmental days).  Its life phase, seasons and senescence are read
    against the organism's real age and the species' real maturity and
    lifespan, by the same rules Species Sim applies to its own clock.
    """

    life_timing = None
    real_age_days = None
    _reading_real_life = False

    def generate_snapshot(self, age_days, lod, *args, **kwargs):
        if "render_snapshot" not in self.__dict__:
            # Species Sim opens on a half-grown plant in full detail.  An
            # organism is grown to its own age straight after it is made:
            # a seedling is all it needs until then.
            age_days, lod = 1.0, 1
        return super().generate_snapshot(age_days, lod, *args, **kwargs)

    def life_state(self, age_days=None):
        timing = self.life_timing
        if timing is None or not timing.real_clock or self.real_age_days is None:
            return super().life_state(age_days)
        self._reading_real_life = True
        try:
            return super().life_state(self.real_age_days)
        finally:
            self._reading_real_life = False

    @property
    def mature_age_days(self):
        if self._reading_real_life:
            return self.life_timing.seed_days  # the adult phase begins with seed, before full size
        return SpeciesSimulation.mature_age_days.fget(self)

    @property
    def life_history_profile(self):
        profile = SpeciesSimulation.life_history_profile.fget(self)
        if self._reading_real_life:
            return self.life_timing.life_history_profile(profile)
        return profile


@dataclass
class RepresentativeOrganism:
    representative_id: str
    species_id: str
    x: float
    y: float
    seed: int
    age_days: float = 1.0
    health: float = 0.72
    alive: bool = True
    seasons_lived: int = 0
    reproduction_index: float = 0.0
    last_outcome: dict = field(default_factory=dict)
    simulation: SpeciesSimulation | None = field(default=None, repr=False)
    # The real age at which the body was last grown and the life stage it
    # shows, and why the organism ended.
    body_age_days: float = 1.0
    body_stage: tuple = ()
    death_cause: str = ""
    # The recorded plant this organism is, for a species kept as individuals.
    individual_uid: int | None = None
    # Whether it has come of age and been taken into the planet's kept pictures.
    in_pictures: bool = False


class RepresentativePopulationManager:
    """Maintain the few organisms of each population that are simulated in depth.

    A crust or a sward has three or four, set down where it is densest.  In a
    species kept as individuals they are some of its recorded plants: a few to
    a stand, spread out, each steering the plants around it.  When one dies
    another plant is picked and followed from the age it has.
    """

    MAX_PER_SPECIES = 4
    # Plants followed in depth in a species kept as individuals.
    SIMULATED_PER_STAND = 3
    SIMULATED_MAX = 4
    # Growing the body of a plant picked at its age is the costly part: after
    # the first of a season, no more are picked once this long has gone into it.
    PICK_BUDGET_MS = 40.0
    # A seedling picked to be followed grows up as a plant of its own and
    # joins the planet's kept pictures; an older one keeps the look it had.
    OWN_SEED_BELOW_SHARE = 0.12
    DAYS_PER_SEASON = 91.3125
    # Regrowing an organism is the costly part of a season, so only some are
    # regrown each season and the others report from the body they last grew.
    # Every organism is regrown at least once in ``MAX_STALE_SEASONS``, and a
    # body in its first seasons every season: a seedling's picture must not
    # stand in for a tree that has since grown up.
    MAX_REGROWN_PER_SEASON = 3
    MAX_STALE_SEASONS = 4

    def __init__(self, world_model, pictures=None):
        self.world_model = world_model
        # The planet's kept plant pictures (``plant_pictures``), when there are any.
        self.pictures = pictures
        self.representatives = {}
        self._serials = {}
        self._picked, self._picking_since = 0, 0.0

    def _new_representative(self, species_id, x, y, seed=None, individual_uid=None, real_age_days=1.0):
        serial = self._serials.get(species_id, 0) + 1
        self._serials[species_id] = serial
        digest = hashlib.sha256(f"{species_id}:{x:.5f}:{y:.5f}:{serial}".encode("utf-8")).digest()
        representative_id = f"runtime_{species_id}_representative_{serial:02d}"
        entity = self.world_model.get_entity(species_id) or {"id": species_id, "type": "species"}
        simulation = RepresentativeBody(
            world_model=self.world_model,
            species_id=species_id,
            species_entity=entity,
            seed=int.from_bytes(digest[:2], "big") if seed is None else int(seed),
        )
        simulation.lod = 1
        simulation.life_timing = resolve_plant_life_timing(simulation.species_entity, simulation.blueprint.growth)
        representative = RepresentativeOrganism(
            representative_id=representative_id,
            species_id=species_id,
            x=x,
            y=y,
            seed=simulation.seed,
            simulation=simulation,
            individual_uid=individual_uid,
        )
        self.grow_body(representative, max(1.0, float(real_age_days)))
        self.representatives[representative_id] = representative
        return representative

    @staticmethod
    def life_timing(representative):
        return getattr(representative.simulation, "life_timing", None)

    def developmental_days(self, representative, real_age_days):
        """The developmental age Species Sim grows for an organism of this real age."""
        timing = self.life_timing(representative)
        days = timing.developmental_days(real_age_days) if timing is not None else float(real_age_days)
        return min(days, float(getattr(representative.simulation, "max_age_days", math.inf)))

    def grow_body(self, representative, real_age_days=None):
        """Grow the organism's body for its real age (or move it to ``real_age_days`` first)."""
        if real_age_days is not None:
            representative.age_days = max(0.0, float(real_age_days))
        simulation = representative.simulation
        simulation.real_age_days = representative.age_days
        simulation.set_age(self.developmental_days(representative, representative.age_days))
        representative.body_age_days = representative.age_days
        representative.body_stage = self.life_stage(simulation, representative.age_days)

    @staticmethod
    def life_stage(simulation, real_age_days):
        """The life stage a body shows at a real age: its phase and how far its decline has gone."""
        held = getattr(simulation, "real_age_days", None)
        simulation.real_age_days = real_age_days
        try:
            state = simulation.life_state()
        finally:
            simulation.real_age_days = held
        return state.get("phase"), round(float(state.get("senescence_factor", 0.0) or 0.0), 1)

    def set_maturity(self, representative, fraction):
        """Put an organism at a share of the way to mature size, in real time."""
        timing = self.life_timing(representative)
        maturity_days = timing.maturity_days if timing is not None else representative.simulation.mature_age_days
        self.grow_body(representative, maturity_days * max(0.0, float(fraction)))

    @staticmethod
    def condition(representative, environment):
        """Species Sim's ecological outcome for an organism, with its condition read apart from its size.

        Species Sim scales vitality by how much of its mature size a body has.
        A seedling is small, not sick: asked that way, a tree would count as
        failing for the decades it takes to grow up.  So the outcome is taken
        as for a full-grown body in the same state, and the real size is put
        back beside it.
        """
        stats = representative.simulation.render_snapshot.stats
        size = float(stats.get("maturity", 0.0) or 0.0)
        stats["maturity"] = 1.0
        try:
            outcome = dict(representative.simulation.get_ecological_outcome(environment))
        finally:
            stats["maturity"] = size
        outcome["maturity"] = round(size, 4)
        outcome["real_age_days"] = representative.age_days
        return outcome

    def lifespan_days(self, representative):
        """How long this individual lives: the species' lifespan, less for some than for others."""
        timing = self.life_timing(representative)
        if timing is None or not timing.real_clock:
            return math.inf  # a cycle that ends with reproduction ends itself
        return timing.lifespan_days * (0.75 + 0.25 * (representative.seed % 997) / 996.0)

    @staticmethod
    def has_seasons(simulation):
        """Whether the body looks different through the year (leaf fall, flowers, fruit)."""
        known = getattr(simulation, "_body_has_seasons", None)
        if known is None:
            from simulations.species.plant_reproduction import seasonal_reproductive_state

            known = seasonal_reproductive_state(simulation.blueprint.growth, 1.0, 1.0) is not None
            simulation._body_has_seasons = known
        return known

    def body_lag(self, representative):
        """How overdue a new body is: 1 when it should be regrown, 0 when it could not differ.

        A growing body is due when the organism has grown by as much as the
        body's own age, within a step of 2 to 10 % of full size, and at the
        latest when the organism is full-grown.  A full-grown body is due once
        a year if it has seasons to show, otherwise only when its life moves
        on to another stage.  A body at the oldest age Species Sim grows
        cannot change at all.
        """
        simulation = representative.simulation
        target_age = representative.age_days + self.DAYS_PER_SEASON
        body = float(simulation.render_snapshot.age_days)
        target = self.developmental_days(representative, target_age)
        stale = target - body
        if stale <= 1e-9:
            return 0.0
        timing = self.life_timing(representative)
        grown = timing.developmental_maturity_days if timing is not None else float(simulation.mature_age_days)
        if body < grown:
            if target >= grown:
                return 1.0 + stale / grown  # it should stand full-grown by now
            smallest = min(self.DAYS_PER_SEASON, grown * 0.02)
            largest = min(self.MAX_STALE_SEASONS * self.DAYS_PER_SEASON, max(smallest, grown * 0.10))
            return stale / max(smallest, min(largest, body))
        if self.has_seasons(simulation):
            waited = (target_age - representative.body_age_days) / self.DAYS_PER_SEASON
            return waited / self.MAX_STALE_SEASONS
        return 1.0 if self.life_stage(simulation, target_age) != representative.body_stage else 0.0

    @staticmethod
    def _spatial_sample(candidates, count):
        if not candidates or count <= 0:
            return []
        ordered = sorted(candidates, key=lambda item: (-item[0], item[2], item[1]))
        selected = [ordered[0]]
        while len(selected) < min(count, len(ordered)):
            remaining = [item for item in ordered if item not in selected]
            chosen = max(
                remaining,
                key=lambda item: (
                    min(math.hypot(item[1] - other[1], item[2] - other[2]) for other in selected),
                    item[0],
                ),
            )
            selected.append(chosen)
        return selected

    def sync_from_population(self, ecology):
        """Seed organisms directly into free-coordinate population patches."""
        self._picked, self._picking_since = 0, time.perf_counter()
        with getattr(ecology, "canopies_held", nullcontext)():
            self._sync_from_population(ecology)

    def _sync_individuals(self, ecology, species_id):
        """Keep a species' simulated plants standing: drop those whose plant is gone, pick new ones."""
        plants = ecology.species_individuals(species_id)
        standing = set(plants["uid"].tolist())
        alive = []
        for item in self.representatives.values():
            if item.species_id != species_id or not item.alive:
                continue
            if item.individual_uid in standing:
                alive.append(item)
            else:
                item.alive, item.death_cause = False, item.death_cause or "population gone"
                ecology.individuals.simulated.discard(item.individual_uid)
        stands = sum(1 for patch in ecology.species_patches(species_id)
                     if len(ecology.individuals.members(patch.patch_id) or ()))
        desired = min(len(standing), self.SIMULATED_MAX, self.SIMULATED_PER_STAND * stands)
        x, y, share = plants["x"], plants["y"], plants["share"]
        free = ~np.isin(plants["uid"], [item.individual_uid for item in alive])
        followed = [(item.x, item.y) for item in alive]
        while len(followed) < desired and free.any():
            if self._picked and (time.perf_counter() - self._picking_since) * 1000.0 > self.PICK_BUDGET_MS:
                break  # the rest are picked next season
            self._picked += 1
            if followed:
                # The plant furthest from every plant already followed; of two as far, the better grown.
                near = np.min([np.hypot(x - fx, y - fy) for fx, fy in followed], axis=0)
                score = near * (0.5 + share)
            else:
                # The first: the best grown, and of those the one in the middle of them all.
                score = share - np.hypot(x - x.mean(), y - y.mean()) * 1e-6
            pick = int(np.argmax(np.where(free, score, -np.inf)))
            free[pick] = False
            followed.append((float(x[pick]), float(y[pick])))
            seed = None
            if self.pictures is not None and share[pick] >= self.OWN_SEED_BELOW_SHARE:
                seed = self.pictures.seed(species_id, int(plants["variant"][pick]))
            representative = self._new_representative(
                species_id, float(x[pick]), float(y[pick]), seed=seed,
                individual_uid=int(plants["uid"][pick]), real_age_days=float(plants["grown_days"][pick]))
            representative.in_pictures = seed is not None
            ecology.follow_individual(representative.individual_uid)

    def _sync_from_population(self, ecology):
        keeps_individuals = getattr(ecology, "keeps_individuals", None)
        for species_id in ecology.profiles:
            patches = ecology.species_patches(species_id)
            if not patches:
                continue
            if callable(keeps_individuals) and keeps_individuals(ecology.profiles[species_id]):
                self._sync_individuals(ecology, species_id)
                continue
            alive = [item for item in self.representatives.values() if item.species_id == species_id and item.alive]
            desired = self.MAX_PER_SPECIES if max(patch.abundance for patch in patches) >= 0.075 else 3
            if len(alive) >= desired:
                continue
            minimum_spacing = max(0.10, max(patch.radius_m for patch in patches) * 0.10)
            candidates = [
                candidate for candidate in ecology.representative_sites(species_id, count=32)
                if all(math.hypot(candidate[1] - item.x, candidate[2] - item.y) >= minimum_spacing for item in alive)
            ]
            for _abundance, x, y in self._spatial_sample(candidates, desired - len(alive)):
                self._new_representative(species_id, x, y)

    def advance_season(self, ecology):
        self.sync_from_population(ecology)
        with getattr(ecology, "canopies_held", nullcontext)():
            return self._advance_season(ecology)

    def _advance_season(self, ecology):
        outcomes_by_species = {}
        alive_representatives = [item for item in self.representatives.values() if item.alive]

        lags = {item.representative_id: self.body_lag(item) for item in alive_representatives}
        due = [item for item in alive_representatives if lags[item.representative_id] >= 1.0 - 1e-9]
        quota = max(self.MAX_REGROWN_PER_SEASON, math.ceil(len(due) / self.MAX_STALE_SEASONS))
        regrown = {
            item.representative_id
            for item in sorted(due, key=lambda item: (-lags[item.representative_id], item.representative_id))[:quota]
        }
        for representative in alive_representatives:
            local_abundance = ecology.abundance_at(representative.species_id, representative.x, representative.y)
            if not representative.alive:
                continue  # its plant went with its stand
            if representative.individual_uid is None and local_abundance <= 0.003:
                representative.alive, representative.death_cause = False, "population gone"
                continue
            height = float(representative.simulation.render_snapshot.bounds_m[5] or 0.0)
            environment = ecology.environment_at(representative.x, representative.y, max(0.05, height * 0.35))
            profile = ecology.profiles[representative.species_id]
            total_abundance = ecology.total_abundance_at(representative.x, representative.y)
            local_scale = max((patch.radius_m for patch in ecology.species_patches(representative.species_id)), default=0.5)
            nearby_representatives = sum(
                item.alive
                and item.representative_id != representative.representative_id
                and math.hypot(item.x - representative.x, item.y - representative.y) <= max(0.6, local_scale * 1.5)
                for item in alive_representatives
            )
            water_stress = _clamp(1.0 - float(moisture_response(profile, ecology.wetness_for(profile, environment))))
            light_stress = _clamp((profile.light_minimum - environment["plant_available_light"]) / max(0.08, profile.light_minimum))
            thermal, _limiting = thermal_response(profile, environment)
            deep_environment = {
                "water_stress": water_stress,
                "light_stress": light_stress,
                "temperature_stress": 1.0 - thermal,
                "competition": _clamp(max(0.0, total_abundance - local_abundance) + nearby_representatives * 0.06),
                "disturbance": 0.0,
                "disease_pressure": _clamp(nearby_representatives * 0.025),
                "available_nitrogen_g_m2": environment.get("available_nitrogen_g_m2", 0.0),
                "available_phosphorus_g_m2": environment.get("available_phosphorus_g_m2", 0.0),
                "soil_depth_m": environment.get("soil_depth_m"),
                "soil_ph": environment.get("soil_ph"),
            }
            representative.age_days += self.DAYS_PER_SEASON
            representative.simulation.real_age_days = representative.age_days
            if representative.representative_id in regrown:
                self.grow_body(representative)
            outcome = self.condition(representative, deep_environment)
            dead = (outcome.get("life_history") or {}).get("phase") == "dead"
            vigour = float(outcome.get("vitality", 0.0) or 0.0)
            representative.last_outcome = outcome
            representative.seasons_lived += 1
            representative.reproduction_index += float(outcome.get("fecundity", 0.0) or 0.0)
            mortality = float(outcome.get("mortality_risk", 0.0) or 0.0)
            representative.health = _clamp(representative.health + (vigour - 0.42) * 0.18 - mortality * 0.035)
            if representative.age_days >= self.lifespan_days(representative):
                representative.alive, representative.death_cause = False, "old age"
            elif dead:
                representative.alive, representative.death_cause = False, "life cycle complete"
            elif representative.health <= 0.025:
                representative.alive, representative.death_cause = False, "poor condition"
            outcomes_by_species.setdefault(representative.species_id, []).append(outcome)
            if representative.individual_uid is not None:
                self._record_individual(ecology, representative, outcome)

        feedback = {}
        for species_id, outcomes in outcomes_by_species.items():
            count = max(1, len(outcomes))
            vitality = sum(float(item.get("vitality", 0.0) or 0.0) for item in outcomes) / count
            fecundity = sum(float(item.get("fecundity", 0.0) or 0.0) for item in outcomes) / count
            mortality = sum(float(item.get("mortality_risk", 0.0) or 0.0) for item in outcomes) / count
            nitrogen_response = sum(float(item.get("nitrogen_response", 0.0) or 0.0) for item in outcomes) / count
            phosphorus_response = sum(float(item.get("phosphorus_response", 0.0) or 0.0) for item in outcomes) / count
            root_depth = sum(float(item.get("root_depth_m", 0.0) or 0.0) for item in outcomes) / count
            root_spread = sum(float(item.get("root_system_span_m", 0.0) or 0.0) for item in outcomes) / count
            feedback[species_id] = {
                # Each simulated plant by itself, for the plants around it to take after.
                "simulated": [item["steers"] for item in outcomes if "steers" in item],
                "representative_count": count,
                "mean_vitality": vitality,
                "mean_fecundity": fecundity,
                "mean_mortality_risk": mortality,
                "growth_multiplier": 0.68 + vitality * 0.72,
                "dispersal_multiplier": 0.72 + fecundity * 0.72,
                "mortality_pressure": mortality * 0.018,
                "mean_nitrogen_response": nitrogen_response,
                "mean_phosphorus_response": phosphorus_response,
                "mean_nitrogen_stress": 1.0 - nitrogen_response,
                "mean_phosphorus_stress": 1.0 - phosphorus_response,
                "mean_root_depth_m": root_depth,
                "mean_root_spread_m": root_spread,
                "mean_root_exploration": _clamp((root_depth + root_spread) / 2.5),
            }
        return feedback

    def _record_individual(self, ecology, representative, outcome):
        """Carry a simulated plant's season over to its record, and to the plants that take after it."""
        uid = representative.individual_uid
        if not representative.alive:
            # A plant at the end of its life leaves a seedling; one that failed leaves a gap.
            ecology.release_individual(uid, renew=representative.death_cause != "poor condition")
            return
        variant = None
        timing = self.life_timing(representative)
        grown = timing.maturity_days if timing is not None else representative.simulation.mature_age_days
        if self.pictures is not None and not representative.in_pictures and representative.age_days >= grown:
            # Come of age on this planet: from now on plants of its species may look like it.
            variant = self.pictures.add_grown(representative.species_id, representative.seed, {
                "ground_light": ecology.ground_light_at(representative.x, representative.y)})
            representative.in_pictures = True
        ecology.follow_individual(uid, grown_days=representative.age_days, variant=variant)
        vitality = float(outcome.get("vitality", 0.0) or 0.0)
        mortality = float(outcome.get("mortality_risk", 0.0) or 0.0)
        outcome["steers"] = (representative.x, representative.y, 0.68 + vitality * 0.72, mortality * 0.018)

    def items(self, species_id=None, alive_only=False):
        values = list(self.representatives.values())
        if species_id is not None:
            values = [item for item in values if item.species_id == species_id]
        if alive_only:
            values = [item for item in values if item.alive]
        return sorted(values, key=lambda item: item.representative_id)

    def get(self, representative_id):
        return self.representatives.get(representative_id)

    def summary(self):
        values = self.items()
        return {
            "total": len(values),
            "alive": sum(item.alive for item in values),
            "dead": sum(not item.alive for item in values),
            "species": len({item.species_id for item in values if item.alive}),
        }
