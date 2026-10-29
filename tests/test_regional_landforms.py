import unittest
from pathlib import Path

import numpy as np

from simulations.world_gen import regional_landforms as rl
from simulations.world_gen import rock_scarps as rs
from simulations.world_gen.natural_materials import configure_material_catalog
from world.persistent_ontology_store import PersistentOntologyStore

CIRCUMFERENCE_M = 40_030_000.0


def setUpModule():
    rows = PersistentOntologyStore(
        Path(__file__).resolve().parents[1] / "ontology" / "index0.owl"
    ).load_datasets().get("materials") or []
    configure_material_catalog(rows)


def _grid(n=161, span=0.004, u0=0.25, v0=0.70):
    u = (u0 + span * np.arange(n)[None, :] / (n - 1)) * np.ones((n, 1))
    v = (v0 + span * np.arange(n)[:, None] / (n - 1)) * np.ones((1, n))
    return u, v, {"min_u": u0, "max_u": u0 + span, "min_v": v0, "max_v": v0 + span}


class ArcCacheTest(unittest.TestCase):
    def test_regional_snapshot_without_spreading_model_does_not_share_the_planet_entry(self):
        calls = []
        original = rl._build_arc_volcanoes

        def fake(tectonic_model, map_seed, circumference_m):
            calls.append(bool(tectonic_model.get("seafloor_spreading_model")))
            return [{"u": 0.1 * len(calls), "v": 0.5, "height_m": 1.0, "radius_m": 1.0}]

        rl._build_arc_volcanoes = fake
        rl._ARC_CACHE.clear()
        try:
            planet = {"map_seed": "s", "boundary_segments": [{}] * 3, "plates": [{}] * 2, "seafloor_spreading_model": {"rate_scale": 1.0}}
            regional = {"map_seed": "s", "boundary_segments": [{}] * 3, "plates": [{}] * 2}
            first = rl.arc_volcanoes(planet, CIRCUMFERENCE_M)
            second = rl.arc_volcanoes(regional, CIRCUMFERENCE_M)
        finally:
            rl._build_arc_volcanoes = original
            rl._ARC_CACHE.clear()
        self.assertEqual(calls, [True, False])
        self.assertNotEqual(first, second)


class CaprockOnVolcanoTest(unittest.TestCase):
    def _parent(self):
        u, v, _bounds = _grid()
        volcano = {"u": 0.252, "v": 0.702, "height_m": 2000.0, "radius_m": 11_000.0}
        return {
            "id": "parent",
            "heightmap_model": {
                "map_seed": "t",
                "planet_circumference_m": CIRCUMFERENCE_M,
                "regional_landforms": {"landforms": [{"landform": "volcanic_arc", "volcanoes": [volcano]}]},
            },
            "material_heatmap_model": {"layers": [
                {"material_id": "mat_sandstone", "mean_fraction": 0.4, "formation_category": "clastic_sedimentary_basin"},
                {"material_id": "mat_claystone", "mean_fraction": 0.3, "formation_category": "clastic_sedimentary_basin"},
                {"material_id": "mat_limestone", "mean_fraction": 0.3, "formation_category": "carbonate_sedimentary_basin"},
            ]},
            "water_cycle_model": {"climate_grid": {
                "annual_precipitation_rows_mm": [[250.0] * 3] * 3,
                "annual_potential_evaporation_rows_mm": [[1500.0] * 3] * 3,
            }},
        }, volcano

    def test_parent_volcano_record_rasterizes_on_the_child_grid(self):
        parent, volcano = self._parent()
        u, v, _bounds = _grid()
        edifice = rl._inherited_arc_edifices(u, v, parent)
        self.assertIsNotNone(edifice)
        row, column = np.unravel_index(np.argmax(edifice), edifice.shape)
        self.assertAlmostEqual(float(u[row, column]), volcano["u"], delta=0.0001)
        self.assertAlmostEqual(float(v[row, column]), volcano["v"], delta=0.0001)

    def test_benches_terrace_the_plateau_but_not_the_volcano(self):
        from simulations.world_gen import alluvial_fans

        parent, _volcano = self._parent()
        u, v, bounds = _grid()
        edifice = rl._inherited_arc_edifices(u, v, parent)
        # A plateau cut by a valley, with the stratovolcano on top.
        valley = 600.0 * np.exp(-(((u - 0.2535) / 0.0004) ** 2))
        elevation = 2000.0 + 3000.0 * (v - 0.70) - valley + edifice
        spacing = 0.004 / 160 * CIRCUMFERENCE_M * 0.5

        def caprock_residual(entity):
            rows, residual, diagnostics = rl.apply_regional_landforms(
                elevation.tolist(), elevation.tolist(), level=rl.CAPROCK_LEVEL, sea_level=0.0,
                source_bounds=bounds, spacing_x_m=spacing, spacing_y_m=spacing, parent_spacing_m=6 * spacing,
                root_planet=None, parent_entity=entity,
            )
            self.assertTrue([item for item in diagnostics["landforms"] if item.get("landform", "").startswith("caprock")])
            return np.asarray(residual)

        minimum_level = alluvial_fans.FAN_MIN_LEVEL
        alluvial_fans.FAN_MIN_LEVEL = 99  # isolate the caprock remap
        try:
            exempt = caprock_residual(parent)
            no_record = dict(parent, heightmap_model={**parent["heightmap_model"], "regional_landforms": {"landforms": []}})
            terraced = caprock_residual(no_record)
        finally:
            alluvial_fans.FAN_MIN_LEVEL = minimum_level
        upper_cone = edifice > 800.0
        self.assertGreater(float(np.abs(terraced[upper_cone]).mean()), 20.0)
        self.assertLess(float(np.abs(exempt[upper_cone]).mean()), 0.25 * float(np.abs(terraced[upper_cone]).mean()))

