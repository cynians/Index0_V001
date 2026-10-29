from copy import deepcopy
import hashlib
import math
from pathlib import Path
import shutil
from types import SimpleNamespace
import uuid

import numpy as np
import pygame
import pytest

from simulations.world_gen.highest_lod_example import (build_models, hydrate_entity, target_entity,
    inspection_overlay, reference_window_entity, DATA_ROOT, RECIPE_VERSION)
from simulations.world_gen.reference_raster import read_numeric_tiff
from simulations.world_gen.regional_refinement import MAX_DETAIL_LEVEL, refinement_sample_dimensions
from simulations.map.worldgen_substrate import WorldgenSubstrate
from simulations.map.map_simulation import MapSimulation
from simulations.biosphere.biosphere_simulation import BiosphereSimulation, _BiosphereWorldView
from simulations.biosphere.biosphere_renderer import BiosphereBuilderRenderer
from simulations.biosphere.ecology import BiosphereEcology, profile_from_entity
from tools.author_highest_lod_example_map import build_changes
from world.simulation_context import SimulationContext
from world.ontology_repository import OntologyRepository
from world.persistent_ontology_store import PersistentOntologyStore
from app.launch_affordance_resolver import LaunchAffordanceResolver
from app.navigation_controller import NavigationController


def fixture():
    root=hydrate_entity(target_entity())
    return root,WorldgenSubstrate(root,root["bounds"])


def test_large_tiled_reference_does_not_invent_survey_scale_or_submetre_measurements():
    root,s=fixture()
    assert root["map_detail_level"]==MAX_DETAIL_LEVEL==7
    assert root["map_context_detail_level"]==3
    assert refinement_sample_dimensions(7,30.,30.)==(301,301)  # Global scale contract unchanged.
    assert root["biosphere_area_m2"]==36_000_000
    assert s.heightmap["sample_spacing_x_m"]==6
    native=s.heightmap["native_raster_tiles"]
    assert native["width"]==native["height"]==6000 and len(native["tiles"])==36
    assert native["sample_spacing_m"]==root["map_detail_profile"]["measurement_floor_m"]==1
    assert "parent_location" not in root and "parent_map_id" not in s.heightmap
    assert build_models() is build_models()
    assert all(m["input_fingerprint"]==s.heightmap["input_fingerprint"] for m in build_models().values())


def test_native_samples_match_retained_numeric_raster_and_cross_tile_seams():
    _,s=fixture()
    tile=read_numeric_tiff(DATA_ROOT/"elevation_2_2.tif")
    for row,col in ((100,120),(200,430),(600,720)):
        assert s.elevation(2000+col+.5,2000+row+.5)==float(tile[row,col])
    left=read_numeric_tiff(DATA_ROOT/"elevation_2_1.tif")
    assert s.elevation(2000,2200.5)==pytest.approx((float(left[200,999])+float(tile[200,0]))*.5)
    xx,yy=np.meshgrid([1999.5,2000,2000.5],[2200.5,2201.5])
    sampled=s.native.sample_many(xx,yy)
    for j in range(2):
        for i in range(3):
            assert sampled[j,i]==pytest.approx(s.elevation(xx[j,i],yy[j,i]))
    assert len(s.native.cache)<=12


def test_sparse_marine_nodata_is_unknown_not_fabricated_bathymetry():
    root,s=fixture()
    assert np.isnan(read_numeric_tiff(DATA_ROOT/"elevation_5_5.tif")).all()
    e=s.environment_at(5500,5500)
    assert e["observed_elevation_m"] is None and not e["terrain_elevation_known"]
    assert e["open_water"] and s.elevation(5500,5500)==0  # Explicit rendering plane only.
    assert not s.terrestrial_habitat_at(5500,5500)
    assert {"soil_depth_m","soil_fertility","soil_ph","salinity_psu","water_depth_m"}<=set(e["runtime_default_fields"])
    assert root["heightmap_model"]["sea_level_m"] is None
    assert "NAVD88" in root["heightmap_model"]["vertical_datum"]
    assert root["regolith_soil_model"]["grid"]=={}
    assert "water_depth_m_rows" not in root["water_cycle_model"]["surface_water_grid"]


