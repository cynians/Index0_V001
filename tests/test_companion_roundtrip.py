import base64
import json
import os
import tempfile
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from companion.server import CompanionServer
from ui.pixel_art_editor_ui import PixelArtEditorUI


class CompanionRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((320, 240))

    def make_editor(self):
        illustration = {
            "id": "companion_art",
            "name": "Companion art",
            "idea_class": "illustration",
            "media_path": "",
        }
        world_model = SimpleNamespace(get_entity=lambda entity_id: illustration if entity_id == "companion_art" else None)
        host = SimpleNamespace(
            pixel_art_editor=None,
            pixel_art_painting=False,
            world_model=world_model,
            PROJECT_ROOT=Path("."),
            layout={},
            LINE_HEIGHT=18,
            _parent_entity_for_illustration=lambda value: None,
            _pixel_canvas_size_for_entity=lambda entity, size: (8, 8),
            _sanitize_entity_id=lambda value: value,
            _ellipsize_text=lambda text, font, width: text,
            assign_illustration_image=lambda illustration_id, path: True,
        )
        controller = PixelArtEditorUI(host)
        self.assertTrue(controller.open("companion_art"))
        host.pixel_art_editor["metric_size_buffer"] = "1"
        self.assertTrue(controller.begin_canvas())
        host.pixel_art_editor["canvas_rect"] = pygame.Rect(0, 0, 80, 80)
        return controller, host

    def test_server_publish_and_take_result_round_trip(self):
        server = CompanionServer(port=0)
        server.start()
        try:
            token = server.publish_canvas(4, 4, b"fake-png-bytes", label="probe")
            state = server.current_canvas()
            self.assertEqual(state["token"], token)
            self.assertEqual(state["label"], "probe")

            self.assertIsNone(server.take_result("some-other-token"))
            server.submit_result(token, 4, 4, b"reply-bytes")
            result = server.take_result(token)
            self.assertIsNotNone(result)
            self.assertEqual(result["png_bytes"], b"reply-bytes")
            self.assertIsNone(server.take_result(token))
        finally:
            server.stop()

    def test_send_to_companion_then_receive_drawing_updates_active_layer(self):
        controller, host = self.make_editor()
        controller.send_to_companion()
        token = host.pixel_art_editor.get("companion_token")
        self.assertTrue(token)
        server_url = host.pixel_art_editor.get("companion_url")
        self.assertTrue(server_url)

        canvas_url = server_url.rstrip("/") + "/canvas"
        with urllib.request.urlopen(canvas_url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["token"], token)
        self.assertEqual(payload["width"], 8)
        self.assertEqual(payload["height"], 8)

        drawn = pygame.Surface((8, 8), pygame.SRCALPHA)
        drawn.fill((0, 0, 0, 0))
        drawn.fill((10, 200, 90, 255), pygame.Rect(2, 2, 3, 3))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temp_path = handle.name
        try:
            pygame.image.save(drawn, temp_path)
            with open(temp_path, "rb") as fh:
                png_bytes = fh.read()
        finally:
            os.remove(temp_path)
        body = json.dumps({
            "token": token,
            "width": 8,
            "height": 8,
            "png_base64": base64.b64encode(png_bytes).decode("ascii"),
        }).encode("utf-8")
        request = urllib.request.Request(canvas_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)

        controller._poll_companion()
        self.assertIsNone(host.pixel_art_editor.get("companion_token"))
        self.assertEqual(controller.composite_color_at(3, 3), (10, 200, 90))
        self.assertIsNone(controller.composite_color_at(0, 0))


if __name__ == "__main__":
    unittest.main()
