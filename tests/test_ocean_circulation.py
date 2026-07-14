import unittest

from simulations.world_gen.ocean_circulation import derive_ocean_circulation


class OceanCirculationTests(unittest.TestCase):
    def test_continents_partition_basins_and_seed_gyres(self):
        width, height = 30, 16
        ocean_mask = [[True for _x in range(width)] for _y in range(height)]
        for y in range(height):
            for x in (7, 8, 19, 20):
                ocean_mask[y][x] = False

        model = derive_ocean_circulation(ocean_mask, mean_surface_temperature_k=288.0, rotation_hours=24.0)

        self.assertEqual("ocean_circulation_seeded", model["status"])
        self.assertGreaterEqual(model["summary"]["ocean_basin_count"], 2)
        self.assertGreaterEqual(model["summary"]["major_gyre_count"], 2)
        self.assertTrue(model["summary"]["western_boundary_intensification"])
        self.assertTrue(model["summary"]["coastal_upwelling"])

    def test_currents_transport_heat_poleward(self):
        ocean_mask = [[True for _x in range(24)] for _y in range(14)]
        model = derive_ocean_circulation(ocean_mask, mean_surface_temperature_k=288.0, rotation_hours=24.0)
        temperatures = model["sea_surface_temperature_rows_k"]

        self.assertGreater(sum(temperatures[len(temperatures) // 2]) / 24, sum(temperatures[1]) / 24)
        self.assertTrue(any(vector is not None for row in model["vector_rows"] for vector in row))


if __name__ == "__main__":
    unittest.main()
