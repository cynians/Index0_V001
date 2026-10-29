import math
import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from simulations.building import blueprint_store
from simulations.building.blueprint_designer_renderer import BlueprintDesignerRenderer
from simulations.building.blueprint_designer_simulation import BlueprintDesignerSimulation, next_version_label
from simulations.building.blueprint_store import BlueprintAssetStore
from tests.test_building_sim import FakeWorldModel


class BlueprintWorld(FakeWorldModel):
    def get_dataset(self, name):
        return [entity for entity in self.entities.values() if entity.get("_dataset") == name]


def _world(extra=None):
    entities = [
        {"id": "bp_hut", "_dataset": "building_blueprints", "type": "building_blueprint",
         "name": "Hut", "pretty_name": "Hut", "blueprint_version_label": "Mk Ia", "wiki_entry": "Keep me"},
        {"id": "mat_brick", "_dataset": "materials", "type": "material", "name": "Brick",
         "pretty_name": "Brick", "display_color": [150, 80, 60], "tags": ["construction_material"]},
        {"id": "mat_glass", "_dataset": "materials", "type": "material", "name": "Glass",
         "pretty_name": "Glass", "display_color": [110, 150, 170], "material_class": "engineered_material"},
        {"id": "component_kitchen_sink", "_dataset": "components", "type": "component",
         "name": "Kitchen Sink", "pretty_name": "Kitchen Sink"},
        {"id": "loc_site", "_dataset": "locations", "type": "location", "name": "Site",
         "map_coordinate_space": "site_meters"},
    ]
    entities.extend(extra or [])
    return BlueprintWorld(entities)


class DesignerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        cls.screen = pygame.display.set_mode((1400, 900))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = BlueprintAssetStore(self.temp.name)
        self.previous_store = blueprint_store.set_shared_store(self.store)
        self.world = _world()
        self.sim = BlueprintDesignerSimulation(self.world, "bp_hut", store=self.store)
        self.renderer = BlueprintDesignerRenderer()
        self.frame()
        self.sim.views["plan"] = {"center": [5.0, 5.0], "zoom": 30.0}
        self.frame()

    def tearDown(self):
        blueprint_store.set_shared_store(self.previous_store)
        self.temp.cleanup()

    def frame(self):
        self.renderer.draw(self.screen, self.sim)

    def move(self, point, view="plan"):
        pos = tuple(int(round(v)) for v in self.sim.world_to_screen(point, view))
        self.sim.handle_pointer_motion(pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0)), None, pos)
        return pos

    def click(self, point, button=1, view="plan"):
        pos = self.move(point, view)
        self.sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button), None, pos)
        self.sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=button), None, pos)
        self.frame()

    def press(self, key):
        rect = self.sim.hitboxes[key]
        for event_type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            self.sim.handle_pointer_event(pygame.event.Event(event_type, pos=rect.center, button=1), None, rect.center)
        self.frame()

    def draw_rect_room(self, a, b):
        self.press("tool:rect")
        self.click(a)
        self.click(b)


