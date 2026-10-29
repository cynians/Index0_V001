import unittest
from types import SimpleNamespace
from unittest.mock import patch

from simulations.world_gen import regional_refinement as rr


class _World:
    def __init__(self, *entities):
        self.loader = SimpleNamespace(entities={entity["id"]: entity for entity in entities})

    def get_entity(self, entity_id):
        return self.loader.entities.get(entity_id)


def _planet(circumference_m=40_030_000.0):
    return {
        "id": "planet", "name": "Planet", "location_class": "planet", "map_detail_level": 0,
        "bounds": {"type": "bbox", "min_x": -180.0, "max_x": 180.0, "min_y": -90.0, "max_y": 90.0},
        "heightmap_model": {"circumference_m": circumference_m, "sample_grid": {"width": 513, "height": 257}},
    }


def _window(planet, width_m, height_m=None, center=(10.0, 20.0)):
    """Bounds of a footprint of this size on a planet's map."""
    circumference = planet["heightmap_model"]["circumference_m"]
    width = width_m / circumference * 360.0
    height = (height_m if height_m is not None else width_m / 1.5) / (circumference * 0.5) * 180.0
    return {"min_x": center[0] - width / 2, "max_x": center[0] + width / 2, "min_y": center[1] - height / 2, "max_y": center[1] + height / 2}


def _tile(level, width_m, height_m, *, bounds=None, entity_id="tile", parent="planet", grid=None):
    tile = rr._planned_tile(level, bounds or {"min_x": 0.0, "max_x": 1.0, "min_y": 0.0, "max_y": 1.0}, width_m, height_m, grid)
    tile.update({"id": entity_id, "name": entity_id, "refinement_parent_map_id": parent, "location_role": "map_refinement_region"})
    return tile


def _inside(tile, width_m, height_m):
    """Bounds of a footprint of this size in the middle of a tile."""
    bounds = tile["bounds"]
    tile_width_m, tile_height_m = rr.map_physical_dimensions_m(tile)
    half_x = 0.5 * width_m / tile_width_m * (bounds["max_x"] - bounds["min_x"])
    half_y = 0.5 * height_m / tile_height_m * (bounds["max_y"] - bounds["min_y"])
    center_x, center_y = 0.5 * (bounds["min_x"] + bounds["max_x"]), 0.5 * (bounds["min_y"] + bounds["max_y"])
    return {"min_x": center_x - half_x, "max_x": center_x + half_x, "min_y": center_y - half_y, "max_y": center_y + half_y}


class ScaleLevelTests(unittest.TestCase):
    def test_the_level_of_a_map_is_the_scale_of_its_footprint(self):
        expected = {30_000_000.0: 0, 8_100_000.0: 1, 600_000.0: 1, 120_000.0: 2, 16_000.0: 3, 2_400.0: 4, 300.0: 5, 38.4: 6}
        self.assertEqual(expected, {extent: rr.footprint_level(extent) for extent in expected})
        self.assertEqual(0, rr.map_scale_level(_planet()))
        # A map says what it is by its size, whatever number it was stored with:
        # a "Region" of 3,600 km is a Macroregion.
        self.assertEqual(1, rr.map_scale_level(_tile(2, 3_640_000.0, 2_050_000.0)))
        self.assertAlmostEqual(rr.map_cell_size_m(_planet()), 40_030_000.0 / 512.0)
        self.assertAlmostEqual(rr.map_cell_size_m(_tile(2, 120_000.0, 80_000.0)), 234.375)

    def test_every_level_has_room_for_the_next_below_it(self):
        # The coarsest map of a level still has a child a level finer and three times as fine.
        for level in range(0, 5):
            extent = rr.LEVEL_MAX_EXTENT_M[level + 1] * 1.001 if level else 9_000_000.0
            parent = _tile(level, extent, extent / 1.5) if level else _planet(9_000_000.0)
            limit = rr.max_refinement_extent_m(parent)
            self.assertGreater(limit, rr.LEVEL_MAX_EXTENT_M[level + 2], level)
            self.assertLessEqual(limit, rr.LEVEL_MAX_EXTENT_M[level + 1], level)


