import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from ui.pixel_art_editor_ui import PixelArtEditorUI


class PixelArtEditorLayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((320, 240))

    def make_editor(self, project_root=None):
        illustration = {
            "id": "layered_art",
            "name": "Layered art",
            "idea_class": "illustration",
            "media_path": "",
        }
        world_model = SimpleNamespace(get_entity=lambda entity_id: illustration if entity_id == "layered_art" else None)
        host = SimpleNamespace(
            pixel_art_editor=None,
            pixel_art_painting=False,
            world_model=world_model,
            PROJECT_ROOT=Path(project_root or "."),
            layout={},
            LINE_HEIGHT=18,
            _parent_entity_for_illustration=lambda value: None,
            _pixel_canvas_size_for_entity=lambda entity, size: (8, 8),
            _sanitize_entity_id=lambda value: value,
            _ellipsize_text=lambda text, font, width: text,
            assign_illustration_image=lambda illustration_id, path: True,
        )
        controller = PixelArtEditorUI(host)
        self.assertTrue(controller.open("layered_art"))
        host.pixel_art_editor["metric_size_buffer"] = "1"
        self.assertTrue(controller.begin_canvas())
        host.pixel_art_editor["canvas_rect"] = pygame.Rect(0, 0, 80, 80)
        return controller, host, illustration

    def test_layers_composite_in_order_and_visibility_is_respected(self):
        controller, host, _ = self.make_editor()
        host.pixel_art_editor["color"] = (220, 30, 40)
        controller.paint_at((15, 15))
        controller.add_layer()
        host.pixel_art_editor["color"] = (30, 80, 230)
        controller.paint_at((15, 15))

        self.assertEqual((30, 80, 230), controller.composite_color_at(1, 1))
        controller.toggle_layer_visibility(1)
        self.assertEqual((220, 30, 40), controller.composite_color_at(1, 1))

    def test_completed_stroke_can_be_undone_and_redone(self):
        controller, host, _ = self.make_editor()
        host.pixel_art_editor["color"] = (10, 200, 120)
        controller.handle_click((45, 45))
        controller.finish_stroke()

        self.assertEqual((10, 200, 120), controller.composite_color_at(4, 4))
        self.assertTrue(controller.undo())
        self.assertIsNone(controller.composite_color_at(4, 4))
        self.assertTrue(controller.redo())
        self.assertEqual((10, 200, 120), controller.composite_color_at(4, 4))

    def test_save_and_reopen_restores_editable_layers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, host, illustration = self.make_editor(temp_dir)
            host.pixel_art_editor["color"] = (90, 180, 70)
            controller.paint_at((5, 5))
            controller.add_layer()
            host.pixel_art_editor["color"] = (210, 140, 30)
            controller.paint_at((75, 75))

            self.assertTrue(controller.save())
            self.assertTrue((Path(temp_dir) / illustration["pixel_document_path"]).is_file())
            controller.close()
            self.assertTrue(controller.open("layered_art"))
            host.pixel_art_editor["metric_size_buffer"] = "1"
            self.assertTrue(controller.begin_canvas())

            self.assertEqual(2, len(host.pixel_art_editor["layers"]))
            self.assertEqual((90, 180, 70), controller.composite_color_at(0, 0))
            self.assertEqual((210, 140, 30), controller.composite_color_at(7, 7))

    def test_reference_trace_is_locked_visible_and_excluded_from_png(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, host, illustration = self.make_editor(temp_dir)
            reference = pygame.Surface((4, 2), pygame.SRCALPHA)
            reference.fill((240, 50, 70, 255))
            host.pixel_art_editor["reference_surface"] = reference

            self.assertTrue(controller.paste_reference_as_trace_layer())
            trace = host.pixel_art_editor["layers"][0]
            self.assertTrue(trace["reference_only"])
            self.assertTrue(trace["locked"])
            self.assertEqual(0.35, trace["opacity"])
            self.assertEqual(1, host.pixel_art_editor["active_layer"])
            self.assertIsNone(trace["pixels"][0][0])
            self.assertEqual((240, 50, 70), trace["pixels"][3][2])
            self.assertEqual((240, 50, 70), trace["pixels"][4][5])
            self.assertGreater(controller.composite_surface().get_at((2, 3)).a, 0)
            self.assertEqual(0, controller.composite_surface(include_reference=False).get_at((2, 3)).a)

            controller.select_layer(0)
            controller.paint_at((25, 35))
            self.assertEqual((240, 50, 70), trace["pixels"][3][2])
            self.assertTrue(controller.save())
            exported = pygame.image.load(Path(temp_dir) / illustration["media_path"]).convert_alpha()
            self.assertEqual(0, exported.get_at((2, 3)).a)
            self.assertEqual(1, illustration["pixel_layer_count"])
            self.assertEqual(1, illustration["pixel_reference_layer_count"])

    def test_orthographic_mode_creates_saves_and_restores_three_scaled_views(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, host, illustration = self.make_editor(temp_dir)
            controller.close()
            self.assertTrue(controller.open("layered_art"))
            host._pixel_canvas_size_for_entity = lambda entity, size: (120, 120)
            host.pixel_art_editor["setup_mode"] = "orthographic"
            host.pixel_art_editor["dimension_buffers"] = {"length": "4", "width": "2", "height": "1"}

            self.assertTrue(controller.begin_canvas())
            self.assertEqual({"front", "side", "top"}, set(host.pixel_art_editor["views"]))
            self.assertEqual((120, 30), (host.pixel_art_editor["views"]["front"]["width"], host.pixel_art_editor["views"]["front"]["height"]))
            self.assertEqual((60, 30), (host.pixel_art_editor["views"]["side"]["width"], host.pixel_art_editor["views"]["side"]["height"]))
            self.assertEqual((120, 60), (host.pixel_art_editor["views"]["top"]["width"], host.pixel_art_editor["views"]["top"]["height"]))

            host.pixel_art_editor["canvas_rect"] = pygame.Rect(0, 0, 120, 30)
            host.pixel_art_editor["color"] = (220, 40, 50)
            controller.paint_at((0, 0))
            controller.switch_view("side")
            host.pixel_art_editor["canvas_rect"] = pygame.Rect(0, 0, 60, 30)
            host.pixel_art_editor["color"] = (40, 80, 220)
            controller.paint_at((0, 0))

            self.assertTrue(controller.save())
            self.assertEqual("orthographic", illustration["pixel_editor_mode"])
            self.assertEqual(4.0, illustration["depicted_length_m"])
            self.assertEqual(2.0, illustration["depicted_width_m"])
            self.assertEqual(1.0, illustration["depicted_height_m"])
            self.assertEqual(3, len(illustration["pixel_view_paths"]))
            for path in illustration["pixel_view_paths"].values():
                self.assertTrue((Path(temp_dir) / path).is_file())

            controller.close()
            self.assertTrue(controller.open("layered_art"))
            self.assertTrue(controller.begin_canvas())
            self.assertEqual((220, 40, 50), controller.composite_color_at(0, 0))
            controller.switch_view("side")
            self.assertEqual((40, 80, 220), controller.composite_color_at(0, 0))


if __name__ == "__main__":
    unittest.main()
