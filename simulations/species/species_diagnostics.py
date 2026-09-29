"""Diagnostic products for comparing individuals from one Species Sim."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simulations.species.plant_assets import PlantAssetStore
from simulations.species.species_simulation import SpeciesSimulation


DEFAULT_GALLERY_STAGES = (
    ("seedling", 0.0),
    ("juvenile", 0.35),
    ("subadult", 0.65),
    ("mature", 1.0),
    ("senescent", 1.0),
)

TREE_ARCHITECTURE_SPECIES_IDS = (
    "spec_betula_pendula",
    "spec_quercus_robur",
    "spec_aesculus_hippocastanum",
)


@dataclass
class GrowthGalleryCase:
    """One rendered comparison specimen and its compact diagnostic record."""

    index: int
    stage: str
    seed: int
    age_days: float
    simulation: SpeciesSimulation

    @property
    def snapshot(self):
        return self.simulation.render_snapshot

    def record(self) -> dict[str, Any]:
        summary = self.simulation.get_growth_summary()
        life_state = self.simulation.life_state(self.age_days)
        return {
            "index": self.index,
            "stage": self.stage,
            "seed": self.seed,
            "age_days": round(self.age_days, 3),
            "life_phase": life_state.get("phase"),
            "maturity": summary.get("maturity", 0.0),
            "placement_count": summary.get("placement_count", 0),
            "stem_count": summary.get("stem_count", 0),
            "branch_count": summary.get("branch_count", 0),
            "leaf_count": summary.get("leaf_count", 0),
            "leaf_sample_count": summary.get("leaf_sample_count", summary.get("leaf_count", 0)),
            "leaf_cluster_count": summary.get("leaf_cluster_count", 0),
            "estimated_leaf_count": summary.get("estimated_leaf_count", summary.get("leaf_count", 0)),
            "leaf_area_m2": summary.get("leaf_area_m2", 0.0),
            "curved_segment_count": summary.get("curved_segment_count", 0),
            "vitality": self.simulation.get_ecological_outcome({}).get("vitality", 0.0),
        }


def _stage_age(simulation, stage, fraction):
    """Choose ages from the species' authored life-history thresholds."""

    profile = simulation.life_history_profile
    maturity = simulation.mature_age_days
    if stage == "seedling":
        if simulation.blueprint.growth.get("growth_behaviour") == "tussock_tillering":
            return max(1., maturity*.05)
        return 0.0
    if stage in {"juvenile", "subadult"}:
        return max(1.0, maturity * fraction)
    if stage == "mature":
        return maturity
    reproductive_start = float(profile.get("reproductive_start_days", maturity) or maturity)
    senescence_start = float(profile.get("senescence_start_days", reproductive_start) or reproductive_start)
    if stage == "reproductive":
        return min(simulation.max_age_days, reproductive_start + max(1.0, (senescence_start - reproductive_start) * 0.35))
    decline_window = max(30.0, float(profile.get("cycle_days", 365.0) or 365.0))
    return min(simulation.max_age_days, senescence_start + decline_window * 0.25)


def build_growth_gallery(
    species_entity: dict[str, Any],
    *,
    species_id: str | None = None,
    asset_store: PlantAssetStore | None = None,
    seeds: tuple[int, ...] = (101, 202, 303, 404),
    stages=DEFAULT_GALLERY_STAGES,
    lod: int = 2,
) -> list[GrowthGalleryCase]:
    """Build a deterministic matrix of maturity stages and individuals."""

    if stages is DEFAULT_GALLERY_STAGES and species_entity.get("plant_growth_behaviour") == "tussock_tillering":
        # Include flowering explicitly: maturity can precede reproductive onset.
        stages = (("seedling", .05), ("juvenile", .35), ("mature", 1.),
                  ("reproductive", 1.), ("senescent", 1.))
    species_id = str(species_id or species_entity.get("id") or "species_preview")
    cases = []
    index = 1
    for stage, fraction in stages:
        for seed in seeds:
            simulation = SpeciesSimulation(
                species_entity=species_entity,
                species_id=species_id,
                seed=int(seed),
                asset_store=asset_store,
            )
            simulation.set_lod(lod)
            simulation.set_age(_stage_age(simulation, stage, fraction))
            cases.append(GrowthGalleryCase(index, stage, int(seed), simulation.age_days, simulation))
            index += 1
    return cases


def build_tree_architecture_comparison(world_model=None, *, asset_store=None, seed=303):
    """Build the fixed three-tree benchmark from live ontology entities."""

    entities = []
    if world_model is not None:
        for species_id in TREE_ARCHITECTURE_SPECIES_IDS:
            if hasattr(world_model, "resolved_species_entity"):
                entity = world_model.resolved_species_entity(species_id)
            else:
                entity = world_model.get_entity(species_id) if hasattr(world_model, "get_entity") else None
            if isinstance(entity, dict):
                entities.append(entity)
    else:
        from pathlib import Path
        from world.persistent_ontology_store import PersistentOntologyStore

        datasets = PersistentOntologyStore(
            Path(__file__).resolve().parents[2] / "ontology" / "index0.owl"
        ).load_datasets()
        by_id = {
            entity["id"]: entity
            for rows in datasets.values()
            for entity in rows
            if isinstance(entity, dict) and entity.get("id")
        }
        entities = [by_id[species_id] for species_id in TREE_ARCHITECTURE_SPECIES_IDS if species_id in by_id]

    cases = []
    for entity in entities:
        simulation = SpeciesSimulation(species_entity=entity, seed=seed, asset_store=asset_store)
        simulation.set_lod(2)
        simulation.set_age(simulation.mature_age_days)
        cases.append(simulation)
    return cases