class ScarpOrdersTest(unittest.TestCase):
    """What a level builds from a layered parent, and what it hands down (``rock_scarps``)."""

    N = 241
    SPAN = 0.003

    def _layers(self):
        return {"layers": [
            {"material_id": "mat_shale", "mean_fraction": 0.5, "formation_category": "clastic_sedimentary_basin"},
            {"material_id": "mat_limestone", "mean_fraction": 0.3, "formation_category": "carbonate_sedimentary_basin"},
            {"material_id": "mat_basalt", "mean_fraction": 0.2, "formation_category": "igneous_extrusive_mafic"},
        ]}

    def _climate(self, precipitation):
        return {"climate_grid": {
            "annual_precipitation_rows_mm": [[precipitation] * 3] * 3,
            "annual_potential_evaporation_rows_mm": [[1500.0] * 3] * 3,
        }}

    def _region(self, precipitation, inflow=None, parent_rivers=None):
        """Region scale: a plain, an escarpment flank falling 3000 m over a third of the tile, a plain."""
        from simulations.world_gen import alluvial_fans

        u, _v, bounds = _grid(n=self.N, span=self.SPAN)
        spacing = self.SPAN / (self.N - 1) * CIRCUMFERENCE_M * 0.5
        across = (u - 0.25) / self.SPAN
        elevation = 3600.0 - 300.0 * across - 3000.0 * np.clip((across - 1.0 / 3.0) * 3.0, 0.0, 1.0)
        parent = {
            "id": "parent", "world_gen_seed": {"resolved_map_seed": "t"},
            "heightmap_model": {"map_seed": "t", "regional_landforms": {"landforms": []}},
            "material_heatmap_model": self._layers(), "water_cycle_model": self._climate(precipitation),
        }
        if parent_rivers is not None:
            parent["water_cycle_model"]["drainage_network_model"] = {"rivers": parent_rivers}
        minimum_level = alluvial_fans.FAN_MIN_LEVEL
        alluvial_fans.FAN_MIN_LEVEL = 99  # isolate the scarps
        try:
            rows, residual, diagnostics = rl.apply_regional_landforms(
                elevation.tolist(), elevation.tolist(), level=rl.CAPROCK_LEVEL, sea_level=0.0,
                source_bounds=bounds, spacing_x_m=spacing, spacing_y_m=spacing, parent_spacing_m=16 * spacing,
                root_planet=None, parent_entity=parent, inflow=inflow,
            )
        finally:
            alluvial_fans.FAN_MIN_LEVEL = minimum_level
        return np.asarray(rows), np.asarray(residual), diagnostics, bounds, spacing, across

    def test_a_layered_flank_breaks_into_cliffs_and_the_plains_beside_it_stay_plains(self):
        rows, residual, diagnostics, _bounds, spacing, across = self._region(precipitation=150.0)
        record = next(item for item in diagnostics["landforms"] if item.get("landform") == rs.LANDFORM_ID)
        self.assertEqual((record["built_at_level"], record["inherited"]), (2, False))
        self.assertEqual(record["cliff_forming_beds"], ["mat_basalt", "mat_limestone"])
        self.assertEqual(record["bed_thickness_m"], list(rs.BED_THICKNESS_M[2]))
        strata = record["strata"]
        self.assertEqual(strata["model"], rs.MODEL)
        self.assertEqual(len(strata["bed_materials"]), len(strata["beds"]))
        self.assertTrue(all(len(bed) == 4 for bed in strata["beds"]))
        for key in ("uv_bounds", "structure", "bed_order", "weight", "slope", "parent_spacing_m"):
            self.assertIn(key, strata)
        inner = (slice(40, 200), slice(40, 200))
        flank = (across > 0.37) & (across < 0.63)
        # Plain: beyond the half-bench a cliff at the flank's foot reaches
        # out onto (where a bed of the stack crosses the foot, ~0.1 of the tile).
        plain = (across < 0.2) | (across > 0.8)
        steepest = float(np.abs(np.diff(rows, axis=1))[inner].max()) / spacing
        smooth_slope = 3300.0 / (self.N - 1) * 3.0 / spacing
        self.assertGreater(steepest, 2.5 * smooth_slope)
        self.assertGreater(float(np.abs(residual[inner][flank[inner]]).max()), 50.0)
        # A scarp on the plain would need a run of tens of kilometres: the parent's to draw.
        self.assertLess(float(np.abs(residual[inner][plain[inner]]).max()), 1.0)
        # Mean height is kept without a box-mean correction (scarps of several
        # hundred metres; the flank's ends cut two of them short).
        self.assertLess(abs(float(residual[inner][flank[inner]].mean())), 40.0)

    def test_a_wet_climate_buries_more_of_the_face(self):
        dry = next(item for item in self._region(150.0)[2]["landforms"] if item.get("landform") == rs.LANDFORM_ID)
        wet = next(item for item in self._region(2400.0)[2]["landforms"] if item.get("landform") == rs.LANDFORM_ID)
        self.assertGreater(dry["exposed_face_share"], 0.9)
        self.assertLess(wet["exposed_face_share"], 0.5)
        self.assertLess(wet["rampart_angle_deg"], dry["rampart_angle_deg"])

    def test_the_next_level_steps_the_parents_order_again_and_cuts_its_own(self):
        from simulations.world_gen import alluvial_fans
        from simulations.world_gen.regional_refinement import _sample_bicubic_grid

        rows, _residual, diagnostics, bounds, spacing, _across = self._region(precipitation=150.0)
        parent = {
            "id": "region", "world_gen_seed": {"resolved_map_seed": "t"},
            "heightmap_model": {
                "map_seed": "t:parent", "sample_grid": {"rows": rows.tolist()},
                "source_uv_bounds": bounds, "regional_landforms": diagnostics,
            },
            "material_heatmap_model": self._layers(), "water_cycle_model": self._climate(150.0),
        }
        # Local scale: six times finer, over the middle of the flank.
        n = 181
        u0 = bounds["min_u"] + 0.44 * self.SPAN
        v0 = bounds["min_v"] + 0.44 * self.SPAN
        child_span = self.SPAN * (n - 1) / 6.0 / (self.N - 1)
        u, v, child_bounds = _grid(n=n, span=child_span, u0=u0, v0=v0)
        inherited = _sample_bicubic_grid(rows, (u - bounds["min_u"]) / self.SPAN, (v - bounds["min_v"]) / self.SPAN, wrap_x=False)
        minimum_level = alluvial_fans.FAN_MIN_LEVEL
        alluvial_fans.FAN_MIN_LEVEL = 99
        try:
            child_rows, _child_residual, child_diagnostics = rl.apply_regional_landforms(
                inherited.tolist(), inherited.tolist(), level=3, sea_level=0.0,
                source_bounds=child_bounds, spacing_x_m=spacing / 6.0, spacing_y_m=spacing / 6.0, parent_spacing_m=spacing,
                root_planet=None, parent_entity=parent,
            )
        finally:
            alluvial_fans.FAN_MIN_LEVEL = minimum_level
        orders = [item for item in child_diagnostics["landforms"] if item.get("landform") == rs.LANDFORM_ID]
        self.assertEqual([(item["built_at_level"], item["inherited"]) for item in orders], [(2, True), (3, False)])
        # Canyons are cut one level below the scarps they cut back into: none
        # at the level that built the order, a record for that order here.
        from simulations.world_gen import scarp_canyons

        self.assertFalse([item for item in diagnostics["landforms"] if item.get("landform") == scarp_canyons.LANDFORM_ID])
        canyons = [item for item in child_diagnostics["landforms"] if item.get("landform") == scarp_canyons.LANDFORM_ID]
        self.assertEqual([item["order_level"] for item in canyons], [2])
        self.assertEqual(orders[1]["bed_thickness_m"], list(rs.BED_THICKNESS_M[3]))
        # Both orders cut the planet's one stack: a finer order of it, against
        # the same reference horizon.
        coarse, fine = orders[0]["strata"], orders[1]["strata"]
        self.assertGreater(fine["bed_order"], coarse["bed_order"])
        fine_u, fine_v = rs._uv_grids(fine["uv_bounds"], (9, 9))
        np.testing.assert_allclose(rs.dip_offset(fine, fine_u, fine_v), rs.dip_offset(coarse, fine_u, fine_v), atol=5.0)
        child = np.asarray(child_rows)
        before = float(np.abs(np.diff(inherited, axis=1))[30:150, 30:150].max()) / (spacing / 6.0)
        after = float(np.abs(np.diff(child, axis=1))[30:150, 30:150].max()) / (spacing / 6.0)
        self.assertGreater(after, 1.3 * before)
        self.assertEqual(len(rs.heightmap_orders({"regional_landforms": child_diagnostics})), 2)
        # At the tile rim the child is its parent (and its neighbour).
        rim = np.ones(child.shape, dtype=bool)
        rim[1:-1, 1:-1] = False
        self.assertLess(float(np.abs(child - inherited)[rim].max()), 0.05)


