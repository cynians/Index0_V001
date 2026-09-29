"""Re-bake existing authored plant products with the explicit 3D contract."""

from __future__ import annotations

import json
import gzip
from pathlib import Path

from simulations.species.plant_assets import PlantAssetStore, PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from world.entity_loader import EntityLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main():
    loader = EntityLoader(
        entries_directory=PROJECT_ROOT / "entries",
        ontology_path=PROJECT_ROOT / "ontology" / "index0.owl",
        use_ontology=True,
    )
    asset_store = PlantAssetStore(PROJECT_ROOT / "assets" / "plants")
    migrated = []

    for blueprint_path in sorted(asset_store.blueprint_root.glob("*.json.gz")):
        species_id = blueprint_path.name.removesuffix(".json.gz")
        old_blueprint = asset_store.load_blueprint(species_id)
        if old_blueprint is None:
            continue
        old_blueprint.version = 4
        old_blueprint.model_space = {
            "dimensions": 3,
            "up_axis": "z",
            "depth_axis": "y",
            "projection": "orthographic",
            "asset_dimension": 2,
        }
        blueprint_path_out = asset_store.save_blueprint(old_blueprint)

        species = loader.entities.get(species_id) or {"id": species_id}
        snapshot_dir = asset_store.snapshot_root / species_id
        snapshot_count = 0
        snapshot_paths = sorted(snapshot_dir.glob("*.json.gz")) if snapshot_dir.exists() else []
        for snapshot_path in snapshot_paths:
            try:
                with gzip.open(snapshot_path, "rt", encoding="utf-8") as handle:
                    old_snapshot = PlantGrowthSnapshot.from_dict(json.load(handle))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            simulation = SpeciesSimulation(
                species_entity=species,
                species_id=species_id,
                seed=old_snapshot.seed,
                blueprint=old_blueprint,
                asset_store=asset_store,
            )
            simulation.set_lod(old_snapshot.lod)
            simulation.set_age(old_snapshot.age_days)
            asset_store.save_snapshot(simulation.render_snapshot)
            snapshot_count += 1

        migrated.append({
            "species_id": species_id,
            "blueprint": blueprint_path_out,
            "snapshots_rebaked": snapshot_count,
        })

    print(json.dumps({"migrated": migrated}, indent=2))


if __name__ == "__main__":
    main()
