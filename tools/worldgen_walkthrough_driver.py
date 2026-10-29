import os
import sys
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import pygame

from app import App


SCREENSHOT_DIR = ROOT / ".cache" / "screenshots" / "worldgen_walkthrough_hibuz"
START_SYSTEM_ID = "system_hibuz_system"
START_SYSTEM_NAME = "Hibuz System"


class Walkthrough:
    def __init__(self):
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        for path in SCREENSHOT_DIR.glob("*.png"):
            path.unlink()
        self.app = App()
        self.shots = []
        self.step = 1

    def frame(self, count=2):
        for _ in range(count):
            self.app._update_frame(1 / 30)
            self.app.draw()
            pygame.display.flip()

    def shot(self, slug):
        self.frame(2)
        path = SCREENSHOT_DIR / f"{self.step:02d}_{slug}.png"
        pygame.image.save(self.app.screen, str(path))
        self.shots.append(path)
        self.step += 1

    def click(self, pos):
        pygame.mouse.set_pos(pos)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, {"pos": pos, "rel": (0, 0), "buttons": (0, 0, 0)}))
        self.frame(1)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": pos, "button": 1}))
        self.frame(1)
        self.app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, {"pos": pos, "button": 1}))
        self.frame(3)

    def click_rect(self, rect):
        if rect is None:
            raise AssertionError("Expected a visible rectangle to click")
        self.click(rect.center)

    def type_text(self, text):
        for char in text:
            key = ord(char.lower()) if char.strip() else pygame.K_SPACE
            self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, {"key": key, "unicode": char, "mod": 0}))
            self.frame(1)

    def button_rect(self, button_id):
        self.frame(1)
        for button in self.app.ui_manager.buttons:
            if button.id == button_id:
                if not getattr(button, "enabled", True):
                    raise AssertionError(f"Button {button_id} is visible but disabled")
                return button.rect
        raise AssertionError(f"Button {button_id} was not visible")

    def optional_button_rect(self, button_id):
        self.frame(1)
        for button in self.app.ui_manager.buttons:
            if button.id == button_id and getattr(button, "enabled", True):
                return button.rect
        return None

    def active_sim(self):
        sim = self.app.get_active_simulation()
        if sim is None:
            raise AssertionError("Expected an active simulation")
        return sim

    def open_start_card(self):
        self.shot("repository_start")
        ui = self.app.ui_manager.knowledge_ui
        self.click_rect(ui.browser_search_rect)
        self.type_text(START_SYSTEM_NAME)
        self.shot("repository_search_hibuz")

        target_rect = None
        for entity_id, rect in ui.browser_hitboxes:
            if entity_id == START_SYSTEM_ID:
                target_rect = rect
                break
        if target_rect is None:
            raise AssertionError(f"Could not find {START_SYSTEM_NAME} in the visible search results")
        self.click_rect(target_rect)
        self.shot("repository_hibuz_card")

        card = self.find_card(START_SYSTEM_ID)
        if not card.get("is_edit_mode"):
            self.click_rect(card.get("edit_toggle_rect"))
        self.shot("repository_hibuz_toolbox")

        card = self.find_card(START_SYSTEM_ID)
        world_gen_rect = None
        for tool, rect in card.get("toolbelt_hitboxes", []):
            if tool.get("action_id") == "knowledge_launch_world_gen":
                world_gen_rect = rect
                break
        if world_gen_rect is None:
            raise AssertionError("World Gen was not visible in the card toolbox")
        self.click_rect(world_gen_rect)
        self.shot("worldgen_orbit_draft")

    def find_card(self, entity_id):
        self.frame(1)
        for card in self.app.ui_manager.knowledge_ui.cards:
            if card.get("entity_id") == entity_id:
                return card
        raise AssertionError(f"Card {entity_id} is not open")

    def choose_worldgen_candidate(self):
        sim = self.active_sim()
        self.click_rect(sim.formation_theory_button_rect)
        self.shot("worldgen_formation_candidates")

        self.frame(2)
        formation_prefix = "planet_" + START_SYSTEM_ID.removeprefix("system_") + "_planet_formation_"
        candidates = [
            item
            for item in getattr(sim, "planet_hitboxes", [])
            if str(item[0]).startswith(formation_prefix)
        ]
        if not candidates:
            raise AssertionError("Formation Theory did not create visible candidate planets")

        def score(item):
            entity_id, _rect = item
            entity = self.app.world_model.get_entity(entity_id) or {}
            text = " ".join(
                str(entity.get(key) or "").lower()
                for key in ("body_class", "world_gen_template", "suggested_planet_template", "planet_class")
            )
            penalty = 0
            if "gas" in text or "ice_giant" in text:
                penalty += 10
            if "planet" not in text:
                penalty += 2
            return penalty

        candidate_id, candidate_rect = sorted(candidates, key=score)[0]
        self.click_rect(candidate_rect)
        self.shot("worldgen_composition")
        return candidate_id

    def click_worldgen_primary_flow(self, selected_candidate_id):
        sim = self.active_sim()

        self.click_rect(sim.crust_random_generic_button_rect)
        self.shot("worldgen_generic_seed")
        self.click_rect(sim.crust_save_button_rect)
        self.shot("worldgen_atmosphere")

        self.click_rect(sim.crust_save_button_rect)
        self.shot("worldgen_regime")
        self.click_rect(sim.crust_save_button_rect)
        self.shot("worldgen_terrain")
        self.click_rect(sim.crust_save_button_rect)
        self.shot("worldgen_heightmap")

        guard = 0
        while getattr(sim, "editor_stage", "") == "heightmap" and guard < 8:
            self.click_rect(sim.crust_save_button_rect)
            self.shot(f"worldgen_heightmap_action_{guard + 1}")
            guard += 1

        if getattr(sim, "editor_stage", "") == "water_cycle":
            self.shot("worldgen_water_cycle")
            if sim.world_gen_complete_button_rect is not None:
                self.click_rect(sim.world_gen_complete_button_rect)
            else:
                self.click_rect(sim.crust_save_button_rect)
                self.click_rect(sim.world_gen_complete_button_rect)
        elif sim.world_gen_complete_button_rect is not None:
            self.click_rect(sim.world_gen_complete_button_rect)
        else:
            raise AssertionError(f"Could not reach completion from worldgen stage {getattr(sim, 'editor_stage', '?')}")

        self.shot("worldgen_complete")
        planet_id = getattr(sim, "selected_world_gen_planet_id", None) or selected_candidate_id
        if not planet_id:
            raise AssertionError("No selected generated planet after completion")
        return planet_id

    def open_space_and_map(self, planet_id):
        sim = self.active_sim()
        self.click_rect(sim.world_gen_space_button_rect)
        self.shot("space_completed_planet")
        space_sim = self.active_sim()
        if getattr(space_sim, "render_mode", None) != "space":
            raise AssertionError("Space Sim button did not open the space simulation")

        target_pos = None
        self.frame(2)
        for hitbox in getattr(space_sim, "body_label_hitboxes", []):
            if hitbox.get("entity_id") == planet_id:
                target_pos = hitbox["rect"].center
                break
        for entry in space_sim.system.get_entries():
            if target_pos is not None:
                break
            source = space_sim.system.get_source_entity_for_space_object(entry.get("object"))
            if isinstance(source, dict) and source.get("id") == planet_id:
                target_pos = self.app.camera.world_to_screen(entry["object"].get_position())
                break
        if target_pos is None:
            raise AssertionError(f"Generated planet {planet_id} was not visible in space")

        self.click(target_pos)
        self.shot("space_planet_selected")
        self.click_rect(self.button_rect("open_space_body_map"))
        self.shot("map_planet_root")

    def draw_polygon_with_button_finish(self, points):
        for point in points:
            self.click(point)
        self.shot("map_polygon_ready")
        self.click_rect(self.button_rect("finish_map_selection"))
        self.frame(6)

    def open_locations_menu(self):
        open_rect = self.optional_button_rect("map_open_layer_menu:locations")
        if open_rect is not None:
            self.click_rect(open_rect)

    def click_visible_button(self, button_id, shot_slug=None):
        self.click_rect(self.button_rect(button_id))
        if shot_slug:
            self.shot(shot_slug)

    def create_hierarchy_and_biosphere(self):
        # Planet -> Country
        self.open_locations_menu()
        self.shot("map_planet_locations_menu")
        self.click_visible_button("new_location:country")
        self.draw_polygon_with_button_finish([(500, 270), (760, 285), (745, 455), (490, 440)])
        country_id = self.active_sim().selected_entity_id
        self.shot("map_country_created")
        self.click_visible_button("open_region_map", "map_country_root")

        # Country -> State
        self.open_locations_menu()
        self.shot("map_country_locations_menu")
        self.click_visible_button("new_location:state")
        self.draw_polygon_with_button_finish([(545, 315), (705, 315), (700, 425), (535, 425)])
        state_id = self.active_sim().selected_entity_id
        self.shot("map_state_created")
        self.click_visible_button("open_region_map", "map_state_root")

        # State -> Biosphere patch -> Bioregion
        self.click_visible_button("new_biosphere_patch", "map_biosphere_draft")
        self.draw_polygon_with_button_finish([(585, 350), (650, 350), (655, 405), (580, 405)])
        biosphere_patch_id = self.active_sim().selected_entity_id
        self.shot("map_biosphere_patch_created")
        self.click_visible_button("create_biosphere", "bioregion_opened")
        bioregion_sim = self.active_sim()
        if getattr(bioregion_sim, "render_mode", None) != "bioregion":
            raise AssertionError("Create Biosphere did not open a bioregion simulation")
        self.shot("bioregion_final")
        return country_id, state_id, biosphere_patch_id, getattr(bioregion_sim, "year", None)

    def run(self):
        self.frame(4)
        self.open_start_card()
        candidate_id = self.choose_worldgen_candidate()
        planet_id = self.click_worldgen_primary_flow(candidate_id)
        self.open_space_and_map(planet_id)
        country_id, state_id, patch_id, year = self.create_hierarchy_and_biosphere()
        print(f"planet_id={planet_id}")
        print(f"country_id={country_id}")
        print(f"state_id={state_id}")
        print(f"biosphere_patch_id={patch_id}")
        print(f"year={year}")
        print("screenshots:")
        for path in self.shots:
            print(path)


if __name__ == "__main__":
    try:
        Walkthrough().run()
    finally:
        pygame.quit()
