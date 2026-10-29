"""Persist only the lightweight generated-landscape recipe and Biosphere overlay."""

from pathlib import Path

from simulations.world_gen.generated_landscape_artifact import (
    MAP_ID,
    biosphere_overlay,
    build_models,
    target_entity,
)
from world.persistent_ontology_store import PersistentOntologyStore


def build_changes(datasets):
    existing = {entity["id"]: entity for rows in datasets.values() for entity in rows}
    changes = []
    for authored in (target_entity(), biosphere_overlay()):
        old = existing.get(authored["id"])
        merged = {**old, **authored} if isinstance(old, dict) else authored
        if old != merged:
            changes.append(merged)
    return changes


def main():
    build_models()  # Validate retained artifacts before changing the ontology.
    store = PersistentOntologyStore(Path("ontology/index0.owl"))
    changes = build_changes(store.load_datasets())
    print(store.apply_changes(entities=changes) if changes else f"{MAP_ID} is current")


if __name__ == "__main__":
    main()
