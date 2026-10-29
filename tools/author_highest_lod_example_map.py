"""Persist the target recipe and separate biological inspection overlay only."""
from pathlib import Path
import argparse
import json

from simulations.world_gen.highest_lod_example import target_entity, inspection_overlay, build_models, RECIPE_VERSION, MAP_ID
from world.persistent_ontology_store import PersistentOntologyStore


def build_changes(datasets, revise=False):
    existing = {e["id"]: e for rows in datasets.values() for e in rows}
    changes = []
    target = existing.get(MAP_ID)
    old_recipe = (target or {}).get("map_generation_recipe") or []
    revision = revise and target is not None and RECIPE_VERSION not in old_recipe
    if revision and "estuary-survey-target-v1" not in old_recipe:
        raise ValueError("Refusing to revise a target with an unrecognized recipe")
    for authored in (target_entity(), inspection_overlay()):
        old = existing.get(authored["id"])
        if old is not None:
            if not revision:
                continue
            # Full replacements preserve unrelated fields on both existing entities.
            authored = {**old, **authored}
            if authored["id"] == MAP_ID:
                for key in build_models():
                    authored.pop(key,None)  # Only the recipe is persisted, not million-cell grids.
        changes.append(authored)
    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--revise",action="store_true")
    args = parser.parse_args()
    store = PersistentOntologyStore(Path("ontology/index0.owl"))
    datasets = store.load_datasets()
    species = {e["id"] for e in datasets.get("species", [])}
    assert all(i["species_id"] in species for i in inspection_overlay()["inspection_introductions"])
    build_models()  # Validate all retained assets before changing the live target.
    changes = build_changes(datasets,revise=args.revise)
    if changes:
        if args.revise:
            backup=Path("artifacts/highest_lod_example_map_v2/v1_ontology_snapshot.json")
            backup.parent.mkdir(parents=True,exist_ok=True)
            if not backup.exists():
                ids={e["id"] for e in changes}
                backup.write_text(json.dumps([e for rows in datasets.values() for e in rows if e["id"] in ids],indent=2),encoding="utf-8")
        print(store.apply_changes(entities=changes))
    else:
        print("Target and overlay already exist; preserved without changes.")


if __name__ == "__main__":
    main()
