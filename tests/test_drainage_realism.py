import unittest

from simulations.world_gen.drainage import (
    _channel_morphology,
    _include_downstream_connectors,
    _smoothed_channel_points,
    _spatially_diverse_segments,
    _terrain_flow_directions,
    derive_drainage_network,
    derive_surface_hydrology_grids,
    inherit_parent_drainage,
)
from simulations.world_gen.regolith_soils import derive_regolith_soil_model
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

    def test_a_river_entering_a_regional_tile_is_in_its_river_list(self):
        # A valley draining east; the parent brings 5,000 cells of catchment
        # in through the west edge at row 10, and only the east edge drains.
        width, height = 40, 21
        rows = [[200.0 - 2.0 * x + 6.0 * abs(y - 10) for x in range(width)] for y in range(height)]
        ocean = [[False] * width for _y in range(height)]
        runoff = [[100.0] * width for _y in range(height)]
        inlets = [[(x == 0 or y in (0, height - 1)) for x in range(width)] for y in range(height)]

        def largest(inflow):
            model = derive_drainage_network(
                rows, ocean, runoff, wrap_x=False, detail_level=2, represented_area_m2=float(width * height) * 1.0e6, inflow=inflow,
            )
            rivers = model.get("rivers") or []
            return max((float(river.get("catchment_area_weighted_cells", 0.0) or 0.0) for river in rivers), default=0.0)

        self.assertLessEqual(largest(None), float(width * height))
        entered = largest({"cells": {(0, 10): 5000.0}, "inlets": inlets, "means": {"runoff": 250.0}})
        self.assertGreater(entered, 5000.0)

    def test_a_sparse_river_polyline_is_carved_between_its_vertices(self):
        from simulations.world_gen.surface_evolution import _river_grid_path

        path = _river_grid_path({"points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.5}]}, 21, 11)
        self.assertEqual(path[0], (0, 0))
        self.assertEqual(path[-1], (20, 5))
        self.assertEqual(len(path), 21)
        self.assertTrue(all(max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1 for a, b in zip(path, path[1:])))

    def test_routed_path_over_a_high_sill_is_not_trenched(self):
        # A path the flood routing carried out of a basin over a 300 m rise:
        # the bed may not be forced down through the whole rise.
        rows = [[100.0, 400.0, 400.0, 90.0] for _y in range(4)]
        drainage = {"rivers": [{
            "id": "river_1", "flow_regime": "perennial", "flow": 1.0, "stream_order": 3,
            "points": [{"x": 0.0, "y": 0.5}, {"x": 0.33, "y": 0.5}, {"x": 0.67, "y": 0.5}, {"x": 1.0, "y": 0.5}],
        }]}
        carved, incision = _apply_channel_incision(
            rows, drainage, {"sample_spacing_x_m": 1000.0, "sample_spacing_y_m": 1000.0},
            active_water=True, declared_strength=1.0, wrap_x=False,
        )
        deepest = max(max(row) for row in incision)
        self.assertGreater(deepest, 0.0)
        self.assertLess(deepest, 0.2 * 300.0)

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

    def test_a_dry_planet_scale_basin_keeps_its_terminal_lake(self):
        # Planet scale (detail 0, lakes of at least 3 cells when full): a
        # closed basin whose runoff supports less than one cell of open water
        # still ends in a terminal lake, shallow and flagged for the playa model.
        rows, ocean = _synthetic_closed_basin()
        runoff = [[0.0 if ocean[y][x] else 2.0 for x in range(9)] for y in range(9)]
        precipitation = [[80.0 for _x in range(9)] for _y in range(9)]
        evaporation = [[2300.0 for _x in range(9)] for _y in range(9)]
        model = derive_drainage_network(
            rows, ocean, runoff, wrap_x=False, detail_level=0,
            precipitation_rows=precipitation, potential_evaporation_rows=evaporation,
            represented_area_m2=81.0 * 6.0e9,
        )
        self.assertTrue(model["lakes"])
        lake = model["lakes"][0]
        self.assertTrue(lake["endorheic"] and lake["water_balance_limited"])
        self.assertLess(lake["cell_count"], 3)
        self.assertLess(lake["terminal_fill_fraction"], 1.0)

    def test_wet_basin_overflows_through_its_outlet(self):
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

    def test_a_tributary_keeps_its_own_flow_where_it_joins_a_trunk(self):
        # A trunk valley along the middle row, one side valley from the north.
        width, height, trunk_row, side_column = 21, 15, 7, 10
        rows = [[100.0 - 2.0 * x + 6.0 * abs(y - trunk_row) for x in range(width)] for y in range(height)]
        for y in range(trunk_row):
            rows[y][side_column] -= 3.0  # a side valley that stays above the trunk
        model = derive_drainage_network(
            rows, [[False] * width for _y in range(height)], [[500.0] * width for _y in range(height)],
            wrap_x=False, detail_level=4,
            precipitation_rows=[[1200.0] * width for _y in range(height)],
            potential_evaporation_rows=[[600.0] * width for _y in range(height)],
        )
        trunk_y = trunk_row / (height - 1)
        side = [
            river for river in model["rivers"]
            if abs(river["points"][0]["y"] - trunk_y) > 1e-6 and abs(river["points"][-1]["y"] - trunk_y) < 1e-6
        ]
        self.assertTrue(side)
        largest = max(river["runoff_accumulation_mm_cells"] for river in model["rivers"])
        for river in side:
            # Gauged at its own last cell, not at the junction cell on the trunk.
            self.assertLess(river["runoff_accumulation_mm_cells"], 0.3 * largest)
            self.assertLess(river["catchment_cell_count"], 0.3 * width * height)
            self.assertLess(river["stream_order"], model["maximum_stream_order"])

    def test_a_path_along_a_tile_edge_is_not_drawn_across_the_tile(self):
        path = [(0, y) for y in range(24)]
        regional = _smoothed_channel_points(path, 41, 30, False, amplitude_cells=1.2, wavelength_cells=8.0)
        self.assertTrue(all(0.0 <= point["x"] <= 0.1 for point in regional))
        self.assertTrue(all(0.0 <= point["y"] <= 1.0 for point in regional))
        # A planet's map does wrap: the same path there may cross the seam.
        planet = _smoothed_channel_points(path, 41, 30, True, amplitude_cells=1.2, wavelength_cells=8.0)
        self.assertTrue(any(point["x"] > 0.9 for point in planet))

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

    def test_parent_lake_identity_and_child_shoreline_survive_refinement(self):
        parent = {
            "detail_level": 1,
            "rivers": [],
            "lakes": [{
                "id": "lake_major",
                "area_fraction": 0.04,
                "surface_elevation_m": 42.0,
                "bounds": {"min_x": 0.35, "max_x": 0.65, "min_y": 0.35, "max_y": 0.65},
            }],
        }
        child = {
            "detail_level": 2,
            "rivers": [],
            "lakes": [{
                "id": "lake_local",
                "surface_elevation_m": 41.8,
                "bounds": {"min_x": 0.2, "max_x": 0.8, "min_y": 0.2, "max_y": 0.8},
                "cells": [[2, 2], [3, 2]],
            }],
        }
        inherited = inherit_parent_drainage(
            parent,
            child,
            {"min_u": 0.4, "max_u": 0.6, "min_v": 0.4, "max_v": 0.6},
            {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
        )
        self.assertEqual(1, inherited["inherited_parent_lake_count"])
        self.assertEqual(1, inherited["refined_parent_lake_count"])
        self.assertEqual("refined_parent_lake", inherited["lakes"][0]["network_role"])
        self.assertEqual("generated_lod_1:lake_major", inherited["lakes"][0]["origin_lake_id"])
        self.assertEqual([[2, 2], [3, 2]], inherited["lakes"][0]["cells"])

    def test_local_tributary_snaps_to_inherited_parent_trunk(self):
        parent = {
            "detail_level": 0,
            "rivers": [{
                "id": "river_main", "stream_order": 4, "flow": 0.9,
                "points": [{"x": 0.1, "y": 0.5}, {"x": 0.9, "y": 0.5}],
            }],
        }
        child = {
            "detail_level": 1,
            "grid_width": 201,
            "grid_height": 201,
            "lakes": [],
            "rivers": [{
                "id": "river_local", "stream_order": 2, "flow": 0.4,
                "points": [{"x": 0.2, "y": 0.1}, {"x": 0.52, "y": 0.492}],
            }],
        }
        inherited = inherit_parent_drainage(
            parent,
            child,
            {"min_u": 0.4, "max_u": 0.6, "min_v": 0.4, "max_v": 0.6},
            {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0},
        )
        tributary = next(river for river in inherited["rivers"] if river["id"] == "river_local")
        self.assertEqual("snapped_to_inherited_trunk", tributary["cross_lod_connection"])
        self.assertEqual("confluence", tributary["mouth"])
        self.assertAlmostEqual(0.5, tributary["points"][-1]["y"])

    def test_surface_hydrology_grids_expose_water_channels_and_wetness(self):
        rows = [[10.0 - y for _x in range(7)] for y in range(7)]
        ocean = [[False] * 7 for _y in range(7)]
        network = {
            "rivers": [{
                "points": [{"x": 0.5, "y": 0.0}, {"x": 0.5, "y": 1.0}],
                "flow_regime": "perennial", "estimated_discharge_m3_s": 8.0,
                "average_width_m": 12.0,
            }],
            "ephemeral_channels": [],
            "lakes": [],
            "flow_accumulation_rows": [[1.0] * 7 for _y in range(7)],
        }
        runoff_grid, surface_grid = derive_surface_hydrology_grids(
            rows, ocean, network, region_width_m=600.0, region_height_m=600.0,
            runoff_rows=[[250.0] * 7 for _y in range(7)],
            precipitation_rows=[[700.0] * 7 for _y in range(7)],
            potential_evaporation_rows=[[500.0] * 7 for _y in range(7)],
        )
        self.assertEqual(1.0, runoff_grid["channel_presence_rows"][3][3])
        self.assertTrue(surface_grid["water_presence_rows"][3][3])
        self.assertGreater(surface_grid["water_depth_m_rows"][3][3], 0.0)
        self.assertGreater(runoff_grid["wetness_index_rows"][3][3], runoff_grid["wetness_index_rows"][3][0])


def _channel_across(samples, discharge, *, regime="perennial", size_m=256.0):
    """Hydrology rasters of one straight channel down the middle of dry, level ground."""
    rows = [[10.0] * samples for _y in range(samples)]
    network = {
        "rivers": [{
            "points": [{"x": 0.5, "y": 0.0}, {"x": 0.5, "y": 1.0}],
            "flow_regime": regime, "estimated_discharge_m3_s": discharge,
            # As the water cycle records it: hydraulic width with a 2 m display floor.
            "average_width_m": max(2.0, 2.8 * discharge ** 0.5),
        }],
    }
    return derive_surface_hydrology_grids(
        rows, [[False] * samples for _y in range(samples)], network,
        region_width_m=size_m, region_height_m=size_m,
        runoff_rows=[[15.0] * samples for _y in range(samples)],
        precipitation_rows=[[480.0] * samples for _y in range(samples)],
        potential_evaporation_rows=[[3500.0] * samples for _y in range(samples)],
    )


def _wetting(runoff_grid):
    """Mean wetness the channel adds to the ground, and the wetted width in cells."""
    row = runoff_grid["wetness_index_rows"][len(runoff_grid["wetness_index_rows"]) // 2]
    dry = row[0]
    excess = [value - dry for value in row]
    return sum(excess) / len(excess), sum(value > 0.005 for value in excess)


class WettingBesideWaterTests(unittest.TestCase):
    """Wet ground beside water is measured in metres and by what the water carries."""

    def test_a_rivers_wet_margin_is_as_wide_on_the_ground_at_every_sample_spacing(self):
        # 20 m3/s: 12.5 m of channel and a 37.5 m margin on either side.  The
        # margin used to be three cells whatever the cell: 6 m at 2 m samples,
        # 48 m at 16 m samples.
        widths_m, means = {}, {}
        for samples in (129, 33, 17):
            spacing = 256.0 / (samples - 1)
            means[spacing], cells = _wetting(_channel_across(samples, 20.0)[0])
            widths_m[spacing] = cells * spacing
        for spacing, width_m in widths_m.items():
            self.assertAlmostEqual(87.0, width_m, delta=2.0 * spacing, msg=f"{spacing} m samples")
        self.assertAlmostEqual(means[2.0], means[8.0], delta=means[2.0] * 0.10)
        self.assertAlmostEqual(means[2.0], means[16.0], delta=means[2.0] * 0.10)

    def test_a_rill_is_a_channel_but_neither_open_water_nor_a_wet_bank(self):
        # What a 100 m2 catchment sheds in a dry climate, against a stream.
        rill_runoff, rill_water = _channel_across(129, 1e-6, regime="intermittent")
        stream_runoff, stream_water = _channel_across(129, 2.0)
        centre = 64
        self.assertEqual(1.0, rill_runoff["channel_presence_rows"][centre][centre])
        self.assertFalse(rill_water["water_presence_rows"][centre][centre])
        self.assertEqual(0.0, rill_water["water_depth_m_rows"][centre][centre])
        self.assertTrue(stream_water["water_presence_rows"][centre][centre])
        self.assertAlmostEqual(0.24 * 2.0 ** 0.38, stream_water["water_depth_m_rows"][centre][centre], places=3)
        rill, stream = _wetting(rill_runoff)[0], _wetting(stream_runoff)[0]
        self.assertGreater(stream, 0.01)
        self.assertLess(rill, stream * 0.001)
        self.assertLess(max(rill_runoff["wetness_index_rows"][centre]) - rill_runoff["wetness_index_rows"][centre][0], 0.005)

    def test_a_channel_narrower_than_a_cell_wets_only_its_share_of_the_cell(self):
        # A brook of 50 l/s (0.6 m wide, 1.9 m margin) at 0.5 m and at 8 m samples.
        fine = _wetting(_channel_across(513, 0.05)[0])[0]
        coarse_grid = _channel_across(33, 0.05)[0]
        coarse = _wetting(coarse_grid)[0]
        self.assertAlmostEqual(fine, coarse, delta=fine * 0.10)
        row = coarse_grid["wetness_index_rows"][16]
        # Only the cell the brook crosses is wetter, and far from saturated.
        self.assertEqual(1, sum(value > row[0] + 1e-6 for value in row))
        self.assertLess(max(row) - row[0], 0.06)

    def test_a_stream_narrower_than_its_cell_leaves_the_cell_its_soil(self):
        # 1 m3/s: a 2.8 m stream, drawn through 8 m cells.  The flag marks
        # the cell as water; the soil model used to give such a cell no soil.
        samples = 9
        runoff_grid, surface_grid = _channel_across(samples, 1.0, size_m=64.0)
        centre = samples // 2
        self.assertTrue(surface_grid["water_presence_rows"][centre][centre])
        share = surface_grid["water_fraction_rows"][centre][centre]
        self.assertAlmostEqual(2.8 / 8.0, share, places=2)
        self.assertEqual(0.0, surface_grid["water_fraction_rows"][centre][centre + 1])

        def flat(value):
            return [[value] * samples for _y in range(samples)]

        soils = derive_regolith_soil_model(
            {},
            {"sample_grid": {"rows": flat(10.0)}},
            {
                "climate_grid": {"temperature_rows_k": flat(295.0), "annual_precipitation_rows_mm": flat(900.0)},
                "runoff_grid": runoff_grid,
                "surface_water_grid": surface_grid,
            },
            {"process_grid": {"chemical_weathering_rows": flat(0.4)}},
            {},
        )
        depth = soils["grid"]["soil_depth_m_rows"][centre]
        self.assertGreater(depth[0], 0.5)
        self.assertAlmostEqual(depth[0] * (1.0 - share), depth[centre], places=3)
        # For its chemistry the cell is ground: wetter than the plain, not water.
        moisture = soils["grid"]["soil_moisture_rows"][centre]
        self.assertGreater(moisture[centre], moisture[0])
        self.assertLess(moisture[centre], 1.0)

    def test_a_lake_shore_is_wet_over_tens_of_metres_not_over_cells(self):
        for samples, spacing in ((65, 4.0), (9, 32.0)):
            rows = [[10.0] * samples for _y in range(samples)]
            cells = [[x, y] for y in range(samples) for x in range(samples // 2 + 1)]
            runoff_grid, _water = derive_surface_hydrology_grids(
                rows, [[False] * samples for _y in range(samples)],
                {"lakes": [{"cells": cells, "surface_elevation_m": 10.2}]},
                region_width_m=256.0, region_height_m=256.0,
                runoff_rows=[[15.0] * samples for _y in range(samples)],
                precipitation_rows=[[480.0] * samples for _y in range(samples)],
                potential_evaporation_rows=[[3500.0] * samples for _y in range(samples)],
            )
            row = runoff_grid["wetness_index_rows"][samples // 2]
            shore = samples // 2
            wet_m = sum(value > row[-1] + 0.005 for value in row[shore + 1:]) * spacing
            self.assertLessEqual(wet_m, 30.0 + spacing, msg=f"{spacing} m samples")
            self.assertGreaterEqual(wet_m, 30.0 - 2.0 * spacing if spacing < 30.0 else 0.0, msg=f"{spacing} m samples")


if __name__ == "__main__":
    unittest.main()
