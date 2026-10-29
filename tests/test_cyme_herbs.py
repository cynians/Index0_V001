"""Portable cyme architecture, native assets and canonical photosynthetic bracts."""
import json,math,copy
from pathlib import Path
import pygame,pytest
from simulations.species.cyme_herbs import cyme_herb_profile,draw_cyme_bract
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from tools.author_plant_species import validate_updates,AuthoringError
from tools.author_plant_assets import load_manifest,render_module,PixelEditorHost
from ui.pixel_art_editor_ui import PixelArtEditorUI
from world.world_model import WorldModel
SID='spec_euphorbia_dulcis'
def entity():return {'id':'synthetic_forked_cyme_herb',**json.loads(Path(f'assets/species_trait_specs/{SID}.json').read_text())['updates']}
def grown(e=None,age=145,lod=2):
    s=SpeciesSimulation(species_entity=e or entity(),seed=303);s.set_lod(lod);s.set_age(age);return s
@pytest.mark.parametrize('key,value',[('shoot_count',0),('main_nodes',17),('fork_levels',4),('ray_count',2.5),
    ('leaf_width_m',True),('bract_length_m',float('nan')),('shoot_radius_m',float('inf')),('fork_length_ratio',1)])
def test_invalid_profiles_are_rejected(key,value):
    p=entity()['plant_shoot_profile'];p[key]=value
    assert cyme_herb_profile(p) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_shoot_profile':p})
def test_live_transport_assets_and_identity():
    pygame.init();pygame.display.set_mode((1,1));w=WorldModel();raw=w.loader.get(SID)
    assert w.plant_catalogue.is_leaf_species(SID) and raw['parents']==['cladis_spurge_euphorbia']
    packet=json.loads(Path(f'assets/species_trait_specs/{SID}.json').read_text())
    assert all(raw[k]==v==w.resolved_species_entity(SID)[k] for k,v in packet['updates'].items())
    for module in load_manifest(Path(f'assets/plant_asset_specs/{SID}.json'))['modules']:
        row=w.loader.get(module['illustration_id']);editor=PixelArtEditorUI(PixelEditorHost(w.loader))
        assert row['parents']==[SID] and editor.open(row['id'])
        image=pygame.image.load(row['media_path']);assert image.get_size()==(75,75)
        assert pygame.image.tobytes(image,'RGBA')==pygame.image.tobytes(render_module(module),'RGBA')
    pygame.quit()
def test_canonical_connected_geometry_and_portable_unrelated_fixture():
    s=grown();snap=s.render_snapshot
    assert snap.stats['shoot_count']==3 and snap.stats['cyathium_count']==45
    assert snap.stats['cyme_bract_count']==90 and snap.stats['estimated_leaf_count']==129
    assert snap.stats['root_model_status']=='unresolved' and snap.stats['root_segment_count']==0
    assert snap.stats['leaf_area_m2']>0 and snap.stats['structural_axis_length_m']>0
    assert snap.to_dict()==grown().render_snapshot.to_dict()==PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    for i,p in enumerate(snap.placements):assert -1<=p[1]<i and all(math.isfinite(v) for v in p[2:])
    for attachment in snap.attachment_points:
        if attachment.get('socket')=='leaf':
            host=snap.placements[attachment['stem_placement_index']]
            leaf=snap.placements[attachment['leaf_placement_index']]
            assert leaf[2:5]==host[2:5] and math.dist(attachment['position_m'],host[2:5])<.0001
