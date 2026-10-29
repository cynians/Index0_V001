"""Explicit vine branching remains bounded, connected and season-independent."""
import copy,json,math
from pathlib import Path
import pytest
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantBlueprint,PlantGrowthSnapshot
from simulations.species.vine_organs import branched_vine_profile
from tools.author_plant_species import validate_updates,AuthoringError
from world.world_model import WorldModel

SID='spec_celastrus_orbiculatus'
ENV={'climbing_supports':[{'id':'fixture','kind':'tree','position_m':[.5,0,0],'height_m':4.,'radius_m':.06}]}
def entity():
    return {'id':'unrelated_branched_climber',**json.loads(Path(f'assets/plant_asset_specs/{SID}.json').read_text())['species_field_updates']}
def grown(e=None,age=150,lod=2,env=ENV):
    s=SpeciesSimulation(species_entity=e or entity(),seed=303,environment=copy.deepcopy(env));s.set_lod(lod);s.set_age(age);return s

@pytest.mark.parametrize('key,value',[('lateral_count',True),('lateral_count',25),('lateral_nodes',3.5),
    ('node_spacing_m',0),('lateral_length_m',float('nan')),('ground_meander_m',float('inf')),
    ('lateral_budget_fraction',.8),('ground_wavelength_m',None)])
def test_profile_validation_rejects_nonfinite_unbounded_and_missing(key,value):
    p=entity()['plant_shoot_profile'];p[key]=value
    assert branched_vine_profile(p) is None
    with pytest.raises(AuthoringError):validate_updates({'plant_shoot_profile':p})

def test_live_fields_identity_and_portable_unrelated_fixture():
    w=WorldModel();raw=w.loader.get(SID);resolved=w.resolved_species_entity(SID)
    assert w.plant_catalogue.is_leaf_species(SID) and raw['parents']==['cladis_staff_vines_celastrus']
    packet=json.loads(Path(f'assets/species_trait_specs/{SID}.json').read_text())
    assert raw['plant_shoot_profile']==resolved['plant_shoot_profile']==packet['updates']['plant_shoot_profile']
    sim=grown();snap=sim.render_snapshot
    assert sim.blueprint.growth['branched_vine_version']==1
    assert snap.stats['vine_lateral_axis_count']==12 and snap.stats['estimated_leaf_count']>100
    assert PlantBlueprint.from_dict(sim.blueprint.to_dict()).fingerprint()==sim.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()==grown().render_snapshot.to_dict()
    assert snap.stats['vine_axis_length_m']<=snap.stats['vine_axis_budget_m']+.001
    for i,p in enumerate(snap.placements):
        assert -1<=p[1]<i and all(math.isfinite(v) for v in p[2:])
    for socket in snap.attachment_points:
        if socket.get('socket')=='lateral_shoot_base':
            host=snap.placements[socket['stem_placement_index']]
            child=socket['branch_placement_index']
            assert math.dist(socket['position_m'],host[2:5])<1e-6
            assert snap.placement_paths[str(child)][0]==host[2:5]

def test_canonical_branches_ecology_and_seasonal_skeleton_do_not_depend_on_visible_organs():
    for age in [150,265,345]:
        sims=[grown(age=age,lod=lod) for lod in range(3)]
        for key in ['estimated_leaf_count','leaf_area_m2','vine_axis_length_m','vine_lateral_axis_count',
                    'vine_lateral_axis_length_m','vine_fruit_sample_count','vine_flower_cyme_count','root_length_m']:
            assert len({s.render_snapshot.stats[key] for s in sims})==1
        assert sims[0].get_ecological_outcome()==sims[1].get_ecological_outcome()==sims[2].get_ecological_outcome()
    def axes(s):
        return [(p[0],p[2:5],s.render_snapshot.placement_paths[str(i)])
                for i,p in enumerate(s.render_snapshot.placements) if p[0] in {'stem_section','branch_section'}]
    assert axes(grown(age=150))==axes(grown(age=265))==axes(grown(age=345))
    assert grown(age=345).render_snapshot.stats['estimated_leaf_count']==0
    assert grown(age=345).render_snapshot.stats['vine_fruit_sample_count']>0

def test_zero_missing_neutrality_and_body_plan_gates():
    assert grown(age=0).render_snapshot.stats['vine_lateral_axis_count']==0
    e=entity();e['plant_shoot_profile']['lateral_count']=0
    assert grown(e).render_snapshot.stats['vine_lateral_axis_count']==0
    assert not any(p[0]=='branch_section' for p in grown(e).render_snapshot.placements)
    base=entity();base.pop('plant_shoot_profile')
    assert not grown(base).blueprint.growth.get('branched_vine_version')
    for profile in [None,{},True,{'form':'branched_vine'}]:
        e={**base,'plant_shoot_profile':profile}
        assert grown(e).blueprint.fingerprint()==grown(base).blueprint.fingerprint()
    for key,value in [('plant_woodiness','herbaceous'),('leaf_attachment_pattern','other_unknown'),
                      ('plant_growth_form','forb')]:
        e=entity();e[key]=value
        if key=='plant_growth_form':e['plant_growth_behaviour']='iterative_indeterminate'
        assert not grown(e).blueprint.growth.get('branched_vine_version')

def test_meander_lateral_drop_and_density_change_the_intended_geometry():
    e=entity();e['plant_shoot_profile']['ground_meander_m']=0
    straight=grown(e,env={});e['plant_shoot_profile']['ground_meander_m']=.8
    curved=grown(e,env={})
    def lateral_span(s):
        main=[p[2:5] for p in s.render_snapshot.placements if p[0]=='stem_section']
        start,end=main[0],main[-1];dx,dy=end[0]-start[0],end[1]-start[1];norm=math.hypot(dx,dy)
        return max(abs((p[0]-start[0])*dy-(p[1]-start[1])*dx)/norm for p in main)
    assert lateral_span(curved)>lateral_span(straight)+.4
    assert curved.render_snapshot.stats['vine_support_contact_count']==0
    assert max(p[4] for p in curved.render_snapshot.placements if p[0] in {'stem_section','branch_section'})<.08
    e=entity();e['plant_shoot_profile']['lateral_drop']=0;raised=grown(e)
    e['plant_shoot_profile']['lateral_drop']=1;drooping=grown(e)
    def ends(s):return [s.render_snapshot.placements[int(k)][4] for k,v in s.render_snapshot.placement_orientations.items() if v.get('axis_role')=='vine_lateral']
    assert sum(ends(drooping))<sum(ends(raised))
    assert drooping.blueprint.fingerprint()!=raised.blueprint.fingerprint()
    e=entity();e['plant_shoot_profile']['lateral_count']=3
    assert grown(e).render_snapshot.stats['estimated_leaf_count']<grown().render_snapshot.stats['estimated_leaf_count']
    e['plant_shoot_profile'].update(lateral_count=24,lateral_nodes=12,lateral_length_m=2.,node_spacing_m=.05)
    maximal=grown(e,env={}).render_snapshot
    assert maximal.stats['vine_axis_length_m']<=18.001 and len(maximal.placements)<2500
