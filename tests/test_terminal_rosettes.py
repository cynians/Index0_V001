"""Architecture and transport invariants for terminal rosettes."""
import copy
import json
import math

import pytest

from simulations.species.plant_assets import PlantBlueprint
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.terminal_rosettes import terminal_rosette_profile
from tools.author_plant_species import AuthoringError, validate_updates


@pytest.fixture
def entity():
    # A standalone synthetic recipe, independent of the live ontology.
    return {
        'plant_growth_form': 'tree', 'plant_growth_behaviour': 'rhizomatous_clonal',
        'plant_woodiness': 'woody', 'plant_lifespan': 'perennial',
        'leaf_length': {'typical_m': .65}, 'leaf_attachment_pattern': 'terminal_cluster',
        'plant_shoot_profile': {
            'form': 'terminal_rosette', 'axis_layout': 'basal_clump',
            'axis_height_m': 2., 'axis_radius_m': .075, 'axis_spread_m': .55,
            'leaf_width_m': .008, 'leaf_bend': .3, 'skirt_fraction': .85,
            'elevation_onset': .2, 'peduncle_length_m': 1., 'peduncle_radius_m': .014,
            'panicle_length_m': 1., 'panicle_width_m': .55, 'crown_count': 3,
            'leaves_per_crown': 100, 'dead_leaves_per_crown': 65,
            'panicle_branches': 18, 'flowers_per_branch': 7,
        },
    }


def sim(entity):
    return SpeciesSimulation(species_entity=entity, species_id='synthetic_rosette', seed=303)


def test_canonical_geometry_accounting_and_attachments(entity):
    s = sim(entity)
    snapshots = [s.generate_snapshot(180, lod) for lod in range(3)]
    a = snapshots[2]
    assert a.to_dict() == s.generate_snapshot(180, 2).to_dict()
    assert a.stats['terminal_crown_count'] == 3
    assert a.stats['estimated_leaf_count'] == 300
    assert a.stats['retained_dead_leaf_count'] == 195
    assert sum(c['estimated_leaf_count'] for c in a.leaf_clusters) == 300
    assert a.stats['leaf_area_m2'] == round(sum(c['leaf_area_m2'] for c in a.leaf_clusters), 6)
    for other in snapshots[:2]:
        for key in ('estimated_leaf_count', 'leaf_area_m2', 'structural_axis_length_m'):
            assert other.stats[key] == a.stats[key]
    for i, placement in enumerate(a.placements):
        assert placement[1] < i
        assert placement[1] >= 0 or placement[0] == 'root'
        assert all(math.isfinite(v) for v in placement[2:])
        path = a.placement_paths.get(str(i), [])
        for point in path:
            for axis, v in enumerate(point):
                assert a.bounds_m[axis*2]-.001 <= v <= a.bounds_m[axis*2+1]+.001
    leaf_hosts = {a.placements[i][1] for i, o in a.placement_orientations.items()
                  if o.get('terminal_blade') for i in [int(i)]}
    assert len(leaf_hosts) == 3
    assert len(a.placements) < 1000


def test_crown_topology_and_dead_foliage_are_independent_of_leaf_size(entity):
    one = copy.deepcopy(entity)
    one['plant_shoot_profile']['crown_count'] = 1
    one['plant_shoot_profile']['dead_leaves_per_crown'] = 0
    a, b = sim(one).generate_snapshot(180, 2), sim(entity).generate_snapshot(180, 2)
    assert a.stats['terminal_crown_count'] == 1
    assert a.stats['leaf_area_m2'] == pytest.approx(b.stats['leaf_area_m2']/3, abs=1e-6)
    assert sim(one).blueprint.module('leaf').length_m == sim(entity).blueprint.module('leaf').length_m
    no_skirt = copy.deepcopy(entity)
    no_skirt['plant_shoot_profile']['dead_leaves_per_crown'] = 0
    assert sim(no_skirt).generate_snapshot(180, 2).stats['leaf_area_m2'] == b.stats['leaf_area_m2']
    young = sim(entity).generate_snapshot(1, 2)
    assert young.stats['terminal_crown_count'] == 1
    assert young.stats['terminal_crowns_m'][0][2] < .02
    no_skirt['plant_shoot_profile']['dead_leaves_per_crown'] = 65
    no_skirt['plant_shoot_profile']['skirt_fraction'] = 0
    assert sim(no_skirt).generate_snapshot(180, 2).stats['retained_dead_leaf_count'] == 0


@pytest.mark.parametrize('layout', ['basal_clump', 'forked'])
def test_portable_recipe_and_layouts(entity, layout):
    entity['plant_shoot_profile']['axis_layout'] = layout
    blueprint = PlantBlueprint.from_species_entity(entity, 'synthetic')
    restored = PlantBlueprint.from_dict(json.loads(json.dumps(blueprint.to_dict())))
    assert restored.fingerprint() == blueprint.fingerprint()
    other = copy.deepcopy(entity)
    other['plant_shoot_profile']['leaf_bend'] = .6
    assert PlantBlueprint.from_species_entity(other, 'synthetic').fingerprint() != blueprint.fingerprint()
    snap = sim(entity).generate_snapshot(180, 2)
    assert snap.stats['terminal_crown_count'] == 3
    assert all(p[1] < i for i, p in enumerate(snap.placements))


@pytest.mark.parametrize('key,value', [('crown_count', 0), ('crown_count', True),
    ('leaf_bend', float('nan')), ('axis_height_m', float('inf')),
    ('leaves_per_crown', 10000), ('axis_layout', 'unknown')])
def test_bad_recipes_are_rejected_and_runtime_is_neutral(entity, key, value):
    p = entity['plant_shoot_profile']
    p[key] = value
    assert terminal_rosette_profile(p) is None
    with pytest.raises(AuthoringError):
        validate_updates({'plant_shoot_profile': p})
    assert 'terminal_rosette_version' not in PlantBlueprint.from_species_entity(entity).growth


def test_missing_recipe_preserves_generic_grammar(entity):
    entity.pop('plant_shoot_profile')
    assert 'terminal_rosette_version' not in sim(entity).blueprint.growth


def test_reproductive_organs_share_real_stalk_sockets(entity):
    entity.update(reproductive_mode='both', plant_reproductive_structure='panicle',
        plant_reproductive_profile={'cycle_days': 365., 'flowering_start': .37,
            'fruit_start': .51, 'flowering_end': .54, 'fruit_ripe': .75,
            'fruit_retention_end': .9, 'flower_size_m': .045, 'fruit_size_m': .06,
            'unripe_color': [113, 135, 65], 'ripe_color': [153, 117, 68]})
    s = sim(entity)
    flowers, fruits = s.generate_snapshot(177.75, 2), s.generate_snapshot(280, 2)
    assert flowers.stats['terminal_rosette_flower_count'] > 0
    assert fruits.stats['terminal_rosette_fruit_count'] > 0
    assert fruits.stats['terminal_rosette_flower_count'] == 0
    for snap, organ, sign in ((flowers, 'flower', -1), (fruits, 'fruit', 1)):
        for i, p in enumerate(snap.placements):
            if p[0] == organ:
                assert snap.placements[p[1]][0] == 'branch_section'
                assert snap.placement_orientations[str(i)]['forward'][2] == sign