def test_ecology_bracts_and_structural_axes_stay_canonical_across_phases_and_lods():
    stages=[grown(age=a) for a in [45,145,220,350,510]]
    assert [s.render_snapshot.stats['cyathium_count'] for s in stages]==[0,45,0,0,45]
    assert [s.render_snapshot.stats['capsule_count'] for s in stages]==[0,0,45,0,0]
    def geometry(s):return [[p[0],*p[2:5]] for p in s.render_snapshot.placements if p[0] in {'stem_section','branch_section'}]
    assert all(geometry(s)==geometry(stages[0]) for s in stages)
    assert stages[3].render_snapshot.stats['estimated_leaf_count']==0
    assert stages[3].render_snapshot.stats['leaf_area_m2']==0
    for age in [145,220]:
        sims=[grown(age=age,lod=l) for l in range(3)]
        for key in ['leaf_area_m2','estimated_leaf_count','structural_axis_length_m','cyme_bract_count','cyathium_count','capsule_count']:
            assert len({s.render_snapshot.stats[key] for s in sims})==1
        assert sims[0].get_ecological_outcome()==sims[1].get_ecological_outcome()==sims[2].get_ecological_outcome()
        assert all(k in sims[0].render_snapshot.modules for k in ['leaf','branch_section','flower','fruit'])
def test_controls_change_forks_bract_area_and_fingerprint_with_bounded_maximal_graph():
    e=entity();e['plant_shoot_profile']['fork_levels']=0;simple=grown(e)
    assert simple.render_snapshot.stats['cyathium_count']==15 and simple.render_snapshot.stats['cyme_bract_count']==30
    assert simple.blueprint.fingerprint()!=grown().blueprint.fingerprint()
    e=entity();e['plant_shoot_profile']['bract_width_m']=.009
    assert grown(e).render_snapshot.stats['leaf_area_m2']<grown().render_snapshot.stats['leaf_area_m2']
    e['plant_shoot_profile'].update(shoot_count=6,ray_count=8,fork_levels=3,main_nodes=16)
    maximal=grown(e).render_snapshot
    assert maximal.stats['cyathium_count']==720 and len(maximal.placements)<5000
def test_zero_missing_unknown_and_body_plan_gates():
    assert grown(age=0).render_snapshot.stats['estimated_leaf_count']==0
    e=entity();e['reproductive_mode']='vegetative';assert grown(e).render_snapshot.stats['cyathium_count']==0
    e['reproductive_mode']='other_unknown';assert grown(e).render_snapshot.stats['capsule_count']==0
    for p in [None,{},True,{'form':'pleiochasial_herb'}]:
        e=entity();e['plant_shoot_profile']=p;assert not grown(e).blueprint.growth.get('cyme_herb_version')
    for key,value in [('plant_woodiness','woody'),('plant_growth_behaviour','iterative_indeterminate'),('plant_reproductive_structure','capitulum'),('plant_flowering_position','lateral')]:
        e=entity();e[key]=value;assert not grown(e).blueprint.growth.get('cyme_herb_version')
def test_native_bract_shape_uses_authored_palette_and_physical_extent():
    pygame.init();source=pygame.Surface((75,75),pygame.SRCALPHA);source.fill((91,141,63,255))
    output=pygame.Surface((100,100),pygame.SRCALPHA)
    assert draw_cyme_bract(output,source,(10,50),(70,50),30)
    bounds=output.get_bounding_rect();assert bounds.width<=62 and bounds.height<=32
    assert source.get_at((0,0))==(91,141,63,255)
    assert not draw_cyme_bract(output,None,(10,50),(70,50),30)
    pygame.quit()

def test_projected_bract_collapses_edge_on_and_retains_cupped_margins():
    source=pygame.Surface((75,75),pygame.SRCALPHA);source.fill((91,141,63,255))
    face=pygame.Surface((100,100),pygame.SRCALPHA)
    edge=face.copy();cup=face.copy()
    draw_cyme_bract(face,source,(10,50),(70,50),30,transverse=(0,15))
    draw_cyme_bract(edge,source,(10,50),(70,50),30,transverse=(0,0))
    draw_cyme_bract(cup,source,(10,50),(70,50),30,transverse=(0,0),cup_offset=(0,-10))
    assert edge.get_bounding_rect().height==1
    assert face.get_bounding_rect().height>cup.get_bounding_rect().height>edge.get_bounding_rect().height
    assert cup.get_bounding_rect().top<edge.get_bounding_rect().top
