"""Persistent underground topology and reversible seasonal shoot cohorts."""
import copy
import json
import math

import pytest

from simulations.species.plant_assets import PlantBlueprint
from simulations.species.seasonal_rhizomes import seasonal_rhizome_profile
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_species import AuthoringError, validate_updates


@pytest.fixture
def entity():
    return {'plant_growth_form': 'forb', 'plant_growth_behaviour': 'rhizomatous_clonal',
        'plant_woodiness': 'herbaceous', 'plant_lifespan': 'perennial', 'plant_life_form': 'geophyte',
        'belowground_storage': ['rhizome'], 'leaf_phenology': 'deciduous',
        'root_architecture': 'adventitious', 'leaf_length': {'typical_m': .08},
        'reproductive_mode': 'both', 'plant_reproductive_structure': 'flower',
        'plant_shoot_profile': {'form': 'seasonal_rhizome', 'rhizome_length_m': .28,
            'rhizome_depth_m': .025, 'rhizome_radius_m': .002, 'shoot_height_m': .18,
            'shoot_radius_m': .001, 'bract_height_fraction': .55, 'petiole_length_m': .012,
            'leaf_width_ratio': 1.1, 'leaf_pitch_deg': 12., 'basal_petiole_length_m': .12,
            'fruit_head_size_m': .012, 'fruit_peduncle_drop': .8, 'rhizome_axes': 2,
            'buds_per_axis': 4, 'bracts_per_shoot': 3, 'basal_leaves_per_bud': 1},
        'plant_reproductive_profile': {'cycle_days': 365., 'flowering_start': .22,
            'fruit_start': .32, 'flowering_end': .36, 'fruit_ripe': .43,
            'fruit_retention_end': .52, 'flower_size_m': .028, 'fruit_size_m': .012,
            'unripe_color': [116, 143, 66], 'ripe_color': [153, 126, 78],
            'leaf_out_start': .12, 'leaf_out_full': .22, 'leaf_fall_start': .42, 'leaf_fall_end': .56}}


def simulate(entity):
    return SpeciesSimulation(species_entity=entity, species_id='synthetic_seasonal_rhizome', seed=303)


def persistent(snapshot):
    return [(i, p) for i, p in enumerate(snapshot.placements)
            if p[0] == 'renewal_bud' or snapshot.placement_orientations[str(i)].get('seasonal_axis_role') == 'rhizome']


def test_shoots_die_back_and_return_without_erasing_rhizomes_or_roots(entity):
    s = simulate(entity)
    spring, summer, next_spring = [s.generate_snapshot(age, 2) for age in (100, 270, 465)]
    assert spring.stats['seasonal_shoot_count'] == 8
    assert summer.stats['seasonal_shoot_count'] == 0
    assert summer.stats['estimated_leaf_count'] == 0
    assert summer.stats['leaf_area_m2'] == 0.
    assert next_spring.stats['seasonal_shoot_count'] == 8
    assert persistent(spring) == persistent(summer) == persistent(next_spring)
    for key in ('rhizome_axis_length_m', 'rhizome_bud_count', 'root_length_m', 'root_depth_m'):
        assert spring.stats[key] == summer.stats[key] == next_spring.stats[key]
    assert s.life_state(270)['phase'] == 'dormant'
    s.set_age(270)
    assert s.get_ecological_outcome()['mortality_risk'] < 1.
    assert not any(p[0] in {'leaf', 'flower', 'fruit'} for p in summer.placements)
    assert not any(o.get('seasonal_axis_role') in {'seasonal_shoot', 'petiole', 'peduncle', 'basal_petiole'}
                   for o in summer.placement_orientations.values())


def test_leaf_accounting_and_reproductive_sockets(entity):
    s = simulate(entity)
    spring, fruit = s.generate_snapshot(100, 2), s.generate_snapshot(145, 2)
    assert spring.stats['estimated_leaf_count'] == 24
    assert spring.stats['seasonal_flower_count'] == 8
    assert fruit.stats['seasonal_fruit_head_count'] == 8
    assert fruit.stats['estimated_leaf_count'] == 32
    assert len(spring.leaf_clusters) == 24
    assert spring.stats['leaf_area_m2'] == round(sum(x['leaf_area_m2'] for x in spring.leaf_clusters), 6)
    for snap in (spring, fruit):
        for p in snap.placements:
            if p[0] in {'flower', 'fruit'}:
                assert snap.placements[p[1]][2:5] == p[2:5]
    assert all(o['forward'][2] < 0 for o in fruit.placement_orientations.values()
               if o.get('seasonal_reproductive_head'))