class BlueprintDesignerGrundrissTests(DesignerTestCase):
    def test_rectangle_and_polygon_rooms_share_a_wall(self):
        self.draw_rect_room((0, 0), (6, 4))
        self.press("tool:room")
        for point in ((6, 0), (10, 0), (10, 4), (6, 4)):
            self.click(point)
        self.click((6, 0))  # Clicking the first corner closes the room.
        rooms = self.sim.blueprint["rooms"]
        self.assertEqual(len(rooms), 2)
        interior = [w for w in self.sim.derived["walls"] if w["kind"] == "interior"]
        self.assertEqual(len(interior), 1)
        self.assertAlmostEqual(interior[0]["length_m"], 4.0)
        self.assertAlmostEqual(self.sim.derived["rooms"][rooms[1]["key"]]["gross_area_m2"], 16.0)

    def test_live_segment_length_and_area_are_drawn_while_drafting(self):
        labels = []
        original = self.renderer._label_box
        self.renderer._label_box = lambda screen, text, *args, **kwargs: (labels.append(text), original(screen, text, *args, **kwargs))
        self.press("tool:room")
        self.click((0, 0))
        self.click((4, 0))
        self.move((4, 3.5))
        self.frame()
        self.assertIn("4.00 m", labels)   # placed segment
        self.assertIn("3.50 m", labels)   # rubber-band segment to the cursor
        self.assertIn("7.00 m²", labels)  # running area

    def test_typed_lengths_place_exact_walls_and_rectangles(self):
        self.press("tool:room")
        self.click((0, 0))
        self.move((5, 0.2))  # cursor direction: roughly east
        for char in "4.25":
            self.sim.handle_event(pygame.event.Event(pygame.KEYDOWN, key=0, unicode=char, mod=0))
        self.assertEqual(self.sim.length_entry, "4.25")
        self.sim.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0))
        last = self.sim.draft_points[-1]
        self.assertAlmostEqual(math.dist(last, (0, 0)), 4.25, places=3)
        self.sim.cancel_draft()
        self.press("tool:rect")
        self.click((10, 0))
        self.move((12, 3))  # drag toward the south-east
        for char in "6x4":
            self.sim.handle_event(pygame.event.Event(pygame.KEYDOWN, key=0, unicode=char, mod=0))
        self.sim.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0))
        room = self.sim.blueprint["rooms"][-1]
        xs = sorted({p[0] for p in room["points"]})
        ys = sorted({p[1] for p in room["points"]})
        self.assertEqual((xs, ys), ([10.0, 16.0], [0.0, 4.0]))

    def test_grid_snap_and_shift_free_placement(self):
        self.press("tool:room")
        self.move((1.23, 2.71))
        self.assertEqual(self.sim.cursor_plan, (1.0, 2.5))
        self.assertEqual(self.sim.cursor_snap, "grid")
        self.sim._mods_override = pygame.KMOD_SHIFT
        self.move((1.23, 2.71))
        self.assertEqual(self.sim.cursor_snap, "free")
        self.assertAlmostEqual(self.sim.cursor_plan[0], 1.23, delta=0.05)
        self.sim._mods_override = None
        self.sim.toggle_snap()
        self.move((1.23, 2.71))
        self.assertEqual(self.sim.cursor_snap, "free")

    def test_existing_corners_attract_the_cursor(self):
        self.draw_rect_room((0, 0), (6, 4))
        self.sim._mods_override = pygame.KMOD_SHIFT  # free placement still snaps to corners
        self.press("tool:room")
        self.move((6.1, 4.1))
        self.assertEqual(self.sim.cursor_snap, "vertex")
        self.assertEqual(self.sim.cursor_plan, (6.0, 4.0))

    def test_overlapping_room_is_rejected(self):
        self.draw_rect_room((0, 0), (6, 4))
        self.click((2, 2))
        self.click((8, 8))
        self.assertEqual(len(self.sim.blueprint["rooms"]), 1)
        self.assertTrue(self.sim.status_is_error)
        self.assertIn("Overlaps", self.sim.status)

    def test_openings_are_placed_on_walls_with_their_class(self):
        self.draw_rect_room((0, 0), (6, 4))
        self.press("tool:opening")
        self.press("opening_class:double_door")
        self.click((3, 0.02))
        self.press("opening_class:window")
        self.click((6, 2))
        classes = [o["opening_class"] for o in self.sim.blueprint["openings"]]
        self.assertEqual(classes, ["double_door", "window"])
        attached = [o for w in self.sim.derived["walls"] for o in w["openings"]]
        self.assertEqual(len(attached), 2)
        self.click((20, 20))  # nowhere near a wall
        self.assertEqual(len(self.sim.blueprint["openings"]), 2)

    def test_fixed_items_come_from_the_item_catalog_and_stay_inside_rooms(self):
        self.draw_rect_room((0, 0), (6, 4))
        self.press("tool:fixture")
        self.assertEqual(self.sim.picker["kind"], "fixture")
        self.press("picker:item:component_kitchen_sink")
        self.click((10, 10))
        self.assertEqual(self.sim.blueprint["fixtures"], [])
        self.click((1, 1))
        self.assertEqual([f["ref"] for f in self.sim.blueprint["fixtures"]], ["component_kitchen_sink"])
        room_key = self.sim.blueprint["rooms"][0]["key"]
        self.assertEqual(self.sim.derived["rooms"][room_key]["fixtures"], [self.sim.blueprint["fixtures"][0]["key"]])

    def test_dragging_a_shared_corner_moves_both_rooms(self):
        self.draw_rect_room((0, 0), (6, 4))
        self.draw_rect_room((6, 0), (10, 4))
        self.press("tool:select")
        start = self.move((6, 4))
        self.sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=start, button=1), None, start)
        end = self.move((7, 4))
        self.sim.handle_pointer_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=end, button=1), None, end)
        corners = [tuple(p) for room in self.sim.blueprint["rooms"] for p in room["points"]]
        self.assertEqual(corners.count((7.0, 4.0)), 2)
        self.assertNotIn((6.0, 4.0), corners)
        self.sim.undo()
        corners = [tuple(p) for room in self.sim.blueprint["rooms"] for p in room["points"]]
        self.assertEqual(corners.count((6.0, 4.0)), 2)

    def test_levels_copy_outline_and_stairs(self):
        self.draw_rect_room((0, 0), (6, 4))
        self.press("level:add")
        self.assertEqual(self.sim.active_level, "L1")
        self.press("level:copy_below")
        upper = [r for r in self.sim.blueprint["rooms"] if r["level"] == "L1"]
        self.assertEqual(len(upper), 1)
        self.assertEqual(self.sim.derived["totals"]["level_count"], 2)
        self.press("level:height_up")
        self.assertAlmostEqual(self.sim.blueprint["levels"][1]["height_m"], 3.25)
        self.press("level:select:L0")
        self.press("tool:stair")
        self.click((4, 1))
        self.click((5.5, 3.5))
        stairs = self.sim.blueprint["vertical_features"]
        self.assertEqual([(s["from_level"], s["to_level"]) for s in stairs], [("L0", "L1")])

    def test_rename_room_through_the_selection_panel(self):
        self.draw_rect_room((0, 0), (6, 4))
        self.press("sel:rename")
        self.sim.text_edit["buffer"] = ""
        for char in "Workshop":
            self.sim.handle_event(pygame.event.Event(pygame.KEYDOWN, key=0, unicode=char, mod=0))
        self.sim.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0))
        self.assertEqual(self.sim.blueprint["rooms"][0]["name"], "Workshop")


