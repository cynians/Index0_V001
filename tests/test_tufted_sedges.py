"""Explicit sedge architecture remains portable, bounded and phase-stable."""
import copy,json,math
from pathlib import Path
import pygame
import pytest
from simulations.species.tufted_sedges import tufted_sedge_profile,draw_blade_asset
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from tools.author_plant_species import validate_updates,AuthoringError
from tools.author_plant_assets import load_manifest,render_module,PixelEditorHost
from ui.pixel_art_editor_ui import PixelArtEditorUI
from world.world_model import WorldModel

SID='spec_cyperus_polystachyos'
def recipe():
    e={'id':'unrelated_metric_sedge','plant_growth_form':'graminoid','plant_growth_behaviour':'tussock_tillering',
       'plant_woodiness':'herbaceous','plant_lifespan':'short_lived_perennial','leaf_attachment_pattern':'basal_tuft',
       'plant_leaf_distribution':'basal_tuft','plant_reproductive_structure':'digitate_spike_cluster',
       'reproductive_mode':'sexual','mature_height':{'max_m':.7}}
    e.update(json.loads(Path(f'assets/species_trait_specs/{SID}.json').read_text())['updates']);return e
def grown(age=178,lod=2,e=None):
    s=SpeciesSimulation(species_entity=e or recipe(),seed=303);s.set_lod(lod);s.set_age(age);return s

@pytest.mark.parametrize('key,value',[('culm_count',0),('culm_count',99),('ray_count',1.5),('leaf_width_m',float('nan')),
    ('bract_count',True),('ray_length_m',-.1),('spikelet_length_m',float('inf')),('spikelet_width_m',.02),
    ('cluster_spread_deg',float('nan')),('cluster_spread_deg',80)])
def test_bad_recipes_rejected_and_runtime_unresolved(key,value):
    p=recipe()['plant_shoot_profile'];p[key]=value
    assert tufted_sedge_profile(p) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_shoot_profile':p})

@pytest.mark.parametrize('key,value',[('plant_growth_form','forb'),('plant_growth_behaviour','iterative_indeterminate'),
     ('plant_woodiness','woody'),('leaf_attachment_pattern','along_stem'),('plant_reproductive_structure','spike')])
def test_body_plan_gates_preserve_legacy_path(key,value):
    e=recipe();e[key]=value
    assert not grown(e=e).blueprint.growth.get('tufted_sedge_version')

def test_canonical_units_geometry_and_ecology_are_portable_across_lod():
    s=grown();a=s.render_snapshot
    assert a.to_dict()==grown().render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(a.to_dict()).to_dict()==a.to_dict()
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert a.stats['basal_blade_count']==24 and a.stats['involucral_bract_count']==24
    assert a.stats['spikelet_cluster_count']==24 and a.stats['flower_spikelet_count']==408
    assert a.stats['estimated_leaf_count']==48
    for i,p in enumerate(a.placements):assert -1<=p[1]<i and all(math.isfinite(v) for v in p[2:])
    for key in ['estimated_leaf_count','leaf_area_m2','flower_spikelet_count','spikelet_cluster_count','root_length_m']:
        assert len({grown(lod=l).render_snapshot.stats[key] for l in range(3)})==1
    assert len({json.dumps(grown(lod=l).get_ecological_outcome(),sort_keys=True) for l in range(3)})==1
    assert all(s.blueprint.module(k).asset_ref is None for k in ['leaf','flower','fruit'])

def test_flower_fruit_and_vegetative_phases_preserve_fertile_axes_and_blades():
    samples=[grown(a) for a in [45,178,270,350]]
    assert [s.render_snapshot.stats['flower_spikelet_count'] for s in samples]==[0,408,0,0]
    assert [s.render_snapshot.stats['fruit_spikelet_count'] for s in samples]==[0,0,408,0]
    assert samples[1].life_state()['phenology_source'].startswith('qualitative')
    for s in samples:
        structural=[[p[0],*p[2:5]] for p in s.render_snapshot.placements if p[0] in ['stem_section','branch_section','leaf']]
        assert structural==[[p[0],*p[2:5]] for p in samples[0].render_snapshot.placements if p[0] in ['stem_section','branch_section','leaf']]
    zero=grown(0);assert zero.render_snapshot.stats['estimated_leaf_count']==0
    assert zero.render_snapshot.stats['flower_spikelet_count']==0
    e=recipe();e['reproductive_mode']='vegetative';assert grown(e=e).render_snapshot.stats['flower_spikelet_count']==0
    e['reproductive_mode']='other_unknown';assert grown(e=e).render_snapshot.stats['flower_spikelet_count']==0
    e=recipe();e['plant_lifespan']='annual'
    assert grown(178,e=e).render_snapshot.stats['flower_spikelet_count']==408
    assert grown(600,e=e).life_state()['phase']=='dead'
    # Other short-lived perennial recipes still use their original clock.
    e=recipe();e.pop('plant_shoot_profile')
    assert 'phenology_source' not in grown(e=e).life_state()

