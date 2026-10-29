"""Live Kingcup composition and reusable basal cactus clump behavior."""
import copy
import json
import math
from pathlib import Path

import pytest

from simulations.species.columnar_succulents import columnar_profile
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import AuthoringError, validate_updates
from world.persistent_ontology_store import PersistentOntologyStore
from world.plant_catalogue import PlantCatalogue
from world.species_inheritance import is_authored_field
from world.world_model import WorldModel


SID = "spec_echinocereus_triglochidiatus"
UPDATES = json.loads(Path(f"artifacts/{SID}/pending_updates.json").read_text())


def synthetic(**changes):
    return {"id": "spec_other_clumping_cactus", "type": "species", **copy.deepcopy(UPDATES), **changes}


def simulation(entity=None, age=490.925, lod=2):
    sim = SpeciesSimulation(species_entity=entity or synthetic(), seed=303)
    sim.set_lod(lod)
    sim.set_age(age)
    return sim


def test_live_plant_identity_field_transport_and_editable_modules():
    datasets = PersistentOntologyStore(Path("ontology/index0.owl")).load_datasets()
    entities = {row["id"]: row for rows in datasets.values() if isinstance(rows, list)
                for row in rows if isinstance(row, dict) and row.get("id")}
    assert PlantCatalogue.build(entities).is_leaf_species(SID)
    assert entities[SID]["parents"] == ["cladis_echinocereus"]
    world = WorldModel()
    raw, resolved = world.loader.get(SID), world.resolved_species_entity(SID)
    for key, value in UPDATES.items():
        assert raw[key] == resolved[key] == value
        assert is_authored_field(raw, key)
    blueprint = PlantBlueprint.from_species_entity(resolved, SID)
    assert blueprint.growth["columnar_version"] == 2
    assert blueprint.growth["columnar_profile"]["axis_layout"] == "basal_clump"
    assert blueprint.growth["max_height_m"] == .3
    assert blueprint.growth["root_profile"]["depth_source"] == "depth_class_default"
    assert blueprint.growth["root_profile"]["target_depth_m"] == .35
    for role in ("leaf", "stem", "flower", "fruit"):
        field = f"plant_{role}_module_ref"
        assert is_authored_field(raw, field)
        path = Path(raw[field])
        assert path.is_file()
        assert path.with_suffix(".layers.json.gz").is_file()
    assert PlantBlueprint.from_dict(blueprint.to_dict()).fingerprint() == blueprint.fingerprint()


@pytest.mark.parametrize("field,value", [
    ("stem_count", 0), ("stem_count", True), ("stem_count", 65),
    ("stem_radius_m", math.nan), ("clump_radius_m", 0),
    ("rib_count", 3), ("areole_spacing_m", -1),
])
def test_invalid_basal_clump_controls_are_rejected(field, value):
    profile = {**UPDATES["plant_shoot_profile"], field: value}
    assert columnar_profile(profile) is None
    with pytest.raises(AuthoringError):
        validate_updates({"plant_shoot_profile": profile})
    unresolved = simulation(synthetic(plant_shoot_profile=profile))
    assert unresolved.render_snapshot.stats["columnar_model_status"] == "unresolved_missing_shoot_profile"


def test_connected_basal_stems_start_above_ground_without_false_horizontal_pad():
    sim = simulation()
    snap = sim.render_snapshot
    assert snap.to_dict() == simulation().render_snapshot.to_dict()
    assert snap.stats["columnar_axis_count"] == 9
    assert snap.stats["columnar_arm_count"] == 0
    assert snap.stats["estimated_leaf_count"] == 0
    assert snap.stats["leaf_area_m2"] == 0
    assert snap.stats["photosynthetic_stem_area_m2"] > .5
    assert snap.stats["stem_storage_volume_m3"] > 0
    assert snap.stats["columnar_flower_count"] == 18
    stems = [(i, p) for i, p in enumerate(snap.placements) if p[0] == "stem_section"]
    assert len(stems) == 9
    for index, placement in stems:
        assert snap.placements[placement[1]][0] == "root"
        path = snap.placement_paths[str(index)]
        assert path[0][2] == 0
        assert path[-1] == placement[2:5]
        assert all(b[2] >= a[2] for a, b in zip(path, path[1:]))
        assert sum(math.dist(a, b) for a, b in zip(path, path[1:])) < .5
    assert any(math.hypot(*snap.placement_paths[str(i)][0][:2]) > .05 for i, _ in stems)
    for index, placement in enumerate(snap.placements):
        assert placement[1] == -1 or 0 <= placement[1] < index
        assert all(math.isfinite(x) for x in placement[2:7])
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict() == snap.to_dict()


def test_stem_count_response_seasonal_organs_and_lod_stable_ecology():
    from tools.render_species_views import stage_ages
    normal = simulation()
    assert [label for label, _ in stage_ages(normal)[:2]] == ["Young stem", "Clump growth"]
    p = UPDATES["plant_shoot_profile"]
    fewer = simulation(synthetic(plant_shoot_profile={**p, "stem_count": 4}))
    wider = simulation(synthetic(plant_shoot_profile={**p, "stem_radius_m": .06}))
    assert fewer.render_snapshot.stats["columnar_axis_count"] == 4
    assert fewer.render_snapshot.stats["photosynthetic_stem_area_m2"] < normal.render_snapshot.stats["photosynthetic_stem_area_m2"]
    assert wider.render_snapshot.stats["stem_storage_volume_m3"] > normal.render_snapshot.stats["stem_storage_volume_m3"]
    assert fewer.blueprint.fingerprint() != normal.blueprint.fingerprint()
    assert wider.blueprint.fingerprint() != normal.blueprint.fingerprint()
    assert normal.render_snapshot.stats["root_depth_m"] == fewer.render_snapshot.stats["root_depth_m"]
    young, fruit = simulation(age=100), simulation(age=602.25)
    assert not any(p[0] in {"flower", "fruit"} for p in young.render_snapshot.placements)
    assert sum(p[0] == "fruit" for p in fruit.render_snapshot.placements) == 18
    assert not any(p[0] == "flower" for p in fruit.render_snapshot.placements)
    for lod in (0, 1):
        coarse = simulation(lod=lod)
        for key in ("photosynthetic_stem_area_m2", "stem_storage_volume_m3", "root_depth_m", "root_spread_m", "root_length_m"):
            assert coarse.render_snapshot.stats[key] == normal.render_snapshot.stats[key]
        assert coarse.get_ecological_outcome() == normal.get_ecological_outcome()
    assert normal.get_ecological_outcome()["photosynthetic_source"] == "green_stem_surface"


def test_biosphere_representative_uses_same_blueprint_and_grounded_metrics():
    from simulations.biosphere.representatives import RepresentativeBody
    world = WorldModel()
    live = SpeciesSimulation(world_model=world, species_id=SID, seed=303)
    live.set_age(490.925)
    rep = RepresentativeBody(species_entity=world.resolved_species_entity(SID), seed=303)
    rep.set_age(490.925)
    assert rep.blueprint.fingerprint() == live.blueprint.fingerprint()
    assert rep.render_snapshot.stats["columnar_axis_count"] == live.render_snapshot.stats["columnar_axis_count"]
    assert rep.get_ecological_outcome()["photosynthetic_stem_area_m2"] > 0
    assert rep.get_ecological_outcome()["root_depth_m"] == live.get_ecological_outcome()["root_depth_m"]
