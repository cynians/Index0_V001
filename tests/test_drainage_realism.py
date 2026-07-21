import unittest

from simulations.world_gen.drainage import (
    _channel_morphology,
    _include_downstream_connectors,
    _smoothed_channel_points,
    _spatially_diverse_segments,
    derive_drainage_network,
)


def _synthetic_closed_basin():
    rows = [[0.0 if x in {0, 8} or y in {0, 8} else 120.0 for x in range(9)] for y in range(9)]
    for y in range(3, 6):
        for x in range(3, 6):
            rows[y][x] = 35.0 if (x, y) != (4, 4) else 5.0
    ocean = [[x in {0, 8} or y in {0, 8} for x in range(9)] for y in range(9)]
    return rows, ocean


class DrainageRealismTests(unittest.TestCase):
    def test_thinned_river_retains_downstream_connector_chain(self):
        upstream = (90.0, 2, [(10, 10), (11, 11)], 9)
        middle = (100.0, 3, [(11, 11), (12, 12)], 15)
        outlet = (120.0, 3, [(12, 12), (13, 13)], 20)
        unrelated = (80.0, 2, [(40, 40), (41, 41)], 8)

        connected = _include_downstream_connectors(
            [upstream], [upstream, middle, outlet, unrelated],
        )

        self.assertEqual([upstream, middle, outlet], connected)

    def test_macro_lod_thins_parallel_neighboring_sources(self):
        clustered = [
            (100.0 - index, 2, [(20 + index, 40), (30, 30)], 12)
            for index in range(6)
        ]
        remote = (80.0, 2, [(70, 40), (75, 30)], 10)

        selected = _spatially_diverse_segments(
            clustered + [remote], 8, width=100,
            minimum_source_spacing_cells=9, wrap_x=False,
        )

        self.assertEqual(2, len(selected))
        self.assertEqual((20, 40), selected[0][2][0])
        self.assertEqual((70, 40), selected[1][2][0])

    def test_straight_d8_route_gets_subcell_sinuosity_without_moving_endpoints(self):
        path = [(index, index) for index in range(12)]
        points = _smoothed_channel_points(
            path, 16, 16, False, amplitude_cells=0.8, wavelength_cells=8.0,
        )
        self.assertEqual(0.0, points[0]["x"])
        self.assertEqual(0.0, points[0]["y"])
        self.assertAlmostEqual(11 / 15, points[-1]["x"], places=6)
        self.assertAlmostEqual(11 / 15, points[-1]["y"], places=6)
        self.assertTrue(any(abs(point["x"] - point["y"]) > 0.001 for point in points[1:-1]))

    def test_steep_confined_channel_is_straighter_than_lowland_mainstem(self):
        path = [(x, 2) for x in range(9)]
        steep_rows = [[1000.0 - x * 90.0 + abs(y - 2) * 180.0 for x in range(9)] for y in range(5)]
        flat_rows = [[100.0 - x * 1.2 + abs(y - 2) * 2.0 for x in range(9)] for y in range(5)]
        steep = _channel_morphology(path, steep_rows, 9, 5, 5000.0, 0.8, 3)
        flat = _channel_morphology(path, flat_rows, 9, 5, 5000.0, 0.8, 3)
        self.assertEqual("confined_straight", steep["pattern"])
        self.assertGreater(flat["sinuosity_amplitude_cells"], steep["sinuosity_amplitude_cells"])
        self.assertFalse(flat["divergence_allowed"])

    def test_short_confluence_segment_has_no_independent_meander_phase(self):
        path = [(2, 2), (3, 3), (4, 3)]
        rows = [[100.0 - x * 2.0 for x in range(7)] for _y in range(7)]
        morphology = _channel_morphology(path, rows, 7, 7, 2500.0, 0.95, 4)
        self.assertEqual("junction_segment", morphology["pattern"])
        self.assertEqual(0.0, morphology["sinuosity_amplitude_cells"])
        self.assertEqual(1, morphology["render_width_px"])

    def test_arid_basin_stays_smaller_and_endorheic(self):
        rows, ocean = _synthetic_closed_basin()
        runoff = [[0.0 if ocean[y][x] else 2.0 for x in range(9)] for y in range(9)]
        precipitation = [[80.0 for _x in range(9)] for _y in range(9)]
        evaporation = [[1800.0 for _x in range(9)] for _y in range(9)]
        model = derive_drainage_network(
            rows, ocean, runoff, wrap_x=False, detail_level=3,
            precipitation_rows=precipitation,
            potential_evaporation_rows=evaporation,
            represented_area_m2=81_000_000.0,
        )
        self.assertTrue(model["lakes"])
        lake = model["lakes"][0]
        self.assertTrue(lake["endorheic"])
        self.assertTrue(lake["water_balance_limited"])
        self.assertLess(lake["cell_count"], lake["maximum_capacity_cell_count"])

    def test_wet_basin_can_overflow_but_spillway_incises_raw_capacity(self):
        rows, ocean = _synthetic_closed_basin()
        runoff = [[0.0 if ocean[y][x] else 650.0 for x in range(9)] for y in range(9)]
        precipitation = [[1600.0 for _x in range(9)] for _y in range(9)]
        evaporation = [[720.0 for _x in range(9)] for _y in range(9)]
        model = derive_drainage_network(
            rows, ocean, runoff, wrap_x=False, detail_level=3,
            precipitation_rows=precipitation,
            potential_evaporation_rows=evaporation,
            represented_area_m2=81_000_000.0,
        )
        self.assertTrue(model["lakes"])
        lake = model["lakes"][0]
        self.assertTrue(lake["overflowing"])
        self.assertFalse(lake["endorheic"])
        self.assertGreater(lake["annual_inflow_index_mm_weighted_cells"], 0.0)
        self.assertGreater(lake["area_km2"], 0.0)

    def test_global_lake_areas_use_spherical_cell_weights(self):
        rows = [[100.0 for _x in range(8)] for _y in range(8)]
        ocean = [[False for _x in range(8)] for _y in range(8)]
        for x in range(8):
            ocean[4][x] = True
            rows[4][x] = 0.0
        rows[1][2] = 0.0
        rows[6][5] = 0.0
        runoff = [[300.0 for _x in range(8)] for _y in range(8)]
        model = derive_drainage_network(
            rows, ocean, runoff, wrap_x=True, detail_level=3,
            precipitation_rows=[[1200.0] * 8 for _y in range(8)],
            potential_evaporation_rows=[[700.0] * 8 for _y in range(8)],
        )
        self.assertTrue(all("area_fraction" in lake for lake in model["lakes"]))
        self.assertAlmostEqual(
            model["lake_area_fraction"],
            sum(lake["area_fraction"] for lake in model["lakes"]),
            places=5,
        )


if __name__ == "__main__":
    unittest.main()
