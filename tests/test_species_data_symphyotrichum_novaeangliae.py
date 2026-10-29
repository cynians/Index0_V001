"""Live New England Aster taxonomy, source gaps and editable assets."""
import gzip
import json
from pathlib import Path

from PIL import Image
from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel


def test_live_aster_fields_transport_and_editable_modules():
    world=WorldModel()
    species_id='spec_symphyotrichum_novaeangliae'
    raw=world.loader.get(species_id)
    entity=world.resolved_species_entity(species_id)
    assert world.is_plant_species(species_id)
    assert raw['parents']==['cladis_virguloid_asters_virgulus']
    assert raw['binomial_name']=='Symphyotrichum novaeangliae'
    for key,value in {'plant_growth_form':'forb','plant_growth_behaviour':'rhizomatous_clonal',
            'leaf_arrangement':'alternate','plant_flowering_position':'terminal',
            'plant_reproductive_structure':'capitulum','root_architecture':'fibrous',
            'reproductive_mode':'both','clonal_spread':'low'}.items():
        assert raw[key]==entity[key]==value
    for key in ('maturity_age','longevity','max_root_depth','frost_tolerance','temperature_range'):
        assert not raw.get(key)
    for key in ('waterlogging_tolerance','salinity_tolerance','mycorrhizal_type','nitrogen_fixation'):
        assert raw[key]=='other_unknown'
    sim=SpeciesSimulation(species_entity=entity,seed=303)
    assert sim.blueprint.growth['clonal_forb_profile']['nodes_per_shoot']==32
    assert sim.blueprint.growth['inflorescence_profile']['head_layout']=='rounded'
    assert sim.blueprint.module('leaf').length_m==.065
    assert sim.blueprint.module('flower').length_m==.032
    assert sim.blueprint.module('fruit').length_m==.028
    for role,kind in [('leaf','leaf'),('stem','stem_section'),('branch','branch_section'),
                      ('flower','flower'),('fruit','fruit')]:
        path=Path(sim.blueprint.module(kind).asset_ref)
        assert path.is_file()
        with Image.open(path) as image:
            assert image.size==(75,75) and image.mode=='RGBA'
        illustration=next(row for row in world.loader.entities.values() if row.get('media_path')==path.as_posix())
        assert illustration['parents']==[species_id]
        assert illustration['plant_asset_role']==role
        with gzip.open(illustration['pixel_document_path'],'rt',encoding='utf-8') as stream:
            document=json.load(stream)
        assert document['version']==2
        assert document.get('layers')


def test_biosphere_uses_same_clonal_herb_and_lod_neutral_condition():
    from simulations.biosphere.representatives import RepresentativePopulationManager
    world=WorldModel()
    manager=RepresentativePopulationManager(world)
    individual=manager._new_representative('spec_symphyotrichum_novaeangliae',0.,0.)
    manager.set_maturity(individual,1.)
    sim=individual.simulation
    assert sim.blueprint.growth.get('clonal_forb_profile_version')
    counts=[]; areas=[]; conditions=[]
    for lod in (0,1,2):
        sim.set_lod(lod)
        counts.append(sim.render_snapshot.stats['estimated_leaf_count'])
        areas.append(sim.render_snapshot.stats['leaf_area_m2'])
        conditions.append(manager.condition(individual,{}))
        assert sim.render_snapshot.stats['root_depth_source']=='runtime_default'
    assert counts[0]==counts[1]==counts[2] and counts[0]>90
    assert areas[0]==areas[1]==areas[2] and areas[0]>.04
    assert conditions[0]==conditions[1]==conditions[2]