class CanyonThroughParentScarpsTest(ScarpOrdersTest):
    """Streams crossing the scarps their parent built run in canyons (``scarp_canyons``)."""

    test_a_layered_flank_breaks_into_cliffs_and_the_plains_beside_it_stay_plains = None
    test_a_wet_climate_buries_more_of_the_face = None
    test_the_next_level_steps_the_parents_order_again_and_cuts_its_own = None

    def _local(self):
        from simulations.world_gen import alluvial_fans, scarp_canyons
        from simulations.world_gen.regional_refinement import _sample_bicubic_grid

        rows, _residual, diagnostics, bounds, spacing, _across = self._region(precipitation=150.0)
        parent = {
            "id": "region", "world_gen_seed": {"resolved_map_seed": "t"},
            "heightmap_model": {
                "map_seed": "t:parent", "sample_grid": {"rows": rows.tolist()},
                "source_uv_bounds": bounds, "regional_landforms": diagnostics,
            },
            "material_heatmap_model": self._layers(), "water_cycle_model": self._climate(150.0),
        }
        n = 181
        child_span = self.SPAN * (n - 1) / 6.0 / (self.N - 1)
        u, v, child_bounds = _grid(n=n, span=child_span, u0=bounds["min_u"] + 0.44 * self.SPAN, v0=bounds["min_v"] + 0.44 * self.SPAN)
        inherited = _sample_bicubic_grid(rows, (u - bounds["min_u"]) / self.SPAN, (v - bounds["min_v"]) / self.SPAN, wrap_x=False)
        minimum_level = alluvial_fans.FAN_MIN_LEVEL
        alluvial_fans.FAN_MIN_LEVEL = 99
        try:
            child_rows, _child_residual, child_diagnostics = rl.apply_regional_landforms(
                inherited.tolist(), inherited.tolist(), level=3, sea_level=0.0,
                source_bounds=child_bounds, spacing_x_m=spacing / 6.0, spacing_y_m=spacing / 6.0, parent_spacing_m=spacing,
                root_planet=None, parent_entity=parent,
            )
        finally:
            alluvial_fans.FAN_MIN_LEVEL = minimum_level
        record = next(item for item in child_diagnostics["landforms"] if item.get("landform") == scarp_canyons.LANDFORM_ID)
        return np.asarray(child_rows), record

    def test_the_flanks_streams_cut_canyons_into_the_parents_scarps(self):
        from simulations.world_gen import scarp_canyons

        cut, record = self._local()
        self.assertEqual(record["order_level"], 2)
        self.assertGreaterEqual(record["canyon_count"], 1)
        self.assertGreater(record["max_depth_m"], 30.0)
        self.assertGreater(record["longest_m"], 1000.0)
        self.assertGreater(record["canyons"][0]["catchment_km2"], 0.5)
        self.assertGreaterEqual(record["widest_floor_m"], 0.0)
        # Against the same tile with its scarps left whole.
        original = scarp_canyons.cut_canyons
        scarp_canyons.cut_canyons = lambda *args, **kwargs: (None, None, {"landform": scarp_canyons.LANDFORM_ID, "canyon_count": 0})
        try:
            whole, _record = self._local()
        finally:
            scarp_canyons.cut_canyons = original
        lowered = whole - cut
        self.assertGreater(float(lowered.max()), 30.0)
        # The tile loses rock: what the walls shed into the stream is gone,
        # what falls beside it lies as debris at their foot.
        self.assertGreater(float(lowered.mean()), 0.0)
        self.assertGreater(float(lowered.max()), float(-lowered.min()))
        # The tile rim is left alone: there the child is its parent.  (To a
        # decimetre against canyons 300 m deep: rockfall's sideways spread
        # reaches the rim cells by that much.)
        rim = np.ones(lowered.shape, dtype=bool)
        rim[1:-1, 1:-1] = False
        self.assertLess(float(np.abs(lowered[rim]).max()), 0.25)


