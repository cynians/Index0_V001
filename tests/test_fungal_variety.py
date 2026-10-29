"""Named paired artwork and colony variation remain stable through growth/LOD."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from simulations.species.fungal_growth import wood_test_fixture
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from tools.author_plant_assets import validate_manifest, ManifestError
from world.fungal_traits import validate_fungal_profile
from world.world_model import WorldModel


def recipe():
    return json.loads(Path('assets/species_trait_specs/spec_trametes_gibbosa.json').read_text())['updates']['fungal_growth_profile']


def grown(age=90,lod=2,seed=303,profile=None):
    sim=SpeciesSimulation(species_entity={'id':'spec_synthetic_varied_bracket','fungal_growth_profile':profile or recipe()},seed=seed)
    sim.set_lod(lod);sim.set_age(age);return sim


@pytest.mark.parametrize('key,value',[
    ('body_variant_keys',[]),('body_variant_keys',['lobed','lobed']),('body_variant_keys',[False]),
    ('body_variant_keys',['../../file']),('cap_width_scale_range',[1.4,.55]),
    ('cap_width_scale_range',[False,1]),('cap_width_scale_range',[.2,3]),
    ('body_cluster_count',True),('body_cluster_count',0),('body_cluster_count',2.5)])
def test_invalid_variation_controls_are_rejected(key,value):
    p=recipe();p['visual_calibration'][key]=value
    with pytest.raises(ValueError):validate_fungal_profile(p)


def test_pairing_and_distinct_manifest_ids_required_for_variants():
    manifest=json.loads(Path('assets/plant_asset_specs/spec_trametes_gibbosa.json').read_text())
    validate_manifest(manifest)
    broken=deepcopy(manifest);broken['modules'].pop()
    with pytest.raises(ManifestError,match='paired'):validate_manifest(broken)
    broken=deepcopy(manifest);broken['modules'].append(deepcopy(broken['modules'][2]))
    with pytest.raises(ManifestError,match='Duplicate'):validate_manifest(broken)
    broken=deepcopy(manifest);broken['modules'][2]['variant_key']='../bad'
    with pytest.raises(ManifestError,match='variant_key'):validate_manifest(broken)


def test_variant_and_socket_identity_are_stable_through_age_and_lod():
    adult=grown().render_snapshot
    assert {b['variant_key'] for b in adult.stats['fungal_bodies']}=={'default','kidney','lobed','thick'}
    assert len({round(b['cap_width_m'],4) for b in adult.stats['fungal_bodies']})==6
    assert adult.to_dict()==grown().render_snapshot.to_dict()
    assert adult.to_dict()!=grown(seed=304).render_snapshot.to_dict()
    lookup={b['id']:b for b in adult.stats['fungal_bodies']}
    for age in (35,60,90,108):
        sims=[grown(age,lod) for lod in range(3)]
        assert sims[0].get_ecological_outcome()==sims[1].get_ecological_outcome()==sims[2].get_ecological_outcome()
        assert sims[0].render_snapshot.bounds_m==sims[1].render_snapshot.bounds_m==sims[2].render_snapshot.bounds_m
        for sim in sims:
            for body in sim.render_snapshot.stats['fungal_bodies']:
                mature=lookup[body['id']]
                assert body['variant_key']==mature['variant_key']
                assert body['socket_m']==mature['socket_m']
                assert body['cap_width_m']<=mature['cap_width_m']
                assert body['stipe_length_m']==0
            assert PlantGrowthSnapshot.from_dict(sim.render_snapshot.to_dict()).to_dict()==sim.render_snapshot.to_dict()


def test_grouping_and_size_controls_are_independent_of_colony_and_body_count():
    p=recipe();p['visual_calibration'].pop('body_cluster_count')
    plain=grown(profile=p).render_snapshot;grouped=grown().render_snapshot
    assert [b['socket_m'] for b in plain.stats['fungal_bodies']]!=[b['socket_m'] for b in grouped.stats['fungal_bodies']]
    assert plain.stats['estimated_fruiting_body_count']==grouped.stats['estimated_fruiting_body_count']==6
    assert plain.stats['colonised_wood_volume_proxy_m3']==grouped.stats['colonised_wood_volume_proxy_m3']
    p=recipe();p['visual_calibration']['cap_width_scale_range']=[1,1]
    uniform=grown(profile=p).render_snapshot
    assert {round(b['cap_width_m'],6) for b in uniform.stats['fungal_bodies']}=={.12}


def test_saved_variant_modules_are_portable_and_artwork_does_not_change_ecology():
    world=WorldModel();entity=world.resolved_species_entity('spec_trametes_gibbosa')
    sim=SpeciesSimulation(species_entity=entity,seed=303);sim.set_age(90)
    assert len(sim.blueprint.modules)==9
    assert PlantBlueprint.from_dict(sim.blueprint.to_dict()).fingerprint()==sim.blueprint.fingerprint()
    for key in ('kidney','lobed','thick'):
        for role in ('fruiting_body','fruiting_cap'):
            assert sim.blueprint.module(f'{role}:{key}').asset_ref
    missing=deepcopy(entity)
    missing.pop('fungal_body_module_ref');missing.pop('fungal_cap_module_ref');missing['fungal_module_anchors']={}
    other=SpeciesSimulation(species_entity=missing,seed=303);other.set_age(90)
    assert sim.render_snapshot.stats==other.render_snapshot.stats
    assert sim.get_ecological_outcome()==other.get_ecological_outcome()


def test_editing_variant_preserves_base_reference_and_other_views():
    from ui.knowledge_browser_ui import KnowledgeBrowserUI
    world=WorldModel();parent=deepcopy(world.loader.get('spec_trametes_gibbosa'))
    original=deepcopy(parent);saved=[]
    browser=KnowledgeBrowserUI.__new__(KnowledgeBrowserUI)
    browser.world_model=SimpleNamespace();browser.cards=[]
    browser._parent_entity_for_illustration=lambda _:parent
    browser._persist_entity_to_repository=lambda e:saved.append(deepcopy(e))
    browser._build_browser_items=lambda _:[];browser._relayout_cards=lambda:None
    assert browser.assign_plant_asset_to_parent({'plant_asset_target_field':'fungal_body_module_ref',
        'plant_asset_variant':'lobed','media_path':'assets/fixture_lobed.png','depicted_size_m':.12,
        'pixel_module_anchor':{'attachment_point':[.1,.5],'growth_axis':[1,0]}})
    after=saved[-1]
    assert after['fungal_body_module_ref']==original['fungal_body_module_ref']
    assert after['fungal_module_anchors']['fruiting_body']['variants']['lobed']['asset_ref']=='assets/fixture_lobed.png'
    assert after['fungal_module_anchors']['fruiting_cap']==original['fungal_module_anchors']['fruiting_cap']
    variants=deepcopy(after['fungal_module_anchors']['fruiting_body']['variants'])
    assert browser.assign_plant_asset_to_parent({'plant_asset_target_field':'fungal_body_module_ref',
        'media_path':'assets/fixture_base.png','depicted_size_m':.12,
        'pixel_module_anchor':{'attachment_point':[.1,.5],'growth_axis':[1,0]}})
    assert saved[-1]['fungal_module_anchors']['fruiting_body']['variants']==variants


def test_renderer_uses_corresponding_named_views_for_each_body():
    import pygame
    from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, TopDownDiagnosticCamera, top_down_diagnostic_bounds
    pygame.init();pygame.display.set_mode((1,1))
    try:
        world=WorldModel();sim=SpeciesSimulation(world_model=world,species_id='spec_trametes_gibbosa',seed=303)
        sim.set_age(90);sim.set_lod(2)
        renderer=SpeciesRenderer(SimpleNamespace(camera=None));original=renderer._module_asset;requests=[]
        def record(simulation,role):
            requests.append(role);return original(simulation,role)
        renderer._module_asset=record
        for prefix,camera in (('fruiting_body',DiagnosticCamera(600,600,(-.6,.6,-.1,1.4))),
                              ('fruiting_cap',TopDownDiagnosticCamera(600,600,top_down_diagnostic_bounds(sim)))):
            requests.clear()
            surface=pygame.Surface((600,600),pygame.SRCALPHA)
            renderer._draw_individual(surface,sim,camera=camera,cache=False,clear=False,draw_environment=False)
            assert set(requests)=={prefix,f'{prefix}:kidney',f'{prefix}:lobed',f'{prefix}:thick'}
            bbox=surface.get_bounding_rect()
            assert bbox.left>0 and bbox.top>0 and bbox.right<600 and bbox.bottom<600
    finally:
        pygame.quit()
