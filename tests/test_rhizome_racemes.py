"""Seasonal patch persistence, ascending flowering and physical organ transport."""
import gzip
import json
import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pygame
import pytest
from simulations.species.rhizome_racemes import rhizome_raceme_profile, raceme_stage
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_renderer import SpeciesRenderer, DiagnosticCamera, diagnostic_cell_bounds
from world.world_model import WorldModel
from world.plant_catalogue import PlantCatalogue
from tools.author_plant_assets import load_manifest, render_module, PixelArtEditorUI, PixelEditorHost

ROOT=Path(__file__).resolve().parents[1]; SID='spec_chamaenerion_angustifolium'

def entity():
    return {'id':'spec_unrelated_test_fixture',**deepcopy(json.loads((ROOT/f'assets/species_trait_specs/{SID}.json').read_text())['updates'])}

def grown(age=156.95,lod=2,changes=None):
    e=entity(); e.update(changes or {})
    s=SpeciesSimulation(species_entity=e,seed=303);s.set_lod(lod);s.set_age(age);return s

def test_live_identity_saved_assets_and_serialization():
    w=WorldModel();e=w.resolved_species_entity(SID)
    assert PlantCatalogue.build(w.loader.entities).is_species(SID)
    assert e['parents']==['cladis_fireweeds_chamaenerion']
    s=SpeciesSimulation(world_model=w,species_id=SID,seed=303);s.set_age(156.95)
    assert s.blueprint.growth['rhizome_raceme_profile']['raceme_nodes']==28
    assert s.blueprint.module('flower').length_m==.035
    assert s.blueprint.module('fruit').length_m==.06
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(s.render_snapshot.to_dict()).to_dict()==s.render_snapshot.to_dict()
    pygame.init();pygame.display.set_mode((1,1))
    manifest=load_manifest(ROOT/f'assets/plant_asset_specs/{SID}.json')
    for module in manifest['modules']:
        illustration=w.loader.get(module['illustration_id'])
        with gzip.open(ROOT/illustration['pixel_document_path'],'rt',encoding='utf8') as f: assert json.load(f)['version']==2
        editor=PixelArtEditorUI(PixelEditorHost(w.loader));assert editor.open(illustration['id']) and editor.begin_canvas()
        actual=pygame.image.load(ROOT/illustration['media_path'])
        assert pygame.image.tobytes(actual,'RGBA')==pygame.image.tobytes(render_module(module),'RGBA')
    renderer=SpeciesRenderer(SimpleNamespace(camera=DiagnosticCamera(800,600,diagnostic_cell_bounds(s.render_snapshot))))
    for mode in ('individual','top_down','editor','gallery'):
        assert s.set_active_simulation_panel_tab(mode);renderer.draw(pygame.Surface((1500,950)),s)
    pygame.quit()

@pytest.mark.parametrize('age',[0,35,80,117,156.95,226,343,521.95])
def test_canonical_lod_determinism_geometry_and_bounds(age):
    sims=[grown(age,lod) for lod in range(3)]
    assert sims[2].render_snapshot.to_dict()==grown(age).render_snapshot.to_dict()
    for k in ('leaf_area_m2','estimated_leaf_count','raceme_flower_count','raceme_capsule_count','structural_axis_length_m'):
        assert len({s.render_snapshot.stats[k] for s in sims})==1
    assert sims[0].get_ecological_outcome()==sims[2].get_ecological_outcome()
    for s in sims:
        snap=s.render_snapshot;assert len(snap.placements)<2500
        for i,p in enumerate(snap.placements):
            assert p[1]==-1 or 0<=p[1]<i
            assert all(math.isfinite(v) for v in p[2:7])
        assert all(math.isfinite(v) for v in snap.bounds_m)

def test_flowers_move_upward_capsules_below_and_rhizomes_survive():
    young,mixed,late,winter,next_year=[grown(t) for t in (117,156.95,226,343,521.95)]
    mean=lambda s:sum(x['rank'] for r in s.render_snapshot.stats['raceme_shoots'] for x in r['reproductive_organs'] if x['stage']=='flower')/s.render_snapshot.stats['raceme_flower_count']
    assert mean(mixed)>mean(young)
    for r in mixed.render_snapshot.stats['raceme_shoots']:
        fruits=[o['rank'] for o in r['reproductive_organs'] if o['stage']=='fruit']
        flowers=[o['rank'] for o in r['reproductive_organs'] if o['stage']=='flower']
        assert max(fruits)<min(flowers)
    assert late.render_snapshot.stats['raceme_flower_count']==0
    assert late.render_snapshot.stats['raceme_capsule_count']==140
    assert winter.render_snapshot.stats['estimated_leaf_count']==0
    def rhizomes(s):
        return [(i,p) for i,p in enumerate(s.render_snapshot.placements) if p[0]=='branch_section']
    assert rhizomes(mixed)==rhizomes(winter)==rhizomes(next_year)
    assert next_year.render_snapshot.stats['raceme_flower_count']==mixed.render_snapshot.stats['raceme_flower_count']

@pytest.mark.parametrize('change',[{'leaf_nodes':True},{'shoot_count':0},{'raceme_nodes':1000},{'rhizome_depth_m':float('nan')},{'flower_size_m':0}])
def test_invalid_recipe_neutral(change):
    p=entity()['plant_shoot_profile'];p.update(change)
    assert rhizome_raceme_profile(p) is None

def test_missing_season_or_asexual_mode_cannot_invent_reproduction():
    for c in ({'plant_reproductive_profile':{}},{'reproductive_mode':'vegetative'}):
        s=grown(changes=c)
        assert s.render_snapshot.stats['raceme_flower_count']==0
        assert s.render_snapshot.stats['raceme_capsule_count']==0
    a=grown();p=entity()['plant_shoot_profile'];p['shoot_count']=2
    b=grown(changes={'plant_shoot_profile':p})
    assert b.render_snapshot.stats['shoot_count']==2
    assert b.render_snapshot.stats['leaf_area_m2']<a.render_snapshot.stats['leaf_area_m2']
    assert b.blueprint.fingerprint()!=a.blueprint.fingerprint()

def test_biosim_grounded_and_map_transport():
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view
    pygame.init();pygame.display.set_mode((1,1));s=grown()
    scene=SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),world_units_to_meters=1.,get_representative_species_simulation=lambda _:s)
    item={'species_id':SID,'representative_id':'fixture','abundance':1.,'visual_scale':1.,'variant':0}
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    art,anchor=BiosphereBuilderRenderer(SimpleNamespace(),species_renderer=renderer)._render_sprite_surface(scene,item,SimpleNamespace(zoom=400.,sprite_height_cap=84))
    assert pygame.mask.from_surface(art).count()>0
    assert top_view(s) is not None
    pygame.quit()
