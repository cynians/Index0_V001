import math
import unittest

from simulations.building import blueprint_model as bm
from simulations.building.blueprint_views import elevation_primitives, top_primitives


def _three_room_blueprint():
    blueprint = bm.new_blueprint("bp_test", "Test")
    blueprint["rooms"] = [
        {"key": "r001", "name": "Hall", "points": [[0, 0], [10, 0], [10, 6], [0, 6]]},
        {"key": "r002", "name": "Kitchen", "points": [[0, 6], [4, 6], [4, 10], [0, 10]]},
        {"key": "r003", "name": "Store", "points": [[4, 6], [10, 6], [10, 10], [4, 10]]},
    ]
    blueprint["openings"] = [
        {"key": "o001", "center": [5, 0.05], "opening_class": "double_door"},
        {"key": "o002", "center": [2, 6], "opening_class": "door"},
        {"key": "o003", "center": [10, 8], "opening_class": "window"},
    ]
    blueprint["fixtures"] = [{"key": "f001", "ref": "component_kitchen_sink", "position": [1, 9]}]
    return bm.normalize_blueprint(blueprint)


class BlueprintGeometryTests(unittest.TestCase):
    def test_shared_and_t_junction_edges_become_interior_walls(self):
        derived = bm.derive_geometry(_three_room_blueprint())
        interior = [w for w in derived["walls"] if w["kind"] == "interior"]
        exterior = [w for w in derived["walls"] if w["kind"] == "exterior"]
        # The hall's south edge is split where the kitchen/store wall meets it.
        self.assertEqual(sorted(round(w["length_m"], 3) for w in interior), [4.0, 4.0, 6.0])
        self.assertAlmostEqual(sum(w["length_m"] for w in exterior), 40.0)
        self.assertEqual({w["facing"] for w in exterior}, {"north", "south", "east", "west"})

    def test_outline_and_floor_space_are_derived(self):
        derived = bm.derive_geometry(_three_room_blueprint())
        level = derived["levels"][0]
        self.assertEqual(len(level["outline_loops"]), 1)
        self.assertAlmostEqual(bm.polygon_area([tuple(p) for p in level["outline_loops"][0]]), 100.0)
        totals = derived["totals"]
        # Gross area reaches the outer wall faces (half of the 30 cm wall outside).
        self.assertAlmostEqual(totals["gross_floor_area_m2"], 10.3 * 10.3, places=4)
        self.assertLess(totals["net_floor_area_m2"], 100.0)
        hall = derived["rooms"]["r001"]
        # 10 x 6 inset by 15 cm (exterior) on three sides and 6 cm (interior) on one.
        self.assertAlmostEqual(hall["net_area_m2"], (10 - 0.3) * (6 - 0.15 - 0.06), places=4)
        self.assertEqual(derived["rooms"]["r002"]["fixtures"], ["f001"])

    def test_openings_attach_to_the_nearest_wall(self):
        derived = bm.derive_geometry(_three_room_blueprint())
        by_key = {o["key"]: (w, o) for w in derived["walls"] for o in w["openings"]}
        self.assertEqual(set(by_key), {"o001", "o002", "o003"})
        wall, door = by_key["o001"]
        self.assertEqual(wall["facing"], "north")
        self.assertAlmostEqual(door["width_m"], bm.OPENING_CLASSES["double_door"]["width_m"])
        self.assertTrue(door["passable"])
        self.assertFalse(by_key["o003"][1]["passable"])
        self.assertEqual(by_key["o002"][0]["kind"], "interior")

    def test_room_validation_allows_neighbours_and_rejects_overlap(self):
        blueprint = _three_room_blueprint()
        self.assertIsNone(bm.validate_room_polygon(blueprint, "L0", [[10, 0], [14, 0], [14, 6], [10, 6]]))
        self.assertIn("Overlaps", bm.validate_room_polygon(blueprint, "L0", [[2, 2], [5, 2], [5, 5], [2, 5]]))
        self.assertIn("Overlaps", bm.validate_room_polygon(blueprint, "L0", [[0, 0], [10, 0], [10, 6], [0, 6]]))
        self.assertIn("crosses", bm.validate_room_polygon(blueprint, "L0", [[20, 0], [24, 4], [24, 0], [20, 4]]))
        # A room on another level may sit directly above.
        blueprint["levels"].append({"key": "L1", "name": "1st floor", "elevation_m": 3.0, "height_m": 3.0})
        self.assertIsNone(bm.validate_room_polygon(blueprint, "L1", [[0, 0], [10, 0], [10, 6], [0, 6]]))

    def test_roof_shapes_raise_height_and_add_gables(self):
        blueprint = _three_room_blueprint()
        self.assertEqual(bm.derive_geometry(blueprint)["totals"]["building_height_m"], 3.0)
        blueprint["roof"] = {"shape": "gable", "pitch_deg": 45, "ridge_axis": "x", "overhang_m": 0.0}
        derived = bm.derive_geometry(blueprint)
        self.assertAlmostEqual(derived["roof"]["rise_m"], 10.3 / 2.0, places=4)
        self.assertEqual({g["facing"] for g in derived["roof"]["gable_walls"]}, {"east", "west"})
        blueprint["roof"]["shape"] = "hip"
        self.assertEqual(len(bm.derive_geometry(blueprint)["roof"]["planes"]), 4)

    def test_upper_level_stacks_on_the_one_below(self):
        blueprint = _three_room_blueprint()
        blueprint["levels"].append({"key": "L1", "name": "1st floor", "elevation_m": 3.0, "height_m": 2.8})
        blueprint["rooms"].append({"key": "r004", "level": "L1", "name": "Loft", "points": [[0, 0], [10, 0], [10, 6], [0, 6]]})
        derived = bm.derive_geometry(bm.normalize_blueprint(blueprint))
        self.assertEqual(derived["totals"]["level_count"], 2)
        self.assertAlmostEqual(derived["totals"]["wall_height_m"], 5.8)
        upper = [w for w in derived["walls"] if w["level"] == "L1"]
        self.assertTrue(all(w["base_z"] == 3.0 for w in upper))

    def test_placement_transform_rotates_walls_and_leaves_door_gaps(self):
        derived = bm.derive_geometry(_three_room_blueprint())
        walls = bm.placed_wall_segments(derived, (100.0, 50.0), 90.0)
        # Rotating 90 degrees clockwise maps plan +x onto parent +y.
        self.assertAlmostEqual(bm.plan_to_parent((10.0, 0.0), (100.0, 50.0), 90.0)[1], 60.0)
        total = sum(math.dist(a, b) for a, b in walls)
        passable = sum(o["width_m"] for w in derived["walls"] for o in w["openings"] if o["passable"])
        self.assertAlmostEqual(total, 54.0 - passable, places=4)
        footprint = bm.placed_footprint(derived, (100.0, 50.0), 90.0)
        self.assertAlmostEqual(bm.polygon_area([tuple(p) for p in footprint[0]]), 10.3 * 10.3, places=4)

    def test_summary_lists_rooms_fixtures_and_materials(self):
        blueprint = _three_room_blueprint()
        blueprint["default_materials"] = {"facade": "mat_brick"}
        blueprint["surface_materials"] = {"room:r001:floor": "mat_timber"}
        summary = bm.summary_fields(blueprint)
        self.assertEqual([room["key"] for room in summary["blueprint_rooms"]], ["r001", "r002", "r003"])
        self.assertEqual(summary["blueprint_fixtures"][0]["room"], "r002")
        self.assertEqual(summary["fixed_items"], ["component_kitchen_sink"])
        self.assertEqual(summary["materials_used"], ["mat_brick", "mat_timber"])


