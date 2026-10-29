"""Drive the real application with queued input events and screenshots.

For walking a feature through the actual UI without a desktop: the ``App`` is
constructed normally, events go through pygame's queue into the app's own
``_process_events`` / ``_update_frame`` / ``_render_frame`` steps, and the
screen surface is saved as PNG.  Nothing is mocked; the ontology is the live
one, so every action a script performs is real and persists.

    from tools.app_driver import Driver
    d = Driver("demo", shots_dir)
    d.open_card_by_search("Test System Prime", "system_test_system_prime")
    d.launch_from_card("system_test_system_prime", "world_gen")
    d.shot("worldgen")

See ``docs/City_Prototype_Creation_Process.md`` for a full walkthrough.

Import this module before anything else that imports pygame: it selects the
headless SDL drivers and fixes the window size.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import pygame

from app.app import App


WINDOW_SIZE = (1600, 900)
_real_display_info = pygame.display.Info
_mouse_position = [(WINDOW_SIZE[0] // 2, WINDOW_SIZE[1] // 2)]


def _display_info():
    # The window sizes itself from the desktop; the dummy driver reports 1024x768.
    info = _real_display_info()
    return type("Info", (), {
        "current_w": WINDOW_SIZE[0], "current_h": WINDOW_SIZE[1],
        "__getattr__": lambda self, name: getattr(info, name),
    })()


pygame.display.Info = _display_info
# The dummy video driver has no cursor; wheel zoom and hover read this.
pygame.mouse.get_pos = lambda: _mouse_position[0]


class Driver:
    def __init__(self, prefix="shot", shots_dir=None, read_only=False):
        self.app = App()
        if read_only:
            # Look-only sessions (UI audits, profiling): nothing reaches the
            # ontology store, so they are safe beside a running application.
            self.app.world_model.loader.use_ontology = False
            self.app.world_model.loader.save_changed_dataset_files = lambda *args, **kwargs: None
            self._redirect_worldgen_storage()
        knowledge_ui = self.app.ui_manager.knowledge_ui
        # A driven session must never touch the user's unsaved card drafts
        # (.cache/card_drafts.json is shared with the real app).
        knowledge_ui.card_drafts = {}
        knowledge_ui.DRAFT_CACHE_PATH = None
        knowledge_ui._write_card_drafts = lambda: None
        self.prefix = prefix
        self.step = 1
        self.shots_dir = Path(shots_dir) if shots_dir else PROJECT_ROOT / ".cache" / "screenshots" / prefix
        self.shots_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _redirect_worldgen_storage():
        """Send raster bundles of regions refined in a look-only session to a temp folder.

        Refinement writes each new region's rasters beside the ontology, not
        through the loader; without this a look-only run leaves orphan
        ``assets/maps/material_heatmaps/*.i0r`` files for regions that were
        never stored.
        """
        import tempfile

        from simulations.biosphere import terrain_site
        from simulations.world_gen import regional_refinement

        scratch = tempfile.mkdtemp(prefix="index0_driver_worldgen_")
        generate = regional_refinement.generate_refined_region

        def redirected(*args, **kwargs):
            if kwargs.get("storage_root") is None:
                kwargs["storage_root"] = scratch
            return generate(*args, **kwargs)

        regional_refinement.generate_refined_region = redirected
        terrain_site.generate_refined_region = redirected

    @property
    def center(self):
        return self.app.width // 2, self.app.height // 2

    # -- frames and input -------------------------------------------------

    def frame(self, count=2):
        """Run the app's own main-loop steps ``count`` times."""
        for _ in range(count):
            self.app._process_events()
            self.app._update_frame(1 / 30)
            self.app._render_frame()

    def post(self, event_type, **attributes):
        pygame.event.post(pygame.event.Event(event_type, attributes))

    def shot(self, slug):
        self.frame(2)
        path = self.shots_dir / f"{self.prefix}_{self.step:02d}_{slug}.png"
        pygame.image.save(self.app.screen, str(path))
        self.step += 1
        return path

    def move(self, pos):
        pos = (int(pos[0]), int(pos[1]))
        _mouse_position[0] = pos
        self.post(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0))
        self.frame(1)

    def click(self, pos, button=1):
        pos = (int(pos[0]), int(pos[1]))
        self.move(pos)
        self.post(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)
        self.frame(1)
        self.post(pygame.MOUSEBUTTONUP, pos=pos, button=button)
        self.frame(3)

    def click_rect(self, rect):
        assert rect is not None, "expected a visible rectangle to click"
        self.click(rect.center)

    def drag(self, start, end, button=1):
        self.move(start)
        self.post(pygame.MOUSEBUTTONDOWN, pos=(int(start[0]), int(start[1])), button=button)
        self.frame(1)
        self.move(end)
        self.post(pygame.MOUSEBUTTONUP, pos=(int(end[0]), int(end[1])), button=button)
        self.frame(2)

    def wheel(self, pos, notches):
        self.move(pos)
        self.post(pygame.MOUSEWHEEL, x=0, y=notches, precise_x=0.0, precise_y=float(notches), flipped=False)
        self.frame(2)

    def key(self, key, char="", mod=0):
        self.post(pygame.KEYDOWN, key=key, unicode=char, mod=mod, scancode=0)
        self.frame(1)
        self.post(pygame.KEYUP, key=key, mod=mod, scancode=0)
        self.frame(2)

    def enter(self):
        self.key(pygame.K_RETURN, chr(13))

    def type_text(self, text):
        for char in text:
            key = ord(char.lower()) if char.strip() else pygame.K_SPACE
            self.post(pygame.KEYDOWN, key=key, unicode=char, mod=0, scancode=0)
            self.frame(1)

    # -- what is on screen ------------------------------------------------

    def sim(self):
        return self.app.get_active_simulation()

    def buttons(self):
        """Every clickable button on screen: sidebar, selection card, empty-state panel."""
        self.frame(1)
        ui = self.app.ui_manager
        return {
            button.id: button
            for group in (ui.buttons, ui.simulation_selection_buttons, ui.map_empty_state_buttons)
            for button in group
        }

    def button(self, button_id):
        button = self.buttons().get(button_id)
        assert button is not None, f"button {button_id} is not visible; visible: {sorted(self.buttons())}"
        assert getattr(button, "enabled", True), f"button {button_id} is disabled ({button.label})"
        return button

    def press(self, button_id):
        self.click_rect(self.button(button_id).rect)

    def card(self, entity_id):
        self.frame(1)
        for card in self.app.ui_manager.knowledge_ui.cards:
            if card.get("entity_id") == entity_id:
                return card
        return None

    def open_card_by_search(self, name, entity_id):
        """Type ``name`` into the repository search and click the entity's row."""
        knowledge_ui = self.app.ui_manager.knowledge_ui
        self.click_rect(knowledge_ui.browser_search_rect)
        self.type_text(name)
        self.frame(2)
        for row_id, rect in knowledge_ui.browser_hitboxes:
            if row_id == entity_id:
                self.click_rect(rect)
                card = self.card(entity_id)
                assert card is not None, f"clicking {entity_id} in the browser opened no card"
                return card
        raise AssertionError(
            f"{entity_id} is not in the search results: {[row for row, _ in knowledge_ui.browser_hitboxes][:12]}"
        )

    def launch_from_card(self, entity_id, mode):
        """Click one of the launch buttons at the bottom of an open card."""
        card = self.card(entity_id)
        assert card is not None, f"card {entity_id} is not open"
        options = card.get("launch_mode_hitboxes", [])
        for option, rect in options:
            if option.get("mode") == mode:
                self.click_rect(rect)
                return option
        if not options and card.get("launch_rect") is not None:
            # A card with a single launch affordance shows one button, not a mode row.
            entity = self.app.world_model.get_entity(entity_id)
            offered = [option["mode"] for option in self.app.navigation.launch_resolver.options_for_entity(
                entity, world_model=self.app.world_model)]
            assert mode in offered, f"launch mode {mode} is not offered for {entity_id}; resolver offers {offered}"
            self.click_rect(card["launch_rect"])
            return {"mode": mode}
        raise AssertionError(
            f"launch mode {mode} is not on the card; it offers {[option.get('mode') for option, _ in options]}"
        )

    # -- map helpers ------------------------------------------------------

    def frame_map_window(self, world_point, visible_width_world, tolerance=1.08):
        """Drag ``world_point`` to the screen centre and wheel-zoom until the
        visible width is ``visible_width_world``.  Uses only pan and wheel."""
        camera = self.app.camera
        cx, cy = self.center
        for _ in range(60):
            for _ in range(4):
                screen = camera.world_to_screen(world_point)
                dx, dy = cx - screen[0], cy - screen[1]
                if abs(dx) < 3 and abs(dy) < 3:
                    break
                dx = max(-500, min(500, dx))
                dy = max(-300, min(300, dy))
                self.drag((cx, cy), (cx + dx, cy + dy))
            if self.app.width / camera.zoom <= visible_width_world * tolerance:
                break
            self.wheel((cx, cy), 1)
        return camera.world_to_screen(world_point), self.app.width / camera.zoom