class WaterGapTest(ScarpOrdersTest):
    """A river the parent carries crosses the scarps a level builds in a gap (``water_gap_corridor``)."""

    test_a_layered_flank_breaks_into_cliffs_and_the_plains_beside_it_stay_plains = None
    test_a_wet_climate_buries_more_of_the_face = None
    test_the_next_level_steps_the_parents_order_again_and_cuts_its_own = None

    RIVER_ROW = 120

    def test_the_parents_river_runs_through_the_scarps_at_its_own_level(self):
        # 5,000 km2 come in over the west edge and run down the flank; the parent draws rivers from 1,000 km2.
        inflow = {"cells": [[0, self.RIVER_ROW, 5.0e9]], "total_area_m2": 5.0e9}
        rows, residual, diagnostics, _bounds, _spacing, across = self._region(
            150.0, inflow=inflow, parent_rivers=[{"catchment_area_km2": 1000.0}, {"catchment_area_km2": 25000.0}])
        record = next(item for item in diagnostics["landforms"] if item.get("landform") == rs.LANDFORM_ID)
        self.assertEqual(record["water_gaps"]["parent_river_area_km2"], 1000.0)
        self.assertGreater(record["water_gaps"]["gap_cells_on_a_step"], 10)
        self.assertGreater(record["water_gaps"]["step_height_in_gaps_m"], 50.0)
        flank = (across[0] > 0.37) & (across[0] < 0.63)
        # Away from the river the flank is a staircase; along it the ground is the ground the river ran on.
        for row in (40, 80, 160, 200):
            self.assertGreater(float(np.abs(residual[row, flank]).max()), 50.0)
        self.assertLess(float(np.abs(residual[self.RIVER_ROW, flank]).max()), 1.0)
        # And the river leaves the flank as it came onto it: nothing is held up along its course.
        depth = rl.depth_under_outlet(rows, 0.0)
        self.assertLess(float(depth[self.RIVER_ROW, 5:-5].max()), 0.05)

    def test_without_river_records_there_is_no_gap(self):
        inflow = {"cells": [[0, self.RIVER_ROW, 5.0e9]], "total_area_m2": 5.0e9}
        _rows, residual, diagnostics, _bounds, _spacing, across = self._region(150.0, inflow=inflow)
        record = next(item for item in diagnostics["landforms"] if item.get("landform") == rs.LANDFORM_ID)
        self.assertIsNone(record["water_gaps"]["parent_river_area_km2"])
        flank = (across[0] > 0.37) & (across[0] < 0.63)
        self.assertGreater(float(np.abs(residual[self.RIVER_ROW, flank]).max()), 50.0)


