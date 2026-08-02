import unittest

from simulations.world_gen.drainage import (
    _channel_morphology,
    _include_downstream_connectors,
    _smoothed_channel_points,
    _spatially_diverse_segments,
    _terrain_flow_directions,
    derive_drainage_network,
    inherit_parent_drainage,
)
from simulations.world_gen.surface_evolution import _apply_channel_incision
from simulations.world_gen.water_cycle import _classify_channel_regime


def _synthetic_closed_basin():
    rows = [[0.0 if x in {0, 8} or y in {0, 8} else 120.0 for x in range(9)] for y in range(9)]
    for y in range(3, 6):
        for x in range(3, 6):
            rows[y][x] = 35.0 if (x, y) != (4, 4) else 5.0
    ocean = [[x in {0, 8} or y in {0, 8} for x in range(9)] for y in range(9)]
    return rows, ocean


class DrainageRealismTests(unittest.TestCase):
    def test_arid_channel_candidates_become_wadis_not_active_rivers(self):
        classification = _classify_channel_regime({
            "catchment_mean_runoff_mm": 4.0,
            "estimated_discharge_m3_s": 18.0,
            "catchment_climate": {
                "mean_precipitation_mm": 70.0,
                "mean_potential_evaporation_mm": 1900.0,
                "mean_groundwater_recharge_mm": 0.1,
                "mean_snowmelt_runoff_mm": 0.0,
                "mean_driest_month_precipitation_mm": 0.0,
                "mean_wettest_month_precipitation_mm": 8.0,
            },
        })

        self.assertEqual("ephemeral", classification["flow_regime"])
        self.assertEqual("wadi_or_arroyo", classification["geomorphic_expression"])
        self.assertLess(classification["flow_months_per_year"], 2.0)

    def test_large_dry_basin_discharge_does_not_imply_perennial_water(self):
        classification = _classify_channel_regime({
            "catchment_mean_runoff_mm": 9.0,
            "estimated_discharge_m3_s": 80.0,
            "catchment_climate": {
                "mean_precipitation_mm": 110.0,
                "mean_potential_evaporation_mm": 2200.0,
                "mean_groundwater_recharge_mm": 0.2,
                "mean_driest_month_precipitation_mm": 0.0,
                "mean_wettest_month_precipitation_mm": 12.0,
            },
        })

        self.assertEqual("ephemeral", classification["flow_regime"])

    def test_wet_catchment_can_keep_river_perennial_across_dry_reach(self):
        classification = _classify_channel_regime({
            "catchment_mean_runoff_mm": 130.0,
            "estimated_discharge_m3_s": 35.0,
            "catchment_climate": {
                "mean_precipitation_mm": 740.0,
                "mean_potential_evaporation_mm": 1050.0,
                "mean_groundwater_recharge_mm": 18.0,
                "mean_driest_month_precipitation_mm": 11.0,
                "mean_wettest_month_precipitation_mm": 98.0,
            },
        })

        self.assertEqual("perennial", classification["flow_regime"])
        self.assertEqual(12.0, classification["flow_months_per_year"])

    def test_ephemeral_wadi_incises_terrain_without_becoming_surface_water(self):
        rows = [
            [120.0, 116.0, 112.0, 108.0],
            [118.0, 114.0, 110.0, 106.0],
            [116.0, 112.0, 108.0, 104.0],
            [114.0, 110.0, 106.0, 102.0],
        ]
        drainage = {
            "rivers": [],
            "ephemeral_channels": [{
                "id": "wadi_1",
                "flow_regime": "ephemeral",
                "flow": 0.7,
                "stream_order": 2,
                "points": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 0.33, "y": 0.33},
                    {"x": 0.67, "y": 0.67},
                    {"x": 1.0, "y": 1.0},
                ],
            }],
        }
        carved, incision = _apply_channel_incision(
            rows,
            drainage,
            {
                "sample_spacing_x_m": 1000.0,
                "sample_spacing_y_m": 1000.0,
            },
            active_water=True,
            declared_strength=1.0,
            wrap_x=False,
        )

        self.assertLess(carved[1][1], rows[1][1])
        self.assertGreater(incision[1][1], 0.0)

    def test_filled_dem_routes_broad_slope_into_valley_not_flood_visit_fan(self):
        rows = [
            [100.0 - y * 10.0 + abs(x - 3) * 8.0 for x in range(7)]
            for y in range(7)
        ]
        ocean = [[y == 6 for _x in range(7)] for y in range(7)]
        flood_parent = {
            (x, y): (max(0, x - 1), min(6, y + 1))
            for y in range(6)
            for x in range(7)
        }

        downstream = _terrain_flow_directions(
            rows, rows, flood_parent, ocean, wrap_x=False,
        )

        self.assertEqual((2, 2), downstream[(1, 1)])
        self.assertEqual((4, 2), downstream[(5, 1)])
        self.assertEqual((3, 2), downstream[(3, 1)])

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

    def test_regional_boundary_outlets_are_not_called_endorheic(self):
        rows = [
            [1000.0 - x * 80.0 - y * 20.0 for x in range(11)]
            for y in range(9)
        ]
        ocean = [[False] * 11 for _y in range(9)]
        runoff = [[900.0] * 11 for _y in range(9)]
        model = derive_drainage_network(
            rows,
            ocean,
            runoff,
            wrap_x=False,
            detail_level=4,
            precipitation_rows=[[1500.0] * 11 for _y in range(9)],
            potential_evaporation_rows=[[650.0] * 11 for _y in range(9)],
        )
        self.assertGreater(model["external_boundary_outlet_count"], 0)
        self.assertTrue(
            any(river["mouth"] == "external_boundary" for river in model["rivers"])
        )

    def test_parent_trunk_is_projected_into_child_lod(self):
        parent = {
            "rivers": [{
                "id": "river_main",
                "stream_order": 3,
                "flow": 0.8,
                "mouth": "ocean",
                "points": [
                    {"x": 0.1, "y": 0.5},
                    {"x": 0.9, "y": 0.5},
                ],
            }]
        }
        child = {"rivers": []}
        inherited = inherit_parent_drainage(
            parent,
            child,
            {"min_u": 0.4, "max_u": 0.6, "min_v": 0.4, "max_v": 0.6},
            {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
        )
        self.assertEqual(1, inherited["inherited_parent_trunk_count"])
        trunk = inherited["rivers"][0]
        self.assertEqual("inherited_parent_trunk", trunk["network_role"])
        self.assertAlmostEqual(0.0, trunk["points"][0]["x"])
        self.assertAlmostEqual(1.0, trunk["points"][-1]["x"])

    def test_inherited_trunk_keeps_one_stable_origin_across_nested_lods(self):
        parent = {
            "detail_level": 0,
            "rivers": [{
                "id": "river_main",
                "stream_order": 3,
                "flow": 0.8,
                "mouth": "ocean",
                "points": [
                    {"x": 0.1, "y": 0.5},
                    {"x": 0.9, "y": 0.5},
                ],
            }],
        }
        child_bounds = {
            "min_u": 0.2, "max_u": 0.8, "min_v": 0.2, "max_v": 0.8,
        }
        child = inherit_parent_drainage(
            parent,
            {"detail_level": 1, "rivers": []},
            child_bounds,
            {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
        )
        grandchild = inherit_parent_drainage(
            child,
            {"detail_level": 2, "rivers": []},
            {"min_u": 0.35, "max_u": 0.65, "min_v": 0.35, "max_v": 0.65},
            child_bounds,
        )

        self.assertEqual(1, grandchild["inherited_parent_trunk_count"])
        self.assertEqual(
            "generated_lod_0:river_main",
            grandchild["rivers"][0]["origin_river_id"],
        )
        self.assertNotIn(
            "parent_trunk_parent_trunk",
            grandchild["rivers"][0]["id"],
        )

    def test_local_retrace_of_inherited_trunk_is_suppressed(self):
        parent = {
            "detail_level": 0,
            "rivers": [{
                "id": "river_main",
                "stream_order": 3,
                "flow": 0.8,
                "points": [
                    {"x": 0.1, "y": 0.5},
                    {"x": 0.9, "y": 0.5},
                ],
            }],
        }
        child = {
            "detail_level": 1,
            "rivers": [{
                "id": "river_local",
                "stream_order": 2,
                "flow": 0.6,
                "points": [
                    {"x": 0.0, "y": 0.505},
                    {"x": 1.0, "y": 0.505},
                ],
            }],
        }
        inherited = inherit_parent_drainage(
            parent,
            child,
            {"min_u": 0.4, "max_u": 0.6, "min_v": 0.4, "max_v": 0.6},
            {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
        )

        self.assertEqual(1, inherited["river_segment_count"])
        self.assertEqual(1, inherited["suppressed_duplicate_local_reach_count"])


if __name__ == "__main__":
    unittest.main()
