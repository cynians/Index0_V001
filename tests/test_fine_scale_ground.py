"""Fine ground (LOD4+): water read off the heightfield, relic channels, inherited soil."""
import unittest

import numpy as np

from simulations.world_gen import alluvial_channels as ac
from simulations.world_gen import fine_hydrology as fh
from simulations.world_gen import floodplain_relics as fr
from simulations.world_gen.exact_rounding import height_decimals
from simulations.world_gen.regolith_soils import derive_regolith_soil_model

PARENT_BOUNDS = {"min_u": 0.1, "max_u": 0.1001, "min_v": 0.5, "max_v": 0.50006}


def _rows(value, size=4):
    return [[value] * size for _ in range(size)]


def _climate(runoff_mm=300.0, precipitation_mm=900.0, evaporation_mm=1000.0, recharge_mm=100.0):
    return {
        "annual_runoff_rows_mm": _rows(runoff_mm),
        "annual_precipitation_rows_mm": _rows(precipitation_mm),
        "annual_potential_evaporation_rows_mm": _rows(evaporation_mm),
        "annual_groundwater_recharge_rows_mm": _rows(recharge_mm),
    }


def _water_cycle(rivers=(), **climate):
    rivers = list(rivers)
    return {
        "status": "water_cycle_seeded",
        "climate_grid": _climate(**climate),
        "drainage_network_model": {"rivers": rivers, "ephemeral_channels": [], "grid_width": 4, "grid_height": 4},
        "runoff_grid": {}, "surface_water_grid": {}, "rivers": rivers, "lakes": [],
    }