class BlueprintViewTests(unittest.TestCase):
    def test_elevations_show_only_walls_facing_the_viewer(self):
        blueprint = _three_room_blueprint()
        derived = bm.derive_geometry(blueprint)
        south = elevation_primitives(blueprint, derived, "south")
        walls = [p for p in south if p["kind"] == "wall"]
        self.assertEqual(len(walls), 2)  # Kitchen and store south walls.
        self.assertTrue(all(p["surface_key"].endswith(":outer") for p in walls))
        east = elevation_primitives(blueprint, derived, "east")
        windows = [p for p in east if p["kind"] == "opening"]
        self.assertEqual(len(windows), 1)
        # The window sits 0.9 m above the floor.
        self.assertAlmostEqual(min(z for _u, z in windows[0]["polygon"]), 0.9)

    def test_gable_verge_is_visible_edge_on(self):
        blueprint = _three_room_blueprint()
        blueprint["roof"] = {"shape": "gable", "pitch_deg": 30, "ridge_axis": "x", "overhang_m": 0.3}
        derived = bm.derive_geometry(bm.normalize_blueprint(blueprint))
        east = elevation_primitives(blueprint, derived, "east")
        self.assertEqual(sum(1 for p in east if p["kind"] == "gable"), 1)
        self.assertEqual(sum(1 for p in east if p["kind"] == "roof"), 2)

    def test_top_view_shows_roof_or_floors(self):
        blueprint = _three_room_blueprint()
        derived = bm.derive_geometry(blueprint)
        self.assertEqual({p["kind"] for p in top_primitives(blueprint, derived, show_roof=True)}, {"roof"})
        floors = top_primitives(blueprint, derived, show_roof=False, level_key="L0")
        self.assertEqual(sorted(p["room"] for p in floors), ["r001", "r002", "r003"])


if __name__ == "__main__":
    unittest.main()
