import math
from simulations.species.forest_ecology import build_forest_plan, branch_response, light_at
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.plant_assets import PlantAssetStore
from world.plant_catalogue import PlantCatalogue, PLANTAE_ID


def test_catalogue_follows_ancestry_and_cycles_not_labels():
    entities={PLANTAE_ID:{'type':'cladistics'},
              'a':{'type':'cladistics','parents':[PLANTAE_ID,'b']},
              'b':{'type':'cladistics','parents':['a']},
              'plant':{'type':'species','parents':['b','missing']},
              'image':{'type':'ideas','parents':['plant']},
              'fake':{'type':'species','common_name':'Oak','plant_growth_form':'tree'}}
    catalogue=PlantCatalogue.build(entities)
    assert catalogue.species_ids==frozenset({'plant'})
    assert not catalogue.contains('image')
    entities['a']['parents']=['b']
    assert not PlantCatalogue.build(entities).species_ids
    assert catalogue.is_species('plant')  # immutable previous generation
    assert not PlantCatalogue.build({}).entity_ids


def test_shade_and_spacing_have_distinct_effects():
    growth={'max_height_m':30,'shade_tolerance':'medium','crown_openness':.43}
    plans=[build_forest_plan(growth,303,'dense',v) for v in ('low','medium','high')]
    assert plans[0]['established_count'] < plans[1]['established_count'] <= plans[2]['established_count']
    positions=lambda p:[(t['x'],t['y']) for t in p['trees']]
    assert positions(plans[0])==positions(plans[2])
    assert plans[0]==build_forest_plan(growth,303,'dense','low')
    opened=build_forest_plan(growth,303,'open','low')
    assert opened['mean_ground_light']>plans[0]['mean_ground_light']
    assert opened['established_count']>plans[0]['established_count']
    assert all(.02<=r['light']<=1 for p in plans for r in p['recruits'])


def test_repository_build_and_reparent_refresh_catalogue():
    from types import SimpleNamespace
    from world.entity_loader import EntityLoader
    loader=EntityLoader.__new__(EntityLoader)
    plant={'id':'p','type':'species','parents':[PLANTAE_ID]}
    loader.datasets={'cladistics':[{'id':PLANTAE_ID,'type':'cladistics'}],'species':[plant]}
    loader.entity_aliases={}
    loader.build_entity_index()
    assert loader.plant_catalogue.is_species('p')
    loader.use_ontology=True
    loader._persistent_store=SimpleNamespace(persist_entity_fields=lambda *args:True)
    loader._clear_entity_deletion=lambda *args:None
    plant['parents']=[]
    assert loader.persist_entity_fields(plant,['parents'])
    assert not loader.plant_catalogue.is_species('p')


def test_forest_shortcuts_and_pause_do_not_change_authored_fields():
    import pygame
    from app.input_router import InputRouter
    from types import SimpleNamespace
    entity={'id':'p','shade_tolerance':'medium'}
    sim=SpeciesSimulation(species_entity=entity)
    sim.diagnostic_view='forest'
    app=SimpleNamespace(get_active_simulation=lambda:sim,knowledge_layer_active=False)
    router=InputRouter(app)
    assert router._handle_keydown_navigation(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_s))
    assert sim.forest_spacing=='open'
    assert router._handle_keydown_navigation(pygame.event.Event(pygame.KEYDOWN,key=pygame.K_t))
    assert sim.forest_tolerance=='low' and entity['shade_tolerance']=='medium'
    age=sim.age_days
    sim.update(10)
    assert sim.age_days==age


def test_direction_requires_light_contrast_and_tolerance_retains_shade_leaves():
    uniform={'directional_light':[.2]*8,'growth_bias':[0,0],'shade_tolerance':'low'}
    low,turn=branch_response(uniform,0,0)
    high,_=branch_response({**uniform,'shade_tolerance':'high'},0,0)
    assert turn==0 and high>low
    assert branch_response({**uniform,'growth_bias':[0,.7]},0,0)[1]>0
    assert branch_response({},0,0)==(1.,0.)
    assert light_at(0,0,100,[{'id':1,'height_m':20,'radius_m':5,'x':0,'y':0,'opacity':.7}])==1


def test_crown_response_is_deterministic_lod_stable_and_cache_separated():
    entity={'id':'test_tree','plant_growth_form':'tree','plant_leaf_distribution':'mixed_long_short_shoots',
            'plant_shoot_dimorphism':'long_and_short_shoots','shade_tolerance':'low'}
    env={'directional_light':[.08]*8,'growth_bias':[0,0],'shade_tolerance':'low'}
    control=SpeciesSimulation(species_entity=entity,seed=9)
    shaded=SpeciesSimulation(species_entity=entity,seed=9,environment=env)
    control.set_age(control.mature_age_days)
    shaded.set_age(shaded.mature_age_days)
    assert len(shaded.render_snapshot.leaf_clusters)<len(control.render_snapshot.leaf_clusters)
    assert shaded.render_snapshot.to_dict()==shaded.generate_snapshot().to_dict()
    snapshots=[shaded.generate_snapshot(lod=lod) for lod in range(3)]
    assert len({s.stats['estimated_leaf_count'] for s in snapshots})==1
    assert len({s.stats['leaf_area_m2'] for s in snapshots})==1
    for snapshot in snapshots:
        assert len(snapshot.placements)<20000
        for i,p in enumerate(snapshot.placements):
            assert p[0] in snapshot.modules
            assert p[1]<i
            assert all(math.isfinite(v) for v in p[2:])
            if p[0]=='leaf':
                assert p[2:5]==snapshot.placements[p[1]][2:5]
    store=PlantAssetStore()
    assert store.snapshot_path(control.render_snapshot)!=store.snapshot_path(shaded.render_snapshot)


def test_woodland_scatter_has_clearance_extent_and_seed_variation():
    growth = {'max_height_m': 30, 'shade_tolerance': 'medium'}
    plan = build_forest_plan(growth, 1)
    trees = plan['trees']
    assert len(trees) == 28
    assert plan['extent_m'] * 2 > 80
    assert all(abs(t[axis]) + t['radius_m'] <= plan['extent_m'] for t in trees for axis in ('x', 'y'))
    assert min(math.hypot(a['x']-b['x'], a['y']-b['y'])
               for i, a in enumerate(trees) for b in trees[i+1:]) >= .63 * plan['spacing_m']
    assert trees != build_forest_plan(growth, 2)['trees']
    assert min(t['maturity'] for t in trees) < .65
