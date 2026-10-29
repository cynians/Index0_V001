"""Moringa's tripinnate tree, panicle and hanging capsule composition."""
import json
import math
from copy import deepcopy
from pathlib import Path

import pytest
from simulations.species.plant_assets import PlantBlueprint, PlantGrowthSnapshot
from simulations.species.species_simulation import SpeciesSimulation
from simulations.species.pendant_reproduction import pendant_geometry
from world.world_model import WorldModel


@pytest.fixture(scope='module')
def world():
    return WorldModel()


@pytest.fixture(scope='module')
def entity(world):
    return world.resolved_species_entity('spec_moringa_oleifera')


def make(entity, age=177.75, lod=2):
    s=SpeciesSimulation(species_entity=entity,seed=303)
    s.set_lod(lod);s.set_age(age)
    return s


def test_taxonomy_whole_leaf_and_leaflet_units(world,entity):
    assert world.loader.plant_catalogue.is_leaf_species(entity['id'])
    assert entity['parents']==['cladis_moringaceae']
    assert entity['binomial_name']=='Moringa oleifera'
    assert entity['leaf_structure']=='pinnately_compound'
    assert entity['leaf_division_order']==3
    assert entity['leaf_length']['typical_m'] > 10*entity['leaflet_length']['typical_m']
    assert entity['leaf_arrangement']=='alternate'
    assert entity['nitrogen_fixation']=='none'


def test_authored_transport_and_unknowns(world,entity):
    payload=json.loads(Path('assets/species_trait_specs/spec_moringa_oleifera.json').read_text())['updates']
    raw=world.loader.get(entity['id'])
    assert all(raw[k]==v and entity[k]==v for k,v in payload.items())
    assert all(k not in raw for k in ('maturity_age','max_root_depth','temperature_range','soil_ph_range','frost_tolerance'))
    assert entity['plant_axis_continuity']=='other_unknown'
    s=make(entity)
    assert s.blueprint.growth['shoot_distribution_grammar']==1
    assert s.blueprint.growth['inflorescence_profile']['display_floret_count']==18
    assert s.blueprint.module('flower').visual['depicted_size_m']==.03
    assert s.blueprint.module('fruit').visual['depicted_size_m']==.40
    assert s.render_snapshot.stats['root_depth_source']=='depth_class_default'


def test_lod_canonical_foliage_roots_and_determinism(entity):
    s=make(entity)
    keys=('estimated_leaf_count','leaf_area_m2','root_depth_m','root_spread_m','root_length_m','structural_axis_length_m')
    snapshots=[s.generate_snapshot(177.75,lod) for lod in (0,1,2)]
    assert len({tuple(snap.stats[k] for k in keys) for snap in snapshots})==1
    assert snapshots[-1].to_dict()==make(entity).render_snapshot.to_dict()
    assert PlantBlueprint.from_dict(s.blueprint.to_dict()).fingerprint()==s.blueprint.fingerprint()
    assert PlantGrowthSnapshot.from_dict(s.render_snapshot.to_dict()).to_dict()==s.render_snapshot.to_dict()
    for i,p in enumerate(s.render_snapshot.placements):
        assert p[1]==-1 or 0<=p[1]<i
        assert all(math.isfinite(n) for n in p[2:])


def test_density_changes_ecological_foliage_not_leaf_size(entity):
    dense=deepcopy(entity)
    dense.update(plant_crown_openness=.65,plant_fine_twig_density=.4,plant_leaf_cluster_density=.4)
    a,b=make(entity),make(dense)
    assert a.blueprint.fingerprint()!=b.blueprint.fingerprint()
    assert a.blueprint.module('leaf').length_m==b.blueprint.module('leaf').length_m
    assert a.render_snapshot.stats['leaf_area_m2'] < b.render_snapshot.stats['leaf_area_m2']
    assert a.get_ecological_outcome()['leaf_area_proxy'] < b.get_ecological_outcome()['leaf_area_proxy']


def test_flower_panicle_and_pendant_capsule_phases(entity):
    flowers=make(entity)
    fruit=make(entity,292.)
    assert any(p[0]=='flower' for p in flowers.render_snapshot.placements)
    assert not any(p[0]=='fruit' for p in flowers.render_snapshot.placements)
    assert any(p[0]=='fruit' for p in fruit.render_snapshot.placements)
    assert not any(p[0]=='flower' for p in fruit.render_snapshot.placements)
    for p in fruit.render_snapshot.placements:
        if p[0]=='fruit':
            anchor,tip=pendant_geometry(fruit.blueprint.growth,p,fruit.blueprint.module('fruit'))
            assert anchor[:2]==tip[:2]==tuple(p[2:4])
            assert tip[2]<anchor[2]<p[4]
            assert anchor[2]-tip[2]==pytest.approx(.4*max(.55,p[6]))
            assert fruit.render_snapshot.bounds_m[4]<=tip[2]


def test_reuse_is_trait_driven(entity):
    explicit=deepcopy(entity)
    # Hold generic ID-derived visual defaults constant as well as authored biology.
    for key,value in make(entity).blueprint.growth['architecture_ranges'].items():
        explicit['plant_'+key]=deepcopy(value)
    other=deepcopy(explicit)
    other['id']='spec_unrelated_tripinnate_fixture'
    other['parents']=[]
    other['binomial_name']='Synthetic fixture'
    a,b=make(explicit),make(other)
    assert a.blueprint.growth==b.blueprint.growth
    # Generic species-salted crookedness can differ; the same trait path and
    # canonical foliage response must survive an unrelated synthetic identity.
    for key in ('estimated_leaf_count','leaf_area_m2','leaf_cluster_count','branch_count'):
        assert a.render_snapshot.stats[key]==b.render_snapshot.stats[key]
    assert any(p[0]=='flower' for p in b.render_snapshot.placements)
    assert b.render_snapshot.to_dict()==make(other).render_snapshot.to_dict()
    denser=deepcopy(other)
    denser['plant_leaf_cluster_density']=.8
    assert make(denser).render_snapshot.stats['leaf_area_m2'] > b.render_snapshot.stats['leaf_area_m2']
