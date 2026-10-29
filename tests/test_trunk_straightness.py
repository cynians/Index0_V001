"""Visual straightness is independent of the plant's unknown botanical architecture."""

import math

import pytest

from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_editor import editable_field_rows, new_editor_state, preview_entity
from simulations.species.species_simulation import SpeciesSimulation


def tree(**updates):
    return dict(id="spec_synthetic_straight_trunk", plant_growth_form="tree",
                plant_growth_behaviour="branched_woody", plant_axis_continuity="other_unknown",
                plant_leaf_distribution="along_shoot", mature_height={"max_m": 8},
                leaf_length={"typical_m": 0.09}, **updates)


def grown(entity, seed=303, lod=2):
    sim = SpeciesSimulation(species_entity=entity, seed=seed)
    sim.set_lod(lod)
    sim.set_age(sim.mature_age_days)
    return sim


def trunk_nodes(sim):
    return [(index, p) for index, p in enumerate(sim.render_snapshot.placements)
            if p[0] == "stem_section" and p[7] == 1]


def test_zero_keeps_existing_snapshot_geometry_and_missing_keeps_blueprint_shape():
    absent = grown(tree())
    zero = grown(tree(plant_trunk_straightness={"typical": 0}))
    assert "trunk_straightness" not in absent.blueprint.growth
    assert "trunk_straightness" not in absent.blueprint.growth["architecture_ranges"]
    first, second = absent.render_snapshot.to_dict(), zero.render_snapshot.to_dict()
    first.pop("blueprint_fingerprint")
    second.pop("blueprint_fingerprint")
    assert first == second


def test_straightness_reduces_all_primary_trunk_deviations_and_internal_bends():
    results = [grown(tree(plant_trunk_straightness={"typical": amount}))
               for amount in (0, 0.5, 1)]
    deviations = [max(math.hypot(p[2], p[3]) for _i, p in trunk_nodes(sim)[:12]) for sim in results]
    assert deviations[0] > deviations[1] > deviations[2]
    assert deviations[2] == 0
    assert len({sim.blueprint.fingerprint() for sim in results}) == 3
    for sim in results:
        assert sim.blueprint.growth["axis_continuity"] == "other_unknown"
    assert [p[4] for _i, p in trunk_nodes(results[0])] == [p[4] for _i, p in trunk_nodes(results[2])]
    assert [p[6] for _i, p in trunk_nodes(results[0])] == [p[6] for _i, p in trunk_nodes(results[2])]
    assert len(results[0].render_snapshot.placements) == len(results[2].render_snapshot.placements)
    for index, p in trunk_nodes(results[2]):
        assert str(index) not in results[2].render_snapshot.placement_paths
        assert all(math.isfinite(value) for value in p[2:7])


def test_straight_secondary_trunks_keep_separation():
    entity = tree(plant_apical_control={"typical": 0}, plant_trunk_straightness={"typical": 1})
    sim = grown(entity, seed=303)
    nodes = trunk_nodes(sim)
    assert len(nodes) > 12
    assert all(p[2] == p[3] == 0 for _i, p in nodes[:12])
    assert any(math.hypot(p[2], p[3]) > 0.01 for _i, p in nodes[12:])
    # Every secondary axis is straight even though it inclines away from the primary.
    for start in range(12, len(nodes), 12):
        axis = [p for _i, p in nodes[start:start + 12]]
        tip = axis[-1]
        for p in axis:
            assert p[2] == pytest.approx(tip[2] * p[4] / tip[4], abs=0.0002)
            assert p[3] == pytest.approx(tip[3] * p[4] / tip[4], abs=0.0002)


def test_range_is_editable_portable_deterministic_and_ecology_stable_across_lods():
    entity = tree(plant_trunk_straightness={"min": 0, "typical": 0.5, "max": 1,
                                          "status": "visual_fit", "source": "test_observation"})
    rows = editable_field_rows(entity, "trunk")
    assert next(r for r in rows if r["field"] == "plant_trunk_straightness")["kind"] == "range"
    state = new_editor_state(entity)
    assert preview_entity(state, "minimum")["plant_trunk_straightness"]["typical"] == 0
    assert preview_entity(state, "maximum")["plant_trunk_straightness"]["typical"] == 1
    sim = grown(entity)
    assert sim.render_snapshot.to_dict() == grown(entity).render_snapshot.to_dict()
    assert sim.blueprint.to_dict() == PlantBlueprint.from_dict(sim.blueprint.to_dict()).to_dict()
    for lod in (0, 1):
        outcome = grown(entity, lod=lod).get_ecological_outcome()
        for key in ("structural_biomass_proxy", "resource_demand", "estimated_leaf_count"):
            assert outcome[key] == sim.get_ecological_outcome()[key]