def test_mapped_masks_and_categories_stay_categorical_and_aligned():
    root,s=fixture()
    assert root["wetlands_model"]["feature_count"]==95
    assert root["river_model"]["mapped_channel_feature_count"]==57
    assert root["landcover_model"]["source_resolution_m"]==30
    for x,y in ((3050.2,2760.7),(3550.5,2950.5),(5000,4000)):
        assert s.sample("landcover_class",x,y)==int(s.sample("landcover_class",x,y))
        assert s.sample("water_presence",x,y) in (0.,1.)
    assert any(v for row in s.fields["wetland_presence"] for v in row)
    for key,rows in s.fields.items():
        if rows is not None:
            assert len(rows)==1001 and all(len(row)==1001 for row in rows)
            assert np.isfinite(np.asarray(rows)).all()


def test_real_seasonal_climate_is_separate_from_derived_local_fields():
    root,_=fixture()
    c=root["water_cycle_model"]["climate_grid"]
    n=c["source_normals"]
    assert n["period"]=="1991–2020" and n["koppen"]=="Csb"
    assert n["annual_precipitation_mm"]==pytest.approx(1601.641,abs=.01)
    assert n["monthly_precipitation_mm"][6]<n["monthly_precipitation_mm"][11]/5
    assert n["monthly_temperature_c"][7]>n["monthly_temperature_c"][0]+10
    assert "not observed" in c["downscaling"]
    assert "soil profiles" in root["reference_environment_model"]["unknown"]


def test_native_detail_window_samples_same_source_without_fake_lineage():
    root,source=fixture()
    window=reference_window_entity(3300,2700,60,40)
    s=WorldgenSubstrate(window,window["bounds"])
    assert window["reference_source_map_id"]==root["id"]
    assert window["heightmap_model"]["sample_grid"]["width"]==61
    assert window["heightmap_model"]["sample_spacing_x_m"]==1
    assert "parent_location" not in window
    for x,y in ((3300.5,2700.5),(3340.5,2720.5)):
        assert s.elevation(x,y)==source.elevation(x,y)
    assert window["heightmap_model"]["reference_orthophoto"]["uv_bounds"]==[.55,.45,.56,2740/6000]
    with pytest.raises(ValueError):
        reference_window_entity(5800,5900,600,600)
    with pytest.raises(ValueError):
        reference_window_entity(0,0,10000,10000)


def test_import_full_extent_fit_camera_and_do_not_expand_or_bootstrap_over_it():
    root,_=fixture();world=_BiosphereWorldView(root_entity=root)
    map_sim=MapSimulation(SimulationContext(2400,root["id"],world))
    sim=BiosphereSimulation(world,dict(patch_location_id=root["id"],bootstrap_lifeless=True,initial_extent_m=10))
    assert sim.bounds==map_sim.bounds=={k:root["bounds"][k] for k in ("min_x","max_x","min_y","max_y")}
    assert sim.substrate.heightmap is root["heightmap_model"]
    assert sim.maximum_extent_m==6000 and sim._expand_if_population_reaches_edge() is False
    assert map_sim.min_zoom<=.005
    assert map_sim.get_initial_camera_zoom(1000,800)<.2


def test_navigation_imports_same_reference_and_card_offers_both_modes():
    root,_=fixture();world=_BiosphereWorldView(root_entity=root);tabs=[]
    assert {o["mode"] for o in LaunchAffordanceResolver().options_for_entity(root)}>={"map","biosphere"}
    app=SimpleNamespace(world_model=world,tab_manager=SimpleNamespace(tabs=tabs,add_tab=tabs.append,activate_tab_by_key=lambda key:False),
        get_active_simulation=lambda:None,knowledge_layer_active=True,camera_controller=SimpleNamespace(setup_for_sim=lambda sim:None))
    assert NavigationController(app).launch_biosphere_tab(root["id"])
    assert tabs[0].sim_instance.simulation.bounds["max_x"]==6000


def test_repeat_authoring_preserves_edits_and_explicit_revision_carries_unrelated_fields():
    target=target_entity();target["user_note"]="keep"
    overlay=inspection_overlay();overlay["user_note"]="also keep"
    datasets=dict(locations=[target],biospheres=[overlay])
    assert build_changes(datasets)==build_changes(datasets,revise=True)==[]
    target["map_generation_recipe"]=["estuary-survey-target-v1"]
    changes=build_changes(datasets,revise=True)
    assert len(changes)==2 and changes[0]["user_note"]=="keep" and changes[1]["user_note"]=="also keep"
    assert RECIPE_VERSION in changes[0]["map_generation_recipe"] and "heightmap_model" not in changes[0]
    target["map_generation_recipe"]=["user_custom_recipe"]
    with pytest.raises(ValueError):
        build_changes(datasets,revise=True)


