"""Young pyramidal crown response, isolated from unrelated tree patterns."""
import math
from unittest.mock import patch
import pytest
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot


def entity(**fields):
    return {'id':'spec_synthetic_whorled_tree', 'plant_growth_form':'tree',
        'plant_growth_behaviour':'branched_woody', 'plant_woodiness':'woody',
        'plant_leaf_distribution':'mixed_long_short_shoots',
        'plant_shoot_dimorphism':'long_and_short_shoots',
        'plant_axis_continuity':'monopodial', 'plant_branching_rhythm':'rhythmic',
        'plant_crown_shape':'conical', 'leaf_structure':'needle_like',
        'leaf_arrangement':'fascicled', 'leaf_fascicle_size':5,
        'mature_height':{'max_m':10.}, **fields}


def sim(e=None, fraction=.2222, lod=2):
    s=SpeciesSimulation(species_entity=e or entity(),seed=303)
    s.set_lod(lod); s.set_age(s.mature_age_days*fraction)
    return s


def primaries(snapshot):
    ps=snapshot.placements
    return [i for i,p in enumerate(ps) if p[0]=='branch_section' and p[7]==2
            and ps[p[1]][0]=='stem_section']


def root_geometry(snapshot):
    ps=snapshot.placements
    return [(p[0],p[2:],ps[p[1]][0] if p[1]>=0 else None) for p in ps
            if p[0] in {'root','root_section','root_support','renewal_organ','renewal_bud'}]


def old_snapshot(s):
    with patch('simulations.species.tree_shoots.has_young_conical_crown',return_value=False):
        return s.generate_snapshot(s.age_days,s.lod)


def test_young_crown_adds_successive_tiers_and_narrows_upper_axes():
    s=sim(); before=old_snapshot(s); after=s.render_snapshot
    assert len(primaries(before))==6 and len(primaries(after))==12
    starts=primaries(after)
    assert len({after.placements[after.placements[i][1]][4] for i in starts})==4
    # Final primary segments of the top whorl shorten, rather than retaining
    # the old wide crown cap. Compare full endpoints, not foliage draw caps.
    endpoint=lambda snap,i: snap.placements[i+3]
    radial=lambda snap,i: math.hypot(*endpoint(snap,i)[2:4])
    assert sum(radial(after,i) for i in starts[-3:]) < sum(radial(before,i) for i in primaries(before)[-3:])
    assert root_geometry(before)==root_geometry(after)
    assert after.stats['leaf_area_m2']>before.stats['leaf_area_m2']


def test_mature_geometry_is_exactly_preserved():
    s=sim(fraction=1.)
    assert s.render_snapshot.to_dict()==old_snapshot(s).to_dict()


@pytest.mark.parametrize('field,value',[
    ('plant_crown_shape',None),('plant_crown_shape','other_unknown'),
    ('plant_crown_shape','irregular'),('plant_crown_shape','umbrella'),
    ('plant_branching_rhythm',None),('plant_branching_rhythm','diffuse'),
    ('plant_branching_rhythm','other_unknown')])
def test_other_patterns_remain_exactly_preserved(field,value):
    s=sim(entity(**{field:value}))
    assert 'young_conical_crown_version' not in s.blueprint.growth
    assert s.render_snapshot.to_dict()==old_snapshot(s).to_dict()


def test_determinism_lod_ecology_geometry_and_portability():
    cases=[sim(lod=lod) for lod in [0,1,2]]
    assert len({s.render_snapshot.stats['leaf_area_m2'] for s in cases})==1
    assert [s.get_ecological_outcome({}) for s in cases]==[cases[0].get_ecological_outcome({})]*3
    s=cases[-1]; snap=s.render_snapshot
    assert snap.to_dict()==sim().render_snapshot.to_dict()
    assert PlantGrowthSnapshot.from_dict(snap.to_dict()).to_dict()==snap.to_dict()
    bp=s.blueprint.to_dict()
    assert PlantBlueprint.from_dict(bp).fingerprint()==s.blueprint.fingerprint()
    assert bp['growth']['young_conical_crown_version']==1
    bp['growth'].pop('young_conical_crown_version')
    assert PlantBlueprint.from_dict(bp).fingerprint()!=s.blueprint.fingerprint()
    for i,p in enumerate(snap.placements):
        assert p[1]<i
        assert all(math.isfinite(v) for v in p[2:7])
        assert max(abs(v) for v in p[2:5])<15
    assert s.blueprint.growth['fascicle_size']==5


def test_live_pine_transport_and_distinct_fir_generalization():
    from world.world_model import WorldModel
    world=WorldModel()
    for sid,parent in [('spec_pinus_strobus','cladis_pines_pinus'),
                       ('spec_abies_nordmanniana','cladis_firs_abies')]:
        assert world.loader.plant_catalogue.is_leaf_species(sid)
        e=world.resolved_species_entity(sid)
        s=SpeciesSimulation(world_model=world,species_id=sid,seed=303)
        assert world.loader.get(sid)['parents']==[parent]
        for field,key in [('plant_crown_shape','crown_shape'),('plant_branching_rhythm','branching_rhythm')]:
            assert e[field]==s.blueprint.growth[key]
        assert s.blueprint.growth['young_conical_crown_version']==1
        s.set_age(s.mature_age_days*.2222)
        assert len(primaries(s.render_snapshot))>=12


def test_biosphere_representatives_receive_same_live_crown_recipe():
    from world.world_model import WorldModel
    from simulations.biosphere.biosphere_simulation import BiosphereSimulation
    world=WorldModel()
    site=BiosphereSimulation.reference_site(world_model=world)
    site.ecology.introduce('spec_pinus_strobus',5,5,1.5,.8)
    site.representatives.sync_from_population(site.ecology)
    reps=site.representatives.items(alive_only=True)
    assert reps
    for rep in reps:
        s=rep.simulation
        assert s.blueprint.growth['young_conical_crown_version']==1
        s.set_age(s.mature_age_days*.2222)
        assert len(primaries(s.render_snapshot))==12
        assert s.get_ecological_outcome()['leaf_area_proxy']>0