class HeldToGroundTest(unittest.TestCase):
    """A step stands only on relief the beds give the ground (``hold_scarps_to_ground``)."""

    N = 161
    SPACING = 100.0
    # Weak mudstone, a strong cap, weak again, a strong sandstone: [base, thickness, erodibility, resistance].
    BEDS = [[0.0, 270.0, 0.88, 0.42], [270.0, 60.0, 0.41, 0.77], [330.0, 90.0, 0.88, 0.42], [420.0, 180.0, 0.46, 0.72]]

    def _order(self, horizon_north, flexure_m):
        """A level plain at 900 m over a flexure of the stack: the beds rise ``flexure_m`` southwards over 2 km.

        Returns the plain, the steps ``build_order`` would add (its recipe), the record and the grid.
        """
        from simulations.world_gen.material_routing import gaussian_blur

        span = self.SPACING * (self.N - 1) / (CIRCUMFERENCE_M * 0.5)
        u, v, bounds = _grid(n=self.N, span=span)
        ground = np.full((self.N, self.N), 900.0)
        down = np.arange(self.N)[:, None] * np.ones((1, self.N))
        structure = horizon_north + flexure_m * 0.5 * (1.0 + np.tanh((down - 80.0) / 6.0))
        strata = {
            "model": rs.MODEL, "built_at_level": 2, "bed_order": 1, "parent_spacing_m": 5000.0, "regolith_depth_m": 0.0,
            "exposure": 1.0, "rampart_gradient": 0.65, "talus_gradient": rs.TALUS_GRADIENT,
            "beds": self.BEDS, "bed_materials": ["mat_mudstone", "mat_conglomerate", "mat_mudstone", "mat_sandstone"],
            "uv_bounds": bounds, "structure": rs.coarse_grid(structure, rs.STRUCTURE_RECORD_CELLS, digits=2),
            "weight": rs.coarse_grid(np.ones(ground.shape), rs.WEIGHT_RECORD_CELLS),
        }
        dip = rs.dip_offset(strata, u, v)
        relative = gaussian_blur(ground - dip, rs.SMOOTHING_CELLS)
        fall_y, fall_x = np.gradient(relative, self.SPACING)
        strata["slope"] = rs.coarse_grid(gaussian_blur(np.hypot(fall_x, fall_y), rs.SLOPE_SMOOTHING_CELLS), rs.SLOPE_RECORD_CELLS, digits=5)
        _dip, weight, slope = rs.record_fields(strata, u, v)
        built = rs.step(relative, weight, slope, rs.scarp_transfer(strata)) - relative
        return ground, built, strata, u, v, relative

    def _held(self, ground, built, strata, u, v):
        return rl.hold_scarps_to_ground(
            built, ground, np.ones(ground.shape, dtype=bool), strata, u=u, v=v, dx=self.SPACING, dy=self.SPACING)

    def test_a_cap_the_plain_never_reaches_is_no_wall_and_its_foot_no_moat(self):
        # The plain cuts only the mudstone (130 to 250 m above the horizon); the cap is 270 m up.
        ground, built, strata, u, v, relative = self._order(650.0, 120.0)
        self.assertLess(float(relative.max()), 255.0)
        self.assertGreater(float(built.max()), 40.0)      # what the remap alone stands up
        self.assertLess(float(built.min()), -20.0)        # and the groove it cuts at the foot
        held, held_strata, record = self._held(ground, built, strata, u, v)
        after = ground + held
        self.assertLess(float(after.max()), 900.5)
        self.assertGreater(float(after.min()), 899.5)
        self.assertGreater(record["cells_held_to_the_ground_around"], 100)
        # The record is what was built: a finer level that reads it steps the same ground.
        _dip, weight, slope = rs.record_fields(held_strata, u, v)
        np.testing.assert_allclose(rs.step(relative, weight, slope, rs.scarp_transfer(held_strata)) - relative, held, atol=1e-6)

    def test_a_cap_that_crops_out_stands_as_a_hogback(self):
        # Here the plain cuts down through the cap across the flexure (350 m above the horizon to 230 m).
        ground, built, strata, u, v, relative = self._order(550.0, 120.0)
        self.assertGreater(float(relative.max()), 330.0)
        self.assertLess(float(relative.min()), 270.0)
        held, _held_strata, _record = self._held(ground, built, strata, u, v)
        after = ground + held
        self.assertGreater(float(after.max()), 920.0)     # the ridge stands over the plain
        self.assertGreater(float(after.min()), 899.5)     # with no moat beside it

    def test_a_staircase_on_a_slope_is_left_as_it_is(self):
        # The plain tilted so that it falls through the beds over the whole tile: every scarp's run is there.
        ground, _built, strata, u, v, _relative = self._order(400.0, 0.0)
        ground = ground - 0.03 * self.SPACING * np.arange(self.N)[:, None]
        from simulations.world_gen.material_routing import gaussian_blur

        dip = rs.dip_offset(strata, u, v)
        relative = gaussian_blur(ground - dip, rs.SMOOTHING_CELLS)
        fall_y, fall_x = np.gradient(relative, self.SPACING)
        strata["slope"] = rs.coarse_grid(gaussian_blur(np.hypot(fall_x, fall_y), rs.SLOPE_SMOOTHING_CELLS), rs.SLOPE_RECORD_CELLS, digits=5)
        _dip, weight, slope = rs.record_fields(strata, u, v)
        built = rs.step(relative, weight, slope, rs.scarp_transfer(strata)) - relative
        self.assertGreater(float(np.abs(built).max()), 40.0)
        held, _held_strata, record = self._held(ground, built, strata, u, v)
        inner = (slice(20, -20), slice(20, -20))
        np.testing.assert_allclose(held[inner], built[inner], atol=0.5)


