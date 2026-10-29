"""Sessile ground cups keep fungal identity, physical sizes and colony state."""
import json
import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot,is_fungal_growth_species_entity
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer,DiagnosticCamera,TopDownDiagnosticCamera,IsometricDiagnosticCamera
from tools.author_plant_assets import load_manifest,render_module,PixelEditorHost
from tools.author_plant_species import validate_updates,AuthoringError
from ui.pixel_art_editor_ui import PixelArtEditorUI
from world.fungal_traits import validate_fungal_profile
from world.world_model import WorldModel

SID='spec_aleuria_aurantia'

def recipe():
    return json.loads(Path(f'assets/species_trait_specs/{SID}.json').read_text())['updates']['fungal_growth_profile']

def grown(age=156.95,lod=2,profile=None,env=None):
    s=SpeciesSimulation(species_entity={'id':'synthetic_soil_cup','fungal_growth_profile':profile or recipe()},seed=303,environment=env)
    s.set_lod(lod);s.set_age(age);return s

def test_saved_fungal_identity_native_assets_and_portability():
    world=WorldModel();raw=world.loader.get(SID)
    assert raw['parents']==['cladis_aleuria']
    assert world.plant_catalogue.is_species(SID) is False
    assert is_fungal_growth_species_entity(raw,world.loader.entities)
    assert raw['fungal_growth_profile']==recipe()
    assert not any(k in raw for k in ['plant_growth_form','plant_leaf_module_ref','plant_flower_module_ref'])
    s=grown();snap=s.render_snapshot
    assert not any(s.blueprint.module(k) for k in ['leaf','root','stem_section','flower','fruit'])
    assert s.blueprint.module('fruiting_body:folded') is None # Synthetic fixture has no asset wiring.
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()
    pygame.init();pygame.display.set_mode((1,1))
    try:
        for module in load_manifest(Path(f'assets/plant_asset_specs/{SID}.json'))['modules']:
            row=world.loader.get(module['illustration_id'])
            assert row['parents']==[SID]
            editor=PixelArtEditorUI(PixelEditorHost(world.loader))
            assert editor.open(row['id'])
            art=pygame.image.load(row['media_path'])
            assert art.get_size()==(75,75)
            assert pygame.image.tobytes(art,'RGBA')==pygame.image.tobytes(render_module(module),'RGBA')
    finally:
        pygame.quit()

@pytest.mark.parametrize('age',[0,66,123.28,139.27,156.95,170,188.88,238.95])
def test_bounded_deterministic_canonical_soil_geometry_at_every_lod(age):
    sims=[grown(age,lod) for lod in range(3)]
    assert sims[2].render_snapshot.to_dict()==grown(age).render_snapshot.to_dict()
    assert sims[0].get_ecological_outcome()==sims[1].get_ecological_outcome()==sims[2].get_ecological_outcome()
    for s in sims:
        snap=s.render_snapshot
        assert len(snap.placements)<=64
        assert snap.stats['root_segment_count']==0 and snap.stats['leaf_area_m2']==0
        for i,p in enumerate(snap.placements):
            assert -1<=p[1]<i
            assert all(math.isfinite(v) for v in p[2:])
            assert p[4]<0 if p[0]=='mycelium' else p[4]==0
        for body in snap.stats['fungal_bodies']:
            assert body['stipe_length_m']==body['stipe_diameter_m']==0
            assert body['cap_socket_m'][2]==0

def test_colony_survives_flushes_and_unknown_nutrition_is_not_a_decay_flux():
    adult,resting,next_flush=grown(),grown(188.88),grown(238.95)
    mycelium=lambda s:[p for p in s.render_snapshot.placements if p[0]=='mycelium']
    assert mycelium(adult)==mycelium(resting)==mycelium(next_flush)
    assert adult.render_snapshot.stats['estimated_fruiting_body_count']==7
    assert resting.render_snapshot.stats['estimated_fruiting_body_count']==0
    assert next_flush.life_state()['flush_index']==1
    for env in [{'fungal_moisture':0},{'fungal_fruiting_enabled':False},{'fungal_ground_substrate':'dead_hardwood'}]:
        assert grown(env=env).render_snapshot.stats['estimated_fruiting_body_count']==0
    eco=adult.get_ecological_outcome()
    assert eco['feeding_mode_status']=='soil_trophic_unknown'
    assert eco['photosynthesis_proxy']==eco['wood_decay_activity_proxy']==0
    assert eco['decomposition_rate_source']=='unknown_no_mass_or_nutrient_flux_implemented'

