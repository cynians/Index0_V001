"""Canonical topology, microphyll accounting and spore-cone transport."""
import copy
import json
import math

import pytest

from simulations.species.creeping_uprights import creeping_upright_profile
from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import AuthoringError, validate_updates


@pytest.fixture
def entity():
    return {'plant_growth_form': 'other_unknown', 'plant_growth_behaviour': 'stoloniferous_clonal',
        'plant_woodiness': 'herbaceous', 'plant_lifespan': 'perennial',
        'root_architecture': 'adventitious', 'leaf_length': {'typical_m': .007},
        'reproductive_mode': 'both', 'plant_reproductive_structure': 'strobilus',
        'plant_shoot_profile': {'form': 'creeping_uprights', 'runner_length_m': .5,
            'runner_radius_m': .001, 'upright_height_m': .22, 'upright_radius_m': .0011,
            'leaf_width_m': .001, 'runner_leaf_fraction': .25, 'fork_spread': .32,
            'constriction_depth': .72, 'strobilus_length_m': .025, 'strobilus_width_m': .004,
            'fertile_fraction': .65, 'runner_count': 2, 'uprights_per_runner': 4,
            'leaves_per_upright': 220, 'fork_levels': 0, 'growth_sections': 4}}


def simulate(entity):
    return SpeciesSimulation(species_entity=entity, species_id='synthetic_uprights', seed=303)


def test_determinism_canonical_lod_and_no_angiosperm_organs(entity):
    s = simulate(entity)
    a = s.generate_snapshot(177.75, 2)
    assert a.to_dict() == s.generate_snapshot(177.75, 2).to_dict()
    assert a.stats['upright_shoot_count'] == 8
    assert a.stats['estimated_leaf_count'] == 1872
    assert a.stats['strobilus_count'] == 5
    assert not any(p[0] in {'flower', 'fruit'} for p in a.placements)
    assert len(a.leaf_clusters) == a.stats['estimated_leaf_count']
    assert a.stats['leaf_area_m2'] == round(sum(x['leaf_area_m2'] for x in a.leaf_clusters), 6)
    for lod in (0, 1):
        b = s.generate_snapshot(177.75, lod)
        for key in ('estimated_leaf_count', 'leaf_area_m2', 'strobilus_count', 'structural_axis_length_m', 'root_length_m'):
            assert b.stats[key] == a.stats[key]
    assert len(a.placements) < 4000


def test_actual_attachment_sockets_and_path_bounds(entity):
    a = simulate(entity).generate_snapshot(177.75, 2)
    for i, p in enumerate(a.placements):
        assert p[1] < i
        assert p[1] >= 0 or p[0] == 'root'
        assert all(math.isfinite(v) for v in p[2:])
        for point in a.placement_paths.get(str(i), []):
            for axis, value in enumerate(point):
                assert a.bounds_m[axis*2]-.001 <= value <= a.bounds_m[axis*2+1]+.001
        if p[0] == 'strobilus':
            assert a.placements[p[1]][2:5] == p[2:5]
            assert a.placement_orientations[str(i)]['spore_cone']
    runner_sockets = [x['position_m'] for x in a.attachment_points if x['socket'] == 'upright_base']
    assert len({tuple(x) for x in runner_sockets if x[2] < .003}) == 8
    assert a.stats['rooting_contact_count'] == 8


def test_forks_change_topology_without_enlarging_leaves(entity):
    a = simulate(entity).generate_snapshot(177.75, 2)
    changed = copy.deepcopy(entity)
    changed['plant_shoot_profile'].update(fork_levels=1, constriction_depth=0.)
    s = simulate(changed)
    b = s.generate_snapshot(177.75, 2)
    assert b.stats['upright_fork_count'] > a.stats['upright_fork_count']
    assert b.stats['estimated_leaf_count'] > a.stats['estimated_leaf_count']
    assert s.blueprint.module('leaf').length_m == .007
    assert s.blueprint.fingerprint() != simulate(entity).blueprint.fingerprint()


def test_missing_unknown_and_zero_controls(entity):
    unknown = copy.deepcopy(entity)
    unknown['plant_shoot_profile']['form'] = 'other_unknown'
    assert 'creeping_upright_version' not in simulate(unknown).blueprint.growth
    unknown.pop('plant_shoot_profile')
    assert 'creeping_upright_version' not in simulate(unknown).blueprint.growth
    entity['plant_shoot_profile'].update(fertile_fraction=0., runner_leaf_fraction=0.)
    a = simulate(entity).generate_snapshot(177.75, 2)
    assert a.stats['strobilus_count'] == 0
    assert a.stats['estimated_leaf_count'] == 1760
    entity['reproductive_mode'] = 'vegetative'
    entity['plant_shoot_profile']['fertile_fraction'] = 1.
    assert simulate(entity).generate_snapshot(177.75, 2).stats['strobilus_count'] == 0


@pytest.mark.parametrize('key,value', [('runner_count', 0), ('runner_count', True),
    ('runner_length_m', float('nan')), ('upright_radius_m', float('inf')),
    ('fork_levels', 3), ('leaves_per_upright', 999)])
def test_invalid_recipes_are_rejected_and_neutral(entity, key, value):
    entity['plant_shoot_profile'][key] = value
    assert creeping_upright_profile(entity['plant_shoot_profile']) is None
    with pytest.raises(AuthoringError):
        validate_updates({'plant_shoot_profile': entity['plant_shoot_profile']})
    assert 'creeping_upright_version' not in simulate(entity).blueprint.growth


def test_budget_and_portable_spore_module(entity):
    blueprint = simulate(entity).blueprint
    restored = PlantBlueprint.from_dict(json.loads(json.dumps(blueprint.to_dict())))
    assert restored.fingerprint() == blueprint.fingerprint()
    assert restored.module('strobilus').length_m == .025
    assert restored.module('strobilus').radius_m == .002
    entity['plant_shoot_profile'].update(runner_count=4, uprights_per_runner=8, fork_levels=2)
    assert creeping_upright_profile(entity['plant_shoot_profile']) is None


def test_leaf_remainder_and_stage_development(entity):
    entity['plant_shoot_profile'].update(leaves_per_upright=33, runner_leaf_fraction=0.)
    s = simulate(entity)
    a, b = s.generate_snapshot(5, 2), s.generate_snapshot(177.75, 2)
    assert a.stats['upright_shoot_count'] < b.stats['upright_shoot_count']
    assert b.stats['estimated_leaf_count'] == 8*33