class BaseLevelTest(unittest.TestCase):
    """Scarps and canyons cut down towards the sea, never under it."""

    def test_land_keeps_a_share_of_its_height_above_the_sea(self):
        ground = np.array([[-20.0, 0.4, 10.0, 60.0, 60.0, 200.0]])
        change = np.array([[-5.0, -3.0, -40.0, -80.0, -10.0, 30.0]])
        held = rl.hold_above_base_level(change, ground, 0.0)
        after = ground + held
        self.assertEqual(float(held[0, 0]), -5.0)                         # the sea bed is not this rule's
        self.assertAlmostEqual(float(after[0, 1]), 0.4 * rl.BASE_LEVEL_SHARE)
        self.assertAlmostEqual(float(after[0, 2]), 10.0 * rl.BASE_LEVEL_SHARE)
        self.assertAlmostEqual(float(after[0, 3]), 60.0 * rl.BASE_LEVEL_SHARE)   # an 80 m cut held at 9 m
        self.assertEqual(float(held[0, 4]), -10.0)                        # a cut that stays above is left
        self.assertEqual(float(held[0, 5]), 30.0)                         # and so is ground that rises
        self.assertTrue((after[0, 1:] > 0.0).all())

    def test_the_datum_is_the_sea_level_given(self):
        held = rl.hold_above_base_level(np.array([[-500.0]]), np.array([[-1900.0]]), -2000.0)
        self.assertAlmostEqual(float(-1900.0 + held[0, 0]), -2000.0 + 100.0 * rl.BASE_LEVEL_SHARE)