def _river_parent(*, dx=8.0, width=240, height=140, slope=0.003, inflow_m2=3.5e10, runoff_mm=24.0):
    """A Site-scale parent with one carved river on a plain, as a refinement leaves it."""
    x = np.arange(width) * dx
    y = np.arange(height) * dx
    across = np.abs(y[:, None] - y[height // 2])
    elevation = 300.0 - slope * x[None, :] + 0.002 * across + np.zeros((height, 1))
    heightmap = {
        "map_seed": "relic-test", "map_detail_level": 4, "source_uv_bounds": dict(PARENT_BOUNDS),
        "sample_spacing_x_m": dx, "sample_spacing_y_m": dx,
    }
    _dx, _dy, to_local, to_uv = ac.local_frame(heightmap, elevation.shape)
    inflow = np.zeros(elevation.shape)
    inflow[height // 2, 0] = inflow_m2 / (dx * dx)
    parent_of_parent = {
        "id": "local", "heightmap_model": {"map_seed": "relic-test"},
        "water_cycle_model": {"climate_grid": _climate(runoff_mm=runoff_mm, precipitation_mm=570.0, evaporation_mm=2300.0)},
        "world_gen_seed": {"derived_planet_physics": {"surface_gravity_m_s2": 9.81}},
    }
    residual, record = ac.alluvial_channel_residual(
        elevation, np.ones(elevation.shape, dtype=bool), level=4, dx=dx, dy=dx, parent_spacing_m=53.0,
        parent_entity=parent_of_parent, to_local=to_local, to_uv=to_uv, seed_text="relic-test", inflow_cells=inflow,
    )
    heightmap["sample_grid"] = {"rows": (elevation + residual).tolist()}
    heightmap["regional_landforms"] = {"level": 4, "landforms": [record]}
    return {"id": "site", "heightmap_model": heightmap, "map_detail_level": 4}, ((width - 1) * dx, (height - 1) * dx)


def _child_frame(parent_size_m, origin_m, size_m, shape):
    """A child heightmap frame over ``size_m`` of the parent at ``origin_m`` (both in metres)."""
    width_m, height_m = parent_size_m
    u_span = PARENT_BOUNDS["max_u"] - PARENT_BOUNDS["min_u"]
    v_span = PARENT_BOUNDS["max_v"] - PARENT_BOUNDS["min_v"]
    bounds = {
        "min_u": PARENT_BOUNDS["min_u"] + u_span * origin_m[0] / width_m,
        "max_u": PARENT_BOUNDS["min_u"] + u_span * (origin_m[0] + size_m[0]) / width_m,
        "min_v": PARENT_BOUNDS["min_v"] + v_span * origin_m[1] / height_m,
        "max_v": PARENT_BOUNDS["min_v"] + v_span * (origin_m[1] + size_m[1]) / height_m,
    }
    return {
        "source_uv_bounds": bounds,
        "sample_spacing_x_m": size_m[0] / (shape[1] - 1), "sample_spacing_y_m": size_m[1] / (shape[0] - 1),
    }


def _relics(parent, parent_size_m, *, origin_m, size_m=(240.0, 160.0), shape=(161, 241), level=5, parent_spacing=8.0):
    frame = _child_frame(parent_size_m, origin_m, size_m, shape)
    dx, dy, to_local, _to_uv = ac.local_frame(frame, shape)
    elevation = np.full(shape, 296.0)
    residual, record = fr.relic_channel_residual(
        elevation, np.ones(shape, dtype=bool), level=level, dx=dx, dy=dy, parent_spacing_m=parent_spacing,
        parent_entity=parent, to_local=to_local, channel_record={},
    )
    return residual, record, frame, elevation


class HeightStorageTest(unittest.TestCase):
    def test_fine_levels_keep_more_than_centimetres(self):
        self.assertEqual(height_decimals(8.0), 2)
        self.assertEqual(height_decimals(53.0), 2)
        self.assertGreaterEqual(height_decimals(0.78), 3)
        self.assertGreaterEqual(height_decimals(0.1), 3)
        # Unknown spacing (planet maps) keeps the old precision.
        self.assertEqual(height_decimals(None), 2)


class FineHydrologyTest(unittest.TestCase):
    def _hollow(self, level=5):
        size, dx = 81, 1.0
        x = (np.arange(size) - size // 2) * dx
        # A slope with one hollow down its middle and noses either side.
        elevation = 100.0 - 0.05 * np.arange(size)[:, None] * dx + 0.002 * x[None, :] ** 2
        return {
            "map_detail_level": level, "sample_grid": {"rows": elevation.tolist()},
            "sample_spacing_x_m": dx, "sample_spacing_y_m": dx, "sea_level_m": None,
        }, elevation

    def test_levels_coarser_than_site_are_left_alone(self):
        heightmap, _elevation = self._hollow(level=3)
        water = _water_cycle()
        self.assertIs(fh.refine_surface_hydrology(heightmap, water), water)
        heightmap, _elevation = self._hollow(level=4)
        self.assertIn("fine_surface_hydrology", fh.refine_surface_hydrology(heightmap, water))

    def test_phantom_streams_are_no_rivers_and_no_water(self):
        heightmap, _elevation = self._hollow()
        trickles = [
            {"id": f"river_{index}", "estimated_discharge_m3_s": 0.0, "flow_regime": "intermittent",
             "points": [{"x": 0.5, "y": 0.1}, {"x": 0.5, "y": 0.9}]}
            for index in range(40)
        ]
        water = fh.refine_surface_hydrology(heightmap, _water_cycle(trickles))
        self.assertEqual(water["rivers"], [])
        self.assertEqual(water["river_count"], 0)
        self.assertEqual(water["fine_surface_hydrology"]["unchannelised_flow_path_count"], 40)
        presence = np.asarray(water["surface_water_grid"]["water_presence_rows"])
        self.assertFalse(presence.any())
        self.assertEqual(float(np.asarray(water["runoff_grid"]["channel_presence_rows"]).max()), 0.0)

    def test_a_brook_is_one_thread_of_water_down_the_hollow_and_a_pond_on_its_way_passes_it_on(self):
        heightmap, elevation = self._hollow()
        size = elevation.shape[0]
        centre = size // 2
        runoff_m_s = 300.0 / 1000.0 / fh.SECONDS_PER_YEAR
        # Thirty litres a second come in at the head of the hollow: a brook too narrow for a metre cell to carve.
        brook = dict(heightmap, boundary_inflow={"cells": [[centre, 0, 0.03 / runoff_m_s]]})
        water = fh.refine_surface_hydrology(brook, _water_cycle())
        presence = np.asarray(water["surface_water_grid"]["water_presence_rows"], dtype=bool)
        self.assertTrue(presence[:, centre].all())                       # from the rim it enters by to the rim it leaves by
        self.assertEqual(int(presence.sum()), size)                      # one cell wide, and nothing beside it
        self.assertGreater(float(np.asarray(water["surface_water_grid"]["water_depth_m_rows"])[presence].min()), 0.0)
        self.assertEqual(water["fine_surface_hydrology"]["uncarved_stream_cell_fraction"], round(size / size ** 2, 5))
        # The same brook with a pond dug into its course: water above the pond, in it, and below it again.
        y, x = np.mgrid[0:size, 0:size]
        pond = elevation - 0.8 * np.clip(1.0 - np.hypot(x - centre, y - 30) / 6.0, 0.0, 1.0)
        dammed = dict(brook, sample_grid={"rows": pond.tolist()})
        cycle = _water_cycle()
        cycle["lakes"] = [{"id": "pond", "cells": [], "surface_elevation_m": float(elevation[30, centre]) - 0.25,
                           "bounds": {"min_x": 0.4, "max_x": 0.6, "min_y": 0.28, "max_y": 0.46}}]
        refined = fh.refine_surface_hydrology(dammed, cycle)
        presence = np.asarray(refined["surface_water_grid"]["water_presence_rows"], dtype=bool)
        self.assertTrue(presence[30, centre] and presence[30, centre + 2])   # the pond, wider than a thread
        self.assertTrue(presence[5:20, centre].all())                        # the brook above it
        self.assertTrue(presence[45:, centre].all())                         # and below it, where it used to end
        self.assertFalse(presence[60, centre + 3])

    def test_hollows_are_wetter_than_noses_and_no_water_is_added(self):
        heightmap, _elevation = self._hollow()
        water = fh.refine_surface_hydrology(heightmap, _water_cycle())
        wetness = np.asarray(water["runoff_grid"]["wetness_index_rows"])
        centre = wetness.shape[1] // 2
        hollow = float(wetness[40:70, centre - 1:centre + 2].mean())
        nose = float(wetness[40:70, 5:12].mean())
        self.assertGreater(hollow, nose + 0.1)
        # The coarse levels' index for this climate, with nothing redistributed.
        supply = 300.0 + 0.7 * 100.0 + 0.08 * 900.0
        uniform = 0.04 + 0.68 * supply / (supply + 1000.0)
        self.assertLess(nose, uniform)
        self.assertGreater(hollow, uniform)
        low, middle, high = water["fine_surface_hydrology"]["redistribution_share_p05_p50_p95"]
        self.assertLess(low, middle)
        self.assertLess(middle, 1.0)
        self.assertGreater(high, 1.0)

    def test_a_lake_the_parent_hands_down_as_a_box_is_water_with_a_wet_shore(self):
        size = 81
        y, x = np.mgrid[0:size, 0:size]
        # A bowl one metre deep in level ground.
        bowl = 100.0 - np.clip(1.0 - np.hypot(x - 40, y - 40) / 15.0, 0.0, 1.0)
        heightmap = {
            "map_detail_level": 5, "sample_grid": {"rows": bowl.tolist()},
            "sample_spacing_x_m": 1.0, "sample_spacing_y_m": 1.0, "sea_level_m": None,
        }
        water = _water_cycle()
        water["lakes"] = [{"id": "lake", "cells": [], "surface_elevation_m": 99.6,
                           "bounds": {"min_x": 0.2, "max_x": 0.8, "min_y": 0.2, "max_y": 0.8}}]
        refined = fh.refine_surface_hydrology(heightmap, water)
        presence = np.asarray(refined["surface_water_grid"]["water_presence_rows"])
        depth = np.asarray(refined["surface_water_grid"]["water_depth_m_rows"])
        self.assertTrue(presence[40, 40])
        self.assertAlmostEqual(float(depth[40, 40]), 0.6, delta=0.01)
        # Only the part of the bowl below the lake's level.
        self.assertFalse(presence[40, 40 + 13])
        wetness = np.asarray(refined["runoff_grid"]["wetness_index_rows"])
        shore = float(wetness[40, 40 + 11])
        far = float(wetness[5, 5])
        self.assertGreater(shore, far + 0.1)

    def test_multiple_flow_accumulation_conserves_and_spreads(self):
        size = 41
        # A cone: flow from the top spreads all round instead of down eight lines.
        y, x = np.mgrid[0:size, 0:size]
        cone = 50.0 - np.hypot(x - size // 2, y - size // 2)
        sinks = np.zeros(cone.shape, dtype=bool)
        sinks[0, :] = sinks[-1, :] = sinks[:, 0] = sinks[:, -1] = True
        accumulation, _filled = fh.multiple_flow_accumulation(cone, np.ones(cone.shape), sinks, dx=1.0, dy=1.0)
        # Every cell ends in a sink, and sinks pass nothing on.
        self.assertAlmostEqual(float(accumulation[sinks].sum()), float(size * size), delta=1e-6 * size * size)
        ring = accumulation[size // 2 + np.rint(12 * np.sin(np.linspace(0, 2 * np.pi, 48, endpoint=False))).astype(int),
                            size // 2 + np.rint(12 * np.cos(np.linspace(0, 2 * np.pi, 48, endpoint=False))).astype(int)]
        self.assertLess(float(ring.max() / ring.min()), 4.0)

    def test_water_and_wet_margin_follow_the_carved_channel(self):
        parent, parent_size = _river_parent()
        shape = (201, 241)
        frame = _child_frame(parent_size, (600.0, 460.0), (240.0, 200.0), shape)
        heightmap = dict(frame)
        channel_record = parent["heightmap_model"]["regional_landforms"]["landforms"][0]
        heightmap.update({
            "map_detail_level": 5, "sea_level_m": None,
            "regional_landforms": {"landforms": [dict(channel_record, inherited_reaches=channel_record["reaches"], reaches=[])]},
        })
        fields = ac.channel_fields(channel_record["reaches"], shape, dx=frame["sample_spacing_x_m"], dy=frame["sample_spacing_y_m"],
                                   to_local=ac.local_frame(frame, shape)[2])
        self.assertTrue(fields["in_channel"].any())
        ground = np.where(np.isfinite(fields["stage_m"]), fields["stage_m"], 296.0) + 0.6
        # The carved section below the banks, a terrace 3 m up on one side.
        channel_row = int(np.mean(np.nonzero(fields["in_channel"])[0]))
        terrace = np.where(np.arange(shape[0])[:, None] < channel_row, 3.0, 0.0) * np.ones((1, shape[1]))
        elevation = np.where(fields["in_channel"], fields["bank"] - fields["depth"], ground + terrace)
        heightmap["sample_grid"] = {"rows": elevation.tolist()}
        trunk = {"id": "trunk", "estimated_discharge_m3_s": 15.0, "flow_regime": "intermittent",
                 "points": [{"x": 0.0, "y": 0.5}, {"x": 1.0, "y": 0.5}]}
        water = fh.refine_surface_hydrology(heightmap, _water_cycle([trunk], runoff_mm=24.0, precipitation_mm=570.0, evaporation_mm=2300.0, recharge_mm=10.0))
        presence = np.asarray(water["surface_water_grid"]["water_presence_rows"])
        depth = np.asarray(water["surface_water_grid"]["water_depth_m_rows"])
        self.assertTrue(presence.any())
        # Water only between the banks, and where the carved section holds it.
        self.assertFalse((presence & ~fields["in_channel"]).any())
        self.assertTrue(np.allclose(depth[presence], fields["water_depth"][presence], atol=2e-3))
        self.assertEqual([river["id"] for river in water["rivers"]], ["trunk"])
        wetness = np.asarray(water["runoff_grid"]["wetness_index_rows"])
        margin = np.maximum(fields["distance_m"] - 0.5 * fields["width_m"], 0.0)
        beside = (margin > 2.0) & (margin < 12.0)
        low_bank = beside & (terrace == 0.0)
        high_bank = beside & (terrace > 0.0)
        far = ~np.isfinite(fields["distance_m"]) | (margin > 3.5 * fields["width_m"])
        self.assertTrue(low_bank.any() and high_bank.any())
        self.assertGreater(float(wetness[low_bank].mean()), float(wetness[high_bank].mean()) + 0.05)
        if (far & (terrace == 0.0)).any():
            self.assertGreater(float(wetness[low_bank].mean()), float(wetness[far & (terrace == 0.0)].mean()) + 0.05)


class RelicChannelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent, cls.parent_size = _river_parent()
        cls.reach = cls.parent["heightmap_model"]["regional_landforms"]["landforms"][0]["reaches"][0]

    def test_a_level_builds_only_the_orders_its_cells_resolve_and_its_parent_could_not(self):
        residual, record, _frame, _elevation = _relics(self.parent, self.parent_size, origin_m=(300.0, 80.0))
        axis = record["axes"][0]
        orders = fr._orders(axis)
        self.assertTrue(axis["braided"])
        # First-order threads are wide enough for the 8 m parent: its job.
        self.assertGreaterEqual(orders[0]["width_m"], fr.RESOLVE_WIDTH_CELLS * 8.0)
        self.assertEqual(record["orders_left_to_the_parent_level"], [0])
        self.assertEqual(record["orders_built_here"], [1])
        self.assertEqual(axis["orders"], {"1": 5})
        self.assertGreater(float(np.abs(residual).max()), 0.05)
        # Chutes are shallower than the channel that built the plain.
        self.assertLess(float(-residual.min()), orders[0]["depth_m"])

    def test_swales_are_cut_and_their_volume_stands_in_the_bars(self):
        residual, record, _frame, _elevation = _relics(self.parent, self.parent_size, origin_m=(300.0, 80.0))
        self.assertLess(float(residual.min()), -0.05)
        self.assertGreater(float(residual.max()), 0.0)
        # Zero-mean over a few lane spacings.
        self.assertLess(abs(float(residual[30:-30, 30:-30].mean())), 0.02)
        self.assertGreater(record["new_relic_cell_fraction"], 0.05)
        self.assertLess(record["new_relic_cell_fraction"], 0.6)

    def test_sibling_tiles_agree_where_they_meet(self):
        left, _record, _frame, _elevation = _relics(self.parent, self.parent_size, origin_m=(300.0, 80.0))
        right, _record, _frame, _elevation = _relics(self.parent, self.parent_size, origin_m=(420.0, 80.0))
        # The right tile starts half-way across the left one: the same ground twice.
        self.assertTrue(np.allclose(left[20:-20, 150:220], right[20:-20, 30:100], atol=0.02))

    def test_the_next_level_adds_the_next_order_and_keeps_its_parents(self):
        _residual, record, frame, elevation = _relics(self.parent, self.parent_size, origin_m=(300.0, 80.0))
        parcel = {"id": "parcel", "map_detail_level": 5, "heightmap_model": dict(
            frame, map_detail_level=5, sample_grid={"rows": elevation.tolist()},
            regional_landforms={"landforms": [record]},
        )}
        shape = (161, 161)
        plot_frame = _child_frame(self.parent_size, (380.0, 120.0), (32.0, 32.0), shape)
        dx, dy, to_local, _to_uv = ac.local_frame(plot_frame, shape)
        residual, plot_record = fr.relic_channel_residual(
            np.full(shape, 296.0), np.ones(shape, dtype=bool), level=6, dx=dx, dy=dy, parent_spacing_m=1.0,
            parent_entity=parcel, to_local=to_local, channel_record={},
        )
        self.assertEqual(plot_record["orders_built_here"], [2])
        self.assertEqual(plot_record["axes"][0]["orders"], {"1": 5, "2": 6})
        self.assertEqual(plot_record["axes"][0]["points"], record["axes"][0]["points"])
        self.assertGreater(float(np.abs(residual).max()), 0.01)

    def test_a_child_at_its_parents_spacing_adds_nothing(self):
        _residual, record, frame, elevation = _relics(self.parent, self.parent_size, origin_m=(300.0, 80.0))
        parcel = {"id": "parcel", "map_detail_level": 5, "heightmap_model": dict(
            frame, map_detail_level=5, sample_grid={"rows": elevation.tolist()},
            regional_landforms={"landforms": [record]},
        )}
        shape = (41, 41)
        crop = _child_frame(self.parent_size, (380.0, 120.0), (40.0, 40.0), shape)
        dx, dy, to_local, _to_uv = ac.local_frame(crop, shape)
        # No detail band at the parent's own spacing: the caller passes 0.
        residual, crop_record = fr.relic_channel_residual(
            np.full(shape, 296.0), np.ones(shape, dtype=bool), level=6, dx=dx, dy=dy, parent_spacing_m=0.0,
            parent_entity=parcel, to_local=to_local, channel_record={},
        )
        self.assertEqual(crop_record["orders_built_here"], [])
        self.assertEqual(float(np.abs(residual).max()), 0.0)
        self.assertEqual(crop_record["axes"][0]["orders"], {"1": 5})

    def test_relics_keep_out_of_the_water_and_chutes_cut_the_bars(self):
        shape = (201, 241)
        frame = _child_frame(self.parent_size, (600.0, 460.0), (240.0, 200.0), shape)
        dx, dy, to_local, _to_uv = ac.local_frame(frame, shape)
        fields = ac.channel_fields([self.reach], shape, dx=dx, dy=dy, to_local=to_local)
        self.assertTrue(fields["in_channel"].any())
        # The carved section, as the landform stage sees it.
        elevation = np.where(fields["in_channel"], fields["bank"] - fields["depth"], 296.0)
        residual, record = fr.relic_channel_residual(
            elevation, np.ones(shape, dtype=bool), level=5, dx=dx, dy=dy, parent_spacing_m=8.0,
            parent_entity=self.parent, to_local=to_local, channel_record={},
        )
        self.assertEqual(record["orders_built_here"], [1])
        wet = fields["water_depth"] > 0.05
        bars = fields["in_channel"] & (elevation > fields["stage_m"] + 0.3)
        self.assertTrue(wet.any() and bars.any())
        self.assertEqual(float(np.abs(residual[wet]).max()), 0.0)
        # Chutes cross the bars that stand above the mean-flow stage.
        self.assertLess(float(residual[bars].min()), -0.05)

    def test_a_hill_standing_in_the_plain_carries_no_relics(self):
        shape = (161, 241)
        frame = _child_frame(self.parent_size, (300.0, 80.0), (240.0, 160.0), shape)
        dx, dy, to_local, _to_uv = ac.local_frame(frame, shape)
        y, x = np.mgrid[0:shape[0], 0:shape[1]]
        distance = np.hypot((x - 120) * dx, (y - 80) * dy)
        hill = 30.0 * np.exp(-0.5 * (distance / 30.0) ** 2)
        residual, _record = fr.relic_channel_residual(
            296.0 + hill, np.ones(shape, dtype=bool), level=5, dx=dx, dy=dy, parent_spacing_m=8.0,
            parent_entity=self.parent, to_local=to_local, channel_record={},
        )
        flank = (distance > 20.0) & (distance < 45.0)
        plain = distance > 95.0
        self.assertLess(float(np.abs(residual[flank]).max()), 0.02)
        self.assertGreater(float(np.abs(residual[plain]).max()), 0.05)

    def test_deterministic(self):
        first, _record, _frame, _elevation = _relics(self.parent, self.parent_size, origin_m=(300.0, 80.0))
        second, _record, _frame, _elevation = _relics(self.parent, self.parent_size, origin_m=(300.0, 80.0))
        self.assertTrue(np.array_equal(first, second))

    def test_consumers_read_the_same_geometry(self):
        residual, record, frame, elevation = _relics(self.parent, self.parent_size, origin_m=(300.0, 80.0))
        heightmap = dict(frame, sample_grid={"rows": (elevation + residual).tolist()}, regional_landforms={"landforms": [record]})
        fields = fr.heightmap_relic_fields(heightmap)
        self.assertEqual(fields["floor"].shape, residual.shape)
        floors = fields["floor"] > 0.8
        bars = fields["floor"] < 0.05
        self.assertTrue(floors.any() and bars.any())
        # Channel floors are the low ground, and hold the fill.
        self.assertLess(float(residual[floors].mean()), float(residual[bars].mean()) - 0.03)
        self.assertGreater(float(fields["fill_m"][floors].mean()), 0.02)
        self.assertLess(float(fields["fill_m"][bars].mean()), 0.1 * float(fields["fill_m"][floors].mean()))


class FineSoilTest(unittest.TestCase):
    def _models(self, elevation, *, level=6, spacing=0.5, parent_depth=0.8, landforms=None, frame=None):
        heightmap = dict(frame or {}, **{
            "map_detail_level": level, "sample_grid": {"rows": np.asarray(elevation).tolist()},
            "sample_spacing_x_m": spacing, "sample_spacing_y_m": spacing, "sea_level_m": None,
            "refinement_detail_band": {"parent_sample_spacing_m": spacing * 8.0},
            "regional_landforms": {"landforms": landforms or []},
        })
        parent_rows = lambda value: [[value] * 6 for _ in range(6)]  # noqa: E731
        parent_soil = {"grid": {
            "soil_depth_m_rows": parent_rows(parent_depth), "porosity_rows": parent_rows(0.31),
            "relative_permeability_rows": parent_rows(0.4), "ph_rows": parent_rows(8.1), "salinity_index_rows": parent_rows(0.2),
        }}
        water = {"climate_grid": _climate(), "runoff_grid": {}, "surface_water_grid": {}}
        return heightmap, water, parent_soil

    def test_a_plot_without_process_grids_keeps_its_parents_soil(self):
        elevation = np.full((61, 61), 100.0) + 0.01 * np.arange(61)[None, :]
        heightmap, water, parent_soil = self._models(elevation)
        alone = derive_regolith_soil_model({}, heightmap, water, {}, {})
        inherited = derive_regolith_soil_model({}, heightmap, water, {}, {}, parent_soil_model=parent_soil, parent_window=(0.2, 0.4, 0.2, 0.4))
        self.assertLess(float(np.asarray(alone["grid"]["soil_depth_m_rows"]).mean()), 0.5)
        self.assertAlmostEqual(float(np.asarray(inherited["grid"]["soil_depth_m_rows"]).mean()), 0.8, delta=0.02)
        self.assertAlmostEqual(float(np.asarray(inherited["grid"]["ph_rows"]).mean()), 8.1, delta=0.01)
        self.assertTrue(inherited["fine_scale_soil"]["inherits_parent_soil"])

    def test_soil_is_thin_on_a_nose_and_thick_in_a_hollow(self):
        x = (np.arange(81) - 40) * 0.5
        # A ridge and a hollow side by side on a slope.
        profile = 0.6 * np.exp(-((x + 10.0) / 4.0) ** 2) - 0.6 * np.exp(-((x - 10.0) / 4.0) ** 2)
        elevation = 100.0 + profile[None, :] - 0.02 * np.arange(81)[:, None]
        heightmap, water, parent_soil = self._models(elevation)
        soil = derive_regolith_soil_model({}, heightmap, water, {}, {}, parent_soil_model=parent_soil, parent_window=(0.2, 0.4, 0.2, 0.4))
        depth = np.asarray(soil["grid"]["soil_depth_m_rows"])
        nose = float(depth[20:60, 20].mean())
        hollow = float(depth[20:60, 60].mean())
        self.assertLess(nose, 0.8 * 0.95)
        self.assertGreater(hollow, 0.8 * 1.05)
        self.assertGreater(hollow, nose * 1.15)

    def test_an_abandoned_channel_holds_deeper_finer_soil_than_the_bar_beside_it(self):
        parent, parent_size = _river_parent()
        residual, record, frame, elevation = _relics(parent, parent_size, origin_m=(300.0, 80.0))
        heightmap, water, parent_soil = self._models(
            elevation + residual, level=5, spacing=1.0, landforms=[record], frame=frame,
        )
        heightmap["refinement_detail_band"] = {"parent_sample_spacing_m": 8.0}
        soil = derive_regolith_soil_model({}, heightmap, water, {}, {}, parent_soil_model=parent_soil, parent_window=(0.2, 0.4, 0.2, 0.4))
        fields = fr.heightmap_relic_fields(heightmap)
        floors = fields["floor"] > 0.8
        bars = fields["floor"] < 0.05
        depth = np.asarray(soil["grid"]["soil_depth_m_rows"])
        permeability = np.asarray(soil["grid"]["relative_permeability_rows"])
        self.assertGreater(float(depth[floors].mean()), float(depth[bars].mean()) + 0.05)
        self.assertLess(float(permeability[floors].mean()), float(permeability[bars].mean()))
        # Soil is moved between floors and bars; the parcel keeps its parent's mean.
        self.assertAlmostEqual(float(depth[30:-30, 30:-30].mean()), 0.8, delta=0.06)
        # One level down the chutes are the parent's: only the new order moves soil again.
        heightmap["map_detail_level"] = 6
        deeper = derive_regolith_soil_model({}, heightmap, water, {}, {}, parent_soil_model=parent_soil, parent_window=(0.2, 0.4, 0.2, 0.4))
        self.assertAlmostEqual(float(np.asarray(deeper["grid"]["soil_depth_m_rows"]).mean()), 0.8, delta=0.03)
        # A Site-scale tile that builds an order itself has no parent soil to inherit, and still sorts its own.
        heightmap["map_detail_level"] = 4
        record["axes"][0]["orders"] = {"1": 4}
        site = derive_regolith_soil_model({}, heightmap, water, {}, {})
        site_depth = np.asarray(site["grid"]["soil_depth_m_rows"])
        self.assertGreater(float(site_depth[floors].mean()), float(site_depth[bars].mean()) + 0.05)
        self.assertFalse(site["fine_scale_soil"]["inherits_parent_soil"])


if __name__ == "__main__":
    unittest.main()
