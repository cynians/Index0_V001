"""Spruce composition and responsive, precisely attached conifer whorls."""
import gzip
import json
import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import pygame
import pytest
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.species_renderer import SpeciesRenderer,DiagnosticCamera,diagnostic_cell_bounds
from simulations.species.pendant_reproduction import pendant_geometry
from world.world_model import WorldModel
from world.plant_catalogue import PlantCatalogue
from tools.author_plant_assets import load_manifest,render_module,PixelEditorHost,PixelArtEditorUI

ROOT=Path(__file__).resolve().parents[1];SID='spec_picea_obovata'
def entity():
    return {'id':'spec_unrelated_synthetic_conifer',**deepcopy(json.loads((ROOT/f'assets/species_trait_specs/{SID}.json').read_text())['updates'])}
def grown(e=None,age=500,lod=2):
    s=SpeciesSimulation(species_entity=e or entity(),seed=303);s.set_lod(lod);s.set_age(age);return s
def sockets(s):return [a for a in s.render_snapshot.attachment_points if a.get('socket')=='interpolated_whorl']

def test_live_composition_and_editable_assets():
    w=WorldModel();e=w.resolved_species_entity(SID)
    assert PlantCatalogue.build(w.loader.entities).is_species(SID)
    assert e['parents']==['cladis_spruces_picea']
    s=SpeciesSimulation(world_model=w,species_id=SID,seed=303);s.set_age(500)
    assert s.blueprint.growth['branching_subpattern_version']==2
    assert s.blueprint.module('leaf').length_m==.018
    assert s.blueprint.module('leaf').radius_m==.001
    assert s.blueprint.growth['leaf_arrangement']=='spiral'
    assert all(c.get('fascicle_size',0)==0 for c in s.render_snapshot.leaf_clusters)
    assert e['plant_module_anchors']['leaf']['depicted_size_m']==.1
    assert s.blueprint.growth['reproductive_structure']=='cone'
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(s.render_snapshot.to_dict()).to_dict()==s.render_snapshot.to_dict()
    pygame.init();pygame.display.set_mode((1,1))
    m=load_manifest(ROOT/f'assets/plant_asset_specs/{SID}.json')
    assert len(m['modules'])==5
    for module in m['modules']:
        illustration=w.loader.get(module['illustration_id'])
        with gzip.open(ROOT/illustration['pixel_document_path'],'rt',encoding='utf8') as f:assert json.load(f)['version']==2
        editor=PixelArtEditorUI(PixelEditorHost(w.loader));assert editor.open(illustration['id']) and editor.begin_canvas()
        assert pygame.image.tobytes(pygame.image.load(ROOT/illustration['media_path']),'RGBA')==pygame.image.tobytes(render_module(module),'RGBA')
    renderer=SpeciesRenderer(SimpleNamespace(camera=DiagnosticCamera(800,650,diagnostic_cell_bounds(s.render_snapshot))))
    for mode in ('individual','top_down','editor'):
        assert s.set_active_simulation_panel_tab(mode);renderer.draw(pygame.Surface((1500,950)),s)
    pygame.quit()

def test_density_changes_actual_whorls_not_only_branches_at_old_heights():
    values=[]
    for density in (.2,.6,1.):
        e=entity();e['plant_primary_branch_density']={'min':density,'typical':density,'max':density}
        s=grown(e);a=sockets(s);heights={round(x['position_m'][2],5) for x in a}
        values.append((len(a),len(heights)))
        assert len(a)<=96
        assert len(a)==len(heights)*3
        for socket in a:
            path=s.render_snapshot.placement_paths[str(socket['placement_index'])]
            assert math.dist(path[0],socket['position_m'])<.0002
        assert s.render_snapshot.to_dict()==grown(e).render_snapshot.to_dict()
    assert values[0][0]<values[1][0]<values[2][0]
    assert values[0][1]<values[1][1]<values[2][1]

@pytest.mark.parametrize('age',[35,120,500,635])
def test_lod_and_ecological_canonical_quantities(age):
    sims=[grown(age=age,lod=i) for i in range(3)]
    for k in ('estimated_leaf_count','leaf_area_m2','structural_axis_length_m','conifer_primary_axis_count','conifer_tier_count'):
        assert len({s.render_snapshot.stats[k] for s in sims})==1
    assert sims[0].get_ecological_outcome()==sims[2].get_ecological_outcome()
    for s in sims:
        snap=s.render_snapshot;assert len(snap.placements)<18000
        for i,p in enumerate(snap.placements):
            assert p[1]==-1 or 0<=p[1]<i
            assert all(math.isfinite(v) for v in p[2:7])

def test_missing_and_zero_keep_established_geometry():
    e=entity();e.pop('plant_primary_branch_density')
    a=grown(e);e['plant_primary_branch_density']={'min':0.,'typical':0.,'max':0.};b=grown(e)
    assert a.render_snapshot.placements==b.render_snapshot.placements
    assert a.render_snapshot.placement_paths==b.render_snapshot.placement_paths
    assert not sockets(a) and not sockets(b)
    assert a.blueprint.growth['branching_subpattern_version']==1

@pytest.mark.parametrize('width',[0,True,float('nan'),.3])
def test_invalid_optional_leaf_width_is_neutral(width):
    from simulations.species.woody_axes import woody_axes_profile
    p=entity()['plant_shoot_profile'];p['leaf_width_m']=width
    assert woody_axes_profile(p) is None

def test_mature_cones_hang_and_unknown_roots_remain_unresolved():
    s=grown(age=635);snap=s.render_snapshot
    cones=[x for x in snap.placements if x[0]=='fruit'];assert cones
    for p in cones[:10]:
        anchor,tip=pendant_geometry(s.blueprint.growth,p,s.blueprint.module('fruit'))
        assert tip[2]<anchor[2]<p[4]
    assert not any(p[0]=='root_section' for p in snap.placements)
    assert snap.stats['root_model_status']=='unresolved'

def test_biosim_grounded_sprite_and_top_map():
    from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
    from simulations.biosphere.plant_pictures import top_view
    pygame.init();pygame.display.set_mode((1,1));s=grown()
    scene=SimpleNamespace(world_model=SimpleNamespace(repository_revision=0),world_units_to_meters=1.,get_representative_species_simulation=lambda _:s)
    item={'species_id':SID,'representative_id':'fixture','abundance':1.,'visual_scale':1.,'variant':0}
    renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    art,_=BiosphereBuilderRenderer(SimpleNamespace(),species_renderer=renderer)._render_sprite_surface(scene,item,SimpleNamespace(zoom=400.,sprite_height_cap=84))
    assert pygame.mask.from_surface(art).count()>0
    assert top_view(s) is not None
    pygame.quit()