class OutletHoldTest(unittest.TestCase):
    """The rock steps leave no ground deeper under its outlet than it was."""

    def _valley(self):
        """A valley falling 1 m a cell eastwards to the sea, between sides 30 m higher."""
        ground = (60.0 - np.arange(64, dtype=float))[None, :] * np.ones((21, 1))
        ground[:6, :] += 30.0
        ground[-6:, :] += 30.0
        return ground

    def test_ground_that_drains_has_no_depth_under_its_outlet(self):
        self.assertLess(float(rl.depth_under_outlet(self._valley(), 0.0).max()), 0.01)

    def test_a_tread_cut_below_its_lip_comes_back_up_to_it(self):
        ground = self._valley()
        change = np.zeros(ground.shape)
        change[8:13, 20:30] = -12.0                                # a bench floor 12 m down, its lip left standing
        self.assertGreater(float(rl.depth_under_outlet(ground + change, 0.0).max()), 10.0)
        held, cells = rl.hold_above_outlets(change, ground, 0.0)
        after = ground + held
        self.assertGreater(cells, 30)
        self.assertLess(float(rl.depth_under_outlet(after, 0.0).max()), 0.05)
        sill = float(ground[10, 30])                               # the first cell below the cut
        self.assertLess(float(np.abs(after[8:13, 20:30] - np.minimum(ground[8:13, 20:30], sill)).max()), 0.05)
        self.assertTrue((after <= ground + 1e-9).all())             # nothing stands higher than it did
        outside = np.ones(ground.shape, dtype=bool)
        outside[8:13, 20:30] = False
        self.assertEqual(float(np.abs(held[outside]).max()), 0.0)

    def test_ground_behind_a_bed_raised_across_the_valley_stands_level_with_it(self):
        ground = self._valley()
        change = np.zeros(ground.shape)
        change[:, 40:43] = 8.0                                     # a bed 8 m proud, right across
        held, cells = rl.hold_above_outlets(change, ground, 0.0)
        after = ground + held
        self.assertGreater(cells, 20)
        self.assertLess(float(rl.depth_under_outlet(after, 0.0).max()), 0.05)
        lip = float(ground[10, 40]) + 8.0                          # the bed's highest cell on the way out
        np.testing.assert_allclose(after[10, 34:40], lip, atol=0.05)    # the valley floor behind it
        self.assertEqual(float(np.abs(held[:, 43:]).max()), 0.0)        # downstream as the steps left it
        np.testing.assert_allclose(held[:, 40:43], 8.0, atol=0.05)      # the bed itself too

    def test_a_cut_that_drains_is_left_as_it_is(self):
        ground = self._valley()
        change = np.zeros(ground.shape)
        change[8:13, 20:] = -6.0                                   # a canyon cut all the way down to the sea
        held, cells = rl.hold_above_outlets(change, ground, 0.0)
        self.assertEqual(cells, 0)
        np.testing.assert_array_equal(held, change)

    def test_a_hollow_the_ground_had_keeps_its_depth(self):
        ground = self._valley()
        ground[9:12, 24:28] -= 9.0                                 # a pan the steps did not make
        change = np.zeros(ground.shape)
        change[:, 50:] = -2.0                                      # steps elsewhere, draining
        before = rl.depth_under_outlet(ground, 0.0)
        self.assertGreater(float(before.max()), 7.0)
        held, cells = rl.hold_above_outlets(change, ground, 0.0)
        self.assertEqual(cells, 0)
        np.testing.assert_array_equal(held, change)
        deeper = change.copy()
        deeper[9:12, 24:28] = -5.0                                 # and steps that deepen it by 5 m
        held, cells = rl.hold_above_outlets(deeper, ground, 0.0)
        self.assertEqual(cells, 12)
        np.testing.assert_allclose(rl.depth_under_outlet(ground + held, 0.0)[9:12, 24:28], before[9:12, 24:28], atol=0.05)

    def test_no_change_is_no_work(self):
        ground = self._valley()
        held, cells = rl.hold_above_outlets(np.zeros(ground.shape), ground, 0.0)
        self.assertEqual(cells, 0)
        self.assertFalse(held.any())


