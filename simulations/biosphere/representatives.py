"""Persistent deep-simulation representatives for continuous populations."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math

from simulations.species.species_simulation import SpeciesSimulation


def _clamp(value):
    return max(0.0, min(1.0, float(value)))


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


class RepresentativePopulationManager:
    """Maintain 3–4 costly organisms per established spatial population."""

    MAX_PER_SPECIES = 4
    DAYS_PER_SEASON = 91.3125

    def __init__(self, world_model):
        self.world_model = world_model
        self.representatives = {}
        self._serials = {}

    def _new_representative(self, species_id, x, y):
        serial = self._serials.get(species_id, 0) + 1
        self._serials[species_id] = serial
        digest = hashlib.sha256(f"{species_id}:{x:.5f}:{y:.5f}:{serial}".encode("utf-8")).digest()
        representative_id = f"runtime_{species_id}_representative_{serial:02d}"
        entity = self.world_model.get_entity(species_id) or {"id": species_id, "type": "species"}
        simulation = SpeciesSimulation(
            world_model=self.world_model,
            species_id=species_id,
            species_entity=entity,
            seed=int.from_bytes(digest[:2], "big"),
        )
        simulation.lod = 1
        simulation.set_age(1.0)
        representative = RepresentativeOrganism(
            representative_id=representative_id,
            species_id=species_id,
            x=x,
            y=y,
            seed=simulation.seed,
            simulation=simulation,
        )
        self.representatives[representative_id] = representative
        return representative

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
        for species_id in ecology.profiles:
            patches = ecology.species_patches(species_id)
            if not patches:
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
        outcomes_by_species = {}
        alive_representatives = [item for item in self.representatives.values() if item.alive]
        for representative in alive_representatives:
            local_abundance = ecology.abundance_at(representative.species_id, representative.x, representative.y)
            if local_abundance <= 0.003:
                representative.alive = False
                continue
            environment = ecology.environment_at(representative.x, representative.y)
            profile = ecology.profiles[representative.species_id]
            total_abundance = ecology.total_abundance_at(representative.x, representative.y)
            local_scale = max((patch.radius_m for patch in ecology.species_patches(representative.species_id)), default=0.5)
            nearby_representatives = sum(
                item.alive
                and item.representative_id != representative.representative_id
                and math.hypot(item.x - representative.x, item.y - representative.y) <= max(0.6, local_scale * 1.5)
                for item in alive_representatives
            )
            water_stress = _clamp(abs(environment["soil_moisture"] - profile.moisture_optimum) / profile.moisture_tolerance)
            light_stress = _clamp((profile.light_minimum - environment["surface_solar_exposure"]) / max(0.08, profile.light_minimum))
            deep_environment = {
                "water_stress": water_stress,
                "light_stress": light_stress,
                "competition": _clamp(max(0.0, total_abundance - local_abundance) + nearby_representatives * 0.06),
                "disturbance": 0.0,
                "disease_pressure": _clamp(nearby_representatives * 0.025),
            }
            representative.age_days += self.DAYS_PER_SEASON
            representative.simulation.set_age(representative.age_days)
            outcome = representative.simulation.get_ecological_outcome(deep_environment)
            representative.last_outcome = dict(outcome)
            representative.seasons_lived += 1
            representative.reproduction_index += float(outcome.get("fecundity", 0.0) or 0.0)
            vitality = float(outcome.get("vitality", 0.0) or 0.0)
            mortality = float(outcome.get("mortality_risk", 0.0) or 0.0)
            representative.health = _clamp(representative.health + (vitality - 0.42) * 0.18 - mortality * 0.035)
            if outcome.get("life_history", {}).get("phase") == "dead" or representative.health <= 0.025 or local_abundance <= 0.003:
                representative.alive = False
            outcomes_by_species.setdefault(representative.species_id, []).append(outcome)

        feedback = {}
        for species_id, outcomes in outcomes_by_species.items():
            count = max(1, len(outcomes))
            vitality = sum(float(item.get("vitality", 0.0) or 0.0) for item in outcomes) / count
            fecundity = sum(float(item.get("fecundity", 0.0) or 0.0) for item in outcomes) / count
            mortality = sum(float(item.get("mortality_risk", 0.0) or 0.0) for item in outcomes) / count
            feedback[species_id] = {
                "representative_count": count,
                "mean_vitality": vitality,
                "mean_fecundity": fecundity,
                "mean_mortality_risk": mortality,
                "growth_multiplier": 0.68 + vitality * 0.72,
                "dispersal_multiplier": 0.72 + fecundity * 0.72,
                "mortality_pressure": mortality * 0.018,
            }
        return feedback

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
