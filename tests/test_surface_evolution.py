import unittest

from simulations.world_gen.surface_evolution import derive_surface_evolution_model


def _heightmap():
    return {
        "radius_m": 6_371_000.0,
        "circumference_m": 40_030_000.0,
        "sea_level_m": 0.0,
        "wrap_x": True,
        "sample_grid": {
            "rows": [
                [-500.0, -120.0, 20.0, 90.0],
                [-300.0, 120.0, 820.0, 1260.0],
                [-160.0, 160.0, 640.0, 980.0],
                [-400.0, -80.0, 70.0, 130.0],
            ],
        },
    }


def _water_cycle(liquid=True):
    temperature = 284.0 if liquid else 255.0
    precipitation = 1100.0 if liquid else 35.0
    runoff = 420.0 if liquid else 0.0
    return {
        "liquid_water_possible": liquid,
        "hydrology_enabled": liquid,
        "climate_grid": {
            "temperature_rows_k": [[temperature] * 4 for _ in range(4)],
            "annual_precipitation_rows_mm": [[precipitation] * 4 for _ in range(4)],
            "annual_runoff_rows_mm": [[runoff] * 4 for _ in range(4)],
            "seasonal_snow_fraction_rows": [[0.0, 0.0, 0.15, 0.3] for _ in range(4)],
        },
        "drainage_network_model": {
            "flow_accumulation_rows": [
                [1.0, 4.0, 10.0, 28.0],
                [2.0, 9.0, 22.0, 55.0],
                [2.0, 7.0, 18.0, 40.0],
                [1.0, 3.0, 8.0, 20.0],
            ],
        },
    }


class SurfaceEvolutionTests(unittest.TestCase):
    def test_wet_world_couples_climate_to_landscape(self):
        result = derive_surface_evolution_model(
            planet={"simulated_geology_age_myr": 2200.0},
            terrain={"erosion": {"strength": 0.75, "processes": ["fluvial", "chemical_weathering"]}},
            heightmap=_heightmap(),
            water_cycle=_water_cycle(liquid=True),
            atmosphere={"surface_pressure_bar": 1.0},
        )
        self.assertEqual(result["status"], "surface_evolution_seeded")
        self.assertGreater(result["process_means"]["fluvial"], 0.01)
        self.assertGreater(result["process_means"]["weathering"], 0.01)
        self.assertGreater(result["process_means"]["deposition"], 0.0)
        self.assertEqual(1.0, result["surface_pressure_bar"])
        self.assertNotEqual(
            result["heightmap"]["sample_grid"]["rows"],
            _heightmap()["sample_grid"]["rows"],
        )

    def test_dry_world_does_not_invent_fluvial_erosion(self):
        result = derive_surface_evolution_model(
            planet={},
            terrain={"erosion": {"strength": 0.6, "processes": ["aeolian"]}},
            heightmap=_heightmap(),
            water_cycle=_water_cycle(liquid=False),
            atmosphere={"pressure_bar": 0.03},
        )
        self.assertEqual(result["status"], "surface_evolution_seeded")
        self.assertFalse(result["liquid_water_enabled"])
        self.assertEqual(result["process_means"]["fluvial"], 0.0)
        self.assertEqual(result["process_means"]["weathering"], 0.0)
        self.assertGreater(result["process_means"]["aeolian"], 0.0)

    def test_active_surface_processes_degrade_catalogued_crater_relief(self):
        result = derive_surface_evolution_model(
            planet={"crater_model": {"craters": [{"x": 0.6667, "y": 0.6667, "diameter_km": 1800.0}]}},
            terrain={"erosion": {"strength": 0.9, "processes": ["fluvial", "chemical_weathering"]}},
            heightmap=_heightmap(),
            water_cycle=_water_cycle(liquid=True),
            atmosphere={"pressure_bar": 1.0},
        )
        self.assertGreater(result["process_means"]["crater_degradation"], 0.0)

    def test_routed_river_incises_ravine_and_enforces_downstream_gradient(self):
        heightmap = {
            "radius_m": 6_371_000.0,
            "circumference_m": 4_000.0,
            "region_width_m": 4_000.0,
            "region_height_m": 4_000.0,
            "sample_spacing_x_m": 1_000.0,
            "sample_spacing_y_m": 1_000.0,
            "sea_level_m": 0.0,
            "wrap_x": False,
            "sample_grid": {"rows": [
                [30.0, 35.0, 40.0, 35.0, 30.0],
                [80.0, 110.0, 145.0, 120.0, 65.0],
                [220.0, 180.0, 205.0, 115.0, 20.0],
                [120.0, 135.0, 150.0, 100.0, 25.0],
                [20.0, 25.0, 30.0, 25.0, 15.0],
            ]},
        }
        climate = {
            "temperature_rows_k": [[286.0] * 5 for _ in range(5)],
            "annual_precipitation_rows_mm": [[1250.0] * 5 for _ in range(5)],
            "annual_runoff_rows_mm": [[520.0] * 5 for _ in range(5)],
            "seasonal_snow_fraction_rows": [[0.0] * 5 for _ in range(5)],
        }
        path = [
            {"x": 0.0, "y": 0.5},
            {"x": 0.25, "y": 0.5},
            {"x": 0.5, "y": 0.5},  # raw DEM rises here
            {"x": 0.75, "y": 0.5},
            {"x": 1.0, "y": 0.5},
        ]
        water_cycle = {
            "liquid_water_possible": True,
            "hydrology_enabled": True,
            "climate_grid": climate,
            "drainage_network_model": {
                "flow_accumulation_rows": [[1.0, 3.0, 9.0, 27.0, 81.0] for _ in range(5)],
                "rivers": [{"points": path, "flow": 0.85, "stream_order": 3}],
            },
        }
        result = derive_surface_evolution_model(
            planet={"simulated_geology_age_myr": 1800.0},
            terrain={"erosion": {"strength": 0.8, "processes": ["fluvial"]}},
            heightmap=heightmap,
            water_cycle=water_cycle,
            atmosphere={"surface_pressure_bar": 1.0},
        )
        evolved = result["heightmap"]["sample_grid"]["rows"]
        channel = [evolved[2][x] for x in range(5)]
        self.assertTrue(all(channel[index + 1] < channel[index] for index in range(4)))
        self.assertGreater(result["channel_incision"]["channel_and_bank_cell_count"], 5)
        self.assertGreater(result["channel_incision"]["maximum_incision_m"], 0.0)
        self.assertLess(evolved[1][2], heightmap["sample_grid"]["rows"][1][2])