def test_bilinear_and_invalid_grid_remain_supported_for_other_generated_maps():
    root=dict(heightmap_model=dict(sample_grid=dict(rows=[[0,2],[2,4]]),min_elevation_m=0,max_elevation_m=4))
    s=WorldgenSubstrate(root,dict(min_x=0,max_x=2,min_y=0,max_y=2))
    assert s.elevation(1,1)==2 and s.elevation(-1,-1)==0 and s.elevation(4,4)==4
    root["heightmap_model"]["sample_grid"]["rows"]=[[0,1],[0]]
    with pytest.raises(ValueError):
        WorldgenSubstrate(root,s.bounds)
    root["heightmap_model"]["sample_grid"]["rows"]=[[float("nan"),1],[1,1]]
    with pytest.raises(ValueError):
        WorldgenSubstrate(root,s.bounds).elevation(.5,.5)


def test_recipe_and_overlay_roundtrip_in_restarted_quadstore():
    cache_root=Path(__file__).resolve().parents[1]/".cache"
    temp=cache_root/f"lod-roundtrip-{uuid.uuid4().hex}";temp.mkdir(parents=True)
    try:
        path=temp/"ontology/index0.owl";database=temp/"store.sqlite3"
        OntologyRepository({"locations":[],"biospheres":[]}).save_owl(path)
        store=PersistentOntologyStore(path,database_path=database)
        assert store.apply_changes(entities=build_changes(store.load_datasets()))["upserted"]==2
        d=PersistentOntologyStore(path,database_path=database).load_datasets()
        root=d["locations"][0];overlay=d["biospheres"][0]
        assert root["biosphere_entity_id"]==overlay["id"] and overlay["overlay_location"]==root["id"]
        assert root["bounds"]["max_x"]==6000 and "heightmap_model" not in root
        assert hydrate_entity(root)["heightmap_model"]["sample_grid"]["width"]==1001
        assert overlay["inspection_introductions"]==[]
    finally:
        assert temp.resolve().parent==cache_root.resolve();shutil.rmtree(temp)


def test_land_occupancy_uses_mapped_open_water_without_inventing_depth():
    root,s=fixture();eco=BiosphereEcology(root["bounds"],[profile_from_entity(dict(id="grass",plant_growth_form="graminoid"))]);eco.substrate=s
    eco.introduce("grass",3500,2900,4000,.9)
    assert eco.abundance_at("grass",5500,5500)==0
    assert eco._suitability(eco.profiles["grass"],eco.environment_at(5500,5500))==0
    assert eco.abundance_at("grass",3500,2700)>0


def test_reference_renderer_clicking_and_caches_reuse_same_native_terrain():
    pygame.init();root=reference_window_entity(3300,2700,60,60);world=_BiosphereWorldView(root_entity=root)
    sim=BiosphereSimulation(world,dict(patch_location_id=root["id"]));sim.isometric_fullscreen_preview=True
    renderer=BiosphereBuilderRenderer(SimpleNamespace());screen=pygame.Surface((700,600))
    before=sim.substrate.elevation(3320,2720)
    renderer.draw(screen,sim);pixels=pygame.image.tobytes(screen,"RGB")
    p=renderer._iso(sim._isometric_projection_state,3320,2720)
    assert sim._screen_to_world(None,p)==pytest.approx((3320,2720),abs=1e-4)
    renderer.draw(screen,sim)
    assert pixels==pygame.image.tobytes(screen,"RGB")
    assert sim.substrate.elevation(3320,2720)==before
    for zoom in (1.1,1.2,1.3,1.4,1.5):
        sim.isometric_view_zoom=zoom;renderer.draw(screen,sim)
    assert len(renderer._terrain_surface_cache)<=4 and len(sim.substrate.native.cache)<=12


def test_source_path_and_checksum_protection():
    _,s=fixture()
    native=deepcopy(s.native.descriptor)
    record=next(t for t in native["tiles"] if t["row"]==t["column"]==2)
    record["path"]="../outside.tif"
    from simulations.world_gen.reference_raster import NativeRasterTiles
    with pytest.raises(ValueError,match="escapes"):
        NativeRasterTiles(native,s.bounds).sample(2200.5,2200.5)
    record["path"]="assets/maps/reference/dosewallips/elevation_2_2.tif";record["sha256"]="0"*64
    with pytest.raises(ValueError,match="checksum"):
        NativeRasterTiles(native,s.bounds).sample(2200.5,2200.5)
