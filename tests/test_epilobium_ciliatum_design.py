"""Live willowherb composition and reusable heterophyllous forb response."""

import gzip
import json
from copy import deepcopy
from pathlib import Path

from PIL import Image

from simulations.species.basal_herbs import basal_herb_profile
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from world.plant_catalogue import PlantCatalogue
from world.world_model import WorldModel


SID = "spec_epilobium_ciliatum"


def _saved_entity():
    world = WorldModel()
    return world, world.resolved_species_entity(SID)


def _snapshot(entity, day=240, lod=2):
    sim = SpeciesSimulation(species_entity=entity, seed=303)
    return sim, sim.generate_snapshot(age_days=day, lod=lod)


def test_live_record_and_pixel_studio_assets():
    world, entity = _saved_entity()
    raw = world.loader.get(SID)
    assert PlantCatalogue.build(world.loader.entities).is_leaf_species(SID)
    assert raw["parents"] == ["cladis_willowherbs_epilobium"]
    assert raw["binomial_name"] == "Epilobium ciliatum"
    assert raw["plant_lifespan"] == "perennial"
    assert raw["reproductive_mode"] == "both"
    assert raw["leaf_arrangement"] == "opposite"
    assert raw["plant_shoot_profile"]["upper_leaf_arrangement"] == "alternate"
    for unresolved in ("maturity_age", "longevity", "max_root_depth", "mycorrhizal_type"):
        assert not raw.get(unresolved)
    for role in ("leaf", "stem", "branch", "flower", "fruit"):
        path = Path(raw[f"plant_{role}_module_ref"])
        with Image.open(path) as image:
            assert image.mode == "RGBA" and image.size == (75, 75)
        row = world.loader.get(f"illust_epilobium_ciliatum_{role}_module")
        assert row["parents"] == [SID] and row["media_path"] == path.as_posix()
        with gzip.open(row["pixel_document_path"], "rt", encoding="utf-8") as stream:
            document = json.load(stream)
        assert document["version"] == 2 and document["layers"]
        assert entity[f"plant_{role}_module_ref"] == path.as_posix()


def test_transition_is_bounded_and_changes_leaf_counts_without_changing_axes():
    _, entity = _saved_entity()
    sim, mixed = _snapshot(entity)
    main = [c for c in mixed.leaf_clusters if c["branch_order"] == 0]
    assert {c["estimated_leaf_count"] for c in main} == {1, 2}
    lower = [c for c in main if c["position_m"][2] < 0.30]
    upper = [c for c in main if c["position_m"][2] > 0.43]
    assert lower and upper
    assert all(c["estimated_leaf_count"] == 2 for c in lower)
    assert all(c["estimated_leaf_count"] == 1 for c in upper)

    control = deepcopy(entity)
    control["id"] = "spec_unrelated_heterophyllous_forb_fixture"
    control["plant_shoot_profile"] = dict(entity["plant_shoot_profile"])
    control["plant_shoot_profile"].pop("upper_leaf_arrangement")
    control["plant_shoot_profile"].pop("leaf_arrangement_transition_fraction")
    other_sim, opposite = _snapshot(control)
    assert "leaf_arrangement_transition_version" not in other_sim.blueprint.growth
    assert sim.blueprint.fingerprint() != other_sim.blueprint.fingerprint()
    assert all(c["estimated_leaf_count"] == 2 for c in opposite.leaf_clusters if c["branch_order"] == 0)
    axes = lambda s: [(p[0], p[2:5]) for p in s.placements if p[0] in {"stem_section", "branch_section"}]
    assert axes(mixed) == axes(opposite)
    assert mixed.stats["estimated_leaf_count"] < opposite.stats["estimated_leaf_count"]
    assert basal_herb_profile({**entity["plant_shoot_profile"], "leaf_arrangement_transition_fraction": float("nan")}) is None
    assert basal_herb_profile({**entity["plant_shoot_profile"], "upper_leaf_arrangement": "other_unknown"}) is None


def test_flower_to_capsule_cycle_and_lod_stable_canonical_counts():
    _, entity = _saved_entity()
    _, flowers = _snapshot(entity, 178)
    _, fruits = _snapshot(entity, 281)
    assert any(p[0] == "flower" for p in flowers.placements)
    assert any(p[0] == "fruit" for p in fruits.placements)
    assert not any(p[0] == "fruit" for p in flowers.placements)
    assert not any(p[0] == "flower" for p in fruits.placements)
    assert fruits.to_dict() == _snapshot(entity, 281)[1].to_dict()
    assert PlantGrowthSnapshot.from_dict(fruits.to_dict()).to_dict() == fruits.to_dict()
    assert PlantBlueprint.from_dict(PlantBlueprint.from_species_entity(entity).to_dict()).fingerprint() == PlantBlueprint.from_species_entity(entity).fingerprint()
    for lod in (0, 1, 2):
        _, sample = _snapshot(entity, 281, lod)
        assert sample.stats["estimated_leaf_count"] == fruits.stats["estimated_leaf_count"]
        assert sample.stats["leaf_area_m2"] == fruits.stats["leaf_area_m2"]
        assert len(sample.placements) < 1000
        assert all(-1 <= p[1] < i for i, p in enumerate(sample.placements))
    for change in ({"plant_reproductive_profile": None}, {"reproductive_mode": "vegetative"},
                   {"plant_reproductive_structure": "other_unknown"}):
        control = {**entity, **change, "id": "spec_unrelated_fruiting_forb_fixture"}
        assert not any(p[0] == "fruit" for p in _snapshot(control, 281)[1].placements)