class BlueprintDesignerPersistenceTests(DesignerTestCase):
    def test_save_writes_asset_and_merges_summary_into_the_full_entity(self):
        self.draw_rect_room((0, 0), (6, 4))
        self.assertTrue(self.sim.dirty)
        self.press("save")
        entity = self.world.get_entity("bp_hut")
        self.assertEqual(entity["wiki_entry"], "Keep me")
        self.assertEqual(entity["blueprint_status"], "draft")
        self.assertEqual(entity["blueprint_asset_path"], "assets/buildings/bp_hut.json.gz")
        self.assertAlmostEqual(entity["footprint_area_m2"], 6.3 * 4.3, places=2)
        asset = Path(self.temp.name) / entity["blueprint_asset_path"]
        with gzip.open(asset, "rt", encoding="utf-8") as handle:
            self.assertEqual(len(json.load(handle)["rooms"]), 1)
        self.assertFalse(self.sim.dirty)
        reopened = BlueprintDesignerSimulation(self.world, "bp_hut", store=self.store)
        self.assertEqual(len(reopened.blueprint["rooms"]), 1)

    def test_released_blueprint_is_read_only_and_forks_a_new_version(self):
        self.draw_rect_room((0, 0), (6, 4))
        self.press("save")
        self.world.entities["bp_hut"]["blueprint_status"] = "released"
        self.frame()
        self.assertNotIn("tool:rect", self.sim.hitboxes)
        self.assertFalse(self.sim.add_level())
        self.assertIn("new version", self.sim.status)
        self.press("new_version")
        action = self.sim.consume_pending_navigation_action()
        self.assertEqual(action["launch_mode"], "blueprint_designer")
        new_id = action["entity_id"]
        self.assertEqual(new_id, "bp_hut_mk_ib")
        fork = self.world.get_entity(new_id)
        self.assertEqual(fork["predecessor"], "bp_hut")
        self.assertEqual(fork["blueprint_version_label"], "Mk Ib")
        self.assertEqual(fork["blueprint_status"], "draft")
        self.assertEqual(self.world.get_entity("bp_hut")["successor"], new_id)
        forked = BlueprintDesignerSimulation(self.world, new_id, store=self.store)
        self.assertFalse(forked.read_only)
        self.assertEqual(len(forked.blueprint["rooms"]), 1)

    def test_version_labels_increment(self):
        self.assertEqual(next_version_label("Mk Ia"), "Mk Ib")
        self.assertEqual(next_version_label("Mk 2"), "Mk 3")
        self.assertEqual(next_version_label(""), "v2")

    def test_place_on_map_offers_site_parents_and_requests_placement(self):
        self.draw_rect_room((0, 0), (6, 4))
        self.press("place_on_map")
        self.assertEqual(self.sim.picker["kind"], "parent")
        self.press("picker:item:loc_site")
        action = self.sim.consume_pending_navigation_action()
        self.assertEqual(action, {"id": "blueprint_place_on_parent", "blueprint_id": "bp_hut", "parent_id": "loc_site"})
        self.assertFalse(self.sim.dirty)  # placement saves first


