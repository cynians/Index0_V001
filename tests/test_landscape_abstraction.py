from copy import deepcopy

import numpy as np
import pytest

from simulations.world_gen.highest_lod_example import hydrate_entity,target_entity
from simulations.world_gen.landscape_abstraction import abstract_landscape,reconstruct_landscape,evaluate_reconstruction


@pytest.fixture(scope="module")
def experiment():
    reference=hydrate_entity(target_entity())
    abstraction=abstract_landscape(reference)
    return reference,abstraction


def test_abstraction_is_compact_lod3_and_contains_no_native_or_fine_grid(experiment):
    reference,parent=experiment
    assert parent["detail_level"]==3 and parent["spacing_m"]==30
    assert (parent["width"],parent["height"])==(201,201)
    assert "native_raster_tiles" not in repr(parent)
    assert len(parent["broad_fields"]["elevation_rows_m"])==201
    assert parent["source_fingerprint"]==reference["heightmap_model"]["input_fingerprint"]
    assert parent["unknown"]==reference["reference_environment_model"]["unknown"]
    assert parent["residual_budget_m"]>0


def test_narrow_connected_features_survive_parent_sampling(experiment):
    _,parent=experiment
    network=parent["feature_network"]
    assert np.asarray(network["river_corridor_rows"]).any()
    assert network["river_components"] and network["water_components"]
    assert all(component["id"].startswith("river_") for component in network["river_components"])
    assert np.asarray(network["shoreline_rows"]).any()


def test_reconstruction_is_deterministic_bounded_and_uses_only_parent(experiment):
    _,parent=experiment
    a=reconstruct_landscape(parent,seed=17);b=reconstruct_landscape(deepcopy(parent),seed=17)
    c=reconstruct_landscape(parent,seed=18)
    za=np.asarray(a["elevation_rows_m"]);zb=np.asarray(b["elevation_rows_m"]);zc=np.asarray(c["elevation_rows_m"])
    assert za.shape==(1001,1001) and np.array_equal(za,zb)
    assert not np.array_equal(za,zc)
    assert a["maximum_absolute_residual_m"]<=parent["residual_budget_m"]
    assert a["parent_fingerprint"]==parent["fingerprint"]


def test_parent_surface_is_close_and_outer_boundary_is_exact(experiment):
    _,parent=experiment
    child=reconstruct_landscape(parent,seed=83)
    z=np.asarray(child["elevation_rows_m"]);p=np.asarray(parent["broad_fields"]["elevation_rows_m"])
    assert np.sqrt(np.mean((z[::5,::5]-p)**2))<parent["residual_budget_m"]*.5
    residual=np.asarray(child["residual_rows_m"])
    assert not residual[0].any() and not residual[-1].any()
    assert not residual[:,0].any() and not residual[:,-1].any()


def test_evaluation_separates_structure_from_stochastic_pixel_match(experiment):
    reference,parent=experiment
    score=evaluate_reconstruction(parent,reconstruct_landscape(parent,seed=241),reference)
    assert score["parent_sample_difference_rmse_m"]<parent["residual_budget_m"]*.5
    assert score["residual_budget_respected"]
    assert score["river_boundary_portals_preserved"]
    assert score["reference_pixel_rmse_m"]>0
    assert .2<score["residual_rms_ratio"]<3


def test_invalid_contract_and_unbounded_request_are_rejected(experiment):
    _,parent=experiment
    broken=deepcopy(parent);broken["contract_version"]="future"
    with pytest.raises(ValueError):reconstruct_landscape(broken)
    with pytest.raises(ValueError):reconstruct_landscape(parent,output_spacing_m=.5)


def test_generated_parent_route_needs_no_reference_specific_models():
    rows=[[30-y*3-x for x in range(5)] for y in range(5)]
    climate=dict(temperature_rows_k=[[284.]*5 for _ in range(5)],
        annual_precipitation_rows_mm=[[900.]*5 for _ in range(5)],
        annual_runoff_rows_mm=[[240.]*5 for _ in range(5)],koppen_rows=[["Cfb"]*5 for _ in range(5)])
    generated=dict(id="generated_lod3",map_coordinate_space="local_cartesian",map_detail_level=3,
        bounds=dict(type="bbox",min_x=0,max_x=120,min_y=0,max_y=120),
        heightmap_model=dict(model_version="generated",sample_spacing_x_m=30.,sample_spacing_y_m=30.,sea_level_m=20.,
            sample_grid=dict(width=5,height=5,rows=rows)),
        water_cycle_model=dict(climate_grid=climate,rivers=[dict(id="r1",mouth="ocean",stream_order=2,flow=.7,
            points=[dict(x=0.,y=0.),dict(x=.5,y=.5),dict(x=1.,y=1.)])],lakes=[]))
    parent=abstract_landscape(generated,parent_spacing_m=30.)
    assert parent["source_map_id"]=="generated_lod3" and parent["calibration_kind"]=="generated_parent"
    assert parent["climate_boundary"]["observation_based"] is False
    assert parent["feature_network"]["river_graph"][0]["id"]=="r1"
    assert np.asarray(parent["feature_network"]["river_corridor_rows"]).any()
    assert parent["residual_statistics"]["steep_hillslope"]["source"]=="scale-specific procedural prior"
    child=reconstruct_landscape(parent,seed=8,output_spacing_m=6.)
    assert (child["width"],child["height"])==(21,21)


def test_dry_generated_parent_does_not_label_relative_runoff_as_broad_wetland():
    rows=[[50-y-x*.2 for x in range(5)] for y in range(5)]
    climate=dict(temperature_rows_k=[[290.]*5 for _ in range(5)],annual_precipitation_rows_mm=[[100.]*5 for _ in range(5)],
        annual_runoff_rows_mm=[[float(y)]*5 for y in range(5)],koppen_rows=[["BWh"]*5 for _ in range(5)])
    generated=dict(id="dry",map_detail_level=3,bounds=dict(type="bbox",min_x=0,max_x=120,min_y=0,max_y=120),
        heightmap_model=dict(sample_spacing_x_m=30.,sea_level_m=0.,sample_grid=dict(rows=rows)),
        water_cycle_model=dict(climate_grid=climate,rivers=[],lakes=[]))
    parent=abstract_landscape(generated,parent_spacing_m=30.)
    assert not np.asarray(parent["feature_network"]["wetland_rows"]).any()