class StepTests(unittest.TestCase):
    def test_a_footprint_too_large_to_be_a_level_finer_is_refused_with_the_largest_that_works(self):
        planet = _planet()
        with self.assertRaises(rr.RefinementStepError) as raised:
            rr.next_refinement_step(_World(planet), planet, _window(planet, 25_000_000.0, 8_400_000.0))
        self.assertEqual("too_large", raised.exception.reason)
        self.assertAlmostEqual(8_192_000.0, raised.exception.max_extent_m)
        self.assertIn("8.2 Mm", str(raised.exception))
        # Under a Region of 120 km (234 m a cell) a map is Local scale and at least three times finer.
        region = _tile(2, 120_000.0, 80_000.0)
        self.assertAlmostEqual(234.375 / 3.0 * 384.0, rr.max_refinement_extent_m(region))
        with self.assertRaises(rr.RefinementStepError) as raised:
            rr.next_refinement_step(_World(region), region, _inside(region, 60_000.0, 40_000.0))
        self.assertEqual("too_large", raised.exception.reason)

    def test_a_footprint_one_level_finer_is_one_step(self):
        planet = _planet()
        step = rr.next_refinement_step(_World(planet), planet, _window(planet, 5_000_000.0))
        self.assertTrue(step["final"])
        self.assertEqual(1, step["level"])
        region = _tile(2, 120_000.0, 80_000.0)
        step = rr.next_refinement_step(_World(region), region, _inside(region, 16_000.0, 10_000.0))
        self.assertEqual((True, 3), (step["final"], step["level"]))

    def test_a_footprint_levels_finer_gets_the_maps_in_between(self):
        planet = _planet()
        world = _World(planet)
        target = _window(planet, 300.0, 190.0)
        plan = rr.describe_refinement(world, planet, target)
        self.assertEqual({"status": "ok", "level": 5, "label": "Parcel", "steps": 5, "reused": 0},
                         {key: plan[key] for key in ("status", "level", "label", "steps", "reused")})
        # Each in-between map is one level down, holds the target and is at least three times finer.
        parent, levels = planet, []
        for _step in range(6):
            step = rr.next_refinement_step(world, parent, target)
            levels.append(step["level"])
            self.assertTrue(rr._contains(step["bounds"], target))
            self.assertTrue(rr._contains(parent["bounds"], step["bounds"]))
            child = rr._planned_tile(step["level"], step["bounds"], step["width_m"], step["height_m"])
            self.assertEqual(step["level"], rr.footprint_level(max(step["width_m"], step["height_m"])))
            self.assertGreaterEqual(rr.map_cell_size_m(parent) / rr.map_cell_size_m(child), rr.MIN_REFINEMENT_STEP - 1e-9)
            if step["final"]:
                break
            parent = child
        self.assertEqual([1, 2, 3, 4, 5], levels)
        with self.assertRaises(rr.RefinementStepError) as raised:
            rr.next_refinement_step(world, planet, target, allow_intermediate=False)
        self.assertEqual("too_small", raised.exception.reason)

    def test_an_in_between_map_that_exists_is_used_again(self):
        planet = _planet()
        target = _window(planet, 120_000.0, 80_000.0)
        macro_bounds = _window(planet, 4_000_000.0)
        macro = _tile(1, 4_000_000.0, 4_000_000.0 / 1.5, bounds={"type": "bbox", **macro_bounds}, entity_id="macro")
        elsewhere = _tile(1, 4_000_000.0, 4_000_000.0 / 1.5, bounds={"type": "bbox", **_window(planet, 4_000_000.0, center=(-120.0, -40.0))}, entity_id="elsewhere")
        world = _World(planet, macro, elsewhere)
        step = rr.next_refinement_step(world, planet, target)
        self.assertFalse(step["final"])
        self.assertIs(macro, step["reuse"])
        plan = rr.describe_refinement(world, planet, target)
        self.assertEqual((2, 1, 1), (plan["level"], plan["steps"], plan["reused"]))

    def test_the_finest_level_is_the_ten_centimetre_floor(self):
        plot = _tile(6, 38.4, 38.4)
        self.assertAlmostEqual(0.1, rr.map_cell_size_m(plot), delta=0.005)
        self.assertTrue(rr.refinement_floor_reached(plot))
        self.assertEqual("finest", rr.describe_refinement(_World(plot), plot, _inside(plot, 12.0, 12.0))["status"])
        # A parcel always reaches the floor, also where that is under three times finer.
        parcel = _tile(5, 110.0, 110.0)
        step = rr.next_refinement_step(_World(parcel), parcel, _inside(parcel, 38.0, 38.0))
        self.assertEqual((True, 6), (step["final"], step["level"]))
        # A plot too wide for the floor takes one last step to it: a Survey.
        wide = _tile(6, 100.0, 100.0)
        self.assertFalse(rr.refinement_floor_reached(wide))
        step = rr.next_refinement_step(_World(wide), wide, _inside(wide, 30.0, 30.0))
        self.assertEqual((True, 7), (step["final"], step["level"]))
        self.assertEqual("too_large", rr.describe_refinement(_World(wide), wide, _inside(wide, 60.0, 60.0))["status"])

    def test_a_grid_of_its_own_must_still_be_three_times_finer(self):
        site = _tile(4, 2_400.0, 1_500.0)                     # 6.25 m a cell
        chunk = _inside(site, 128.0, 128.0)
        step = rr.next_refinement_step(_World(site), site, chunk, sample_dimensions=(129, 129))
        self.assertEqual((True, 5), (step["final"], step["level"]))
        fine_site = _tile(4, 900.0, 900.0)                    # 2.3 m a cell
        with self.assertRaises(rr.RefinementStepError):
            rr.next_refinement_step(_World(fine_site), fine_site, _inside(fine_site, 128.0, 128.0), sample_dimensions=(129, 129))