class BlueprintDesignerDesignTests(DesignerTestCase):
    def setUp(self):
        super().setUp()
        self.draw_rect_room((0, 0), (6, 4))
        self.press("tool:opening")
        self.press("opening_class:window")
        self.click((3, 4))
        self.press("stage:design")
        self.press("view:south")

    def test_default_and_surface_materials(self):
        self.press("role:facade")
        self.press("picker:item:mat_brick")
        self.assertEqual(self.sim.blueprint["default_materials"]["facade"], "mat_brick")
        wall = next(p for p in self.sim.design_primitives() if p["kind"] == "wall")
        # Low on the wall, beside the window rather than on it.
        solid_point = (min(p[0] for p in wall["polygon"]) + 0.5, 0.4)
        self.click(solid_point, view="south")
        self.assertEqual(self.sim.selection["key"], wall["surface_key"])
        self.press("surface:set")
        self.press("picker:item:mat_glass")
        self.assertEqual(self.sim.material_for(wall["surface_key"], "facade"), "mat_glass")
        self.press("surface:clear")
        self.assertEqual(self.sim.material_for(wall["surface_key"], "facade"), "mat_brick")

    def test_pixel_studio_details_round_trip(self):
        self.press("details:paint")
        editor = self.sim.pixel_art_editor
        self.assertTrue(self.sim.is_vehicle_pixel_editor_active())
        view = editor["views"]["south"]
        reference, detail = view["layers"]
        self.assertTrue(reference["reference_only"])
        mask = editor["view_masks"]["south"]
        self.assertEqual(len(mask), view["height"])
        self.assertTrue(any(any(row) for row in mask))
        self.assertFalse(all(all(row) for row in mask))
        detail["pixels"][len(mask) // 2][len(mask[0]) // 2] = [255, 0, 0]
        self.assertTrue(self.sim.pixel_art_editor_ui.save())
        stored = self.sim.blueprint["view_details"]["south"]
        self.assertEqual((stored["width"], stored["height"]), (view["width"], view["height"]))
        painted = sum(1 for row in stored["layers"][0]["pixels"] for color in row if color)
        self.assertEqual(painted, 1)
        self.frame()  # details render over the facade

    def test_material_texture_set_tiles_on_surfaces(self):
        texture_path = Path(self.temp.name) / "brick_texture.layers.json.gz"
        red, dark = [180, 40, 30], [60, 20, 10]
        pixels = [[red if (x + y) % 2 == 0 else dark for x in range(16)] for y in range(16)]
        document = {"texture_set": {
            "version": 1, "texture_id": "tex", "width": 16, "height": 16,
            "grid": {"columns": 3, "rows": 3}, "seed": 17,
            "base_layers": [{"name": "Base", "visible": True, "opacity": 1.0, "pixels": pixels}],
            "variants": [],
        }}
        with gzip.open(texture_path, "wt", encoding="utf-8") as handle:
            json.dump(document, handle)
        self.world.entities["mat_brick"]["material_texture_set_ref"] = str(texture_path)
        surface = pygame.Surface((64, 64), pygame.SRCALPHA)
        self.sim.materials.fill_polygon(surface, [(0, 0), (64, 0), (64, 64), (0, 64)], "mat_brick", "facade",
                                        meters_to_px=16.0, anchor=(0, 0))
        self.assertEqual(tuple(surface.get_at((0, 0)))[:3], tuple(red))
        self.assertEqual(tuple(surface.get_at((1, 0)))[:3], tuple(dark))


class MaterialTexturePipelineTests(unittest.TestCase):
    """Pixel Studio texture save -> material_texture_set_ref -> tiled surface."""

    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((320, 240))

    def test_saved_texture_illustration_is_tiled_on_building_surfaces(self):
        from types import SimpleNamespace

        from simulations.building.material_visuals import MaterialVisuals
        from ui.knowledge_browser_ui import KnowledgeBrowserUI
        from ui.pixel_art_editor_ui import PixelArtEditorUI

        with tempfile.TemporaryDirectory() as root:
            material = {"id": "mat_brick", "_dataset": "materials", "type": "material",
                        "name": "Brick", "display_color": [10, 10, 10]}
            illustration = {"id": "idea_brick_texture", "name": "Brick texture", "idea_class": "illustration",
                            "parents": ["mat_brick"], "pixel_editor_mode": "texture", "media_path": ""}
            entities = {"mat_brick": material, "idea_brick_texture": illustration}
            world_model = SimpleNamespace(get_entity=entities.get)
            persisted = []
            browser = SimpleNamespace(
                world_model=world_model, cards=[],
                _parent_entity_for_illustration=lambda value: material,
                _persist_entity_to_repository=persisted.append,
            )
            host = SimpleNamespace(
                pixel_art_editor=None, pixel_art_painting=False, world_model=world_model,
                PROJECT_ROOT=Path(root), layout={}, LINE_HEIGHT=18,
                _parent_entity_for_illustration=lambda value: material,
                _pixel_canvas_size_for_entity=lambda entity, size: (8, 8),
                _sanitize_entity_id=lambda value: value,
                _ellipsize_text=lambda text, font, width: text,
                assign_illustration_image=lambda illustration_id, path: True,
                assign_texture_set_to_parent=lambda value: KnowledgeBrowserUI.assign_texture_set_to_parent(browser, value),
            )
            editor = PixelArtEditorUI(host)
            self.assertTrue(editor.open("idea_brick_texture"))
            host.pixel_art_editor["metric_size_buffer"] = "1"
            self.assertTrue(editor.begin_canvas())
            self.assertEqual(host.pixel_art_editor["setup_mode"], "texture")
            layer = editor._active_layer()
            width, height = host.pixel_art_editor["canvas_width"], host.pixel_art_editor["canvas_height"]
            layer["pixels"] = [[[200, 60, 40]] * width for _ in range(height)]
            self.assertTrue(editor.save())

            self.assertEqual(material["material_texture_set_ref"], illustration["pixel_document_path"])
            self.assertEqual(persisted, [material])
            visuals = MaterialVisuals(SimpleNamespace(get_entity=entities.get), project_root=root)
            self.assertIsNotNone(visuals.texture("mat_brick"))
            surface = pygame.Surface((32, 32), pygame.SRCALPHA)
            visuals.fill_polygon(surface, [(0, 0), (32, 0), (32, 32), (0, 32)], "mat_brick", "facade",
                                 meters_to_px=16.0, anchor=(0, 0))
            self.assertEqual(tuple(surface.get_at((5, 5)))[:3], (200, 60, 40))


if __name__ == "__main__":
    unittest.main()
