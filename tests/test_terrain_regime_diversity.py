import unittest

from simulations.world_gen.heightmap import derive_heightmap_model
from simulations.world_gen.terrain_seed import derive_terrain_seed_model


def _physics():
    return {
        "radius_earth": 1.0,
        "radius_m": 6_371_000.0,
        "surface_gravity_g": 1.0,
    }


def _regime(tectonics="stagnant_lid", cycle="none"):
    return {
        "interior": {
            "internal_heat_w_m2": 0.05,
            "tectonic_regime": tectonics,
        },
        "surface_processes": {
            "hydrologic_cycle": cycle,
            "crater_retention": "moderate",
            "liquid_water_possible": cycle != "none",
            "alternate_surface_fluid_possible": False,
            "primary_topography": "test",
            "erosion_processes": ["aeolian"],
        },
    }


class TerrainRegimeDiversityTests(unittest.TestCase):
    def test_unconfigured_worlds_receive_distinct_derived_styles(self):
        magma = derive_terrain_seed_model(
            {"map_seed": "magma", "water_fraction": 0.0}, _physics(),
            {"surface_pressure_bar": 0.2, "estimated_surface_temperature_k": 1200.0}, _regime(),
        )
        dry = derive_terrain_seed_model(
            {"map_seed": "dry", "water_fraction": 0.01}, _physics(),
            {"surface_pressure_bar": 0.8, "estimated_surface_temperature_k": 300.0}, _regime(),
        )
        frozen = derive_terrain_seed_model(
            {"map_seed": "frozen", "water_fraction": 0.20}, _physics(),
            {"surface_pressure_bar": 0.4, "estimated_surface_temperature_k": 250.0}, _regime(),
        )
        self.assertEqual(magma["specialized_surface_processes"]["geologic_style"], "magma_seas")
        self.assertEqual(dry["specialized_surface_processes"]["geologic_style"], "aeolian_dune_seas")
        self.assertEqual(frozen["specialized_surface_processes"]["geologic_style"], "glaciated")
        self.assertEqual(magma["specialized_surface_processes"]["geologic_style_source"], "derived")

    def test_style_morphology_changes_heightfield(self):
        common = {"water_fraction": 0.01}
        atmosphere = {"surface_pressure_bar": 0.8, "estimated_surface_temperature_k": 300.0}
        magma_terrain = derive_terrain_seed_model({**common, "map_seed": "shared", "geologic_style": "magma_seas"}, _physics(), atmosphere, _regime())
        dune_terrain = derive_terrain_seed_model({**common, "map_seed": "shared", "geologic_style": "aeolian_dune_seas"}, _physics(), atmosphere, _regime())
        magma = derive_heightmap_model(magma_terrain, seed={"map_seed": "shared"})
        dunes = derive_heightmap_model(dune_terrain, seed={"map_seed": "shared"})
        self.assertNotEqual(magma["sample_grid"]["rows"], dunes["sample_grid"]["rows"])

