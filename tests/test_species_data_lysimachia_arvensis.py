"""Live Scarlet Pimpernel card, artwork and BioSim transport."""
import gzip
import json
from PIL import Image
from world.world_model import WorldModel

def test_live_card_identity_unknowns_and_editable_organs():
    world=WorldModel();sid='spec_lysimachia_arvensis';raw=world.loader.get(sid)
    assert world.is_plant_species(sid)
    assert raw['parents']==['cladis_loosestrifes_lysimachia']
    assert raw['binomial_name']=='Lysimachia arvensis'
    assert raw['plant_lifespan']=='annual' and raw['clonal_spread']=='none'
    assert raw['plant_flowering_position']=='lateral' and raw['pollination']==['self_pollination']
    for key in ('max_root_depth','maturity_age','longevity','frost_tolerance','temperature_range'):
        assert not raw.get(key)
    for key in ('nitrogen_fixation','mycorrhizal_type','salinity_tolerance','waterlogging_tolerance'):
        assert raw[key]=='other_unknown'
    for role in ('leaf','stem','branch','flower','fruit'):
        path=raw[f'plant_{role}_module_ref']
        with Image.open(path) as image:
            assert image.mode=='RGBA' and image.size==(75,75)
        row=next(r for r in world.loader.entities.values() if r.get('media_path')==path)
        assert row['parents']==[sid] and row['plant_asset_role']==role
        with gzip.open(row['pixel_document_path'],'rt',encoding='utf-8') as stream:
            doc=json.load(stream)
        assert doc['version']==2 and doc['layers']

def test_biosphere_representative_has_same_annual_recipe_at_all_lods():
    from simulations.biosphere.representatives import RepresentativePopulationManager
    manager=RepresentativePopulationManager(WorldModel())
    individual=manager._new_representative('spec_lysimachia_arvensis',0.,0.)
    manager.set_maturity(individual,1.)
    s=individual.simulation;counts=[];areas=[];conditions=[]
    assert s.blueprint.growth['creeping_herb_profile_version']==1
    for lod in (0,1,2):
        s.set_lod(lod)
        counts.append(s.render_snapshot.stats['estimated_leaf_count'])
        areas.append(s.render_snapshot.stats['leaf_area_m2'])
        conditions.append(manager.condition(individual,{}))
    assert counts[0]==counts[1]==counts[2] and counts[0]>50
    assert areas[0]==areas[1]==areas[2]
    assert conditions[0]==conditions[1]==conditions[2]