class ChainTests(unittest.TestCase):
    def test_the_maps_in_between_are_made_in_order_and_each_is_the_next_ones_parent(self):
        planet = _planet()
        world = _World(planet)
        target = _window(planet, 2_400.0, 1_500.0)
        made, reports = [], []

        def fake_step(world_model, parent_entity, bounds, *, level, progress_callback=None, **options):
            width_m, height_m = rr._requested_footprint_m(parent_entity, bounds)
            tile = _tile(level, width_m, height_m, bounds=bounds, entity_id=f"made_{len(made)}", parent=parent_entity["id"])
            made.append((level, parent_entity["id"], options.get("sample_dimensions"), options.get("focus_occurrence_id")))
            world_model.loader.entities[tile["id"]] = tile
            if progress_callback is not None:
                progress_callback(0.5, "relief")
            return tile

        with patch.object(rr, "_generate_refined_step", side_effect=fake_step):
            result = rr.generate_refined_region(
                world, planet, target, focus_occurrence_id="occ", progress_callback=lambda share, text, preview=None: reports.append((share, text)))
            self.assertEqual(4, result["map_detail_level"])
            self.assertEqual(
                [(1, "planet", None, None), (2, "made_0", None, None), (3, "made_1", None, None), (4, "made_2", None, "occ")], made)
            self.assertTrue(rr._contains(result["bounds"], target) and rr._contains(target, result["bounds"]))
            # Progress runs over the whole chain and says where it is.
            self.assertEqual([0.125, 0.375, 0.625, 0.875], [round(share, 3) for share, _text in reports])
            self.assertTrue(reports[0][1].startswith("Macroregion (1 of 4)"))
            # A second map nearby uses the three maps that are there.
            made.clear()
            near = _window(planet, 2_400.0, 1_500.0, center=(10.0005, 20.0005))
            rr.generate_refined_region(world, planet, near)
            self.assertEqual([(4, "made_2", None, None)], made)

    def test_rebuilding_in_place_makes_no_maps_in_between(self):
        planet = _planet()
        with patch.object(rr, "_generate_refined_step") as step:
            with self.assertRaises(rr.RefinementStepError):
                rr.generate_refined_region(_World(planet), planet, _window(planet, 2_400.0, 1_500.0), allow_intermediate=False)
            step.assert_not_called()


if __name__ == "__main__":
    unittest.main()
