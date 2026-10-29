import json
import math
from collections import Counter
from pathlib import Path

import pytest

from simulations.species.lateral_shoots import (
    LATERAL_SHOOT_FIELDS, authored_shoot_control, lateral_shoot_path, point_on_shoot,
)
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_editor import editable_field_rows, new_editor_state, preview_entity
from simulations.species.species_simulation import SpeciesSimulation


def entity(**updates):
    return {"id": "spec_unrelated_lateral_fixture", "plant_growth_form": "forb",
            "plant_woodiness": "herbaceous", "plant_growth_behaviour": "iterative_indeterminate",
            "leaf_attachment_pattern": "along_stem", "plant_leaf_distribution": "along_shoot",
            "leaf_arrangement": "opposite", "plant_flowering_position": "terminal",
            "plant_reproductive_structure": "compound_umbel", "reproductive_mode": "sexual",
            "mature_height": {"typical_m": .7, "max_m": 1.2}, **updates}


def simulation(data, lod=2, seed=303):
    sim = SpeciesSimulation(species_entity=data, seed=seed)
    sim.set_age(170); sim.set_lod(lod)
    return sim


@pytest.mark.parametrize("field", LATERAL_SHOOT_FIELDS)
@pytest.mark.parametrize("value", [None, {}, "other_unknown", True, float("nan"), float("inf"),
                                   -.1, 1.1, {"min": .5, "typical": .2, "max": .8}])
def test_missing_invalid_unknown_keeps_exact_legacy_geometry(field, value):
    a, b = simulation(entity()), simulation(entity(**{field: value}))
    assert authored_shoot_control(value) is None
    assert a.blueprint.fingerprint() == b.blueprint.fingerprint()
    assert a.render_snapshot.to_dict() == b.render_snapshot.to_dict()
    assert a.get_ecological_outcome({}) == b.get_ecological_outcome({})


def test_arc_length_control_and_zero_have_literal_meaning():
    origin = (0., 0., .6); old = (.3, .2, .8)
    assert lateral_shoot_path(origin, old, 1) is None
    assert lateral_shoot_path(origin, old, 1, 0, .8) == [origin]
    for length in [0.1, .3, 1]:
        path = lateral_shoot_path(origin, old, 1, length, .8)
        assert sum(math.dist(a,b) for a,b in zip([origin,*path],path)) == pytest.approx(length)
    path = lateral_shoot_path(origin, old, 20, 1, 1)
    assert len(path) == 8
    assert sum(math.dist(a,b) for a,b in zip([origin,*path],path)) <= 2


def test_curvature_changes_tangent_and_reach_without_changing_arc_length():
    origin = (0., 0., .6); old = (.3, .0, .85)
    paths = [lateral_shoot_path(origin,old,1,.2,curve) for curve in [0,.4,.8,1]]
    reaches = [p[-1][0] for p in paths]
    assert reaches == sorted(reaches,reverse=True)
    elevations = []
    for p in paths:
        dx,dy,dz = [b-a for a,b in zip(p[-2],p[-1])]
        elevations.append(math.degrees(math.atan2(dz,math.hypot(dx,dy))))
        assert sum(math.dist(a,b) for a,b in zip([origin,*p],p)) == pytest.approx(.2)
    assert elevations == sorted(elevations)
    assert elevations[-1] > 85


@pytest.mark.parametrize("mode", ["iterative_indeterminate", "suckering_clonal",
                                  "rhizomatous_clonal", "stoloniferous_clonal"])
