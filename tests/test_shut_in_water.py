"""Water the land shuts in: which water is the sea, where a lake stands, how it is drawn."""
import unittest

import numpy as np

from simulations.world_gen import fine_hydrology as fh
from simulations.world_gen import regional_refinement as rr
from simulations.world_gen.drainage import derive_drainage_network
from simulations.world_gen.heightmap import joined_sea_rows, refresh_heightmap_derivatives
from simulations.world_gen.true_color import LAKE_MIN_FILL, derive_true_color_model, render_true_color_surface

ROWS, COLUMNS = 33, 65
SEA_COLUMNS = 16
PIT = (slice(12, 21), slice(40, 49))
BOUNDS = {"min_u": 0.148, "max_u": 0.152, "min_v": 0.409, "max_v": 0.411}


def _ground(pit_m=-12.0, land_m=40.0, sea_m=-30.0):
    """Level land, the sea along the west, and a pit below sea level that the land shuts in."""
    ground = np.full((ROWS, COLUMNS), float(land_m))
    ground[:, :SEA_COLUMNS] = float(sea_m)
    ground[PIT] = float(pit_m)
    return ground


def _sea():
    sea = np.zeros((ROWS, COLUMNS), dtype=bool)
    sea[:, :SEA_COLUMNS] = True
    return sea


def _heightmap(ground, level=2, spacing=400.0):
    return {
        "status": "fixture", "projection": "equirectangular", "coverage": "regional_patch", "wrap_x": False,
        "map_detail_level": level, "radius_m": 6_371_000.0, "circumference_m": 40_030_000.0,
        "equator_resolution_m_per_px": spacing, "sample_spacing_x_m": spacing, "sample_spacing_y_m": spacing,
        "sea_level_m": 0.0, "sea_level_locked": True, "source_uv_bounds": dict(BOUNDS),
        "sample_grid": {"width": ground.shape[1], "height": ground.shape[0], "wrap_x": False, "rows": ground.tolist()},
        "surface_masks": {"ice_rows": np.zeros(ground.shape, dtype=bool).tolist()},
    }


def _parent():
    """A coarse parent over the tile: ocean in the west, land in the east."""
    rows = np.where(np.arange(60)[None, :] < 30, -500.0, 200.0) * np.ones((40, 1))
    return {"heightmap_model": {
        "sample_grid": {"rows": rows.tolist()}, "source_uv_bounds": {"min_u": 0.1, "max_u": 0.2, "min_v": 0.4, "max_v": 0.42},
        "sea_level_m": 0.0, "sample_spacing_x_m": 15_000.0,
    }}


