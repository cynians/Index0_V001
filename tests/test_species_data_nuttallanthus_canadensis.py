"""Live Blue Toadflax identity, source gaps, editable assets and BioSim."""
import gzip
import json
from PIL import Image
from world.world_model import WorldModel

def test_live_species_identity_evidence_and_editable_assets():
    w=WorldModel();sid='spec_nuttallanthus_canadensis';raw=w.loader.get(sid)
    assert w.is_plant_species(sid)
    assert raw['parents']==['cladis_nuttallanthus']
    assert raw['binomial_name']=='Nuttallanthus canadensis'
    assert raw['plant_shoot_dimorphism']=='long_and_short_shoots'
    assert raw['plant_flowering_position']=='terminal'
    assert raw['pollination']==['self_pollination']
    for k in ('maturity_age','longevity','max_root_depth','temperature_range','frost_tolerance'):
        assert not raw.get(k)
    for k in ('clonal_spread','moisture_preference','waterlogging_tolerance','salinity_tolerance','nitrogen_fixation','mycorrhizal_type'):
        assert raw[k]=='other_unknown'
    for role in ('leaf','stem','branch','flower','fruit'):
        path=raw[f'plant_{role}_module_ref']
        with Image.open(path) as image: assert image.size==(75,75) and image.mode=='RGBA'
        row=next(r for r in w.loader.entities.values() if r.get('media_path')==path)
        assert row['parents']==[sid] and row['plant_asset_role']==role
        with gzip.open(row['pixel_document_path'],'rt',encoding='utf-8') as f: doc=json.load(f)
        assert doc['version']==2 and doc['layers']

def test_biosphere_representative_reuses_dimorphic_graph_and_canonical_ecology():
    from simulations.biosphere.representatives import RepresentativePopulationManager
    manager=RepresentativePopulationManager(WorldModel())
    ind=manager._new_representative('spec_nuttallanthus_canadensis',0.,0.)
    manager.set_maturity(ind,1.);s=ind.simulation
    assert s.blueprint.growth['dimorphic_herb_profile_version']==1
    counts=[];areas=[];conditions=[]
    for lod in (0,1,2):
        s.set_lod(lod)
        counts.append(s.render_snapshot.stats['estimated_leaf_count'])
        areas.append(s.render_snapshot.stats['leaf_area_m2'])
        conditions.append(manager.condition(ind,{}))
    assert counts[0]==counts[1]==counts[2]==121
    assert areas[0]==areas[1]==areas[2]
    assert conditions[0]==conditions[1]==conditions[2]