def test_cluster_spacing_changes_positions_not_sizes_counts_or_ecology():
    clustered=grown();p=recipe();p['visual_calibration']['body_cluster_radius_ratio']=1.
    loose=grown(profile=p)
    assert loose.blueprint.fingerprint()!=clustered.blueprint.fingerprint()
    assert loose.get_ecological_outcome()==clustered.get_ecological_outcome()
    for a,b in zip(clustered.render_snapshot.stats['fungal_bodies'],loose.render_snapshot.stats['fungal_bodies']):
        assert math.hypot(*a['socket_m'][:2])==pytest.approx(math.hypot(*b['socket_m'][:2])*.48)
        assert a['cap_width_m']==b['cap_width_m'] and a['cap_height_m']==b['cap_height_m']
    assert {b['variant_key'] for b in clustered.render_snapshot.stats['fungal_bodies']}=={None,'folded'}
    young=grown(123.28).render_snapshot.stats['fungal_bodies'][0]
    adult=clustered.render_snapshot.stats['fungal_bodies'][0]
    assert young['cap_height_m']/young['cap_width_m']>adult['cap_height_m']/adult['cap_width_m']

@pytest.mark.parametrize('change',[
    {'attachment':'ground_stalked'}, {'substrates':['dead_hardwood']},
    {'feeding_modes':['wood_saprotroph']},
    {'stipe_length':{'min_m':0,'typical_m':.01,'max_m':.02}},
    {'stipe_diameter':{'min_m':False,'typical_m':0,'max_m':0}},
    {'cap_width':{'min_m':.1,'typical_m':.05,'max_m':.02}},
    {'visual_calibration':{'body_count':True}},
    {'visual_calibration':{'body_cluster_radius_ratio':0}},
    {'visual_calibration':{'body_variant_keys':[{}]}},
    {'simulation_calibration':{'flush_cycle_model_days':float('nan')}},
])
def test_invalid_cup_profiles_cannot_be_authored(change):
    p=recipe();p.update(deepcopy(change))
    with pytest.raises(ValueError):validate_fungal_profile(p)
    with pytest.raises(AuthoringError):validate_updates({'fungal_growth_profile':p})

def test_metric_views_and_biosim_consumers_paint_saved_cups():
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view
    pygame.init();pygame.display.set_mode((1,1))
    try:
        s=SpeciesSimulation(world_model=WorldModel(),species_id=SID,seed=303);s.set_age(156.95)
        assert s.blueprint.module('fruiting_cap:folded') is not None
        renderer=SpeciesRenderer(SimpleNamespace(camera=None))
        for cls,bounds in [(DiagnosticCamera,(-.16,.16,-.04,.06)),(TopDownDiagnosticCamera,(-.16,.16,-.16,.16)),(IsometricDiagnosticCamera,[-.16,.16,-.16,.16,-.04,.06])]:
            canvas=pygame.Surface((500,400),pygame.SRCALPHA)
            renderer._draw_individual(canvas,s,camera=cls(500,400,bounds),cache=False,draw_environment=False)
            assert pygame.surfarray.array3d(canvas)[:,:,0].max()>200
        scene=SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),world_units_to_meters=1.,get_representative_species_simulation=lambda _:s)
        item={'species_id':SID,'representative_id':'test','abundance':1.,'visual_scale':1.,'variant':0}
        sprite,anchor=BiosphereBuilderRenderer(SimpleNamespace(),species_renderer=renderer)._render_sprite_surface(scene,item,SimpleNamespace(zoom=400.,sprite_height_cap=84))
        assert sprite.get_bounding_rect().width>0 and all(math.isfinite(v) for v in anchor)
        assert top_view(s).get_bounding_rect().width>0
    finally:
        pygame.quit()
