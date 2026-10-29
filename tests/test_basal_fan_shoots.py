import math
from copy import deepcopy
from pathlib import Path

import pygame

from simulations.species.basal_fan_shoots import basal_fan_profile
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_editor import PREVIEW_AFFECTING_FIELDS
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera
from tools.author_plant_assets import load_manifest, render_module, canvas_size
from tools.author_plant_species import validate_updates


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'assets/plant_asset_specs/spec_codonorhiza_elandsmontana.json'


def fixture(**changes):
    # An unrelated identity exercises a portable recipe, without live state.
    updates = deepcopy(load_manifest(MANIFEST)['species_field_updates'])
    return dict(id='spec_synthetic_sparse_fan', plant_growth_form='forb',
                plant_growth_behaviour='determinate_sympodial', plant_woodiness='herbaceous',
                plant_lifespan='perennial', reproductive_mode='sexual',
                plant_flowering_position='terminal', **updates, **changes)


def simulation(entity=None):
    sim = SpeciesSimulation(species_entity=entity or fixture(), seed=303)
    sim.set_age(167.75)
    return sim


def test_manifest_transport_and_physical_dimensions():
    manifest = load_manifest(MANIFEST)
    validate_updates(manifest['species_field_updates'])
    assert 'plant_shoot_profile' in PREVIEW_AFFECTING_FIELDS
    sim = simulation()
    assert sim.blueprint.growth['max_height_m'] == .21
    assert sim.blueprint.module('leaf').length_m == .18
    assert sim.blueprint.module('leaf').radius_m == .006
    assert sim.blueprint.module('flower').length_m == .030
    assert sim.blueprint.module('fruit').length_m == .005
    pygame.init()
    for module in manifest['modules']:
        sprite = render_module(module)
        assert sprite.get_size() == canvas_size(module['depicted_size_m']) == (75,75)
        assert sprite.get_bounding_rect().width > 0


def test_sparse_leaf_sockets_and_flat_flowering_envelope():
    snap = simulation().render_snapshot
    basal = [a for a in snap.attachment_points if a.get('cohort') == 'basal_leaf']
    cauline = [a for a in snap.attachment_points if a.get('cohort') == 'cauline_leaf']
    assert len(basal) == len(cauline) == 1
    assert snap.stats['estimated_leaf_count'] == 2
    a,b = (snap.placements[items[0]['leaf_placement_index']] for items in (basal,cauline))
    assert a[4] < .01 and .07 < b[4] < .12
    assert b[6] < a[6]
    assert b[2:5] == snap.placements[b[1]][2:5]
    flowers = [p for p in snap.placements if p[0] == 'flower']
    assert len(flowers) == 14
    assert max(p[4] for p in flowers)-min(p[4] for p in flowers) < .02
    assert all(snap.placements[p[1]][0] == 'branch_section' for p in flowers)


def test_development_replaces_flowers_with_capsules():
    sim = simulation()
    snaps = [sim.generate_snapshot(age_days=age,lod=2) for age in (0,12,54,167.75,220,250)]
    assert snaps[0].stats['estimated_leaf_count'] == 0
    assert snaps[1].stats['leaf_area_m2'] < snaps[2].stats['leaf_area_m2']
    assert not any(p[0] in {'flower','fruit'} for p in snaps[2].placements)
    assert snaps[3].stats['sympodial_flower_count'] == 14
    assert snaps[3].stats['sympodial_fruit_count'] == 0
    assert 0 < snaps[4].stats['sympodial_flower_count'] < 14
    assert snaps[5].stats['sympodial_flower_count'] == 0
    assert snaps[5].stats['sympodial_fruit_count'] == 14
    for snap in snaps:
        for parent in {p[1] for p in snap.placements if p[0] == 'flower'}:
            assert not any(p[0] == 'fruit' and p[1] == parent for p in snap.placements)


def test_graph_determinism_round_trips_and_lod_ecology():
    sim = simulation()
    assert sim.render_snapshot.to_dict() == simulation().render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(sim.blueprint.to_dict()).to_dict() == sim.blueprint.to_dict()
    snap = sim.render_snapshot
    assert abs(sum(c['leaf_area_m2'] for c in snap.leaf_clusters)-snap.stats['leaf_area_m2']) < .0000011
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict() == snap.to_dict()
    for i,p in enumerate(snap.placements):
        assert p[1] == -1 or 0 <= p[1] < i
        assert all(math.isfinite(v) for v in p[2:7])
    quantities = []
    outcomes = []
    for lod in (0,1,2):
        sim.render_snapshot = sim.generate_snapshot(lod=lod)
        quantities.append(tuple(sim.render_snapshot.stats[k] for k in
            ('estimated_leaf_count','leaf_area_m2','structural_axis_length_m')))
        outcomes.append(sim.get_ecological_outcome()['resource_demand'])
    assert quantities[0] == quantities[1] == quantities[2]
    assert outcomes[0] == outcomes[1] == outcomes[2]


def test_invalid_or_unselected_recipe_preserves_legacy():
    for change in ({'branch_count':0},{'branch_count':10000}, {'basal_leaf_count':True},
                   {'leaf_width_m':float('nan')},{'form':'unknown'}):
        profile = {**fixture()['plant_shoot_profile'], **change}
        assert basal_fan_profile(profile) is None
        entity=fixture();entity['plant_shoot_profile']=profile
        assert 'basal_fan_profile' not in simulation(entity).blueprint.growth
    for key,value in (('plant_growth_form','shrub'),('plant_woodiness','woody'),
                      ('leaf_attachment_pattern','other_unknown')):
        entity=fixture();entity[key]=value
        assert 'basal_fan_profile' not in simulation(entity).blueprint.growth
    for mode in ('vegetative','other_unknown'):
        entity=fixture();entity['reproductive_mode']=mode
        assert not any(p[0] in {'flower','fruit'} for p in simulation(entity).render_snapshot.placements)


def test_recipe_changes_fingerprint_and_supports_another_sparse_fan():
    first = simulation()
    entity=fixture();entity['id']='spec_unrelated_three_leaved_fan'
    entity['plant_shoot_profile']['basal_leaf_count']=2
    entity['plant_shoot_profile']['branch_count']=9
    second=simulation(entity)
    assert second.render_snapshot.stats['estimated_leaf_count'] == 3
    assert second.blueprint.fingerprint() != first.blueprint.fingerprint()
    assert second.render_snapshot.stats['sympodial_flower_count'] == 20
    for p in second.render_snapshot.placements:
        if p[0] in {'stem_section','branch_section'}:
            assert second.render_snapshot.placements[p[1]][0] not in {'leaf','flower','fruit'}


def test_render_uses_projected_leaf_pose_and_preserves_zoomed_metric_length():
    from types import SimpleNamespace
    entity=fixture()
    entity['plant_leaf_module_ref']='preview_test_leaf'
    entity['plant_module_anchors']={'leaf':{'attachment_point':[.5,1.], 'growth_axis':[0.,-1.]}}
    sim=simulation(entity)
    pygame.init()
    sprite=pygame.Surface((5,75),pygame.SRCALPHA);sprite.fill((40,110,40))
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    renderer._module_asset=lambda *args: sprite
    # A 0.18 m blade in a 0.40 m-wide 1000 px camera exceeds the legacy
    # 180 px cap. Check actual painted extent, not a copy of the formula.
    screen=pygame.Surface((1000,1000),pygame.SRCALPHA)
    camera=DiagnosticCamera(1000,1000,(-.2,.2,-.05,.35))
    renderer._draw_module_asset(screen,sim,camera,'leaf',(500,800),0.,1.)
    assert screen.get_bounding_rect().height > 300
