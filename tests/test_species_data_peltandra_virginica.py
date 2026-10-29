"""Live Arrow Arum taxonomy, field transport and Pixel Studio assets."""
import gzip
import json
from pathlib import Path

from simulations.species.species_simulation import SpeciesSimulation
from world.world_model import WorldModel


def test_live_arrow_arum_data_and_editable_assets():
    world = WorldModel()
    entity = world.resolved_species_entity('spec_peltandra_virginica')
    assert world.is_plant_species(entity['id'])
    assert entity['parents'] == ['cladis_arrow_arums_peltandra']
    assert entity['plant_growth_form'] == 'aquatic'
    assert entity['plant_growth_behaviour'] == 'rhizomatous_clonal'
    assert entity['belowground_storage'] == ['rhizome']
    assert entity['pollination'] == ['fly']
    assert entity['plant_reproductive_structure'] == 'spike'
    for key in ('maturity_age','longevity','max_root_depth','frost_tolerance','salinity_tolerance'):
        assert entity.get(key) in (None,'other_unknown')
    sim = SpeciesSimulation(species_entity=entity,seed=303)
    assert sim.blueprint.growth['emergent_rosette_profile']['petiole_length_m'] == .68
    assert sim.blueprint.module('leaf').length_m == .30
    assert sim.blueprint.module('flower').length_m == .18
    assert sim.blueprint.module('fruit').length_m == .045
    for role,kind in [('leaf','leaf'),('stem','stem_section'),('flower','flower'),('fruit','fruit')]:
        asset = Path(sim.blueprint.module(kind).asset_ref)
        assert asset.is_file()
        illustration = next(row for row in world.loader.entities.values()
                            if row.get('media_path') == asset.as_posix())
        assert illustration['parents'] == [entity['id']]
        assert illustration['plant_asset_role'] == role
        with gzip.open(illustration['pixel_document_path'],'rt',encoding='utf-8') as stream:
            doc = json.load(stream)
        assert doc['version'] == 2


def test_biosphere_representative_consumes_the_same_emergent_body_and_area():
    from simulations.biosphere.representatives import RepresentativePopulationManager
    world = WorldModel()
    manager = RepresentativePopulationManager(world)
    representative = manager._new_representative('spec_peltandra_virginica', 0., 0.)
    manager.set_maturity(representative, 1.)
    body = representative.simulation
    assert body.blueprint.growth.get('emergent_rosette_version')
    assert body.render_snapshot.stats['estimated_leaf_count'] == 7
    outcomes = []
    for lod in (0,1,2):
        body.set_lod(lod)
        outcomes.append(manager.condition(representative, {}))
        assert body.render_snapshot.stats['leaf_area_m2'] > .15
        assert body.render_snapshot.stats['root_depth_source'] == 'runtime_default'
    assert outcomes[0] == outcomes[1] == outcomes[2]