class SeaMaskTest(unittest.TestCase):
    """Ground below sea level is the sea only where water joins it to the open sea."""

    def test_a_tile_asks_its_parent_which_water_is_the_sea(self):
        heightmap = _heightmap(_ground())
        sea = rr._sea_mask(heightmap, _parent(), 0.0)
        np.testing.assert_array_equal(sea, _sea())                       # the pit is not the sea's
        self.assertIsNone(rr._sea_mask(heightmap, {}, 0.0))              # no parent grid: nothing is known
        self.assertIsNone(rr._sea_mask(heightmap, _parent(), None))      # a world without a sea

    def test_ground_below_sea_level_that_land_shuts_in_is_land(self):
        untold = refresh_heightmap_derivatives(_heightmap(_ground()))
        told = refresh_heightmap_derivatives(_heightmap(_ground()), sea_mask=_sea())
        before, after = untold["surface_masks"], told["surface_masks"]
        self.assertFalse(before["ocean_is_joined_sea"])
        self.assertTrue(np.asarray(before["ocean_rows"])[PIT].all())     # everything below sea level was sea
        self.assertTrue(after["ocean_is_joined_sea"])
        ocean, land = np.asarray(after["ocean_rows"]), np.asarray(after["land_rows"])
        np.testing.assert_array_equal(ocean, _sea())
        np.testing.assert_array_equal(land, ~_sea())
        self.assertFalse(np.asarray(after["coastal_rows"])[PIT].any())   # and it has no sea shore
        self.assertTrue(np.asarray(before["coastal_rows"])[PIT].any())
        self.assertLess(told["hypsometry_summary"]["ocean_fraction"], untold["hypsometry_summary"]["ocean_fraction"])
        self.assertEqual(told["sample_grid"]["rows"], untold["sample_grid"]["rows"])   # the ground itself is as it was

    def test_a_mask_on_another_grid_is_not_used(self):
        told = refresh_heightmap_derivatives(_heightmap(_ground()), sea_mask=np.ones((5, 5), dtype=bool))
        self.assertFalse(told["surface_masks"]["ocean_is_joined_sea"])
        self.assertTrue(np.asarray(told["surface_masks"]["ocean_rows"])[PIT].all())

    def test_the_layers_read_the_sea_back_on_their_own_grids(self):
        self.assertIsNone(joined_sea_rows(refresh_heightmap_derivatives(_heightmap(_ground()))))
        told = refresh_heightmap_derivatives(_heightmap(_ground()), sea_mask=_sea())
        np.testing.assert_array_equal(joined_sea_rows(told), _sea())
        coarse = joined_sea_rows(told, (17, 33))                          # the water cycle's grid
        self.assertEqual(coarse.shape, (17, 33))
        self.assertTrue(coarse[:, :SEA_COLUMNS // 2].all())
        self.assertFalse(coarse[:, SEA_COLUMNS // 2:].any())

    def test_fine_hydrology_floods_the_sea_and_not_the_pit(self):
        ground = _ground(pit_m=-1.5, land_m=3.0, sea_m=-4.0)
        water_cycle = {
            "status": "water_cycle_seeded",
            "climate_grid": {
                "annual_runoff_rows_mm": [[300.0] * 4] * 4, "annual_precipitation_rows_mm": [[900.0] * 4] * 4,
                "annual_potential_evaporation_rows_mm": [[1000.0] * 4] * 4, "annual_groundwater_recharge_rows_mm": [[100.0] * 4] * 4,
            },
            "drainage_network_model": {"rivers": [], "ephemeral_channels": [], "grid_width": 4, "grid_height": 4},
            "runoff_grid": {}, "surface_water_grid": {}, "rivers": [], "lakes": [],
        }
        untold = fh.refine_surface_hydrology(refresh_heightmap_derivatives(_heightmap(ground, level=5, spacing=2.0)), water_cycle)
        told = fh.refine_surface_hydrology(
            refresh_heightmap_derivatives(_heightmap(ground, level=5, spacing=2.0), sea_mask=_sea()), water_cycle)
        before = np.asarray(untold["surface_water_grid"]["water_presence_rows"])
        after = np.asarray(told["surface_water_grid"]["water_presence_rows"])
        self.assertTrue(before[PIT].all())                                # 1.5 m of sea in a hole in the ground
        self.assertFalse(after[PIT].any())                                # no lake was given: the pit is dry ground
        self.assertTrue(after[:, :SEA_COLUMNS].all())
        depth = np.asarray(told["surface_water_grid"]["water_depth_m_rows"])
        self.assertAlmostEqual(float(depth[16, 4]), 4.0, delta=0.01)
        self.assertEqual(float(depth[16, 44]), 0.0)


def _valley_behind_a_sill(scale=1.0):
    """A valley that drains west to the sea over a sill, with a hollow 15 m deep behind it (heights times ``scale``).

    The hollow's floor steps a metre a cell, so some cell lies within a
    metre or two of the sill.
    """
    columns = np.arange(41)
    profile = np.where(
        columns <= 5, 10.0 * columns,                                    # up from the sea to the sill at 50 m
        np.where(columns <= 35, 50.0 - np.minimum(columns - 5, 35 - columns), 50.0 + 20.0 * (columns - 35)),
    ).astype(float)
    ground = np.tile(profile, (9, 1))
    ground[[0, -1], :] = 500.0                                           # valley sides
    ground[:, 0] = -10.0
    ground *= float(scale)
    ocean = np.zeros(ground.shape, dtype=bool)
    ocean[:, 0] = True
    return ground, ocean


class SillRuleTest(unittest.TestCase):
    """A lake that overflows stands at its sill on a regional map; only a planet cell hides a gorge."""

    def _lake(self, detail_level, scale=1.0, runoff_mm=650.0, precipitation_mm=1600.0, evaporation_mm=720.0):
        ground, ocean = _valley_behind_a_sill(scale)
        shape = ground.shape
        model = derive_drainage_network(
            ground.tolist(), ocean.tolist(), np.where(ocean, 0.0, runoff_mm).tolist(), wrap_x=False, detail_level=detail_level,
            precipitation_rows=np.full(shape, precipitation_mm).tolist(),
            potential_evaporation_rows=np.full(shape, evaporation_mm).tolist(),
            represented_area_m2=float(ground.size) * 1.0e6,
        )
        self.assertTrue(model["lakes"])
        return model["lakes"][0]

    def test_a_regional_lake_that_overflows_stands_at_its_sill(self):
        for level in (1, 2, 3, 5):
            lake = self._lake(level, scale=20.0 if level == 1 else 1.0)
            step = 20.0 if level == 1 else 1.0
            self.assertTrue(lake["overflowing"], level)
            self.assertFalse(lake["endorheic"], level)
            self.assertAlmostEqual(lake["spill_elevation_m"], 50.0 * step, delta=0.5 * step)
            self.assertLessEqual(lake["spillway_incision_m"], step + 0.1, level)       # within a cell's step of the sill
            self.assertGreater(lake["maximum_depth_m"], 13.0 * step, level)

    def test_a_planet_cell_holds_the_gorge_the_outflow_has_cut(self):
        planet = self._lake(0, scale=20.0)
        self.assertTrue(planet["overflowing"])
        self.assertGreater(planet["spillway_incision_m"], 100.0)
        self.assertLess(planet["maximum_depth_m"], 0.6 * 300.0)

    def test_a_dry_basin_keeps_its_water_below_the_sill_at_any_scale(self):
        lake = self._lake(3, runoff_mm=2.0, precipitation_mm=80.0, evaporation_mm=2300.0)
        self.assertTrue(lake["endorheic"] and lake["water_balance_limited"])
        self.assertLess(lake["surface_elevation_m"], lake["spill_elevation_m"] - 5.0)
        self.assertEqual(lake["spillway_incision_m"], 0.0)


def _lake_record(surface_m=20.0, **fields):
    """A lake over the pit on a drainage grid half as fine as the heightfield."""
    cells = [[x, y] for y in range(PIT[0].start // 2, PIT[0].stop // 2 + 1) for x in range(PIT[1].start // 2, PIT[1].stop // 2 + 1)]
    return {"id": "lake", "cells": cells, "surface_elevation_m": float(surface_m), "terminal_fill_fraction": 1.0, **fields}


def _water(*lakes):
    lakes = list(lakes)
    return {
        "status": "water_cycle_seeded", "lakes": lakes,
        "drainage_network_model": {"grid_width": (COLUMNS + 1) // 2, "grid_height": (ROWS + 1) // 2, "lakes": lakes},
    }


class LakeWaterTest(unittest.TestCase):
    """The lakes the drainage retained, as water on the heightfield."""

    def test_a_lake_is_water_up_to_its_own_level(self):
        ground = _ground()
        depth = fh._lake_water(_water(_lake_record(20.0)), ground, ground.shape)
        np.testing.assert_allclose(depth[PIT], 32.0)
        outside = np.ones(ground.shape, dtype=bool)
        outside[PIT] = False
        self.assertEqual(float(depth[outside].max()), 0.0)               # the land round it stands above the lake

    def test_a_playa_can_be_left_dry(self):
        ground = _ground()
        playa = _water(_lake_record(-11.0, terminal_fill_fraction=0.2))
        self.assertGreater(float(fh._lake_water(playa, ground, ground.shape)[PIT].min()), 0.9)
        self.assertEqual(float(fh._lake_water(playa, ground, ground.shape, min_fill=LAKE_MIN_FILL).max()), 0.0)

    def test_a_lake_known_only_as_its_parents_box_can_be_left_out(self):
        ground = _ground()
        box = _water({"id": "lake", "cells": [], "surface_elevation_m": 45.0,
                      "bounds": {"min_x": 0.5, "max_x": 0.9, "min_y": 0.2, "max_y": 0.8}})
        drawn = fh._lake_water(box, ground, ground.shape)
        self.assertGreater(float(drawn[16, 36]), 4.0)                    # level land inside the box, under 5 m of water
        self.assertEqual(float(drawn[16, 20]), 0.0)
        self.assertEqual(float(fh._lake_water(box, ground, ground.shape, boxes=False).max()), 0.0)


    def test_a_lake_handed_down_as_a_box_is_kept_to_where_the_parent_had_water(self):
        ground = _ground()
        box = _water({"id": "lake", "cells": [], "surface_elevation_m": 45.0,
                      "bounds": {"min_x": 0.0, "max_x": 1.0, "min_y": 0.0, "max_y": 1.0}})
        everywhere = fh._lake_water(box, ground, ground.shape)
        parent_water = np.zeros(ground.shape, dtype=bool)
        parent_water[10:22, 30:40] = True
        kept = fh._lake_water(box, ground, ground.shape, within=parent_water)
        self.assertGreater(int((everywhere > 0).sum()), int((kept > 0).sum()))
        self.assertTrue(((kept > 0) <= parent_water).all() and (kept > 0).any())
        np.testing.assert_allclose(kept[parent_water], everywhere[parent_water])
        # A lake the level found for itself is not cut by it.
        own = _water(_lake_record(20.0))
        np.testing.assert_allclose(fh._lake_water(own, ground, ground.shape, within=np.zeros(ground.shape, dtype=bool)),
                                   fh._lake_water(own, ground, ground.shape))


class ParentLakeLevelTest(unittest.TestCase):
    """A lake keeps its parent's level on a finer tile: the tile draws the shore, it does not drain the lake."""

    def _tiles(self):
        from tests import test_fine_scale_ground as ground_fixtures

        size, spacing = 81, 8.0
        y, x = np.mgrid[0:size, 0:size] * spacing
        # Level ground at 100 m with a hollow two metres deep in its middle.
        bowl = lambda px, py: 100.0 - 2.0 * np.clip(1.0 - np.hypot(px - 320.0, py - 320.0) / 120.0, 0.0, 1.0)  # noqa: E731
        parent = {"map_detail_level": 4, "sample_grid": {"rows": bowl(x, y).tolist()}, "sample_spacing_x_m": spacing,
                  "sample_spacing_y_m": spacing, "sea_level_m": None,
                  "source_uv_bounds": {"min_u": 0.1, "max_u": 0.2, "min_v": 0.5, "max_v": 0.6}}
        lake = {"id": "lake_001", "cells": [], "surface_elevation_m": 99.5,
                "bounds": {"min_x": 0.2, "max_x": 0.8, "min_y": 0.2, "max_y": 0.8}}
        cycle = ground_fixtures._water_cycle()
        cycle["lakes"] = [lake]
        cycle["drainage_network_model"]["lakes"] = [lake]
        parent_water = fh.refine_surface_hydrology(parent, cycle)
        # The middle half of it, four times as fine.  Its own solver found the sill 60 cm lower.
        fy, fx = np.mgrid[0:161, 0:161] * 2.0 + 160.0
        child = {"map_detail_level": 5, "sample_grid": {"rows": bowl(fx, fy).tolist()}, "sample_spacing_x_m": 2.0,
                 "sample_spacing_y_m": 2.0, "sea_level_m": None,
                 "source_uv_bounds": {"min_u": 0.125, "max_u": 0.175, "min_v": 0.525, "max_v": 0.575}}
        refined = {"id": "parent_lake_generated_lod_4:lake_001", "cells": [], "surface_elevation_m": 98.9,
                   "parent_surface_elevation_m": 99.5, "inherited_from_parent": True,
                   "bounds": {"min_x": 0.0, "max_x": 1.0, "min_y": 0.0, "max_y": 1.0}}
        child_cycle = ground_fixtures._water_cycle()
        child_cycle["lakes"] = [refined]
        child_cycle["drainage_network_model"]["lakes"] = [refined]
        return parent, parent_water, child, child_cycle, bowl(fx, fy)

    def test_the_finer_tile_fills_the_lake_to_its_parents_level(self):
        parent, parent_water, child, child_cycle, ground = self._tiles()
        level = fh.parent_lake_level(child, parent, parent_water, ground.shape)
        self.assertEqual(float(np.nanmax(level)), 99.5)
        self.assertTrue(np.isnan(level[0, 0]))                               # far from the lake the parent tells none
        with_parent = fh.refine_surface_hydrology(child, child_cycle, parent=(parent, parent_water))["surface_water_grid"]
        alone = fh.refine_surface_hydrology(child, child_cycle)["surface_water_grid"]
        water, depth = np.asarray(with_parent["water_presence_rows"], dtype=bool), np.asarray(with_parent["water_depth_m_rows"])
        lower = np.asarray(alone["water_presence_rows"], dtype=bool)
        # Water wherever the finer ground lies under the parent's level, as deep as that; left to itself the
        # tile would fill only to the sill it found.
        np.testing.assert_array_equal(water, ground < 99.5 - fh.OPEN_WATER_DEPTH_M)
        np.testing.assert_allclose(depth[water], 99.5 - ground[water], atol=0.002)
        np.testing.assert_array_equal(lower, ground < 98.9 - fh.OPEN_WATER_DEPTH_M)
        self.assertGreater(int(water.sum()), 1.5 * int(lower.sum()))
        # A parent without lakes hands none down, and a hollow the tile finds for itself is still its own.
        dry_parent = fh.refine_surface_hydrology(parent, __import__("tests.test_fine_scale_ground", fromlist=["x"])._water_cycle())
        self.assertTrue(np.isnan(fh.parent_lake_level(child, parent, dry_parent, ground.shape)).all())
        own = dict(child_cycle["lakes"][0], inherited_from_parent=None, id="lake_009", cells=[[1, 1], [2, 1], [1, 2], [2, 2]])
        found = dict(child_cycle, lakes=[own], drainage_network_model=dict(child_cycle["drainage_network_model"], lakes=[own]))
        kept = np.asarray(fh.refine_surface_hydrology(child, found, parent=(parent, dry_parent))["surface_water_grid"]["water_presence_rows"], dtype=bool)
        np.testing.assert_array_equal(kept, fh._lake_water(found, ground, ground.shape) > fh.OPEN_WATER_DEPTH_M)
        self.assertTrue(kept.any())


class RiverTroughTest(unittest.TestCase):
    """The solver's fill of a carved channel is the channel's own trough, not a lake."""

    def _river(self, above_bank_m):
        """A carved river with a "lake" laid over a short stretch of it, so far above or below its banks there."""
        from simulations.world_gen import alluvial_channels as ac
        from tests import test_fine_scale_ground as ground_fixtures

        parent, _size = ground_fixtures._river_parent()
        heightmap = dict(parent["heightmap_model"], map_detail_level=4, sea_level_m=None)
        rows = np.asarray(heightmap["sample_grid"]["rows"], dtype=float)
        fields = ac.heightmap_channel_fields(heightmap, shape=rows.shape)
        stretch = np.zeros(rows.shape, dtype=bool)
        stretch[:, int(0.46 * rows.shape[1]):int(0.54 * rows.shape[1])] = True
        there = fields["in_channel"] & stretch
        banks = fields["bank"][there]
        surface = float(banks.min()) + above_bank_m if above_bank_m < 0 else float(banks.max()) + above_bank_m
        cycle = ground_fixtures._water_cycle(runoff_mm=24.0, precipitation_mm=570.0, evaporation_mm=2300.0)
        lake = {"id": "trough", "cells": [], "surface_elevation_m": surface,
                "bounds": {"min_x": 0.46, "max_x": 0.54, "min_y": 0.0, "max_y": 1.0}}
        cycle["lakes"] = [lake]
        cycle["drainage_network_model"]["lakes"] = [lake]
        return heightmap, cycle, fields, there

    def test_a_fill_below_the_banks_adds_no_water_to_the_river(self):
        heightmap, cycle, fields, there = self._river(-0.1)
        plain = dict(cycle, lakes=[], drainage_network_model=dict(cycle["drainage_network_model"], lakes=[]))
        river = np.asarray(fh.refine_surface_hydrology(heightmap, plain)["surface_water_grid"]["water_presence_rows"], dtype=bool)
        filled = fh.refine_surface_hydrology(heightmap, cycle)["surface_water_grid"]
        water = np.asarray(filled["water_presence_rows"], dtype=bool)
        self.assertTrue(river[there].any() and not river[there].all())      # bars stand dry at mean flow
        np.testing.assert_array_equal(water[there], river[there])           # and stay dry: the fill is no lake
        depth = np.asarray(filled["water_depth_m_rows"], dtype=float)
        np.testing.assert_allclose(depth[there], np.where(river[there], fields["water_depth"][there], 0.0), atol=0.002)
        # Left to the solver's fill, the same stretch would stand brim-full.
        brim = fh._lake_water(cycle, np.asarray(heightmap["sample_grid"]["rows"], dtype=float), water.shape)
        self.assertGreater(float((brim[there] > 0.02).mean()), float(river[there].mean()) + 0.1)

    def test_a_lake_that_stands_above_the_banks_drowns_the_channel(self):
        heightmap, cycle, _fields, there = self._river(+0.5)
        water = np.asarray(fh.refine_surface_hydrology(heightmap, cycle)["surface_water_grid"]["water_presence_rows"], dtype=bool)
        self.assertTrue(water[there].all())


class LakeDrawingTest(unittest.TestCase):
    """True Color draws the sea and the lakes as water, and a dry basin as ground."""

    SIZE = (130, 66)
    SEA_PIXEL, LAND_PIXEL, PIT_PIXEL = (8, 33), (60, 33), (89, 33)

    def _render(self, *, told=True, water_cycle=None):
        heightmap = refresh_heightmap_derivatives(_heightmap(_ground()), sea_mask=_sea() if told else None)
        planet = {
            "id": "ares",
            "heightmap_model": heightmap,
            "surface_palette": {"surface_color": [164, 104, 76], "palette": [[72, 54, 48], [164, 104, 76], [214, 168, 126]]},
            "atmosphere_model": {"surface_pressure_bar": 0.008, "visual_model": {"visible": True, "tint_color": [188, 142, 110]}},
            "natural_material_model": {"catalog_version": 4, "planet_tags": ["oxidizing_surface", "aeolian_surface", "weathered_surface"]},
        }
        surface = render_true_color_surface(
            heightmap, derive_true_color_model(planet), water_cycle=water_cycle, atmosphere=planet["atmosphere_model"], target_size=self.SIZE,
        )
        self.assertEqual(self.SIZE, surface.get_size())
        return surface

    def _is_water(self, surface, pixel):
        colour = surface.get_at(pixel)
        return colour.b > colour.r

    def _assert_much_the_same(self, first, second):
        # The picture scales its tones by the whole frame, so a pixel moves a few steps when water appears elsewhere.
        self.assertLessEqual(max(abs(a - b) for a, b in zip(tuple(first)[:3], tuple(second)[:3])), 8)

    def test_the_sea_is_water_and_a_shut_in_basin_is_ground(self):
        untold = self._render(told=False)
        self.assertTrue(self._is_water(untold, self.SEA_PIXEL))
        self.assertFalse(self._is_water(untold, self.LAND_PIXEL))
        self.assertTrue(self._is_water(untold, self.PIT_PIXEL))          # below sea level: drawn as sea
        told = self._render()
        self.assertTrue(self._is_water(told, self.SEA_PIXEL))
        self.assertFalse(self._is_water(told, self.PIT_PIXEL))
        self._assert_much_the_same(told.get_at(self.SEA_PIXEL), untold.get_at(self.SEA_PIXEL))
        pit = told.get_at(self.PIT_PIXEL)
        self.assertGreater(pit.r, pit.b + 40)                            # a dusty basin floor, as red as the land

    def test_a_lake_the_drainage_retained_is_drawn_as_water(self):
        dry = self._render()
        lake = self._render(water_cycle=_water(_lake_record(20.0)))
        self.assertTrue(self._is_water(lake, self.PIT_PIXEL))
        self.assertFalse(self._is_water(lake, self.LAND_PIXEL))
        self._assert_much_the_same(lake.get_at(self.LAND_PIXEL), dry.get_at(self.LAND_PIXEL))   # nothing else changes
        self._assert_much_the_same(lake.get_at(self.SEA_PIXEL), dry.get_at(self.SEA_PIXEL))

    def test_a_playa_and_a_parents_box_are_left_as_ground(self):
        dry = self._render()
        playa = self._render(water_cycle=_water(_lake_record(-11.0, terminal_fill_fraction=0.2)))
        self.assertEqual(playa.get_at(self.PIT_PIXEL), dry.get_at(self.PIT_PIXEL))
        box = self._render(water_cycle=_water({"id": "lake", "cells": [], "surface_elevation_m": 45.0,
                                               "bounds": {"min_x": 0.5, "max_x": 0.9, "min_y": 0.2, "max_y": 0.8}}))
        self.assertEqual(box.get_at(self.LAND_PIXEL), dry.get_at(self.LAND_PIXEL))
        self.assertFalse(self._is_water(box, self.PIT_PIXEL))


if __name__ == "__main__":
    unittest.main()