def test_determinism_bounds_parents_lod_and_transport(entity):
    s = simulate(entity);a = s.generate_snapshot(100, 2)
    assert a.to_dict() == s.generate_snapshot(100, 2).to_dict()
    for i, p in enumerate(a.placements):
        assert p[1] < i
        assert p[1] >= 0 or p[0] == 'root'
        assert all(math.isfinite(x) for x in p[2:])
        for point in a.placement_paths.get(str(i), []):
            for axis, value in enumerate(point):
                assert a.bounds_m[axis*2]-.001 <= value <= a.bounds_m[axis*2+1]+.001
    for lod in (0, 1):
        other = s.generate_snapshot(100, lod)
        for key in ('estimated_leaf_count', 'leaf_area_m2', 'rhizome_axis_length_m', 'root_length_m'):
            assert other.stats[key] == a.stats[key]
    blueprint = PlantBlueprint.from_dict(json.loads(json.dumps(s.blueprint.to_dict())))
    assert blueprint.fingerprint() == s.blueprint.fingerprint()
    assert len(a.placements) < 1000


@pytest.mark.parametrize('key,value', [('rhizome_axes', 0), ('buds_per_axis', True),
    ('rhizome_depth_m', float('nan')), ('shoot_height_m', float('inf')),
    ('bracts_per_shoot', 100), ('fruit_peduncle_drop', -1)])
def test_invalid_authoring_is_rejected_and_runtime_is_neutral(entity, key, value):
    entity['plant_shoot_profile'][key] = value
    assert seasonal_rhizome_profile(entity['plant_shoot_profile']) is None
    with pytest.raises(AuthoringError):
        validate_updates({'plant_shoot_profile': entity['plant_shoot_profile']})
    assert 'seasonal_rhizome_version' not in simulate(entity).blueprint.growth


def test_unknown_and_missing_calendar_are_distinct_from_dormancy(entity):
    entity.pop('plant_reproductive_profile')
    s = simulate(entity);a = s.generate_snapshot(270, 2)
    assert a.stats['seasonal_shoot_count'] == 8
    assert a.stats['seasonal_calendar_status'] == 'unresolved_neutral_active'
    entity['plant_shoot_profile']['form'] = 'other_unknown'
    assert 'seasonal_rhizome_version' not in simulate(entity).blueprint.growth
    entity.pop('plant_shoot_profile')
    assert 'seasonal_rhizome_version' not in simulate(entity).blueprint.growth


def test_reusable_topology_contrast_does_not_resize_individual_leaves(entity):
    a = simulate(entity)
    entity['plant_shoot_profile'].update(rhizome_axes=1, bracts_per_shoot=0, basal_leaves_per_bud=0)
    b = simulate(entity);snapshot = b.generate_snapshot(100, 2)
    assert snapshot.stats['rhizome_bud_count'] == 4
    assert snapshot.stats['estimated_leaf_count'] == 0
    assert b.blueprint.module('leaf').length_m == a.blueprint.module('leaf').length_m
    assert b.blueprint.fingerprint() != a.blueprint.fingerprint()


def test_production_biosim_hides_dormant_shoots_and_restores_spring_picture(entity):
    import pygame
    from types import SimpleNamespace
    from simulations.species.species_renderer import SpeciesRenderer
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view
    pygame.init()
    try:
        s = simulate(entity)
        renderer = SpeciesRenderer(SimpleNamespace())
        bio = BiosphereBuilderRenderer(SimpleNamespace(), species_renderer=renderer)
        scene = SimpleNamespace(world_model=SimpleNamespace(repository_revision=0), world_units_to_meters=1.,
                                get_representative_species_simulation=lambda _rid: s)
        instance = {'species_id': s.species_id, 'representative_id': 'fixture',
                    'abundance': 1., 'visual_scale': 1., 'variant': 0}
        counts = []
        for age in (100, 270, 465):
            s.set_age(age)
            image, _ = bio._render_sprite_surface(scene, instance, SimpleNamespace(zoom=400., sprite_height_cap=84))
            counts.append(pygame.mask.from_surface(image).count())
            if age == 270:
                assert top_view(s) is None
        assert counts[0] > 0 and counts[1] == 0 and counts[2] == counts[0]
    finally:
        pygame.quit()
