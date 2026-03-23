import pygame

from engine.window import SimWindow
from engine.tab_manager import TabManager
from engine.simulation_instance import SimulationInstance
from engine.tab import Tab
from simulations.space.space_simulation import SpaceSimulation
from simulations.map.map_simulation import MapSimulation
from engine.renderer import Renderer
from engine.camera_controller import CameraController
from world.world_model import WorldModel
from ui.ui_manager import UIManager


class App(SimWindow):
    """
    Main application entry point.

    Responsibilities:
    * manage app-level menu state
    * manage tabs
    * route update / draw / input
    * bridge UI events to the active simulation
    """

    def __init__(self):
        super().__init__(
            width=1200,
            height=800,
            title="Index_0"
        )

        self.camera_controller = CameraController(
            self.camera,
            self.width,
            self.height
        )

        self.tab_manager = TabManager()
        self.world_model = WorldModel()
        self.renderer = Renderer(self)
        self.ui_manager = UIManager()

        self.menu_active = True

    def get_active_simulation(self):
        if self.menu_active:
            return None

        tab = self.tab_manager.get_active()

        if tab:
            return tab.sim_instance.simulation

        return None

    def _focus_existing_tab_by_key(self, tab_key):
        """
        Activate an already-open tab by semantic key and reset the camera.
        """
        activated = self.tab_manager.activate_tab_by_key(tab_key)
        if not activated:
            return False

        active_sim = self.get_active_simulation()
        self.camera_controller.setup_for_sim(active_sim)
        return True

    def _launch_space_root_tab(self):
        """
        Open or focus the root space simulation tab.
        """
        tab_key = ("space", "root")

        if self._focus_existing_tab_by_key(tab_key):
            self.menu_active = False
            return

        new_tab = Tab(
            SimulationInstance(SpaceSimulation(world_model=self.world_model)),
            name="System: Sol",
            tab_key=tab_key
        )

        self.tab_manager.add_tab(new_tab)
        self.tab_manager.active_index = len(self.tab_manager.tabs) - 1
        self.menu_active = False
        self.camera_controller.setup_for_sim(new_tab.sim_instance.simulation)

    def _launch_earth_map_tab(self):
        """
        Open or focus the default Earth map simulation tab.
        """
        tab_key = ("map", "planet_earth")

        if self._focus_existing_tab_by_key(tab_key):
            self.menu_active = False
            return

        from world.simulation_context import SimulationContext

        context = SimulationContext(
            year=2400,
            root_entity_id="planet_earth",
            world_model=self.world_model
        )

        new_map_sim = MapSimulation(context)
        new_tab = Tab(
            SimulationInstance(new_map_sim),
            name="Map: Earth",
            tab_key=tab_key
        )

        self.tab_manager.add_tab(new_tab)
        self.tab_manager.active_index = len(self.tab_manager.tabs) - 1
        self.menu_active = False
        self.camera_controller.setup_for_sim(new_map_sim)

    def _open_region_map_tab(self, entity_id):
        """
        Open a new map simulation tab rooted at the selected entity,
        or focus the existing one if it is already open.
        """
        if not entity_id:
            return

        entity = self.world_model.get_entity(entity_id)
        if not entity:
            return

        tab_key = ("map", entity_id)
        if self._focus_existing_tab_by_key(tab_key):
            self.menu_active = False
            return

        from world.simulation_context import SimulationContext

        active_sim = self.get_active_simulation()
        year = getattr(active_sim, "year", 2400) if active_sim is not None else 2400

        context = SimulationContext(
            year=year,
            root_entity_id=entity_id,
            world_model=self.world_model
        )

        new_map_sim = MapSimulation(context)
        new_tab = Tab(
            SimulationInstance(new_map_sim),
            name=f"Map: {entity.get('name', entity_id)}",
            tab_key=tab_key
        )

        self.tab_manager.add_tab(new_tab)
        self.tab_manager.active_index = len(self.tab_manager.tabs) - 1
        self.menu_active = False
        self.camera_controller.setup_for_sim(new_map_sim)

    def _open_parent_region_map_tab(self, map_sim):
        """
        Open the parent root of the given map simulation in a new map tab.
        """
        if map_sim is None:
            return

        if not hasattr(map_sim, "get_parent_root_entity_id"):
            return

        parent_entity_id = map_sim.get_parent_root_entity_id()
        if not parent_entity_id:
            return

        self._open_region_map_tab(parent_entity_id)

    def _open_map_for_selected_space_body(self, space_sim):
        """
        Ensure a map anchor exists for the selected space body and open it.
        """
        if space_sim is None:
            return

        if not hasattr(space_sim, "get_selected_body_entity"):
            return

        body_entity = space_sim.get_selected_body_entity()
        if not body_entity:
            return

        location_id, _created = space_sim.system.ensure_location_anchor_for_body_entity(
            body_entity,
            self.world_model
        )

        if not location_id:
            return

        self.world_model.refresh()
        self._open_region_map_tab(location_id)

    def _handle_keydown(self, event):
        """
        Handle application-level keyboard controls.
        """
        if self.menu_active:
            return

        if event.key == pygame.K_TAB:
            self.tab_manager.switch_next()

            sim = self.get_active_simulation()
            self.camera_controller.setup_for_sim(sim)

        sim = self.get_active_simulation()

        if sim:
            if event.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
                sim.sim_clock.set_time_scale(sim.sim_clock.time_scale + 0.25)

            elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                sim.sim_clock.set_time_scale(sim.sim_clock.time_scale - 0.25)

            elif event.key == pygame.K_0:
                sim.sim_clock.set_time_scale(1.0)

            elif event.key == pygame.K_SPACE:
                sim.sim_clock.toggle_pause()

    def _handle_ui_action(self, action_id, active_sim):
        """
        Route UI button actions for either the main menu or the active simulation.
        """
        if action_id == "launch_space_root":
            self._launch_space_root_tab()
            return True

        elif action_id == "launch_earth_map":
            self._launch_earth_map_tab()
            return True

        if action_id == "open_region_map" and active_sim is not None:
            selected_entity_id = getattr(active_sim, "selected_entity_id", None)
            self._open_region_map_tab(selected_entity_id)
            return True

        elif action_id == "open_parent_region_map" and active_sim is not None:
            self._open_parent_region_map_tab(active_sim)
            return True

        elif action_id == "open_space_body_map" and active_sim is not None:
            self._open_map_for_selected_space_body(active_sim)
            return True

        return False

    def _handle_middle_click_reset(self, event, active_sim):
        """
        Reset camera view for the active simulation on middle click.
        """
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 2:
            if active_sim is not None:
                self.camera_controller.setup_for_sim(active_sim)
            return True

        return False

    def _handle_pointer_input(self, event, active_sim):
        """
        Forward pointer motion and left-click events to the active simulation.
        """
        if active_sim and hasattr(active_sim, "handle_pointer_motion"):
            if event.type == pygame.MOUSEMOTION:
                active_sim.handle_pointer_motion(
                    event=event,
                    camera=self.camera,
                    screen_pos=event.pos
                )

        if active_sim and hasattr(active_sim, "handle_pointer_event"):
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                active_sim.handle_pointer_event(
                    event=event,
                    camera=self.camera,
                    screen_pos=event.pos
                )

    def update(self, dt):
        if self.menu_active:
            return

        self.tab_manager.update(dt)

        sim = self.get_active_simulation()
        self.camera_controller.apply_constraints(sim)

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            self._handle_keydown(event)

        active_sim = self.get_active_simulation()

        self.ui_manager.rebuild_for_state(
            active_sim,
            self.width,
            self.height,
            tab_manager=self.tab_manager,
            camera=self.camera,
            menu_active=self.menu_active
        )

        action_id = self.ui_manager.handle_event(event)
        if action_id is not None:
            handled = self._handle_ui_action(action_id, active_sim)
            if handled:
                return

        if self.menu_active:
            return

        self.tab_manager.handle_event(event)

        active_sim = self.get_active_simulation()

        if self._handle_middle_click_reset(event, active_sim):
            return

        self._handle_pointer_input(event, active_sim)

    def draw(self):
        super().draw_background()

        active_sim = self.get_active_simulation()
        self.ui_manager.rebuild_for_state(
            active_sim,
            self.width,
            self.height,
            tab_manager=self.tab_manager,
            camera=self.camera,
            menu_active=self.menu_active
        )

        if active_sim:
            self.renderer.simulation = active_sim
            self.renderer.draw(self.screen)

        self.ui_manager.draw(self.screen, self.default_font)


def main():
    app = App()
    app.run()


if __name__ == "__main__":
    main()