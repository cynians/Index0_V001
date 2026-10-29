"""Rivers handed from a map to its child: flats, mouths, inherited trunks, the water an inflow brings.

From the consistency walk of 2026-10-20 (docs/LOD_Worldgen_Procedure.md
section 8, "Consistency walk").
"""

import math
import unittest
from collections import defaultdict

import numpy as np

from simulations.world_gen import drainage
from simulations.world_gen import material_routing as routing


def _looped_cells(downstream):
    incoming = defaultdict(int)
    for target in downstream.values():
        if target is not None:
            incoming[target] += 1
    stack = [cell for cell in downstream if not incoming[cell]]
    while stack:
        target = downstream.get(stack.pop())
        if target is not None:
            incoming[target] -= 1
            if not incoming[target]:
                stack.append(target)
    return [cell for cell, count in incoming.items() if count > 0]


def _bowl(n=60):
    ys, xs = np.mgrid[0:n, 0:n].astype(float)
    rows = 100.0 + 0.02 * ((xs - n / 2) ** 2 + (ys - n / 2) ** 2)
    rows[n // 2, int(0.9 * n):] = 90.0  # one gap to the east edge
    return rows


class FlatRoutingTests(unittest.TestCase):
    def test_a_filled_basin_drains_without_loops_and_not_in_grid_lines(self):
        rows = _bowl()
        ocean = np.zeros(rows.shape, dtype=bool).tolist()
        filled, parent, _order = drainage._priority_flood(rows.tolist(), ocean, False)
        downstream = drainage._terrain_flow_directions(rows.tolist(), filled, parent, ocean, False)
        self.assertEqual([], _looped_cells(downstream))
        raised = [(x, y) for y in range(rows.shape[0]) for x in range(rows.shape[1]) if filled[y][x] > rows[y, x]]
        self.assertGreater(len(raised), 500)
        # Epsilon rings drain a flat in the eight grid directions only; the
        # flat's potential turns flow towards the basin's axis, so paths
        # through the flat change direction instead of running straight.
        turns = 0
        for cell in raised[::7]:
            path = [cell]
            while downstream.get(path[-1]) is not None and len(path) < 400:
                path.append(downstream[path[-1]])
            steps = {(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:]) if a in set(raised)}
            turns += len(steps) > 1
        self.assertGreater(turns, 0)

    def test_rounded_heights_never_make_a_loop(self):
        rng = np.random.default_rng(3)
        n = 120
        rows = np.round(rng.random((n, n)) * 2.0 + np.linspace(0.0, 5.0, n)[None, :], 1)
        ocean = np.zeros((n, n), dtype=bool)
        ocean[:, 0] = True
        filled, parent, _order = drainage._priority_flood(rows.tolist(), ocean.tolist(), False)
        downstream = drainage._terrain_flow_directions(rows.tolist(), filled, parent, ocean.tolist(), False)
        self.assertEqual([], _looped_cells(downstream))

    def test_all_runoff_reaches_the_outlet(self):
        rows = _bowl()
        n = rows.shape[0]
        ocean = np.zeros(rows.shape, dtype=bool)
        ocean[:, -1] = True
        network = drainage.derive_drainage_network(
            rows.tolist(), ocean.tolist(), np.full(rows.shape, 100.0).tolist(),
            wrap_x=False, detail_level=3, represented_area_m2=n * n * 1.0e6,
        )
        accumulation = np.asarray(network["flow_accumulation_rows"], dtype=float)
        self.assertAlmostEqual(100.0 * (n * n - n), float(accumulation.max()), delta=100.0 * n + 1.0)


class MouthTests(unittest.TestCase):
    def test_a_segment_that_joins_another_does_not_reach_the_sea(self):
        n = 40
        ys, xs = np.mgrid[0:n, 0:n].astype(float)
        rows = 500.0 - 10.0 * xs + 20.0 * np.abs(ys - n / 2)
        ocean = (xs >= n - 2).tolist()
        network = drainage.derive_drainage_network(
            rows.tolist(), ocean, np.full(rows.shape, 400.0).tolist(),
            wrap_x=False, detail_level=0, represented_area_m2=n * n * 1.0e8,
        )
        joined = [river for river in network["rivers"] if river.get("joins_river_id")]
        self.assertTrue(joined)
        for river in joined:
            self.assertEqual("confluence", river["mouth"])
        self.assertTrue(set(network["delta_candidate_river_ids"]).isdisjoint(river["id"] for river in joined))