def test_metric_controls_change_counts_widths_and_fingerprint_without_species_ids():
    s=grown();e=recipe();e['plant_shoot_profile']['ray_count']=0
    other=grown(e=e);assert other.render_snapshot.stats['spikelet_cluster_count']==6
    assert other.render_snapshot.stats['flower_spikelet_count']==102
    assert other.blueprint.fingerprint()!=s.blueprint.fingerprint()
    e['plant_shoot_profile']['leaf_width_m']=.005
    assert grown(e=e).render_snapshot.stats['leaf_area_m2']>other.render_snapshot.stats['leaf_area_m2']
    e=recipe();e['plant_shoot_profile']['ray_count']=8;e['plant_shoot_profile']['spikelets_per_cluster']=30;e['plant_shoot_profile']['culm_count']=12
    a=grown(e=e).render_snapshot
    assert a.stats['flower_spikelet_count']==3240 and len(a.placements)<7500

def test_fascicles_follow_ray_axes_and_spread_control_changes_angle_without_new_organs():
    def angles(sim):
        result=[]
        for hint in sim.render_snapshot.placement_orientations.values():
            if hint.get('visual_unit')!='spikelet':continue
            dot=sum(a*b for a,b in zip(hint['forward'],hint['cluster_axis']))
            result.append(math.degrees(math.acos(max(-1.,min(1.,dot)))))
        return result
    e=recipe();e['plant_shoot_profile']['cluster_spread_deg']=5
    tight=grown(e=e);e['plant_shoot_profile']['cluster_spread_deg']=45;open_=grown(e=e)
    assert len(angles(tight))==len(angles(open_))==408
    assert max(angles(tight))<=5 and max(angles(open_))>40
    assert tight.blueprint.fingerprint()!=open_.blueprint.fingerprint()
    assert tight.render_snapshot.stats['leaf_area_m2']==open_.render_snapshot.stats['leaf_area_m2']
    assert tight.render_snapshot.placement_paths==open_.render_snapshot.placement_paths
    assert 'tufted_sedge_version' not in grown(e={**recipe(),'plant_shoot_profile':{}}).blueprint.growth
    # Palette/phenology changes preserve not just bases but spikelet axes.
    flower=grown(178).render_snapshot;fruit=grown(270).render_snapshot
    poses=lambda snap:[(p[2:5],snap.placement_orientations[str(i)]['forward'])
                       for i,p in enumerate(snap.placements) if p[0] in {'flower','fruit'}]
    assert poses(flower)==poses(fruit)

def test_authored_blade_preserves_palette_width_and_neutral_missing_asset():
    pygame.init();source=pygame.Surface((3,30),pygame.SRCALPHA);source.fill((85,120,35,255))
    out=pygame.Surface((250,250),pygame.SRCALPHA)
    assert draw_blade_asset(out,source,[(120,220),(140,120),(160,20)],3)
    assert out.get_bounding_rect().height>190 and out.get_bounding_rect().width<60
    assert source.get_at((1,1))==(85,120,35,255)
    assert not draw_blade_asset(out,None,[(0,0),(1,1)],1)
    pygame.quit()

def test_spikelet_renderer_projects_axes_in_side_and_top_cameras(monkeypatch):
    from types import SimpleNamespace
    from simulations.species.species_renderer import SpeciesRenderer,DiagnosticCamera,TopDownDiagnosticCamera
    pygame.init();pygame.display.set_mode((1,1))
    sim=grown();snapshot=sim.render_snapshot;renderer=SpeciesRenderer(SimpleNamespace(camera=None))
    visible={i for i,p in enumerate(snapshot.placements) if p[0]=='flower'}
    index=min(visible);p=snapshot.placements[index];forward=snapshot.placement_orientations[str(index)]['forward']
    rotations=[]
    for camera in [DiagnosticCamera(500,500,[-1,1,-1,1]),TopDownDiagnosticCamera(500,500,[-1,1,-1,1])]:
        drawn=[]
        def capture(screen,sim,camera,kind,point,rotation,scale,**kwargs):
            if kind=='flower':drawn.append(rotation)
            return True
        monkeypatch.setattr(renderer,'_draw_module_asset',capture)
        renderer._draw_individual(pygame.Surface((500,500)),sim,snapshot=snapshot,camera=camera,
            visible_indices=visible,cache=False,draw_environment=False,draw_ground_line=False)
        a=renderer._path_screen(camera,p[2:5])
        b=renderer._path_screen(camera,[p[2+q]+forward[q]*.02 for q in range(3)])
        expected=-math.degrees(math.atan2(b[0]-a[0],a[1]-b[1]))
        assert len(drawn)==408 and drawn[0]==pytest.approx(expected)
        rotations.append(drawn[0])
    assert rotations[0]!=pytest.approx(rotations[1])
    pygame.quit()

def test_live_authorship_and_all_five_pixel_documents_match_manifest():
    pygame.init();pygame.display.set_mode((1,1));w=WorldModel();raw=w.loader.get(SID)
    assert w.plant_catalogue.is_leaf_species(SID) and raw['parents']==['cladis_cyperus']
    packet=json.loads(Path(f'assets/species_trait_specs/{SID}.json').read_text())
    assert all(raw[k]==v==w.resolved_species_entity(SID)[k] for k,v in packet['updates'].items())
    for m in load_manifest(Path(f'assets/plant_asset_specs/{SID}.json'))['modules']:
        row=w.loader.get(m['illustration_id']);assert row['parents']==[SID]
        editor=PixelArtEditorUI(PixelEditorHost(w.loader));assert editor.open(row['id'])
        saved=pygame.image.load(row['media_path']);assert saved.get_size()==(75,75)
        assert pygame.image.tobytes(saved,'RGBA')==pygame.image.tobytes(render_module(m),'RGBA')
    pygame.quit()