class SeaCliffTest(unittest.TestCase):
    """Waves cut a platform and a cliff into a rock shore (``sea_cliffs``)."""

    N = 161
    SPACING = 40.0

    def _shore(self, rock, level=3, parent_spacing=234.0):
        from simulations.world_gen import alluvial_fans, sea_cliffs

        span = self.SPACING * (self.N - 1) / (CIRCUMFERENCE_M * 0.5)
        u, _v, bounds = _grid(n=self.N, span=span)
        # Land rising 4 % eastwards out of the sea; the shore runs north-south a third of the way in.
        east = (np.arange(self.N) - self.N // 3 + 0.5) * self.SPACING
        elevation = (0.04 * east)[None, :] * np.ones((self.N, 1))
        # The parent: a coarse grid around the tile with the ocean on its western half, and a 4 m/s wind.
        wide = {"min_u": bounds["min_u"] - 20 * span, "max_u": bounds["max_u"] + 20 * span,
                "min_v": bounds["min_v"] - 13 * span, "max_v": bounds["max_v"] + 13 * span}
        parent_rows = np.where(np.arange(60)[None, :] < 30, -400.0, 300.0) * np.ones((40, 1))
        wind = np.zeros((6, 6, 3))
        wind[..., 2] = 4.0
        parent = {
            "id": "parent",
            "heightmap_model": {
                "map_seed": "t", "sample_grid": {"rows": parent_rows.tolist()}, "source_uv_bounds": wide, "sea_level_m": 0.0,
                "sample_spacing_x_m": 41 * self.SPACING * (self.N - 1) / 59, "regional_landforms": {"landforms": []},
            },
            "material_heatmap_model": {"layers": [{"material_id": rock, "mean_fraction": 1.0, "formation_category": "plutonic"}]},
            "water_cycle_model": {"climate_grid": {
                "prevailing_wind_rows": wind.tolist(),
                "annual_precipitation_rows_mm": [[800.0] * 3] * 3, "annual_potential_evaporation_rows_mm": [[900.0] * 3] * 3,
            }},
        }
        minimum_level = alluvial_fans.FAN_MIN_LEVEL
        alluvial_fans.FAN_MIN_LEVEL = 99
        try:
            rows, _residual, diagnostics = rl.apply_regional_landforms(
                elevation.tolist(), elevation.tolist(), level=level, sea_level=0.0, source_bounds=bounds,
                spacing_x_m=self.SPACING, spacing_y_m=self.SPACING, parent_spacing_m=parent_spacing, root_planet=None, parent_entity=parent,
            )
        finally:
            alluvial_fans.FAN_MIN_LEVEL = minimum_level
        record = next(item for item in diagnostics["landforms"] if item.get("landform") == sea_cliffs.LANDFORM_ID)
        return elevation, np.asarray(rows), record

    def test_a_weak_rock_shore_is_cut_back_to_a_platform_and_a_cliff(self):
        before, after, record = self._shore("mat_shale")
        self.assertGreater(record["cut_cells"], 50)
        self.assertEqual(record["waves"]["source"], "open_water_of_the_parent_grid")
        self.assertGreater(record["wave_height_m"][1], 1.0)
        middle = self.N // 2
        shore = lambda rows: int(np.flatnonzero(rows[middle] >= 0.0)[0])  # noqa: E731
        self.assertGreater(shore(after), shore(before))                 # the shoreline has moved inland
        steepest = lambda rows: float(np.abs(np.diff(rows[middle])).max()) / self.SPACING  # noqa: E731
        self.assertGreater(steepest(after), 2.0 * steepest(before))     # a cliff where there was a ramp
        lowered = before - after
        self.assertGreater(float(lowered.max()), 2.0)
        self.assertLess(float(lowered[before < 0.0].max()), 1e-6)          # the sea bed is not cut (sand may lie on it)
        self.assertLess(float(np.abs(lowered[0]).max()), 1e-6)             # nor the tile rim
        # Shale lies back behind its platform: nothing stands steeper than debris rests.
        self.assertLess(steepest(after), 0.9)

    def test_strong_rock_is_left_to_the_finer_levels(self):
        before, after, record = self._shore("mat_granite")
        self.assertEqual(record["cut_cells"], 0)
        self.assertLess(float((before - after).max()), 1e-6)            # nothing is cut; the beach may lay sand
        self.assertIn("height_m", record["waves"])                      # the children still learn their waves

    def test_the_shallow_water_in_front_has_taken_its_share(self):
        _before, _after, record = self._shore("mat_shale")
        # The sea bed falls 4 % here: deep water is tens of metres out, and the waves cross that first.
        self.assertGreater(record["spent_on_the_water_in_front"], 0.05)
        self.assertLess(record["spent_on_the_water_in_front"], 0.6)


class BedrockMixTest(unittest.TestCase):
    def test_the_beds_are_the_rock_under_the_mantle_not_the_mantle(self):
        parent = {"material_heatmap_model": {"layers": [
            {"material_id": "mat_saprolite", "mean_fraction": 0.8, "distribution_role": "surface_cover", "formation_category": "saprolitic_regolith"},
            {"material_id": "mat_shale", "mean_fraction": 0.12, "distribution_role": "bedrock", "formation_category": "clastic_sedimentary_basin"},
            {"material_id": "mat_limestone", "mean_fraction": 0.08, "distribution_role": "bedrock", "formation_category": "carbonate_sedimentary_basin"},
        ]}}
        mix = rl._parent_rock_mix(parent)
        self.assertEqual({item[0] for item in mix}, {"mat_shale", "mat_limestone"})
        layered, share = rl._layered_rocks(mix)
        self.assertAlmostEqual(share, 1.0)
        self.assertGreater(rs.face_gradient(dict((item[0], item[3]) for item in layered)["mat_limestone"]), 1.0)
        self.assertEqual(rs.face_gradient(dict((item[0], item[3]) for item in layered)["mat_shale"]), 0.0)
        # Layers without roles (a planet's list) are all read.
        bare = {"material_heatmap_model": {"layers": [dict(layer, distribution_role=None) for layer in parent["material_heatmap_model"]["layers"]]}}
        self.assertEqual(len(rl._parent_rock_mix(bare)), 3)

    def test_a_step_lower_than_the_soil_is_deep_stays_buried(self):
        beds = [[0.0, 3.0, 0.72, 0.34], [3.0, 1.0, 0.38, 0.72], [4.0, 3.0, 0.72, 0.34]]
        record = {"beds": beds, "exposure": 1.0, "rampart_gradient": 0.65}
        smooth = np.linspace(0.0, 7.0, 701)
        slope = np.full(smooth.shape, 0.2)
        bare = rs.step(smooth, 1.0, slope, rs.scarp_transfer(dict(record, regolith_depth_m=0.3)))
        buried = rs.step(smooth, 1.0, slope, rs.scarp_transfer(dict(record, regolith_depth_m=1.5)))
        self.assertGreater(float(np.abs(bare - smooth).max()), 0.3)
        np.testing.assert_allclose(buried, smooth, atol=1e-9)


if __name__ == "__main__":
    unittest.main()