class TrunkInheritanceTests(unittest.TestCase):
    def _parent(self, strong_elsewhere):
        rivers = [
            {"id": f"river_{index:03d}", "stream_order": 6, "flow": 1.0,
             "points": [{"x": 0.05, "y": 0.02 + 0.01 * index}, {"x": 0.15, "y": 0.02 + 0.01 * index}]}
            for index in range(strong_elsewhere)
        ]
        rivers.append({"id": "river_cross", "stream_order": 3, "flow": 0.6, "mouth": "ocean",
                       "points": [{"x": 0.5, "y": 0.2}, {"x": 0.5, "y": 0.8}]})
        return {"detail_level": 2, "rivers": rivers, "lakes": []}

    def test_the_cap_counts_trunks_that_cross_the_child(self):
        bounds = {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0}
        child_bounds = {"min_u": 0.4, "max_u": 0.6, "min_v": 0.4, "max_v": 0.6}
        child = drainage.inherit_parent_drainage(self._parent(40), {"rivers": [], "lakes": []}, child_bounds, bounds)
        self.assertEqual(1, child["inherited_parent_trunk_count"])

    def test_a_trunk_follows_the_child_flow_and_stops_at_its_coast(self):
        n = 50
        # The child's own valley bends: it runs south, then east to a sea in the east.
        accumulation = np.zeros((n, n))
        for y in range(0, 30):
            accumulation[y, 10] = 1000.0 + y
        for x in range(10, n - 8):
            accumulation[30, x] = 2000.0 + x
        bounds = {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0}
        child_bounds = {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0}
        parent = {"detail_level": 1, "lakes": [], "rivers": [
            {"id": "river_001", "stream_order": 4, "flow": 1.0, "mouth": "ocean",
             "points": [{"x": 10 / (n - 1), "y": 0.0}, {"x": 1.3, "y": 1.3}]},
        ]}
        child = drainage.inherit_parent_drainage(
            parent, {"rivers": [], "lakes": [], "flow_accumulation_rows": accumulation.tolist()}, child_bounds, bounds,
        )
        trunk = next(river for river in child["rivers"] if river.get("inherited_from_parent"))
        self.assertEqual("traced_on_child_flow", trunk["geometry_source"])
        end = trunk["points"][-1]
        self.assertAlmostEqual((n - 9) / (n - 1), end["x"], places=3)
        self.assertAlmostEqual(30 / (n - 1), end["y"], places=3)
        self.assertLess(len(trunk["points"]), 8)  # kept at its bends, not one point a cell


class InflowClimateTests(unittest.TestCase):
    def test_a_crossing_carries_its_catchment_mean_not_the_tile_mean(self):
        def surface(x, y):
            return 1000.0 - 5.0 * x + 30.0 * np.abs(y - 10.0)

        parent_h, parent_w = 21, 41
        ys, xs = np.mgrid[0:parent_h, 0:parent_w].astype(float)
        parent = surface(xs, ys)
        land = xs < parent_w - 1
        parent_bounds = {"min_u": 0.0, "max_u": 1.0, "min_v": 0.0, "max_v": 1.0}
        child_bounds = {"min_u": 0.5, "max_u": 0.75, "min_v": 0.3, "max_v": 0.7}
        child_h, child_w = 33, 41
        child_x = (child_bounds["min_u"] + 0.25 * np.arange(child_w) / (child_w - 1)) * (parent_w - 1)
        child_y = (child_bounds["min_v"] + 0.4 * np.arange(child_h) / (child_h - 1)) * (parent_h - 1)
        child = surface(child_x[None, :], child_y[:, None])
        # Wet headwaters, a dry tile: upstream (west of the child) 300 mm, elsewhere 10 mm.
        runoff = np.where(xs < child_x[0], 300.0, 10.0)
        record = routing.boundary_inflow(
            parent, land, parent_bounds, 1.0e6, child, child_bounds, parent_dx=1000.0, parent_dy=1000.0,
            parent_fields={"runoff": runoff},
        )
        cells = record["cells"]
        means = record["catchment_means_mm"]["runoff"]
        self.assertEqual(len(cells), len(means))
        index = max(range(len(cells)), key=lambda i: cells[i][2])
        self.assertGreater(means[index], 250.0)

        # What the parent's own inflow brought is carried on as its own climate.
        parent_inflow = np.zeros(parent.shape)
        parent_inflow[10, 0] = 5.0e10
        brought = np.zeros(parent.shape)
        brought[10, 0] = 5.0e10 * 20.0
        chained = routing.boundary_inflow(
            parent, land, parent_bounds, 1.0e6, child, child_bounds, parent_dx=1000.0, parent_dy=1000.0,
            parent_inflow=parent_inflow, parent_fields={"runoff": runoff}, parent_inflow_fields={"runoff": brought},
        )
        index = max(range(len(chained["cells"])), key=lambda i: chained["cells"][i][2])
        area = chained["cells"][index][2]
        expected = (5.0e10 * 20.0 + (area - 5.0e10) * 300.0) / area
        self.assertAlmostEqual(expected, chained["catchment_means_mm"]["runoff"][index], delta=0.5)
        self.assertTrue(math.isfinite(expected))


if __name__ == "__main__":
    unittest.main()
