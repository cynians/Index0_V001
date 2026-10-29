import numpy as np

from simulations.map.worldgen_substrate import WorldgenSubstrate
from simulations.world_gen.generated_landscape_artifact import (
    EXTENT_M,
    MAP_ID,
    RECIPE_VERSION,
    build_models,
    hydrate_entity,
    target_entity,
)
from simulations.world_gen.regolith_soils import derive_regolith_soil_model


def test_generated_map_recipe_is_lightweight_and_uses_a_metric_frame():
    target = target_entity()
    assert target["id"] == MAP_ID
    assert RECIPE_VERSION in target["map_generation_recipe"]
    assert target["map_coordinate_space"] == "site_meters"
    assert target["bounds"] == {
        "type": "bbox", "min_x": 0.0, "max_x": EXTENT_M,
        "min_y": 0.0, "max_y": EXTENT_M,
    }
    assert "heightmap_model" not in target
    assert target["geographic_source_bounds"]["max_x"] < 180.0


def test_generated_map_hydrates_retained_candidate_into_biosphere_fields():
    root = hydrate_entity(target_entity())
    heightmap = root["heightmap_model"]
    assert heightmap["sample_grid"]["width"] == 1001
    assert heightmap["sample_spacing_x_m"] == 6.0
    substrate = WorldgenSubstrate(root, root["bounds"])
    center = substrate.environment_at(EXTENT_M * 0.5, EXTENT_M * 0.5)
    assert "soil_moisture" not in center["runtime_default_fields"]
    assert "soil_depth_m" not in center["runtime_default_fields"]
    assert "soil_ph" not in center["runtime_default_fields"]
    assert "soil_fertility" in center["runtime_default_fields"]
    assert center["nutrient_status"] == "deferred_to_biomatter_system"
    assert root["regolith_soil_model"]["grid"].get("fertility_index_rows") is None
    assert root["water_cycle_model"]["surface_water_grid"]["depth_status"] == "unresolved_for_retained_candidate"

    water = root["water_cycle_model"]["surface_water_grid"]["water_presence_rows"].values
    y, x = np.argwhere(water)[0]
    water_environment = substrate.environment_at(x / 1000 * EXTENT_M, y / 1000 * EXTENT_M)
    assert water_environment["open_water"]
    assert not substrate.terrestrial_habitat_at(x / 1000 * EXTENT_M, y / 1000 * EXTENT_M)


def test_abiotic_soil_uses_hydrologic_wetness_but_defers_nutrition():
    heightmap = {
        "sea_level_m": None,
        "sample_grid": {"rows": [[10.0, 10.0], [10.0, 10.0]]},
        "surface_masks": {},
    }
    water_cycle = {
        "climate_grid": {
            "temperature_rows_k": [[285.0, 285.0], [285.0, 285.0]],
            "annual_precipitation_rows_mm": [[600.0, 600.0], [600.0, 600.0]],
            "annual_infiltration_rows_mm": [[120.0, 120.0], [120.0, 120.0]],
        },
        "runoff_grid": {"wetness_index_rows": [[0.2, 0.8], [0.2, 0.8]]},
        "surface_water_grid": {"water_presence_rows": [[False, False], [False, True]]},
    }
    surface = {"process_grid": {
        "chemical_weathering_rows": [[0.4, 0.4], [0.4, 0.4]],
        "sediment_deposition_rows": [[0.2, 0.2], [0.2, 0.2]],
        "erosion_potential_rows": [[0.3, 0.3], [0.3, 0.3]],
    }}
    model = derive_regolith_soil_model({}, heightmap, water_cycle, surface, {})
    assert model["nutrient_status"] == "deferred_to_biomatter_system"
    assert "fertility_index_rows" not in model["grid"]
    assert "parent_nitrogen_index_rows" in model["grid"]
    assert "parent_phosphorus_index_rows" in model["grid"]
    assert model["grid"]["soil_moisture_rows"][0] == [0.2, 0.8]
    assert model["grid"]["soil_depth_m_rows"][1][1] == 0.0


def test_abiotic_soil_exports_parent_inventory_not_available_nutrients():
    heightmap = {
        "sea_level_m": None,
        "sample_grid": {"rows": [[10.0, 10.0], [10.0, 10.0]]},
        "surface_masks": {},
    }
    water_cycle = {
        "climate_grid": {},
        "runoff_grid": {},
        "surface_water_grid": {"water_presence_rows": [[False, False], [False, False]]},
    }
    material = {"element_profile": {"N": 0.04, "P": 0.12, "Ca": 1.0, "S": 0.1}}
    model = derive_regolith_soil_model({}, heightmap, water_cycle, {}, material)

    assert model["grid"]["parent_nitrogen_index_rows"][0][0] > 0.0
    assert model["grid"]["parent_phosphorus_index_rows"][0][0] > 0.0
    assert "available_nitrogen_rows" not in model["grid"]
    assert "available_phosphorus_rows" not in model["grid"]
    assert "nutrient_availability" in model["excluded_properties"]