def test_shared_geometry_has_valid_connected_sockets_and_conserves_ecology(mode):
    base = entity(plant_growth_behaviour=mode, clonal_spread="moderate")
    fitted = {**base, "plant_lateral_shoot_length": .15, "plant_lateral_shoot_curvature": .8}
    a, b = simulation(base), simulation(fitted)
    assert a.blueprint.fingerprint() != b.blueprint.fingerprint()
    assert Counter(p[0] for p in a.render_snapshot.placements) == Counter(p[0] for p in b.render_snapshot.placements)
    assert a.get_ecological_outcome({}) == b.get_ecological_outcome({})
    def underground(sim):
        return [p for p in sim.render_snapshot.placements if p[0] in {"root", "root_section", "root_support"}
                or (p[0] == "branch_section" and p[4] <= 0)]
    assert underground(a) == underground(b)
    assert b.render_snapshot.to_dict() == simulation(fitted).render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(b.render_snapshot.to_dict()).to_dict() == b.render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(b.blueprint.to_dict()).fingerprint() == b.blueprint.fingerprint()
    assert any(p[0] == "branch_section" for p in b.render_snapshot.placements)
    for i,p in enumerate(b.render_snapshot.placements):
        assert -1 <= p[1] < i
        assert all(math.isfinite(v) for v in p[2:7])
        if p[0] != "leaf" or b.render_snapshot.placements[p[1]][0] != "branch_section":
            continue
        host = b.render_snapshot.placements[p[1]]
        origin = b.render_snapshot.placements[host[1]][2:5]
        path = b.render_snapshot.placement_paths[str(p[1])]
        # Distance to the nearest actual path piece is zero within rounding.
        distances = []
        for start,end in zip([origin,*path],path):
            d = [end[k]-start[k] for k in range(3)]; norm = sum(v*v for v in d)
            t = max(0,min(1,sum((p[2+k]-start[k])*d[k] for k in range(3))/max(1e-12,norm)))
            distances.append(math.dist(p[2:5],[start[k]+d[k]*t for k in range(3)]))
        assert min(distances) < .0002
    for lod in [0,1]:
        low = simulation(fitted,lod)
        assert low.get_ecological_outcome({}) == b.get_ecological_outcome({})
        def branches(sim):
            return [p[2:5] for p in sim.render_snapshot.placements if p[0] == "branch_section"]
        assert branches(low) == branches(b)


def test_editor_ranges_use_independent_sampling_and_do_not_fill_missing_controls():
    base = entity(plant_branch_droop={"min": .2,"typical":.4,"max":.6})
    assert all(k not in preview_entity(new_editor_state(base)) for k in LATERAL_SHOOT_FIELDS)
    fitted = {**base, **{k: {"min": .1,"typical":.2,"max":.3} for k in LATERAL_SHOOT_FIELDS}}
    for field in LATERAL_SHOOT_FIELDS:
        row = next(r for r in editable_field_rows(fitted) if r["field"] == field)
        assert row["kind"] == "range" and row["affects_preview"]
        assert [preview_entity(new_editor_state(fitted), mode)[field]["typical"]
                for mode in ["minimum","typical","maximum"]] == [.1,.2,.3]
    for seed in range(4):
        a = preview_entity(new_editor_state(base),"variation",seed)
        b = preview_entity(new_editor_state(fitted),"variation",seed)
        assert {k:v for k,v in b.items() if k not in LATERAL_SHOOT_FIELDS} == a
    assert not any(r["field"] in LATERAL_SHOOT_FIELDS for r in editable_field_rows(
        entity(plant_growth_form="tree")))


@pytest.mark.parametrize("sid", ["spec_praxelis_clematidea","spec_cirsium_arvense"])
def test_actual_before_snapshot_is_exactly_preserved_without_new_controls(sid):
    before = json.loads((Path('artifacts')/sid/'shoot_refinement_before.json').read_text())
    sim = SpeciesSimulation(species_entity=before['resolved'],species_id=sid,seed=303)
    sim.set_age(before['age_days']); sim.set_lod(2)
    assert sim.render_snapshot.to_dict() == before['snapshot']
    assert sim.get_ecological_outcome({}) == before['ecology']


def test_inapplicable_fields_and_arc_socket_zero_are_neutral():
    base = entity(plant_growth_form="tree")
    fitted = {**base, "plant_lateral_shoot_length": .2, "plant_lateral_shoot_curvature": .8}
    assert simulation(base).blueprint.fingerprint() == simulation(fitted).blueprint.fingerprint()
    assert point_on_shoot((1,2,3),[(1,2,3)],.7) == (1,2,3)
